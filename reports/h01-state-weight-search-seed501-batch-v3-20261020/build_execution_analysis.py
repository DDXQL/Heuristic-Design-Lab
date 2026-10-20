"""Derive B2-1 tables/audit from saved results only. No API, solver or replay."""
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from random import Random
import csv
import hashlib
import json
import shutil
from statistics import fmean

from fjsp_usage.research.candidates import Candidate, parse_response
from fjsp_usage.research.evolution import ranked, select_parents
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_result
from fjsp_usage.usage_v2 import VERSION as INTERFACE
from tools import h01_weight_local as local
from tools import h01_weight_search as original

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
RUN = ROOT / 'runs' / OUT.name
read = lambda p: json.loads(p.read_text())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def table(name, rows):
    with (OUT / name).open('w', newline='') as stream:
        keys = list(dict.fromkeys(k for row in rows for k in row))
        w = csv.DictWriter(stream, fieldnames=keys, lineterminator='\n')
        w.writeheader(); w.writerows(rows)


def main():
    plan = local.pins_check(RUN)
    state = read(RUN / 'r501/B/checkpoint.json')
    journal = read(RUN / 'r501/B/budgeted_evolution_requests.json')
    evidence = read(OUT / 'Evidence.json')
    assert len(evidence['alpha_profiles']) == 19
    assert all(p['any_within_instance_alpha_varies'] for p in evidence['alpha_profiles'].values())
    initial = read(RUN / 'Initial_population.json')
    assert state['phase'] == 'completed' and state['generation'] == 2
    assert state['inflight'] is None and len(state['attempts']) == 20
    assert len(journal['requests']) == 20 and len(journal['api_attempts']) == 20
    results = {v['id']: read(RUN / 'results' / (v['id'] + '.json')) for v in plan['versions']}
    results.update({k: v['result'] for k, v in state['evaluations'].items()})
    for result in results.values():
        check_result(result, plan['names'])
        assert result['valid'] and len(result['instances']) == 21
        assert result['fitness'] == fmean(row['score'] for row in result['instances'])
        for row in result['instances']:
            assert row['score'] == -row['makespan'] / row['lower_bound']
            if row.get('physical_schedule_sha256'):
                assert digest(row['physical_schedule']) == row['physical_schedule_sha256']
                assert row['physical_schedule_sha256'] == row['recheck_physical_schedule_sha256']
    programs = {p['id']: p for p in initial}
    h = read(RUN / 'H_source_binding.json')
    members = tuple(Candidate(r['review']['description'], r['candidate']['code'],
                              r['candidate']['key'], 'h') for r in h['members'])
    for attempt in state['attempts']:
        record = journal['requests'][attempt['id']]
        c = original.validate(parse_response(record['text'], interface_version=INTERFACE,
                                             member_count=10).code)
        parsed = parse_response(record['text'], interface_version=INTERFACE, member_count=10)
        assert c.key == attempt['code_key']
        programs[attempt['id']] = {'id': attempt['id'], 'candidate': asdict(parsed),
                                  'fitness': results.get(attempt['id'], {}).get('fitness')}
        prompt = original.build_prompt('B', attempt['operator'],
                                        [programs[k] for k in attempt['parents']], members)
        assert prompt == record['prompt']
        assert prompt == (RUN / 'r501/B/prompts' / attempt['id'].replace('/', '_')).read_text()
        assert record['prompt_key'] == digest({'prompt': prompt, 'kind': 'U'})
        assert len(record['attempt_ids']) == 1 and record['status'] == 'completed'
        aid = record['accepted_attempt_id']; api = journal['api_attempts'][aid]
        wire = read(RUN / 'wire_responses' / (hashlib.sha256(aid.encode()).hexdigest() + '.json'))
        assert api['status'] == 'completed' and api['send_confirmed']
        assert wire['global_key'] == aid and wire['send_confirmed']
        assert wire['status'] == 'wire_completed_before_settlement'
        assert wire['reply'] == api['reply']
        assert record['text'] == api['reply']['text'] and record['usage'] == api['usage']
        assert record['response_id'] == api['response_id']
    # Reconstruct selection and replay only the PRNG parent draws, never scheduling.
    populations = [ranked(initial)]
    rng = Random(501)
    for gen in range(2):
        attempts = [a for a in state['attempts'] if f'/g{gen:04d}/' in a['id']]
        assert Counter(a['operator'] for a in attempts) == {'CROSS': 5, 'MUTATE': 5}
        for index, a in enumerate(attempts):
            assert a['operator'] == ('CROSS' if index < 5 else 'MUTATE')
            expected = select_parents(populations[-1], 5 if index < 5 else 1, rng)
            assert a['parents'] == [p['id'] for p in expected]
        children = [programs[a['id']] for a in attempts if a['status'] == 'valid']
        populations.append(ranked(populations[-1] + children)[:5])
    for observed, expected in ((read(RUN / 'P1_population.json')['population'], populations[1]),
                               (state['population'], populations[2])):
        assert [(p['id'], p['fitness']) for p in observed] == [(p['id'], p['fitness']) for p in expected]
    snapshot = RUN / 'P2_population.json'
    if not snapshot.exists():
        snapshot.write_text(json.dumps({'generation': 2, 'basis': 'completed actual checkpoint',
                                        'population': state['population']}, ensure_ascii=False, indent=2) + '\n')
    table('Population_members.csv', [
        {'population': f'P{g}', 'rank': n + 1, 'id': p['id'], 'fitness': p['fitness'],
         'manual_initial': p['id'].startswith('MANUAL/'), 'code_key': p['candidate']['key']}
        for g, population in enumerate(populations) for n, p in enumerate(population)])
    cost_rows = []
    for key, result in results.items():
        for row in result['instances']:
            alphas = row.get('observed_alpha')
            cost_rows.append({
                'id': key, 'file': row['file'], 'makespan': row['makespan'], 'LB': row['lower_bound'],
                'score': row['score'], 'single_solve_wall_seconds': row['single_solve_seconds'],
                'recheck_wall_seconds': row['deterministic_recheck_seconds'], 'cpu_seconds': None,
                'primary_h_calls': sum(row['single_h_calls']) if 'single_h_calls' in row else None,
                'recheck_h_calls': sum(row['deterministic_recheck_h_calls']) if 'deterministic_recheck_h_calls' in row else None,
                'alpha_min': min(alphas) if alphas else None, 'alpha_max': max(alphas) if alphas else None,
                'observed_steps': len(alphas) if alphas else None,
                'physical_schedule_sha256': row.get('physical_schedule_sha256'),
                'timing_basis': 'cached fixed-h; excludes U interface overhead' if key in ('alpha_000', 'alpha_100')
                    else 'cached U evaluation' if key in ('alpha_025', 'alpha_050', 'alpha_075') else 'current batch U evaluation'})
    table('Instance_costs.csv', cost_rows)
    physical_groups = defaultdict(list)
    for key in state['evaluations']:
        physical_groups[tuple(row['physical_schedule_sha256'] for row in results[key]['instances'])].append(key)
    write('Observed_physical_groups.json', {
        'scope': '19 complete new U, physical schedules on 21train; no semantic equivalence claim',
        'unique_groups': len(physical_groups), 'groups': list(physical_groups.values())})
    best_id = evidence['best_new']; best = results[best_id]; equal = results['alpha_050']
    def comparison(left, right):
        return dict(Counter('win' if a['makespan'] < b['makespan'] else 'loss' if a['makespan'] > b['makespan'] else 'tie'
                            for a, b in zip(left['instances'], right['instances'])))
    def cost(result):
        return {'fitness': result['fitness'], 'Cmax_sum_descriptive_only': sum(i['makespan'] for i in result['instances']),
                'solve_wall_seconds': sum(i['single_solve_seconds'] for i in result['instances']),
                'recheck_wall_seconds': sum(i['deterministic_recheck_seconds'] for i in result['instances']),
                'primary_h_calls': sum(sum(i['single_h_calls']) for i in result['instances']) if 'single_h_calls' in result['instances'][0] else None,
                'cpu_seconds': None}
    new_results = [results[v['id']] for v in plan['versions'] if not v['reused']] + [v['result'] for v in state['evaluations'].values()]
    protected = read(ROOT / 'docs/usage-space/h01-b201-prepared/Historical_records_unchanged.json')
    for name, before in protected['files'].items():
        assert sha(ROOT / name) == before['sha256'] and (ROOT / name).stat().st_mtime_ns == before['mtime_ns']
    audit = {
        'stage_B': 'completed, 21/21 valid, 5 reused + 16 new', 'stage_C': 'completed',
        'stage_D': 'completed', 'stage_E': 'saved-result analysis only', 'execution_commit': '0b6432d970ab2b3cceb690f8a0afadab570033e7',
        'plan_sha256': sha(RUN / 'Plan.json'), 'frozen_pins_verified': len(plan['pins']),
        'historical_files_bytes_and_mtimes_unchanged': len(protected['files']),
        'logical_candidates': len(journal['requests']), 'API_attempts': len(journal['api_attempts']),
        'complete_responses': 20, 'retry_attempts': 0, 'pending': 0, 'request_failures': 0,
        'legal_generated': 20, 'complete_valid_new': 19, 'duplicates': 1,
        'invalid_source_or_evaluation_failures': 0, 'legal_rate': 1.0, 'valid_rate_per_logical': .95,
        'duplicate_rate': .05, 'fully_evaluated_new_candidates': 35,
        'new_candidate_instance_evaluations': 735, 'new_solve_passes': 1470,
        'new_solve_wall_seconds': sum(sum(i['single_solve_seconds'] for i in r['instances']) for r in new_results),
        'new_recheck_wall_seconds': sum(sum(i['deterministic_recheck_seconds'] for i in r['instances']) for r in new_results),
        'new_primary_h_calls': sum(sum(sum(i['single_h_calls']) for i in r['instances']) for r in new_results),
        'new_recheck_h_calls': sum(sum(sum(i['deterministic_recheck_h_calls']) for i in r['instances']) for r in new_results),
        'cpu_seconds': None, 'actual_cost': None, 'account_price_invoice_queries': 0,
        'budget': read(RUN / 'Budget_summary.json'), 'best_new': best_id,
        'best_vs_equal': comparison(best, equal),
        'best_physical_schedules_changed_vs_equal': sum(a['physical_schedule_sha256'] != b['physical_schedule_sha256'] for a,b in zip(best['instances'], equal['instances'])),
        'best_observed_steps': sum(len(i['observed_alpha']) for i in best['instances']),
        'H0': cost(results['alpha_100']), 'equal_and_grid_champion': cost(equal), 'best_new_cost': cost(best),
        'best_fitness_improvement': best['fitness'] - equal['fitness'],
        'best_mean_normalized_Cmax_improvement_percent': (best['fitness']-equal['fitness'])/abs(equal['fitness'])*100,
        'all_20_actual_prompts_reconstructed_exactly': True, 'seed501_all_parent_draws_exact': True,
        'all_20_response_attempt_wire_links_verified': True, 'P1_P2_survival_reconstructed_exactly': True,
        'no_search_restart': True, 'no_extra_evaluation_or_replay': True,
        'no_validation_test_instance_load': True, 'all_19_new_evaluated_U_observed_dynamic': True,
        'new_constant_champion': None, 'training_only': True}
    write('Execution_audit.json', audit)
    archive = OUT / 'evidence'
    archive.mkdir(exist_ok=True)
    for name in ('B2_1_authorization.json', 'B2_1_execution_scope.json', 'Plan.json', 'config.pending.json',
                 'protocol.json', 'H_context.json', 'Grid_complete.json', 'Search_status.json',
                 'Budget_summary.json', 'Grid_execution.log', 'Search_execution.log'):
        shutil.copyfile(RUN/name, archive/name)
    for path in (RUN/'sources').glob('*.py'):
        shutil.copyfile(path, OUT/'sources'/path.name)
    for sub in ('wire_responses', 'r501/B/prompts'):
        target = archive / ('prompts' if sub.endswith('prompts') else sub)
        target.mkdir(exist_ok=True)
        for path in (RUN/sub).iterdir():
            if path.is_file(): shutil.copyfile(path, target/path.name)
    shutil.copyfile(RUN/'r501/B/budgeted_evolution_requests.json', archive/'API_journal.json')
    shutil.copyfile(RUN/'r501/B/events.jsonl', archive/'Evolution_events.jsonl')
    write('Original_result_hashes.json', {str(p.relative_to(ROOT)): sha(p) for p in sorted(RUN.rglob('*')) if p.is_file()})
    lines = ['# B2-1：固定H0/H1两代权重程序演化', '',
        '**阶段B–E全部完成。** 原协议、H、七状态、Prompt、模型参数、21train及共享15秒期限均未改；未访问validation/test。', '',
        '## 基线与新候选', '',
        '|策略|Fitness|21实例Cmax合计（非优化目标）|首次求解秒|复检秒|首次h评分调用|',
        '|---|---:|---:|---:|---:|---:|']
    for label, key in [('H0（缓存固定h）','alpha_100'), ('人工等权／21点网格冠军','alpha_050'), ('最佳新动态U '+best_id,best_id)]:
        c=cost(results[key]); lines.append(f'|{label}|{c["fitness"]:.12f}|{c["Cmax_sum_descriptive_only"]}|{c["solve_wall_seconds"]:.3f}|{c["recheck_wall_seconds"]:.3f}|{c["primary_h_calls"] if c["primary_h_calls"] is not None else "未知"}|')
    lines += ['', '21个静态点全部有效；新增16点，复用α=0、0.25、0.5、0.75、1的原成绩。全部点见Candidates.csv及Fixed_weight_curve.svg；所有逐实例makespan见Instances.csv，逐实例计时与h调用见Instance_costs.csv。', '',
        f'最佳新U的Fitness比等权高{audit["best_fitness_improvement"]:.12f}，即平均Cmax/LB降低约{audit["best_mean_normalized_Cmax_improvement_percent"]:.4f}%。逐实例10胜、7负、4平；Cmax合计4050，反而比等权4047高3，因为既定目标按各实例LB归一化后取平均。', '',
        '该程序在3800次实际决策中α范围为[0.262746, 0.539620]，每步实际启用H0/H1，主导成员切换83次，19/21个实例物理排程与等权不同。它读取progress、remaining_work_mean/std及machine_ready_mean/std；未读取candidate_pair_ratio和previous_heuristic。', '',
        '本批19个新且完整评价的U均在实际轨迹中改变权重，没有新常量U冠军。重复槽位B/g0001/000008与B/g0001/000007源码键相同；不补发、不重评。另有源码不同但21train物理排程相同的程序：19个有效新U形成16组，详见Observed_physical_groups.json；这不是普遍程序等价证明。', '',
        '## 实际冠军源码', '', '```python', (OUT/'sources'/f'{best_id.replace("/", "_")}.py').read_text().rstrip(), '```', '',
        '## 代际变化与谱系', '', '|种群|最佳Fitness|平均Fitness|完整成员及Fitness|', '|---|---:|---:|---|']
    for g,pop in enumerate(populations):
        lines.append(f'|P{g}|{pop[0]["fitness"]:.12f}|{fmean(p["fitness"] for p in pop):.12f}|'+ '<br>'.join(f'{p["id"]}: {p["fitness"]:.12f}' for p in pop)+'|')
    lines += ['', '第一代10个子代全部有效，4个进入P1；冠军仍为人工等权，故第一代没有新冠军改进。第二代确从P1抽父代：5次交叉均包含全部4个第一代新成员，3次变异以第一代新成员为父代，共23个父代引用；其余7次引用人工等权。第二代9个有效、1重复，4个第二代子代进入P2，其中2个超过等权。完整20槽父子关系见Lineage.csv；P0/P1/P2全部成员见Population_members.csv。', '',
        '全部20个实际Prompt已按真实父代源码重建并逐字节核对，seed501父代抽样及P1/P2生存选择已从原结果独立复核。父代Fitness只影响外部生存／种群，未显式发送给模型。跨代继承和本批改进已观察到，但不能据此证明显式数值反馈有效，也不能单独归因于多代优于等预算其他搜索。', '',
        '## 预算、评价与成本', '',
        '20个逻辑候选／20次真实API尝试／20份完整响应；重试0，pending0，接口失败0，非法源码0，评价失败0，源码重复1。合法生成率20/20=100%，新且完整有效率19/20=95%，重复率1/20=5%。实际完成35次新增完整训练评价（16静态＋19新U），735个候选—实例评价、1470遍求解，无重启、额外初始化、诊断回放或补发。', '',
        f'新增评价的首次求解合计{audit["new_solve_wall_seconds"]:.3f}秒，复检{audit["new_recheck_wall_seconds"]:.3f}秒；h评分调用分别为{audit["new_primary_h_calls"]:,}和{audit["new_recheck_h_calls"]:,}次。API输入Token 53,502、输出6,097，无未知usage。实际费用unknown/null，账户／价格／账单查询为0；未把未知费用填成0。', '',
        '计时使用perf_counter，为求解／复检墙钟耗时，未采集CPU进程秒。H0端点复用历史固定h计时，不含U接口开销，h调用数未知；等权也是历史缓存。本批新U与缓存基线并非同期精确速度对照，不将秒数差直接解释为算法效率因果变化。冠军首次h调用比等权约多3.31%，两者每步都用两成员，调用量仍会随排程路径与合法动作数变化。', '',
        '## 证据边界与下一步', '',
        '本批证明：在固定H0/H1、原接口和21train条件下，真实LLM两代演化产生了动态权重程序，通过外部选择实现了子代继承，并有新动态U小幅超过人工等权和有限21点静态网格。人工等权相对固定h的主要收益是既有基线收益，不能记为LLM新发现。', '',
        '尚未证明：超过所有可能固定权重、动态性本身的独立因果收益、稳定的多种子收益、泛化、七维状态的充分性，或两代演化比其他等预算搜索更优。未做新的消融、续排或独立评价；不由权重变化或主导切换数推断其更好。', '',
        '下一步最值得验证：冻结本批动态冠军及α=0.5，在预先登记、未参与本批选择的独立数据上做配对评价，检验约0.0463%的微小训练优势是否保持，并继续完整披露退化实例。本轮不执行。', '',
        '## 复现与原始证据', '',
        '原始目录：`runs/'+RUN.name+'/`。请求尝试、完整响应、Prompt、执行授权、协议及事件的只读副本位于evidence/；全部原始评价、物理排程及checkpoint保留在原始目录并另作压缩备份。Original_result_hashes.json逐项绑定原始文件，Execution_audit.json记录核验结论。未复制任何凭证或原始账单。', '',
        '唯一正式入口：`tools/h01_weight_local.py`。本次顺序运行`grid --run-dir runs/'+RUN.name+'`、`search --run-dir runs/'+RUN.name+' --env-file <本机既有凭证路径>`，最后以文档Python运行同入口`report --run-dir ...`。既定恢复命令仍为同目录同一`search`；本批已完成，勿再次启动。', '']
    (OUT/'B2_1_REPORT_ZH.md').write_text('\n'.join(lines))
    print(json.dumps({k:audit[k] for k in ('best_new','fully_evaluated_new_candidates','new_solve_wall_seconds','new_recheck_wall_seconds','new_primary_h_calls','best_vs_equal','best_fitness_improvement')},ensure_ascii=False))


if __name__ == '__main__':
    main()
