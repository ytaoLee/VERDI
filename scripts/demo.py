"""Small generated-data protocol check, not a paper experiment."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'): os.environ[key]='2'
import json, multiprocessing as mp
import numpy as np
from verdi import Owner, Transport, fixed, oracle, image_search

def main():
    rng=np.random.default_rng(19); x=fixed(rng.normal(size=(96,32))); train=fixed(rng.normal(size=(24,32)))
    owner=Owner(dict(enumerate(x)),train); snapshot=owner.publish(); t=Transport(owner.store,network=True)
    try:
        top,stats,_=image_search(owner,t,snapshot,x[0],query_id=0,k=10)
        expected=[pair for pair in oracle(owner.tree.features,x[0],11) if pair[1]!=0][:10]
        assert top==expected
        print(json.dumps({'smoke_check_passed':True,'neighbors':[i for _,i in top],
                          'application_bytes':stats['bytes'],'rounds':stats['rounds'],
                          'scope':'Generated fixture; not a paper benchmark result'},indent=2))
    finally:t.close()

if __name__=='__main__':mp.freeze_support();mp.set_start_method('spawn',force=True);main()
