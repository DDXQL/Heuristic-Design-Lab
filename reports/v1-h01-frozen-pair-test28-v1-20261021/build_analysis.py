"""V1-1 saved-result analysis only. Never calls solver, API or selection."""
from pathlib import Path
from statistics import fmean
from collections import Counter
import csv
import hashlib
import json
import shutil
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
RUN = ROOT / 'runs' / OUT.name
read = lambda p: json.loads(p.read_text())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def fmt(v, digits=6):
    return 'null' if v is None else f'{v:.{digits}f}'


def copy_evidence(source, destination):
    if destination.exists():
        assert sha(source) == sha(destination), 'evidence copy changed: ' + str(destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def main():
    summary = read(RUN / 'V1_report.json')
    protocol = read(RUN / 'Protocol.json')
    checkpoint = read(RUN / 'checkpoint.json')
    assert summary['identity'] == sha(RUN / 'Protocol.json') == '11e87d24f00eeec628659cddcff2e796cd9f6824c062da4323623162ff3bad60'
    assert checkpoint['phase'] == 'completed' and len(checkpoint['tasks']) == 56
    assert summary['planned_evaluations'] == summary['reserved_evaluations'] == 56
    rows = list(csv.DictReader((RUN / 'Paired_results.csv').open()))
    assert len(rows) == 28 and [r['file'] for r in rows] == [r['file'] for r in protocol['instances']]
    costs = []; differences = []; failures = []; success_passes = 0
    for task in protocol['tasks']:
        path = RUN / 'results' / (task['id'] + '.json')
        assert sha(path) == checkpoint['tasks'][task['id']]['result_sha256']
        record = read(path); result = record['result']
        assert record['task'] == task and record['identity'] == summary['identity']
        row = result['instances'][0] if result['valid'] else {}
        if result['valid']:
            assert row['physical_schedule_sha256'] == row['recheck_physical_schedule_sha256']
            assert row['single_h_calls'] == row['deterministic_recheck_h_calls']
            assert abs(row['score'] + row['makespan'] / row['lower_bound']) < 1e-12
            assert row['single_solve_seconds'] + row['deterministic_recheck_seconds'] <= 15
            success_passes += 2
        else:
            failures.append({'task': task, 'error_type': result.get('error_type'), 'error': result.get('error')})
        costs.append({'task_id': task['id'], 'file': task['file'], 'role': task['role'], 'valid': result['valid'],
            'evaluation_wall_seconds': result.get('primary_evaluation_seconds'),
            'single_wall_seconds': row.get('single_solve_seconds'), 'recheck_wall_seconds': row.get('deterministic_recheck_seconds'),
            'single_h_calls': sum(row['single_h_calls']) if result['valid'] else None,
            'recheck_h_calls': sum(row['deterministic_recheck_h_calls']) if result['valid'] else None,
            'single_h0_calls': row.get('single_h_calls', [None]*10)[0],
            'single_h1_calls': row.get('single_h_calls', [None]*10)[1]})
    for row in rows:
        if row['delta_fitness']:
            d = (float(row['equal_Cmax']) - float(row['dynamic_Cmax'])) / float(row['LB'])
            assert abs(d - float(row['delta_fitness'])) < 1e-12
            differences.append(d)
    complete = len(differences) == 28
    if complete:
        assert abs(fmean(differences) - summary['statistics']['delta_fitness']) < 1e-12
        for role in ('dynamic', 'equal'):
            assert abs(-fmean(float(r[role+'_Cmax'])/float(r['LB']) for r in rows) - summary['fitness'][role]) < 1e-12
    with (OUT / 'Evaluation_costs.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(costs[0]), lineterminator='\n'); writer.writeheader(); writer.writerows(costs)
    history = read(ROOT / 'docs/usage-space/v1-0-prepared-20261021/B2_1_history_unchanged.json')
    changed = [p for p, old in history['files'].items() if sha(ROOT/p) != old['sha256'] or (ROOT/p).stat().st_mtime_ns != old['mtime_ns']]
    assert not changed
    times = list(checkpoint['tasks'].values())
    span = max(t.get('finished_at_unix', t['reserved_at_unix']) for t in times) - min(t['reserved_at_unix'] for t in times)
    evaluation_wall = sum(c['evaluation_wall_seconds'] for c in costs if c['evaluation_wall_seconds'] is not None)
    audit = {'protocol_sha256': summary['identity'], 'execution_commit': '81206b33643df4d6de8d0027f5ea261a5c80db28',
        'completed_tasks': len(costs), 'status_counts': dict(Counter(t['status'] for t in times)),
        'valid_evaluations': sum(c['valid'] for c in costs), 'certified_successful_solve_passes': success_passes,
        'failed_evaluations': failures, 'all_original_28_pairs_complete': complete,
        'evaluation_wall_seconds': evaluation_wall, 'reservation_to_last_finish_wall_seconds': span,
        'CPU_process_seconds': None, 'API_requests': 0, 'new_model_programs': 0,
        'automatic_retries': 0, 'execution_restarts': 0, 'extra_replays': 0,
        'analysis_python': sys.executable,
        'presentation_note': 'Saved-result analysis only. Frozen solver and statistical report use original project venv. Tables retained; no new dependencies, solves or statistical substitution.',
        'protected_B2_files_checked': len(history['files']), 'protected_B2_bytes_and_mtimes_changed': changed,
        'independence_scope': 'Checked project records and DDXQL knowledge only, not proof of all external history.',
        'frozen_external_use_confirmation_pending_note': 'V1-0 historical pending marker retained unchanged; fulfilled by V1_1_authorization.json, not by editing Protocol.json.',
        'resource_isolation': 'Sequential CLI, original per-run lock; no dedicated CPU/resource reservation. Wall times are observations, not precise speed causality.'}
    write('Execution_audit.json', audit)
    evidence = OUT / 'evidence'; evidence.mkdir(exist_ok=True)
    for name in ('Protocol.json', 'Protocol.sha256', 'V1_1_authorization.json', 'V1_1_authorization_context.json',
                 'checkpoint.json', 'V1_1_execution.log', 'V1_report.json', 'Paired_results.csv', 'V1_1_final_check.log'):
        if (RUN/name).exists(): copy_evidence(RUN/name, evidence/name)
    for folder, target in [('results',evidence/'results'), ('sources',OUT/'sources')]:
        for source in (RUN/folder).rglob('*'):
            if source.is_file(): copy_evidence(source,target/source.relative_to(RUN/folder))
    for name in ('V1_report.json', 'Paired_results.csv'): copy_evidence(RUN/name, OUT/name)
    stats = summary['statistics']; df = stats.get('delta_fitness'); ci = stats.get('BCa_95_CI')
    pct = df / -summary['fitness']['equal'] * 100 if complete else None
    sorted_rows = sorted((r for r in rows if r['delta_fitness']), key=lambda r:float(r['delta_fitness']))
    best = sorted_rows[-1] if sorted_rows else None; worst = sorted_rows[0] if sorted_rows else None
    train_df = -1.982226488242 - (-1.983144294915)
    text = f'''# V1-1：冻结动态冠军与人工等权的 test28 配对验证

全部28对、56项预登记评价已处理；有效 {sum(c['valid'] for c in costs)}/56，失败 {len(failures)}。没有API请求、搜索、新U、额外回放、重试或重启。没有使用结果重新选择冠军。协议SHA256：`{summary['identity']}`。

## 主结果

|固定程序|test28 Fitness|Cmax合计（非优化目标）|首次求解墙钟秒|复检墙钟秒|首次h评分调用|复检h评分调用|
|---|---:|---:|---:|---:|---:|---:|
'''
    for role,label in [('dynamic','冻结动态 B/g0001/000000'),('equal','人工等权 alpha_050')]:
        c=summary['certified_costs'][role]
        text += f"|{label}|{fmt(summary['fitness'][role],12)}|{summary['Cmax_sum'][role]}|{fmt(c['single_wall_seconds'],3)}|{fmt(c['recheck_wall_seconds'],3)}|{c['h_calls']}|{c['recheck_h_calls']}|\n"
    text += f'''
主指标 ΔF={fmt(df,12)}；正值有利于动态程序。相对等权平均Cmax/LB的变化为 {fmt(pct,4)}%（正值为改善）。胜负平：{summary['pair_outcomes']}。失败或缺失不会用成功子集替代完整Fitness/统计；本次完整性状态为 {complete}。

预登记配对均值BCa：20,000次，seed1701，95%区间 {ci}；状态 `{stats.get('BCa_status',stats.get('status'))}`。双侧精确符号检验 p={stats.get('sign_test_p_two_sided')}，排除平局。未更换统计方法。BCa依赖实例作为独立重采样单位的假设；固定且同源的基准实例不是随机总体样本，区间不应扩展解释为任意FJSP总体保证。

## 逐实例结果

|实例|LB|动态Cmax|等权Cmax|ΔF单实例|结果|
|---|---:|---:|---:|---:|---|
'''
    for r in rows:
        text += f"|{r['file']}|{r['LB']}|{r['dynamic_Cmax'] or 'null'}|{r['equal_Cmax'] or 'null'}|{r['delta_fitness'] or 'null'}|{r['outcome']}|\n"
    if best and worst:
        text += f"\n按归一化差值，最大改善为 {best['file']}：动态/等权 {best['dynamic_Cmax']}/{best['equal_Cmax']}，ΔF={best['delta_fitness']}；最大退化为 {worst['file']}：{worst['dynamic_Cmax']}/{worst['equal_Cmax']}，ΔF={worst['delta_fitness']}。全部实例均保留，不能只用胜例说明效果。\n"
    text += f'''
## 与训练结果及证据边界

原train21：动态−1.982226488242、等权−1.983144294915，ΔF约{train_df:.12f}，相对改善约0.0463%，10胜7负4平；这些是B2-1已存在结果，本轮未重评。test28的方向与幅度见上述完整配对结果。test平均工序数253.57，train为180.95；同属Behnke基准族，规模分布变化及同源关系应一并考虑。

本次能检验两个冻结程序在这28个原留出实例上的表现是否保持训练优势；不能识别动态权重本身的因果贡献、证明LLM多代演化优于等预算其他搜索、超过所有静态权重，或推断跨基准族/多seed稳定性。test28历史审计和DDXQL声明仅覆盖已查记录及本人知情范围，并非所有外部历史未使用的绝对证明。此批test28现在已经消费，不再是后续迭代的独立未见测试证据；不得据此调权或替换冠军后复用独立性声明。

## 成本、失败与复现

实际成功认证求解遍数 {success_passes}；评价包装墙钟合计 {evaluation_wall:.3f} 秒；首项预留至末项完成 {span:.3f} 秒（含逐任务身份核验等开销）。每项首次与复检仍共享15秒。失败详情见Execution_audit.json；无失败时未知计费不适用，因为模型/API请求为0。CPU进程秒未采集，记null；没有独占资源保证，不把墙钟差当精确算法速度因果证据。h调用按评分函数调用认证，首次与复检分别报告；失败成本保留未知。

原B2-1的258项历史文件内容和mtime均未改变；冻结U/H/实例/评价源码未改。完整逐实例归一化值、哈希、复检、墙钟与h调用见[Paired_results.csv](Paired_results.csv)及[Evaluation_costs.csv](Evaluation_costs.csv)；原始56项结果、物理排程及检查点见evidence/，两份原U和H副本见sources/。V1-0完整冻结清单和数据来源审查仍在docs/usage-space/v1-0-prepared-20261021/。

实际入口（本批已完成，不需再求解）：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python -B tools/h01_v1.py run --run-dir runs/{RUN.name}
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python -B tools/h01_v1.py report --run-dir runs/{RUN.name}
PYTHONDONTWRITEBYTECODE=1 {sys.executable} -B reports/{OUT.name}/build_analysis.py
```

run的恢复只读已完成结果，不重新评价；本轮没有为了验证恢复而重启run。报告和表仅从已保存结果派生。最终研究解释及下一阶段建议见本报告末尾的结论。本批到此停止，不自动开展后续研究。
'''
    if complete:
        zero_in_ci = ci is not None and ci[0] <= 0 <= ci[1]
        text += f'''\n## 科研结论与下一步影响\n\n本批动态冠军在test28的平均归一化指标保持训练改善方向：相对改善{pct:.4f}%，高于训练的约0.0463%。但12胜14负2平，两个程序总Cmax均6930；平均改善由不同实例的改善幅度及LB权重共同决定，不能解释为多数实例获胜。BCa区间{'包含' if zero_in_ci else '未包含'}0，符号检验p={stats['sign_test_p_two_sided']:.6f}；当前证据不足以确认稳定泛化优势，也不证明两者等效或动态策略无效。\n\n原先“训练内小幅改善”的结论可更新为“本次冻结留出比较观察到正向平均差，但不确定性大，未获得明确统计优势”。h评分调用动态比等权高{(summary['certified_costs']['dynamic']['h_calls']/summary['certified_costs']['equal']['h_calls']-1)*100:.3f}%；这是轨迹导致的真实工作量差，不能仅从调用数归因于权重公式复杂度。\n\n最值得下一步单独检验的是：保留这两个冻结程序，在另一批事先登记、与现有开发及本次test28隔离的新实例上，正向均值是否可重复；先按精度目标规划样本量，再收集结果，不凭本次胜例筛选样本。任何方法改进只能转到开发数据，不能将已消费test28继续宣称为独立未见验证。后续需要另行授权，本轮不生成数据或执行实验。\n'''
    (OUT/'V1_1_REPORT_ZH.md').write_text(text)
    write('Evidence_hashes.json',{str(p.relative_to(ROOT)):sha(p) for p in sorted(RUN.rglob('*')) if p.is_file() and p.name!='.writer.lock'})
    print(json.dumps({'fitness':summary['fitness'],'statistics':stats,'outcomes':summary['pair_outcomes'],'audit':audit},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
