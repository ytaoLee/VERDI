"""Genuine image-to-image leave-one-out evaluation of unchanged VERDI crypto.

Queries use saved image FP32 features, never caption features. Authentication
audits k+1 neighbors over the whole committed gallery; remove the query ID
locally and retain k. This exact rule is applied to every internal ablation.
"""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='2'
import argparse,gc,json,multiprocessing as mp,sys,time,traceback
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
from verdi.owner import ConfiguredOwner, binding
MODES=('full','fine_only','coarse_only','scan','flat_fine','flat_scan')
from verdi.retrieval import ExperimentClient,Transport,flat_snapshot,fixed,oracle,summarize,reachable
from verdi.common import save,digest,runtime
from verdi.cache import load_cache, paper_inputs

def measure(owner,snaps,x,ids,specs,repeats,output,config):
    output.mkdir(parents=True,exist_ok=True)
    ident={'config':config,'specs':specs,'query_image_ids':ids,'repeats':repeats}
    if (output/'config.json').exists():assert json.loads((output/'config.json').read_text(encoding='utf-8'))==ident
    save(output/'config.json',ident)
    truth={(qi,s['k']):oracle(owner.tree.features,x[qi],s['k']+1) for qi in ids for s in specs.values()}
    save(output/'oracles.json',[{'query':qi,'returned_k':k,'protocol_top':top,'neighbor_top':[(s,i) for s,i in top if i!=qi][:k]} for (qi,k),top in truth.items()])
    journal=output/'queries.jsonl';rows={m:[] for m in specs};done=set()
    if journal.exists():
        raw=journal.read_bytes();lines=raw.splitlines(keepends=True)
        if lines and not lines[-1].endswith(b'\n'):
            save(output/'incomplete_tail.json',{'hex':lines[-1].hex()});lines.pop();journal.write_bytes(b''.join(lines))
        for line in lines:
            r=json.loads(line);assert r['exact'];key=(r['method'],r['query'],r['repeat']);assert key not in done;done.add(key);rows[r['method']].append(r)
    total=len(ids)*len(specs)*repeats
    if len(done)==total:return {m:summarize(rr) for m,rr in rows.items()}
    transport=Transport(owner.store,network=True)
    try:
        for m,spec in specs.items():
            for qi in ids[:2]:
                top,_,_=ExperimentClient(owner,transport,snaps['flat' if spec['mode'].startswith('flat') else 'tree']).search(x[qi],mode=spec['mode'],k=spec['k']+1,batch=spec['batch'])
                assert top==truth[(qi,spec['k'])]
        rng=np.random.default_rng(20261009)
        with open(journal,'a',encoding='utf-8') as f:
            for repeat in range(repeats):
                for qi in rng.permutation(ids):
                    qi=int(qi)
                    for m in rng.permutation(list(specs)):
                        m=str(m)
                        if (m,qi,repeat) in done:continue
                        spec=specs[m];k=spec['k']
                        top,stats,_=ExperimentClient(owner,transport,snaps['flat' if spec['mode'].startswith('flat') else 'tree']).search(x[qi],mode=spec['mode'],k=k+1,batch=spec['batch'])
                        assert top==truth[(qi,k)],(m,qi)
                        neighbors=[(score,i) for score,i in top if i!=qi][:k];assert len(neighbors)==k
                        row={'method':m,'query':qi,'repeat':repeat,'exact':True,'task':'image-to-image leave-one-out',
                             'top_ids':[i for _,i in top],'integer_scores':[s for s,_ in top],
                             'neighbor_ids':[i for _,i in neighbors],'neighbor_scores':[s for s,_ in neighbors],**stats}
                        f.write(json.dumps(row)+'\n');f.flush();done.add((m,qi,repeat));rows[m].append(row)
                        if len(done)%30==0:print(output.name,len(done),'/',total,flush=True)
    except Exception:
        with open(output/'failures.jsonl','a',encoding='utf-8') as f:f.write(json.dumps({'traceback':traceback.format_exc()})+'\n')
        raise
    finally:transport.close()
    summaries={m:summarize(rr) for m,rr in rows.items()};save(output/'summary.json',summaries);return summaries

