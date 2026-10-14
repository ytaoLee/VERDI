"""Actual framed TCP relay: delays and rate-limits bytes before forwarding.

This is application-layer link emulation, not kernel tc, cellular data or
post-hoc bytes/bandwidth latency estimation. Both directions are independently
paced. Original encrypted objects and request/response framing are unchanged.
"""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'): os.environ[k]='1'
import argparse, gc, hashlib, json, multiprocessing as mp, socket, struct, sys, threading, time, traceback
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import psutil

ROOT=Path(__file__).resolve().parents[1]
from verdi.owner import ConfiguredOwner, binding
from verdi.retrieval import ExperimentClient, flat_snapshot, fixed, oracle
from verdi.protocol import Transport, recv_exact, sha
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from verdi.common import save, digest
from verdi.cache import paper_inputs

PROFILES=[{'name':'local_2cpu','cpus':2,'mbps':None,'rtt_ms':0},
          {'name':'local_1cpu','cpus':1,'mbps':None,'rtt_ms':0}]+[
          {'name':f'link_{bw}M_{rtt}ms_1cpu','cpus':1,'mbps':bw,'rtt_ms':rtt}
          for bw in (50,200) for rtt in (2,10)]
MODES=('full','flat_fine','flat_scan')

def stamp(): return datetime.now(timezone.utc).isoformat()
def listen():
    s=socket.socket();s.bind(('127.0.0.1',0));s.listen(4);return s
def connect(port):
    s=socket.create_connection(('127.0.0.1',port));s.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);return s
def frame_recv(s):
    head=recv_exact(s,4);n,=struct.unpack('>I',head);return head+recv_exact(s,n)
def paced_send(s, data, mbps, delay):
    # Actual bytes remain buffered until their scheduled forwarding time.
    start=time.perf_counter()+delay
    rate=mbps*1e6/8
    sent=0
    for offset in range(0,len(data),16384):
        chunk=data[offset:offset+16384];sent+=len(chunk)
        due=start+sent/rate
        wait=due-time.perf_counter()
        if wait>0:time.sleep(wait)
        s.sendall(chunk)

def relay_main(upstream, profile, ready):
    srv=listen();ready.send(srv.getsockname()[1]);ready.close()
    client,_=srv.accept();client.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
    remote=connect(upstream)
    def pump(src,dst):
        try:
            while True: paced_send(dst,frame_recv(src),profile['mbps'],profile['rtt_ms']/2000)
        except (EOFError,ConnectionError,OSError,AssertionError):
            try:dst.shutdown(socket.SHUT_WR)
            except OSError:pass
    a=threading.Thread(target=pump,args=(client,remote));b=threading.Thread(target=pump,args=(remote,client))
    a.start();b.start();a.join();b.join();client.close();remote.close();srv.close()

def store_server(store, ready, stop):
    srv=listen();srv.settimeout(.5);ready.send(srv.getsockname()[1]);ready.close()
    while not stop.is_set():
        try:conn,_=srv.accept()
        except socket.timeout:continue
        conn.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        try:
            while True:
                raw=frame_recv(conn)[4:]
                if raw==b'X':break
                count,=struct.unpack('>I',raw[:4]);assert len(raw)==4+count*32
                objects=[store[raw[i:i+32]] for i in range(4,len(raw),32)]
                response=struct.pack('>I',count)+b''.join(struct.pack('>I',len(o))+o for o in objects)
                conn.sendall(struct.pack('>I',len(response))+response)
        except (EOFError,ConnectionError,AssertionError):pass
        finally:conn.close()
    srv.close()

class MeasuredTransport(Transport):
    def __init__(self,port):
        self.store=None;self.network=True;self.process=None;self.sock=connect(port);self.reset()
    def reset(self):
        super().reset();self.upload_bytes=0;self.download_bytes=0;self.network_wait_seconds=0
    def fetch(self,hashes,kind):
        if not hashes:return []
        before=time.perf_counter();objects=super().fetch(hashes,kind)
        self.network_wait_seconds+=time.perf_counter()-before
        self.upload_bytes+=8+32*len(hashes)
        self.download_bytes+=8+sum(4+len(o) for o in objects)
        assert self.bytes==self.upload_bytes+self.download_bytes
        return objects
    def close(self):
        self.sock.sendall(struct.pack('>I',1)+b'X');self.sock.shutdown(socket.SHUT_WR);self.sock.close()

