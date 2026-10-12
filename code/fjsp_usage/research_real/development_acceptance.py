"""Explicit single-P development acceptance, with retained unknown reservations.

Never settles an old request or opens formal holdouts. Development validation/test
reuse named training files, and cannot support an independent generalization claim.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from fjsp_usage.research.protocol import digest
from llm4ad.task.optimization.fjsp_set import load_instance
from .assets import checked_candidate, check_result
from .budget import BudgetStop
from .runtime import evaluate


def pinned(path, expected):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('development historical evidence changed: '+str(path))
    return json.loads(path.read_text())


def previous_snapshots(runs, plan):
    snapshots=[]
    for name, pins in plan['previous_batches'].items():
        folder=(runs/name).resolve()
        if folder.parent!=runs.resolve() or set(pins)!={'budget_sha256','quota_sha256'}:
            raise ValueError('invalid previous-batch declaration')
        snapshots.append((name,pinned(folder/'budget.json',pins['budget_sha256']),
                          pinned(folder/'platform_quota.json',pins['quota_sha256'])))
    return snapshots


def previous_charges(runs,plan):
    return [r['usage'] if r.get('usage') is not None else r['reservation']
            for _,budget,_ in previous_snapshots(runs,plan) for r in budget['records'].values()]


def check_resume(flow,evidence):
    """Validate a stopped P search and final supplier invoices without editing it."""
    from .continuation import declaration,CHANGE_ALLOWLIST
    from .assets import check_seal,make_receipt
    from .config import ExperimentConfig
    from types import SimpleNamespace
    plan=flow.config.development_acceptance
    pins=plan.get('search_resume_source') if plan else None
    if not pins: return None
    runs=(flow.project_root/'runs').resolve();source=(runs/pins['run']).resolve()
    if source.parent!=runs or source==flow.directory.resolve() or declaration(source)!=pins:
        raise ValueError('stopped P source changed, active or outside runs')
    def read(name):
        if name not in pins['files_sha256']: raise ValueError('missing P resume evidence: '+name)
        return json.loads((source/name).read_text())
    old=read('protocol.json'); oldcontext=digest(old)
    previous=ExperimentConfig.from_dict(old['config'])
    a,b=previous.payload(),flow.config.payload()
    a.pop('development_acceptance');b.pop('development_acceptance')
    if a!=b or old['dataset']!=flow.dataset.metadata or old['prompt_pack']!=flow.protocol['prompt_pack']:
        raise ValueError('P resume cannot change search, model, scoring, dataset, limits or prompts')
    core=lambda p:{k:v for k,v in p.items() if k not in ('search_resume_source','settled_failed_requests')}
    if not previous.development_acceptance or core(previous.development_acceptance)!=core(plan):
        raise ValueError('P resume plan changed outside explicit evidence binding')
    impl=old['implementation'];current=flow.protocol['implementation']
    if any(impl[k]!=current[k] for k in ('version','python','platform','dependencies')):
        raise ValueError('P resume runtime changed')
    if {k for k in set(impl['files'])|set(current['files']) if impl['files'].get(k)!=current['files'].get(k)}-CHANGE_ALLOWLIST:
        raise ValueError('P resume changed evaluation/algorithm closure')
    # Preserve every earlier resume snapshot too; paid branches are serial.
    ancestor=previous.development_acceptance.get('search_resume_source');seen={source}
    while ancestor:
        parent=(runs/ancestor['run']).resolve()
        if parent in seen or len(seen)>16 or parent.parent!=runs or declaration(parent)!=ancestor:
            raise ValueError('changed or cyclic P resume ancestry')
        seen.add(parent)
        ancestor=json.loads((parent/'protocol.json').read_text())['config']['development_acceptance'].get('search_resume_source')
    ledger=read('budget.json');quota=read('platform_quota.json')
    if ledger['identity']!=digest({'config':old['config'],'context':oldcontext}) or quota['identity']!=ledger['identity'] or ledger['halted']:
        raise ValueError('P source ledger identity/overrun invalid')
    if any(ledger['records'].get(k)!=v for k,v in evidence['ledger']['records'].items()):
        raise ValueError('P source lost original reservations')
    if quota['halted'] and quota.get('stop_reason')!='unknown usage or possibly delayed account charge; manual investigation required':
        raise ValueError('P source stopped for a different financial condition')
    prefix=f'r{flow.config.seeds[0]}/P';state=read(prefix+'/checkpoint.json')
    journal=read(prefix+'/budgeted_evolution_requests.json')
    initial=check_seal(read(f'r{flow.config.seeds[0]}/Shared_initial.json'),kind='Shared_initial',mode='real',context=oldcontext)
    if initial['population']!=evidence['rows'] or state['population']!=evidence['rows'] or state['generation']!=0 or state['phase']!='evolution':
        raise ValueError('resume requires frozen P0 and an unfinished first generation')
    n=len(journal['requests'])
    if not 0<n<10 or state['cursor']!=n or len(state['attempts'])!=n or sorted(journal['requests'])!=[f'P/g0000/{i:06d}' for i in range(n)]:
        raise ValueError('P resume cursors/calls are missing or reset')
    extras={k:v for k,v in ledger['records'].items() if k not in evidence['ledger']['records']}
    if set(extras)!={prefix+'/'+k for k in journal['requests']}:
        raise ValueError('P source has orphan or other-phase requests')
    settlement=[];minimum=0;unknown=[]
    proofs=plan.get('settled_failed_requests',{})
    for identifier,r in journal['requests'].items():
        key=prefix+'/'+identifier;charged=extras[key];account=quota['records'][key]
        if (r['global_key']!=key or charged['phase']!=prefix or charged['usage']!=r['usage']
                or charged['prompt_key']!=r['prompt_key'] or r['prompt_key']!=digest({'prompt':r['prompt'],'kind':'U'})
                or r['status'] not in ('completed','failed') or not charged.get('send_confirmed')):
            raise ValueError('P request journal/ledger incomplete or mismatched')
        if r['usage'] is not None and account['status']=='settled': continue
        unknown.append(key)
        proof=proofs.get(key)
        if not proof or set(proof)!={'path','sha256','provider_request_id'}: raise ValueError('new unknown P failure needs exact final billing evidence')
        path=(flow.project_root/proof['path']).resolve()
        if not path.is_relative_to(runs): raise ValueError('P settlement proof must remain in runs')
        body=pinned(path,proof['sha256'])
        if body.get('success') is not True or body.get('inference_requests')!=0: raise ValueError('invalid supplier billing proof')
        records=[x for x in body['records'] if x.get('request_id')==proof['provider_request_id']
            and x.get('model_name')==flow.config.provider.model and x.get('type') in (2,5)
            and type(x.get('quota'))==int and x['quota']>=0
            and account['started_at']<=x.get('created_at',0)<=account.get('finished_at',-30)+30]
        if len(records)!=1 or r['status']!='failed': raise ValueError('supplier invoice not matched to failed P request')
        row=records[0];minimum=max(minimum,account['before_used']+row['quota'])
        settlement.append({'global_key':key,'invoice':row,'proof':proof,'wire_usage_still_unknown':True,
            'original_token_reservation':charged['reservation'],'original_quota_record':account})
    if set(proofs)!=set(unknown): raise ValueError('P settlement declarations must exactly cover uncertain P requests')
    imported=[]
    for child in state['children']:
        identifier=child['id'];r=journal['requests'][identifier];c=checked_candidate(child['candidate'],'U')
        result=state['evaluations'][identifier]['result'];check_result(result,flow.dataset.names['train'])
        if not result['valid'] or child['scores']!=[x['score'] for x in result['instances']]: raise ValueError('P imported child lacks complete train results')
        receipt=make_receipt(c,r,SimpleNamespace(data=ledger,identity=ledger['identity']),previous,
            digest({'provider':old['config']['provider'],'mode':'real'}))
        full={k:v for k,v in child.items() if k not in ('receipt','training_result')}
        full.update(receipt=receipt,training_result=result)
        # Across another resume, keep the original child receipt identity.
        if 'receipt' in child: full['receipt']=child['receipt']
        imported.append(full)
    return {'ledger':ledger,'quota':quota,'checkpoint':state,'journal':journal,
        'imported_children':imported,'settlement_audit':settlement,'settlement_min_used':minimum}


def check_plan(flow,evidence):
    plan=flow.config.development_acceptance
    if not plan: raise ValueError('single-P development plan required')
    names=set(flow.dataset.names['train'])
    if any(set(plan[k])-names for k in ('validation_names','test_names')):
        raise ValueError('development subsets may only contain already-used train names')
    retained={k:evidence['quota']['records'][k]['reserved'] for k in evidence['unresolved']}
    if retained!=plan['retained_unknown_requests']:
        raise ValueError('must retain every inherited unresolved account reservation exactly')
    runs=flow.project_root/'runs'
    previous=previous_snapshots(runs,plan)
    prior_slots=sum(len(b['records']) for _,b,_ in previous)
    if flow.config.total_request_cap+prior_slots>300:
        raise ValueError('lifetime development cap would exceed 300')
    proof=plan['billing_evidence']; logs=[]
    if proof:
        if set(proof)!={'path','sha256'}: raise ValueError('billing proof requires path/hash')
        path=(flow.project_root/proof['path']).resolve()
        if not path.is_relative_to(runs.resolve()): raise ValueError('billing proof must stay in runs')
        body=pinned(path,proof['sha256'])
        if body.get('success') is not True or body.get('inference_requests')!=0:
            raise ValueError('historical supplier metadata evidence invalid')
        logs=body['records']
    hold=0; accounts=[]
    for name,budget,quota in previous:
        unknown=[]
        for key,r in budget['records'].items():
            if r.get('usage') is not None: continue
            q=quota['records'].get(key)
            # An unsent slot remains consumed, with unknown token reservation;
            # it incurred no new account request. Confirmed sends require proof
            # or an additional account hold, even if aggregate delta was zero.
            final=not r.get('send_confirmed')
            matched=[]
            if q:
                matched=[x for x in logs if x.get('type')==5 and x.get('quota')==0
                    and x.get('model_name')==flow.config.provider.model
                    and q.get('started_at',float('inf'))<=x.get('created_at',0)<=q.get('finished_at',-30)+30
                    and x.get('request_id')]
                final=final or len(matched)==1
            if not final:
                hold+=(q or {}).get('reserved',flow.config.platform_quota_reservation)
            unknown.append({'key':key,'original_record':r,'original_quota':q,
                'account_terminal_zero_proof':matched[0] if len(matched)==1 else None,
                'account_hold_required':not final})
        accounts.append({'run':name,'request_slots':len(budget['records']),
            'confirmed_sends':sum(r.get('send_confirmed',False) for r in budget['records'].values()),
            'unknown_usage_original_records':unknown})
    resumed=check_resume(flow,evidence)
    return {'search_resume_source':plan.get('search_resume_source'),
            'settlement_audit':resumed['settlement_audit'] if resumed else [],
            'settlement_min_used':resumed['settlement_min_used'] if resumed else 0,
            'configuration':plan,'previous_request_slots':prior_slots,
            'previous_unknown_account_hold':hold,'previous_batches':accounts,
            'retained_current_account_hold':sum(retained.values()),
            'notice':'No old ledger/quota/usage/response modified. Unknown tokens keep their reservations; billing proof does not replace missing wire usage.'}


def check_budget_scope(ledger,key,phase):
    plan=ledger.config.development_acceptance
    expected=f'r{ledger.config.seeds[0]}/P'
    if phase!=expected or not key.startswith(expected+'/P/g0000/'):
        raise BudgetStop('single-P acceptance forbids initialization, H or other arms')
    if sorted(ledger.data.get('continuation_unresolved_requests',[]))!=sorted(plan['retained_unknown_requests']):
        raise BudgetStop('unknown historical reservations lost or changed')
    if sum(r['phase']==phase for r in ledger.data['records'].values())>=plan['max_new_requests']:
        raise BudgetStop('single-P ten-slot development cap exhausted')
    if plan.get('search_resume_source'):
        pins=plan['search_resume_source'];source=ledger.path.parent.parent/pins['run']
        old=pinned(source/'budget.json',pins['files_sha256']['budget.json'])
        if any(ledger.data['records'].get(k)!=v for k,v in old['records'].items()):
            raise BudgetStop('P resume history was reset or modified')
    previous=previous_snapshots(ledger.path.parent.parent,plan)
    if len(ledger.data['records'])+sum(len(b['records']) for _,b,_ in previous)>=300:
        raise BudgetStop('lifetime 300-slot development cap exhausted')


def ensure(flow):
    flow.assert_current()
    from .continuation import check_binding
    binding,evidence=check_binding(flow)
    check_plan(flow,evidence)
    return binding


def final_population(flow):
    ensure(flow)
    H,members=flow.h_asset()
    population,rows=flow.population(f'r{flow.config.seeds[0]}/P/Final_population.json',
                                   'Final_population',H['artifact_sha256'])
    initial=flow.read(f'r{flow.config.seeds[0]}/Shared_initial.json','Shared_initial')
    if population['shared_initial_hash']!=initial['artifact_sha256']:
        raise ValueError('single-P initial population changed')
    return H,members,population,rows,initial


def seen_evaluation(flow,candidate,members,stage,names,gate_hash):
    # Read train only, never StagedDataset.load/authorize for holdouts.
    flow.dataset.verify('train')
    indices=[flow.dataset.names['train'].index(name) for name in names]
    def calculate():
        instances=[]
        for name,i in zip(names,indices):
            path=flow.dataset.paths['train'][i]
            expected=flow.dataset.manifest['files'][name]['sha256']
            if hashlib.sha256(path.read_bytes()).hexdigest()!=expected: raise ValueError('seen-train file changed')
            instances.append(load_instance(path))
            if hashlib.sha256(path.read_bytes()).hexdigest()!=expected: raise ValueError('seen-train changed during load')
            flow.dataset.opened.append(('development_'+stage,name))
        return evaluate(candidate,members,instances,names,timeout=flow.config.instance_timeout)
    key=digest({'development_stage':stage,'names':names,'code':candidate.key,
                'H':[m.key for m in members],'gate_hash':gate_hash})
    return flow.cache.get(key,names,calculate)


def selection(flow):
    H,members,population,rows,initial=final_population(flow)
    names=flow.config.development_acceptance['validation_names']
    path=flow.directory/'Development_selection.json'
    if path.exists():
        result=flow.read(path.name,'Development_selection')
    else:
        results=[{'id':r['id'],'result':seen_evaluation(flow,checked_candidate(r['candidate'],'U'),
                     members,'validation',names,population['artifact_sha256'])} for r in rows]
        valid=[r for r in results if r['result']['valid']]
        best=min(valid,key=lambda r:(-r['result']['fitness'],r['id'])) if valid else None
        result=flow.write(path.name,'Development_selection',arm='P',seed=flow.config.seeds[0],
            H_hash=H['artifact_sha256'],population_hash=population['artifact_sha256'],
            shared_initial_hash=initial['artifact_sha256'],names=names,results=results,
            status='selected' if best else 'all_invalid',
            selected_row=next(r for r in rows if r['id']==best['id']) if best else None,
            selected_result=best['result'] if best else None,
            notice='Seen training instances; workflow check only, not independent validation.')
    if (result['population_hash']!=population['artifact_sha256'] or result['H_hash']!=H['artifact_sha256']
            or result['shared_initial_hash']!=initial['artifact_sha256'] or result['names']!=names
            or [r['id'] for r in result['results']]!=[r['id'] for r in rows]):
        raise ValueError('development selection binding mismatch')
    for r in result['results']: check_result(r['result'],names)
    valid=[r for r in result['results'] if r['result']['valid']]
    best=min(valid,key=lambda r:(-r['result']['fitness'],r['id'])) if valid else None
    chosen=next(r for r in rows if r['id']==best['id']) if best else None
    if (result['selected_row']!=chosen or result['selected_result']!=(best['result'] if best else None)
            or result['status']!=('selected' if best else 'all_invalid')):
        raise ValueError('development selection must use all final candidates and stable tie')
    flow.progress('DEVELOPMENT_SELECTION_COMPLETE',selected_id=chosen['id'] if chosen else None)
    return result


def freeze(flow):
    selected=selection(flow)
    if selected['status']!='selected': raise ValueError('no valid development U star; cannot freeze success')
    path=flow.directory/'Development_frozen.json'
    if path.exists():
        frozen=flow.read(path.name,'Development_frozen')
        if frozen['selection_hash']!=selected['artifact_sha256'] or frozen['selected_row']!=selected['selected_row']:
            raise ValueError('development freeze changed')
        return frozen
    frozen=flow.write(path.name,'Development_frozen',arm='P',seed=flow.config.seeds[0],
        H_hash=selected['H_hash'],population_hash=selected['population_hash'],
        shared_initial_hash=selected['shared_initial_hash'],selection_hash=selected['artifact_sha256'],
        selected_row=selected['selected_row'],validation_names=selected['names'],
        test_names=flow.config.development_acceptance['test_names'],dataset_hash=flow.dataset.key,
        frozen_at_utc=datetime.now(timezone.utc).isoformat(),notice='Development-only U star; no formal experiment freeze.')
    flow.progress('DEVELOPMENT_FROZEN',selected_id=frozen['selected_row']['id'])
    return frozen


def test(flow):
    frozen=flow.read('Development_frozen.json','Development_frozen')
    if frozen!=freeze(flow): raise ValueError('development test freeze mismatch')
    if frozen['test_names']!=flow.config.development_acceptance['test_names'] or frozen['dataset_hash']!=flow.dataset.key:
        raise ValueError('development test subset changed')
    if (flow.directory/'Development_test_complete.json').exists():
        result=flow.read('Development_test_complete.json','Development_test_complete')
        if result['freeze_hash']!=frozen['artifact_sha256']: raise ValueError('test belongs to different freeze')
        check_result(result['result'],frozen['test_names'])
        return result
    _,members=flow.h_asset()
    evaluated=seen_evaluation(flow,checked_candidate(frozen['selected_row']['candidate'],'U'),
                members,'test',frozen['test_names'],frozen['artifact_sha256'])
    result=flow.write('Development_test_complete.json','Development_test_complete',
        freeze_hash=frozen['artifact_sha256'],selected_id=frozen['selected_row']['id'],
        selected_code_key=frozen['selected_row']['candidate']['key'],names=frozen['test_names'],
        result=evaluated,LLM_requests=0,notice='Seen training subset, code-path acceptance only; U star not changed from test result.')
    flow.progress('DEVELOPMENT_TEST_COMPLETE',valid=evaluated['valid'])
    return result


def report(flow):
    tested=test(flow)
    H,_,population,rows,initial=final_population(flow)
    state=json.loads((flow.directory/f'r{flow.config.seeds[0]}/P/checkpoint.json').read_text())
    counts=dict(Counter(r['status'] for r in state['attempts']))
    phase=f'r{flow.config.seeds[0]}/P'
    charged={k:r for k,r in flow.ledger.data['records'].items() if r['phase']==phase}
    from .continuation import check_binding
    _,evidence=check_binding(flow)
    plan=check_plan(flow,evidence)
    result=flow.write('Development_report.json','Development_report',
        purpose='single-P framework development acceptance',arm='P',
        stages={'H_reuse':True,'P0_reuse':True,'P_one_generation':state['phase']=='completed',
                'development_selection':True,'development_freeze':True,'development_test':True},
        actual_new_requests=sum(r.get('send_confirmed',False) for r in charged.values()),
        consumed_new_slots=len(charged),candidate_outcomes=counts,
        valid_candidates=counts.get('valid',0),duplicate_candidates=counts.get('duplicate',0),
        failed_candidates=sum(n for status,n in counts.items() if status not in ('valid','duplicate')),
        initial_ids=[r['id'] for r in initial['population']],final_ids=[r['id'] for r in rows],
        population_size=len(rows),generation=state['generation'],
        initial_best_fitness=max(r['fitness'] for r in initial['population']),
        final_best_fitness=max(r['fitness'] for r in rows),
        selected_id=tested['selected_id'],selected_code_key=tested['selected_code_key'],
        development_test=tested['result'],budget=flow.ledger.summary(),
        lifetime_reserved_slots=len(flow.ledger.data['records'])+plan['previous_request_slots'],
        lifetime_confirmed_sends=sum(r.get('send_confirmed',False) for r in flow.ledger.data['records'].values())
            +sum(p['confirmed_sends'] for p in plan['previous_batches']),
        lifetime_request_hard_cap=300,retained_account_hold=plan['retained_current_account_hold']+plan['previous_unknown_account_hold'],
        account_guard=json.loads((flow.directory/'platform_quota.json').read_text()),
        other_arms_started=False,formal_holdout_reads=0,
        notice='Development validation/test reuse known training instances. No independent generalization or four-group comparison conclusion.')
    if any((flow.directory/f'r{flow.config.seeds[0]}/{a}').exists() for a in ('B0','B1','B2')):
        raise ValueError('single-P report found another arm')
    flow.progress('DEVELOPMENT_REPORT_COMPLETE',actual_new_requests=result['actual_new_requests'])
    return result
