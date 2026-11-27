"""Render thesis figures from existing real receipts. Never runs a solver."""

import argparse
from collections import defaultdict
import csv
import gzip
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path
from statistics import mean, stdev
import zipfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import MaxNLocator, PercentFormatter

from figure_training_history import COLUMNS
from research_progress import current_rows, formal

ROOT = Path(__file__).resolve().parents[1]
OUTBOX = ROOT.parent / 'transfer-outbox'
PROTOTYPES = ROOT
OUTPUT = ROOT / 'reports/paper-figures'
TSP_HISTORY = OUTPUT / 'inputs/tsp-training-history-20261125.csv.gz'
SEEDS = (501, 502, 503)
METHODS = ('u', 'eoh', 'ross')
NAMES = {'u': 'U', 'eoh': 'EoH', 'ross': 'Ross-style'}
COLORS = {'u': '#0072B2', 'eoh': '#B64D00', 'ross': '#007F62'}
MARKS = {'u': 'o', 'eoh': 's', 'ross': '^'}
INK, GRID, MUTED = '#172635', '#DEE5EB', '#526676'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def records(raw):
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))


class Inputs:
    def __init__(self):
        self.sources = {}

    def read(self, path, member=None):
        if member is None:
            raw = path.read_bytes()
        else:
            with zipfile.ZipFile(path) as archive:
                raw = archive.read(member)
        label = os.path.relpath(path, ROOT) + (f'::{member}' if member else '')
        self.sources[label] = sha256(raw).hexdigest()
        return raw

    def data(self, *args):
        return json.loads(self.read(*args))

    def table(self, *args):
        return records(self.read(*args))