class InstrumentedClient(ExperimentClient):
    def __init__(self,*args):super().__init__(*args);self.decrypt_cpu=0;self.decrypt_calls=0
    def decrypt(self,*args):
        t=time.process_time();v=super().decrypt(*args);self.decrypt_cpu+=time.process_time()-t;self.decrypt_calls+=1;return v

def probe_server(ready):
    srv=listen();ready.send(srv.getsockname()[1]);ready.close();c,_=srv.accept()
    c.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
    try:
        while True:
            raw=frame_recv(c)
            if raw[4:]==b'X':break
            if raw[4:5]==b'D':
                n,=struct.unpack('>I',raw[5:9]);c.sendall(struct.pack('>I',n)+b'Z'*n)
            elif raw[4:5]==b'U':c.sendall(struct.pack('>I',1)+b'K')
            else:c.sendall(raw)
    finally:c.close();srv.close()

def start_relay(upstream,profile):
    a,b=mp.Pipe(False);p=mp.Process(target=relay_main,args=(upstream,profile,b));p.start();port=a.recv();a.close();return p,port

def calibration(profile, output):
    a,b=mp.Pipe(False);p=mp.Process(target=probe_server,args=(b,));p.start();up=a.recv();a.close()
    relay,port=start_relay(up,profile);s=connect(port)
    rtts=[]
    for i in range(22):
        t=time.perf_counter();s.sendall(struct.pack('>I',1)+b'P');assert frame_recv(s)[4:]==b'P'
        if i>=2:rtts.append((time.perf_counter()-t)*1000)
    trials=[];n=16*1024*1024
    for direction in ('download','upload'):
        for repeat in range(3):
            t=time.perf_counter()
            if direction=='download':
                s.sendall(struct.pack('>I',5)+b'D'+struct.pack('>I',n));resp=frame_recv(s);assert resp[4:]==b'Z'*n
            else:
                s.sendall(struct.pack('>I',n+1)+b'U'+b'Z'*n);assert frame_recv(s)[4:]==b'K'
            elapsed=time.perf_counter()-t
            # Raw observed transfer time, without subtracting the latency.
            trials.append({'direction':direction,'repeat':repeat,'payload_bytes':n,'seconds':elapsed,'observed_mbps':n*8/elapsed/1e6})
    s.sendall(struct.pack('>I',1)+b'X');s.shutdown(socket.SHUT_WR);s.close();relay.join(20);p.join(20)
    assert relay.exitcode==0 and p.exitcode==0
    med=float(np.median(rtts));rates=[x['observed_mbps'] for x in trials]
    passed=profile['rtt_ms']<=med<=profile['rtt_ms']+max(2,.25*profile['rtt_ms']) and all(.8*profile['mbps']<=x<=1.03*profile['mbps'] for x in rates)
    result={'profile':profile,'utc':stamp(),'rtt_ms_raw':rtts,'rtt_median_ms':med,'throughput_trials':trials,'passed':passed,
            'scope':'Independent real TCP ping and bidirectional 16 MiB transfers through paced frame relay; no latency subtraction.'}
    save(output,result);assert passed,result
    print('Link calibrated',profile['name'],'RTT',round(med,3),'ms; rate range',round(min(rates),2),round(max(rates),2),flush=True)

