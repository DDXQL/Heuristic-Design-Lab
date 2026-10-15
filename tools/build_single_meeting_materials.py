#!/usr/bin/env python3
"""Build meeting exhibits from saved results only. No provider or solver imports.

Requires matplotlib for PNG/SVG export. Never writes into runs/ or loads holdouts.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import fmean
import subprocess
import tarfile
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
RUN_NAME = 'single-ID-gpt61-paired-training-20261014-v1'
CASE = 'B2/g0000/000000'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text())


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '|' + '|'.join('---' for _ in headers) + '|'] +
                     ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows])


def link(path, out):
    import os
    return Path(os.path.relpath(path, out)).as_posix()


def checked_results(run):
    result = read(run / 'Reconciled_training_results.json')
    training = read(run / 'Training_report.json')
    protocol = read(run / 'protocol.json')
    initial = training['initialization'][0]['accepted_population']
    evaluations = {k: v['result'] for k, v in
                   training['initialization'][0]['all_initial_evaluations'].items()}
    for entry in training['entries']:
        evaluations.update({v['id']: v['result'] for v in entry['all_child_evaluations']})
    valid = [q for q in result['requests'] if (q.get('attempt') or {}).get('category') == 'valid']
    assert len(valid) == 21 and len(initial) == 5
    assert sum(q['send_confirmed'] for q in result['requests']) == 33
    assert sum(q['actual_platform_units'] or 0 for q in result['requests']) == 125096
    assert not result['unknown_cost_requests']
    for q in valid:
        e = evaluations[q['id']]
        assert e['valid'] and e['total_instances'] == len(e['instances']) == 21
        assert [x['file'] for x in e['instances']] == protocol['dataset']['split']['train']
        assert all(x['feasible'] and math.isclose(x['score'], -x['makespan']/x['lower_bound'],
                   rel_tol=1e-12) for x in e['instances'])
        assert math.isclose(e['fitness'], fmean(x['score'] for x in e['instances']), rel_tol=1e-12)
        assert all(x['single_solve_seconds'] >= 0 and x['deterministic_recheck_seconds'] >= 0
                   for x in e['instances'])
    for g in result['groups']:
        checkpoint = read(run / f"r201/{g['arm']}/checkpoint.json")
        final = read(run / f"r201/{g['arm']}/Final_population.json")
        assert checkpoint['phase'] == 'completed' and checkpoint['inflight'] is None
        assert len(checkpoint['attempts']) == 10 and len(g['population']) == 5
        assert [p['id'] for p in final['population']] == [p['id'] for p in g['population']]
        assert math.isclose(g['mean_train_fitness'], fmean(p['fitness'] for p in g['population']))
    return result, training, protocol, initial, evaluations


def make_charts(out, rows, groups):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    preferred = ('Arial Unicode MS', 'PingFang HK', 'Noto Sans CJK SC', 'STHeiti')
    available = {f.name for f in font_manager.fontManager.ttflist}
    font = next((f for f in preferred if f in available), None)
    if font is None:
        raise RuntimeError('A Chinese-capable font is required for these exhibits')
    plt.rcParams.update({'font.family': font, 'axes.unicode_minus': False,
                         'font.size': 13, 'svg.fonttype': 'path', 'svg.hashsalt': RUN_NAME,
                         'axes.spines.top': False,
                         'axes.spines.right': False})
    colors = ['#97A4B5', '#2864AE', '#28977B']
    x = list(range(5))
    fig, ax = plt.subplots(figsize=(12, 6.75))
    for j, (key, label) in enumerate([('slots', '已占槽位'), ('sent', '实际模型请求'), ('valid', '有效候选')]):
        bars = ax.bar([i + (j-1)*.24 for i in x], [r[key] for r in rows], .23,
                      label=label, color=colors[j])
        ax.bar_label(bars, padding=3)
    ax.set(xticks=x, xticklabels=['共享初始化', 'B0', 'B1\n实际请求=0', 'B2', 'P'],
           ylim=(0, 12), ylabel='数量（条 / 次 / 槽位）',
           title='真实生成与有效候选：共享初始化 + 四组各一代')
    ax.legend(loc='upper left', ncol=3, frameon=False)
    ax.set_yticks(range(0, 11, 2)); ax.grid(axis='y', alpha=.15); ax.set_axisbelow(True)
    fig.text(.07, .035, '四组实际请求预算不一致，不能据此判断方法优劣。诊断1次另计；失败/重复不补发。',
             color='#A23B30', fontsize=13)
    fig.subplots_adjust(left=.08, right=.98, top=.89, bottom=.18)
    for ext in ['png', 'svg']:
        fig.savefig(out / f'03_requests.{ext}', dpi=220, facecolor='white')
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(12, 6.75))
    y = list(range(4))
    for i, g in enumerate(groups):
        ax.hlines(i, g['initial_mean_train_fitness'], g['mean_train_fitness'],
                  color='#B9C5D4', linewidth=4, zorder=1)
    ax.scatter([g['initial_mean_train_fitness'] for g in groups], y, s=90,
               color='#97A4B5', marker='o', label='共同初始种群均值', zorder=3)
    ax.scatter([g['mean_train_fitness'] for g in groups], y, s=90,
               color='#2864AE', marker='s', label='最终种群均值', zorder=4)
    ax.scatter([g['best_train_fitness'] for g in groups], y, s=150,
               color='#28977B', marker='*', label='初始 = 最终最佳', zorder=3)
    for i, g in enumerate(groups):
        ax.annotate(f"{g['mean_train_fitness']:.6f}", (g['mean_train_fitness'], i),
                    xytext=(0, -22), textcoords='offset points', ha='center', fontsize=11)
    ax.set(yticks=y, yticklabels=['B0（实际5次）', 'B1（实际0次）', 'B2（实际10次）', 'P（实际10次）'],
           xlim=(-2.27, -2.04), ylim=(-.6, 3.7),
           xlabel='训练适应度 mean(−Cmax/LB)，越大越好 →',
           title='仅比较起点与一代终点：全部最佳仍来自共享初始种群')
    ax.invert_yaxis(); ax.grid(axis='x', alpha=.15); ax.legend(loc='upper center',
        bbox_to_anchor=(.5, -.15), ncol=3, frameon=False)
    fig.text(.08, .025, '仅训练、单种子、一代；横轴局部截取以显示数值。预算不一致，不能推断组间优劣。',
             color='#A23B30', fontsize=13)
    fig.subplots_adjust(left=.18, right=.97, top=.89, bottom=.27)
    for ext in ['png', 'svg']:
        fig.savefig(out / f'03_population.{ext}', dpi=220, facecolor='white')
    plt.close(fig)
    for path in out.glob('03_*.svg'):
        text = re.sub(r'<dc:date>.*?</dc:date>', '<dc:date>2026-10-15</dc:date>', path.read_text())
        path.write_text('\n'.join(line.rstrip() for line in text.splitlines()) + '\n')


def build(run, out):
    out.mkdir(parents=True, exist_ok=True)
    result, training, protocol, initial, evaluations = checked_results(run)
    sources = {p: sha(p) for p in run.rglob('*') if p.is_file()}
    groups = result['groups']
    candidate_map = {v['id']: v['candidate'] for v in initial}
    for g in groups:
        candidate_map.update({v['id']: v['candidate'] for v in g['population']})
    rows = []
    for name in ['INIT', 'B0', 'B1', 'B2', 'P']:
        reqs = [q for q in result['requests'] if q['group'] == name]
        errors = Counter()
        for q in reqs:
            category = (q.get('attempt') or {}).get('category')
            if category == 'valid': continue
            if q['model_request_state'] == 'not_sent_proved_before_invoice_gate': cause = '发送前查账失败（未发送）'
            elif category == 'parse_failure': cause = '响应格式解析失败'
            elif q.get('error_type') == 'TransportError': cause = '流协议校验失败'
            else: cause = '已发送后结算门禁失败（费用后来已核实）'
            errors[cause] += 1
        group = next((g for g in groups if g['arm'] == name), None)
        rows.append({'group': name, 'slots': len(reqs), 'sent': sum(q['send_confirmed'] for q in reqs),
                     'valid': sum((q.get('attempt') or {}).get('category') == 'valid' for q in reqs),
                     'failures': dict(errors), 'surviving_children': group['new_children_surviving'] if group else None,
                     'actual_points': sum(q['actual_platform_units'] or 0 for q in reqs)})
    initial_mean = fmean(x['fitness'] for x in initial); initial_best = max(x['fitness'] for x in initial)
    write_json(out/'summary_data.json', {'run': RUN_NAME, 'groups': rows,
        'initial_mean': initial_mean, 'initial_best': initial_best,
        'populations': [{k:v for k,v in g.items() if k != 'population'} for g in groups],
        'scope': result['scope'], 'comparison_integrity': result['comparison_integrity']})
    (out/'01_进度说明.md').write_text(f'''# 单成员U研究：本批进度（一页版）

本页用于组会说明2026-10-14启动、10-15完成的真实训练批次；仅固定既有H的条件研究，不代表独立测试结论。

**目的与方法。** 在固定10条h上演化利用程序U；U在每个调度步骤接收七项状态、返回一个成员编号，执行器只调用该h为合法动作评分并完成排程。研究问题是H信息与不同提示算子怎样影响U搜索。本批无MIX，也未重新运行Tier1。H沿用开发批次来源及DDXQL技术审查，并获得固定H研究用途批准；它不是本批重新独立生成的正式H。

**数据与共同条件。** Behnke–Geiger本地格式化数据中的21个训练实例（名单、顺序和哈希见索引）；seed201、N=5、精确响应模型Leaf gpt-6.1-sol、v5-state-bounds提示。四组共享同一初始5条U、H、评价器和实例期限15秒。每个有效U均有完整21实例排程、可行性、适应度、单次求解及确定性复检记录；独立诊断另计时。

**实际执行。** 新初始化发出7次请求，获得5条有效U。随后四组各处理一代10槽位并执行生存选择：B0/B1/B2/P实际演化请求5/0/10/10次，新增有效子代4/0/6/6条，最终存活1/0/2/1条。总计32次正式生成、1次独立接入诊断；21条有效U，未发现代码/窄规则重复。15个槽位因发送前查账失败未发送，不能计成模型生成失败或调用。

**观察与局限。** 初始平均适应度{initial_mean:.6f}，最终四组依次为{' / '.join(f"{g['mean_train_fitness']:.6f}" for g in groups)}；越大越好。四组最佳均为{initial_best:.6f}，仍是初始U，没有新子代超过初始冠军。均值变化只描述本批生存选择结果；尤其B1实际调用为0，四组实际预算不一致，不能判断算子/H信息的方法优劣。只有一个种子、一代；未访问正式validation/test，未选择或冻结研究U*，没有独立泛化或统计显著性结论。

**证据与成本。** 本批全部新增调用已核实125,096原始平台点；不是人民币/美元。两个旧未知请求及24,000,000点预留继续保留。接入、归档和查账修复属于实验基础设施，不是算法创新。下一步若开展可比较研究，需新登记且授权的平衡批次；本次材料整理不追加请求或补跑。
''')
    summary_rows = []
    for row in rows:
        g = next((g for g in groups if g['arm'] == row['group']), None)
        summary_rows.append([row['group'], row['slots'], row['sent'], row['valid'],
            '；'.join(f'{k}×{v}' for k,v in row['failures'].items()),
            row['surviving_children'] if g else '不适用（形成P₀的5条）',
            f'{initial_mean:.9f}' if g else '不适用（尚未形成P₀）',
            f'{initial_best:.9f}' if g else '不适用',
            f"{g['mean_train_fitness']:.9f}" if g else f'{initial_mean:.9f}',
            f"{g['best_train_fitness']:.9f}" if g else f'{initial_best:.9f}'])
    text = '# 实验汇总与适应度说明\n\n本表以最终核对报告及原始检查点交叉核验。有效候选数为新增U，四组不重复计入共享P₀。\n\n'
    text += table(['阶段','槽位','实际请求','有效U','失败原因','新子代存活','初始均值','初始最佳','最终均值','最终最佳'], summary_rows)
    text += '''

初始化上限20次，凑齐5条有效U后在第7次停止。正式阶段共47槽位、32次发送、21条有效U；独立诊断另占1槽位/1次请求，没有进入种群。47−32=15个未发送槽位，不能算生成请求。四组均完成既定10槽位，不能等同于均完成10次真实生成。0重复、1解析失败、0候选接口/代码约束失败、0训练运行失败；25个api_failure槽位细分为15未发送、4流协议失败、6已发送后结算失败。后6笔已结算，实验失败记录未改写。

## 如何理解适应度

每个工件先将各工序的最短可选加工时间相加，得到最短工作量W_j。实例下界LB = max(max_j W_j, Σ_j W_j /机器数)，总负荷项不向上取整。每个实例score=−Cmax/LB，候选fitness为全部21个score的算术平均。Cmax是排完全部工序的最终完工时间，越小越好；fitness越大（越接近−1）越好。例如−2.1优于−2.3；fitness=−2.1表示平均Cmax/LB=2.1，不是“距最优解差110%”。LB未必等于最优解，不能转换为最优差距。任何实例失败则整个候选无有效fitness，不取成功子集平均。

种群均值是5条U各自完整训练fitness的平均，最佳是其中最大值；没有按实例挑不同U再拼成成绩。15秒限制主评价中的单实例求解/复检对，独立诊断另有期限。计时不包含LLM生成成本。

## 四组原本比较什么

| 组 | 提供H代码/已审查行为 | 演化提示算子 |
|---|---|---|
| B0 | 否，只知编号和接口 | 原EoH五算子E1/E2/M1/M2/M3，各2槽位 |
| B1 | 是 | 同B0五算子 |
| B2 | 是 | 通用交叉/变异，各5槽位 |
| P | 是 | 特化交叉/变异，各5槽位 |

父代每代固定，交叉用5父代、变异用1父代；子代完整评价后在代末与父代合并，保留fitness前5，同分按稳定ID。交叉/变异分别从原父代池取样，不将本代新子代串入后续父代。B0/B1实际失败破坏了原本可比条件。

## 全部固定成员的训练参照

以下仅固定选择某个h的训练记录，不用验证或测试挑基线，不是独立测试结果。

'''
    text += table(['固定成员','训练fitness'], [[f'h{i}', f"{m['fitness']:.9f}"] for i,m in enumerate(result['fixed_H_train_results'])])
    text += '\n\n## 实际成本（原始平台点，不做汇率换算）\n\n'
    text += table(['阶段','实际点数'], [[row['group'], row['actual_points']] for row in rows] + [['诊断',20],['合计',125096]])
    text += '\n\n未知历史费用/预留不属于本表实际支出。逐请求成本及失败候选成本均见索引；不只展示成功候选费用。\n'
    (out/'02_实验汇总.md').write_text(text)
    make_charts(out, rows, groups)

    case_dir = out/'case_B2_000000'; case_dir.mkdir(exist_ok=True)
    req = next(q for q in result['requests'] if q['id'] == CASE)
    attempt = req['attempt']; parents = attempt['parents']
    journal = read(run/'r201/B2/budgeted_evolution_requests.json')['requests'][CASE]
    assert journal['global_key'] == req['global_key']
    for name, field in [('actual_prompt.txt','prompt'), ('actual_response.txt','text')]:
        (case_dir/name).write_text(journal[field])
    child_code = (run/'candidate_exports/B2_g0000_000000.py').read_text()
    assert ast.dump(ast.parse(child_code)) == ast.dump(ast.parse(candidate_map[CASE]['code']))
    assert child_code.strip() in journal['text']
    (case_dir/'child.py').write_text(child_code)
    init_by_id = {x['id']:x for x in initial}
    for i, pid in enumerate(parents, 1):
        code = init_by_id[pid]['candidate']['code']; assert code.strip() in journal['prompt']
        (case_dir/f'parent_{i}_{pid.split("/")[-1]}.py').write_text(code)
    e = evaluations[CASE]
    comparison = []
    for pid in parents:
        pe = evaluations[pid]
        better = sum(a['makespan'] < b['makespan'] for a,b in zip(e['instances'],pe['instances']))
        equal = sum(a['makespan'] == b['makespan'] for a,b in zip(e['instances'],pe['instances']))
        comparison.append([pid, f"{pe['fitness']:.9f}", better, equal, 21-better-equal])
    compact_instances = [{k:v for k,v in row.items() if k not in
        ('state_trajectory','predicate_coverage')} for row in e['instances']]
    write_json(case_dir/'training21.json', {'id':CASE, 'code_key':candidate_map[CASE]['key'],
        'fitness':e['fitness'], 'instances':compact_instances,
        'note':'Derived copy of historical measurements; no new solver execution. Full traces remain in checkpoint.'})
    ideas = ['工作量/机器就绪的非线性综合分数，区分首步',
             '按进度、候选比例及工作量/就绪比较分段', '固定返回h2',
             '六项连续状态平均后按阈值映射编号', '固定返回h4']
    case_text = '# 真实交叉案例：B2/g0000/000000\n\n选取理由：真实通用CROSS，5个父代、原始请求/响应、有效源码、21实例成绩和生存选择证据齐全，并非选取“最大改进”样本。\n\n'
    case_text += table(['提示中顺序','父代ID','代码所体现的思路','源码'],
        [[i,pid,idea,f'[父代{i}](case_B2_000000/parent_{i}_{pid.split("/")[-1]}.py)']
         for i,(pid,idea) in enumerate(zip(parents,ideas),1)])
    case_text += '''

实际完整提示与响应保存在[actual_prompt.txt](case_B2_000000/actual_prompt.txt)、[actual_response.txt](case_B2_000000/actual_response.txt)。这是当次发送内容的拷贝，包含H上下文、5个父代及通用交叉要求；不是现在重新生成的提示模板。提示不含这些父代的训练分数，表中的分数只用于本次事后核对。

## 从父代到子代：能从代码确认什么

子代[child.py](case_B2_000000/child.py)保留了父代2的progress<0.5、候选比例0.5分界，以及后期机器就绪/工作量的比较。它增加首步的工作量离散程度判断，以h2/h4作多个分支的输出，替换了一些成员映射；这与两个常量父代的输出编号相符，但不能仅据编号相同证明模型“继承了思想”。父代1的综合score公式与父代4的六项平均公式未原样进入子代。

LLM在响应中称结合多个父代，这只是生成解释。我们能确认的是代码变化和以下排程结果，无法证明模型内部推理或局部状态上哪个h最优。

```python
'''+child_code.rstrip()+ '\n```\n\n## 完整训练结果与父代比较\n\n'
    case_text += f"子代fitness={e['fitness']:.9f}；21/21实例可行，确定性复检通过。下表为子代相对各父代的逐实例Cmax比较（越小越好）。\n\n"
    case_text += table(['父代','父代fitness','子代更小','相同','子代更大'],comparison)
    case_text += '\n\n子代优于3个父代的整体fitness，但弱于初始最好的两个父代；相对初始冠军为4好/1同/16差。它没有创造新的最优策略。\n\n'
    case_text += table(['训练实例','Cmax','LB','score','可行','首次求解s','复检s','诊断s'],
        [[row['file'],row['makespan'],f"{row['lower_bound']:.6f}",f"{row['score']:.9f}",'是',
          f"{row['single_solve_seconds']:.6f}",f"{row['deterministic_recheck_seconds']:.6f}",
          f"{row.get('diagnostic_replay_seconds',0):.6f}"] for row in e['instances']])
    case_text += '\n\n机器可读数据见[training21.json](case_B2_000000/training21.json)。首求解/复检/独立诊断累计分别为' + ' / '.join(f"{sum(row[k] for row in e['instances']):.6f}s" for k in ('single_solve_seconds','deterministic_recheck_seconds','diagnostic_replay_seconds')) + '；不能将诊断时间并入首求解或混作模型耗时。\n\n'
    survivors = next(g['population'] for g in groups if g['arm']=='B2')
    assert CASE in {p['id'] for p in survivors}
    case_text += '## 是否进入下一代\n\n**是，B2终代排名第4/5。** 代末父代与全部有效子代一起按训练fitness排序保留前5；不要求子代超过最佳父代才能存活。实际终代如下（并非又运行一代）：\n\n'
    case_text += table(['终代名次','ID','fitness'], [[i,p['id'],f"{p['fitness']:.9f}"] for i,p in enumerate(survivors,1)])
    case_text += f"\n\n本次请求已核实{req['actual_platform_units']}平台点；详见证据索引的原账单链接。完整响应/评估来源哈希记录在source_manifest.json；本例源码是历史模型候选的拷贝，不运行也不送入新种群。\n"
    (out/'04_真实交叉案例.md').write_text(case_text)

    relrun = link(run,out)
    index = f'''# 实验材料索引与证据优先级

职责：从组会材料追溯到当前已完成的真实训练批次。所有链接均为本地路径；GitHub不保存runs/，远端不能直接打开这些本地证据。独立本地备份见Backup_receipt.json（完成备份后生成）。

## 当前应以哪些记录为准

- [最终核对结果]({relrun}/Reconciled_training_results.json)：48槽位/33次实际发送、全部分类、费用和四组终代；财务与次数的首要依据。
- [最终账本交接]({relrun}/Final_budget_handoff.json)：累计128/300槽位、112次确认发送；旧两笔未知预留2400万点不变。
- [实际恢复完成凭证]({relrun}/Search_complete_resumed.json)、[最终完整性核对]({relrun}/Final_integrity_checks.json)。
- [完整训练记录]({relrun}/Training_report.json)：全部候选、逐实例排程成绩、独立轨迹与三类计时。
- [冻结H]({relrun}/H_frozen.json)、[研究用途批准]({relrun}/Human_authorization.json)、[H来源复评]({relrun}/Conditional_H_reassessment.json)。
- [固定协议]({relrun}/protocol.json)、[授权配置]({relrun}/config.migration.authorized.json)、[代码/提示/配置/训练数据快照]({relrun}/code-prompts-config-data-snapshot.tar.gz)。
- [实际训练名单、顺序与哈希](training_identity.json)；只有train21文件被本工具核对，没有读取validation/test实例。
- [全部导出的提示模板清单]({relrun}/prompts/Manifest.json)、[共享初始化模板]({relrun}/prompts/Shared.I1.txt)。模板不是当次具体父代请求；逐次提示以请求journal为准。
- [单笔成本表]({relrun}/Final_training_report.md)及下面每槽位的实际成本凭证链接。公开费率不是实际账单。

## 过时状态与已知缺失

Search_complete.json保留第一次中止状态；Initialization_status.json保留当时只接收4条U的状态。不能将它们覆盖上面的恢复完成凭证。Migration_final.json、Single_results.json及Exclusive_call_handoff.json中的旧费用/未知分类未合入最终逐笔结算；这些旧派生报告只供追溯，当前费用和阶段状态以上述最终核对报告为准。

INIT/init/000005响应正文在早期结算429前未成功归档：模型/usage/账单证据保留，正文缺失，不补造或重发。另4次已发送请求的wire usage未知，但有实际账单token与费用；两者分别记录，不相互冒充。15个未发送槽位没有模型响应，属于“不适用”，不是正文丢失。轨迹中actions=[]且actions_truncated=true是诊断按max_actions=0仅保留选择动作的设计，不表示没有合法动作；不具有全量动作分数日志。没有正式validation/test结果、研究U*或独立多种子证据。

结算失败后完整保存的B2第5次响应仍为原失败槽位；后来结算不意味着回填成有效子代。本次材料不改变候选资格或历史种群。

## 逐阶段原始入口

'''
    index += table(['阶段','真实提示/响应journal','检查点/完整评价','最终种群'],
        [[g, f'[journal]({relrun}/r201/{g}/budgeted_{"initial" if g=="INIT" else "evolution"}_requests.json)',
          f'[checkpoint]({relrun}/r201/{g}/checkpoint.json)',
          f'[P₀]({relrun}/r201/Shared_initial.json)' if g=='INIT' else f'[population]({relrun}/r201/{g}/Final_population.json)'] for g in ['INIT','B0','B1','B2','P']])
    index += '\n\n## 每槽位响应、源码、评价及成本凭证\n\n“已发送+费用已核实”不等于“有效候选”。评价链接指向包含完整实例结果的检查点，按ID检索；没有运行评价则标明未评价。\n\n'
    indexed = []
    for q in result['requests']:
        stem = hashlib.sha256(q['global_key'].encode()).hexdigest()
        wire = run/'wire_responses'/f'{stem}.json'
        export = run/'candidate_exports'/(q['id'].replace('/','_')+'.py')
        response = run/'candidate_exports'/(q['id'].replace('/','_')+'.response.txt')
        cat = (q.get('attempt') or {}).get('category',q['status'])
        resp = f'[wire]({link(wire,out)})' if wire.exists() else (f'[response]({link(response,out)})' if response.exists() else ('正文缺失（已知）' if q['global_key'] in result['raw_body_archival_gap'] else '无正文归档/未发送或诊断，见journal'))
        code = f'[源码]({link(export,out)})' if export.exists() else '无'
        ev = f"[21实例]({relrun}/r201/{q['group']}/checkpoint.json)" if cat=='valid' else '未完成候选评价'
        fee = '不适用（未发送）' if not q['send_confirmed'] else str(q['actual_platform_units'])
        evidence = f"[成本凭证]({relrun}/{q['final_cost_evidence']})"
        indexed.append([q['global_key'],cat,resp,code,ev,fee,evidence])
    index += table(['请求ID','最终原分类','实际响应','候选源码（存在不代表有效）','评价','点数','结算'],indexed)
    (out/'05_证据索引.md').write_text(index+'\n')
    speech = '''# 约1分钟口头汇报稿

这阶段我研究的是：固定10条已有启发式，让大模型生成利用程序U，每一步根据七项状态选择一个h来调度。此次使用21个训练实例、一个种子，初始化7次得到5条有效U，四组共享这一起点，各处理一代10个槽位。实际共发送32次正式生成请求，累计获得21条完整训练有效U。B0、B2和P分别有1、2、1条新子代存活，但没有子代超过初始最佳策略。需要强调，实际调用数不平衡，特别是B1为零，所以现在不能判断哪种方法更好。当前进展是已取得可追溯的真实候选、完整排程评价和生存选择证据；尚没有独立验证、测试或泛化结论。下一步需要在固定协议、相同实际预算下开展新的可比较实验。本次不会追加调用。
'''
    (out/'06_口头汇报稿.md').write_text(speech)
    train = protocol['dataset']['split']['train']
    train_id = {'manifest_sha256':protocol['dataset']['manifest_sha256'],
                'training_order':train,'sha256':{n:protocol['dataset']['hashes'][n] for n in train},
                'H_artifact_sha256':read(run/'H_frozen.json')['artifact_sha256'],
                'source_H_approved_artifact_sha256':read(run/'H_frozen.json')['scope_approval']['source_H_sha256']}
    for n in train:
        assert sha(ROOT/'data/fjsp'/n) == train_id['sha256'][n]
    write_json(out/'training_identity.json',train_id)
    readme = f'''# 单成员U真实训练：组会材料（2026-10-15）

本目录只整理已有真实训练结果，不发请求、不执行求解、不修改runs/。本批各组槽位处理完毕，但因实际调用不均衡而不构成有效四组方法比较。

1. [一页中文进度说明](01_进度说明.md)
2. [实验汇总、适应度与固定成员参照](02_实验汇总.md)
3. PPT用图：[请求与有效候选PNG](03_requests.png) / [SVG](03_requests.svg)；[初始与最终表现PNG](03_population.png) / [SVG](03_population.svg)
4. [真实交叉案例](04_真实交叉案例.md)（包含5父代、当次提示/响应、源码、21实例成绩和生存结果）
5. [实验材料索引及已知缺失](05_证据索引.md)
6. [约1分钟口头稿](06_口头汇报稿.md)
7. [机器可读汇总](summary_data.json)、[数据与H身份](training_identity.json)、[来源哈希](source_manifest.json)、[材料核对](verification.json)、[独立备份凭证](Backup_receipt.json)

两张图均为16:9白底、2640×1485 PNG及文字转路径SVG；只展示初始和一代终点，不绘制多代收敛曲线。B1实际请求=0、预算不一致与不可归因警示已写入图内。SVG可缩放，PNG可直接插入PPT。

## 离线重新生成

在本worktree运行（系统Python带matplotlib与中文字体，本项目.venv目前不含matplotlib）：

```sh
python3 tools/build_single_meeting_materials.py --run-dir runs/{RUN_NAME} --out reports/20261015-single-ID-training
```

生成工具仅使用标准库和matplotlib（本机3.10.0），不导入provider或求解器；核对全部21条有效U的历史逐实例数值，不重新评价。reports/保存精简说明、图和一个案例；runs/、原始账单、数据、环境与密钥不进入Git。来源原始run完整备份和1035份绑定历史材料在仓库外，恢复位置见Backup_receipt.json。GitHub上的本地runs链接不能代替这份备份。
'''
    (out/'README.md').write_text(readme)
    write_json(out/'source_manifest.json', {'run_relative_to_repository':str(run.relative_to(ROOT)),
        'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_files':{str(p.relative_to(ROOT)):h for p,h in sources.items()},
        'source_priority':['Reconciled_training_results.json','Final_budget_handoff.json','Search_complete_resumed.json'],
        'generator_sha256':sha(Path(__file__))})
    # Resolve every Markdown link, including the intentionally local raw evidence.
    missing = []
    for p in out.rglob('*.md'):
        for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if target.startswith(('https://','http://','#')): continue
            if target in ('Backup_receipt.json', 'verification.json'): continue  # generated below/backup step
            if not (p.parent/unquote(target.split('#')[0])).exists(): missing.append([str(p),target])
    assert not missing, missing
    assert all(sha(p)==h for p,h in sources.items()), 'Historical run modified during build'
    write_json(out/'verification.json', {'valid_U_checked':len(valid := [q for q in result['requests'] if (q.get('attempt') or {}).get('category')=='valid']),
        'per_instance_rows_checked':len(valid)*21,'all_fitness_recomputed_from_saved_metrics':True,
        'full_train_feasible':True,'four_final_populations_checked':True,'case_prompt_response_code_match':True,
        'case_survived':True,'local_links_resolve':True,'historical_run_unchanged':True,
        'new_model_requests':0,'new_solver_evaluations':0,'holdout_instance_files_read':0,
        'image_visual_review':'See visual_review.json when available; manual inspection is separate from numerical checks'})
    return sources


def backup(run, out, destination):
    """Copy complete native run + all pinned history/train files; verify every byte."""
    destination.mkdir(parents=True,exist_ok=False)
    config=read(run/'config.migration.authorized.json'); protocol=read(run/'protocol.json')
    paths={p for p in run.rglob('*') if p.is_file()}
    for name, expected in config['conditional_research']['source_files_sha256'].items():
        p=ROOT/'runs'/name
        assert sha(p)==expected
        paths.add(p)
    paths.update(ROOT/'data/fjsp'/n for n in protocol['dataset']['split']['train'])
    paths.add(ROOT/'data/fjsp_manifest.json')
    paths.update(p for p in out.rglob('*') if p.is_file() and p != out/'Backup_receipt.json')
    paths.add(Path(__file__))
    snapshot = run/'code-prompts-config-data-snapshot.tar.gz'
    with tarfile.open(snapshot,'r:gz') as archive:
        assert all(not any(part in ('.env','.venv','venv') or part.startswith('.env.')
                           for part in Path(m.name).parts) for m in archive.getmembers())
    manifest={str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}
    assert all(not any(part in ('.env','.venv','venv') or part.startswith('.env.')
                       for part in Path(n).parts) for n in manifest)
    archive_path=destination/'experiment-and-bound-sources.tar.gz'
    with tarfile.open(archive_path,'w:gz',dereference=True) as archive:
        for name in manifest: archive.add(ROOT/name,arcname=name,recursive=False)
    with tarfile.open(archive_path,'r:gz') as archive:
        members=archive.getmembers(); assert len(members)==len(manifest)
        for m in members:
            assert m.isfile()
            stream=archive.extractfile(m); h=hashlib.sha256()
            for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
            assert h.hexdigest()==manifest[m.name],m.name
    write_json(destination/'FILES_SHA256.json',manifest)
    receipt={'location':str(destination),'archive':str(archive_path),'archive_sha256':sha(archive_path),
        'files':len(manifest),'all_archived_bytes_read_and_verified':True,
        'includes':['complete native run, raw invoices local only','all 1035 pinned historical sources',
                    'train21 files and manifest','frozen code/prompts/config/data snapshot',
                    'meeting materials and generator'],
        'excluded':['API credential files','environment directories','formal holdout instance files'],
        'restore':'tar -xzf experiment-and-bound-sources.tar.gz -C <empty-restore-directory>',
        'note':'Receipt is outside the archive to avoid a self-referential hash; FILES_SHA256.json enables independent verification.'}
    write_json(destination/'BACKUP_RECEIPT.json',receipt)
    write_json(out/'Backup_receipt.json',receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,default=ROOT/'runs'/RUN_NAME)
    parser.add_argument('--out',type=Path,default=ROOT/'reports/20261015-single-ID-training')
    parser.add_argument('--backup-dir',type=Path)
    args=parser.parse_args(); run=args.run_dir.resolve();out=args.out.resolve()
    assert run.is_relative_to(ROOT/'runs') and not out.is_relative_to(ROOT/'runs')
    sources=build(run,out)
    if args.backup_dir: print(json.dumps(backup(run,out,args.backup_dir.resolve()),ensure_ascii=False))
    assert all(sha(p)==h for p,h in sources.items())
    print(f'Generated and checked: {out}')


if __name__=='__main__':main()
