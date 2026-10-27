#!/usr/bin/env python3
"""Read-only historical audit and figures. Never imports project executors.

Uses standard library + matplotlib/numpy only. All writes stay in a NEW
derived report tree; no API, scheduler, candidate generation or solver calls.
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tarfile
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'reports/组会实验盘点-20261027-v1'
TZ = ZoneInfo('Asia/Manila')
SOURCES = {}
CHECKS = []
FIGURES = []


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def record(path):
    path = Path(path).resolve()
    key = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    SOURCES[key] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    return path


def js(path):
    return json.loads(record(ROOT / path).read_text())


def rows(path):
    return list(csv.DictReader(io.StringIO(record(ROOT / path).read_text(encoding='utf-8-sig'))))


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def save_csv(path, values, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or list(dict.fromkeys(k for r in values for k in r))
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for row in values:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def truth(value):
    return str(value).lower() == 'true'


def number(value):
    return float(value) if value not in (None, '', 'null', 'None') else None


def require(condition, message):
    if not condition:
        raise AssertionError(message)
    CHECKS.append(message)


def inventory(out):
    """One metadata walk, then bounded protocol/checkpoint reads, no response text."""
    if (out / '文件索引.csv').exists():
        return json.loads((out / '清点快照.json').read_text())
    file_index = []
    root_dirs = ['runs', 'reports', 'docs', 'preparations', 'experiments', 'provenance']
    for base in root_dirs:
        for parent, directories, files in os.walk(ROOT / base):
            directories[:] = sorted(d for d in directories if d not in ('.git', '.venv', '__pycache__') and not (Path(parent) / d).is_relative_to(out))
            for name in sorted(files):
                p = Path(parent) / name
                if not (p.suffix.lower() in ('.json', '.jsonl', '.csv', '.svg', '.pdf', '.png', '.md', '.zip', '.gz', '.py', '.fjsp') or name.endswith('.sha256')):
                    continue
                st = p.stat()
                file_index.append({'path': str(p.relative_to(ROOT)), 'bytes': st.st_size,
                    'mtime_ns': st.st_mtime_ns, 'kind': '.tar.gz' if name.endswith('.tar.gz') else p.suffix.lower()})
    save_csv(out / '文件索引.csv', file_index)
    assets = []
    for base in ('runs', 'reports', 'preparations'):
        for folder in sorted((ROOT / base).iterdir()):
            if not folder.is_dir() or folder == out:
                continue
            prefix = str(folder.relative_to(ROOT)) + '/'
            index = [r for r in file_index if r['path'].startswith(prefix)]
            small = []
            for item in index:
                p = ROOT / item['path']; name = p.name.lower()
                if name not in ('protocol.json', 'checkpoint.json', 'summary.json', 'progress.json', 'end_summary.json', 'report.json', 'plan.json', 'completion.json', 'search_status.json', 'stop.json'):
                    continue
                if item['bytes'] > 150_000_000:
                    continue
                try:
                    data = js(item['path'])
                    if not isinstance(data, dict):
                        continue
                    cfg = data.get('config', {})
                    brief = {'file': item['path'], 'keys': list(data)[:35]}
                    for key in ('version', 'mode', 'phase', 'status', 'generation', 'cursor', 'init_cursor', 'seed', 'best_fitness', 'fitness', 'error_type'):
                        if key in data and not isinstance(data[key], (dict, list)):
                            brief[key] = data[key]
                    if isinstance(cfg, dict):
                        brief['config'] = {k: cfg[k] for k in ('mode', 'seeds', 'seed', 'generations', 'population_size', 'request_hard_cap', 'total_request_cap', 'instance_timeout', 'solve_seed', 'api_mode', 'type', 'space') if k in cfg}
                        brief['model'] = cfg.get('provider', {}).get('model') if isinstance(cfg.get('provider'), dict) else None
                    for key in ('attempts', 'evaluations', 'population', 'tasks', 'instances', 'groups', 'requests', 'rankings'):
                        if isinstance(data.get(key), (dict, list)):
                            brief[key + '_count'] = len(data[key])
                    if isinstance(data.get('population'), list):
                        fs = [x['fitness'] for x in data['population'] if isinstance(x, dict) and isinstance(x.get('fitness'), (int, float))]
                        if fs:
                            brief['population_best'] = max(fs)
                    if data.get('inflight'):
                        brief['inflight_record_present'] = True
                    small.append(brief)
                except (ValueError, OSError, TypeError) as exc:
                    small.append({'file': item['path'], 'read_error': str(exc)})
            assets.append({'asset': str(folder.relative_to(ROOT)), 'file_count': len(index),
                'bytes': sum(r['bytes'] for r in index),
                'reports': [r['path'] for r in index if Path(r['path']).suffix == '.md' and ('REPORT' in Path(r['path']).name or Path(r['path']).name == 'README.md')],
                'tables': [r['path'] for r in index if Path(r['path']).suffix == '.csv'],
                'archives': [r['path'] for r in index if r['kind'] in ('.tar.gz', '.zip')],
                'snapshots': small})
    archive_index = []
    for item in file_index:
        if item['kind'] not in ('.tar.gz', '.zip'):
            continue
        entry = {**item, 'archive_sha256': sha(ROOT / item['path'])}
        if item['kind'] == '.tar.gz':
            try:
                with tarfile.open(ROOT / item['path']) as t:
                    members = t.getmembers()
                entry.update(member_count=len(members), sample=[m.name for m in members[:6]],
                             top_names=sorted({m.name.split('/')[0] for m in members}), integrity='目录可读；不等于全部结果认证')
            except (tarfile.TarError, EOFError, OSError) as exc:
                entry.update(integrity='不可完整读取/历史不完整包，未解压或修补', error=str(exc))
        archive_index.append(entry)
    save_json(out / '资产快照.json', assets)
    save_json(out / '压缩归档索引.json', archive_index)
    git = subprocess.check_output(['git', 'log', '--all', '-100', '--format=%h %ad %s', '--date=short'], cwd=ROOT, text=True)
    (out / '代码版本索引.txt').write_text(git)
    applicable = [p / 'AGENTS.md' for p in [ROOT, *ROOT.parents]]
    agents = [str(p) for p in applicable if p.exists()]
    agents += [r['path'] for r in file_index if Path(r['path']).name == 'AGENTS.md']
    snapshot = {'date': '2026-10-27', 'timezone': str(TZ), 'head': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'branch': subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
        'git_status_at_start': subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True),
        'applicable_AGENTS': agents, 'file_count': len(file_index), 'asset_folders': len(assets),
        'archive_count': len(archive_index), 'coverage': root_dirs, 'new_API_requests': 0, 'new_FJSP_solves': 0,
        'limits': '文件清单为本工作树物理资产；Git全分支提交仅作版本索引，不推定其他工作树正式运行状态。'}
    save_json(out / '清点快照.json', snapshot)
    return snapshot


def checked_result(path, expected_fitness=None, count=21):
    d = js(path)
    require(d.get('valid') is True and len(d['instances']) == count, str(path) + ': complete valid batch')
    require(len({r['file'] for r in d['instances']}) == count, str(path) + ': unique instance list')
    for r in d['instances']:
        require(abs(r['score'] + r['makespan'] / r['lower_bound']) < 1e-11, str(path) + '/' + r['file'] + ': score arithmetic')
        if r.get('recheck_physical_schedule_sha256'):
            require(r['physical_schedule_sha256'] == r['recheck_physical_schedule_sha256'], str(path) + '/' + r['file'] + ': retained two-pass physical hash')
    require(abs(statistics.fmean(r['score'] for r in d['instances']) - d['fitness']) < 1e-11, str(path) + ': full Fitness arithmetic')
    if expected_fitness is not None:
        require(abs(d['fitness'] - expected_fitness) < 1e-11, str(path) + ': table agrees with raw result')
    return d


def normalise(out):
    data = out / '绘图输入'
    base = 'reports/tier2-baseline-a-train21-seed501-20261024-v1/'
    supp = 'reports/baseline-a-supplemental-T30-seed501-20261024-v1/'
    b1 = 'reports/b1-ns-recovery-B-execution-20261023/'
    b2 = 'reports/h01-state-weight-search-seed501-batch-v3-20261020/'
    grid_dir = 'reports/a4-evidence-protocol-20261024-v1/'
    single = rows(base + 'Single_ranking.csv')
    pairs = rows(supp + 'Composite_pairs_45.csv')
    source_rows = rows(base + 'Sources.csv')
    raw = {}
    for r in single:
        s = next(q for q in source_rows if q['strategy'] == r['strategy'])
        require(sha(ROOT / s['result_path']) == s['result_sha256'], 'single source hash ' + r['strategy'])
        raw[r['strategy']] = checked_result(s['result_path'], float(r['fitness']))
    for r in pairs:
        require(truth(r['valid']), 'composite valid ' + r['strategy'])
        require(sha(ROOT / r['result_path']) == r['result_sha256'], 'pair source hash ' + r['strategy'])
        raw[r['strategy']] = checked_result(r['result_path'], float(r['fitness']))
    require(len(single) == 10 and len(pairs) == 45, '10 singles / 45 unordered pairs')
    require(sum(r['source'] == 'Supplemental-T30' for r in pairs) == 6, 'six new T30 pairs only')
    h0, equal = raw['H0']['fitness'], raw['H0_H1_WS']['fitness']
    base_protocol = js(base + 'Protocol.json')
    supp_protocol = js(supp + 'Protocol.json')
    require(base_protocol['H_order'] == supp_protocol['H_order'], 'A and T30 H order')
    require([(r['file'], r['sha256'], r['LB']) for r in base_protocol['instances']] ==
            [(r['file'], r['sha256'], r['LB']) for r in supp_protocol['instances']], 'A and T30 train21 SHA/LB/order')
    for r in pairs:
        r['protocol_source'] = '独立T30补测' if r['source'] == 'Supplemental-T30' else '原Baseline-A：T15或已认证历史缓存'
    save_csv(data / '01_单H.csv', single)
    save_csv(data / '02_等权45对.csv', pairs)
    grid = rows(grid_dir + 'H01_grid_21.csv')
    require(len(grid) == 21 and all(truth(r['valid']) and int(r['complete_instances']) == 21 for r in grid), 'grid 21/21 complete')
    for r in grid:
        require(sha(ROOT / r['result_path']) == r['result_sha256'], 'grid result hash ' + r['id'])
        checked_result(r['result_path'], float(r['fitness']))
    require(max(float(r['fitness']) for r in grid) == equal, 'grid best equals known equal pair')
    save_csv(data / '03_静态权重21点.csv', grid)
    checkpoints = {
        'B1': js('runs/b1-ns-recovery-B-v1-20261022/r501/B/checkpoint.json'),
        'B2': js('runs/h01-state-weight-search-seed501-batch-v3-20261020/r501/B/checkpoint.json')}
    b1rows = rows(b1 + 'Candidates.csv')
    b2rows = [r for r in rows(b2 + 'Candidates.csv') if r['kind'] == 'LLM_new']
    curves = []
    for name, cp in checkpoints.items():
        byid = {r['id']: r for r in (b1rows if name == 'B1' else b2rows)}
        best = equal if name == 'B2' else None
        curves.append({'method': name, 'query': 0, 'id': '共同人工P0' if name == 'B2' else '尚未形成P0',
                       'fitness': None, 'best_so_far': best, 'status': 'start', 'duplicate': False})
        for i, attempt in enumerate(cp['attempts'], 1):
            tid = attempt['id']; r = byid.get(tid)
            duplicate = attempt['status'] == 'duplicate' or bool(r and r.get('duplicate_of'))
            valid = bool(r) and truth(r['full_valid'] if name == 'B1' else r['valid'])
            value = float(r['fitness']) if valid else None
            if value is not None:
                ev = cp['evaluations'][tid]['result']
                require(ev['valid'] and len(ev['instances']) == 21 and abs(ev['fitness'] - value) < 1e-11, name + '/' + tid + ': native evaluation matches exported row')
                require(abs(statistics.fmean(x['score'] for x in ev['instances']) - value) < 1e-11, name + '/' + tid + ': native full mean')
                best = value if best is None else max(best, value)
            curves.append({'method': name, 'query': i, 'id': tid, 'operator': attempt['operator'],
                           'fitness': value, 'best_so_far': best, 'status': attempt['status'], 'duplicate': duplicate,
                           'original_order_source': 'checkpoint.attempts', 'valid_complete': valid})
        require(len([x for x in curves if x['method'] == name and x.get('valid_complete')]) == (14 if name == 'B1' else 19), name + ': valid candidate count')
    require([r['id'] for r in b1rows] == [a['id'] for a in checkpoints['B1']['attempts']], 'B1 CSV order is native request order')
    require(len(checkpoints['B2']['attempts']) == 20, 'B2 20 logical slots including duplicate')
    save_csv(data / '04_搜索全槽轨迹.csv', curves)
    populations = []
    for method, path in [('B1', b1 + 'Population_members.csv'), ('B2', b2 + 'Population_members.csv')]:
        for r in rows(path):
            r['method'] = method; populations.append(r)
    save_csv(data / '04_种群成员.csv', populations)
    b1summary = js(b1 + 'Summary.json')
    b2evidence = js(b2 + 'Evidence.json')
    best_b1 = max(r['fitness'] for r in curves if r['method'] == 'B1' and r.get('valid_complete'))
    best_b2 = max(r['fitness'] for r in curves if r['method'] == 'B2' and r.get('valid_complete'))
    baseline_rows = [
        {'method': 'H0 单成员', 'fitness': h0, 'source': base + 'Single_ranking.csv', 'scope': '单策略；历史缓存'},
        {'method': '单H Oracle（事后诊断）', 'fitness': js(base + 'Oracle.json')['fitness'] if 'fitness' in js(base + 'Oracle.json') else js(base + 'Summary.json')['Oracle_fitness'], 'source': base + 'Oracle.json', 'scope': '实例级事后选择；不可部署'},
        {'method': 'H0/H3 等权', 'fitness': raw['H0_H3_WS']['fitness'], 'source': supp + 'Composite_pairs_45.csv', 'scope': '45对综合第2'},
        {'method': 'H0/H1 等权', 'fitness': equal, 'source': supp + 'Composite_pairs_45.csv', 'scope': '45对/21点网格最佳已测'},
        {'method': '历史B1：10H自由搜索', 'fitness': best_b1, 'source': b1 + 'Candidates.csv', 'scope': '19槽/14有效；P1，P2未完成'},
        {'method': '历史B2：H01动态权重', 'fitness': best_b2, 'source': b2 + 'Candidates.csv', 'scope': '20演化槽/19新有效；另有P0/网格投入'}]
    save_csv(data / '05_训练质量参照.csv', baseline_rows)
    champion = checkpoints['B2']['evaluations']['B/g0001/000000']['result']
    equal_rows = {r['file']: r for r in raw['H0_H1_WS']['instances']}
    require(set(equal_rows) == {r['file'] for r in champion['instances']}, 'B2 vs WS: full 21 instance pairing')
    instance_delta = []
    for r in champion['instances']:
        old = equal_rows[r['file']]
        require(r['lower_bound'] == old['lower_bound'], 'B2 vs WS paired LB ' + r['file'])
        gain = r['score'] - old['score']
        instance_delta.append({'file': r['file'], 'LB': r['lower_bound'], 'B2_Cmax': r['makespan'],
            'equal_Cmax': old['makespan'], 'delta_Cmax': r['makespan'] - old['makespan'],
            'delta_score': gain, 'delta_F_contribution': gain / 21, 'winner': 'B2' if gain > 0 else 'equal' if gain < 0 else 'tie'})
    require(abs(sum(r['delta_F_contribution'] for r in instance_delta) - (best_b2 - equal)) < 1e-11, 'B2 normalized per-instance contributions sum to complete delta')
    save_csv(data / '06_B2逐实例差异.csv', instance_delta)
    f2 = rows('reports/fusion-v2-train21-seed501-20261023-v2/Ranking.csv')
    f3 = rows('reports/fusion-v3-borda-train21-seed501-20261024-v1/Ranking.csv')
    mechanism = next(r for r in rows('reports/fusion-v2-train21-seed501-20261023-v2/Common_state_summary.csv') if r['source'] == 'H0_H1_WEIGHTED_SUM')
    ranks = next(r for r in rows('reports/fusion-v3-borda-train21-seed501-20261024-v1/diagnosis/Common_state_summary.csv') if r['source'] == 'H0_H1_WEIGHTED_SUM')
    require(mechanism['states'] == ranks['states'] == '3800', 'fusion diagnostic denominator shared WS trace 3800')
    # Recount the saved action records, without rerunning H, U or a scheduler.
    paths=['reports/fusion-v2-train21-seed501-20261023-v2/Common_state_actions.csv.gz',
           'reports/fusion-v3-borda-train21-seed501-20261024-v1/diagnosis/Actions.csv.gz']
    with gzip.open(record(ROOT/paths[0]),'rt') as f:
        action2=[r for r in csv.DictReader(f) if r['source_strategy']=='H0_H1_WEIGHTED_SUM']
    with gzip.open(record(ROOT/paths[1]),'rt') as f:
        action3=[r for r in csv.DictReader(f) if r['source']=='H0_H1_WEIGHTED_SUM']
    require([(r['file'],r['step'],r['state_sha256']) for r in action2] == [(r['file'],r['step'],r['state_sha256']) for r in action3], 'Fusion V2/V3 offline sample state identities and order match')
    require(len(action2)==len(action3)==3800,'saved common-state action rows: 3800')
    for op in ('MAX','MIN'):
        require(sum(r[op+'_action_index']!=r['WEIGHTED_SUM_action_index'] for r in action2)==int(mechanism[op+'_diff_WS']), 'saved action differences recounted '+op)
        require(sum(int(r[op+'_ties_at_max'])>1 for r in action2)==int(mechanism[op+'_tied_states']), 'saved top ties recounted '+op)
    require(sum(r['BORDA_action']!=r['WS_action'] for r in action3)==int(ranks['BORDA_diff_WS']), 'saved Borda action differences recounted')
    fusion = []
    for op in ('WEIGHTED_SUM', 'MAX', 'MIN', 'BORDA'):
        r = next(q for q in (f3 if op == 'BORDA' else f2) if q['strategy'] == 'H0_H1_' + op)
        fit = number(r.get('fitness', r.get('official_fitness'))); require(fit is not None, 'accepted H01 fusion result ' + op)
        diff = 0 if op == 'WEIGHTED_SUM' else int(ranks['BORDA_diff_WS']) if op == 'BORDA' else int(mechanism[op + '_diff_WS'])
        tie = int(ranks['BORDA_tied_states']) if op == 'BORDA' else int(mechanism[op + '_tied_states'])
        fusion.append({'operator': op, 'fitness': fit, 'delta_vs_WS': fit - equal,
            'same_state_diff_vs_WS': diff, 'states': 3800, 'tied_states': tie,
            'mechanism_sample': 'V2保存的H0/H1 WS轨迹，同一3800物理状态；离线诊断',
            'quality_sample': '各固定策略从空排程完整求解train21；V2/V3分批次'})
    save_csv(data / '07_融合机制与质量.csv', fusion)
    a4 = rows('reports/a4-closeout-20261025-v1/Certified_best_so_far.csv')
    require(len(a4) == 93, 'A4 93 committed slots only')
    save_csv(data / '08_A4部分搜索.csv', a4)
    completion = rows('reports/ind-vs-evo-h01-train21-seed501-20261026-v1/closeout-v1/Completion.csv')
    indcurves = rows('reports/ind-vs-evo-h01-train21-seed501-20261026-v1/closeout-v1/Search_curves.csv')
    require(sum(int(r['consumed']) for r in completion) == 113 and sum(int(r['API_attempts']) for r in completion) == 117, 'IND/EVO final 113 slots, 117 attempts')
    save_csv(data / '09_IND_EVO完成度.csv', completion)
    save_csv(data / '09_IND_EVO搜索曲线.csv', indcurves)
    external = rows('reports/h01-champion-hurink-rdata20-seed501-20261026-v1/Paired_instance_results.csv')
    exsummary = js('reports/h01-champion-hurink-rdata20-seed501-20261026-v1/Summary.json')
    require(len(external) == 20 and all(truth(r['both_valid']) for r in external), 'frozen champion transfer 20 full pairs')
    require(abs(sum(float(r['delta_F_contribution']) for r in external) - exsummary['delta_F']) < 1e-11, 'transfer full mean verified from paired rows')
    save_csv(data / '10_冻结冠军训练外逐实例.csv', external)
    certs=js('reports/ind-vs-evo-h01-train21-seed501-20261026-v1/closeout-v1/Champion_certification.json')
    for cert in certs:
        path='runs/ind-vs-evo-h01-train21-seed501-20261026-v1/'+cert['result_path']
        require(sha(ROOT/path)==cert['result_sha256'],'new champion raw result hash '+cert['task_id'])
        checked_result(path,cert['fitness'])
        require(cert['worker_exitcode']==0 and cert['before_after_identity_equal'] and cert['all_first_recheck_physical_hashes_equal'], 'saved champion quality and normal exit '+cert['task_id'])
    champion_record=next(c for c in certs if c['task_id']=='r2_EVO_s16')
    code='reports/h01-champion-hurink-rdata20-seed501-20261026-v1/Frozen_U/dynamic.py'
    record(ROOT/code)
    require(sha(ROOT/code)==champion_record['UTF8_code_sha256'],'training and external frozen champion UTF8 code SHA identical')
    hs=js(base+'H_frozen.json')
    for path in ['runs/h01-state-weight-search-seed501-batch-v3-20261020/H_frozen.json',
                 'reports/h01-champion-hurink-rdata20-seed501-20261026-v1/H_frozen.json']:
        other=js(path)
        require([m['candidate']['code'] for m in hs['members']]==[m['candidate']['code'] for m in other['members']], 'frozen H codes/order match '+path)
    rules = rows('reports/h01-progress-step-train21-seed501-20261025-v1/Ranking.csv')
    switches = rows('reports/fusion-v4-progress-switch-seed501-20261024-v1/Ranking.csv')
    save_csv(data / '11_简单动态规则.csv', rules)
    save_csv(data / '11_算子进度切换.csv', switches)
    ab = rows('reports/cross-feedback-ab-train21-seed501-v1-20261025/execution-v2/Candidates.csv')
    save_csv(data / '12_CROSS反馈候选.csv', ab)
    facts = {'H0': h0, 'equal': equal, 'B1': best_b1, 'B2': best_b2, 'single_oracle': next(r['fitness'] for r in baseline_rows if 'Oracle' in r['method']),
        'B2_delta_equal': best_b2 - equal, 'B2_wlt': [sum(r['winner'] == k for r in instance_delta) for k in ('B2','equal','tie')],
        'B2_sum_Cmax': sum(r['B2_Cmax'] for r in instance_delta), 'equal_sum_Cmax': sum(r['equal_Cmax'] for r in instance_delta),
        'B1_H01_steps': b1summary['H01_dual_steps'], 'B1_actual_pairs': b1summary['observed_dual_pairs'],
        'B2_initial_and_grid': js('reports/baseline-a-supplemental-T30-seed501-20261024-v1/Historical_search_budget_audit.json'),
        'B2_evidence': {k:b2evidence[k] for k in ('logical_candidates_requested','api_attempts_consumed','legal_candidates','duplicate_rate','budget','new_evaluations_completed') if k in b2evidence},
        'external_summary': exsummary, 'IND_EVO_completion': completion}
    save_json(out / '核实数值.json', facts)
    return locals()


def setup_plot():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    fonts = [p for p in font_manager.findSystemFonts() if 'STHeiti Medium' in p]
    if not fonts:
        fonts = [p for p in font_manager.findSystemFonts() if 'PingFang' in p or 'Heiti' in p]
    if not fonts:
        raise RuntimeError('Chinese plotting font unavailable; do not silently emit missing glyphs')
    font_manager.fontManager.addfont(fonts[0])
    plt.rcParams.update({'font.family':font_manager.FontProperties(fname=fonts[0]).get_name(),
        'font.size':11, 'axes.titlesize':13, 'axes.labelsize':11, 'axes.spines.top':False,
        'axes.spines.right':False, 'axes.unicode_minus':False, 'svg.fonttype':'none',
        'pdf.fonttype':42, 'figure.facecolor':'white', 'axes.facecolor':'white', 'savefig.facecolor':'white'})
    return plt


def emit(out, fig, stem, title, note, inputs, main=False):
    import matplotlib.pyplot as plt
    fig.suptitle(title, fontsize=17, y=.98)
    fig.text(.025,.018,note,fontsize=9,color='#475569',va='bottom')
    fig.subplots_adjust(top=.87,bottom=.17,wspace=.30,hspace=.60)
    path=out/'图表';path.mkdir(exist_ok=True)
    for ext in ('png','svg','pdf'):
        fig.savefig(path/(stem+'.'+ext),dpi=200)
        if ext == 'svg':
            svg = path/(stem+'.svg')
            svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
    FIGURES.append({'figure':stem,'title':title,'recommended_main':main,'inputs':inputs,'note':note,
                    'outputs':[str((path/(stem+'.'+e)).relative_to(out)) for e in ('png','svg','pdf')]})
    plt.close(fig)


def plots(out, d):
    import numpy as np
    plt=setup_plot();blue='#2563a6';green='#21896b';red='#c95555';orange='#d58a24';gray='#8291a3'
    single=d['single'];pairs=d['pairs'];grid=d['grid'];equal=d['equal'];facts=d['facts']
    f,ax=plt.subplots(figsize=(11,6.5));fs=[float(r['fitness']) for r in single]
    ax.hlines(range(10),min(fs)-.015,fs,color='#c8d7e6',lw=3);ax.scatter(fs,range(10),s=65,color=[blue]+[gray]*9,zorder=3)
    ax.set(yticks=range(10),yticklabels=[r['strategy'] for r in single],xlabel='完整train21 Fitness = 平均 −Cmax/LB（越高越好）',xlim=(min(fs)-.035,max(fs)+.09));ax.invert_yaxis();ax.grid(axis='x',alpha=.18)
    for i,v in enumerate(fs):ax.text(v+.008,i,f'{v:.6f}',va='center',fontsize=10)
    emit(out,f,'01_单H排名','10个冻结H的单成员训练表现','train21；V5未取整LB；历史双解缓存，非同期计时。H编号在审阅/冻结时已按本训练成绩排序。', ['绘图输入/01_单H.csv'],True)
    f,(ax,bx)=plt.subplots(1,2,figsize=(14,7));matrix=np.full((10,10),np.nan)
    for r in pairs:
        i,j=map(int,re.findall(r'\d+',r['strategy'])[:2]);matrix[i,j]=float(r['fitness'])
    im=ax.imshow(np.ma.masked_invalid(matrix),vmin=min(float(r['fitness']) for r in pairs),vmax=equal,cmap='viridis')
    ax.set(xticks=range(10),yticks=range(10),xticklabels=[f'H{i}' for i in range(10)],yticklabels=[f'H{i}' for i in range(10)],title='全部45个无序对；仅画上三角')
    for r in pairs:
        i,j=map(int,re.findall(r'\d+',r['strategy'])[:2])
        if r['source']=='Supplemental-T30':ax.scatter(j,i,marker='^',s=60,facecolor='none',edgecolor='white',lw=1.4)
    f.colorbar(im,ax=ax,fraction=.045,pad=.03,label='Fitness（越高越好）')
    ordered=sorted(pairs,key=lambda r:float(r['fitness']),reverse=True)
    for k,r in enumerate(ordered,1):
        bx.scatter(k,float(r['fitness']),marker='^' if r['source']=='Supplemental-T30' else 'o',color=orange if r['source']=='Supplemental-T30' else blue,s=40)
    bx.axhline(facts['H0'],color=gray,ls='--',label='Best Single H0');bx.axhline(equal,color=green,ls=':',label='H0/H1等权')
    bx.scatter([],[],color=blue,label='原Baseline-A：39对（含历史缓存）');bx.scatter([],[],marker='^',color=orange,label='独立T30补测：6对')
    bx.set(xlabel='按完整Fitness排序的位置',ylabel='完整train21 Fitness（越高越好）',title='全45对分布；6对超过Best Single');bx.legend(fontsize=9,loc='lower left');bx.grid(alpha=.15)
    emit(out,f,'02_等权45对分布','45个等权成员对的完整质量覆盖','train21 / seed501；39条原批＋6条独立T30。原批包括T15与认证历史缓存；不能当45对同期耗时实验。', ['绘图输入/02_等权45对.csv'],True)
    f,ax=plt.subplots(figsize=(11,6));g=sorted(grid,key=lambda r:float(r['H0_weight']))
    ax.plot([float(r['H0_weight']) for r in g],[float(r['fitness']) for r in g],'-o',color=blue,label='21个已测静态权重（线仅连接采样点）')
    for r in g:
        if truth(r['in_manual_P0']):ax.scatter(float(r['H0_weight']),float(r['fitness']),s=90,facecolor='white',edgecolor=orange,lw=2,zorder=4)
    ax.axhline(facts['B2'],color=green,ls='--',label=f'历史B2动态冠军 {facts["B2"]:.6f}')
    ax.annotate('最佳已测静态 α=0.50',(.5,equal),(.57,equal-.035),arrowprops={'arrowstyle':'->'},fontsize=10)
    ax.set(xlabel='H0权重 α；H1权重 = 1−α',ylabel='完整train21 Fitness（越高越好）',xticks=np.arange(0,1.01,.1));ax.legend(fontsize=10);ax.grid(alpha=.18)
    emit(out,f,'03_H01静态权重曲线','H0/H1静态权重网格：21点完整结果','train21；16次新增完整评价＋5份手工P0缓存；不是连续权重最优，更不是10H联合搜索。', ['绘图输入/03_静态权重21点.csv'])
    f,axes=plt.subplots(2,2,figsize=(14,9))
    for col,name in enumerate(('B1','B2')):
        cr=[r for r in d['curves'] if r['method']==name];ax=axes[0,col]
        ax.step([r['query'] for r in cr],[r['best_so_far'] if r['best_so_far'] is not None else np.nan for r in cr],where='post',color=blue,lw=2,label='含已有父代的best-so-far')
        valid=[r for r in cr if r.get('valid_complete')];ax.scatter([r['query'] for r in valid],[r['fitness'] for r in valid],s=25,color=gray,alpha=.8,label='新候选完整Fitness')
        for dup,label,color,y in [(False,'失败槽位',red,.025),(True,'源码重复槽位',orange,.065)]:
            bad=[r for r in cr if r['query'] and not r.get('valid_complete') and bool(r['duplicate'])==dup]
            ax.scatter([r['query'] for r in bad],[y]*len(bad),transform=ax.get_xaxis_transform(),marker='x' if not dup else 'D',color=color,label=label if bad else None)
        ax.axhline(equal,color=green,ls=':',label='H0/H1等权质量参照')
        ax.set(title='B1：19槽，14完整有效；P2未完成' if name=='B1' else 'B2：20演化槽，19新有效＋1重复',xlabel='原始逻辑槽位顺序（失败不删除）',ylabel='train21 Fitness（越高越好）');ax.grid(alpha=.15);ax.legend(fontsize=8,loc='lower right')
        bx=axes[1,col];pop=[r for r in d['populations'] if r['method']==name];stages=sorted({r['population'] for r in pop})
        means=[statistics.fmean(float(r['fitness']) for r in pop if r['population']==s) for s in stages]
        bests=[max(float(r['fitness']) for r in pop if r['population']==s) for s in stages]
        worst=[min(float(r['fitness']) for r in pop if r['population']==s) for s in stages]
        bx.fill_between(range(len(stages)),worst,bests,color=blue,alpha=.10,label='种群最差至最好');bx.plot(stages,means,'o-',color=blue,label='种群均值');bx.plot(stages,bests,'s--',color=green,label='种群冠军')
        bx.set(title=f'{name}已保存的完整种群（每群5个）',ylabel='train21 Fitness（越高越好）',xlabel='种群快照');bx.legend(fontsize=9);bx.grid(alpha=.15)
    emit(out,f,'04_B1_B2搜索与种群','历史B1/B2搜索轨迹：质量与预算分开解释','原checkpoint尝试顺序；B1九次初始化＋十次演化；B2含强手工P0且另完成21点网格。两者非等先验/等预算消融。', ['绘图输入/04_搜索全槽轨迹.csv','绘图输入/04_种群成员.csv'],True)
    f,ax=plt.subplots(figsize=(12,6.5));q=d['baseline_rows'];ys=list(range(len(q)))
    ax.scatter([r['fitness'] for r in q],ys,s=85,color=[gray,orange,blue,blue,red,green]);ax.set(yticks=ys,yticklabels=[r['method'] for r in q],xlabel='完整train21 Fitness（越高越好）',xlim=(min(r['fitness'] for r in q)-.02,equal+.075));ax.invert_yaxis();ax.grid(axis='x',alpha=.15)
    for y,r in enumerate(q):ax.text(r['fitness']+.003,y,f'{r["fitness"]:.9f}',va='center',fontsize=10)
    f.subplots_adjust(left=.27)
    emit(out,f,'05_训练质量比较','固定基线与历史LLM-U：只比较最终策略质量','train21 / V5-LB；B1/B2搜索空间、初始化、查询和缓存投入不同。Oracle仅事后诊断；本图不证明搜索效率或泛化。', ['绘图输入/05_训练质量参照.csv'],True)
    f,(ax,bx)=plt.subplots(2,1,figsize=(14,8.5),sharex=True);rs=d['instance_delta'];colors=[green if r['delta_score']>0 else red if r['delta_score']<0 else gray for r in rs];x=np.arange(21)
    ax.bar(x,[r['delta_F_contribution'] for r in rs],color=colors);ax.axhline(0,color='#334155',lw=.8);ax.set(ylabel='对ΔFitness的贡献（正值有利B2）',title=f'10胜 / 7负 / 4平；总ΔF = {facts["B2_delta_equal"]:+.9f}')
    bx.bar(x,[r['delta_Cmax'] for r in rs],color=colors);bx.axhline(0,color='#334155',lw=.8);bx.set(ylabel='Cmax差：B2−等权（负值更好）',xticks=x,xticklabels=[r['file'].replace('Behnke','B').replace('.fjsp','') for r in rs],xlabel='完整21实例，保留原顺序');bx.tick_params(axis='x',rotation=45)
    emit(out,f,'06_B2逐实例收益与退化','B2对静态等权：归一化收益与原始Cmax不相同','train21；ΔF = 平均[(Cmax等权−CmaxB2)/LB]。B2总Cmax=4050，等权=4047；主指标仍小幅更好。', ['绘图输入/06_B2逐实例差异.csv'])
    fusion=d['fusion'];labels=['WS','MAX','MIN','Borda'];f,axes=plt.subplots(1,3,figsize=(15,6.5))
    for ax,field,title,ylabel in [(axes[0],'same_state_diff_vs_WS','同一WS轨迹状态：与WS首选动作不同','状态占比（%）'),(axes[1],'tied_states','同一状态的顶端并列','状态占比（%）')]:
        ax.bar(labels,[r[field]/38 for r in fusion],color=[gray,orange,blue,green]);ax.set(title=title,ylabel=ylabel,ylim=(0,108))
        for i,r in enumerate(fusion):ax.text(i,r[field]/38+2,f'{r[field]/38:.1f}%',ha='center',fontsize=10)
    axes[2].scatter(labels,[r['fitness'] for r in fusion],s=75,color=[gray,orange,blue,green]);axes[2].set(title='各固定策略完整求解质量',ylabel='train21 Fitness（越高越好）');axes[2].grid(axis='y',alpha=.2)
    emit(out,f,'07_融合表达与质量','动作不同与排程更好：两种证据必须分开','机制：同一批已保存WS轨迹3800状态，离线反事实；质量：V2/V3分别从空排程求解21实例。MAX约98.9%顶端并列。', ['绘图输入/07_融合机制与质量.csv'])
    f,(ax,bx)=plt.subplots(1,2,figsize=(13,6))
    for repeat,color,axis in [(1,blue,ax),(2,orange,bx)]:
        rr=[r for r in d['a4'] if int(r['repeat'])==repeat]
        axis.step([int(r['slot']) for r in rr],[float(r['best_so_far']) for r in rr],where='post',color=color,label='已认证best-so-far');axis.axhline(equal,color=green,ls=':',label='静态等权');axis.axhline(facts['H0'],color=gray,ls='--',label='H0');axis.set(title=f'重复{repeat}：{len(rr)}/60'+(' 完整' if repeat==1 else ' partial'),xlabel='本重复逻辑查询位置',ylabel='train21 Fitness（越高越好）',xlim=(0,60));axis.grid(alpha=.15);axis.legend(fontsize=9)
    emit(out,f,'08_A4完整与部分路径','A4固定预算静态联合随机搜索：只完成93/300','第一轮60/60，第二轮33/60，其余未启动；总最佳来自查询52。保留五项严格墙钟T30隔离，不计算五轮分布。', ['绘图输入/08_A4部分搜索.csv'])
    f,axes=plt.subplots(1,3,figsize=(15,6),sharey=True)
    for repeat,ax in enumerate(axes,1):
        for arm,color in [('IND',blue),('EVO',orange)]:
            rr=[r for r in d['indcurves'] if int(r['repeat'])==repeat and r['arm']==arm];co=next(r for r in d['completion'] if int(r['repeat'])==repeat and r['arm']==arm)
            ax.step([int(r['logical_query']) for r in rr],[float(r['best_fitness']) for r in rr],where='post',color=color,label=f'{arm}: {co["consumed"]}/20；有效{co["certified_children"]}')
        ax.set(title=f'独立搜索重复 {repeat}',xlabel='逻辑预算位置（含失败槽位）',xlim=(0,20));ax.grid(alpha=.15);ax.legend(fontsize=9)
    axes[0].set_ylabel('含共同P0的train21最佳Fitness（越高越好）')
    emit(out,f,'09_IND_EVO探索性比较','IND与EVO：两条EVO路径突破，但完整重复不足','113/120槽，117尝试；仅重复1双方20/20，其余partial。503/524造成机会不平衡；不是120次独立演化重复。', ['绘图输入/09_IND_EVO搜索曲线.csv','绘图输入/09_IND_EVO完成度.csv'])
    f,(ax,bx)=plt.subplots(1,2,figsize=(15,6.5),gridspec_kw={'width_ratios':[1,1.8]});ex=d['external'];exs=d['exsummary']
    train_best=max(float(r['best_including_P0']) for r in d['completion']);delta_train=train_best-equal
    vals=[delta_train,exs['delta_F']];ax.bar(['train21\n开发选择','Hurink rdata20\n跨基准确认'],vals,color=[green,red]);ax.axhline(0,color='#334155',lw=.8);ax.set(ylabel='动态冠军−静态等权 ΔFitness（正值更好）',title='同一冻结冠军，分数据集报告')
    for i,v in enumerate(vals):ax.text(i,v+(0.008 if v>=0 else -.014),f'{v:+.6f}',ha='center',va='bottom' if v>=0 else 'top')
    excolors=[green if float(r['delta_F_contribution'])>0 else red for r in ex];bx.bar(range(20),[float(r['delta_F_contribution']) for r in ex],color=excolors);bx.axhline(0,color='#334155',lw=.8);bx.set(title='确认集：2胜 / 18负 / 0平',ylabel='逐实例ΔFitness贡献（正值更好）',xticks=range(20),xticklabels=[r['file'].replace('HurinkR_','').replace('.fjsp','') for r in ex]);bx.tick_params(axis='x',rotation=60,labelsize=9)
    emit(out,f,'10_冻结冠军训练外验证','较好的训练冠军，没有延续为本次跨基准收益','r2_EVO_s16代码冻结后一次评价；Hurink rdata20为跨基准/机器尺度迁移，不是同分布holdout。两数据集分别取均值，不合并。', ['绘图输入/09_IND_EVO完成度.csv','绘图输入/10_冻结冠军训练外逐实例.csv'],True)
    f,(ax,bx)=plt.subplots(1,2,figsize=(14,7));rules=sorted(d['rules'],key=lambda r:float(r['fitness']),reverse=True)
    ax.scatter([float(r['fitness']) for r in rules],range(len(rules)),s=30,color=[blue if truth(r['dynamic']) else gray for r in rules]);ax.set(yticks=range(len(rules)),yticklabels=[r['id'] for r in rules],xlabel='train21 Fitness（越高越好）',title='简单分段权重：18动态＋3静态');ax.tick_params(axis='y',labelsize=8);ax.invert_yaxis();ax.axvline(equal,color=green,ls=':')
    sw=[r for r in d['switches'] if r['status']=='valid'];bx.scatter([float(r['fitness']) for r in sw],range(6),s=50,color=orange);bx.set(yticks=range(6),yticklabels=[r['strategy'] for r in sw],xlabel='train21 Fitness（越高越好）',title='V4：六个预定WS/Borda切换');bx.invert_yaxis();bx.axvline(equal,color=green,ls=':',label='固定WS');bx.legend()
    emit(out,f,'11_预定动态规则族','预定简单动态规则：完整列出，不只报告冠军','两项独立固定规则研究，不是LLM搜索。18动态权重规则与6算子切换均未超过等权；只约束这两个有限规则族。', ['绘图输入/11_简单动态规则.csv','绘图输入/11_算子进度切换.csv'])
    ab=d['ab'];contexts=sorted({r['pair_id'] for r in ab});f,ax=plt.subplots(figsize=(12,6))
    for arm,color,shift in [('A',blue,-.13),('B',orange,.13)]:
        for i,pair in enumerate(contexts):
            rr=[r for r in ab if r['pair_id']==pair and r['condition']==arm and truth(r['certified_valid'])]
            yy=[float(r['fitness']) for r in rr];xx=[i+shift+(j-1)*.025 for j in range(len(rr))]
            ax.scatter(xx,yy,color=color,s=45,label=arm if i==0 else None)
            if yy:ax.plot([i+shift-.07,i+shift+.07],[statistics.fmean(yy)]*2,color=color,lw=2)
        n=sum(r['condition']==arm and truth(r['certified_valid']) for r in ab)
        ax.text(.02,.05 if arm=='A' else .01,f'{arm}: {n}/15完整认证',transform=ax.transAxes,color=color,fontsize=10)
    for i,pair in enumerate(contexts):
        v=float(next(r for r in ab if r['pair_id']==pair)['better_parent_fitness'])
        ax.plot([i-.3,i+.3],[v,v],color=gray,ls='--',label='该对较好父代' if i==0 else None)
    ax.set(xticks=range(len(contexts)),xticklabels=contexts,xlabel='冻结父代任务（每条件3次生成；非严格随机配对）',ylabel='完整train21子代Fitness（越高越好）');ax.grid(axis='y',alpha=.15);ax.legend()
    emit(out,f,'12_CROSS成绩反馈分任务','CROSS真实成绩反馈：展示全部有效子代与缺失','A=原提示，B=仅加父代成绩与差值。A一项HTTP524未生成，无Fitness；失败不删槽位、不补样本；5任务并非独立多代重复。', ['绘图输入/12_CROSS反馈候选.csv'])


def catalogue(out, d):
    """Explicit experiment cards + complete physical-folder coverage, not 131 trials."""
    cards=[]
    def add(id,name,patterns,classification,question,space,data,seed,budget,result,evidence,limits,exposed='train开发；非独立泛化',figures=''):
        cards.append(dict(id=id,name=name,patterns=patterns,classification=classification,question=question,space=space,
            dataset=data,seed=seed,metric='完整实例均值 −Cmax/LB；具体LB/接口以所引协议为准',budget=budget,
            result=result,evidence=evidence,limits=limits,exposed=exposed,figures=figures))
    add('H01','Tier 1实际H生成、导入、审阅与冻结',['leaf-framework-30pct-20261009','leaf-framework-30pct-20261010','baseline-a-provenance-timeout-audit'],
        '正式完整','生成有互补性的10H，并追溯编号','单动作评分H；本项目最小EoH-S适配','train21','H搜索7（非501）',
        'v1 9尝试、v2 3尝试；v3导入8H后22新尝试（2初始化+20演化）；不能重复加总导入成员',
        f'冻结10H；最好H0={d["h0"]:.12f}；按train21单H均值排序编号',
        'reports/baseline-a-provenance-timeout-audit-20261024-v1/H_mapping.csv',
        '本卡仅H阶段完整；同目录后续U阶段中断。历史完整源码闭包未全部恢复，非相邻EoH-S全runner复现。',figures='01')
    add('U01','早期单成员P组验收与继承初始化',['leaf-tier2-single-P','leaf-tier2-small-dev','leaf-U-continuation'],
        '正式部分完成','检查U初始化延续与单成员演化','旧单成员SELECT；P组','train21','101',
        '继承35初始化槽位；v4新10演化槽位；v1/v2/v3属于恢复/验收链，不能当独立重复',
        'v4 P组一代完成；冠军−2.076166908582；初始−2.088336727768',
        'runs/leaf-tier2-single-P-acceptance-20261010-v4/r101/P/checkpoint.json',
        '整套四组/多代研究未完成；身份和预算继承，不能累加所有副本。')
    add('U02','旧单成员四组gpt-6.1训练',['single-ID-gpt61-paired-training','single-ID-paired-training'],
        '正式完整','固定旧H条件下四种单成员流程','旧SELECT；四组旧名B0/B1/B2/P，不等于后来的自由B1/H01-B2','train21','201',
        '47正式槽位，32实际正式生成；另1诊断请求。旧模型503阶段单独保留',
        '四组最终冠军均−2.070427513558，来自共同初始化；新有效共21（含5初始化）',
        'runs/single-ID-gpt61-paired-training-20261014-v1/Reconciled_training_results.json',
        '槽位完成但B1实际发送0；四组算法比较被基础设施故障破坏；不能当公平方法证据。')
    add('U03','v2.2 SELECT/MIX双组真实试验',['v22-gpt61-select-mix','real-gpt61-301'],
        '正式完整','放开最多两成员是否生成有效融合','10H SELECT/MIX；共享P0，A/B','train21','301',
        '28槽/28发送：INIT8+两组各10；20完整有效（含5初始化），0源码重复',
        'A冠军−2.185156683819，B冠军−2.225194303278；未超过固定H0',
        'docs/usage-space/real-gpt61-301/Complete_summary.json',
        '单seed；初始化和父代机制与后来的B1/B2不同；不混称新版A/B成绩反馈。')
    add('D01','v2.2机制消融与固定H参照',['usage-v22-mechanism-ablation'],
        '探索性诊断','拆分已生成U的机制表现','已有U及equal/dominant等受控变体','train21','301',
        '固定清单见Ablation_and_fixed_H_summary.csv；API0',
        '保留所有变体完整/失败，不能把人工变体记成LLM新发现',
        'reports/usage-v22-mechanism-ablation-301-20261017-v1/Ablation_and_fixed_H_summary.csv','属训练内诊断，不是新独立搜索重复。')
    add('S01','早期4对×3权重静态扫描',['usage-fixed-pair-weight-grid'],
        '正式完整','人工选定成员对的静态组合潜力','4成员对，每对3个固定比例','train21','501参照；原配置为准',
        '12完整策略；API0',f'最好H0/H1等权={d["equal"]:.12f}',
        'reports/usage-fixed-pair-weight-grid-20261018-v1/Grid_summary.csv',
        '不是45对扫描，不是H01的21点网格；后续复用不算新增评价。',figures='03/05的历史来源')
    add('D02','10H同状态动作多样性',['h10-decision-diversity'],
        '探索性诊断','H是否产生不同首选动作','10H保存状态的影子评分','train21已有轨迹','501参照',
        '384状态、364不同物理状态；0新增完整Fitness/0API',
        '首选动作类别分布已保存；不把动作不同当收益',
        'reports/h10-decision-diversity-v1-20261020/Metrics.json','同源轨迹样本有相关性；不是384个独立实例。')
    add('D03','已生成U状态使用诊断',['u-state-behavior'],
        '探索性诊断','状态读取是否改变有效输出/动作','已有v2.2 U','train21已有记录','301',
        '已有候选/谓词/同状态记录，不计新搜索',
        '代码读取、状态输出、动作变化分别保存',
        'reports/u-state-behavior-v1-20261020/Evidence_index.json','无行为记录时不得由代码外观推论分支因果。')
    add('D04','Task4A同状态受控续排',['task4a-state-information'],
        '探索性诊断','局部动作差异能否改变终局','H0/H1同状态两方向续排','6个已用train实例','原Plan固定',
        '12/12配对（10分歧+2控制）；不形成新U搜索成绩',
        '10分歧配对2/2/6，Cmax差范围−4到4',
        'reports/task4a-state-information-v1-20261020/Paired_results.csv','局部样本，不能声称可学习的普遍状态收益。')
    add('B2','H01静态21点网格＋历史B2两代演化',['h01-state-weight-search-seed501-batch','h01-state-weight-search-seed501-local','h01-state-weight-search-seed501-20261019'],
        '正式完整','已知成员对上动态权重的增量','固定H0/H1，静态网格与动态U','train21','501',
        '5手工P0；21网格=16新+5复用；20演化请求/20响应/19新有效+1重复；新增35完整评价=735项/1470遍',
        f'静态最佳α=.5；动态={d["best_b2"]:.12f}，ΔF={d["best_b2"]-d["equal"]:+.12f}',
        'runs/h01-state-weight-search-seed501-batch-v3-20261020/r501/B/checkpoint.json',
        '原T15/legacy两遍记录，非现代完整退出回执；20不等于从零总成本，副本目录“ 2”不是新重复。',figures='03/04/05/06')
    add('V01','历史B2冻结test28配对验证',['v1-h01-frozen-pair-test28'],
        '正式完整','历史B2训练优势能否延续','冻结历史B2 vs等权','test28（现已暴露）','501',
        '56程序—实例评价；0API',
        '动态−2.235473642174，等权−2.242732515531；12胜14负2平',
        'reports/v1-h01-frozen-pair-test28-v1-20261021/V1_report.json',
        '微小均值优势不构成稳健普遍优势；不能把test28重新称全新确认集。',exposed='test28已访问、已暴露')
    add('B1S','B1原流式10H自由搜索',['b1-full-h-free-seed501'],
        '正式部分完成','自由发现SELECT/MIX成员组合','10H自由U，k=2 CROSS','train21','501',
        '原checkpoint18初始化尝试；后续非流式/Recovery是另声明链',
        '未形成原计划完整两代；不与Recovery19槽相加充当一次重复',
        'runs/b1-full-h-free-seed501-k2-v1-20261021/r501/B/checkpoint.json','传输及身份门禁，目录可能只有本地未跟踪报告。')
    add('B1','B1非流式与Recovery-B',['b1-ns-full-h-free','b1-ns-b-full','b1-ns-recovery-B-v1','b1-ns-recovery-B-execution'],
        '正式部分完成','10H自由成员/融合能否发现强组合','10H SELECT/MIX；k=2交叉','train21','501',
        '19槽/19发送/14完整有效；9初始化+10演化；其中6请求继承、13本恢复新请求；15评价含3次重认证',
        f'P0/P1冠军均{d["best_b1"]:.12f}，P1均值改善；未访问H0/H1双成员执行',
        'reports/b1-ns-recovery-B-execution-20261023/Summary.json',
        'P2未完成；最后超时无after留证，身份停止不能追认原前缀；旧与恢复不算独立重复。',figures='04/05')
    add('F2','Fusion V2固定WS/MAX/MIN',['fusion-v2-train21-seed501'],
        '正式完整','新算子是否改变动作与完整排程','3固定成员对×3算子','train21','501',
        '9任务均终结，3完整有效+6超时null；正式之前v1准备版本不计一次运行',
        'H01 WS最好，MAX−2.073695483437，MIN−2.112728513220',
        'reports/fusion-v2-train21-seed501-20261023-v2/Ranking.csv',
        '6个涉及H5/H9的原null保留；机制状态重放不当完整求解。',figures='07')
    add('F3','Fusion V3 Borda固定策略',['fusion-v3-borda'],
        '正式部分完成','秩融合表达与WS区别','Borda；原3对固定名单','train21','501',
        'H01 21完整；H0/H5回传但异常终态隔离；H5/H9未运行',
        '仅接受H01 Borda−2.066904716328',
        'reports/fusion-v3-borda-train21-seed501-20261024-v1/Ranking.csv',
        'checkpoint running不是仍在正式执行的证明；按Stop及隔离证据解释。',figures='07')
    add('F4','Fusion V4进度算子切换',['fusion-v4-progress-switch'],
        '正式完整','简单WS/Borda动态切换可行性','H01，两个方向×三阈值','train21','501',
        '6/6完整，126项/252遍；0API',
        '最好−2.001911310507，全部低于WS',
        'reports/fusion-v4-progress-switch-seed501-20261024-v1/Ranking.csv',
        '生命周期新版本不追认V3隔离；有限规则族，不代表所有动态策略。',figures='11')
    add('A','Baseline-A原批',['tier2-baseline-a-train21'],
        '正式完整','建立单H、45等权对与单H Oracle','10单H＋45固定WS；事后Oracle','train21','501',
        '10单H有效；45对任务全终结39有效6null；41新策略、14缓存；847首解+847复检启动',
        f'Best Single={d["h0"]:.12f}；Best Pair={d["equal"]:.12f}',
        'reports/tier2-baseline-a-train21-seed501-20261024-v1/Summary.json',
        '正式完整指任务终结，不指55策略全有效；旧6null保留；legacy缓存不是T15同期结果。',figures='01/02/05')
    add('AT30','Baseline-A独立T30补测',['baseline-a-supplemental-T30'],
        '正式完整','补齐6对质量，并同期核对强参照','6原超时对＋H0/H01/H03','train21','501',
        '9/9有效，189项/378遍；全部新评，缓存抵扣0；0API',
        '综合45对全部有效；H01仍第1，无新对超过B2',
        'reports/baseline-a-supplemental-T30-seed501-20261024-v1/Composite_pairs_45.csv',
        '综合表39旧+6新，不是45对同期T30；改变期限同时改变收集机制，不能只归因秒数。',figures='02/05')
    add('A4','A4联合成员与静态权重随机搜索',['a4-static-rs60','a4-closeout'],
        '正式部分完成','有限预算下联合选成员/静态权重','865规范策略，均匀无放回','train21','2026102601–05；求解501',
        '93/300查询，91不同策略；60完整+33partial；81新+10历史缓存+2跨轮复用；3402遍',
        '首轮冠军H01=.65/.35，−2.022083102801，首次查询52；未超过等权',
        'reports/a4-closeout-20261025-v1/Certified_summary.json',
        '查询88/89/90/92/93严格墙钟T30证据隔离；不改质量记录，不计算五轮分布。',figures='08')
    add('AB','固定父代CROSS成绩反馈A/B',['cross-feedback-ab-train21'],
        '正式完整','仅增加父代完整成绩是否改善子代','10H自由历史P0，5配对×3×2','train21','冻结抽样/调用顺序，求解501',
        '30逻辑/30尝试；A14响应B15响应；29完整有效，609项/1218遍',
        '超过较好父代A2/15，B0/15；5配对B均值1胜1平3负',
        'reports/cross-feedback-ab-train21-seed501-v1-20261025/execution-v2/Candidates.csv',
        '一项A HTTP524，非代码失败；非多代反馈试验，不能由合并均值作因果结论。',figures='12')
    add('ABD','CROSS反馈解释性分析',['cross-feedback-ab-explanation'],
        '探索性诊断','B偏弱体现在哪些程序/实例','已有29子代及父代','train21既有结果','无新增随机实验',
        '新增API0/求解0；不删除异常差子代',
        '不支持B普遍复制较好父代的简单解释',
        'reports/cross-feedback-ab-explanation-20261025-v1/REPORT_ZH.md','结构相似不等于行为相同；无新同状态因果诊断。')
    add('RULE','H01简单分段动态权重族',['h01-progress-step'],
        '正式完整','简单状态规则能否超过等权/B2','18动态＋3静态；原27参数规范去重','train21','501',
        '21/21有效；19新+2缓存，399项/798遍；API0',
        '动态最好−1.990909533283；0/18超过等权',
        'reports/h01-progress-step-train21-seed501-20261025-v1/Ranking.csv',
        '全族冠军为静态等权；选择成本需披露，不能说动态全部无价值。',figures='11')
    add('IE','独立生成IND vs完整演化EVO',['ind-vs-evo-h01'],
        '正式部分完成','同新增候选预算比较完整搜索流程','H01动态/静态U，共同5静态P0','train21','3新搜索重复；求解501',
        '113/120逻辑，117API尝试；108响应107完整质量认证；仅重复1双方20/20',
        'EVO两重复突破；最佳r2_EVO_s16 −1.975488675215；IND无突破',
        'reports/ind-vs-evo-h01-train21-seed501-20261026-v1/closeout-v1/Completion.csv',
        '断电/续跑、8次503和1次524；7未启动，单次评价失败；不能强推稳定方法优越。',figures='09/10')
    add('EXT','新冠军冻结训练外质量验证',['h01-champion-hurink-rdata20'],
        '正式完整','固定r2_EVO_s16相对等权是否延续优势','两冻结U，不搜索/调参','Hurink rdata20跨基准/机器尺度迁移','抽样2026102617；求解501',
        '20实例×2=40项，80遍；0API',
        '动态−1.635914532450，等权−1.442119623478；ΔF−0.193794908972；2胜18负',
        'reports/h01-champion-hurink-rdata20-seed501-20261026-v1/Paired_instance_results.csv',
        '支持本次跨基准退化；不是同分布未见验证，也不证明所有动态U或EVO无效。',exposed='策略冻结后一次确认；该20实例现已暴露',figures='10')
    add('ENG','通用抽取、操作入口及本地冒烟',['generic-extraction','fjsp-extraction','engineering-handoff','ops-handoff','learn-fixed','long-job'],
        '探索性诊断','工程行为回归、后台/恢复与入口验收','固定U/toy/合成适配器，不搜索质量','toy；部分已有Behnke1回归','原固定种子',
        '以各验收清单为准；Mock不当真实生成',
        '当前工作树可见learn-fixed-01已完成，属于用户工程练习',
        'reports/engineering-handoff-20261026-v1/REPORT_ZH.md','不能把演示/Mock成绩混入科研质量图。')
    add('NET','流式/提示长度/非流式诊断',['t1-','b1-ns-a-engineering','b1-ns-timeout-boundary','b1-ns-recovery-scope'],
        '探索性诊断','API传输可靠性与留证边界','冻结提示/接口测试，不重新设计H','无正式质量或只用train证据','各诊断协议',
        '逐诊断请求见各账本，未统一混加；T1-D1等名称不是Tier 1生成',
        '保留SSE/503/格式/身份问题；成功响应不等于有效程序',
        'reports/t1-d4b-full-b1-init-nonstream-v1-20261022/Diagnostic_summary.json','只作可靠性证据，不作算法收益比较。')
    add('MOCK','早期离线、合成、玩具验收',['research_v1','s1-s6','v5-four-arm-offline','usage-v2-toy','usage-v2-examples','tier2_offline_v2','formal-readiness-synthetic'],
        '探索性诊断','流程/状态/选择机制的离线验收','手写H或合成候选，不是真实LLM搜索','toy或train21离线','各配置',
        '多目录是修订/副本，不视为独立重复',
        '即使有train21数值也不是冻结10H的正式真实生成结果',
        'runs/research_v1_train_verified_20261005/protocol.json','协议明确offline-mock/handwritten H；不可并入主质量排名。')
    add('DS','DeepSeek探索性演示',['deepseek-pilot'],
        '探索性诊断','API与闭合代码接入','手写EFT/SPT H，不加入正式冻结集合','微型实例/前三个train','原配置',
        '20/50槽，20确认发送；6个H样例5有效，U阶段13有效',
        '只作演示记录，不用其−1.284等混合数据均值比较train21',
        'runs/deepseek-pilot-20261008-v1/report.md','非论文正式H、非完整train21、非四组比较。')
    add('EARLY','早期真实配对pilot的H初始化',['leaf-paired-pilot-20261009'],
        '正式部分完成','完整双层研究前的真实初始化试跑','原H生成阶段，尚未形成冻结10H','协议声明train21','101开发；H阶段以原配置为准',
        '计划总请求150；H检查点3初始化尝试，未完成H集合',
        '不采用仅3候选种群最好值充当正式10H基线',
        'runs/leaf-paired-pilot-20261009-v1/H/checkpoint.json','早期部分尝试；不与后续H导入链混当独立完整重复。')
    add('API','早期API、账单与交接接入验收',['leaf-billing-verification','leaf-handoff-acceptance','leaf-integration-acceptance','leaf-status-integration','leaf-train-timeout-calibration'],
        '探索性诊断','接口接通、用量/扣点留证与进度显示','接入探针/接口样例，不是U搜索质量比较','工程或极小数据','见探针配置',
        '逐探针账本见请求账本范围索引；不按目录相加',
        '仅接口/计费接入证据，不进入Fitness质量图',
        'runs/leaf-integration-acceptance-20261008-v4/protocol.json','价格草案与余额快照不是现时费用，也不回填未知费用为零。')
    add('COND','条件四组研究准备与既有H重审',['conditional-paired-research'],
        '仅有规划','先明确既有H范围与U边界再开展四组','旧单成员U，H适用范围审阅','train21条件重审；协议引用旧split','拟用201',
        '未见这些目录的新U检查点；计划60请求不当实际生成',
        '已有H重审/静态库存属于准备性诊断；正式四组另见U02',
        'runs/conditional-paired-research-20261011-v4/Research_readiness.json','四个目录为修订，非四次独立实验。')
    add('PLAN','准备、预检和未执行协议',['preflight','preparation','prepared','a4-evidence-protocol','h01-alpha-offline-draft','v22-select-mix','v22-gpt61-select-mix-20261014'],
        '仅有规划','正式运行前门禁/协议设计','见各冻结草案；不把计划候选当生成','配置声明不等于实际访问','配置中的拟用seed',
        '预算上限为计划，不记成已消费',
        '有些含离线验证/旧缓存分析，未证明新正式搜索开始',
        'docs/TIER2_A4_STATIC_SEARCH_PROTOCOL_V1.md','相关正式结果另列；55策略回放、Random-U/GP-U、C反思仍无本工作树正式结果。')
    # Each directory is indexed, including mirrors and engineering folders.
    inventory_assets=json.loads((out/'资产快照.json').read_text());asset_rows=[]
    for asset in inventory_assets:
        path=asset['asset'];card=next((c for c in cards if any(pat in path for pat in c['patterns'])),None)
        snaps=asset['snapshots'];phases=sorted({str(s.get('phase',s.get('status'))) for s in snaps if s.get('phase',s.get('status')) is not None})
        cps=[s for s in snaps if s['file'].lower().endswith('/checkpoint.json')]
        ss=[s for s in snaps if s['file'].lower().endswith('/protocol.json')];cfg=ss[0].get('config',{}) if ss else {}
        dates=re.findall(r'20\d{6}',path);date=dates[-1] if dates else '日期见源文件'
        classification=card['classification'] if card else '探索性诊断'
        if any(t in path for t in ('preparation','prepared','preflight','h01-state-weight-search-seed501-local-v2','h01-state-weight-search-seed501-20261019','fusion-v2-train21-seed501-20261023-v1')):
            classification='仅有规划'
        if 'baseline-a-provenance-timeout-audit' in path:classification='探索性诊断'
        if path=='runs/single-ID-paired-training-20261013-authorized-v1':classification='正式部分完成'
        row={'资产路径':path,'实验编号':card['id'] if card else 'OTHER','实验名称':card['name'] if card else path.split('/')[-1],
            '日期':date,'分类':classification,'研究问题':card['question'] if card else '预检/工程/来源记录；未认证新的独立科研结果',
            'H_U空间与方法':card['space'] if card else '见原协议，未自动推断可比性','数据集':card['dataset'] if card else '未知/不适用；不得由目录名称补造',
            'seed':card['seed'] if card else cfg.get('seeds',cfg.get('seed','未知/不适用')),
            '指标':card['metric'] if card else '不纳入统一质量排名','预算与实际完成量':card['budget'] if card else '见资产快照与分阶段账本；未知不填0',
            '最佳结果及基线':card['result'] if card else '未认证；不绘制成绩比较',
            '完整认证范围':card['limits'] if card else '未完成科学身份/完整评价认证，不据completed字段追认',
            '原始状态快照':phases,'原始来源':card['evidence'] if card else [s['file'] for s in snaps][:4],
            '可直接绘图':card['figures'] if card else '否/需专项核查','留出暴露':card['exposed'] if card else '未知，不宣称未见',
            '证据限制':card['limits'] if card else '同名副本/工程资产不当独立重复；完整文件索引可追查',
            '文件数':asset['file_count'],'检查点数':len(cps),'CSV数':len(asset['tables']),'归档':asset['archives']}
        asset_rows.append(row)
    save_csv(out/'实验资产总目录.csv',asset_rows)
    for c in cards:
        c['physical_assets']=[r['资产路径'] for r in asset_rows if r['实验编号']==c['id']]
    save_json(out/'实验登记说明.json',cards)
    # Preserve checkpoint-stage counts, not summable across inherited copies.
    stages=[]
    for a in inventory_assets:
        for snap in a['snapshots']:
            if not snap['file'].lower().endswith('/checkpoint.json'):continue
            cp=js(snap['file']);attempts=cp.get('attempts',[]);ev=cp.get('evaluations',{})
            if not isinstance(attempts,list) or not attempts:continue
            counts={}
            for x in attempts:counts[x.get('status','unknown')]=counts.get(x.get('status','unknown'),0)+1
            valid=[e.get('result',{}) for e in ev.values() if isinstance(e,dict) and isinstance(e.get('result'),dict) and e['result'].get('valid')]
            stages.append({'checkpoint':snap['file'],'phase':cp.get('phase'),'generation':cp.get('generation'),
                'logical_attempt_records':len(attempts),'outcomes':counts,'full_valid_result_records':len(valid),
                'complete_successful_rows':sum(len(r.get('instances',[])) for r in valid),
                'API_attempts':'未由此字段推定；见请求账本','scope':'快照含继承/副本，不跨目录求和；阶段名B1/B2须与run一起识别'})
    save_csv(out/'所有搜索阶段记录.csv',stages)
    # Per-ledger request scopes are explicitly kept apart; no false grand total.
    file_index=list(csv.DictReader((out/'文件索引.csv').open(encoding='utf-8-sig')));journals=[]
    for item in file_index:
        name=Path(item['path']).name
        if name not in ('budget.json','API_attempts.json','budgeted_initial_requests.json','budgeted_evolution_requests.json'):
            continue
        if int(item['bytes'])>100_000_000:continue
        obj=js(item['path']);attempts=obj.get('api_attempts');records=obj.get('records');requests=obj.get('requests')
        if isinstance(attempts,dict):
            logical=len(requests) if isinstance(requests,dict) else None;values=list(attempts.values())
        elif isinstance(records,dict):logical=len(records);values=list(records.values())
        else:continue
        journals.append({'source':item['path'],'ledger_identity':obj.get('identity'),'logical_records':logical,
            'attempt_records':len(attempts) if isinstance(attempts,dict) else None,
            'confirmed_sends':sum(x.get('send_confirmed') is True for x in values),
            'completed_attempt_or_record':sum(x.get('status')=='completed' for x in values),
            'unknown_or_reserved':sum(x.get('status') not in ('completed','failed','rejected','cancelled','proved_unsent') for x in values),
            'known_input_tokens':sum((x.get('usage') or {}).get('input_tokens',0) or 0 for x in values),
            'known_output_tokens':sum((x.get('usage') or {}).get('output_tokens',0) or 0 for x in values),
            'unknown_usage':sum(x.get('usage') is None for x in values),
            'notes':'同identity或继承链为快照/延续；不按目录累加成独立请求，不把未发送槽位计真实API。'})
    save_csv(out/'请求账本范围索引.csv',journals)
    return cards,asset_rows


def write_documents(out,d,cards,assets):
    def link(path,label=None):
        p=Path(path);p=p if p.is_absolute() else ROOT/p
        return f'[{label or p.name}]({p})'
    def own(name,label=None):return link(out/name,label)
    counts={k:sum(r['分类']==k for r in assets) for k in ('正式完整','正式部分完成','探索性诊断','仅有规划')}
    snapshot=json.loads((out/'清点快照.json').read_text())
    doc=['# 实验资产总目录','',f'盘点日期：2026-10-27（Asia/Manila）；当前分支codex/h-usage-space，起点提交`{snapshot["head"]}`。',
        '',f'本工作树共索引{snapshot["file_count"]}个文件、{len(assets)}个物理资产目录、{snapshot["archive_count"]}个归档；人工归并为{len(cards)}类实验/准备/诊断链。**物理目录数不是独立实验重复数**，本地副本、继承和报告副本不能相加。',
        '',f'全部逐目录字段见{own("实验资产总目录.csv")}；所有文件位置见{own("文件索引.csv")}；原始状态摘要见{own("资产快照.json")}。',
        '', '## 分类怎么读','',
        '|分类|物理目录数|解释|','|---|---:|---|',
        *[f'|{k}|{v}|'+({'正式完整':'所列范围计划任务已终结，**不保证所有策略有效或方法比较公平**。','正式部分完成':'有真实搜索/评价，但范围未全部完成或保护停止。','探索性诊断':'局部机制、传输、工程、Mock或只读分析；不自动作为正式收益证据。','仅有规划':'准备/预检/草案，可能有离线检查，不证明正式生成或评价已执行。'}[k])+'|' for k,v in counts.items()],
        '', '分类按任务范围及证据解释，不能只看目录名、protocol.mode或checkpoint.phase。早期T1-D1/D2/D4是传输诊断名称，不是Tier 1 H生成。',
        '', '## 实验链索引','', '|编号|实验|范围分类|数据|图|','|---|---|---|---|',
        *[f'|{c["id"]}|{c["name"]}|{c["classification"]}|{c["dataset"]}|{c["figures"] or "见原结果/不直接绘图"}|' for c in cards],
        '', '## 逐项记录']
    for c in cards:
        doc += ['',f'### {c["id"]}：{c["name"]}','',
            f'- 范围与分类：{c["classification"]}。同链个别准备目录仍按“仅有规划”列入CSV。',
            f'- 研究问题：{c["question"]}。',f'- H/U空间：{c["space"]}。',
            f'- 数据、seed、指标：{c["dataset"]}；{c["seed"]}；{c["metric"]}。',
            f'- 预算与完成量：{c["budget"]}。',f'- 最好结果及对照：{c["result"]}。',
            f'- 首选证据：{link(c["evidence"])}。',f'- 绘图复用：{c["figures"] or "只作归档或需进一步专项核查"}。',
            f'- 数据暴露：{c["exposed"]}。',f'- 认证与可比性边界：{c["limits"]}',
            '- 本工作树对应目录：'+('；'.join(link(p,p) for p in c['physical_assets']) or '准备文档/共享来源，详见文件索引。')]
    doc += ['', '## 额外发现和覆盖边界','',
        '- `learn-fixed-01`是本地工程练习，已完成但不视为新科研比较。通用抽取前后回归也归工程诊断。',
        '- Git全分支能看到`7056f18`等TSP适配实现提交，但当前HEAD没有对应正式TSP campaign。当前工作树的TSP试点协议属于规划，不借代码提交推断运行成功。',
        '- Notion旧V0“实验”页记有EvoFlow/TSP的60次运行与18000代级观察；本工作树未恢复相应原始运行，不将该笔记摘要画进FJSP图或认证成当前实验。',
        f'- Notion读取7页，正文快照见{own("Notion只读来源.json")}。其主要证据页更新到2026-10-25，晚于它的IND/EVO及Hurink验证以本地账本为准；不是穷尽整个Notion工作区。',
        f'- 11个压缩包只读列目录及SHA，见{own("压缩归档索引.json")}；`Partial_109_archive_incomplete_NOT_CERTIFIED`按名称和归档状态保留为旧不完整快照，不能替代最终113槽账本。',
        '- 已按当前目录及祖先检查AGENTS，本现场未找到适用文件。未切换分支/工作树、未推送、未修改旧协议/账本/图表。',
        '- 所有“未知”保留；没有恢复出的历史进程终态或请求正文，不据旧completed标志补造。']
    (out/'实验资产总目录.md').write_text('\n'.join(doc)+'\n')
    # One-to-one local data and primary evidence pointers for every figure.
    source_map={
      '01':['reports/tier2-baseline-a-train21-seed501-20261024-v1/Single_ranking.csv','reports/tier2-baseline-a-train21-seed501-20261024-v1/Sources.csv'],
      '02':['reports/baseline-a-supplemental-T30-seed501-20261024-v1/Composite_pairs_45.csv','reports/tier2-baseline-a-train21-seed501-20261024-v1/Sources.csv','reports/baseline-a-supplemental-T30-seed501-20261024-v1/Sources.csv'],
      '03':['reports/a4-evidence-protocol-20261024-v1/H01_grid_21.csv','runs/h01-state-weight-search-seed501-batch-v3-20261020/Grid_complete.json'],
      '04':['runs/b1-ns-recovery-B-v1-20261022/r501/B/checkpoint.json','runs/h01-state-weight-search-seed501-batch-v3-20261020/r501/B/checkpoint.json','reports/b1-ns-recovery-B-execution-20261023/Population_members.csv','reports/h01-state-weight-search-seed501-batch-v3-20261020/Population_members.csv'],
      '05':['reports/tier2-baseline-a-train21-seed501-20261024-v1/Single_ranking.csv','reports/tier2-baseline-a-train21-seed501-20261024-v1/Oracle.json','reports/b1-ns-recovery-B-execution-20261023/Summary.json','reports/h01-state-weight-search-seed501-batch-v3-20261020/Evidence.json'],
      '06':['runs/h01-state-weight-search-seed501-batch-v3-20261020/r501/B/checkpoint.json','runs/tier2-baseline-a-train21-seed501-20261024-v1/cache/H0_H1_WS.json'],
      '07':['reports/fusion-v2-train21-seed501-20261023-v2/Ranking.csv','reports/fusion-v2-train21-seed501-20261023-v2/Common_state_summary.csv','reports/fusion-v3-borda-train21-seed501-20261024-v1/Ranking.csv','reports/fusion-v3-borda-train21-seed501-20261024-v1/diagnosis/Common_state_summary.csv'],
      '08':['reports/a4-closeout-20261025-v1/Certified_best_so_far.csv','reports/a4-closeout-20261025-v1/Certified_summary.json','reports/a4-closeout-20261025-v1/Timing_isolation.csv'],
      '09':['reports/ind-vs-evo-h01-train21-seed501-20261026-v1/closeout-v1/Completion.csv','reports/ind-vs-evo-h01-train21-seed501-20261026-v1/closeout-v1/Search_curves.csv'],
      '10':['reports/h01-champion-hurink-rdata20-seed501-20261026-v1/Paired_instance_results.csv','reports/h01-champion-hurink-rdata20-seed501-20261026-v1/Summary.json','reports/ind-vs-evo-h01-train21-seed501-20261026-v1/closeout-v1/Champion_certification.json'],
      '11':['reports/h01-progress-step-train21-seed501-20261025-v1/Ranking.csv','reports/fusion-v4-progress-switch-seed501-20261024-v1/Ranking.csv'],
      '12':['reports/cross-feedback-ab-train21-seed501-v1-20261025/execution-v2/Candidates.csv','reports/cross-feedback-ab-train21-seed501-v1-20261025/execution-v2/Final_verification.json']}
    mapping=[]
    for f in FIGURES:
        f['historical_sources']=source_map[f['figure'][:2]]
        for source in f['historical_sources']:
            record(ROOT/source)
            mapping.append({'figure':f['figure'],'source':source,'source_sha256':sha(ROOT/source),'local_inputs':f['inputs'],'role':'原始/认证派生证据；底层结果路径在Sources.csv及原run'})
    save_csv(out/'图表源数据对应.csv',mapping)
    doc=['# 组会图表目录与源数据','', '全部图提供PNG、可编辑文字SVG和矢量PDF。PNG方便粘贴，SVG/PDF用于排版；SVG文字编辑需要本机中文字体。',
         '',f'逐图来源及SHA见{own("图表源数据对应.csv")}；完整读入文件身份见{own("输入来源SHA256.json")}。']
    for f in FIGURES:
        doc+=['',f'## {f["figure"]}：{f["title"]}','',f'用途：{"建议正文" if f["recommended_main"] else "备份页"}。',f'边界：{f["note"]}',
              '', '图片：'+' / '.join(own(p,Path(p).suffix[1:].upper()) for p in f['outputs']),
              '', '本轮绘图表：'+'；'.join(own(p) for p in f['inputs']),
              '', '历史来源：'+'；'.join(link(p,p) for p in f['historical_sources']),
              '', f'![{f["title"]}](图表/{f["figure"]}.png)']
    (out/'组会图表目录.md').write_text('\n'.join(doc)+'\n')
    budgets=[
        dict(experiment='历史B1 Recovery-B',logical=19,API_attempts=19,full_responses=19,new_valid=14,duplicate=0,full_evaluations='本恢复15（含3重认证）；14有效+1失败',FJSP='294完整端态认证行＋20失败前缀行；失败内部成本未知',scope='含6继承生成请求；本恢复新请求13；不能再加原6槽副本'),
        dict(experiment='历史B2演化',logical=20,API_attempts=20,full_responses=20,new_valid=19,duplicate=1,full_evaluations='19新动态',FJSP='399项/798遍',scope='另有16新增静态网格评价+5手工P0缓存；合并新求解735项/1470遍'),
        dict(experiment='A4',logical=93,API_attempts=0,full_responses='不适用',new_valid=93,duplicate='跨轮2',full_evaluations='81新+10历史缓存+2跨轮复用',FJSP='1701项/3402遍',scope='93槽但91不同策略，非5轮完成'),
        dict(experiment='CROSS A/B',logical=30,API_attempts=30,full_responses=29,new_valid=29,duplicate=0,full_evaluations=29,FJSP='609项/1218遍',scope='A14/B15有效；1个A HTTP524；5配对不是30独立搜索重复')]
    for r in d['completion']:
        budgets.append(dict(experiment=f'IND/EVO r{r["repeat"]} {r["arm"]}',logical=int(r['consumed']),API_attempts=int(r['API_attempts']),full_responses=int(r['complete_responses']),new_valid=int(r['certified_children']),duplicate=r['AST_duplicates'] if 'AST_duplicates' in r else '见候选表',full_evaluations='认证候选含缓存；物理求解见Costs_saved_only',FJSP='不从有效率倒推启动次数',scope=f'原定20；HTTP503={r["HTTP503_attempts"]}，HTTP524={r["HTTP524_attempts"]}；未启动{r["unstarted"]}'))
    save_csv(out/'关键搜索预算表.csv',budgets)
    p0=60/865;prob=1-(1-p0)**5
    (out/'搜索预算与证据边界.md').write_text(f'''# 搜索预算与证据边界

## 三种成本必须分开

1. Codex工作额度：当前交互的模型上下文、工具返回及分析工作；不是科研脚本的候选计数。
2. 真实生成请求：脚本访问已配置LeafAPI endpoint，记录在请求账本；逻辑候选、尝试、确认发送、完整响应各有不同含义。
3. 本地FJSP评价：完整策略—实例评价、首解/复检、诊断重放与缓存分别统计；API0不等于计算成本0。

本项目原provider配置指向`https://leafapi.cc/v1/chat/completions`，与Codex交互账本不同。按[OpenAI官方文档](https://learn.chatgpt.com/docs/pricing)，ChatGPT登录使用套餐额度，API-key方式按API费率；不能泛称所有认证方式天然分账。本轮未追溯历史Codex登录方式、套餐或每次交互Token，不估算精确Codex费用，也不由实验Token推算Codex消耗。这里核实的是**科研请求计数不等于Codex消息数**。

## 关键数量

{own('关键搜索预算表.csv')}保留各主实验逻辑、尝试、响应、有效、缓存与评价范围；{own('请求账本范围索引.csv')}覆盖历史账本；{own('所有搜索阶段记录.csv')}列出原检查点阶段。**后两表含同identity快照、继承和副本，禁止直接合计成全项目请求总数。**

旧单成员四组：最终reconciled记录为47正式槽、32正式确认发送，另1诊断；其中名为B1的组10槽但0真实演化发送，冠军来自共同P0。v2.2 seed301为28槽/28发送、20完整有效（含5初始化）。这些旧名不能混同新版B1/历史H01-B2。

历史B1恢复：19槽中4解析/约束错误、14完整有效、1失败实例缺after身份证据。新旧请求分为6继承+13新增；本恢复15评价中有3重认证。不得把有20条成功前缀的失败候选算成第15个有效程序。

历史B2：20演化逻辑/20真实尝试/20完整响应，19新完整有效、1源码重复、不补员。21点网格的5手工P0已含其中，另外16新静态评价；算法20次演化之外有可见开发期查询和强初始化，不能忽略。

## 改善发生在哪里

- B1按原尝试顺序：第2槽首次有效，第3槽再改善，第7槽达到−2.115159624700；之后到第19槽没有冠军提升。P0/P1均值改善，冠军不变；P2没有真实请求。观察轨迹覆盖7种双成员组合，H0/H1实际双成员执行步数为0；不能由源码坐标提到0/1就认定访问了强组合。
- B2含人工P0从−1.983144294915起步；第一代无冠军改进，第二代第一槽即全局逻辑第11槽达到−1.982226488242；剩余9槽没有再次突破，其中第19槽源码重复。此事实不预测第21槽或第三代会得到什么。
- A4第一轮第52查询得到该轮冠军−2.022083102801，之后8查询停滞；第二轮partial第17查询得该轮最好，截止33查询。总93查询没有访问H01等权票，不能把这一未命中归因于动态控制优势。
- IND/EVO的突破分别在r1 EVO第8槽、r2 EVO第17槽。仅重复1双方完整，另两重复partial；503/524与断电影响生成机会，不能把113候选当113次独立演化。

## 增加预算能说明什么

现有B1覆盖不足、B2后半段停滞、A4未命中强等权票，说明“搜索覆盖”仍是可能瓶颈；没有额外实验就不能估计扩大预算后的Fitness，也不能断言一定改善。

可以给出一个**有限空间的命中概率算术**：A4每轮从865策略无放回均匀抽60，对一个预先指定的H01等权票，命中概率为60/865≈{p0*100:.2f}%；按原计划5条独立抽样路径至少一轮命中的概率为1−(1−60/865)^5≈{prob*100:.2f}%。这是候选覆盖概率，不是新实验、不预测冠军质量，也不是300次全局无放回抽样。本轮未抽新候选或消费剩余预算。

完整候选/代码重复/相同train21排程向量不是同一概念。旧B2 19个有效新U形成16组已观测物理排程；旧B1 14有效形成11组，种群P0的5组降到P1的3组（原Behavior_profiles/审计）；相同有限结果不等于全状态程序等价。
''')
    # Useful local locations, both derived artifacts and original evidence.
    nav=['# 有用实验数据、结果和图片的位置','',f'工作区根目录：`{ROOT}`。下列链接可直接打开本机文件；原始路径保持不动。','',
        '## 本次组会交付','',f'- 总结：{own("可用于组会的核心结果与证据边界.md")}。',f'- 全目录：{own("实验资产总目录.md")} / {own("实验资产总目录.csv")}。',
        f'- 全图：{own("组会图表目录.md")}；图表与源数据一一对应：{own("图表源数据对应.csv")}。',
        f'- 预算：{own("搜索预算与证据边界.md")} / {own("关键搜索预算表.csv")}。',
        f'- 所有文件：{own("文件索引.csv")}；归档：{own("压缩归档索引.json")}。','',
        '## 最值得打开的历史数据','', '|用途|结果表/原始来源|如何使用|','|---|---|---|']
    useful=[
      ('10个单H排名','reports/tier2-baseline-a-train21-seed501-20261024-v1/Single_ranking.csv','图01；认证层级和raw路径见同目录Sources.csv'),
      ('45对综合质量','reports/baseline-a-supplemental-T30-seed501-20261024-v1/Composite_pairs_45.csv','图02；39旧+6T30，每行带result_path和SHA'),
      ('全部单H/成员对逐实例','reports/baseline-a-supplemental-T30-seed501-20261024-v1/Composite_static_instances_1155.csv','55策略×21实例；保留来源，不能据此比较同期速度'),
      ('单H事后Oracle','reports/tier2-baseline-a-train21-seed501-20261024-v1/Oracle_instances.csv','不可部署诊断，不是动态理论上界'),
      ('H编号与生成来源','reports/baseline-a-provenance-timeout-audit-20261024-v1/H_mapping.csv','原run+候选ID+代码键+Fitness+冻结编号'),
      ('H01完整21点静态网格','reports/a4-evidence-protocol-20261024-v1/H01_grid_21.csv','图03；每行原结果路径和SHA'),
      ('H01网格逐实例441行','reports/a4-evidence-protocol-20261024-v1/H01_grid_instances_441.csv','核对原Cmax/LB/score'),
      ('历史B1全部候选','reports/b1-ns-recovery-B-execution-20261023/Candidates.csv','保留4解析失败和1评价身份停止，不删槽位'),
      ('历史B1行为记录','reports/b1-ns-recovery-B-execution-20261023/Behavior_profiles.json','实际成员/组合，不从代码出现编号推断动作'),
      ('历史B2全部候选','reports/h01-state-weight-search-seed501-batch-v3-20261020/Candidates.csv','19有效新U+21静态点；缺重复槽须结合原checkpoint'),
      ('历史B2谱系','reports/h01-state-weight-search-seed501-batch-v3-20261020/Lineage.csv','父代使用、子代存活，与Population_members.csv合看'),
      ('B1原顺序检查点','runs/b1-ns-recovery-B-v1-20261022/r501/B/checkpoint.json','含失败和原顺序；只读，不恢复'),
      ('B2原顺序检查点','runs/h01-state-weight-search-seed501-batch-v3-20261020/r501/B/checkpoint.json','含20槽/1重复；只读，不恢复'),
      ('旧test28验证','reports/v1-h01-frozen-pair-test28-v1-20261021/V1_report.json','已暴露旧基准，不能叫全新确认集'),
      ('Fusion V2完整成绩','reports/fusion-v2-train21-seed501-20261023-v2/Ranking.csv','6个null保留；MAX并列机制见图07'),
      ('Fusion V2原始评分/状态','reports/fusion-v2-train21-seed501-20261023-v2/Common_state_actions.csv.gz','大文件，按需流式读取，不能把不同行当独立重复'),
      ('Borda同状态诊断','reports/fusion-v3-borda-train21-seed501-20261024-v1/diagnosis/Common_state_summary.csv','图07取同一WS轨迹3800状态；不新增求解'),
      ('V4算子切换成绩','reports/fusion-v4-progress-switch-seed501-20261024-v1/Ranking.csv','6个固定规则完整，图11'),
      ('A4最终93项','reports/a4-closeout-20261025-v1/Certified_queries.csv','最终收尾优先于原阶段摘要；不续跑'),
      ('A4时间证据隔离','reports/a4-closeout-20261025-v1/Timing_isolation.csv','科学质量与严格T30墙钟认证分开'),
      ('反馈A/B逐实例','reports/cross-feedback-ab-train21-seed501-v1-20261025/execution-v2/Per_instance.csv','29有效子代逐实例，失败单列'),
      ('简单动态规则全族','reports/h01-progress-step-train21-seed501-20261025-v1/Ranking.csv','21规则含3静态；不只挑冠军'),
      ('IND/EVO最终完成量','reports/ind-vs-evo-h01-train21-seed501-20261026-v1/closeout-v1/Completion.csv','113/120、117尝试，分方法/重复'),
      ('新冠军冻结与认证','reports/ind-vs-evo-h01-train21-seed501-20261026-v1/closeout-v1/Champion_freeze.json','代码SHA和result身份，配合同目录Champion_certification.json'),
      ('新冠军代码','reports/h01-champion-hurink-rdata20-seed501-20261026-v1/Frozen_U/dynamic.py','r2_EVO_s16冻结代码，不是本轮新改进'),
      ('静态等权代码','reports/h01-champion-hurink-rdata20-seed501-20261026-v1/Frozen_U/equal.py','冻结对照'),
      ('训练外验证逐实例','reports/h01-champion-hurink-rdata20-seed501-20261026-v1/Paired_instance_results.csv','图10；20新实例跨基准确认，现已暴露'),
      ('冻结H完整代码','reports/h01-champion-hurink-rdata20-seed501-20261026-v1/H_frozen.json','10H顺序/代码，不能只凭编号推断质量')]
    for purpose,path,note in useful:
        require((ROOT/path).exists(),'useful local file exists: '+path)
        nav.append(f'|{purpose}|{link(path,path)}|{note}|')
    nav+=['','## 以后只重画图怎么做','',
        '绘图脚本只使用已有CSV/JSON，不导入求解器、不访问模型。当前项目.venv没有matplotlib，本机`/opt/homebrew/bin/python3`已有matplotlib 3.10.0，因此没有安装或改变项目依赖。',
        '', '```sh', f"cd '{ROOT}'", '/opt/homebrew/bin/python3 -B tools/meeting_results_audit.py build', '/opt/homebrew/bin/python3 -B tools/meeting_results_audit.py verify','```','',
        '此命令只重建本次独立派生目录的图表/表格，不调用旧报告生成入口，不改历史数据。若源文件变动，先保留此版产物并核对原因，不覆盖原实验记录。']
    (out/'有用文件位置导航.md').write_text('\n'.join(nav)+'\n')


def build(out):
    inventory(out)
    d=normalise(out)
    plots(out,d)
    cards,assets=catalogue(out,d)
    write_documents(out,d,cards,assets)
    save_json(out/'图表来源对应.json',FIGURES)
    save_json(out/'输入来源SHA256.json',SOURCES)
    save_json(out/'数值验收.json',{'passed':len(CHECKS),'checks':CHECKS,'new_API_requests':0,'new_FJSP_solves':0})
    print(json.dumps({'figures':len(FIGURES),'formats':['PNG','SVG','PDF'],'checks':len(CHECKS),'source_files':len(SOURCES)},ensure_ascii=False))


def verify(out):
    sources=json.loads((out/'输入来源SHA256.json').read_text())
    changed=[p for p,s in sources.items() if not (ROOT/p).exists() or sha(ROOT/p)!=s['sha256']]
    require(not changed,'all read historical source files unchanged')
    index=json.loads((out/'图表来源对应.json').read_text())
    missing=[p for f in index for p in f['outputs'] if not (out/p).is_file()]
    require(not missing,'all listed figures exist')
    save_json(out/'最终核对.json',{'source_files':len(sources),'changed':changed,'figures':len(index),'missing':missing,'new_API_requests':0,'new_FJSP_solves':0})
    print('verified',len(sources),'sources and',len(index),'figures')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inventory', 'build', 'verify'])
    parser.add_argument('--out-dir', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.out_dir.resolve()
    if out.parent != ROOT / 'reports' or not out.name.startswith('组会实验盘点-'):
        parser.error('outputs must be an independent reports/组会实验盘点-* directory')
    out.mkdir(exist_ok=True)
    if args.action == 'inventory':
        print(json.dumps(inventory(out), ensure_ascii=False, indent=2))
    elif args.action == 'build':
        build(out)
    else:
        verify(out)


if __name__ == '__main__':
    main()
