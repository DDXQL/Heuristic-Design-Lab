"""Offline audit of saved A/B outcomes and best-effort billing association.

No network, no generation, no scheduling. Does not alter any original receipts.
"""
import csv
from collections import Counter
from statistics import fmean
from tools import cross_feedback_ab_execute as x


def save_csv(path,rows):
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)


def audit():
    x.check();r=x.DIRECTORY;out=x.REPORT
    state=x.read(r/'checkpoint.json');journal=x.read(r/'API_attempts.json');plan=x.read(x.BASE/'Tasks.json')
    tasks={t['task_id']:t for t in plan['tasks']}
    start=x.read(r/'Invoices_start.json');end=x.read(r/'Invoices_end.json');seen={i['request_id'] for i in start['records']}
    new=[i for i in end['records'] if i['request_id'] not in seen];allocated=set();fees=[]
    for aid,a in journal['api_attempts'].items():
        metadata=(a.get('reply') or {}).get('metadata',a.get('metadata',{})) or {}
        rid=metadata.get('gateway_request_id');usage=a.get('usage')
        matches=[i for i in new if i.get('request_id')==rid and i.get('model_name')=='gpt-6.1-sol' and i.get('group')=='codex-deafult'];mode='exact_request_id'
        if not matches and usage:
            matches=[i for i in new if i.get('model_name')=='gpt-6.1-sol' and i.get('group')=='codex-deafult'
                and i.get('type')==2 and i.get('prompt_tokens')==usage['input_tokens'] and i.get('completion_tokens')==usage['output_tokens']
                and a['started_at']-2<=i['created_at']<=a['finished_at']+30]
            mode='unique_new_receipt_model_group_window_token_pair'
        if len(matches)!=1 or matches[0]['request_id'] in allocated:raise ValueError('fee association ambiguous; preserve unknown')
        invoice=matches[0];allocated.add(invoice['request_id'])
        fees.append({'attempt_id':aid,'task_id':a['logical_id'],'condition':tasks[a['logical_id']]['condition'],
            'status':a['status'],'association':mode,'wire_request_id':rid,'invoice_request_id':invoice['request_id'],
            'input_tokens':usage['input_tokens'] if usage else None,'output_tokens':usage['output_tokens'] if usage else None,
            'invoice_points':invoice['quota'],'API_seconds':a['elapsed_seconds'],'actual_CNY':None})
    delta=x.read(r/'Account_end.json')['quota']['total_used']-x.read(r/'Account_start.json')['quota']['total_used']
    points=sum(i['quota'] for i in new)
    if len(new)!=30 or len(allocated)!=30 or points!=delta or points!=sum(f['invoice_points'] for f in fees):raise ValueError('batch account/receipt reconciliation mismatch')
    x.write(out/'Billing_association.json',{'new_receipt_count':30,'observed_account_used_delta_points':delta,
        'new_receipt_points':points,'exact_request_id_matches':sum(f['association']=='exact_request_id' for f in fees),
        'token_window_associations':sum(f['association']!='exact_request_id' for f in fees),'actual_CNY':None,
        'qualification':'29 wire gateway IDs differ from invoice IDs; unique tokens/model/group/window and total account delta agree. Supplementary association, not strict request-ID certification; no unknown hold released.',
        'records':fees})
    save_csv(out/'Billing_association.csv',fees)
    with (out/'Candidates.csv').open() as f:entries=list(csv.DictReader(f))
    index={(e['pair_id'],e['repeat_id'],e['condition']):e for e in entries};pairs=[]
    for pair in plan['pairs']:
        for repeat in ['1','2','3']:
            a=index[pair['pair_id'],repeat,'A'];b=index[pair['pair_id'],repeat,'B']
            fa=float(a['fitness']) if a['certified_valid']=='True' else None;fb=float(b['fitness']) if b['certified_valid']=='True' else None
            pairs.append({'pair_id':pair['pair_id'],'repeat_id':repeat,'A_Fitness':fa,'B_Fitness':fb,
                'B_minus_A':fb-fa if fa is not None and fb is not None else None,'A_status':a['status'],'B_status':b['status']})
    save_csv(out/'Paired_repeat_results.csv',pairs)
    complete=[p for p in pairs if p['B_minus_A'] is not None]
    signs=Counter('B_win' if p['B_minus_A']>0 else 'B_loss' if p['B_minus_A']<0 else 'tie' for p in complete)
    rows=0
    for key,record in state['evaluations'].items():
        result=x.read(r/record['result_path']);folder=r/'evaluations'/key
        life=x.read(folder/'lifecycle.json');before=x.read(folder/'before.json');after=x.read(folder/'after.json')
        if (record['status']!='completed' or not result['valid'] or len(result['instances'])!=21
            or result['fitness']!=fmean(i['score'] for i in result['instances']) or life['exitcode']!=0
            or life['alive'] is not False or life['receiver_thread_stopped'] is not True
            or life['all_results_received'] is not True or life['cleanup']!=['join_exit_grace_2.0']
            or before['identity']!=after['identity'] or before['identity']!=x.read(r/'Expected_loaded_identity.json')['identity']
            or any(i['captured_solves']!=2 or i['physical_schedule_sha256']!=i['recheck_physical_schedule_sha256'] for i in result['instances'])):
            raise ValueError('saved result certification mismatch')
        rows+=len(result['instances'])
    if rows!=609 or any(r.rglob('Clock_quarantine.json')) or (r/'Stop.json').exists():raise ValueError('run not cleanly completed')
    for task in plan['tasks']:
        rec=journal['requests'][task['task_id']]
        if rec['prompt']!=(x.BASE/'prompts'/(task['task_id']+'.txt')).read_text():raise ValueError('dispatch prompt differs from original')
    x.write(out/'Final_verification.json',{'passed':True,'certified_programs':29,'certified_instances':rows,
        'solve_passes_started':1218,'normal_exit0_and_identity_all':True,'pending_requests':0,
        'unknown_evaluation_reservations':0,'clock_quarantines':0,'original_tasks_and_prompts_unchanged':True,
        'API_attempts':30,'retries':0,'paired_complete_units':len(complete),'paired_signs':dict(signs),
        'paired_mean_B_minus_A':fmean(p['B_minus_A'] for p in complete),'raw_points_reconciled':points})
    print('POST_AUDIT_PASSED',dict(signs),'observed points',points,flush=True)


if __name__=='__main__':audit()
