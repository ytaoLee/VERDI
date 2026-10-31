"""Small generated-data protocol check, not a paper experiment."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'): os.environ[key]='2'
import json, multiprocessing as mp
import numpy as np
from verdi import FlatOwner, RetrievalClient, Transport, fixed, oracle, ImageCodec, bind_image, recover_image
from verdi.api import authenticated_slots

def main():
    rng=np.random.default_rng(19); x=fixed(rng.normal(size=(96,32))); train=fixed(rng.normal(size=(24,32)))
    owner=FlatOwner(dict(enumerate(x)),train)
    codec=ImageCodec()
    pixels={i:np.full((32,32,3),i,dtype=np.uint8) for i in range(len(x))}
    images={i:bind_image(owner,codec,i,rgb,force_sidecar=bool(i%2)) for i,rgb in pixels.items()}
    snapshot=owner.publish(); t=Transport(owner.store,network=True)
    try:
        client=RetrievalClient(owner,t,snapshot)
        prefix,stats,certificate=client.search(x[0],k=11,mode='flat_fine',batch=16)
        top=[pair for pair in prefix if pair[1]!=0][:10]
        expected=[pair for pair in oracle(owner.features,x[0],11) if pair[1]!=0][:10]
        assert top==expected
        slots=authenticated_slots(client,certificate)
        for _,i in top:
            assert np.array_equal(recover_image(codec,images[i],slots[i],client.state),pixels[i])
        print(json.dumps({'smoke_check_passed':True,'neighbors':[i for _,i in top],
                          'layout':client.state['layout'],'configuration':'Flat + fine','rgb_recovered':len(top),
                          'application_bytes':stats['bytes'],'rounds':stats['rounds'],
                          'scope':'Generated fixture, local image objects; not a paper benchmark or image-delivery timing'},indent=2))
    finally:t.close()

if __name__=='__main__':mp.freeze_support();mp.set_start_method('spawn',force=True);main()
