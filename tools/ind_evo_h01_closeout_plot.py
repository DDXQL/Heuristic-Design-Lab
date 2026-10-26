"""Plot existing closeout CSV only; no project runtime, API, or scheduling imports.

Use a local Python with matplotlib, e.g. /opt/homebrew/bin/python3 on this host.
"""
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


def main():
    directory = Path(__file__).resolve().parents[1]/'reports/ind-vs-evo-h01-train21-seed501-20261026-v1/closeout-v1'
    with (directory/'Search_curves.csv').open() as f:
        curves = list(csv.DictReader(f))
    with (directory/'Completion.csv').open() as f:
        completion = list(csv.DictReader(f))
    with (directory/'Candidates.csv').open() as f:
        candidates = list(csv.DictReader(f))
    colors = {'IND': '#2166ac', 'EVO': '#b2182b'}
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.1), sharey=True)
    for repeat, ax in enumerate(axes, 1):
        for arm in ('IND', 'EVO'):
            rows = [r for r in curves if int(r['repeat']) == repeat and r['arm'] == arm]
            ax.step([int(r['logical_query']) for r in rows], [float(r['best_fitness']) for r in rows],
                    where='post', color=colors[arm], label=arm, linewidth=1.9,
                    linestyle='-' if arm == 'IND' else '--')
            last = rows[-1]
            ax.plot(int(last['logical_query']), float(last['best_fitness']), 'o', color=colors[arm], markersize=4)
            for candidate in candidates:
                if int(candidate['repeat']) == repeat and candidate['arm'] == arm and candidate['outcome'] == 'transport_failed':
                    position = int(candidate['logical_query'])
                    row = next(r for r in rows if int(r['logical_query']) == position)
                    ax.plot(position, float(row['best_fitness']), marker='x', linestyle='none',
                            color=colors[arm], markersize=7, markeredgewidth=1.5)
        sizes = {r['arm']: int(r['consumed']) for r in completion if int(r['repeat']) == repeat}
        ax.set_title(f"Repeat {repeat}: {'full logical budget' if min(sizes.values()) == 20 else 'PARTIAL'}\n"
                     f"IND {sizes['IND']}/20; EVO {sizes['EVO']}/20", fontsize=11)
        ax.axhline(float(curves[0]['best_fitness']), linestyle='--', color='#666666', linewidth=.8)
        ax.set(xlim=(0, 20.5), ylim=(-1.9841, -1.9746), xlabel='Consumed additional logical slots')
        ax.set_xticks([0, 5, 10, 15, 20]); ax.grid(alpha=.22)
        ax.ticklabel_format(axis='y', style='plain', useOffset=False)
    axes[0].set_ylabel('Best complete train21 mean(-Cmax/LB)\n(includes common P0; higher is better)')
    handles = [Line2D([0], [0], color=colors[a], label=a, linewidth=2,
                      linestyle='-' if a == 'IND' else '--') for a in ('IND', 'EVO')]
    handles += [Line2D([0], [0], color='#666666', linestyle='--', label='Common P0 best'),
                Line2D([0], [0], color='black', marker='x', linestyle='none', label='HTTP-failed logical slot')]
    fig.legend(handles=handles, loc='lower center', ncol=4, frameon=False, fontsize=9)
    fig.suptitle('IND vs EVO: saved partial campaign; no extrapolation beyond observed slots', fontsize=12)
    fig.tight_layout(rect=(0, .11, 1, .92))
    for extension in ('png', 'pdf', 'svg'):
        fig.savefig(directory/f'Search_curves.{extension}', dpi=180)
    plt.close(fig)
    svg = directory/'Search_curves.svg'
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
    filenames = ('Search_curves.csv', 'Completion.csv', 'Candidates.csv',
                 'Search_curves.png', 'Search_curves.pdf', 'Search_curves.svg')
    (directory/'Plot_provenance.json').write_text(json.dumps({
        'matplotlib_version': matplotlib.__version__, 'new_API': 0, 'new_solves': 0,
        'plot_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'files': {n: hashlib.sha256((directory/n).read_bytes()).hexdigest() for n in filenames}}, indent=2)+'\n')
    print('Saved offline curve PNG/PDF/SVG from existing CSV.')


if __name__ == '__main__':
    main()
