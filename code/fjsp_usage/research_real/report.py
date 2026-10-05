"""All planned repeats and actual paired counts; failures never silently vanish."""

from itertools import combinations
from collections import Counter
import json
from statistics import fmean, pstdev

from fjsp_usage.research.events import atomic_json
from .assets import check_result
from .workflow import ARMS


def statistics(entries, seeds):
    expected = [(s, a) for s in seeds for a in ARMS]
    if [(e['seed'], e['arm']) for e in entries] != expected:
        raise ValueError('report requires every predeclared repeat/group')
    groups, pairs = {}, {}
    for arm in ARMS:
        planned = [e for e in entries if e['arm'] == arm]
        success = [e for e in planned if e.get('test_result') and e['test_result']['valid']]
        values = [e['test_result']['fitness'] for e in success]
        groups[arm] = {'planned_repeats': len(seeds), 'valid_repeats': len(values),
            'failure_rate': (len(seeds)-len(values))/len(seeds),
            'failed_seeds': [e['seed'] for e in planned if e not in success],
            'mean': fmean(values) if values else None, 'population_std': pstdev(values) if values else None,
            'denominator_note': 'successful repeats only; failures listed; incomplete results are not formal success'}
    for left, right in combinations(ARMS, 2):
        differences, excluded = [], []
        for seed in seeds:
            row = {e['arm']: e for e in entries if e['seed'] == seed}
            l, r = row[left].get('test_result'), row[right].get('test_result')
            if l and r and l['valid'] and r['valid']:
                differences.append({'seed': seed, 'difference': l['fitness'] - r['fitness']})
            else:
                excluded.append({'seed': seed, 'reasons': {arm: (
                    row[arm]['selection_status'] if row[arm].get('test_result') is None else
                    row[arm]['test_result'].get('error_type', 'invalid_test_batch'))
                    for arm in (left,right) if not row[arm].get('test_result') or not row[arm]['test_result']['valid']}})
        values = [d['difference'] for d in differences]
        pairs[left+'-'+right] = {'planned_pairs': len(seeds), 'actual_pairs': len(values),
            'differences': differences, 'mean_difference': fmean(values) if values else None,
            'excluded': excluded,
            'population_std': pstdev(values) if values else None}
    return {'groups': groups, 'paired_differences': pairs}


def write_report(workflow):
    workflow.assert_current()
    frozen = workflow.freeze()
    result = workflow.read('Test_complete.json', 'Test_complete')
    if result['freeze_hash'] != frozen['artifact_sha256']:
        raise ValueError('report test/freeze mismatch')
    for row in result['entries']:
        if row['test_result'] is not None:
            check_result(row['test_result'], workflow.dataset.names['test'])
    ledger = workflow.ledger.summary()
    stats = statistics(result['entries'], workflow.config.seeds)
    search_costs = {}
    for path in sorted(workflow.directory.rglob('checkpoint.json')):
        state = json.loads(path.read_text())
        statuses = Counter(row['status'] for row in state['attempts'])
        count = len(state['attempts'])
        search_costs[str(path.parent.relative_to(workflow.directory))] = {
            'candidate_attempts': count, 'statuses': dict(statuses),
            'valid_rate': statuses['valid']/count if count else None,
            'evaluation_reservations': len(state['evaluations']), 'phase': state['phase'],
            'evaluation_seconds': sum(r.get('result', {}).get('elapsed_seconds', 0) for r in state['evaluations'].values())}
    stage_costs = {}
    for split in ('validation', 'test'):
        # Cache keys are opaque, so expose the counts from saved split results.
        results = ([r['test_result'] for r in result['entries'] if r['test_result'] is not None]
                   + ([result['fixed_h_result']] if result['fixed_h_result'] else [])) if split == 'test' else []
        if split == 'validation':
            for entry in frozen['selection']['entries']:
                if entry['selection_status'] == 'selected':
                    star = workflow.read(f'r{entry["seed"]}/{entry["arm"]}/U_star.json', 'U_star')
                    results.extend(r['result'] for r in star['validation_results'])
                elif entry['selection_status'] == 'selection_failed':
                    results.extend(r['result'] for r in entry['validation_results'])
            results.extend(r['result'] for r in frozen['selection']['fixed_h_validation'])
        stage_costs[split] = {'candidate_result_references': len(results), 'valid_results': sum(r['valid'] for r in results),
                             'requests': 0, 'cache_note': 'identical code/H/split results reused; references are not unique evaluations'}
    test_rows = [r for e in result['entries'] if e['test_result'] for r in e['test_result']['instances']]
    if result['fixed_h_result']:
        test_rows += result['fixed_h_result']['instances']
    report = {'mode': workflow.config.mode, 'research_claim': 'synthetic interface acceptance only'
        if workflow.config.mode == 'synthetic' else 'staged real experiment; assess failures before conclusions',
        'freeze_hash': frozen['artifact_sha256'], 'analysis': workflow.config.analysis,
        'entries': result['entries'], 'statistics': stats, 'budget': ledger,
        'search_costs': search_costs, 'stage_costs': stage_costs,
        'local_unique_stage_evaluations': len(workflow.cache.data['records']),
        'fixed_h_result': result['fixed_h_result'],
        'all_planned_succeeded': bool(result['fixed_h_result'] and result['fixed_h_result']['valid']
            and all(e['test_result'] and e['test_result']['valid'] for e in result['entries'])),
        'timing': {'generation_http_seconds': sum(p['elapsed_seconds'] for p in ledger['phases'].values()),
            'stage_evaluation_seconds': sum(r['result'].get('elapsed_seconds', 0)
                                          for r in workflow.cache.data['records'].values() if r['status'] == 'completed'),
            'test_single_solve_seconds_sum': sum(r['single_solve_seconds'] for r in test_rows),
            'test_deterministic_recheck_seconds_sum': sum(r['deterministic_recheck_seconds'] for r in test_rows),
            'note': 'single solve measured inside worker, including feasibility check; excludes process startup, recheck and traces; synthetic timings are not deployment benchmarks'},
        'limitations': ['JSON gateway adapter only; provider-native adapter must be configured/verified separately',
                         'token/currency limits depend on unverified reservation/prices; requests have hard caps',
                         'AST restriction and killable workers are not a general OS sandbox']}
    atomic_json(workflow.directory/'report.json', report)
    lines = ['# ' + ('合成接口验收报告' if workflow.config.mode == 'synthetic' else '分阶段实验报告'), '',
             '本报告保留所有预先声明的种子与失败记录。合成验收不构成正式研究结果。', '',
             '| 组 | 计划重复 | 成功重复 | 均值 | 总体标准差 | 失败种子 |',
             '|---|---:|---:|---:|---:|---|']
    for arm, value in stats['groups'].items():
        lines.append(f'| {arm} | {value["planned_repeats"]} | {value["valid_repeats"]} | {value["mean"]} | {value["population_std"]} | {value["failed_seeds"]} |')
    lines += ['', '配对差值与实际配对数见 report.json；不以单个最好种子代替全部重复。', '',
              f'已预留请求：{ledger["request_slots"]}；确认发送：{ledger["confirmed_sends"]}；usage 未知：{ledger["unknown_usage_requests"]}。',
              '未提供价格时费用为 null；合成服务的 token 数为固定测试值。',
              '单次排程与确定性复核分别计时；单次含可行性检查，不含进程启动和复核，合成计时不代表部署性能。']
    (workflow.directory/'report.md').write_text('\n'.join(lines)+'\n')
    workflow.progress('REPORT_COMPLETE')
    return report
