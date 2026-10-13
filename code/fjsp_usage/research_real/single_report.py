"""Exhaustive train-only single-member results and invoice-unit calibration."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from statistics import fmean
from fjsp_usage.research.events import atomic_json
from .training_report import write_training_report
from .workflow import ARMS


def write_results(flow):
    training=write_training_report(flow)
    requests=[];candidates=[];costs=[]
    exports=flow.directory/'candidate_exports';exports.mkdir(exist_ok=True)
    ledger=flow.ledger.data['records']
    for group in ('INIT',*ARMS):
        folder=flow.directory/'r201'/group
        journal=folder/('budgeted_initial_requests.json' if group=='INIT' else 'budgeted_evolution_requests.json')
        if not journal.exists():continue
        state=json.loads((folder/'checkpoint.json').read_text())
        attempts={row['id']:row for row in state['attempts']}
        for identifier,record in json.loads(journal.read_text())['requests'].items():
            key=record['global_key'];charged=ledger[key]
            billing_file=flow.directory/'billing'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
            bill=json.loads(billing_file.read_text()) if billing_file.exists() else {}
            units=bill.get('actual_platform_units')
            attempt=attempts.get(identifier)
            evaluation=state['evaluations'].get(identifier,{}).get('result')
            usage=record.get('usage');metadata=record.get('response_metadata',{})
            row={'global_key':key,'id':identifier,'group':group,'send_confirmed':charged.get('send_confirmed',False),
                 'status':record['status'],'attempt':attempt,'wire_usage':usage,
                 'unknown_wire_token_reservation':charged['reservation'] if usage is None else None,
                 'actual_platform_units':units,'billing_status':bill.get('status','no_invoice_evidence'),
                 'billing_file':str(billing_file.relative_to(flow.directory)) if billing_file.exists() else None,
                 'supplier_invoice':bill.get('invoice'),'observed_account_delta':bill.get('original_quota_record',{}).get('observed_account_delta'),
                 'provider_roundtrip_seconds':metadata.get('provider_roundtrip_seconds'),
                 'request_journal_elapsed_seconds':record.get('elapsed_seconds'),
                 'response_metadata':metadata,'error_type':record.get('error_type'),'error':record.get('error')}
            requests.append(row)
            if record.get('text') is not None:
                text=record['text'];match=re.search(r'```python\s*\n(.*?)\n```',text,re.DOTALL)
                stem=identifier.replace('/','_');response=exports/(stem+'.response.txt');response.write_text(text)
                code_file=None
                if match:
                    code_file=exports/(stem+'.py');code_file.write_text(match.group(1)+'\n')
                candidates.append({'id':identifier,'group':group,'category':(attempt or {}).get('category'),
                    'code_key':(attempt or {}).get('code_key'),'response_file':str(response.relative_to(flow.directory)),
                    'code_file':str(code_file.relative_to(flow.directory)) if code_file else None,
                    'code_export_status':'raw model text; validity follows attempt/evaluation, not .py extension',
                    'request':row,'evaluation':evaluation,'valid':bool(evaluation and evaluation.get('valid'))})
    for group in ('INIT',*ARMS):
        rows=[r for r in requests if r['group']==group]
        known=[r for r in rows if r['actual_platform_units'] is not None]
        valid=[r for r in rows if r['attempt'] and r['attempt'].get('category')=='valid']
        evaluated=[c['evaluation'] for c in candidates if c['group']==group and c['evaluation']]
        instances=[row for evaluation in evaluated for row in evaluation.get('instances',[])]
        costs.append({'group':group,'slots':len(rows),'confirmed_sends':sum(r['send_confirmed'] for r in rows),
            'categories':dict(Counter((r['attempt'] or {}).get('category',r['status']) for r in rows)),
            'valid_candidates':len(valid),'valid_per_confirmed_send':len(valid)/sum(r['send_confirmed'] for r in rows) if any(r['send_confirmed'] for r in rows) else None,
            'known_invoice_platform_units':sum(r['actual_platform_units'] for r in known),
            'unknown_invoice_requests':len(rows)-len(known),
            'known_wire_input_tokens':sum(r['wire_usage']['input_tokens'] for r in rows if r['wire_usage'] is not None),
            'known_wire_output_tokens':sum(r['wire_usage']['output_tokens'] for r in rows if r['wire_usage'] is not None),
            'unknown_wire_usage_requests':sum(r['wire_usage'] is None for r in rows),
            'known_valid_candidate_platform_units':sum(r['actual_platform_units'] for r in valid if r['actual_platform_units'] is not None),
            'primary_evaluation_seconds':sum(e.get('primary_evaluation_seconds',0) for e in evaluated),
            'single_solve_seconds':sum(x.get('single_solve_seconds',0) for x in instances),
            'deterministic_recheck_seconds':sum(x.get('deterministic_recheck_seconds',0) for x in instances),
            'diagnostic_replay_seconds':sum(x.get('diagnostic_replay_seconds',0) for x in instances),
            'known_provider_roundtrip_seconds':sum(r['provider_roundtrip_seconds'] for r in rows if r['provider_roundtrip_seconds'] is not None),
            'unknown_provider_roundtrip_times':sum(r['provider_roundtrip_seconds'] is None for r in rows)})
    calibrated=[{'id':r['id'],'group':r['group'],'platform_units_per_1000_wire_tokens':
                1000*r['actual_platform_units']/sum(r['wire_usage'].values())} for r in requests
                if r['actual_platform_units'] is not None and r['wire_usage'] is not None and sum(r['wire_usage'].values())>0]
    entries=training['entries']; comparisons=[]
    from itertools import combinations
    for a,b in combinations(entries,2):
        if a['phase']!='completed' or b['phase']!='completed':continue
        def best(entry):return sorted(entry['population'],key=lambda r:(-r['fitness'],r['id']))[0]
        aa,bb=best(a),best(b)
        # Descriptive train champions, never validation/test-selected U*.
        ha={r['file']:r for r in aa['training_result']['instances']};hb={r['file']:r for r in bb['training_result']['instances']}
        comparisons.append({'pair':a['arm']+'-'+b['arm'],'scope':'training champions; no independent test inference',
            'best_fitness_difference':aa['fitness']-bb['fitness'],
            'mean_population_fitness_difference':a['mean_population_train_fitness']-b['mean_population_train_fitness'],
            'instance_rows':[{'file':n,'A_makespan':ha[n]['makespan'],'B_makespan':hb[n]['makespan'],
                             'A_minus_B_makespan':ha[n]['makespan']-hb[n]['makespan']} for n in flow.dataset.names['train']]})
    asset=flow.write('Single_results.json','Single_results',requests=requests,candidates=candidates,
        costs=costs,train_comparisons=comparisons,training_report_hash=training['artifact_sha256'],
        all_fixed_member_train_results=training['fixed_h_train_results'],budget=flow.ledger.summary(),
        calibration={'unit':'raw platform units; USD/CNY conversion unverified',
            'observed_per_request_units_per_1000_combined_wire_tokens':calibrated,
            'not_official_price':'Ratios reflect actual observed input/output/caching/channel mix, not a price schedule.'},
        status='completed' if all(e['phase']=='completed' for e in entries) else 'partial_or_stopped',
        claim='one-seed preliminary conditional fixed-H training experiment; no MIX, validation or test')
    lines=['# 单成员四组条件训练结果','',f"状态：{asset['status']}；seed201、N5、每组一代10槽位。",
           f"确认发送 {sum(r['send_confirmed'] for r in requests)} 次，登记槽位 {len(requests)}；未补发。",
           '','| 阶段 | 槽位 | 有效候选 | 分类 | 已核实平台单位 | 未知账单 |',
           '|---|---:|---:|---|---:|---:|']
    for c in costs:lines.append(f"| {c['group']} | {c['slots']} | {c['valid_candidates']} | {c['categories']} | {c['known_invoice_platform_units']} | {c['unknown_invoice_requests']} |")
    lines+=['','| 组别 | 状态 | 最佳训练fitness | 种群平均fitness |','|---|---|---:|---:|']
    for e in entries:lines.append(f"| {e['arm']} | {e['phase']} | {e.get('best_train_fitness')} | {e.get('mean_population_train_fitness')} |")
    lines+=['','全部响应/代码见 candidate_exports；全部逐请求费用、逐候选完整训练结果及逐实例组间比较见 Single_results.json。',
            '旧开发记录不是本批结果。常量、重复及无改善均如实保留。平台单位和wire token分别报告；未知不是零。',
            '这是一个seed的训练条件实验，固定旧H来源；未执行validation/test，不能推出独立泛化或正式H生成效果。']
    (flow.directory/'Single_results.md').write_text('\n'.join(lines)+'\n')
    return asset
