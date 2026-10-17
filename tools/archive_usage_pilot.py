#!/usr/bin/env python3
"""Local evidence export for the completed registered seed301 pilot; no eval/API.

Reconcile original export's missing fee fields from certified native/supplemental
receipts without replacing raw reports, failed slots or unknown wire usage.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'code')]
from tools.resume_usage_metadata import verify_existing,sha
from fjsp_usage.research.candidates import parse_response
from fjsp_usage.usage_v2 import VERSION
from fjsp_usage.usage_v2.training_export import observed_profile


def read(p):return json.loads(p.read_text())
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def table(p,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def archive(run,out):
    if (run/'.writer.lock').exists():raise ValueError('wait for the active writer to finish')
    raw=read(run/'results/Training_results.json')
    if raw['status']!='COMPLETED_TRAINING_ONLY':raise ValueError('incomplete pilot is not a final A/B result')
    budget=read(run/'budget.json');quota=read(run/'platform_quota.json');config=read(run/'config.gpt61.authorized.json')
    if quota['halted']:raise ValueError('unresolved quota gate')
    receipt_pins=verify_existing(run,budget,quota,config['provider']['model'])
    out.mkdir(parents=True,exist_ok=True);prompts=out/'Actual_prompts';responses=out/'Actual_responses'
    prompts.mkdir(exist_ok=True);responses.mkdir(exist_ok=True)
    requests=[];candidates=[];states={};journals={};compact_attempts={};fitness={}
    for arm in ('INIT','A','B'):
        folder=run/f'r301/{arm}';state=read(folder/'checkpoint.json');states[arm]=state
        journal=read(folder/('budgeted_initial_requests.json' if arm=='INIT' else 'budgeted_evolution_requests.json'))['requests'];journals[arm]=journal
        attempts={r['id']:r for r in state['attempts']}
        compact_attempts[arm]=[{k:x.get(k) for k in ('id','operator','parents','status','category','code_key','error_type')} for x in state['attempts']]
        for identifier,request in journal.items():
            key=request['global_key'];record=budget['records'][key];base=identifier.replace('/','__')
            (prompts/(base+'.txt')).write_text(request['prompt'])
            h=hashlib.sha256(key.encode()).hexdigest()+'.json';bill=read(run/'billing'/h);wire=read(run/'wire_responses'/h)
            if bill['status']=='invoice_account_matched':invoice=bill['invoice'];proof='billing/'+h
            else:
                proof='billing_reconciliations/'+h;invoice=read(run/proof)['invoice']
            text=request.get('text')
            if text is None:text=wire.get('reply',{}).get('text')
            if text is not None:(responses/(base+'.txt')).write_text(text)
            # A stored complete wire from a FAILED slot is archived as response
            # evidence only; never parsed, re-evaluated or inserted as a child.
            parsed=request['status']=='completed'
            result=state['evaluations'].get(identifier,{}).get('result',{})
            if parsed:
                c=parse_response(request['text'],interface_version=VERSION,member_count=10)
                path=out/(base+'.py')
                if path.exists() and path.read_text()!=c.code:raise ValueError('prior archived source changed')
                path.write_text(c.code);fitness[identifier]=result.get('fitness')
                candidates.append({'arm':arm,'id':identifier,'source':path.name,'code_key':c.key,
                    'description':c.description,'category':attempts[identifier].get('category'),
                    'fitness':result.get('fitness'),'failed_instance':result.get('failed_instance'),
                    'error_type':result.get('error_type'),'profile':observed_profile(result)})
            usage=record.get('usage')
            requests.append({'global_key':key,'arm':arm,'status':record['status'],
                'category':attempts[identifier].get('category'),'send_confirmed':record.get('send_confirmed'),
                'wire_status':wire['status'],'complete_response_saved':text is not None,'candidate_parser_admitted':parsed,
                'wire_input_tokens':usage['input_tokens'] if usage else None,
                'wire_output_tokens':usage['output_tokens'] if usage else None,
                'invoice_input_tokens':invoice.get('prompt_tokens'),'invoice_output_tokens':invoice.get('completion_tokens'),
                'actual_platform_points':invoice['quota'],'certified_receipt':proof,
                'request_elapsed_seconds':record.get('elapsed_seconds'),
                'elapsed_includes_user_pause':request.get('response_metadata',{}).get('request_elapsed_includes_user_pause',False)})
    comparisons=[]
    for index in range(10):
        aid=f'A/g0000/{index:06d}';bid=f'B/g0000/{index:06d}'
        ap=journals['A'][aid]['prompt'];bp=journals['B'][bid]['prompt']
        atext=ap.replace('Permitted modes: SELECT (0) ONLY.','Permitted modes: <paired>.')
        btext=bp.replace('Permitted modes: SELECT (0) OR MIX (1); at most two positive MIX weights.','Permitted modes: <paired>.')
        aa=next(x for x in states['A']['attempts'] if x['id']==aid);bb=next(x for x in states['B']['attempts'] if x['id']==bid)
        if atext!=btext or aa['parents']!=bb['parents'] or aa['operator']!=bb['operator']:
            raise ValueError('actual paired prompt/parent/operator difference beyond permitted modes')
        comparisons.append({'index':index,'operator':aa['operator'],'parents':aa['parents'],
            'mode_only_prompt_difference':True,'A_prompt_sha256':hashlib.sha256(ap.encode()).hexdigest(),
            'B_prompt_sha256':hashlib.sha256(bp.encode()).hexdigest()})
    groups=[];costs=[]
    for g in raw['groups']:
        arm=g['arm'];rr=[x for x in requests if x['arm']==arm]
        group={k:v for k,v in g.items() if k not in ('population_changes','cost')}
        group.update(actual_platform_points=sum(x['actual_platform_points'] for x in rr),cost=g['cost'],
            final_population=[{'id':x['id'],'fitness':x['fitness'],'code_key':x['candidate']['key']} for x in states[arm]['population']],
            best_train_fitness=max(x['fitness'] for x in states[arm]['population']))
        groups.append(group);cost=g['cost'];calls=cost.get('certified_h_calls') or {}
        costs.append({'arm':arm,'primary_evaluation_wall_seconds':cost.get('primary_evaluation_seconds'),
            'independent_diagnostic_wall_seconds':cost.get('independent_diagnostic_seconds'),
            'certified_primary_h_action_score_calls':calls.get('single_h_calls'),
            'certified_recheck_h_action_score_calls':calls.get('deterministic_recheck_h_calls'),
            'certified_diagnostic_h_action_score_calls':calls.get('diagnostic_h_calls'),
            'failed_instance_partial_h_calls_unknown':cost.get('unknown_failed_h_calls') is None,
            'actual_platform_points':group['actual_platform_points']})
    points=sum(x['actual_platform_points'] for x in requests)
    binding=read(run/'V22_binding.json')
    if quota['observed_used']!=binding['peer']['observed_used']+points:raise ValueError('account total differs from individually certified receipts')
    summary={'status':raw['status'],'run':run.name,'seed':301,'split':'21 train only','N':5,
        'source_H_sha256':config['conditional_research']['scope_approval']['source_H_sha256'],
        'provider':config['provider'],'transport_messages':'one user message containing the complete archived prompt; no client system message',
        'groups':groups,'request_slots':len(requests),'confirmed_sends':sum(x['send_confirmed'] for x in requests),
        'syntax_legal_candidates':len(candidates),'duplicate_count':sum(g['duplicate_count'] for g in groups),
        'complete_valid_new_candidates':sum(g['complete_valid_new_candidates'] for g in groups),
        'known_wire_input_tokens':raw['known_input_tokens'],'known_wire_output_tokens':raw['known_output_tokens'],
        'wire_usage_unknown_requests':sum(x['wire_input_tokens'] is None for x in requests),
        'actual_platform_points':points,'unknown_new_fee_requests':0,'currency_conversion_verified':False,
        'historical_request_slots':binding['historical_slots'],'lifetime_request_slots':binding['historical_slots']+len(requests),
        'historical_account_hold_unchanged':24000000,'latest_account_used_points':quota['observed_used'],
        'paired_train_summary':raw['paired_train_summary'],'best_final_candidate_profiles':raw['best_final_candidate_profiles'],
        'holdouts_evaluated':False,'handwritten_candidates_imported':0,
        'raw_export_fee_fields_remain_historical':'A slot1 and B slot4 journal metadata was not rewritten; certified fees here come from native/supplemental receipts.',
        'cost_scope':'Primary wall includes failed main deadlines. Certified per-pass h counts and solve components omit unknown failed-instance work. Request wall may include a marked user pause.',
        'limits':['single seed, one generation, train-selected champions','runtime/API failures reduce usable candidate counts',
            'serial execution, pause, metadata throttle and cache/billing differences affect operational cost',
            'MIX permission changes generated formulas as well as use mechanism; no same-formula ablation or independent generalization evidence']}
    save(out/'Complete_summary.json',summary);save(out/'All_generated_candidates.json',candidates)
    save(out/'Actual_prompt_pair_checks.json',comparisons);save(out/'Compact_attempts.json',compact_attempts)
    save(out/'Common_provider.json',config['provider']);table(out/'All_requests.csv',requests)
    table(out/'Evaluation_costs.csv',costs);table(out/'Paired_best_train.csv',raw['paired_best_train_results'])
    shutil.copyfile(run/'results/All_instance_results.csv',out/'All_instance_results.csv')
    # Financial handoff for subsequent stages. This is our own completed run.
    handoff={'real_caller_active':False,'registered_generation_phases_complete':True,
        'budget_identity':budget['identity'],'budget_sha256':sha(run/'budget.json'),'quota_halted':False,
        'known_new_points':points,'unknown_new_fee_keys':[],'unknown_new_fee_holds':0,
        'latest_verified_used_points':quota['observed_used'],'old_account_hold':24000000,
        'summary':raw['budget'],'phase_statuses':{a:states[a]['phase'] for a in ('A','B')},
        'complete_evidence_sha256':sha(run/'Usage_train_search_complete.json'),
        'receipt_files_sha256':receipt_pins,'notice':'Wire unknown tokens/reservations retained. No new seed/generation or validation/test authorization.'}
    save(run/'Final_budget_handoff.json',handoff)
    provenance=[]
    for folder in ('wire_responses','pause_recovery','financial_recovery'):
        provenance.extend(p for p in (run/folder).rglob('*') if p.is_file())
    provenance.extend(run.glob('User_pause.*.json'))
    provenance.extend(run.glob('Read_only_health.*.json'))
    provenance.extend([run/'config.gpt61.authorized.json',run/'H_frozen.json'])
    save(out/'Final_evidence_manifest.json',{'run':run.name,'protocol_sha256':sha(run/'protocol.json'),
        'budget_sha256':sha(run/'budget.json'),'quota_sha256':sha(run/'platform_quota.json'),
        'financial_handoff_sha256':sha(run/'Final_budget_handoff.json'),'receipt_files_sha256':receipt_pins,
        'runtime_provenance_files_sha256':{str(p.relative_to(run)):sha(p) for p in provenance},
        'archive_files_sha256':{str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='Final_evidence_manifest.json'}})
    return {'status':summary['status'],'slots':len(requests),'fees':points,'groups':[{k:g[k] for k in
        ('arm','syntax_legal_responses','complete_valid_new_candidates','failure_categories','best_train_fitness','mean_final_population_train_fitness')} for g in groups],
        'costs':costs,'pairing':raw['paired_train_summary']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();run=a.directory.resolve();out=a.output.resolve()
    if run.parent!=ROOT/'runs' or not out.is_relative_to(ROOT/'docs'):raise SystemExit('own run and docs output only')
    print(json.dumps(archive(run,out),ensure_ascii=False),flush=True)
