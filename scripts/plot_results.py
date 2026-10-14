"""Render per-query experiment summaries from locally measured journals."""
import argparse,json
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

def run(a):
    rows=[json.loads(line) for line in Path(a.records).read_text(encoding='utf-8').splitlines()]
    methods=sorted(set(r['method'] for r in rows));fig,axs=plt.subplots(2,1,figsize=(3.5,4.8),constrained_layout=True)
    for ax,field,label,factor in [(axs[0],'bytes','Mean application traffic (MB)',1e-6),(axs[1],'seconds','Median query latency (ms)',1e3)]:
        values=[float(np.mean([r[field] for r in rows if r['method']==m])) if field=='bytes' else float(np.median([r[field] for r in rows if r['method']==m])) for m in methods]
        ax.bar(methods,np.asarray(values)*factor);ax.set_ylabel(label);ax.tick_params(axis='x',rotation=30,labelsize=8)
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    for suffix in ('.pdf','.svg','.png'):fig.savefig(out.with_suffix(suffix),dpi=300)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--records',required=True);p.add_argument('--output',required=True);run(p.parse_args())
