"""Descriptive, fixed-parent A/B report. No API dispatch or additional solves."""
import csv
from collections import Counter
from statistics import fmean,median
from fjsp_usage.research.events import atomic_json as write
from tools.cross_feedback_ab_execute import DIRECTORY,REPORT,BASE,read,sha,check


def csvfile(name,rows,columns):
    with (REPORT/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns,lineterminator='\n');w.writeheader();w.writerows(rows)


def summarize(values):
    return {'n':len(values),'mean':fmean(values) if values else None,'median':median(values) if values else None,
            'min':min(values) if values else None,'max':max(values) if values else None}


def report():
    p,b=check();REPORT.mkdir(exist_ok=True);state=read(DIRECTORY/'checkpoint.json');plans=read(BASE/'Tasks.json')
    parents={r['id']:r for r in read(BASE/'Parents.json')};api=read(DIRECTORY/'API_attempts.json') if (DIRECTORY/'API_attempts.json').exists() else {'requests':{},'api_attempts':{}}
    entries=[];instances=[];quality={};physical_groups={};solve_times=0.;solver_primary=0.;passes=0
    for key,record in state['evaluations'].items():
        folder=DIRECTORY/'evaluations'/key
        for file in folder.glob('*.progress.json'):
            progress=read(file);passes+=int(progress.get('first_started',False))+int(progress.get('recheck_started',False))
        if record['status']!='completed':continue
        result=read(DIRECTORY/record['result_path']);quality[key]=result
        solve_times+=sum(x['single_solve_seconds']+x['deterministic_recheck_seconds'] for x in result['instances'])
        solver_primary+=result['primary_evaluation_seconds']
        if result['valid']:
            physical_groups[key]=tuple(x['physical_schedule_sha256'] for x in result['instances'])
        for row in result['instances']:
            instances.append({'candidate_key':key,**{k:row[k] for k in ('file','makespan','lower_bound','score','single_solve_seconds','deterministic_recheck_seconds','physical_schedule_sha256')}})
    for task in plans['tasks']:
        row=state['tasks'].get(task['task_id'],{});key=row.get('evaluation_key');result=quality.get(key)
        eligible=result is not None and result['valid'] and not row.get('clock_quarantined',False)
        bestparent=max(parents[i]['fitness'] for i in task['parents'])
        record=api['requests'].get(task['task_id'],{})
        entries.append({'task_id':task['task_id'],'pair_id':task['pair_id'],'repeat_id':task['repeat_id'],
            'condition':task['condition'],'dispatch_position':task['dispatch_position'],
            'parent_1':task['parents'][0],'parent_2':task['parents'][1],'better_parent_fitness':bestparent,
            'status':row.get('status','not_started'),'complete_response':record.get('status')=='completed',
            'code_admissible':'candidate' in row,'attempts':len(record.get('attempt_ids',[])),
            'candidate_key':row.get('candidate',{}).get('key'),'certified_valid':eligible,
            'fitness':result['fitness'] if eligible else None,
            'delta_vs_better_parent':result['fitness']-bestparent if eligible else None,
            'strictly_better_parent':result['fitness']>bestparent if eligible else None,
            'evaluation_error':result.get('error_type') if result else None,
            'clock_quarantined':row.get('clock_quarantined',False)})
    pairrows=[];paired=[]
    for pair in plans['pairs']:
        arms={}
        for arm in ('A','B'):
            rows=[r for r in entries if r['pair_id']==pair['pair_id'] and r['condition']==arm]
            values=[r['fitness'] for r in rows if r['certified_valid']];stats=summarize(values)
            item={'pair_id':pair['pair_id'],'condition':arm,'planned':len(rows),'started':sum(r['status']!='not_started' for r in rows),
                'complete_responses':sum(r['complete_response'] for r in rows),'code_admissible':sum(r['code_admissible'] for r in rows),
                'strictly_better_parent':sum(r['strictly_better_parent'] is True for r in rows),**stats}
            pairrows.append(item);arms[arm]=item
        paired.append({'pair_id':pair['pair_id'],'A_n':arms['A']['n'],'B_n':arms['B']['n'],
            'B_minus_A_mean':arms['B']['mean']-arms['A']['mean'] if arms['A']['n'] and arms['B']['n'] else None,
            'B_minus_A_median':arms['B']['median']-arms['A']['median'] if arms['A']['n'] and arms['B']['n'] else None})
    group={}
    for arm in ('A','B'):
        rows=[r for r in entries if r['condition']==arm];valid=[r for r in rows if r['certified_valid']]
        group[arm]={'planned':len(rows),'started':sum(r['status']!='not_started' for r in rows),'complete_responses':sum(r['complete_response'] for r in rows),
            'code_admissible':sum(r['code_admissible'] for r in rows),'certified_valid':len(valid),
            'valid_per_planned':len(valid)/len(rows),'valid_per_response':len(valid)/sum(r['complete_response'] for r in rows) if any(r['complete_response'] for r in rows) else None,
            'strictly_better_parent':sum(r['strictly_better_parent'] is True for r in rows),
            'improvement_per_planned':sum(r['strictly_better_parent'] is True for r in rows)/len(rows),
            'improvement_per_valid':sum(r['strictly_better_parent'] is True for r in rows)/len(valid) if valid else None,
            'quality':summarize([r['fitness'] for r in valid]),'statuses':dict(Counter(r['status'] for r in rows)),
            'best':max(valid,key=lambda r:r['fitness']) if valid else None}
    invoices=[]
    if (DIRECTORY/'Invoices_end.json').exists():invoices=read(DIRECTORY/'Invoices_end.json').get('records',[])
    fees=[]
    for aid,a in api['api_attempts'].items():
        reply=a.get('reply',{});metadata=reply.get('metadata',a.get('metadata',{})) or {};rid=metadata.get('gateway_request_id')
        matches=[i for i in invoices if rid and i.get('request_id')==rid and i.get('model_name')==p['provider']['model']]
        receipt=matches[0] if len(matches)==1 else None
        if receipt and a.get('usage') and (receipt.get('prompt_tokens')!=a['usage']['input_tokens'] or receipt.get('completion_tokens')!=a['usage']['output_tokens']):receipt=None
        fees.append({'attempt_id':aid,'logical_id':a['logical_id'],'status':a['status'],'confirmed_send':a.get('send_confirmed'),
            'input_tokens':a.get('usage',{}).get('input_tokens') if a.get('usage') else None,
            'output_tokens':a.get('usage',{}).get('output_tokens') if a.get('usage') else None,
            'reasoning_tokens_subset':metadata.get('reasoning_tokens'),'elapsed_seconds':a.get('elapsed_seconds'),
            'gateway_request_id':rid,'matched_invoice_points':receipt['quota'] if receipt else None,'actual_CNY':None})
    feesummary={'attempts':len(fees),'retries':len(fees)-len(api['requests']),
        'known_wire_input_tokens':sum(r['input_tokens'] or 0 for r in fees),'known_wire_output_tokens':sum(r['output_tokens'] or 0 for r in fees),
        'unknown_usage_attempts':sum(r['input_tokens'] is None for r in fees),
        'matched_invoice_count':sum(r['matched_invoice_points'] is not None for r in fees),
        'matched_invoice_points':sum(r['matched_invoice_points'] or 0 for r in fees),
        'unmatched_fee_attempts':sum(r['matched_invoice_points'] is None for r in fees),
        'actual_CNY':None,'unmatched_cost_CNY':None,'notice':'monetary uncertainty explicitly authorized; no historical hold released'}
    window=read(DIRECTORY/'Run_clock.json') if (DIRECTORY/'Run_clock.json').exists() else {}
    end=read(DIRECTORY/'End_summary.json') if (DIRECTORY/'End_summary.json').exists() else {}
    summary={'phase':state['phase'],'completed_tasks':state['cursor'],'groups':group,'pair_comparisons':paired,'cost':feesummary,
        'new_unique_evaluations':len(state['evaluations']),'new_program_instances_reserved':21*len(state['evaluations']),
        'solve_passes_reserved':42*len(state['evaluations']),'solve_passes_started':passes,
        'complete_physical_schedule_groups':len(set(physical_groups.values())),
        'certified_solve_recheck_seconds':solve_times,'evaluation_primary_seconds':solver_primary,
        'wall_seconds':end.get('end',{}).get('wall',window.get('start_utc_epoch',0))-window.get('start_utc_epoch',0) if end else None,
        'base_protocol_sha256':sha(BASE/'Protocol.json'),'execution_binding_sha256':sha(DIRECTORY/'Execution_binding.json'),
        'limitations':'5 fixed historical parent contexts; 3 correlated generations per arm/context; no multi-generation or generalization inference'}
    write(REPORT/'Analysis_summary.json',summary);write(REPORT/'Fee_summary.json',feesummary)
    csvfile('Candidates.csv',entries,list(entries[0]));csvfile('Pair_summary.csv',pairrows,list(pairrows[0]));csvfile('Paired_differences.csv',paired,list(paired[0]))
    if fees:csvfile('API_attempt_costs.csv',fees,list(fees[0]))
    if instances:csvfile('Per_instance.csv',instances,list(instances[0]))
    def fmt(x):return 'null' if x is None else f'{x:.12f}'
    pairtext='\n'.join('|'+r['pair_id']+'|'+r['condition']+'|'+str(r['n'])+'|'+fmt(r['mean'])+'|'+fmt(r['median'])+'|'+fmt(r['min'])+'|'+fmt(r['max'])+'|'+str(r['strictly_better_parent'])+'|' for r in pairrows)
    body=f'''# CROSS真实成绩反馈A/B执行报告

执行状态：**{state['phase']}**；完成{state['cursor']}/30个冻结任务。复用原P0、5个配对、30份prompt及交错顺序，未重新抽样。旧20元门禁及其原停止记录完整保留；本次用户明确撤销费用前置条件的授权见执行目录`Authorization.json`。未增加C、初始化、变异或多代演化。

|组别|计划|完整响应|代码准入|认证有效|有效/计划|严格超过较好父代|超过/计划|
|---|---:|---:|---:|---:|---:|---:|---:|
|A|15|{group['A']['complete_responses']}|{group['A']['code_admissible']}|{group['A']['certified_valid']}|{group['A']['valid_per_planned']:.2%}|{group['A']['strictly_better_parent']}|{group['A']['improvement_per_planned']:.2%}|
|B|15|{group['B']['complete_responses']}|{group['B']['code_admissible']}|{group['B']['certified_valid']}|{group['B']['valid_per_planned']:.2%}|{group['B']['strictly_better_parent']}|{group['B']['improvement_per_planned']:.2%}|

有效子代质量单列，失败没有赋予惩罚Fitness，也没有补生成。计划分母在partial中保留未启动项，实际响应分母指标见Analysis_summary。

|配对|组|有效n|均值|中位数|最低|最高|严格超过父代数|
|---|---|---:|---:|---:|---:|---:|---:|
{pairtext}

A最佳：{fmt(group['A']['best']['fitness'] if group['A']['best'] else None)}；B最佳：{fmt(group['B']['best']['fitness'] if group['B']['best'] else None)}。冠军仅为补充，不代替配对层面的质量和有效率。

## 成本、期限与认证

API尝试{feesummary['attempts']}/40，额外重试{feesummary['retries']}，每逻辑任务最多2次；完整响应保存后只解析一次，失败不补员。输入/输出已知Token为{feesummary['known_wire_input_tokens']}/{feesummary['known_wire_output_tokens']}，未知用量尝试{feesummary['unknown_usage_attempts']}。匹配供应商request ID、模型和已知Token的账单{feesummary['matched_invoice_count']}笔，共{feesummary['matched_invoice_points']}平台点；其余{feesummary['unmatched_fee_attempts']}笔费用未知。人民币换算未知，未把账户差额直接归因本批；取消费用门禁不等于把未知费用记零。

新增独立程序评价{len(state['evaluations'])}个，预留程序—实例{summary['new_program_instances_reserved']}项，预留双遍{summary['solve_passes_reserved']}遍，实际启动{passes}遍；复用结果仍占逻辑槽。已认证行的首解复检合计{solve_times:.3f}秒，评价器总耗时{solver_primary:.3f}秒，执行墙钟{summary['wall_seconds']}秒。预算从本次first run持久化，最多6小时启动窗口，不覆盖旧停止记录。

使用原V1 usage评分和host规则，train21/seed501、LB不取整、完整mean(-Cmax/LB)、T30完整结果等待及2秒正常退出宽限。每次评价保存前后加载身份、逐实例首解/复检排程hash、进程终态、资源记录；未知身份/复检/终态/账本停止，明确普通超时或已认证U输出错误为null。没有前缀均值。

后台采用文件日志、新会话和SIGHUP保护，启动父进程退出后的行为已用合成控制进程验收；临时caffeinate仅防空闲休眠，结束清理，不能保证合盖计算。墙钟与单调时钟差异超过2秒会隔离候选并停止，不重评。未访问留出集，不续A4，不推送。

## 证据解释边界

本实验是5个固定父代上下文上的探索性生成比较，3次生成不是独立多代演化重复。比较应看各配对B−A差异、有效率和全槽改进比例，不能仅看某个最佳子代。整体训练成绩差异不证明某个状态分支的因果作用，也不构成泛化证据。后续是否补重复或研究显式反思，须据本报告实际完整性与配对差异判断，本轮不追加。

## 文件及复核

执行目录：`{DIRECTORY}`；原任务：`{BASE/'Tasks.json'}`；本报告目录：`{REPORT}`。`API_attempts.json`和`wire_responses/`保留每次发送及首次完整文本，`responses/`为解析前原始回复，`evaluations/`为认证结果/失败，`Events.jsonl`和`Console.log`给出时间线。CSV及JSON为派生数据。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B -m tools.cross_feedback_ab_execute check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B -m tools.cross_feedback_ab_execution_report
```

复核/报告不发API或求解。未知reservation与Stop不能自动清除；同一已完成执行不可再次launch或run新增请求。
'''
    (REPORT/'REPORT_ZH.md').write_text(body)
    print('REPORT',state['phase'],state['cursor'],flush=True)


if __name__=='__main__':report()
