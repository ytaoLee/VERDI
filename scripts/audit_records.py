"""Independently recompute integer oracle and framing totals in query journals."""
import argparse,json
from pathlib import Path
from verdi.cache import load_cache
from verdi.protocol import oracle

def run(a):
    _,x,_=load_cache(a.features); root=Path(a.records); count=0
    files=[root] if root.is_file() else sorted(root.rglob('queries.jsonl'))
    if not files: raise FileNotFoundError('No query records')
    for path in files:
        if a.n is not None: n=a.n
        else:
            configpath=path.parent/'config.json'
            if configpath.exists(): config=json.loads(configpath.read_text(encoding='utf-8'))
            elif (path.parent.parent/'config.json').exists(): config=json.loads((path.parent.parent/'config.json').read_text(encoding='utf-8'))
            else: raise ValueError('Specify --n for this journal')
            n=config.get('n',config.get('config',{}).get('n'))
            if n is None and path.parent.name.startswith('scale_'): n=int(path.parent.name.split('_')[-1])
            if n is None: raise ValueError('Cannot infer gallery size; specify --n')
        features=dict(enumerate(x[:n])); seen=set()
        for line in path.read_text(encoding='utf-8').splitlines():
            row=json.loads(line);key=(row['method'],row['query'],row['repeat']); assert key not in seen;seen.add(key)
            top=oracle(features,x[row['query']],len(row['top_ids']))
            assert row['exact'] and [i for _,i in top]==row['top_ids'] and [s for s,_ in top]==row['integer_scores']
            k=len(row['neighbor_ids']); pairs=[(s,i) for s,i in top if i!=row['query']][:k]
            assert [i for _,i in pairs]==row['neighbor_ids']
            if 'neighbor_scores' in row: assert [s for s,_ in pairs]==row['neighbor_scores']
            assert row['bytes']==sum(row['parts'].values())
            if 'upload_bytes' in row: assert row['bytes']==row['upload_bytes']+row['download_bytes']
            count+=1
    print(json.dumps({'passed':True,'audited_rows':count,'journals':len(files)}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--features',required=True);p.add_argument('--records',required=True);p.add_argument('--n',type=int);run(p.parse_args())
