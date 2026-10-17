#!/usr/bin/env python3
"""Standalone train figures using ReportLab's plotting library (no evaluation)."""
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


if __name__ == '__main__':
    main()