def table(out, name, rows, columns=None):
    with (out / f'{name}.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, columns or list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def tsp_evidence(source, root, outbox):
    folder = root / 'reports/tsp-confirm60-nine-20261124'
    seeds = source.table(folder / 'seed-results.csv')
    units = source.table(folder / 'per-instance.csv')
    training = source.data(outbox / 'triad-candidate-runtime-20261121-r15-six-long-live.zip',
                           'preparations/operations/tsp-reference-r15.json')
    confirmation = outbox / 'tsp-confirm60-d06-results-20261124/confirm60-reference.json'
    held = source.data(confirmation)
    receipt = source.read(confirmation.parent / 'plan/LKH-run-receipt.json')
    spec = source.data(ROOT / 'experiments/triad/lkh.pending.json')
    policy = ('lkh_identity', 'parameters', 'distance_protocol')
    require(all(training[k] == held[k] for k in policy) and
            held['execution_receipt_sha256'] == sha256(receipt).hexdigest() and
            training['execution_receipt_sha256'] != held['execution_receipt_sha256'], 'D06 identities differ')
    execution = json.loads(receipt)
    require(execution['phase'] == 'completed' and execution['completed_processes'] == 60 and
            execution['internal_RUNS'] == spec['runs'] and execution['MAX_TRIALS'] == spec['max_trials'] and
            execution['CPU_hard_seconds_per_process'] == spec['cpu_seconds'] and
            execution['timeout_seconds_per_process'] == spec['timeout_seconds'], 'D06 controls differ')
    require(held['parameters'] == {k: spec[k] for k in ('runs', 'max_trials', 'seed', 'integer_scale')},
            'frozen D06 references disagree with the adopted parameters')
    require(len(training['instances']) == 20 and len(held['instances']) == 60 and
            not ({r['instance_sha256'] for r in training['instances']} &
                 {r['instance_sha256'] for r in held['instances']}), 'D06 splits overlap or differ in size')
    assets = outbox / 'tsp-confirm60-d06-inputs-20261124.zip'
    manifest_raw = source.read(assets, 'confirm.manifest.json')
    manifest = json.loads(manifest_raw)
    sizes = set()
    for row in manifest['instances']:
        instance = source.read(assets, row['path'])
        require(sha256(instance).hexdigest() == row['sha256'], 'confirm60 input hash mismatch')
        sizes.add(len(json.loads(instance)['coordinates']))
    require(sizes == {50}, 'confirm60 contains unexpected sizes')
    key = lambda r: (r['method'], int(r['seed']))
    expected = {(method, seed) for method in METHODS for seed in SEEDS}
    require(len(seeds) == len(expected) and {key(r) for r in seeds} == expected, 'missing or duplicate frozen champion')
    references = {r['file']: r['reference'] for r in held['instances']}
    require(set(references) == {r['file'] for r in manifest['instances']}, 'confirm60 D06 instances differ')
    require(len(units) == 540 and {key(r) for r in units} == expected, 'expected 540 matched instance results')
    scores = defaultdict(dict)
    validation_cpu = defaultdict(float)
    costs = []
    for row in units:
        group, name = key(row), row['file']
        score = float(row['J'])
        ref = references[name]
        require(name not in scores[group] and float(row['D06_reference']) == ref and
                math.isclose(score, (float(row['tour_length']) - ref) / ref, abs_tol=1e-12) and
                int(row['certified_solves']) == 2, 'paired instance score or receipt differs')
        scores[group][name] = score
        validation_cpu[group] += float(row['worker_CPU_seconds'])
    for row in seeds:
        method, seed = key(row)
        require(row['complete'] == 'True' and row['rows'] == '60' and
                row['manifest_sha256'] == sha256(manifest_raw).hexdigest() and
                row['reference_sha256'] == sha256(confirmation.read_bytes()).hexdigest() and
                set(scores[method, seed]) == set(references), 'holdout receipt mismatch')
        require(math.isclose(mean(scores[method, seed].values()), float(row['confirm60_J']), abs_tol=1e-12),
                'seed dataset score disagrees with instance mean')
        require(math.isclose(validation_cpu[method, seed], float(row['certified_worker_CPU_seconds']), abs_tol=1e-9),
                'seed CPU cost disagrees with instance receipts')
        if method == 'ross':
            run = root / f'runs/prototype-hh/tsp-{seed}'
            summary = source.data(run / 'exports/summary.json')
            details = source.data(run / 'exports/costs.json')
            require(sha256(source.read(run / 'Protocol.json')).hexdigest() == row['protocol_sha256'], 'Ross identity differs')
            train_J = summary['best_training_J']
            starts, done = (details[k] for k in ('physical_solve_starts', 'physical_solve_completions'))
            sends, tokens, unknown = details['API_requests'], details['LLM_tokens'], 0
            train_cpu = details.get('certified_rows_worker_CPU_seconds')
        else:
            archive = outbox / 'tsp-r15-champions-20261124.zip'
            prefix = f'{method}-{seed}'
            require(sha256(source.read(archive, f'{prefix}/Protocol.json')).hexdigest() == row['protocol_sha256'],
                    'LLM champion source differs')
            summary = source.data(archive, f'{prefix}/exports/summary.json')
            require(summary['phase'] == 'completed' and summary['successful_evolution_responses'] == 1000,
                    'training cost receipt incomplete')
            train_J = summary['best_J']
            starts, done = (sum(p[k] for p in summary['physical_passes'].values()) for k in ('started', 'completed'))
            sends = summary['confirmed_sends']
            tokens = sum(summary['known_usage_subtotal'].values())
            unknown, train_cpu = summary['confirmed_sends_usage_unknown'], None
        require(math.isclose(float(row['training_J']), train_J, abs_tol=1e-12), 'training score disagrees with receipt')
        costs.append(dict(method=method, seed=seed, train_J=train_J, holdout_J=float(row['confirm60_J']),
                          train_solve_starts=starts, train_solve_completions=done, training_known_tokens=tokens,
                          training_confirmed_API_sends=sends, confirmed_sends_usage_unknown=unknown,
                          training_certified_worker_cpu_s=train_cpu, holdout_wall_s=row['wall_seconds'],
                          holdout_solve_completions=row['solve_completions'],
                          holdout_worker_cpu_s=float(row['certified_worker_CPU_seconds'])))
    pairs = []
    for name, ref in sorted(references.items(), key=lambda kv: (kv[1], kv[0])):
        means = {m: mean(scores[m, s][name] for s in SEEDS) for m in METHODS}
        pairs.append(dict(file=name, LKH_reference_length=ref, U_J=means['u'], EoH_J=means['eoh'], Ross_J=means['ross'],
                          U_minus_EoH=means['u'] - means['eoh'], U_minus_Ross=means['u'] - means['ross']))
    aggregates = source.table(folder / 'method-summary.csv')
    require(len(aggregates) == 3 and {row['method'] for row in aggregates} == set(METHODS), 'method summary differs')
    for row in aggregates:
        group = [r for r in costs if r['method'] == row['method']]
        require(int(row['complete_seeds']) == len(group), 'independent seed count differs')
        for field, prefix in (('train_J', 'train'), ('holdout_J', 'confirm60')):
            values = [r[field] for r in group]
            require(all(math.isclose(op(values), float(row[f'{prefix}_{label}']), abs_tol=1e-12)
                        for op, label in ((mean, 'mean'), (stdev, 'sample_sd'))), 'method summary statistic differs')
    return costs, units, pairs, aggregates


def local_series(source, root, outbox):
    curves = []
    for run in sorted((root / 'runs/prototype-hh').glob('*')):
        path = run / 'exports/candidates.csv'
        protocol_path = run / 'Protocol.json'
        if not path.is_file() or not protocol_path.is_file():
            continue
        protocol_raw = source.read(protocol_path)
        protocol = json.loads(protocol_raw)
        if protocol['engineering_only'] is not False:
            continue
        summary = source.data(run / 'exports/summary.json')
        if summary['phase'] != 'completed':
            continue  # Only stable local exports. Deployed live series use the read-only collector.
        search = protocol['search']
        target = search['population_size'] + 2 * search['iterations']
        for i, row in enumerate(source.table(path)):
            require(row['id'] == f'P-{i:07d}', 'Ross candidate order is incomplete')
            curves.append(dict(problem=summary['problem'], method='ross', seed=summary['seed'], run_id=run.name,
                               protocol_sha256=sha256(protocol_raw).hexdigest(), phase=summary['phase'],
                               count_basis='logical_slots', target=target, step=i + 1,
                               candidate_J=row['J'], best_J=row['best_training_J'],
                               source=f'ross-archive/{run.name}/exports/candidates.csv'))
    historical = outbox / 'fjsp-u501-closeout-20261114-v1-full.zip'
    if historical.is_file():
        summary = source.data(historical, 'run/exports/summary.json')
        require(summary['label'] == 'TRAINING_SEARCH' and summary['phase'] == 'completed', 'historical run incomplete')
        for row in source.table(historical, 'run/exports/candidates.csv'):
            if row['stage'] == 'evolution':
                curves.append(dict(problem='fjsp', method='u', seed=501, run_id=summary['run_id'],
                                   protocol_sha256=summary['protocol_sha256'], phase='completed',
                                   count_basis='historical_attempts', target=summary['evolution_attempts'],
                                   step=int(row['evolution_attempt']), candidate_J=row['J'], best_J=row['best_J'],
                                   source=historical.name + '::run/exports/candidates.csv'))
    return curves


def chosen_series(rows, snapshot):
    groups = defaultdict(list)
    for row in rows:
        if 'Mock' in row['source'] or row['method'] not in METHODS:
            continue
        r = {**row, 'seed': int(row['seed']), 'step': int(row['step']), 'target': int(row['target'])}
        key = r['problem'], r['method'], r['seed']
        selected = snapshot.get(key, {})
        if r['count_basis'] != 'historical_attempts':
            identity = selected.get('protocol_hash')
            if (identity and identity != r['protocol_sha256']) or (not identity and selected.get('run_id') != r['run_id']):
                continue
        groups[(*key, r['count_basis'], r['protocol_sha256'])].append(r)
    for key, values in groups.items():
        values.sort(key=lambda r: r['step'])
        require([r['step'] for r in values] == list(range(1, len(values) + 1)), f'incomplete or duplicate curve prefix: {key}')
        last = math.inf
        for r in values:
            if r['best_J'] not in ('', None):
                value = float(r['best_J'])
                require(math.isfinite(value) and value <= last + 1e-13, f'non-monotone best score: {key}')
                last = value
        if values[0]['phase'] == 'completed':
            require(len(values) == values[0]['target'], f'incomplete evolution series: {key}')
            expected = snapshot.get(key[:3], {}).get('train_J')
            if key[3] != 'historical_attempts' and expected is not None and snapshot[key[:3]]['train_state'] == 'completed':
                require(math.isclose(last, expected, abs_tol=1e-12), f'curve endpoint differs from champion: {key}')
    return groups


def fixed_h(source, prototypes):
    folder = ROOT / 'reports/fjsp-execution-20261112/fixed-H-reuse-v3'
    compatibility = source.data(folder / 'compatibility.json')
    proto = source.data(prototypes / 'runs/prototype-hh/fjsp-501/Protocol.json')
    same_rows = [(r['file'], r['source_sha256']) for r in compatibility['instances']] == [
        (r['file'], r['source_sha256']) for r in proto['instances']]
    require(same_rows and [r['LB'] for r in compatibility['instances']] == [r['reference'] for r in proto['references']]
            and compatibility['H_order'] == proto['binding']['H_keys'],
            'FJSP fixed H and Ross training row, reference or rule library differs')
    fixed = compatibility['ranking'][0]
    costs = [r for r in source.table(folder / 'fixed-H-train21-J.csv') if r['H'] == fixed['H']]
    require(len(costs) == 21 and all(r['valid'] == 'True' for r in costs) and
            math.isclose(mean(float(r['J']) for r in costs), fixed['J'], abs_tol=1e-12), 'fixed H costs differ')
    return fixed


class Figures:
    def __init__(self, output, lang, font, book):
        self.output, self.lang, self.book = output, lang, book
        if lang == 'zh':
            if font is None:
                path = Path('/Library/Fonts/Arial Unicode.ttf')
                font = path if path.is_file() else None
            if font:
                font_manager.fontManager.addfont(font)
                family = font_manager.FontProperties(fname=font).get_name()
            else:
                available = {f.name for f in font_manager.fontManager.ttflist}
                family = next((n for n in ('Noto Sans CJK SC', 'PingFang SC', 'Microsoft YaHei') if n in available), None)
                require(family, 'Chinese labels require --font /path/to/CJK.ttf, or use --lang en')
        else:
            family = 'DejaVu Sans'
        plt.rcParams.update({'font.family': family, 'font.size': 11, 'axes.labelcolor': INK,
                             'axes.edgecolor': '#9BAABA', 'axes.titlecolor': INK,
                             'text.color': INK, 'xtick.color': INK, 'ytick.color': INK,
                             'axes.spines.top': False, 'axes.spines.right': False,
                             'axes.titlepad': 15, 'figure.facecolor': 'white', 'axes.grid': True,
                             'grid.color': GRID, 'grid.linewidth': 0.65, 'axes.axisbelow': True,
                             'pdf.fonttype': 42, 'axes.unicode_minus': False})

    def t(self, zh, en):
        return zh if self.lang == 'zh' else en

    def save(self, fig, name):
        fig.savefig(self.output / f'{name}.pdf', bbox_inches='tight', metadata={'Title': name, 'CreationDate': None})
        fig.savefig(self.output / f'{name}.png', dpi=340, bbox_inches='tight')
        self.book.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    def j_axis(self, ax, *, x=False):
        label = self.t('相对差距 J（越小越好）', 'Relative gap J (lower is better)')
        ax.set_ylabel(label)
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        if x:
            ax.xaxis.set_major_formatter(PercentFormatter(1))

    def dots(self, ax, method, x, y, **kw):
        return ax.scatter(x, y, marker=MARKS[method], color=COLORS[method], **kw)

    def quality(self, problem, scores, name):
        fig, ax = plt.subplots(figsize=(6.8, 4.5), layout='constrained')
        methods = [m for m in METHODS if any(r['method'] == m for r in scores)]
        ymin, ymax = 0., 0.
        for i, method in enumerate(methods):
            group = [r for r in scores if r['method'] == method]
            data = [r['holdout_J'] for r in group]
            center, sd = mean(data), stdev(data)
            ymin, ymax = min(ymin, *data, center - sd), max(ymax, *data, center + sd)
            ax.errorbar(i, center, yerr=sd, color=COLORS[method], fmt='_', markersize=15, markeredgewidth=2,
                        capsize=4, linewidth=1.5, zorder=3)
            for offset, row in zip((-.19, -.28, -.37), group):
                self.dots(ax, method, i + offset, row['holdout_J'], s=41, edgecolors='white', linewidths=.55, zorder=4)
                ax.annotate(str(row['seed']), (i + offset, row['holdout_J']), xytext=(0, 6), textcoords='offset points',
                            color=MUTED, fontsize=7, ha='center')
        ax.set_xticks(range(len(methods)), [NAMES[m] for m in methods])
        ax.set(xlim=(-.58, len(methods)-.4), ylim=(ymin, ymax * 1.13),
               title=f'{problem} · ' + self.t('冻结冠军的训练外质量', 'Held-out quality of frozen champions'))
        ax.set_xlabel(self.t('原始点为独立种子，误差棒为均值 ± 样本标准差',
                             'Points: independent seeds. Error bars: mean ± sample SD.'))
        self.j_axis(ax)
        ax.grid(axis='x', visible=False)
        self.save(fig, name)

    def generalization(self, problem, scores, name):
        fig, ax = plt.subplots(figsize=(6.6, 5.2), layout='constrained')
        scores_on_axes = [r[key] for r in scores for key in ('train_J', 'holdout_J')]
        span = max(scores_on_axes) - min(scores_on_axes) or .01
        lo, hi = min(scores_on_axes) - .13 * span, max(scores_on_axes) + .17 * span
        ax.plot([lo,hi], [lo,hi], '--', color='#8995A4', lw=1, label=self.t('训练与外评相等','Equal gap'))
        for method in METHODS:
            group = [r for r in scores if r['method'] == method]
            if not group:
                continue
            self.dots(ax, method, [r['train_J'] for r in group], [r['holdout_J'] for r in group],
                      s=59, label=NAMES[method], zorder=3)
            for ix, row in enumerate(group):
                dx, dy = ((5, -10), (5, 5), (5, 5))[ix]
                ax.annotate(str(row['seed']), (row['train_J'], row['holdout_J']), xytext=(dx,dy),
                            textcoords='offset points', color=COLORS[method], fontsize=8)
        ax.set(xlim=(lo,hi), ylim=(lo,hi), xlabel=self.t('训练 J', 'Training J'),
               title=f'{problem} · '+self.t('训练与训练外表现', 'Training vs held-out performance'))
        ax.set_aspect('equal', adjustable='box')
        self.j_axis(ax, x=True)
        ax.set_ylabel(self.t('训练外 J（越小越好）','Held-out J (lower is better)'))
        ax.legend(loc='upper left', fontsize=9, frameon=False)
        self.save(fig, name)

    def seed_variation(self, problem, scores, name):
        fig, ax = plt.subplots(figsize=(8.8, 4.5), layout='constrained')
        offsets = {'u': -.25, 'eoh': 0, 'ross': .25}
        for method in METHODS:
            group = [r for r in scores if r['method'] == method]
            if not group:
                continue
            x = [SEEDS.index(r['seed']) + offsets[method] for r in group]
            train, held = ([r[k] for r in group] for k in ('train_J', 'holdout_J'))
            ax.vlines(x, train, held, colors=COLORS[method], alpha=.65, lw=1.6)
            ax.scatter(x, train, s=62, marker=MARKS[method], facecolors='white', edgecolors=COLORS[method], linewidths=1.4,
                       zorder=3)
            self.dots(ax, method, x, held, s=49, label=NAMES[method], zorder=4)
        ax.set_xticks(range(3), SEEDS)
        ax.set(xlim=(-.55, 2.55), xlabel=self.t('种子 · 空心为训练，实心为训练外','Search seed · open: training, filled: held out'),
               title=f'{problem} · '+self.t('按种子观察训练与训练外差距','Training and held-out gap by seed'))
        ax.set_ylim(min(0, ax.get_ylim()[0]), ax.get_ylim()[1] * 1.05)
        self.j_axis(ax)
        ax.legend(loc='upper center', ncol=3, frameon=False)
        self.save(fig, name)

    def paired(self, pairs):
        fig, axes = plt.subplots(1, 2, figsize=(11.1, 4.5), sharey=True, layout='constrained')
        for ax, method, column in zip(axes, ('eoh', 'ross'), ('U_minus_EoH', 'U_minus_Ross')):
            delta = [r[column] for r in pairs]
            avg = mean(delta)
            ax.axhline(0, color='#8191A0', linestyle='--', linewidth=1)
            ax.axhline(avg, color=COLORS['u'], linewidth=1.25,
                       label=self.t('平均差','Mean difference')+f' {avg:+.2%}')
            for wins in (True, False):
                subset = [(i+1, d) for i, d in enumerate(delta) if (d < 0) == wins]
                if subset:
                    x, y = zip(*subset)
                    self.dots(ax, 'u' if wins else method, x, y, s=24, alpha=.9, zorder=4)
            ax.set(title=f'U − {NAMES[method]}', xlim=(0, len(pairs)+1),
                   xlabel=self.t('按 LKH 路线长度排序的实例','Instances ordered by LKH tour length'))
            ax.legend(loc='upper center', fontsize=9, frameon=False)
            ax.yaxis.set_major_formatter(PercentFormatter(1))
        axes[0].set_ylabel(self.t('两方法的 J 差（负值表示 U 更好）','Difference in J (negative favors U)'))
        fig.suptitle('TSP · '+self.t('同一实例上的配对差异','Paired differences on the same instances'), fontsize=15)
        self.save(fig, 'tsp-04-instance-pairs')

    def cost_quality(self, scores):
        fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.75), sharey=True, layout='constrained')
        for ax, key, title, xlabel in zip(axes, ('train_solve_starts','holdout_worker_cpu_s'),
            (self.t('A  训练求解规模','A  Training evaluation volume'), self.t('B  训练外 CPU 开销','B  Held-out CPU cost')),
            (self.t('实际开始的实例求解（千次，含复核）','Actual instance-solve starts (thousands; incl. rechecks)'),
             self.t('60 例的求解进程 CPU 秒（含复核）','Worker CPU seconds across 60 cases (incl. rechecks)'))):
            scale = 1000 if key == 'train_solve_starts' else 1
            for method in METHODS:
                group = [r for r in scores if r['method'] == method]
                self.dots(ax, method, [r[key]/scale for r in group], [r['holdout_J'] for r in group],
                          s=42, label=NAMES[method], zorder=3)
            xlim = ax.get_xlim()
            ax.set(xlabel=xlabel, title=title, xlim=(0,xlim[1]*1.09), ylim=(0,max(r['holdout_J'] for r in scores)*1.19))
            ax.legend(loc='upper left', ncol=3, fontsize=8, frameon=False)
        self.j_axis(axes[0])
        axes[0].set_ylabel(self.t('训练外 J（越小越好）','Held-out J (lower is better)'))
        self.save(fig, 'tsp-06-quality-cost')

    def convergence(self, groups, problem, fixed=None):
        axes_data = defaultdict(list)
        for (p, method, seed, basis, _), values in groups.items():
            if p == problem and any(r['best_J'] not in ('',None) for r in values):
                axes_data[basis].append((method, seed, values))
        if not axes_data:
            return False
        titles = {'logical_slots': self.t('累计考察候选数（含初始化）','Candidates considered (including initialization)'),
                  'successful_responses': self.t('成功返回的演化候选数','Successful evolution responses'),
                  'historical_attempts': self.t('演化尝试数（历史协议）','Evolution attempts (historical protocol)')}
        if problem == 'tsp':
            series = [group for runs in axes_data.values() for group in runs]
            scores = [float(row['best_J']) for _, _, rows in series
                      for row in rows if row['best_J'] not in ('', None)]
            low, high = min(scores), max(scores)
            padding = .05 * (high - low) or .01
            end = max(rows[-1]['step'] for _, _, rows in series)
            for method in METHODS:
                basis = 'logical_slots' if method == 'ross' else 'successful_responses'
                runs = [run for run in axes_data.get(basis, []) if run[0] == method]
                if runs:
                    fig, ax = plt.subplots(figsize=(8.5, 2.8), layout='constrained')
                    self.convergence_panel(ax, runs, titles[basis])
                    ax.set(xlim=(0, end), ylim=(low - padding, high + padding),
                           ylabel=self.t('最佳训练 J（越小越好）','Best training J (lower is better)'))
                    ax.yaxis.set_major_locator(MaxNLocator(5))
                    self.save(fig, f'tsp-03-convergence-{method}')
            return True
        bases = [b for b in ('successful_responses','logical_slots','historical_attempts') if b in axes_data]
        fig, axes = plt.subplots(1, len(bases), figsize=(max(7.2, 5.5*len(bases)), 4.5),
                                squeeze=False, sharey=True, layout='constrained')
        for ax, basis in zip(axes[0], bases):
            self.convergence_panel(ax, axes_data[basis], titles[basis],
                                   fixed if basis == 'logical_slots' else None)
        axes[0][0].set_ylabel(self.t('截至该步最佳训练 J（越小越好）','Best training J so far (lower is better)'))
        title = self.t('真实搜索轨迹', 'Observed search trajectories')
        fig.suptitle(f'{problem.upper()} · {title}', fontsize=15)
        self.save(fig, f'{problem}-03-convergence')
        return True

    def convergence_panel(self, ax, runs, xlabel, fixed=None):
        styles = {501: '-', 502: '--', 503: ':'}
        groups_by_method = defaultdict(list)
        for method, seed, values in runs:
            pairs = {r['step']:float(r['best_J']) for r in values if r['best_J'] not in ('', None)}
            status = '' if values[0]['phase']=='completed' else self.t(' · 未完成',' · incomplete')
            ax.step(pairs.keys(), pairs.values(), where='post', color=COLORS[method], ls=styles[seed],
                    alpha=.62, linewidth=1.25, label=f'{NAMES[method]} {seed}'+status)
            groups_by_method[method].append(pairs)
        for method, series in groups_by_method.items():
            if len(series) == 3:
                common = sorted(set.intersection(*(set(s) for s in series)))
                if common:
                    ax.step(common, [mean(s[x] for s in series) for x in common], where='post', color=COLORS[method],
                            linewidth=2.3, label=NAMES[method]+' '+self.t('三种子均值','three-seed mean'))
        if fixed:
            ax.axhline(fixed['J'], color='#656D77', linestyle='-.', linewidth=1.2, label='Best Fixed H')
        ax.set(xlabel=xlabel, xlim=(0,None))
        ax.xaxis.set_major_locator(MaxNLocator(6, integer=True))
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.legend(frameon=False, fontsize=9, loc='upper right')

    def progress(self, problem, rows, date):
        fig, ax = plt.subplots(figsize=(8.5, .46*len(rows)+1.75), layout='constrained')
        for i, row in enumerate(rows):
            m, ratio = row['method'], row['count']/row['target']
            ax.barh(i, 1, color='#E8EDF1', height=.56)
            finished = row.get('train_state') == 'completed' and row['count'] == row['target']
            patch=ax.barh(i, ratio, color=COLORS[m], height=.56, alpha=1 if finished else .78)
            if not finished:
                patch[0].set_hatch('///')
                patch[0].set_edgecolor(COLORS[m])
            word = self.t('已完成','complete') if finished else self.t('未完成','incomplete')
            ax.text(1.025, i, f'{row["count"]}/{row["target"]} · {word}', va='center', color=INK, fontsize=10)
        ax.set_yticks(range(len(rows)), [f'{NAMES[r["method"]]} {r["seed"]}' for r in rows])
        ax.set(xlim=(0, 1.27), ylim=(len(rows)-.48,-.52), xlabel=self.t('各自预算的完成比例','Fraction of each run’s own budget'),
               title=f'{problem.upper()} · '+self.t(f'训练进度快照（{date}）',f'Training progress snapshot ({date})'))
        ax.set_xticks([0,.25,.5,.75,1.]); ax.xaxis.set_major_formatter(PercentFormatter(1))
        ax.grid(axis='y', visible=False)
        self.save(fig, f'{problem}-01-training-progress')


