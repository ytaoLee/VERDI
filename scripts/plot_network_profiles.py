"""Replot the six Windows profiles; all 18 median/CI observations are retained."""
from pathlib import Path
import argparse,csv,json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=Path('outputs/windows_network'))
args=parser.parse_args()
OUT=args.output
OUT.parent.mkdir(parents=True,exist_ok=True)
rows=list(csv.DictReader((ROOT/'paper_data/windows_network_display.csv').open(encoding='utf-8')))
assert len(rows)==18 and len({(r['profile'],r['method']) for r in rows})==18
lookup={(r['profile'],r['method']):r for r in rows}
methods=['Geo + fine','Flat + fine','Flat scan']
colors=['#8EABC3','#76A79C','#C5B18E']
hatches=['','','']
profiles=[
 ['Local, 2 CPUs','Local, 1 CPU'],
 ['50 Mb/s, 2 ms','50 Mb/s, 10 ms','200 Mb/s, 2 ms','200 Mb/s, 10 ms']]
plt.rcParams.update({
 'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
 'font.size':7.2,'axes.labelsize':7.2,'axes.titlesize':7.7,
 'xtick.labelsize':7.2,'ytick.labelsize':7.2,'legend.fontsize':7.2,
 'axes.linewidth':0.6,'hatch.linewidth':0.35,
 'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none',
 'savefig.facecolor':'white'
})
fig=plt.figure(figsize=(3.5,2.1))
width=.35
height=width*3.5/2.1
axes=[fig.add_axes([left,.25,width,height]) for left in [.14,.62]]
numeric_audit=[]
for idx,(ax,pp) in enumerate(zip(axes,profiles)):
    ax.set_box_aspect(1)
    ax.set_facecolor('#F2F2F2')
    ax.set_axisbelow(True)
    ax.grid(axis='y',color='#303030',alpha=.18,linewidth=.45)
    ax.tick_params(axis='both',direction='in',length=2.5,width=.6,top=True,right=True,pad=2)
    x=np.arange(len(pp),dtype=float)
    for j,(m,c,h) in enumerate(zip(methods,colors,hatches)):
        med=np.array([float(lookup[(p,m)]['median_ms']) for p in pp])
        low=np.array([float(lookup[(p,m)]['ci_low_ms']) for p in pp])
        high=np.array([float(lookup[(p,m)]['ci_high_ms']) for p in pp])
        assert np.all(np.isfinite(med)) and np.all(low<=med) and np.all(high>=med)
        yerr=np.vstack([med-low,high-med])
        bars=ax.bar(x+(j-1)*.24,med,width=.22,color=c,edgecolor='#46515A',
                    linewidth=.45,hatch=h,yerr=yerr,
                    error_kw={'ecolor':'#27343C','elinewidth':.6,'capsize':1.3,'capthick':.6},
                    label=m,zorder=3)
        for p,bar,v,l,u in zip(pp,bars,med,low,high):
            assert abs(bar.get_height()-v)<1e-9
            numeric_audit.append({'profile':p,'method':m,'median_ms':float(v),
              'ci_low_ms':float(l),'ci_high_ms':float(u),
              'bar_x':float(bar.get_x()),'bar_height':float(bar.get_height())})
    ax.set_xlim(-.52,len(pp)-.48)
    ax.set_xticks(x)
    if idx==0:
        ax.set_xticklabels(['2','1'])
        ax.set_xlabel('Logical CPUs',labelpad=4)
        ax.set_ylim(0,600);ax.set_yticks([0,200,400,600])
        ax.set_title('(a) Local CPU affinity',pad=5)
    else:
        ax.set_xticklabels(['50\n2 ms','50\n10 ms','200\n2 ms','200\n10 ms'])
        ax.set_xlabel('Bandwidth (Mb/s)',labelpad=4)
        ax.set_ylim(0,6000);ax.set_yticks([0,2000,4000,6000])
        ax.set_title('(b) Shaped links',pad=5)
fig.text(.027,.535,'Median latency (ms)',ha='center',va='center',rotation=90,rotation_mode='anchor',fontsize=7.2)
legend=[Patch(facecolor=c,edgecolor='#46515A',linewidth=.45,hatch=h,label=m)
        for c,h,m in zip(colors,hatches,methods)]
fig.legend(handles=legend,ncol=3,loc='upper center',bbox_to_anchor=(.54,.99),
           frameon=False,handlelength=1.4,handleheight=.9,handletextpad=.4,columnspacing=1.0,
           borderaxespad=0.)
fig.canvas.draw()
geometry=[]
for i,ax in enumerate(axes):
    box=ax.get_window_extent()
    assert abs(box.width-box.height)<1e-6
    geometry.append({'panel':chr(97+i),'width_px':box.width,'height_px':box.height,
      'ylim':[float(v) for v in ax.get_ylim()],'zero_based':bool(ax.get_ylim()[0]==0)})
# Fixed physical size: no outside tight crop can change the manuscript font scale.
fig.savefig(OUT.with_suffix('.pdf'))
fig.savefig(OUT.with_suffix('.svg'))
fig.savefig(OUT.with_suffix('.png'),dpi=600)
(OUT.with_name(OUT.name+'_numeric_audit.json')).write_text(json.dumps({
 'points':numeric_audit,'panel_geometry':geometry,'source_rows':len(rows),
 'method_colors':dict(zip(methods,colors)),'min_font_pt':7.2,
 'bootstrap':'95% query-block CIs copied unchanged; not interpolated/recomputed',
 'styles':'grey plot area, inward ticks, subtle dark y-grid, low-saturation fills',
 'current_figure':'Figure 4; rounded published medians and CIs, not raw trials'},indent=2),encoding='utf-8')
plt.close(fig)
print('Wrote vector PDF/SVG and 600-dpi preview; 18/18 values and intervals preserved.')