def quality(folder,output,meta):
    images=np.load(folder/'gallery.npy',mmap_mode='r')[:meta['test_images']]
    xf=fixed(images);floating=np.asarray(images,np.float64)
    journal=output/'image_quality.jsonl';rows=[]
    if journal.exists():rows=[json.loads(l) for l in journal.read_text(encoding='utf-8').splitlines()]
    with open(journal,'a',encoding='utf-8') as f:
        for qi in range(len(rows),len(images)):
            si=xf@xf[qi];sf=floating@floating[qi]
            ii=[int(i) for i in np.argsort(-si,kind='stable') if i!=qi][:10]
            ff=[int(i) for i in np.argsort(-sf,kind='stable') if i!=qi][:10]
            r={'query_image_id':qi,'integer_neighbors':ii,'float_neighbors':ff,
               'ordered_agreement':{str(k):ii[:k]==ff[:k] for k in (1,5,10)},
               'set_recall':{str(k):len(set(ii[:k])&set(ff[:k]))/k for k in (1,5,10)}}
            f.write(json.dumps(r)+'\n');f.flush();rows.append(r)
            if (qi+1)%500==0:print('I2I quality',qi+1,'/',len(images),flush=True)
    result={'dataset':meta['dataset'],'gallery_size':len(images),'query_images':len(rows),'task':'leave-one-out nearest-neighbor fidelity; no semantic relevance annotations',
            'ordered_agreement_percent':{str(k):100*np.mean([r['ordered_agreement'][str(k)] for r in rows]) for k in (1,5,10)},
            'float_set_recall_percent':{str(k):100*np.mean([r['set_recall'][str(k)] for r in rows]) for k in (1,5,10)}}
    save(output/'image_quality_summary.json',result)

def run(a):
    output=Path(a.output);output.mkdir(parents=True,exist_ok=True)
    all_exp=paper_inputs()
    for ds in a.datasets:
        exp=all_exp[ds];folder=Path(a.cache_root)/ds;out=output/ds;out.mkdir(exist_ok=True)
        for n,h in exp['files_sha256'].items():assert digest(folder/n)==h
        meta=json.loads((folder/'features_complete.json').read_text(encoding='utf-8'));x=fixed(np.load(folder/'gallery.npy',mmap_mode='r'));training=fixed(np.load(folder/'calibration.npy'))
        ids=exp['target_image_indices'][:a.queries]
        config={'task':'image-to-image leave-one-out','dataset':ds,'query_image_ids':ids,'seed':20261009,'formal_hashes':exp['files_sha256'],'runtime':runtime(),'source_sha256':digest(Path(__file__))}
        # Runtime metadata is preserved separately, not used as a resume identity.
        save(out/'environment.json',config.pop('runtime'))
        scales=[1000,5000,10000,50000 if ds=='coco' else 25000] if not a.pilot else [1000]
        result={'task':'image-to-image leave-one-out','queries':len(ids),'repeats':a.repeats,'scales':{}}
        for n in scales:
            t=time.perf_counter();owner=ConfiguredOwner(dict(enumerate(x[:n])),training,**binding(meta));build=time.perf_counter()-t
            t=time.perf_counter();tree=owner.publish();publish=time.perf_counter()-t;flat=flat_snapshot(owner,tree)
            print(ds,'encrypted gallery',n,'built',round(build,2),'s',flush=True)
            specs={m:{'mode':m,'k':10,'batch':16} for m in MODES}
            summary=measure(owner,{'tree':tree,'flat':flat},x,ids,specs,a.repeats,out/f'scale_{n}',config)
            storage={}
            for name,snap in [('tree',tree),('flat',flat)]:
                rr=reachable(owner,snap);storage[name]={'reachable_objects':len(rr),'raw_payload_bytes':sum(len(owner.store[h]) for h in rr)}
            result['scales'][str(n)]={'methods':summary,'storage':storage,'tree_build_seconds':build,'tree_publication_seconds':publish}
            save(out/'retrieval_summary.json',result);del owner;gc.collect()
        if not a.pilot:
            for parameter,value in [('bits',v) for v in (4,6,8)]+[('capacity',v) for v in (8,16,32)]+[('batch',v) for v in (1,4,16,64)]+[('k',v) for v in (1,5,10,50)]:
                conf={'bits':6,'capacity':16,'batch':16,'k':10,parameter:value}
                owner=ConfiguredOwner(dict(enumerate(x[:10000])),training,conf['capacity'],conf['bits'],**binding(meta));tree=owner.publish();flat=flat_snapshot(owner,tree)
                specs={m:{'mode':m,'k':conf['k'],'batch':conf['batch']} for m in ('full','flat_fine')}
                measure(owner,{'tree':tree,'flat':flat},x,ids,specs,a.repeats,out/f'sweep_{parameter}_{value}',{**config,'sweep':conf,'n':10000})
                del owner;gc.collect()
            quality(folder,out,meta)
    save(output/'complete.json',{'passed':True,'task':'image-to-image','datasets':a.datasets})

if __name__=='__main__':
    mp.freeze_support();mp.set_start_method('spawn',force=True)
    p=argparse.ArgumentParser();p.add_argument('--cache-root',required=True);p.add_argument('--datasets',nargs='+',choices=['coco','flickr30k'],default=['coco','flickr30k']);p.add_argument('--output',required=True);p.add_argument('--queries',type=int,default=30);p.add_argument('--repeats',type=int,default=3);p.add_argument('--pilot',action='store_true');run(p.parse_args())