def worker(port,profile,keys,public,snapshots,queries,truth,floattruth,output,repeats):
    proc=psutil.Process();available=proc.cpu_affinity();affinity=available[:profile['cpus']];proc.cpu_affinity(affinity)
    owner=SimpleNamespace(keys=keys,signing=SimpleNamespace(public_key=lambda:Ed25519PublicKey.from_public_bytes(public)))
    trans=MeasuredTransport(port);journal=output/'queries.jsonl'
    done=set()
    if journal.exists():
        raw=journal.read_bytes();lines=raw.splitlines(keepends=True)
        if lines and not lines[-1].endswith(b'\n'):
            save(output/'incomplete_tail.json',{'utc':stamp(),'tail_hex':lines[-1].hex()});lines.pop();journal.write_bytes(b''.join(lines))
        for l in lines:
            r=json.loads(l);assert r['exact'];key=(r['method'],r['query'],r['repeat']);assert key not in done;done.add(key)
    peak=[proc.memory_info().rss];running=threading.Event();running.set()
    def monitor():
        while running.is_set():peak[0]=max(peak[0],proc.memory_info().rss);time.sleep(.005)
    sampler=threading.Thread(target=monitor,daemon=True);sampler.start()
    try:
        for mode in MODES:
            for qi in list(queries)[:2]:
                c=InstrumentedClient(owner,trans,snapshots['tree' if mode=='full' else 'flat'])
                top,_,_=c.search(queries[qi],mode=mode,k=11);assert top==truth[qi]
        rng=np.random.default_rng(20261009)
        with open(journal,'a',encoding='utf-8') as f:
            for repeat in range(repeats):
                for qi in rng.permutation(list(queries)):
                    qi=int(qi)
                    for mode in rng.permutation(MODES):
                        mode=str(mode)
                        if (mode,qi,repeat) in done:continue
                        gc.collect();peak[0]=proc.memory_info().rss;base=peak[0]
                        c=InstrumentedClient(owner,trans,snapshots['tree' if mode=='full' else 'flat'])
                        top,stats,transcript=c.search(queries[qi],mode=mode,k=11)
                        assert top==truth[qi],(mode,qi)
                        neighbors=[(s,i) for s,i in top if i!=qi][:10]
                        assert len(neighbors)==10 and any(i==qi for _,i in top)
                        rr={'utc':stamp(),'profile':profile['name'],'method':mode,'query':qi,'repeat':repeat,'exact':True,
                            'top_ids':[i for _,i in top],'integer_scores':[s for s,_ in top],
                            'neighbor_ids':[i for _,i in neighbors],'neighbor_scores':[s for s,_ in neighbors],
                            'float_set_recall10':len(set(i for _,i in neighbors)&set(floattruth[qi]))/10,
                            'upload_bytes':trans.upload_bytes,'download_bytes':trans.download_bytes,
                            'network_wait_seconds':trans.network_wait_seconds,'decrypt_cpu_seconds':c.decrypt_cpu,
                            'decrypt_calls':c.decrypt_calls,'rss_before_bytes':base,'peak_rss_sampled_bytes':max(peak[0],proc.memory_info().rss),
                            'cpu_affinity':proc.cpu_affinity(),**stats}
                        f.write(json.dumps(rr)+'\n');f.flush();done.add((mode,qi,repeat))
                        del transcript,c
                        if len(done)%15==0:print(profile['name'],len(done),'/',len(queries)*len(MODES)*repeats,flush=True)
    except Exception:
        with open(output/'failures.jsonl','a',encoding='utf-8') as f:f.write(json.dumps({'utc':stamp(),'traceback':traceback.format_exc()})+'\n')
        raise
    finally:running.clear();sampler.join();trans.close()

