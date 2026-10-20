"""New-protocol conditional fixed-H experiment, never promotion of a dev run.

Old code/order/reviews/receipts stay immutable; every member is re-evaluated.
Explicit research-scope approval and new request authorization are required.
Historical budgets stay external, hash pinned, and count against lifetime caps.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
from fjsp_usage.research.protocol import digest
from fjsp_usage.research.events import atomic_json
from .assets import check_seal, load_h, checked_candidate, check_result, validate_row
from .budget import BudgetStop

VERSION = 'conditional-fixed-existing-H-v1-20261011'


def validate_declaration(config):
    d = config.conditional_research
    fields = {'version','source_run','source_files_sha256','history_batches',
              'lifetime_request_cap','scope_approval','baseline_policy','holdout_policy'}
    if (not isinstance(d,dict) or set(d)!=fields or d['version']!=VERSION
            or config.mode!='real' or config.purpose!='research'
            or config.development_h_source or config.development_continuation_source or config.development_acceptance
            or d['lifetime_request_cap']!=300 or config.platform_quota_ceiling!=30000000
            or not config.training_diagnostics or d['baseline_policy']!='validation_select_one_report_all_train'
            or d['holdout_policy']!='locked_until_protocol_and_search_complete'
            or not d['source_files_sha256'] or len(set(d['history_batches']))!=len(d['history_batches'])):
        raise ValueError('conditional research requires explicit fixed-H provenance/history/approval and unchanged lifetime boundaries')
    for name in [d['source_run']]+d['history_batches']:
        p=PurePosixPath(name)
        if p.is_absolute() or len(p.parts)!=1 or '..' in p.parts:
            raise ValueError('research sources must be named runs children')
    for name, sha in d['source_files_sha256'].items():
        p=PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or str(p)!=name or len(p.parts)<2 or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('research source pins require normal runs-relative paths and SHA256')
    approval=d['scope_approval']
    if approval is not None:
        if (not isinstance(approval,dict) or set(approval)!={'reviewer','scope','note','source_H_sha256','member_code_keys'}
                or approval['scope']!='conditional-fixed-H-research'
                or any(not isinstance(approval[k],str) or not approval[k].strip() for k in ('reviewer','note'))):
            raise ValueError('actual human scope approval required; no placeholder reviewer')


def pinned_bundle(root, declaration, *, check_writer=True):
    runs=(Path(root)/'runs').resolve(); docs={}
    for name,expected in declaration['source_files_sha256'].items():
        path=(runs/name).resolve()
        if not path.is_relative_to(runs) or path==runs: raise ValueError('source path escape')
        if check_writer and (runs/PurePosixPath(name).parts[0]/'.writer.lock').exists(): raise ValueError('research source has a writer lock')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected: raise ValueError('historical research source changed: '+name)
        if path.suffix=='.json': docs[name]=json.loads(raw)
    return docs


def _get(docs, run, name):
    key=run+'/'+name
    if key not in docs: raise ValueError('missing source pin: '+key)
    return docs[key]


def check_origin(root, config, dataset, *, check_writer=True):
    d=config.conditional_research; docs=pinned_bundle(root,d,check_writer=check_writer); run=d['source_run']
    old=_get(docs,run,'protocol.json'); source=_get(docs,run,'H_frozen.json')
    check_seal(source,kind='H_frozen',mode='real',context=digest(old))
    if old['dataset']!=dataset.metadata or old['config']['instance_timeout']!=config.instance_timeout:
        raise ValueError('conditional source requires identical data order/hash and evaluation deadline')
    if old['config']['provider']!=config.payload()['provider']:
        from fjsp_usage.usage_v2.model_migration import check_provider_migration
        check_provider_migration(config, old['config']['provider'], source['artifact_sha256'])
    members=load_h(source,mode='real',context=digest(old),size=config.H_size,
        names=dataset.names['train'],review_timeout=config.review_timeout)
    # Confirm frozen descriptions still reflect the actual original human action.
    origin=old['config']['development_continuation_source']['run']
    original_H=_get(docs,origin,'H_frozen.json')
    original_protocol=_get(docs,origin,'protocol.json')
    generated=_get(docs,origin,'H_candidates.json')
    check_seal(original_H,kind='H_frozen',mode='real',context=digest(original_protocol))
    check_seal(generated,kind='H_candidates',mode='real',context=digest(original_protocol))
    if original_H['source_hash']!=generated['artifact_sha256']:
        raise ValueError('original frozen H generation binding mismatch')
    reviews=_get(docs,origin,'H_review_completed_20261010.json')
    confirmation=_get(docs,origin,'human_review_confirmation_20261010.json')
    if (source['members']!=original_H['members'] or confirmation.get('human_approved') is not True
            or set(confirmation['code_keys'])!={m.key for m in members}
            or confirmation['review_file_sha256']!=d['source_files_sha256'][origin+'/H_review_completed_20261010.json']
            or confirmation['H_source_hash']!=generated['artifact_sha256']
            or set(reviews)!={m.key for m in members}):
        raise ValueError('original human review/code/order evidence mismatch')
    for row in source['members']:
        review=row['review']; key=row['candidate']['key']
        if any(review[k]!=v for k,v in reviews[key].items()): raise ValueError('human description/reviewer changed')
        # Native receipts may originate in earlier H runs; verify those raw
        # ledgers and exact response journals, not just copied foreign receipts.
        receipt=row['receipt']; candidate=checked_candidate(row['candidate'],'h')
        ledgers=[x for n,x in docs.items() if n.endswith('/budget.json') and x.get('identity')==receipt['ledger_identity']]
        matches=[b['records'].get(receipt['global_key']) for b in ledgers]
        if not any(r and r.get('send_confirmed') is True and r['status']=='completed'
                   and r['usage']==receipt['usage'] and r['prompt_key']==receipt['prompt_key'] for r in matches):
            raise ValueError('H receipt missing original confirmed ledger')
        journals=[x for n,x in docs.items() if n.endswith(('budgeted_initial_requests.json','budgeted_evolution_requests.json'))]
        if not any(r.get('global_key')==receipt['global_key'] and r.get('text')==receipt['response_text']
                   and r.get('prompt_key')==receipt['prompt_key'] for j in journals for r in j['requests'].values()):
            raise ValueError('H receipt missing original raw response')
        validate_row(row,dataset.names['train'],'real','h')
    # This pathway changes prompt/observation, not state or action semantics.
    from .config import fingerprint
    current=fingerprint(root)
    for path in ('code/fjsp_usage/offline_v2.py','code/fjsp_usage/research/scheduler.py',
                 'code/llm4ad/task/optimization/fjsp_set/scheduler.py',
                 'code/llm4ad/task/optimization/fjsp_set/instances.py'):
        if old['implementation']['files'].get(path)!=current['files'].get(path):
            raise ValueError('conditional H state/scheduler/parser changed; a new reviewed protocol required')
    return source,members,docs


def history_summary(root, config):
    """Keep every unknown wire reservation; only final invoices settle account holds."""
    d=config.conditional_research; docs=pinned_bundle(root,d)
    slots=sends=hold=0; unknown=[]; charges=[]; latest_used=0
    source=_get(docs,d['source_run'],'protocol.json')
    plan=source['config']['development_acceptance']
    zero_proof=docs.get(plan['billing_evidence']['path'].removeprefix('runs/'))
    if (not zero_proof or zero_proof.get('success') is not True or zero_proof.get('inference_requests')!=0
            or d['source_files_sha256'].get(plan['billing_evidence']['path'].removeprefix('runs/'))!=plan['billing_evidence']['sha256']):
        raise ValueError('historical zero-debit evidence not pinned')
    settled=_get(docs,d['source_run'],'platform_quota.json').get('development_settlement_reconciliation',[])
    settlement={s['global_key']:s for s in settled}
    request_ids=set()
    for run in d['history_batches']:
        budget=_get(docs,run,'budget.json'); quota=_get(docs,run,'platform_quota.json')
        old=_get(docs,run,'protocol.json')
        historical_model=old['config']['provider']['model']
        if budget['identity']!=digest({'config':old['config'],'context':digest(old)}) or quota['identity']!=budget['identity']:
            raise ValueError('historical ledger/protocol identity mismatch')
        latest_used=max(latest_used,quota.get('observed_used',0))
        slots+=len(budget['records']); sends+=sum(r.get('send_confirmed',False) for r in budget['records'].values())
        for key,r in budget['records'].items():
            identity=(budget['identity'],key)
            if identity in request_ids: raise ValueError('overlapping history batches would double-count')
            request_ids.add(identity)
            charges.append(r['usage'] if r.get('usage') is not None else r['reservation'])
            if r.get('usage') is not None: continue
            q=quota['records'].get(key,{}); reserved=q.get('reserved',config.platform_quota_reservation)
            final=not r.get('send_confirmed',False); proof=None
            if r.get('send_confirmed'):
                z=[v for v in zero_proof['records'] if v.get('type')==5 and v.get('quota')==0
                   and v.get('model_name')==historical_model and v.get('request_id')
                   and q.get('started_at',float('inf'))<=v.get('created_at',0)<=q.get('finished_at',-30)+30]
                if len(z)==1: final=True; proof=z[0]
                s=settlement.get(key) if run==d['source_run'] else None
                if s:
                    path=s['proof']['path'].removeprefix('runs/')
                    body=docs.get(path)
                    if d['source_files_sha256'].get(path)!=s['proof']['sha256'] or not body or body.get('success') is not True or body.get('inference_requests')!=0:
                        raise ValueError('failed-request invoice proof changed')
                    match=[v for v in body['records'] if v.get('request_id')==s['proof']['provider_request_id']]
                    if (len(match)!=1 or match[0]!=s['invoice'] or match[0].get('type')!=2
                            or type(match[0].get('quota')) is not int or match[0]['quota']<0
                            or match[0].get('model_name')!=historical_model
                            or not q.get('started_at',float('inf'))<=match[0].get('created_at',0)<=q.get('finished_at',-30)+30):
                        raise ValueError('failed-request invoice does not match model/window/id')
                    final=True; proof=match[0]
                if not final and quota.get('invoice_reconciliations'):
                    # New prior batches may have certified failed-send invoices
                    # while their response token usage remains unknown. Require
                    # immutable, model/window/debit-matched proof; never rewrite
                    # the raw ledger or discard its token reservation.
                    from fjsp_usage.usage_v2.billing import certified_reconciliation
                    invoice=certified_reconciliation(key,q,quota['invoice_reconciliations'],docs,run,historical_model,d['source_files_sha256'])
                    if invoice is not None: final=True; proof=invoice
            if not final: hold+=reserved
            unknown.append({'run':run,'key':key,'raw_record':r,'raw_quota':q,
                'account_hold':0 if final else reserved,'account_final_proof':proof,
                'wire_usage':None,'token_reservation':r['reservation']})
    if slots+config.total_request_cap>d['lifetime_request_cap']: raise ValueError('new batch plus history exceeds lifetime request boundary')
    return {'historical_request_slots':slots,'historical_confirmed_sends':sends,
        'unknown_requests':unknown,'retained_account_hold':hold,'historical_token_charges':charges,
        'latest_saved_account_used':latest_used,'lifetime_request_cap':d['lifetime_request_cap'],
        'new_request_cap':config.total_request_cap,'notice':'Invoices settle account holds only; unknown wire usage/token reservations remain unchanged.'}


def prepare(flow):
    flow.assert_current(); source,members,_=check_origin(flow.project_root,flow.config,flow.dataset)
    history=history_summary(flow.project_root,flow.config)
    if (flow.directory/'Conditional_H_reassessment.json').exists():
        a=flow.read('Conditional_H_reassessment.json','Conditional_H_reassessment')
        if a['source_H_hash']!=source['artifact_sha256'] or a['history']!=history: raise ValueError('reassessment provenance changed')
        return a
    rows=[]
    for original in source['members']:
        candidate=checked_candidate(original['candidate'],'h')
        result=flow.train_eval(candidate,())
        check_result(result,flow.dataset.names['train'])
        rows.append({'source_row':original,'result':result,
            'same_training_makespans_as_source':result['valid'] and
                [r['makespan'] for r in result['instances']]==[r['makespan'] for r in original['training_result']['instances']]})
    asset=flow.write('Conditional_H_reassessment.json','Conditional_H_reassessment',
        source_H_hash=source['artifact_sha256'],source_run=flow.config.conditional_research['source_run'],
        training_files=list(flow.dataset.names['train']),rows=rows,history=history,
        research_scope_approved=flow.config.conditional_research['scope_approval'] is not None,
        notice='Existing development H conditioned on, not new formal EoH-S H generation; original human approval scope is unchanged.')
    # No automatic H freeze or approval. This is a reviewable offline result.
    atomic_json(flow.directory/'Conditional_H_scope_review_template.json',{
        'reviewer':'','scope':'conditional-fixed-H-research','note':'',
        'source_H_sha256':source['artifact_sha256'], 'member_code_keys':[m.key for m in members]})
    flow.progress('CONDITIONAL_RESEARCH_PREPARED_NO_NEW_REQUESTS', valid_H=sum(r['result']['valid'] for r in rows))
    return asset


def freeze_h(flow):
    flow.assert_current(); a=prepare(flow); source,members,_=check_origin(flow.project_root,flow.config,flow.dataset)
    approval=flow.config.conditional_research['scope_approval']
    if not approval: raise ValueError('existing H review was for development only; actual conditional research scope approval required')
    if approval['source_H_sha256']!=source['artifact_sha256'] or approval['member_code_keys']!=[m.key for m in members]:
        raise ValueError('research scope approval must bind exact original H codes and numbering')
    rows=[]
    for row in a['rows']:
        if not row['result']['valid']: raise ValueError('all conditional H members must pass complete new-protocol train evaluation')
        original=row['source_row']; result=row['result']
        rows.append({**original,'training_result':result,'fitness':result['fitness'],
            'scores':[r['score'] for r in result['instances']], 'conditional_source_hash':a['artifact_sha256']})
    if (flow.directory/'H_frozen.json').exists(): return h_asset(flow)[0]
    asset=flow.write('H_frozen.json','H_frozen',members=rows, member_count=len(members),
        training_files=list(flow.dataset.names['train']),source_hash=a['artifact_sha256'],
        source_mechanism='conditional existing development H; no new Tier1 generation',scope_approval=approval)
    h_asset(flow); flow.progress('CONDITIONAL_H_FROZEN')
    return asset


def h_asset(flow):
    source,_,_=check_origin(flow.project_root,flow.config,flow.dataset,check_writer=getattr(flow,'check_source_writer',True))
    a=flow.read('Conditional_H_reassessment.json','Conditional_H_reassessment')
    H=flow.read('H_frozen.json','H_frozen')
    approval=flow.config.conditional_research['scope_approval']
    if not approval or H.get('scope_approval')!=approval or H['source_hash']!=a['artifact_sha256'] or a['source_H_hash']!=source['artifact_sha256']:
        raise ValueError('conditional H source/approval binding mismatch')
    if approval['source_H_sha256']!=source['artifact_sha256'] or approval['member_code_keys']!=[r['candidate']['key'] for r in source['members']]:
        raise ValueError('conditional scope approval code/order mismatch')
    if len(a['rows'])!=len(source['members']): raise ValueError('reassessment member count mismatch')
    for r,old,e in zip(H['members'],source['members'],a['rows']):
        check_result(e['result'],flow.dataset.names['train'])
        if not e['result']['valid'] or e['source_row']!=old: raise ValueError('incomplete conditional train evidence')
        expected={**old,'training_result':e['result'],'fitness':e['result']['fitness'],
            'scores':[x['score'] for x in e['result']['instances']],'conditional_source_hash':a['artifact_sha256']}
        if r!=expected: raise ValueError('conditional member code/order/review/results changed')
    return H,load_h(H,mode='real',context=flow.context,size=flow.config.H_size,
        names=flow.dataset.names['train'],review_timeout=flow.config.review_timeout)


def dispatch_check(flow):
    flow.config.check_dispatch(); h_asset(flow)
    audit=history_summary(flow.project_root,flow.config)
    prepare_asset=flow.read('Conditional_H_reassessment.json','Conditional_H_reassessment')
    if prepare_asset['history']!=audit: raise BudgetStop('historical budget binding changed')
    return audit


def budget_check(ledger,key,phase):
    audit=history_summary(ledger.path.parent.parent.parent,ledger.config)
    if phase.startswith('H/') or phase not in ledger.config.phase_caps(): raise BudgetStop('conditional research permits no H generation')
    if audit['historical_request_slots']+len(ledger.data['records'])>=audit['lifetime_request_cap']:
        raise BudgetStop('cumulative 300-slot boundary exhausted')
    if not (ledger.path.parent/'H_frozen.json').exists(): raise BudgetStop('conditional research H not frozen')
    return audit
