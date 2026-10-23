"""Post-evaluation audit only: no instance parsing, H calls, solves or network.

Bind the frozen experiment and derive a complete 189-row table (including null
timeout rows). Correct the ideal-arithmetic MAX interpretation using recorded
floating-point counterexamples; leave the preregistered source/protocol intact.
"""
import csv
import gzip
import itertools
import json
from pathlib import Path

from tools.fusion_v2_experiment import ROOT, DEFAULT, check, read, sha, specs, csv_write
from fjsp_usage.research.events import atomic_json


def main():
    out = Path(__file__).resolve().parent
    run = ROOT/'runs'/out.name
    protocol = check(run)
    summary = read(out/'Summary.json')
    checkpoint = read(run/'checkpoint.json')
    assert checkpoint['phase'] == 'completed' and len(checkpoint['strategies']) == 9
    references = read(run/'References.json')
    reference_rows = {k: {r['file']: r for r in v['training_result']['instances']}
                      for k, v in references.items()}
    all_rows, costs, boundary_rows = [], [], []
    for spec in specs():
        folder = run/'evidence'/spec['id']
        result = read(folder/'result.json')
        available = {r['file']: r for r in result['instances']}
        before, life, boundary = read(folder/'before.json'), read(folder/'lifecycle.json'), read(folder/'boundary.json')
        assert life['alive'] is False and life['pid'] == before['pid']
        assert boundary['decision'] != 'stop'
        if result['valid']:
            assert read(folder/'after.json')['identity'] == before['identity'] and life['exitcode'] == 0
        else:
            assert result['fitness'] is None and result['error_type'] == 'Timeout'
            assert boundary['reason'] == 'confirmed_timeout_termination' and life['exitcode'] == -15
        boundary_rows.append({'strategy':spec['id'], 'valid':result['valid'],
            'completed_instances':len(available), 'failed_instance':result.get('failed_instance'),
            'error_type':result.get('error_type'), 'exitcode':life['exitcode'], 'alive':life['alive'],
            'boundary_decision':boundary['decision'], 'end_identity': 'matched' if (folder/'after.json').exists() else 'unavailable_confirmed_terminated'})
        for expected in protocol['instances']:
            name = expected['file']; row = available.get(name)
            status = 'complete_pair' if row else 'confirmed_timeout'
            all_rows.append({'strategy':spec['id'], 'file':name, 'candidate_valid':result['valid'],
                'instance_status':status, 'Cmax':row['makespan'] if row else None, 'LB':expected['LB'],
                'score':row['score'] if row else None,
                'H0_Cmax':reference_rows['H0'][name]['makespan'],
                'H01_equal_Cmax':reference_rows['H01_equal'][name]['makespan'],
                'delta_Cmax_vs_H0':row['makespan']-reference_rows['H0'][name]['makespan'] if row else None,
                'delta_Cmax_vs_H01_equal':row['makespan']-reference_rows['H01_equal'][name]['makespan'] if row else None,
                'delta_F_vs_H0':row['score']-reference_rows['H0'][name]['score'] if row else None,
                'delta_F_vs_H01_equal':row['score']-reference_rows['H01_equal'][name]['score'] if row else None,
                'single_seconds':row['single_solve_seconds'] if row else None,
                'recheck_seconds':row['deterministic_recheck_seconds'] if row else None,
                'parent_observed_seconds':None if row else result['parent_observed_instance_seconds'],
                'error_type':None if row else result.get('error_type'),
                'physical_schedule_sha256':row['physical_schedule_sha256'] if row else None})
            if row:
                costs.append({'strategy':spec['id'], 'file':name,
                    'first_solve_seconds':row['single_solve_seconds'], 'recheck_seconds':row['deterministic_recheck_seconds'],
                    'first_H_seconds':row['first_costs']['h_scoring_seconds'],
                    'first_fusion_seconds':row['first_costs']['fusion_seconds'],
                    'recheck_H_seconds':row['recheck_costs']['h_scoring_seconds'],
                    'recheck_fusion_seconds':row['recheck_costs']['fusion_seconds'],
                    'trace_write_seconds':row['first_trace_write_seconds'],
                    'CPU_seconds':row['instance_CPU_seconds'], 'peak_RSS_bytes_macOS':row['peak_RSS_native_units']})
    assert len(all_rows) == 189 and len({(r['strategy'],r['file']) for r in all_rows}) == 189
    assert sum(r['Cmax'] is None for r in all_rows) == 6
    csv_write(out/'All_instances_189.csv', all_rows)
    csv_write(out/'Cost_breakdown.csv', costs)
    csv_write(out/'Exception_and_identity_audit.csv', boundary_rows)
    # Verify the two finite-precision exceptions from the actual saved matrices.
    cases = []
    with gzip.open(out/'Common_state_actions.csv.gz', 'rt') as handle:
        mismatches = [r for r in csv.DictReader(handle) if r['MAX_is_member_top_action'] == 'False']
    for case in mismatches:
        path = run/'evidence'/case['source_strategy']/(Path(case['file']).stem+'.trace.jsonl.gz')
        with gzip.open(path, 'rt') as handle:
            trace = next(r for r in map(json.loads, handle) if r['step'] == int(case['step']))
        chosen = int(case['MAX_action_index']); details = []
        collapse = False
        for member in trace['support']:
            raw = trace['columns'][str(member)]; norm = trace['normalized'][str(member)]
            top = max(range(len(raw)), key=lambda a:raw[a])
            collapse |= raw[chosen] < raw[top] and norm[chosen] == norm[top] == 1.
            details.append({'member':member, 'raw_top_index':top, 'chosen_raw':raw[chosen],
                            'raw_top_value':raw[top], 'chosen_normalized':norm[chosen],
                            'raw_top_normalized':norm[top]})
        assert collapse
        cases.append({'source':case['source_strategy'], 'file':case['file'], 'step':int(case['step']),
                      'MAX_index':chosen, 'details':details})
    assert len(cases) == 2
    atomic_json(out/'Floating_point_cases.json', cases)
    audit = {'protocol_sha256':sha(run/'Protocol.json'), 'analysis_source_sha256':sha(__file__),
        'analysis_scope':'post-evaluation recombination/audit only; frozen operators/pairs/metric unchanged',
        'new_solves':0, 'new_H_calls':0, 'new_API_requests':0,
        '189_rows':len(all_rows), 'complete_pairs':len(costs), 'null_timeout_rows':6,
        'valid_strategies':3, 'confirmed_timeout_strategies':6,
        'identity_mismatches':0, 'unknown_process_terminations':0,
        'same_state_occurrences':sum(r['states'] for r in summary['same_state_diagnostics'] if r['source']!='UNION_DEDUPLICATED'),
        'same_state_deduplicated_union':sum(r['states'] for r in summary['same_state_diagnostics'] if r['source']=='UNION_DEDUPLICATED'),
        'source_protection_final_check':'PASS', 'floating_point_raw_endpoint_exceptions':len(cases),
        'MAX_corrected_interpretation':'MAX selects the first top action of normalized columns; finite min-max can merge distinct raw scores, so it need not equal a raw SELECT endpoint',
        'quality_boundary':'only H01 has a complete three-operator comparison; cross-pair ranking consistency is unknown'}
    atomic_json(out/'Final_audit.json', audit)
    summary.setdefault('MAX_expression_boundary_original_preregistered', summary['MAX_expression_boundary'])
    summary['MAX_expression_boundary'] = audit['MAX_corrected_interpretation']
    summary['post_evaluation_interpretation_correction'] = 'Floating_point_cases.json and Final_audit.json; no execution/source/protocol change'
    atomic_json(out/'Summary.json', summary)
    lines = ['# V2 融合机制可行性：最终报告', '',
        '**结论：动作行为确实改变，尚无排程收益证据。** 已执行全部9个预定策略：H0/H1三策略有效，另6策略在Behnke57确认超时，完整Fitness=null。',
        '没有改变成员对、算子、15秒期限、Fitness或同分规则；没有补跑、扩预算或访问留出集。', '',
        '## 实现与兼容性', '',
        '执行器：`code/fjsp_usage/fusion_v2/execution.py`；独立CLI：`experiments/tier2/fusion_v2/run.py`；生命周期/分析：`tools/fusion_v2_experiment.py`。',
        '协议定义：`docs/FUSION_V2_PROTOCOL.md`。每列沿用V1 min–max，常量列归零；SELECT和单成员WS保留原始分数。',
        '归一化SUM与0.5/0.5 WS只差正比例，故不单列。MAX/MIN接受两个等值正支持项，不静默忽略不等权重。',
        '旧V1源码未修改；54项测试/Mock/回归通过。H01等权正式21实例的Cmax、LB、score及已有物理签名与V1逐项一致。',
        '已核对实例加载器会按machine排序alternatives，因此本轮实际同分顺序为job、machine；通用执行器本身保留输入枚举首项。',
        '可信callable U可按七状态返回不同算子、成员及WS权重；本轮没有扩大LLM AST、生成程序或开展演化。', '',
        '## 九个策略的结果', '', '| 策略 | 完整train21 Fitness | 相对H0 | 相对H01等权 | 状态 |', '|---|---:|---:|---:|---|']
    for r in summary['rankings']:
        text = lambda x: f'{x:.12f}' if x is not None else 'null'
        lines.append(f"| {r['strategy']} | {text(r['fitness'])} | {text(r['delta_F_vs_H0'])} | {text(r['delta_F_vs_H01_equal'])} | {'21/21有效' if r['valid'] else '20/21完成；Behnke57超时'} |")
    lines += ['', 'H0历史基线为−2.111804960626，H01等权为−1.983144294915；引用身份与完整结果见Reference_provenance.json。',
        '无效策略不参加完整Fitness排名，禁止用成功前缀算均值。完整189行（含6行null）见All_instances_189.csv；Instances.csv保留183个成功求解对的原始派生表。', '',
        'H01：MAX相对WS为3胜/16负/2平，ΔF=−0.090551188522；MIN为1胜/18负/2平，ΔF=−0.129584218305。两者均在21个实例上与WS产生不同物理排程。',
        '三个有效策略形成3个不同的完整train21物理排程组。另两成员对无完整三算子结果，不能判断跨成员对优劣是否一致。', '',
        '## 相同状态动作差异', '',
        '在全部首解的成功求解对中记录全物理状态和全部合法动作评分，离线用同一矩阵重组；已执行算子的动作和分数逐步复现一致。',
        '共31200个状态出现记录、30245个按实例/完整物理状态/历史成员分组后的去重状态。来源条件化明细见Common_state_summary.csv，逐状态见Common_state_actions.csv.gz。', '',
        '| 成员对 | 去重状态 | MAX≠WS | MIN≠WS | MAX顶端同分状态 |', '|---|---:|---:|---:|---:|']
    for r in summary['same_state_diagnostics']:
        if r['source']=='UNION_DEDUPLICATED':
            lines.append(f"| {r['pair']} | {r['states']} | {r['MAX_diff_WS']} | {r['MIN_diff_WS']} | {r['MAX_tied_states']} |")
    lines += ['', 'H01的MAX顶端同分为11140/11346（约98.18%），故其结果强烈依赖冻结同分规则。H05/H59的状态统计只覆盖20个成功实例，不包括超时实例；它们是局部动作证据，不是完整质量证据。', '',
        '## 表达能力与浮点证据边界', '',
        'MIN在人工可核验矩阵上能选出任何非负线性加权都无法首选的折衷动作（测试中给出证明）。本轮真实状态只统计与固定等权WS的差异，未证明每个差异都超出全部连续权重。',
        '**对原自动汇总中MAX端点表述的修正：** 精确实数min–max下，MAX首选是某列首个最大动作；在冻结浮点实现中，归一化可能把不同原始分数舍入成同一1.0，因而不一定等于原始SELECT端点。',
        '实际发现2例，均来自H0/H5 MAX轨迹：Behnke34第57步（H0原始14.799999999999994与14.799999999999999均归一化为1）；Behnke51第97步（−27.35与−27.349999999999998均变为1）。完整证据见Floating_point_cases.json。',
        '这是既有归一化和精确同分交互的数值现象，不能包装成MAX的结构性表达优势。本轮保留原语义，未修复或重评。', '',
        '## 成本、异常与保护', '',
        f"预留189项；首解189遍、复检189遍，共378遍启动；183项通过两遍一致性验证，6项在复检启动后超时，未取得认证完整结果。",
        f"主评价串行wall time为{summary['costs']['primary_wall_seconds']:.3f}秒（约7.53分钟）；成功实例CPU为{summary['costs']['successful_instance_CPU_seconds']:.3f}秒。",
        '认证成功部分的两遍H调用为46,424,688；失败部分细分CPU/H调用未知，不补零。Cost_breakdown.csv和raw结果保存逐实例时间、H/融合时间及峰值RSS。',
        '首解含全状态/矩阵记录开销，复检不记录；15秒父进程等待包含求解和留证准备，不能当成纯算法耗时，更不能从超时判定某融合算子必然更慢。',
        '6个超时均有匹配起始加载身份、文件前后哈希、父等待触发及exitcode=−15/非存活终态；缺少结束加载身份被明确记为“确认终止下不可用”，不是忽略缺失。',
        '完整策略均有前后加载身份一致与exit0；无身份冲突或未知终态。Network_guard.json为零阻断事件；正式代码不构造供应商客户端。API=0，额外诊断求解/H调用=0。',
        '原始压缩矩阵共522,575,401字节，保存在独立runs；Artifact_index.json给出逐文件SHA256。Git报告保留原始结果/身份回执及压缩逐状态派生表，未将约498MiB矩阵重复入库。',
        '首次...-v1因训练原路径未加入保护名单，在零预留/零求解时停止；旧记录保留在preflight_stop。修正后用...-v2新目录运行，没有重置已消耗求解。',
        'B2历史四个API/记账模块与当时清单不同，已逐项披露且本轮不导入；本地排程、H编译、LB、动作选择源码与历史科学身份匹配。', '',
        '## 后续建议', '',
        '保持WEIGHTED_SUM为默认，暂不据此启动大规模LLM演化。MIN有可解释的折衷机制，可保留为独立研究支线，但当前H01结果不支持质量优势；MAX应先解释其顶端同分和固定枚举偏好。',
        '涉及H5的完整质量证据不足，应先在新的独立协议中判断评价成本/留证开销边界；本轮不延长期限、不补评。之后若开放动态算子，需要与相同成员、相同生成/评价预算的WS-only空间比较。',
        '本轮只支持：接口可运行、算子会改变动作、在H01上未见质量收益；不支持动态算子有效、LLM能发现更好策略或跨实例稳定泛化。train21已暴露，未使用validation11/test28。', '',
        '## 复现与证据', '', '命令见Commands.md。先运行核心report，再执行：', '', '```bash',
        'PYTHONPATH=code:. .venv/bin/python -B reports/fusion-v2-train21-seed501-20261023-v2/finalize_report.py', '```', '',
        'Final_audit.json绑定本分析脚本SHA256与原协议；该脚本不解析FJSP实例、不调用H、不新增求解。冻结实现和协议保留原样，以上解释修正有原始矩阵证据。']
    (out/'FINAL_REPORT_ZH.md').write_text('\n'.join(lines)+'\n')
    auto = out/'REPORT_ZH.md'
    marker = '> 后续完整审计与浮点端点表述修正见 **FINAL_REPORT_ZH.md**；以最终报告为准。\n\n'
    original = auto.read_text()
    if not original.startswith(marker):
        auto.write_text(marker+original)
    commands = out/'Commands.md'
    extra = '\n最终189行表、异常审计和浮点解释修正：\n\n```bash\nPYTHONPATH=code:. .venv/bin/python -B reports/fusion-v2-train21-seed501-20261023-v2/finalize_report.py\n```\n'
    if extra not in commands.read_text():
        commands.write_text(commands.read_text()+extra)
    check(run)
    print(audit)


if __name__ == '__main__':
    main()
