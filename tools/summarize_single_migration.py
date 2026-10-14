#!/usr/bin/env python3
"""Post-run train/cost report; no credential, client, replay or holdout loading."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from statistics import fmean

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import seal
from fjsp_usage.research_real.single_billing import match_invoice


def build(directory):
    p=Path(directory);results=json.loads((p/'Single_results.json').read_text())
    training=json.loads((p/'Training_report.json').read_text())
    budget=json.loads((p/'budget.json').read_text());quota=json.loads((p/'platform_quota.json').read_text())
    diag=json.loads((p/'Diagnostic_requests.json').read_text())['requests']
    requests=[*results['requests'],*({'global_key':v['global_key'],'id':k,'group':'DIAGNOSTIC',
        'wire_usage':v.get('usage'),'response_metadata':v.get('response_metadata',{}),'status':v['status'],
        'send_confirmed':budget['records'][v['global_key']]['send_confirmed'],'attempt':None} for k,v in diag.items())]
    proof_paths=[p/'Settlement_resume_proof.json',*sorted((p/'billing_reconciliations').glob('*.json'))]
    proofs={v['global_key']:(path,v) for path in proof_paths if path.exists() for v in [json.loads(path.read_text())]}
    rows=[]
    for r in requests:
        path=p/'billing'/(hashlib.sha256(r['global_key'].encode()).hexdigest()+'.json')
        bill=json.loads(path.read_text());units=bill.get('actual_platform_units') if bill.get('status')=='invoice_account_matched' else None
        invoice=bill.get('invoice');source=str(path.relative_to(p))
        if r['global_key'] in proofs:
            proof_path,proof=proofs[r['global_key']]
            if hashlib.sha256(path.read_bytes()).hexdigest()!=proof['original_billing_sha256']:raise ValueError('original bill changed')
            for name,sha in proof['evidence_files_sha256'].items():
                if hashlib.sha256((p/name).read_bytes()).hexdigest()!=sha:raise ValueError('reconciliation evidence changed')
            invoice_evidence=next(name for name in proof['evidence_files_sha256'] if 'invoices' in name)
            after=json.loads((p/invoice_evidence).read_text())
            invoice=match_invoice(bill['before'],after,proof['reconciled_account'],'gpt-6.1-sol',
                failed=True,response_id=proof['supplier_request_id'])
            if invoice!=proof['invoice']:raise ValueError('reconciliation invoice mismatch')
            units=invoice['quota'];source=str(proof_path.relative_to(p))
        not_sent=(not r['send_confirmed'] and bill.get('status')=='before_dispatch'
            and bill.get('before',{}).get('success') is not True
            and r.get('error')=='cannot inspect supplier billing before dispatch'
            and r['global_key'] not in quota['records'])
        rows.append({**r,'actual_platform_units':units,
            'model_request_state':'not_sent_proved_before_invoice_gate' if not_sent else ('confirmed_sent' if r['send_confirmed'] else 'send_uncertain'),
            'cost_status':'not_applicable_no_inference_request' if not_sent else ('verified_invoice' if units is not None else 'unknown'),'final_invoice':invoice,'final_cost_evidence':source,
            'wire_tokens':r.get('wire_usage'),
            'invoice_tokens':{'input_tokens':invoice.get('prompt_tokens'),'output_tokens':invoice.get('completion_tokens')} if invoice else None})
    if {r['global_key'] for r in rows}!=set(budget['records']) or len(rows)!=len(budget['records']):
        raise ValueError('every ledger request must have exactly one output/cost row')
    categories={g:dict(Counter((r.get('attempt') or {}).get('category',r['status']) for r in rows if r['group']==g))
        for g in ('INIT','B0','B1','B2','P','DIAGNOSTIC')}
    initial=training['initialization'][0];initial_scores=[r['fitness'] for r in initial.get('accepted_population',[])]
    groups=[]
    for e in training['entries']:
        pop=e.get('population',[]);initial_ids={r['id'] for r in initial.get('accepted_population',[])}
        groups.append({'arm':e['arm'],'status':e['phase'],'slots':e['attempts'],
            'categories':categories[e['arm']],
            'confirmed_model_requests':sum(r['send_confirmed'] for r in rows if r['group']==e['arm']),
            'proved_unsent_slots':sum(r['model_request_state']=='not_sent_proved_before_invoice_gate' for r in rows if r['group']==e['arm']), 'mean_train_fitness':e.get('mean_population_train_fitness'),
            'best_train_fitness':e.get('best_train_fitness'),
            'initial_mean_train_fitness':fmean(initial_scores) if initial_scores else None,
            'initial_best_train_fitness':max(initial_scores) if initial_scores else None,
            'new_children_surviving':sum(r['id'] not in initial_ids for r in pop),
            'population':pop})
    unknown_cost=[r['global_key'] for r in rows if r['cost_status']=='unknown']
    unknown_wire=[r['global_key'] for r in rows if r['send_confirmed'] and r.get('wire_usage') is None]
    artifact=seal({'kind':'Reconciled_single_training_results','mode':'real','context':results['context'],
        'requests':rows,'groups':groups,'categories':categories,'accepted_shared_U':len(initial_scores),
        'fresh_init_requests':sum(r['group']=='INIT' for r in rows),
        'diagnostic_requests':sum(r['group']=='DIAGNOSTIC' for r in rows),
        'formal_requests':sum(r['group']!='DIAGNOSTIC' and r['send_confirmed'] for r in rows),
        'formal_slots':sum(r['group']!='DIAGNOSTIC' for r in rows),
        'proved_unsent_slots':sum(r['model_request_state']=='not_sent_proved_before_invoice_gate' for r in rows),
        'valid_candidates':sum((r.get('attempt') or {}).get('category')=='valid' for r in rows),
        'known_new_cost_points':sum(r['actual_platform_units'] for r in rows if r['actual_platform_units'] is not None),
        'unknown_cost_requests':unknown_cost,'unknown_wire_usage_requests':unknown_wire,
        'known_wire_input_tokens':sum(r['wire_usage']['input_tokens'] for r in rows if r.get('wire_usage') is not None),
        'known_wire_output_tokens':sum(r['wire_usage']['output_tokens'] for r in rows if r.get('wire_usage') is not None),
        'fixed_H_train_results':training['fixed_h_train_results'],
        'train_comparisons':results['train_comparisons'],
        'raw_body_archival_gap':['r201/init/INIT/init/000005'],
        'archival_gap_notice':'Full wire usage/model/stop/id known, but response body lost at 429 quota query before recording fix; slot remains failed, no reconstructed candidate.',
        'budget':results['budget'],'latest_verified_used_points':quota.get('observed_used'),
        'old_unknown_account_hold_points':24000000,'new_unknown_fee_hold_points':sum(
            quota['records'][k]['reserved'] for k in unknown_cost if k in quota['records']),
        'old_unknowns_never_zeroed':True,'quota_halted':quota['halted'],
        'unit':'raw platform points; no verified USD/CNY conversion',
        'comparison_integrity':'four-arm comparison invalidated by unequal infrastructure failures and zero actual B1 evolution requests' if any(g['confirmed_model_requests']==0 for g in groups) else 'inspect per-arm request/availability history before attributing train differences',
        'status':results['status'],'scope':'One seed, fixed-existing-H conditional TRAINING study; no validation/test, effect/generalization conclusion or MIX.'})
    atomic_json(p/'Reconciled_training_results.json',artifact)
    lines=['# gpt-6.1-sol 单成员四组训练批次','',artifact['scope'],'',
        f"诊断{artifact['diagnostic_requests']}，正式生成{artifact['formal_requests']}；有效候选{artifact['valid_candidates']}；新实际核实扣费{artifact['known_new_cost_points']}点。",
        f"未知费用请求：{unknown_cost}；未知wire用量请求：{unknown_wire}。原两个未知账户预留24000000点保持。",'',
        '| 组 | 阶段 | 槽位 | 实际模型请求 | 未发送槽位 | 分类 | 初始均值 | 最终均值 | 最终最佳 | 新子代存活 |',
        '|---|---|---:|---:|---:|---|---:|---:|---:|---:|']
    for g in groups:lines.append(f"| {g['arm']} | {g['status']} | {g['slots']} | {g['confirmed_model_requests']} | {g['proved_unsent_slots']} | {g['categories']} | {g['initial_mean_train_fitness']} | {g['mean_train_fitness']} | {g['best_train_fitness']} | {g['new_children_surviving']} |")
    lines+=['','## 每次请求和候选成本','',
        '有效候选行使用本次生成实际账单，不把共享初始化或失败请求成本摊成假定费用；整批全部成本另行汇总。wire与账单token分别保存。','',
        '| 请求 | 分类 | 实际点数 | wire输入/输出 | 成本凭证 |','|---|---|---:|---|---|']
    for r in rows:
        cat=(r.get('attempt') or {}).get('category',r['status'])
        lines.append(f"| {r['global_key']} | {cat} | {r['actual_platform_units'] if r['cost_status']!='not_applicable_no_inference_request' else '未发送／费用不适用'} | {r.get('wire_usage')} | [{r['final_cost_evidence']}]({r['final_cost_evidence']}) |")
    lines+=['',artifact['comparison_integrity'],'',artifact['archival_gap_notice'],'',
        '全部候选源码/响应在candidate_exports及wire_responses；逐实例成绩、可行性、fitness和分开计时见本JSON及Training_report.json。旧gpt-5.6-sol阶段为503访问失败中止，不混入本初始池或比较。']
    (p/'Final_training_report.md').write_text('\n'.join(lines)+'\n')
    atomic_json(p/'Final_budget_handoff.json',{'version':'single-ID-final-cumulative-handoff-v1-20261014',
        'real_caller_active':False,'budget_identity':budget['identity'],'budget_sha256':hashlib.sha256((p/'budget.json').read_bytes()).hexdigest(),
        'summary':artifact['budget'],'quota_halted':quota['halted'],
        'latest_verified_used_points':quota.get('observed_used'),'known_new_points':artifact['known_new_cost_points'],
        'unknown_new_fee_keys':unknown_cost,'old_account_hold':24000000,
        'unknown_new_fee_holds':artifact['new_unknown_fee_hold_points'],
        'unknown_wire_keys':unknown_wire,'reconciliation_files':[str(path.relative_to(p)) for path in proof_paths if path.exists()],
        'old59_authorization_retired':True,'remaining_model_batch_cap':61-len(budget['records'])})
    return artifact


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',required=True,type=Path);a=p.parse_args()
    artifact=build(a.run_dir)
    print(json.dumps({k:artifact[k] for k in ('status','formal_requests','valid_candidates','known_new_cost_points','unknown_cost_requests')},ensure_ascii=False))


if __name__=='__main__':main()
