# Offline-only reporting derivative: same aggregation as frozen reporter;
# avoids re-reading redundant per-instance row copies for an archive.
# Latest continuation end is shown; original clock/end remain unchanged.
"""Post-hoc report from certified records; no API or scheduling entry points."""
from collections import Counter,defaultdict
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
from statistics import fmean,median
import tarfile
from zoneinfo import ZoneInfo


def csv_save(path,rows):
    if not rows:return
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()})


def quality(values):
    return {'n':len(values),'mean':fmean(values) if values else None,'median':median(values) if values else None,
            'minimum':min(values) if values else None,'maximum':max(values) if values else None}


def report():
    from tools import ind_evo_h01 as x
    out=x.REPORT;out.mkdir(exist_ok=True);p=x.read(x.RUN/'Protocol.json');s=x.read(x.RUN/'checkpoint.json')
    plans=x.read(x.RUN/'Tasks.json');p0=x.read(x.RUN/'P0.json');startbest=x.ranked(p0)[0]
    expected=x.sha(x.RUN/'Protocol.json')
    if expected!=(x.RUN/'Protocol.sha256').read_text().strip():raise ValueError('report protocol mismatch')
    results={};costs=[];instances=[]
    # Even on a Stop, retain only individually completed and hashed certifications.
    for key,r in s['evaluations'].items():
        if r['status']!='completed':continue
        path=x.RUN/r['result_path']
        if x.sha(path)!=r['result_sha256']:raise ValueError('report result hash mismatch')
        full=x.read(path)
        x.validate_result(full,p['instances'],r['level'])
        compact={k:full[k] for k in ('valid','fitness','total_instances','primary_evaluation_seconds') if k in full}
        compact['instances']=[{k:v for k,v in a.items() if k in ('file','makespan','lower_bound','score',
            'physical_schedule_sha256','single_solve_seconds','deterministic_recheck_seconds')} for a in full['instances']]
        results[key]=compact
        if r['origin']=='new':
            folder=path.parent;phase=[x.read(a) for a in folder.glob('*.progress.json')]
            life=x.read(folder/'lifecycle.json')
            costs.append({'key':key,'owner_task':r.get('owner_task'),'valid':full['valid'],'error_type':full.get('error_type'),
                'failed_instance':full.get('failed_instance'),'successful_prefix_rows':len(full['instances']),
                'first_starts':sum(bool(a.get('first_started')) for a in phase),
                'recheck_starts':sum(bool(a.get('recheck_started')) for a in phase),
                'known_first_seconds':sum(a['single_solve_seconds'] for a in full['instances']),
                'known_recheck_seconds':sum(a['deterministic_recheck_seconds'] for a in full['instances']),
                'primary_seconds':full['primary_evaluation_seconds'],'exitcode':life['exitcode'],
                'boundary':full['boundary']['reason']})
    all_journals={};attempts=[]
    for f in (x.RUN/'journals').glob('*.json'):
        j=x.read(f);all_journals[f.stem]=j
        for aid,a in j['api_attempts'].items():attempts.append({'unit':f.stem,**a})
    entries=[];curves=[];units=[];lineage=[];result_groups=defaultdict(list);unknown_physical=[]
    (out/'Generated_U').mkdir(exist_ok=True)
    for task in plans:
        saved=s['tasks'].get(task['task_id'])
        row={**task,'status':saved['status'] if saved else 'not_started','outcome':saved.get('outcome') if saved else None,
             'complete_response':bool(saved and saved.get('generation_status')=='completed'),
             'code_key':saved.get('code_key') if saved else None,'certified_valid':False,'fitness':None,
             'admitted':bool(saved and saved.get('admitted')),'within_search_duplicate':bool(saved and saved.get('duplicate')),
             'quality_cache_hit':bool(saved and saved.get('cache_hit')),'API_attempts':saved.get('API_attempts',0) if saved else 0,
             'parents':saved.get('parents',[]) if saved else [],'operator':saved.get('operator') if saved else None}
        if saved and saved.get('candidate'):
            (out/'Generated_U'/(task['task_id']+'.py')).write_text(saved['candidate']['code'])
        r=results.get(saved.get('evaluation_key')) if saved else None
        valid=bool(saved and saved.get('certified_valid') and not saved.get('clock_quarantined') and r and r['valid'])
        if valid:
            row.update(certified_valid=True,fitness=r['fitness'])
            hashes=[a.get('physical_schedule_sha256') for a in r['instances']]
            if all(hashes):result_groups[x.digest(hashes)].append(task['task_id'])
            else:unknown_physical.append(task['task_id'])
            for a in r['instances']:instances.append({'task_id':task['task_id'],'repeat':task['repeat'],'arm':task['arm'],**a})
        entries.append(row)
    bytask={r['task_id']:r for r in entries}
    for repeat in (1,2,3):
        for arm in ('IND','EVO'):
            uid=f'r{repeat}_{arm}';unit=s['units'][uid];incumbent=startbest;first=None;best_new=None
            curves.append({'repeat':repeat,'arm':arm,'logical_query':0,'best_fitness':incumbent['fitness'],
                           'incumbent_id':incumbent['id'],'delta_P0':0.})
            for k,tid in enumerate(unit['attempts'],1):
                e=bytask[tid];saved=s['tasks'][tid]
                if e['certified_valid']:
                    child={'id':tid,'fitness':e['fitness'],'candidate':saved['candidate']}
                    if best_new is None or child['fitness']>best_new['fitness']:best_new=child
                    if child['fitness']>incumbent['fitness']:
                        incumbent=child
                        if first is None:first=k
                curves.append({'repeat':repeat,'arm':arm,'logical_query':k,'best_fitness':incumbent['fitness'],
                               'incumbent_id':incumbent['id'],'delta_P0':incumbent['fitness']-startbest['fitness']})
            own=[e for e in entries if e['repeat']==repeat and e['arm']==arm]
            valid=[e['fitness'] for e in own if e['certified_valid']]
            nominal={**quality(valid)}
            j=all_journals.get(uid,{'requests':{},'api_attempts':{}})
            units.append({'repeat':repeat,'arm':arm,'logical_started':len(j['requests']),
                'committed':len(unit['attempts']),'complete20':len(unit['attempts'])==20,
                'champion_id':incumbent['id'],'champion_Fitness':incumbent['fitness'],
                'delta_P0':incumbent['fitness']-startbest['fitness'],'first_exceed_query':first,
                'champion_new_id':best_new['id'] if best_new else None,'champion_new_Fitness':best_new['fitness'] if best_new else None,
                'complete_responses':sum(e['complete_response'] for e in own),'certified_candidates':len(valid),
                'novel_valid_admitted':sum(e['admitted'] for e in own),'AST_duplicates':sum(e['within_search_duplicate'] for e in own),
                'quality_cache_hits':sum(e['quality_cache_hit'] for e in own),
                'API_attempts':len(j['api_attempts']),**{'new_quality_'+k:v for k,v in nominal.items()}})
            if arm=='EVO':
                future_parents=Counter(parent for t in s['tasks'].values() if t.get('repeat')==repeat and t.get('arm')=='EVO' for parent in t.get('parents',[]))
                snapshots=unit['snapshots']
                for e in own:
                    t=s['tasks'].get(e['task_id'],{});source=t.get('source_id')
                    lineage.append({'repeat':repeat,'task_id':e['task_id'],'source_id':source,'operator':e['operator'],
                        'generation':e['slot']//10,'parents':e['parents'],'parent_pool':t.get('parent_pool',[]),
                        'outcome':e['outcome'],'admitted':e['admitted'],'fitness':e['fitness'],
                        'in_P1':source in snapshots.get('P1',[]) if source else False,
                        'in_P2':source in snapshots.get('P2',[]) if source else False,
                        'times_used_as_later_parent':future_parents.get(source,0),
                        'improved_running_champion':any(c['repeat']==repeat and c['arm']=='EVO' and c['incumbent_id']==e['task_id'] for c in curves)})
    for row in p0:
        hashes=[a.get('physical_schedule_sha256') for a in results[row['candidate']['key']]['instances']]
        if all(hashes):result_groups[x.digest(hashes)].append(row['id'])
        else:unknown_physical.append(row['id'])
    csv_save(out/'Candidates.csv',entries);csv_save(out/'Search_curves.csv',curves)
    csv_save(out/'Search_summary.csv',units);csv_save(out/'Per_instance.csv',instances)
    csv_save(out/'EVO_lineage.csv',lineage);csv_save(out/'Evaluation_costs.csv',costs)
    x.write(out/'Population_snapshots.json',{uid:u['snapshots'] for uid,u in s['units'].items() if uid.endswith('EVO')})
    x.write(out/'Physical_schedule_groups.json',{'groups':dict(result_groups),'physical_unknown':unknown_physical,
        'notice':'same complete train21 physical schedules only; not all-state behavior equivalence'})
    # Best-effort invoice association, never a science gate or exact CNY estimate.
    snapshots=[x.read(f) for f in sorted((x.RUN/'metadata').glob('*.json'))]
    before=next((r for r in snapshots if r['label']=='start'),{})
    before_ids={r.get('request_id') for r in before.get('invoices',{}).get('records',[])}
    invoices={r.get('request_id'):r for snap in snapshots for r in snap.get('invoices',{}).get('records',[])
              if r.get('request_id') and r.get('request_id') not in before_ids}
    assigned=set();fees=[]
    for a in attempts:
        meta=(a.get('reply') or {}).get('metadata',a.get('metadata',{})) or {};usage=a.get('usage')
        rid=meta.get('gateway_request_id');matches=[i for i in invoices.values() if i['request_id']==rid];mode='exact_request_id'
        if not matches and usage:
            matches=[i for i in invoices.values() if i.get('model_name')==p['provider']['model']
                and i.get('prompt_tokens')==usage['input_tokens'] and i.get('completion_tokens')==usage['output_tokens']
                and a['started_at']-2<=i.get('created_at',0)<=a.get('finished_at',a['started_at'])+30]
            mode='unique_model_tokens_window_INFERENCE'
        match=matches[0] if len(matches)==1 and matches[0]['request_id'] not in assigned else None
        if match:assigned.add(match['request_id'])
        fees.append({'attempt_id':a['id'],'unit':a['unit'],'status':a['status'],'association':mode if match else 'unknown_or_ambiguous',
            'input_tokens':usage['input_tokens'] if usage else None,'output_tokens':usage['output_tokens'] if usage else None,
            'API_seconds':a.get('elapsed_seconds'),'invoice_points':match.get('quota') if match else None,
            'invoice_request_id':match['request_id'] if match else None,'actual_CNY':None})
    csv_save(out/'API_costs.csv',fees)
    x.write(out/'API_costs.json',{'records':fees,'CNY':'unknown; no conversion inferred','fees_do_not_gate':True,
        'associated_points':sum(r['invoice_points'] for r in fees if r['invoice_points'] is not None),
        'unknown_invoice_attempts':sum(r['invoice_points'] is None for r in fees),
        'qualified':'token/time association is supplementary inference, not strict request-ID certification; unrelated account usage not assigned'})
    clock=x.read(x.RUN/'Run_clock.json') if (x.RUN/'Run_clock.json').exists() else None
    end=x.read(x.RUN/'continuation-v1/recovery-v1/End_summary.json') if (x.RUN/'continuation-v1/recovery-v1/End_summary.json').exists() else x.read(x.RUN/'continuation-v1/End_summary.json') if (x.RUN/'continuation-v1/End_summary.json').exists() else x.read(x.RUN/'End_summary.json') if (x.RUN/'End_summary.json').exists() else None
    armstats={}
    for arm in ('IND','EVO'):
        own=[e for e in entries if e['arm']==arm];a=[r for r in fees if r['unit'].endswith(arm)]
        ownerids={r['task_id'] for r in own};c=[r for r in costs if r['owner_task'] in ownerids]
        armstats[arm]={'complete_repeats':sum(u['complete20'] for u in units if u['arm']==arm),
            'improved_repeats':sum(u['delta_P0']>0 for u in units if u['arm']==arm),
            'complete_responses':sum(e['complete_response'] for e in own),'certified_candidates':sum(e['certified_valid'] for e in own),
            'novel_valid_admitted':sum(e['admitted'] for e in own),'AST_duplicates':sum(e['within_search_duplicate'] for e in own),
            'outcomes':dict(Counter(e['outcome'] for e in own)),'API_attempts':len(a),
            'known_input_tokens':sum(r['input_tokens'] for r in a if r['input_tokens'] is not None),
            'known_output_tokens':sum(r['output_tokens'] for r in a if r['output_tokens'] is not None),
            'unknown_usage_attempts':sum(r['input_tokens'] is None for r in a),
            'associated_points':sum(r['invoice_points'] for r in a if r['invoice_points'] is not None),
            'unknown_invoice_attempts':sum(r['invoice_points'] is None for r in a),
            'new_physical_evaluations':len(c),'physical_solve_starts':sum(r['first_starts']+r['recheck_starts'] for r in c),
            'known_first_seconds':sum(r['known_first_seconds'] for r in c),
            'known_recheck_seconds':sum(r['known_recheck_seconds'] for r in c),
            'physical_primary_seconds':sum(r['primary_seconds'] for r in c)}
    summary={'phase':s['phase'],'planned':120,'committed':sum(len(u['attempts']) for u in s['units'].values()),
        'logical_requests_started':sum(len(j['requests']) for j in all_journals.values()),'API_attempts':len(attempts),
        'P0_best':startbest,'arms':armstats,'units':units,'new_unique_evaluations':len(costs),
        'reserved_instances':sum(r['reserved_instances'] for r in s['evaluations'].values()),
        'reserved_solves':sum(r['reserved_solves'] for r in s['evaluations'].values()),
        'actual_solve_starts':sum(r['first_starts']+r['recheck_starts'] for r in costs),
        'complete_physical_groups':len(result_groups),'physical_unknown':len(unknown_physical),
        'wall_seconds':end['end']['wall']-clock['start']['wall'] if end and clock else None,
        'protocol_sha256':expected,'holdout':0,'model':p['provider']['model']}
    x.write(out/'Summary.json',summary)
    fmt=lambda v:'null' if v is None else f'{v:.12f}'
    lines=['# 独立生成IND与演化EVO：固定新增候选预算的探索性对照','',
        f"终态{s['phase']}；计划120，实际启动{summary['logical_requests_started']}逻辑请求、提交{summary['committed']}候选槽位、API尝试{len(attempts)}/180。共同P0冠军{startbest['fitness']:.12f}，额外P0历史投入5策略，不能称从零20查询。",'',
        '|重复|组|完成槽位|P0＋新增冠军|ΔP0|首次超过位置|仅新增冠军|认证质量数|新颖有效子代|AST重复|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for u in units:lines.append(f"|{u['repeat']}|{u['arm']}|{u['committed']}/20|{fmt(u['champion_Fitness'])}|{fmt(u['delta_P0'])}|{u['first_exceed_query']}|{fmt(u['champion_new_Fitness'])}|{u['certified_candidates']}|{u['novel_valid_admitted']}|{u['AST_duplicates']}|")
    lines+=['','## 观察事实','',
        f"IND改善共同初始冠军{armstats['IND']['improved_repeats']}/3，EVO {armstats['EVO']['improved_repeats']}/3。完整重复分别{armstats['IND']['complete_repeats']}/3、{armstats['EVO']['complete_repeats']}/3；partial不包装为完成。",'',
        'Search_curves.csv逐重复列第0至实际已提交候选槽位的best-so-far，0为共同P0。Search_summary.csv同时给仅新增候选质量均值、中位数与范围；认证重复代码的已知质量可以列入该分布，但不会冒充新颖子代。',
        'Candidates.csv保留所有120计划槽位和每个失败／未启动项，API失败与代码准入、运行无效、重复分别列示。失败Fitness保持null，不删失败后冒称总成功率。',
        'EVO_lineage.csv与Population_snapshots.json展示P0/P1/P2、父代、子代入群体及下一代作为父代的次数。第二代没有后续代，不能用“未再当父代”评价其有效性。',
        f"完整排程指纹有{len(result_groups)}组，{len(unknown_physical)}个来源缺完整物理指纹（主要是历史原生端点）；不填造、不称全状态行为等价。",'',
        '## 机制与公平性','',
        'EVO使用原H01 CROSS/MUTATE模板、原rank加权父代采样和整代elitist更新，未加入成绩反馈。IND适配权重初始化接口且无P0代码／父代／历史；H语义、七状态和输出约束相同。比较包含父代信息利用的完整流程，不能单独识别CROSS、MUTATE或选择贡献。',
        '三次搜索是独立的新API上下文路径，未发送模型seed，不将同槽位视为严格随机配对；跨组／重复共享身份匹配的评价缓存，所以不是独立物理计时重复。',
        '共同P0的历史T15／原生复检证据等级明确披露，双方共用同一完整train21质量；新生成统一T30完整接收＋2秒正常退出、两遍一致性、源码身份与seed501。仅历史质量参照不追认为同期墙钟对照。',
        '历史B2与简单动态基线仅外部质量参考，未作为新EVO重复或提供给生成模型；未使用其他网格排名／测试信息。',
        '## 成本与限制','']
    for arm,a in armstats.items():lines.append(f"{arm}：{a['complete_responses']}完整响应，{a['certified_candidates']}认证质量记录，{a['novel_valid_admitted']}新颖有效子代；API {a['API_attempts']}次，已知输入/输出Token {a['known_input_tokens']}/{a['known_output_tokens']}，未知usage尝试{a['unknown_usage_attempts']}；可关联原始扣点{a['associated_points']}，未关联尝试{a['unknown_invoice_attempts']}。新物理评价{a['new_physical_evaluations']}、实际启动{a['physical_solve_starts']}遍，父进程评价区间{a['physical_primary_seconds']:.3f}秒。")
    lines+=['',f"总物理预留{summary['reserved_instances']}项/{summary['reserved_solves']}遍，实际启动{summary['actual_solve_starts']}遍。campaign墙钟{summary['wall_seconds']}秒（至结束摘要，不含后续归档／审阅）。CNY未知，不作虚假换算；Token时间窗账单关联是推断，精确request-ID关联另列。",
        '只对3次搜索重复作描述比较，不将120候选当120次独立演化。不强行作显著性或泛化结论；即使EVO领先，也不能拆分证明各算子有效。未改善的来源应先看实际生成质量、重复、无效和群体传递记录，不能从最终均值直接归因。',
        '本报告不扩充样本、模型或模板；所有历史冻结记录保持原样。未知请求、身份、进程终态或预算时保持Stop和原证据，不自动清理／重跑。',
        f"协议SHA：{expected}。模板、P0、全部原始请求／响应、费用与评价账本在runs/{x.NAME}/及本目录Raw_execution_evidence.tar.gz。复现入口见docs/IND_EVO_H01_PROTOCOL_V1.md；不要对完成目录重新prepare或launch。"]
    (out/'REPORT_ZH.md').write_text('\n\n'.join(r for r in lines if r)+'\n')
    return summary
