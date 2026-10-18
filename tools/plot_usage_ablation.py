#!/usr/bin/env python3
"""Standalone train figures using ReportLab's plotting library (no evaluation)."""
import argparse
import csv
import json
from pathlib import Path

from reportlab.graphics import renderSVG
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String, Line, Rect
from reportlab.graphics.widgets.markers import makeMarker
from reportlab.lib import colors

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/usage-v22-mechanism-ablation-301-20261017-v1'
PALETTE = [colors.HexColor(x) for x in ('#1768AC', '#188351', '#D47A16', '#555555')]


def base(title, subtitle):
    drawing = Drawing(1200, 540)
    drawing.add(Rect(0, 0, 1200, 540, fillColor=colors.white, strokeColor=None))
    drawing.add(String(65, 507, title, fontName='Helvetica-Bold', fontSize=19))
    drawing.add(String(65, 483, subtitle, fontSize=11, fillColor=colors.HexColor('#444444')))
    return drawing


def chart(drawing, data, joined=True):
    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 75, 100, 1080, 320
    plot.data = data
    plot.joinedLines = int(joined)
    plot.xValueAxis.labels.fontSize = 10
    plot.yValueAxis.labels.fontSize = 10
    plot.yValueAxis.visibleGrid = True
    plot.yValueAxis.gridStrokeColor = colors.HexColor('#dddddd')
    plot.yValueAxis.gridStrokeWidth = .5
    for i in range(len(data)):
        plot.lines[i].strokeColor = PALETTE[i % 4]
        plot.lines[i].strokeWidth = 1.6
        plot.lines[i].symbol = makeMarker(('FilledCircle', 'FilledSquare', 'FilledDiamond', 'Circle')[i % 4])
        plot.lines[i].symbol.size = 5
    drawing.add(plot)
    return plot


