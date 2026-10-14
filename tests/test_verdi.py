import copy
import multiprocessing as mp
import unittest
import numpy as np
from verdi import Owner, FlatOwner, RetrievalClient, Transport, fixed, oracle, flat_snapshot, image_search, ImageCodec, bind_image, recover_image
from verdi.api import authenticated_slots
from verdi.retrieval import BitQuantizer
from verdi.protocol import sha

class VerdiTests(unittest.TestCase):
    def setUp(self):
        rng=np.random.default_rng(41)
        self.x=fixed(rng.normal(size=(72,24)));self.train=fixed(rng.normal(size=(18,24)))
        self.owner=Owner(dict(enumerate(self.x)),self.train,capacity=8)
        self.snap=self.owner.publish()

    def test_all_internal_modes_match_integer_oracle(self):
        flat=flat_snapshot(self.owner,self.snap)
        for mode in ('full','fine_only','coarse_only','scan','flat_fine','flat_scan'):
            for qi in (0,3):
                with self.subTest(mode=mode,qi=qi):
                    snap=flat if mode.startswith('flat') else self.snap
                    result,_,_=image_search(self.owner,Transport(self.owner.store),snap,self.x[qi],query_id=qi,k=10,mode=mode)
                    truth=[p for p in oracle(self.owner.tree.features,self.x[qi],11) if p[1]!=qi][:10]
                    self.assertEqual(result,truth)

    def test_tcp_frames_and_complete_verification(self):
        transport=Transport(self.owner.store,network=True)
        try:
            top,stats,_=RetrievalClient(self.owner,transport,self.snap).search(self.x[0],k=11)
            self.assertEqual(top,oracle(self.owner.tree.features,self.x[0],11))
            self.assertEqual(stats['bytes'],sum(stats['parts'].values()))
            self.assertGreater(stats['rounds'],0)
        finally:transport.close()

    def test_missing_coverage_and_forged_scores_rejected(self):
        for mode in ('full','fine_only','coarse_only','scan','flat_fine','flat_scan'):
            snap=flat_snapshot(self.owner,self.snap) if mode.startswith('flat') else self.snap
            c=RetrievalClient(self.owner,Transport(self.owner.store),snap);_,_,cert=c.search(self.x[0],k=11,mode=mode)
            bad=copy.deepcopy(cert);s,i=bad['top'][0];bad['top'][0]=(s+1,i)
            with self.assertRaises(Exception):c.verify(self.x[0],11,bad)
            bad=copy.deepcopy(cert);bad['done'].remove(next(iter(bad['done'])))
            with self.assertRaises(Exception):c.verify(self.x[0],11,bad)

    def test_modified_ciphertext_rejected(self):
        store=dict(self.owner.store);h=self.owner.records[0][2];raw=bytearray(store[h]);raw[-1]^=1;store[h]=bytes(raw)
        with self.assertRaises(Exception):RetrievalClient(self.owner,Transport(store),self.snap).search(self.x[0],k=11,mode='scan')

    def test_updates_keep_survivors_and_exactness(self):
        for cls,mode in ((Owner,'full'),(FlatOwner,'flat_fine')):
            owner=cls(dict(enumerate(self.x[:48])),self.train,capacity=8);old=owner.publish();records=dict(owner.records)
            for step in range(12):
                i=48+step//2
                owner.insert(i,self.x[i]) if step%2==0 else owner.delete(i)
                snapshot=owner.publish();self.assertNotEqual(snapshot,old);old=snapshot
                features=owner.tree.features if mode=='full' else owner.features
                self.assertTrue(all(owner.records[j]==records[j] for j in records))
                top,_,_=RetrievalClient(owner,Transport(owner.store),snapshot).search(self.x[0],k=11,mode=mode)
                self.assertEqual(top,oracle(features,self.x[0],11))
                if mode=='full':owner.tree.check()

    def test_quantization_clipping_error_is_conservative(self):
        for bits in (4,6,8):
            quant=BitQuantizer.fit(self.train,bits);restored=BitQuantizer.from_bytes(quant.bytes())
            for row in (self.x[0],np.full(24,32767,dtype=np.int64),np.full(24,-32767,dtype=np.int64)):
                center,error=restored.decode(quant.encode(row));diff=row-center
                self.assertGreaterEqual(error*error,int(diff@diff))

    def test_zero_negative_and_ties_leave_one_out(self):
        values=np.array([[10,0],[10,0],[10,0],[-10,0],[0,10],[0,-10]],dtype=np.int64)
        owner=Owner(dict(enumerate(values)),values,capacity=2);snap=owner.publish()
        for qi in (0,3):
            result,_,_=image_search(owner,Transport(owner.store),snap,values[qi],query_id=qi,k=4)
            self.assertEqual(result,[p for p in oracle(owner.tree.features,values[qi],5) if p[1]!=qi][:4])

    def test_snapshot_substitution_rejected(self):
        self.owner.insert(99,self.x[0]);new=self.owner.publish();store=dict(self.owner.store);store[self.snap]=store[new]
        with self.assertRaises(Exception):RetrievalClient(self.owner,Transport(store),self.snap).search(self.x[0],k=11)

    def test_image_binding_rgb_and_both_formats(self):
        codec=ImageCodec();rng=np.random.default_rng(7)
        for i,pixels,mode in ((0,np.zeros((70,73,3),dtype=np.uint8),'embed'),(1,rng.integers(0,256,(70,73,3),dtype=np.uint8),'sidecar')):
            obj=bind_image(self.owner,codec,i,pixels);self.assertEqual(obj['mode'],mode)
            snap=self.owner.publish();client=RetrievalClient(self.owner,Transport(self.owner.store),snap)
            _,_,cert=client.search(self.x[i],k=11,mode='fine_only');slot=authenticated_slots(client,cert)[i]
            self.assertTrue(np.array_equal(recover_image(codec,obj,slot,client.state),pixels))
            other=self.owner.records[1-i]
            with self.assertRaises(Exception):recover_image(codec,obj,other,client.state)
            bad=copy.deepcopy(obj);b=bytearray(bad['meta']);b[-1]^=1;bad['meta']=bytes(b)
            with self.assertRaises(Exception):recover_image(codec,bad,slot,client.state)

    def test_region_tamper_is_diagnosed_without_release(self):
        codec=ImageCodec();obj=bind_image(self.owner,codec,0,np.zeros((128,128,3),dtype=np.uint8))
        bad=copy.deepcopy(obj);b=bytearray(bad['tiles'][1]);b[0]^=1;bad['tiles'][1]=bytes(b)
        accepted,status,pixels=codec.decode(bad,obj['context'],obj['expected'])
        self.assertFalse(accepted);self.assertIsNone(pixels);self.assertEqual(status[1],'tampered')
        self.assertTrue(all(s=='valid' for j,s in enumerate(status) if j!=1))

if __name__=='__main__':mp.freeze_support();mp.set_start_method('spawn',force=True);unittest.main()
