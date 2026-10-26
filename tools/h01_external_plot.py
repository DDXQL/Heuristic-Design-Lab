"""Plot all frozen confirmation pairs from CSV; no scheduling/API imports."""
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    directory=Path(__file__).resolve().parents[1]/'reports/h01-champion-hurink-rdata20-seed501-20261026-v1'
    with (directory/'Paired_instance_results.csv').open() as f:rows=list(csv.DictReader(f))
    s=json.loads((directory/'Summary.json').read_text());assert s['full_confirmation_valid'] and len(rows)==20
    gain=[float(r['ratio_gain']) for r in rows]
    labels=[r['file'].replace('HurinkR_','').replace('.fjsp','')+f" ({r['operations']} ops, {r['machines']} M)" for r in rows]
    fig,ax=plt.subplots(figsize=(9,7.2))
    ax.barh(range(len(rows)),gain,color=['#2166ac' if v>0 else '#b2182b' for v in gain])
    ax.set_yticks(range(len(rows)),labels,fontsize=9);ax.invert_yaxis();ax.axvline(0,color='black',linewidth=.8)
    ax.axvline(s['delta_F'],color='#333333',linestyle='--',label=f"Full-set mean gain = {s['delta_F']:+.4f}")
    ax.set_xlabel('(Cmax_equal - Cmax_dynamic) / LB; positive favors frozen dynamic U')
    ax.set_title('Fixed champion vs equal weights: all 20 Hurink rdata confirmation instances\n'
                 '2 wins / 18 losses / 0 ties; cross-benchmark + smaller-machine-count transfer',fontsize=11)
    ax.grid(axis='x',alpha=.2);ax.legend(loc='lower left',fontsize=9);fig.tight_layout()
    for suffix in ('png','pdf'):fig.savefig(directory/f'All_instance_gains.{suffix}',dpi=180)
    plt.close(fig)
    names=('Paired_instance_results.csv','Summary.json','All_instance_gains.png','All_instance_gains.pdf')
    (directory/'Plot_provenance.json').write_text(json.dumps({'matplotlib':matplotlib.__version__,
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_and_artifacts':{n:hashlib.sha256((directory/n).read_bytes()).hexdigest() for n in names},
        'new_API':0,'new_solves':0},indent=2)+'\n')
    print('Saved all-instance confirmation figure from existing CSV.')


if __name__=='__main__':main()