def links(name):
    return f'[{name}.pdf]({name}.pdf) · [PNG]({name}.png)'


def make_index(out, dates, units, pairs, groups, fixed, additional):
    counts = {p: sorted(f'{NAMES[m]} {s}' for (problem, m, s, basis, _) in groups
                        if problem == p and basis == 'successful_responses') for p in ('tsp','fjsp','obp')}
    tsp_methods = ('u', 'eoh')
    tsp_curves = {(m, s): rows for (p, m, s, basis, _), rows in groups.items()
                  if p == 'tsp' and m in tsp_methods and basis == 'successful_responses'
                  and len(rows) == 1000 and rows[0]['phase'] == 'completed'}
    tsp_gaps = {f'{NAMES[m]} {s}' for m in tsp_methods for s in SEEDS if (m, s) not in tsp_curves}
    tsp_scope = ('目前已核实 Ross-style 三条阶梯曲线。U/EoH 的轨迹覆盖见下方说明。' if tsp_gaps else
                 'U、EoH 和 Ross-style 的九条阶梯曲线及各自的三种子均值均已核实。')
    tsp_convergence_links = '<br>'.join(
        f"{NAMES[m]} · {links(f'tsp-03-convergence-{m}')}"
        for m in METHODS if any(p == 'tsp' and method == m and any(r['best_J'] not in ('', None) for r in rows)
                                for (p, method, _, _, _), rows in groups.items()))
    delta = {}
    for method in ('EoH','Ross'):
        v = [r[f'U_minus_{method}'] for r in pairs]
        delta[method] = dict(mean=mean(v), wins=sum(x < 0 for x in v), ties=sum(x == 0 for x in v))
    r = {m: [p for p in units if p['method'] == m] for m in METHODS}
    averages = {m: mean(p['holdout_J'] for p in rows) for m, rows in r.items()}
    holdout_gaps = {m: mean(p['holdout_J'] - p['train_J'] for p in rows) for m, rows in r.items()}
    costs = {m: (min(p['train_solve_starts'] for p in rows), max(p['train_solve_starts'] for p in rows),
                 mean(p['holdout_worker_cpu_s'] for p in rows)) for m, rows in r.items()}
    idx = ['# 论文实验图表', '', f'集群进度取自 {dates} 的最近回执。实线轨迹来自候选记录，进度条来自独立的状态快照。', '',
           '[整套图 PDF](paper-figures.pdf) · [绘图源码](../../tools/paper_figures.py) · [输入文件与 SHA-256](source-manifest.json) · [科研汇报](../RESEARCH_PROGRESS.md)', '',
           '实验以 U 为研究主体。EoH 提供直接演化求解规则的对照，Ross-style 提供同状态和规则库下的传统路由对照，Best Fixed H 检验按状态切换规则的收益。', '',
           '在 TSP 上，三种方法使用相同的训练外实例，并以统一设置的 LKH 求解结果作为评价参考。所有 J 均为相对参照成本的平均差距，越小越好。', '',
           '## TSP', '',
           '| 图 | 读图要点 | 数据与统计口径 |', '| --- | --- | --- |',
           f"| 01 · {links('tsp-01-holdout-quality')} | U 的训练外平均 J 为 {averages['u']:.2%}，接近 Ross-style 的 {averages['ross']:.2%}。EoH 的均值最低，为 {averages['eoh']:.2%}。 | [逐种子数据](tsp-seed-quality-cost.csv)和[方法汇总](tsp-method-summary.csv)。每种方法三个独立搜索，误差棒为均值 ± 样本标准差。 |",
           f"| 02 · {links('tsp-02-train-vs-holdout')} | 每点是一个冻结冠军，横轴为训练 J，纵轴为训练外 J。虚线表示两项 J 相等。九个冠军的训练外 J 均高于训练 J，U、EoH、Ross-style 平均分别高 {100*holdout_gaps['u']:.2f}、{100*holdout_gaps['eoh']:.2f}、{100*holdout_gaps['ross']:.2f} 个百分点。 | [逐种子数据](tsp-seed-quality-cost.csv)，训练与外评成对显示，坐标等尺度。 |",
           f"| 03 · {tsp_convergence_links} | {tsp_scope}细线为各次搜索截至当步的最佳训练 J，粗线为三种子均值。 | [有序候选数据](training-curves.csv)。U 和 EoH 统计模型成功返回的演化候选。Ross-style 统计搜索考察的候选，含初始化。 |",
           f"| 04 · {links('tsp-04-instance-pairs')} | U 在 {delta['EoH']['wins']}/60 例优于 EoH，在 {delta['Ross']['wins']}/60 例优于 Ross-style。平均差分别为 {delta['EoH']['mean']:+.2%}、{delta['Ross']['mean']:+.2%}，负值对 U 有利。 | [60 例配对表](tsp-instance-pairs.csv)与[原始 540 条方法×种子×实例记录](tsp-instance-seed-raw.csv)。先在同一实例内平均三个种子，每例只作一个差值，按 LKH 路长排序。 |",
           f"| 05 · {links('tsp-05-seed-variation')} | 同一种子内的空心点、实心点分别表示训练、外评。U 的 501 种子在三个 U 冠军中训练 J 最高，外评 J 最低。 | [逐种子数据](tsp-seed-quality-cost.csv)，展示九个冠军的两次测量。 |",
           f"| 06 · {links('tsp-06-quality-cost')} | U 的训练求解启动数少于 EoH。外评求解进程 CPU 时间平均为 U {costs['u'][2]:.2f} 秒、EoH {costs['eoh'][2]:.2f} 秒。 | [计时与成本](tsp-seed-quality-cost.csv)。训练统计实际启动的实例求解，含复核和启动后失败。外评均基于同一台 Mac 的双遍复核，横轴为逐例求解进程 CPU 秒之和。 |", '',
           '实际训练求解启动数范围和外评 CPU 秒均值如下。训练求解数包含初始化，不含共享 H 生成、模型推理和排队。训练 CPU 只在有回执的方法中保留。', '',
           '| 方法 | 每种子训练求解启动数范围 | 平均外评求解进程 CPU 秒 |', '| --- | ---: | ---: |',
           *(f'| {NAMES[m]} | {a:,}–{b:,} | {c:.3f} |' for m, (a,b,c) in costs.items()), '',
           '各方法使用的训练计算预算不可由候选数换算。已知 token 为记录小计，未返回用量的请求单列。正式外评所有 60 个实例都是 50 城市、均匀分布，现有数据不支持按城市规模或分布分组。', '',
           '## FJSP', '',
           f"- **训练进度**　{links('fjsp-01-training-progress')}。以最新回执为准，进度条按各自预算展示，只用于说明完成程度。数据见[训练进度快照](training-progress.csv)。",
           f"- **训练轨迹**　{links('fjsp-03-convergence')}。Ross-style 501 的横轴为累计考察候选数，历史 U 501 的横轴为演化尝试数。经核对实例和下界，Ross-style 面板可画同一训练集的 Best Fixed H 水平线（J = {fixed['J']:.6f}）。正式外评待补。数据见[有序候选数据](training-curves.csv)及[固定 H 逐例记录](../fjsp-execution-20261112/fixed-H-reuse-v3/fixed-H-train21-J.csv)。", '',
           '## OBP', '',
           f"- **训练进度**　{links('obp-01-training-progress')}。数据见[训练进度快照](training-progress.csv)。中途成绩不参与正式外评排序。", '']
    if counts['obp']:
        idx += [f"- **训练轨迹**　{links('obp-03-convergence')}。曲线只到已取得的真实候选，未完成的种子各自注明。", '']
    if additional:
        idx += ['## 新增的正式留出结果', '', *additional, '']
    idx += ['## 轨迹覆盖与缺项', '',
            *(f"- **{p.upper()}**　当前 R15 成功返回序列已读到 " + ('、'.join(found) if found else '无') + '。'
              for p, found in counts.items()),
            ('- TSP U/EoH 各三个种子均已完成训练及正式外评。仍待取回逐步训练记录的有 '
             + '、'.join(sorted(tsp_gaps)) + '。' if tsp_gaps else
             '- TSP U/EoH 各三个种子的逐步训练记录均已取回，与冻结冠军训练 J 核对一致。'),
            '- FJSP 和 OBP 的逐步训练记录覆盖以表中列出的种子为准。FJSP 历史 U 501 的曲线单列。',
            '- 缺少各方法逐候选累计 CPU 或统一计时回执，暂不提供按训练计算成本对齐的收敛图。OBP 固定 H 需要可核验的逐例成本与同一参照。FJSP、OBP 正式外评数据到齐后再生成同集比较。',
            '- 阶梯线仅保持已知的截至当步最优值。均值使用三个种子都有观测的步数。各曲线的结束位置由实际记录决定。', '',
            '## D06 · 评价参考如何产生', '',
            'D06 是项目中给 TSP 固定参考值生成方案的编号。LKH 是启发式求解器。返回的闭合路线是可行解，给出数学最优路线长度的上界，未提供最优性证明。', '',
            '- **版本与调用**　绑定的二进制为 LKH 3.0.13。实际编译输入为项目留档的第三方候选源码，官方源码逐字节等价未核实。每个实例启动一个进程，最多 10 轮内部搜索（`RUNS=10`），每轮最多 1000 次试探（`MAX_TRIALS=1000`），单轮搜索内部按 10 秒 CPU 计时检查（`TIME_LIMIT=10`）。参考生成种子为 `SEED=1`。外层对每个实例进程另有 120 秒 CPU 硬上限和 150 秒墙钟上限。',
            '- **路线长度**　用单位方形上的原始浮点欧氏距离构造矩阵，乘以 1,000,000 后按 `floor(x + 0.5)` 转为 LKH 的显式整数矩阵。取得闭合路线后，用原始浮点欧氏距离重算含返程的长度，作为该实例的评价分母。',
            '- **训练与留出分别生成**　核对了训练 20 例与留出 60 例的参考文件。二进制、参数和距离协议一致，实例内容与执行回执不同。留出集回执确认 60 个 LKH 进程全部结束。',
            '- **原始证据**　[冻结规格](../../experiments/triad/lkh.pending.json) · [参数写入与外层执行](../../experiments/triad/assets.py) · [原操作规约](../../docs/统一实验包操作指南.md)。正式训练和外评参考文件及执行回执见[输入清单](source-manifest.json)。', '',
            '## 复绘', '',
            '在仓库根目录使用装有 [`requirements-closeout.txt`](../../requirements-closeout.txt) 的 Python。默认读归档的 TSP 历史，输出中文 340 DPI PNG 和矢量 PDF。', '',
            '```bash', 'python3 -B tools/paper_figures.py', '```', '',
            '英文标签用 `python3 -B tools/paper_figures.py --lang en --output reports/paper-figures-en`。Matplotlib 找不到中文字体时可用 `--font /path/to/CJK.ttf`。`--prototype-root` 和 `--outbox` 可指定已有输入目录的位置。', '',
            'TSP U/EoH 的六份原始历史保存在[归档 CSV](inputs/tsp-training-history-20261125.csv.gz)。需要重取时，脚本使用平时的 SSH 登录方式，只读取已经核验的六个归档断点。', '',
            '```bash', 'python3 -B tools/pull_tsp_history.py',
            'python3 -B tools/paper_figures.py --history "$HOME/Developer/transfer-outbox/tsp-training-history-20261125.csv"', '```', '',
            '其他已部署训练记录可通过通用只读入口取得。', '',
            '```bash',
            'ssh hdl-cluster \\',
            '  \'"$HOME/hdl-envs/portable-v2/bin/python" -I -B - "$HOME/hdl-deploy"\' \\',
            '  < tools/figure_training_history.py > "$HOME/Downloads/hdl-training-history.csv" && \\',
            'python3 -B tools/paper_figures.py --history "$HOME/Downloads/hdl-training-history.csv"',
            '```', '',
            '后续先刷新[实验状态矩阵](../EXPERIMENT_STATUS.md)，再运行同一绘图命令。正式外评图纳入预先指定的同一留出集与参照上的三种子核验结果。验证集结果不会当成正式测试。', '']
    if not tsp_gaps:
        at = {step: [mean(float(tsp_curves[m, s][step - 1]['best_J']) for s in SEEDS)
                     for m in tsp_methods] for step in (500, 1000)}
        idx[idx.index('## FJSP'):idx.index('## FJSP')] = [
            f'图 03 中，第 500 个成功返回候选时，U 的平均最佳训练 J 为 {at[500][0]:.2%}，'
            f'EoH 为 {at[500][1]:.2%}。到第 1000 个时，两者分别为 {at[1000][0]:.2%} 和 {at[1000][1]:.2%}。'
            '该横轴衡量候选进度，计算开销另见图 06。', '']
    (out / 'README.md').write_text('\n'.join(idx), encoding='utf-8')


