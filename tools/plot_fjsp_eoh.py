"""Standalone standard plots over saved EoH CSV; no business or model imports."""
from pathlib import Path
import argparse,csv,json
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run-dir',type=Path,required=True);args=ap.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    out=args.run_dir/'analysis'
    engineering=json.loads((out/'Summary.json').read_text())['engineering_only']
    with (out/'progress_curve.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
    for key,name,title,ylabel in [('best_fitness','best_fitness','Best complete training Fitness','mean(-Cmax/LB); higher is better'),
                                 ('full_valid_unique_H_evaluations','full_valid_evaluations','Complete valid unique H evaluations','Cumulative complete valid AST-distinct H')]:
        values=[r for r in rows if r[key]!=''];fig,ax=plt.subplots(figsize=(9,5),layout='constrained')
        if values:ax.step([int(r['physical_attempts']) for r in values],[float(r[key]) for r in values],where='post',lw=2)
        else:ax.text(.5,.5,'No complete valid evaluation yet',transform=ax.transAxes,ha='center')
        prefix='MOCK engineering / artificial scores: ' if engineering else 'FJSP / train21 / native EoH: '
        maximum=max(1,int(rows[-1]['physical_attempts']));ax.set(xlim=(0,maximum),xlabel='Physical attempts (initialization, failures and duplicates included)',ylabel=ylabel,title=prefix+title)
        if key!='best_fitness':ax.set_ylim(bottom=0)
        for n in (1023,1050):
            if n<=maximum:ax.axvline(n,color='gray',ls='--',lw=.8)
        ax.grid(alpha=.2);fig.supxlabel('MOCK: no real model or solver validation.' if engineering else 'Training-only description; historical A/B conditions differ.',fontsize=9)
        fig.savefig(out/(name+'.png'),dpi=180);fig.savefig(out/(name+'.svg'));plt.close(fig)
if __name__=='__main__':main()