def run(args):
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    expected=paper_inputs()['coco']
    folder=Path(args.features)
    for name,h in expected['files_sha256'].items():assert digest(folder/name)==h
    meta=json.loads((folder/'features_complete.json').read_text(encoding='utf-8'))
    ids=expected['target_image_indices'][:args.queries]
    xf=np.load(folder/'gallery.npy',mmap_mode='r')[:args.n];training=fixed(np.load(folder/'calibration.npy'))
    x=fixed(xf);q=x[ids]
    config={'dataset':'coco','task':'image-to-image leave-one-out','n':args.n,'image_query_ids':ids,'repeats':args.repeats,'modes':MODES,'profiles':[p for p in PROFILES if args.profiles is None or p['name'] in args.profiles],
            'bits':6,'capacity':16,'batch':16,'protocol_k':11,'returned_neighbors':10,'seed':20261009,'hashes':expected['files_sha256'],
            'scope':'Desktop CPU affinity emulation; independently paced TCP frame relay; empty client object cache; original encrypted protocol and full coverage audit.',
            'source_sha256':{str(p.relative_to(ROOT)):digest(p) for p in list((ROOT/'src/verdi').rglob('*.py'))+[Path(__file__)] if '__pycache__' not in p.parts}}
    if (output/'config.json').exists():assert json.loads((output/'config.json').read_text(encoding='utf-8'))==json.loads(json.dumps(config)),'Changed configuration; use a new directory'
    save(output/'config.json',config)
    save(output/'environment.json',{'utc':stamp(),'python':sys.version,'numpy':np.__version__,'cpu_affinity':psutil.Process().cpu_affinity(),'ram':psutil.virtual_memory()._asdict(),'env_threads':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')},'pid':os.getpid()})
    t=time.perf_counter();owner=ConfiguredOwner(dict(enumerate(x)),training,**binding(meta));tree=owner.publish();flat=flat_snapshot(owner,tree)
    queries=dict(zip(ids,q));truth={qi:oracle(owner.tree.features,v,11) for qi,v in queries.items()}
    # Public floating reference accumulated in float64, ascending ID ties.
    floattruth={qi:[int(i) for i in np.argsort(-(np.asarray(xf,np.float64)@np.asarray(xf[qi],np.float64)),kind='stable') if i!=qi][:10] for qi in ids}
    save(output/'oracles.json',{'integer':{str(qi):{'ids':[i for _,i in top],'scores':[s for s,_ in top]} for qi,top in truth.items()},'float64_from_fp32':floattruth})
    save(output/'build.json',{'build_publish_oracles_seconds':time.perf_counter()-t,'objects':len(owner.store),'object_payload_bytes':sum(map(len,owner.store.values())),'snapshot_digests':{'tree':tree.hex(),'flat':flat.hex()}})
    print('Built real encrypted gallery',args.n,'objects',len(owner.store),flush=True)
    a,b=mp.Pipe(False);stop=mp.Event();server=mp.Process(target=store_server,args=(owner.store,b,stop));server.start();port=a.recv();a.close()
    try:
        for profile in [p for p in PROFILES if args.profiles is None or p['name'] in args.profiles]:
            directory=output/profile['name'];directory.mkdir(exist_ok=True)
            total=len(ids)*args.repeats*len(MODES)
            if (directory/'complete.json').exists():
                assert json.loads((directory/'complete.json').read_text(encoding='utf-8'))['passed']
                if profile['mbps']:
                    for suffix in ('before','after'):
                        assert json.loads((directory/f'calibration_{suffix}.json').read_text(encoding='utf-8'))['passed']
                continue
            relay=None;endpoint=port
            if profile['mbps']:
                calibration(profile,directory/'calibration_before.json');relay,endpoint=start_relay(port,profile)
            pub=owner.signing.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
            client=mp.Process(target=worker,args=(endpoint,profile,owner.keys,pub,{'tree':tree,'flat':flat},queries,truth,floattruth,directory,args.repeats));client.start();client.join()
            assert client.exitcode==0,profile
            if relay:relay.join(20);assert relay.exitcode==0;calibration(profile,directory/'calibration_after.json')
            save(directory/'complete.json',{'utc':stamp(),'records':total,'passed':True})
        save(output/'complete.json',{'utc':stamp(),'passed':True,'records':len(ids)*args.repeats*len(MODES)*len(config['profiles'])})
    finally:stop.set();server.join(10);assert server.exitcode==0

if __name__=='__main__':
    mp.freeze_support();mp.set_start_method('spawn',force=True)
    p=argparse.ArgumentParser();p.add_argument('--features',required=True);p.add_argument('--profiles',nargs='+',choices=[p['name'] for p in PROFILES]);p.add_argument('--n',type=int,default=10000);p.add_argument('--queries',type=int,default=30);p.add_argument('--repeats',type=int,default=3);p.add_argument('--output',required=True)
    run(p.parse_args())