def final_holdouts(figures, out, selected):
    grouped = defaultdict(lambda: defaultdict(list))
    for (problem, method, seed), row in selected.items():
        if problem in ('fjsp', 'obp') and method in METHODS and formal(row):
            grouped[problem, tuple(row['holdout_identity'])][method].append(
                dict(method=method, seed=seed, train_J=row['train_J'], holdout_J=row['holdout_J']))
    counts = defaultdict(int)
    links_list = []
    for (problem, _), methods in grouped.items():
        scores = [r for rows in methods.values() if {r['seed'] for r in rows} == set(SEEDS) for r in rows]
        if not scores:
            continue
        counts[problem] += 1
        base = f'{problem}-holdout-{counts[problem]}'
        table(out, base, scores)
        figures.quality(problem.upper(), scores, base+'-quality')
        figures.generalization(problem.upper(), scores, base+'-train-vs-holdout')
        figures.seed_variation(problem.upper(), scores, base+'-seeds')
        links_list.append(f'- [{base} 数据]({base}.csv) · '+links(base+'-quality')+' · '+links(base+'-train-vs-holdout')+' · '+links(base+'-seeds'))
    return links_list


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--prototype-root', type=Path, default=PROTOTYPES)
    parser.add_argument('--outbox', type=Path, default=OUTBOX)
    parser.add_argument('--snapshot', type=Path, default=ROOT/'reports/experiment-status-snapshot.json')
    parser.add_argument('--history', type=Path, default=TSP_HISTORY, help='History CSV or CSV.GZ; defaults to the archived TSP data')
    parser.add_argument('--lang', choices=('zh','en'), default='zh')
    parser.add_argument('--font', type=Path)
    args = parser.parse_args()
    source = Inputs()
    snapshot = source.data(args.snapshot)['records']
    selected = current_rows(snapshot)
    as_of = max(r['as_of'][:10] for r in snapshot)
    scores, instances, pairs, aggregates = tsp_evidence(source, args.prototype_root, args.outbox)
    history = local_series(source, args.prototype_root, args.outbox)
    raw_history = source.read(args.history)
    history.extend(records(gzip.decompress(raw_history) if args.history.suffix == '.gz' else raw_history))
    groups = chosen_series(history, selected)
    fixed = fixed_h(source, args.prototype_root)
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    table(out, 'tsp-seed-quality-cost', scores)
    table(out, 'tsp-method-summary', aggregates)
    table(out, 'tsp-instance-seed-raw', instances)
    table(out, 'tsp-instance-pairs', pairs)
    table(out, 'training-curves', [r for values in groups.values() for r in values], COLUMNS)
    progress_cols = ('problem','method','seed','as_of','train_state','count','target','train_J')
    progress = [{k:r.get(k) for k in progress_cols} for (p,m,s), r in selected.items()
                if p in ('fjsp','obp') and m in METHODS and r.get('count') is not None and r.get('target')]
    progress.sort(key=lambda r: (r['problem'], METHODS.index(r['method']), r['seed']))
    table(out, 'training-progress', progress, progress_cols)
    from matplotlib.backends.backend_pdf import PdfPages
    with PdfPages(out/'paper-figures.pdf', metadata={'Title': 'Experimental figures / Heuristic Design Lab',
                                                   'CreationDate': None}) as book:
        figures = Figures(out, args.lang, args.font, book)
        figures.quality('TSP', scores, 'tsp-01-holdout-quality')
        figures.generalization('TSP', scores, 'tsp-02-train-vs-holdout')
        figures.convergence(groups, 'tsp')
        figures.paired(pairs)
        figures.seed_variation('TSP', scores, 'tsp-05-seed-variation')
        figures.cost_quality(scores)
        for problem in ('fjsp','obp'):
            figures.progress(problem, [r for r in progress if r['problem']==problem], as_of)
            figures.convergence(groups, problem, fixed=fixed if problem=='fjsp' else None)
        additional = final_holdouts(figures, out, selected)
    make_index(out, as_of, scores, pairs, groups, fixed, additional)
    (out/'source-manifest.json').write_text(json.dumps({'as_of': as_of, 'matplotlib': matplotlib.__version__,
        'language': args.lang, 'sha256_by_source': source.sources}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(out/'README.md')


if __name__ == '__main__':
    main()
