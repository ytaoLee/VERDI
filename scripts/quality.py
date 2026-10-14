"""Leave-one-out integer/float nearest-neighbor fidelity, not semantic recall."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'): os.environ[key]='2'
import argparse, json
from pathlib import Path
from benchmark import quality
from verdi.cache import load_cache

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--features',required=True); p.add_argument('--output',required=True)
    a=p.parse_args(); folder=Path(a.features); out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    meta,_,_=load_cache(folder); quality(folder,out,meta)