def main():
    plan = json.loads((OUT / 'Plan.json').read_text())
    rows = list(csv.DictReader((OUT / 'Ablation_and_fixed_H_instances.csv').open()))
    summary = list(csv.DictReader((OUT / 'Ablation_and_fixed_H_summary.csv').open()))
    names = plan['names']
    figs = OUT / 'figures'
    figs.mkdir(exist_ok=True)
    for prefix in ('B5', 'B3'):
        ids = [f'{prefix}_{v}' for v in ('original', 'equal', 'winner')] + ['H0']
        data = []
        incomplete = []
        for key in ids:
            indexed = {r['file']: r for r in rows if r['id'] == key}
            points = [(i+1, float(indexed[name]['makespan'])/float(indexed[name]['lower_bound']))
                      for i, name in enumerate(names) if indexed[name]['makespan']]
            data.append(points)
            if len(points) != 21:
                incomplete.append(key)
        drawing = base(f'{prefix}: original vs equal weights vs maximum-weight SELECT',
            'Train21 only | Cmax / unrounded V5 LB: lower is better | historical originals and H0 reused')
        plot = chart(drawing, data)
        plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = 1, 21
        plot.xValueAxis.valueSteps = list(range(1, 22))
        plot.xValueAxis.labelTextFormat = lambda x: names[int(round(x))-1].replace('Behnke', '').replace('.fjsp', '')
        plot.yValueAxis.labelTextFormat = '%.1f'
        drawing.add(String(75, 440, 'Cmax / LB', fontSize=11))
        drawing.add(String(445, 67, 'Behnke instance number (original declared order)', fontSize=11))
        for i, text in enumerate(('Original dynamic weights', 'Equal positive-support weights', 'Maximum-weight single h', 'Best fixed h: H0')):
            x = 75 + i*275
            drawing.add(Line(x, 38, x+20, 38, strokeColor=PALETTE[i], strokeWidth=2))
            drawing.add(String(x+25, 34, text, fontSize=10))
        drawing.add(String(75, 12, 'All 4 curves complete (21/21).' if not incomplete else
                           'Missing/failed: ' + ', '.join(incomplete), fontSize=10))
        renderSVG.drawToFile(drawing, str(figs / f'{prefix}_instances.svg'))
    eligible = [r for r in summary[:6] if r['valid'] == 'True' and r['primary_h_calls']]
    drawing = base('Quality and certified h action-scoring calls: six frozen strategies',
        'Train21 only | fitness higher is better | cost = one solve; deterministic recheck has the same certified call count')
    labels = [r['id'].replace('original', 'O').replace('equal', 'E').replace('winner', 'W') for r in eligible]
    data = [[(float(r['primary_h_calls'])/1e6, float(r['fitness']))] for r in eligible]
    plot = chart(drawing, data, joined=False)
    plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = 1.5, 4.6
    plot.yValueAxis.valueMin, plot.yValueAxis.valueMax = -2.45, -2.22
    plot.yValueAxis.valueSteps = [-2.45, -2.4, -2.35, -2.3, -2.25]
    plot.yValueAxis.labelTextFormat = '%.2f'
    plot.xValueAxis.labelTextFormat = '%.1f'
    plot.lineLabelFormat = 'values'
    plot.lineLabelArray = [[label] for label in labels]
    for i, label in enumerate(labels):
        variant = eligible[i]['kind']
        plot.lines[i].strokeColor = PALETTE[('original', 'equal', 'winner').index(variant)]
        plot.lines[i].symbol = makeMarker('FilledCircle' if label.startswith('B5') else 'FilledDiamond')
        plot.lines[i].symbol.size = 6
        plot.lineLabels[(i, 0)].fontSize = 11
        plot.lineLabels[(i, 0)].dx = 9
        plot.lineLabels[(i, 0)].dy = 9
    drawing.add(String(75, 440, 'Complete-train fitness', fontSize=11))
    drawing.add(String(430, 67, 'Certified primary h calls (millions; lower is less work)', fontSize=11))
    drawing.add(String(75, 39, 'O = original; E = equal; W = winner-only. Fixed h call counts: NA (not recorded); fixed h points omitted.', fontSize=10))
    failures = [r['id'] for r in summary[:6] if r['valid'] != 'True']
    drawing.add(String(75, 18, 'All 6 ablation versions complete. Historical B0/B1/B2: invalid at Behnke57, fitness and failed calls NA; omitted.'
                       if not failures else 'INVALID (no full-fitness point): ' + ', '.join(failures), fontSize=10))
    renderSVG.drawToFile(drawing, str(figs / 'quality_cost.svg'))


