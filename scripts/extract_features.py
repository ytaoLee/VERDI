"""Encode supplied dataset images in the published filename order."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'): os.environ[key]='2'
import argparse, hashlib, json
from pathlib import Path
import numpy as np
from PIL import Image
from verdi.common import save, digest, CLIP_REV, MODEL_SHA
from verdi.cache import paper_inputs


def run(a):
    import torch, clip
    out=Path(a.output)
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new empty output directory; existing caches are preserved')
    out.mkdir(parents=True,exist_ok=True)
    names={}
    for path in Path(a.images).rglob('*'):
        if path.is_file() and path.suffix.lower() in ('.jpg','.jpeg','.png'):
            if path.name in names: raise ValueError('Ambiguous image filename: '+path.name)
            names[path.name]=path
    config=Path(__file__).resolve().parents[1]/'configs'
    orders={kind:(config/f'{a.dataset}_{kind}_filenames.txt').read_text(encoding='utf-8').splitlines()
            for kind in ('gallery','calibration')}
    missing=[name for order in orders.values() for name in order if name not in names]
    if missing: raise FileNotFoundError(f'Missing {len(missing)} required images, first: {missing[:5]}')
    device='cuda' if a.device=='auto' and torch.cuda.is_available() else ('cpu' if a.device=='auto' else a.device)
    torch.backends.cuda.matmul.allow_tf32=False; torch.backends.cudnn.allow_tf32=False
    model,preprocess=clip.load('ViT-B/32',device=device,jit=False); model=model.float().eval()
    hashes={}; used=set()
    for kind,order in orders.items():
        array=np.lib.format.open_memmap(out/f'{kind}.npy',mode='w+',dtype=np.float32,shape=(len(order),512))
        rowhash=[]
        for start in range(0,len(order),a.batch_size):
            batch=[]
            for name in order[start:start+a.batch_size]:
                path=names[name]; h=digest(path)
                if h in used: raise ValueError('Duplicate or overlapping source image: '+name)
                used.add(h); rowhash.append(h)
                with Image.open(path) as im: batch.append(preprocess(im.convert('RGB')))
            with torch.no_grad():
                feature=model.encode_image(torch.stack(batch).to(device)).float()
                feature=feature/feature.norm(dim=-1,keepdim=True)
            array[start:start+len(batch)]=feature.cpu().numpy(); array.flush()
            print(kind,min(start+a.batch_size,len(order)),'/',len(order),flush=True)
        hashes[kind]=rowhash
    paper=paper_inputs()[a.dataset]
    files={f'{kind}.npy':digest(out/f'{kind}.npy') for kind in orders}
    manifest={kind:[{'filename':name,'image_sha256':h} for name,h in zip(order,hashes[kind])]
              for kind,order in orders.items()}
    save(out/'dataset_manifest.json',manifest)
    save(out/'features_complete.json',{'dataset':a.dataset,'protocol':paper['protocol'],
         'test_images':paper['test_images'],'gallery_size':len(orders['gallery']),
         'calibration_images':len(orders['calibration']),'identity':{'encoder':'OpenAI CLIP ViT-B/32',
         'clip_revision':CLIP_REV,'model_sha256':MODEL_SHA,'precision':'fp32-no-autocast','torch':torch.__version__,
         'batch_size':a.batch_size,'tf32':False,'device':device},'files_sha256':files,
         'image_sha256':hashes['gallery'],'calibration_sha256':hashes['calibration'],
         'paper_cache_matches':files==paper['files_sha256']})
    print(json.dumps({'paper_cache_matches':files==paper['files_sha256'],'files_sha256':files}))
    if files!=paper['files_sha256']:
        raise RuntimeError('Extraction completed, but arrays differ from the paper cache. Inspect the recorded encoder environment before paper benchmarks.')

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--dataset',required=True,choices=['coco','flickr30k'])
    p.add_argument('--images',required=True);p.add_argument('--output',required=True)
    p.add_argument('--batch-size',type=int,default=16);p.add_argument('--device',default='auto');run(p.parse_args())
