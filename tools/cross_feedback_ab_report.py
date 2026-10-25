"""Reproducible report of the monetary pre-dispatch stop; never generates/evaluates."""
import csv
import difflib
import json
from pathlib import Path
from fjsp_usage.research.events import atomic_json
from tools.cross_feedback_ab import DEFAULT, REPORT, check, read, sha


def table(path, rows, columns):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def report():
    protocol = check(); stop = read(DEFAULT/'Fee_stop.json')
    state = read(DEFAULT/'checkpoint.json'); money = read(DEFAULT/'API_cost_ledger.json')
    evaluations = read(DEFAULT/'Evaluation_ledger.json'); plan = read(DEFAULT/'Tasks.json')
    parents = {r['id']: r for r in read(DEFAULT/'Parents.json')}
    first_pair = plan['pairs'][0]['pair_id']
    a = (DEFAULT/'prompts'/(first_pair+'_r1_A.txt')).read_text().splitlines(keepends=True)
    b = (DEFAULT/'prompts'/(first_pair+'_r1_B.txt')).read_text().splitlines(keepends=True)
    # Zero-context presentation avoids whitespace-only context in the saved diff.
    (REPORT/'Rendered_AB.diff').write_text(''.join(difflib.unified_diff(
        a, b, fromfile='A current CROSS', tofile='B only score block', n=0)))
    if (state['logical_started'] or state['completed_responses'] or money['attempts']
            or evaluations['evaluations'] or evaluations['solve_passes_started']
            or state['phase'] != 'blocked_before_inference_by_fee_gate'):
        raise ValueError('this report only accepts the certified zero-dispatch monetary stop')
    candidates = []
    for task in plan['tasks']:
        candidates.append({**{k: task[k] for k in ['task_id', 'pair_id', 'repeat_id', 'condition', 'dispatch_position']},
             'parent_1': task['parents'][0], 'parent_2': task['parents'][1],
             'parent_1_key': parents[task['parents'][0]]['candidate']['key'],
             'parent_2_key': parents[task['parents'][1]]['candidate']['key'],
             'prompt_sha256': sha(DEFAULT/'prompts'/(task['task_id']+'.txt')),
             'status': 'not_started_fee_gate', 'fitness': None, 'attempts': 0})
    table(REPORT/'Candidate_results.csv', candidates, list(candidates[0]))
    paired, summaries = [], []
    for pair in plan['pairs']:
        best = max(parents[x]['fitness'] for x in pair['parents'])
        for repeat in range(1, 4):
            paired.append({'pair_id': pair['pair_id'], 'repeat_id': repeat,
                           'A_status': 'not_started_fee_gate', 'B_status': 'not_started_fee_gate',
                           'A_Fitness': None, 'B_Fitness': None, 'B_minus_A': None})
        for condition in ['A', 'B']:
            summaries.append({'pair_id': pair['pair_id'], 'condition': condition, 'planned': 3,
                'started': 0, 'complete_responses': 0, 'code_valid': 0, 'certified': 0,
                'validity_rate': None, 'mean': None, 'median': None, 'min': None, 'max': None,
                'better_parent_Fitness': best, 'strictly_better_children': 0, 'improvement_rate': None})
    table(REPORT/'Paired_task_results.csv', paired, list(paired[0]))
    table(REPORT/'Pair_summaries.csv', summaries, list(summaries[0]))
    summary = {'status': 'STOP_BEFORE_INFERENCE', 'permission_missing': False,
        'planned_pairs': len(plan['pairs']), 'planned_candidates': len(plan['tasks']),
        'logical_candidates_started': 0, 'complete_responses': 0, 'API_attempts': 0,
        'retries': 0, 'parse_failures': 0, 'generated_duplicates': 0, 'certified_children': 0,
        'evaluation_failures': 0, 'timeouts': 0, 'program_instance_evaluations': 0, 'solve_passes': 0,
        'new_inference_cost_CNY': 0, 'unknown_new_inference_cost_CNY': 0,
        'wire_input_tokens': 0, 'wire_output_tokens': 0, 'metadata_GETs': 5,
        'rates': None, 'quality_difference': None, 'protocol_sha256': sha(DEFAULT/'Protocol.json'),
        'evidence': {'fee_gate_sha256': sha(DEFAULT/'Fee_stop.json'),
                     'parent_audit_sha256': sha(REPORT/'Parent_audit.json'),
                     'offline_acceptance_sha256': sha(REPORT/'Offline_acceptance.json')},
        'qualification': 'five free metadata GETs, no model dispatch; old fees/holds untouched; zero generated data is not a negative A/B result'}
    atomic_json(REPORT/'Analysis_summary.json', summary)
    pair_lines = '\n'.join('|'+p['pair_id']+'|'+p['parents'][0]+'|'+p['parents'][1]+'|3＋3|未启动|' for p in plan['pairs'])
    pstats = protocol['parent_audit']
    body = f'''# CROSS成绩反馈A/B：实现及费用门禁停止报告

本轮**未产生A/B子代结果**。已实现独立提示词适配、完成12项离线验收、核对历史自由P0并冻结5个父代配对和30个逻辑任务；供应商费用证据不足以可靠保证最多20元，按本轮明确停止条件停在真实调用前。不是缺少用户运行授权，不需要重复批准同一范围。

## 已完成及被冻结内容

来源为Recovery-B的5个完整自由SELECT/MIX P0，非B2五个固定权重；每个21train、首解复检物理hash一致、原始before/after源码身份可查、当前核心科学源码和数据字节匹配、5个AST key各异。原历史T15资源标签保留，没有补求解父代；后续新子代拟用现有T30结果等待/2秒退出宽限，核心V1语义不变，但正式适配器尚未接入验收。

|配对|parent_1 / PARENT 0|parent_2 / PARENT 1|A＋B计划|状态|
|---|---|---|---:|---|
{pair_lines}

抽样seed为{plan['pair_seed']}，顺序seed为{plan['order_seed']}；从全部10个无序配对中均匀无放回抽5对，不看效果选配对。每对父代方向一次确定，A/B及三次重复一致；15个任务单元随机交错A/B，A先8次、B先7次。完整列表在`Tasks.json`，30份prompt在`prompts/`，示例差异见`Rendered_AB.diff`。

A与当前B1 CROSS字节一致；B仅插入两成绩、`delta=Fitness(parent_2)-Fitness(parent_1)`、越大越好及因果边界短句。未给B额外排序、交叉策略或长分析要求。与旧方案草案相反的delta方向以本轮用户指令为准，未改旧文档。

首次离线测试发现插入块额外增加空行，已在冻结计划前修正，失败日志保留为`Offline_tests_01_FAILED.log`；12项复验全部通过。Mock使用合成字典与源码格式检查，对网络、真实传输、实例加载和求解入口设置失败断言；正式和toy排程启动均为0。

## 为什么没有真实调用

5次只读GET已取得模型列表、当前价格、平台状态和token配额；均非推理请求。锁定配置为`gpt-6.1-sol`、`openai-chat-v1`、非流式、max output 8192，output token reservation 32768、input reservation 65536、temperature/reasoning_effort均为null；没有擅自换模型或增加C。

公开价格为272k内`p*2 + cr*0.1 + cc*2.5 + c*10`，更长时`p*4 + cr*0.2 + cc*5 + c*15`，group `codex-deafult`倍率0.5。公开quota_per_unit为500000，显示币种USD，usd_exchange_rate/price为7.3。**这些公开配置不能单独认证实际商户人民币扣费换算，也不能认证包括推理、缓存写入及网关附加输入的最大计费量。** 不将显示汇率或充值价当作已证实账单换算。

现有`model_migration.risk_reservation`明确返回`certified_provider_upper_bound=False`，只能提供附安全系数的工程包络。不能把它改名为硬上限、先发一次看账单或消费全部余额。本地观察未见其他实验writer锁或生成进程，但这不证明远端/其他设备没有账户占用；历史未知费用和预留没有清零。相应门禁与公开快照见`Fee_gate.json`和`Preflight_*.json`。

本次token配额快照可用97706135 raw points，**未认证为人民币余额，也未据此扩大20元授权**。当前缺口是费用认证和接受过测试的货币预留/结算适配器，不是H成绩缺失。这里没有把仅合成验收的launchd工具当正式无人值守执行器。

## 成本与结果解释

|项目|A|B|合计|
|---|---:|---:|---:|
|计划逻辑候选|15|15|30|
|实际开始/完整响应/认证子代|0/0/0|0/0/0|0/0/0|
|API尝试/重试|0/0|0/0|0/0|
|新增程序—实例/求解遍数|0/0|0/0|0/0|
|新增推理费用/未核实推理费用|0/0元|0/0元|0/0元|

输入/输出Token和新增求解耗时均为0。0成本依据是根本未派发推理，不是已认证整个账户人民币发票。有效率、配对均值/中位数/范围、超过父代比例和组别最佳均为**不可计算**，不是0分、0%或负结论；CSV留空。30个任务是未启动，不算生成失败，不用P0成绩或历史子代冒充新A组。

原P0完整双遍求解耗时约{min(pstats['parent_two_solve_train_seconds']):.2f}—{max(pstats['parent_two_solve_train_seconds']):.2f}秒/程序；按其中位数/最大值粗推30个新程序的求解本体为{pstats['projected_30_evaluations_seconds_at_parent_median']:.1f}/{pstats['projected_30_evaluations_seconds_at_parent_max']:.1f}秒，另加API、IPC与清理。它只是历史成本依据，不保证子代耗时。拟定首次真实run起最多6小时启动窗口；**尚未首次run，所以未创建Run_clock，未消费或重置任何期限**。没有启动防休眠或修改全局电源设置。

## 科研回答与后续限制

尚不能判断真实成绩是否改善质量、是否只集中个别配对、是否改变有效率或成本；没有生成数据。当前既不支持补重复，也不支持加入显式反思C。应先补齐实际人民币换算及供应商最大计费量/账户占用证据，再验收货币门禁和正式执行器；不增加本轮30/40/2/20元规模。

已完成：A/B实现、历史P0审计、离线验收、冻结任务/prompt、空账本及停止报告。尚未完成：真实生成、子代求解/质量分析、正式后台执行接入。原A4、历史实验及其他未提交文件保持不变，不推送。

协议SHA256：`{summary['protocol_sha256']}`。

可复核命令（均不发请求、不求解）：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B -m tools.cross_feedback_ab check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B -m tools.cross_feedback_ab_report
```

不重新prepare，不删除`Fee_stop.json`；将来若可提供可靠费用证据，须以保留本计划和本次停止记录的独立协议修订接入并验收。运行授权已存在，但本轮到此结束，不自动续跑。
'''
    (REPORT/'REPORT_ZH.md').write_text(body)
    print('Report saved; no real API or solves', flush=True)


if __name__ == '__main__': report()