def plot_grid(directory):
    """Reuse drawing/axis helpers for a separately frozen manual grid."""
    directory = Path(directory).resolve()
    analysis = json.loads((directory / 'Analysis.json').read_text())
    rows = analysis['summaries']
    fixed = json.loads((directory / 'Fixed_H_reused.json').read_text())
    h0 = next(r['result']['fitness'] for r in fixed if r['id'] == 'H0')
    figs = directory / 'figures'
    figs.mkdir(exist_ok=True)
    pairs = list(dict.fromkeys(r['pair'] for r in rows))
    drawing = base('Manual fixed-pair weight grid: complete-train fitness',
                   'Train21 | higher is better | 15s per instance includes deterministic recheck | all 12 candidates shown')
    for j, weight in enumerate((.25, .5, .75)):
        drawing.add(String(280+295*j, 440, f'Raw weights (a,b) = ({weight:.2f},{1-weight:.2f})', fontSize=11))
    for i, pair in enumerate(pairs):
        drawing.add(String(65, 370-90*i, 'H' + pair.replace(',', ' / H'), fontSize=13))
        for j, row in enumerate(r for r in rows if r['pair'] == pair):
            x, y = 250+295*j, 337-90*i
            valid = row['valid']
            fill = '#dcefe4' if valid and row['fitness_minus_H0'] > 0 else '#f5e9da' if valid else '#f7d9db'
            drawing.add(Rect(x, y, 280, 73, fillColor=colors.HexColor(fill), strokeColor=colors.white))
            text = f'{row["fitness"]:.6f}' if valid else 'INVALID: ' + row['failed_instance']
            detail = f'delta vs H0: {row["fitness_minus_H0"]:+.6f}' if valid else f'{row["completed_instances"]}/21 complete; full fitness NA'
            drawing.add(String(x+12, y+43, text, fontSize=13))
            drawing.add(String(x+12, y+17, detail, fontSize=10))
    drawing.add(String(65, 39, f'H0 reference: {h0:.6f}. Green = higher fitness than H0; tan = equal/lower; red = invalid.', fontSize=11))
    drawing.add(String(65, 17, 'Manual training-set parameter selection; not LLM evolution, not independently validated.', fontSize=10))
    renderSVG.drawToFile(drawing, str(figs / 'grid_results.svg'))
    valid = [r for r in rows if r['valid']]
    drawing = base('Quality versus certified h action-scoring calls: manual grid',
                   'Train21 | higher fitness and fewer calls preferred | calls shown for first solve; recheck certified separately')
    if valid:
        data = [[(r['primary_h_calls']/1e6, r['fitness'])] for r in valid]
        plot = chart(drawing, data, joined=False)
        xs, ys = [p[0][0] for p in data], [p[0][1] for p in data] + [h0]
        spread = max(max(xs)-min(xs), .3)
        ymin, ymax = min(ys), max(ys)
        margin = max((ymax-ymin)*.13, .015)
        plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = min(xs)-.15*spread, max(xs)+.15*spread
        plot.yValueAxis.valueMin, plot.yValueAxis.valueMax = ymin-margin, ymax+margin
        plot.yValueAxis.labelTextFormat, plot.xValueAxis.labelTextFormat = '%.2f', '%.1f'
        plot.lineLabelFormat = 'values'
        plot.lineLabelArray = [[r['id'].replace('H', '').replace('_w', ':').replace('_', '/')] for r in valid]
        label_offsets = {'H0_H1_w50_50': (8, 9), 'H0_H3_w50_50': (8, -15),
            'H0_H1_w75_25': (8, 11), 'H0_H3_w75_25': (8, -14),
            'H0_H3_w25_75': (12, 3), 'H3_H6_w75_25': (12, -14)}
        for i, row in enumerate(valid):
            plot.lines[i].strokeColor = PALETTE[pairs.index(row['pair'])]
            plot.lines[i].symbol = makeMarker(('FilledCircle', 'FilledSquare', 'FilledDiamond')[(.25, .5, .75).index(row['weight_a'])])
            plot.lines[i].symbol.size = 6
            plot.lineLabels[(i, 0)].fontSize = 9
            plot.lineLabels[(i, 0)].dx, plot.lineLabels[(i, 0)].dy = label_offsets.get(row['id'], (8, 9))
        y = plot.y + (h0-(ymin-margin))/(ymax-ymin+2*margin)*plot.height
        drawing.add(Line(plot.x, y, plot.x+plot.width, y, strokeColor=colors.grey, strokeDashArray=[4, 3]))
        drawing.add(String(80, y+5, f'H0 {h0:.6f}; historical h calls NA', fontSize=10))
    else:
        drawing.add(String(75, 300, 'No complete valid grid candidate; full fitness and cost points unavailable.', fontSize=13))
    drawing.add(String(75, 67, 'Certified primary h calls (millions). Labels: member a/member b : weight a/weight b in percent.', fontSize=10))
    failed = [r['id'] for r in rows if not r['valid']]
    drawing.add(String(75, 39, f'Complete valid: {len(valid)}/12. Failed: {len(failed)}; see red grid cells. Failed partial calls unknown; no full-fitness points.', fontSize=10))
    drawing.add(String(75, 17, 'Fixed-h call counts were not recorded; omitted from x-axis. Historical versus current timing is descriptive only.', fontSize=10))
    renderSVG.drawToFile(drawing, str(figs / 'grid_quality_cost.svg'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grid-directory', type=Path)
    args = parser.parse_args()
    plot_grid(args.grid_directory) if args.grid_directory else main()
