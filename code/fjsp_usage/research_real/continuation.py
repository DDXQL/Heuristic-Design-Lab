"""Offline, development-only v3 -> v4 binding with durable budget carry-forward.

Original records are read-only. Rebinding context is not reapproving H or
reattributing its receipts. Unknown sent requests block dispatch, not preparation.
This adapter never queries a provider or opens/evaluates dataset instances.
"""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research.sets import ranked
from .assets import (check_seal, checked_candidate, validate_row, check_result,
                     make_receipt, seal)
from .budget import BudgetStop
from .config import ExperimentConfig
from .initialization import selector_signature
from .prompts import prompt_manifest
from .search import V5BudgetedSearch

OLD_VERSION = 'V5-FJSP-selector-prompts-v3-20261008'
from .prompts import PROMPT_VERSION
NEW_VERSION = PROMPT_VERSION
CHANGE_ALLOWLIST = {
    'code/fjsp_usage/research/evolution.py',
    'code/fjsp_usage/research_real/initialization.py',
    'code/fjsp_usage/research_real/prompts.py',
    'code/fjsp_usage/research_real/search.py',
    'code/fjsp_usage/research_real/continuation.py',
    'code/fjsp_usage/research_real/config.py',
    'code/fjsp_usage/research_real/budget.py',
    'code/fjsp_usage/research_real/development_reuse.py',
    'code/fjsp_usage/research_real/workflow.py',
    'experiments/tier2/research_real_v1/run.py',
    'experiments/tier2/research_real_v1/manifest.json',
    'code/fjsp_usage/research_real/quota_guard.py',
    'code/fjsp_usage/research_real/development_acceptance.py',
}
BASE_FILES = {'protocol.json', 'budget.json', 'platform_quota.json',
    'H_frozen.json', 'H_candidates.json', 'H/checkpoint.json',
    'H/budgeted_initial_requests.json', 'H/budgeted_evolution_requests.json',
    'H_review_completed_20261010.json', 'human_review_confirmation_20261010.json'}


def search_snapshot(config):
    return {'population_size':config.population_size,'generations':config.generations,
            'attempts_per_generation':config.attempts_per_generation,
            'phase_request_caps':config.phase_caps()}


def declaration(source):
    """Pin a quiet run; never read credentials or follow escaping symlinks."""
    source = Path(source).resolve()
    if (source/'.writer.lock').exists():
        raise ValueError('continuation source still has a writer lock')
    files = {}
    for path in sorted(source.rglob('*')):
        if path.is_file():
            if not path.resolve().is_relative_to(source):
                raise ValueError('source file escapes run directory')
            files[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'run': source.name, 'files_sha256': files}


def source_evidence(flow):
    config = flow.config
    if not config.development_continuation_source:
        raise ValueError('no explicit continuation source declaration')
    pins = config.development_continuation_source
    runs = (flow.project_root/'runs').resolve()
    source = (runs/pins['run']).resolve()
    if source.parent != runs or source == flow.directory.resolve():
        raise ValueError('source must be a distinct project runs child')
    if declaration(source) != {k:pins[k] for k in ('run','files_sha256')}:
        raise ValueError('continuation source files changed or were added/removed')
    def read(name):
        if name not in pins['files_sha256']:
            raise ValueError('required source evidence not hash-pinned: '+name)
        return json.loads((source/name).read_text())
    if not BASE_FILES <= set(pins['files_sha256']):
        raise ValueError('incomplete frozen-H/human/budget evidence pins')
    old = read('protocol.json')
    old_config = ExperimentConfig.from_dict(old['config'])
    if (old['mode'] != 'real' or old_config.purpose != 'framework_development'
            or old['dataset'] != flow.dataset.metadata or len(old_config.seeds) != 1
            or old_config.development_continuation_source is not None):
        raise ValueError('one-seed real development source with identical manifest required')
    a, b = old_config.payload(), config.payload()
    for key in ('real_requests_authorized', 'development_h_source', 'development_continuation_source', 'development_acceptance'):
        a.pop(key); b.pop(key)
    change = pins.get('search_change')
    if change:
        if (change['from'] != search_snapshot(old_config) or change['to'] != search_snapshot(config)
                or config.population_size >= old_config.population_size
                or config.generations != 1 or config.attempts_per_generation != 10):
            raise ValueError('declared development reduction differs from source/target parameters')
        for phase,cap in old_config.phase_caps().items():
            expected = 10 if phase.rsplit('/',1)[-1] in ('B0','B1','B2','P') else cap
            if config.phase_caps()[phase] != expected:
                raise ValueError('only unused evolution phase caps may shrink to ten')
        for key in ('population_size','generations','attempts_per_generation','phase_request_caps'):
            a.pop(key);b.pop(key)
    if a != b:
        raise ValueError('continuation changed model, evaluation, search or budget limits')
    pack = prompt_manifest()
    if old['prompt_pack']['version'] != OLD_VERSION or pack['version'] != NEW_VERSION:
        raise ValueError('only the declared legacy source and current pack are supported; task sections must remain identical')
    if any(pack['sections'].get(k) != value for k,value in old['prompt_pack']['sections'].items()):
        raise ValueError('H/task/operator/output prompt sections changed')
    previous, current = old['implementation'], flow.protocol['implementation']
    if any(previous[k] != current[k] for k in ('version','python','platform','dependencies')):
        raise ValueError('runtime/dependencies changed')
    changes = sorted(k for k in set(previous['files'])|set(current['files'])
                     if previous['files'].get(k) != current['files'].get(k))
    if set(changes)-CHANGE_ALLOWLIST:
        raise ValueError('evaluation/algorithm closure changed outside continuation allowance')
    context = digest(old)
    ledger = read('budget.json')
    if ledger['identity'] != digest({'config':old['config'],'context':context}):
        raise ValueError('original ledger context mismatch')
    quota = read('platform_quota.json')
    if quota['identity'] != ledger['identity']:
        raise ValueError('original account guard context mismatch')
    if (quota['ceiling'] != config.platform_quota_ceiling
            or quota['reservation'] != config.platform_quota_reservation):
        raise ValueError('account limits differ')
    if quota.get('observed_used',0) > config.platform_quota_ceiling:
        raise ValueError('account already exceeds development boundary')
    names = flow.dataset.names['train']
    H = check_seal(read('H_frozen.json'), kind='H_frozen',mode='real',context=context)
    generated = check_seal(read('H_candidates.json'),kind='H_candidates',mode='real',context=context)
    if (H['source_hash'] != generated['artifact_sha256'] or H['member_count'] != config.H_size
            or H['training_files'] != list(names) or len(H['members']) != config.H_size
            or [r['member_id'] for r in H['members']] != list(range(config.H_size))
            or [{k:v for k,v in r.items() if k not in ('review','member_id')} for r in H['members']]
               != ranked(generated['population'])):
        raise ValueError('frozen H order/source differs')
    confirmation = read('human_review_confirmation_20261010.json')
    reviews = read('H_review_completed_20261010.json')
    if (confirmation.get('human_approved') is not True
            or confirmation['review_file_sha256'] != pins['files_sha256']['H_review_completed_20261010.json']
            or confirmation['H_source_hash'] != generated['artifact_sha256']
            or set(confirmation['code_keys']) != set(reviews)
            or set(reviews) != {r['candidate']['key'] for r in H['members']}):
        raise ValueError('human confirmation not bound to exact frozen codes/review file')
    imported = None
    if any(r.get('source_import_hash') for r in H['members']):
        from .development_reuse import source_rows, check_imported_rows
        imported = check_seal(read('H_development_source.json'),
            kind='H_development_source',mode='real',context=context)
        originals, audit = source_rows(flow.project_root,old_config,old['dataset'],previous,
                                       _historical_prompt_pack=old['prompt_pack'])
        check_imported_rows(imported, originals, audit)
    old_transport = digest({'provider':old['config']['provider'],'mode':'real'})
    def native(row, kind, journal):
        candidate = checked_candidate(row['candidate'],kind)
        record = journal['requests'][row['id']]
        charged = ledger['records'][record['global_key']]
        if (record['status'] != 'completed' or charged['status'] != 'completed'
                or not charged['send_confirmed'] or charged['usage'] != record['usage']
                or charged['prompt_key'] != record['prompt_key']
                or record.get('response_metadata',{}).get('model') != config.provider.expected_response_model):
            raise ValueError('original response/model/usage/ledger inconsistent')
        return make_receipt(candidate,record,SimpleNamespace(data=ledger,identity=ledger['identity']),
                            old_config,old_transport)
    H_checkpoint = read('H/checkpoint.json')
    if (H_checkpoint['phase'] != 'completed' or H_checkpoint['generation'] != config.H_generations
            or {r['candidate']['key'] for r in H_checkpoint['population']} != set(reviews)):
        raise ValueError('H not backed by completed search checkpoint')
    for row in H['members']:
        candidate = validate_row(row,names,'real','h')
        review = row['review']
        if (review['reviewed_code_key'] != candidate.key
                or review['reviewer'] != confirmation['reviewer']
                or {k:review[k] for k in ('description','reviewer','method','note')} != reviews[candidate.key]
                or digest(review['samples']) != review['sample_sha256']):
            raise ValueError('human review changed or detached from code')
        checkpoint_row = next(r for r in H_checkpoint['population'] if r['id']==row['id'])
        if any(row.get(k) != v for k,v in checkpoint_row.items()):
            raise ValueError('H checkpoint binding mismatch')
        if row.get('source_import_hash'):
            original = next(r for r in imported['population'] if r['id']==row['id'])
            if row['source_import_hash'] != imported['artifact_sha256'] or any(row.get(k)!=v for k,v in original.items()):
                raise ValueError('imported H provenance changed')
        else:
            journal_name = 'H/budgeted_initial_requests.json' if '/init/' in row['id'] else 'H/budgeted_evolution_requests.json'
            if native(row,'h',read(journal_name)) != row['receipt']:
                raise ValueError('H receipt reattributed')
    seed = config.seeds[0]; repeat = f'r{seed}'
    if any(n.startswith(repeat+'/'+arm+'/') for n in pins['files_sha256'] for arm in ('B0','B1','B2','P')):
        raise ValueError('source already began four-arm evolution')
    checkpoint = read(repeat+'/INIT/checkpoint.json')
    journal = read(repeat+'/INIT/budgeted_initial_requests.json')
    journal_keys = set()
    for phase, log in (('H/init',read('H/budgeted_initial_requests.json')),
                       ('H/search',read('H/budgeted_evolution_requests.json')),
                       (repeat+'/init',journal)):
        for identifier, record in log['requests'].items():
            key = phase+'/'+identifier
            charged = ledger['records'].get(key)
            if (record['global_key'] != key or not charged or charged['phase'] != phase
                    or record['prompt_key'] != digest({'prompt':record['prompt'],'kind':record['kind']})
                    or charged['prompt_key'] != record['prompt_key']
                    or charged.get('usage') != record.get('usage')):
                raise ValueError('all historical request slots must retain journal/ledger binding')
            if charged.get('send_confirmed') and (key not in quota['records']
                    or not quota['records'][key].get('send_confirmed')):
                raise ValueError('confirmed send missing account record')
            journal_keys.add(key)
    if journal_keys != set(ledger['records']):
        raise ValueError('orphan/missing historical request reservations require separate investigation')
    if checkpoint['phase'] != 'initialization' or checkpoint['generation'] or checkpoint['children']:
        raise ValueError('source is not a partial shared initialization')
    count = len(journal['requests'])
    expected_ids = [f'INIT/init/{i:06d}' for i in range(count)]
    if sorted(journal['requests']) != expected_ids:
        raise ValueError('initialization request IDs have gaps or collisions')
    if checkpoint['init_cursor'] + bool(checkpoint['inflight']) != count:
        raise ValueError('source cursor/journal differ')
    if checkpoint['inflight'] and checkpoint['inflight']['id'] != expected_ids[-1]:
        raise ValueError('unexpected inflight request identifier')
    rows, excluded, seen_signatures = [], [], {}
    for row in sorted(checkpoint['population'],key=lambda r:r['id']):
        candidate = checked_candidate(row['candidate'],'U')
        result = checkpoint['evaluations'][row['id']]['result']
        check_result(result,names)
        full = {**row,'receipt':native(row,'U',journal),'training_result':result}
        validate_row(full,names,'real','U')
        signature = selector_signature(candidate.code)
        if signature in seen_signatures:
            excluded.append({'id':row['id'],'code_key':candidate.key,'equivalent_to':seen_signatures[signature]})
        else:
            seen_signatures[signature] = row['id']; rows.append(full)
    if change and len(rows) != config.population_size:
        raise ValueError('reduced population must reuse ALL unique complete-training U, no truncation/refill')
    unresolved = sorted(key for key,r in ledger['records'].items()
        if r.get('send_confirmed') and (r.get('usage') is None or r['status'] in ('pending','reserved')))
    unresolved = sorted(set(unresolved)|{key for key,r in quota['records'].items()
                                       if r['status'] in ('pending','settlement_unknown')})
    if ledger.get('halted') or quota.get('halted'):
        raise ValueError('source has a separate halted/overrun condition requiring explicit investigation')
    if len(ledger['records']) > config.total_request_cap:
        raise ValueError('source already exceeded request cap')
    for phase, cap in config.phase_caps().items():
        if sum(r['phase']==phase for r in ledger['records'].values()) > cap:
            raise ValueError('source already exceeded phase cap')
    return {'source':str(source),'old_context':context,'old_protocol':old,'H':H,
        'generated':generated,'checkpoint':checkpoint,'journal':journal,'ledger':ledger,
        'quota':quota,'seed':seed,'rows':ranked(rows),'excluded':excluded,
        'init_cursor':count,'unresolved':unresolved,'source_changes':changes,
        'search_change':change,'reuse_shared_complete':bool(change)}


class OfflineTransport:
    def __init__(self, config):
        self.identity = digest({'provider':config.payload()['provider'],'mode':config.mode})

    def preflight(self, *args, **kwargs):
        raise AssertionError('offline continuation must not send')

    dispatch = preflight


def binding_payload(flow, evidence):
    payload = {'source_declaration':flow.config.development_continuation_source,
        'original_context':evidence['old_context'],
        'original_H_hash':evidence['H']['artifact_sha256'],
        'original_budget_identity':evidence['ledger']['identity'],
        'inherited_U_ids':[r['id'] for r in evidence['rows']],
        'excluded_equivalent_U':evidence['excluded'],
        'inherited_init_cursor':evidence['init_cursor'],
        'unresolved_requests':evidence['unresolved'],
        'source_changes':evidence['source_changes'],
        'declared_search_change':evidence['search_change'],
        'reuse_shared_complete':evidence['reuse_shared_complete']}
    if flow.config.development_acceptance:
        from .development_acceptance import check_plan
        payload['development_acceptance'] = check_plan(flow,evidence)
    return payload


def check_binding(flow):
    evidence = source_evidence(flow)
    binding = flow.read('Continuation_binding.json','Continuation_binding')
    expected = binding_payload(flow,evidence)
    if any(binding.get(k)!=v for k,v in expected.items()):
        raise ValueError('continuation binding differs from original evidence')
    if (flow.ledger.data.get('continuation_binding_hash') != binding['artifact_sha256']
            or flow.ledger.data.get('continuation_unresolved_requests') != evidence['unresolved']
            or any(flow.ledger.data['records'].get(k)!=v for k,v in evidence['ledger']['records'].items())):
        raise ValueError('inherited budget records, unknown reservation or binding were reset')
    frozen = flow.read('H_frozen.json','H_frozen')
    if (frozen.get('original_frozen_hash') != evidence['H']['artifact_sha256']
            or frozen.get('continuation_binding_hash') != binding['artifact_sha256']):
        raise ValueError('rebound H lost its original freeze binding')
    if flow.config.development_acceptance:
        from .development_acceptance import check_resume
        resumed = check_resume(flow,evidence)
        if resumed and any(flow.ledger.data['records'].get(k)!=v for k,v in resumed['ledger']['records'].items()):
            raise ValueError('development search-resume budget history was modified')
    return binding,evidence


def check_foreign_row(flow, row):
    binding,evidence = check_binding(flow)
    origins = evidence['H']['members']+evidence['rows']
    if flow.config.development_acceptance:
        from .development_acceptance import check_resume
        resumed = check_resume(flow,evidence)
        if resumed: origins += resumed['imported_children']
    match = next((r for r in origins if r['id']==row['id']),None)
    if match is None:
        if row['receipt']['ledger_identity'] != flow.ledger.identity:
            raise ValueError('unbound foreign receipt')
        return False
    expected = match
    if row['candidate']['kind']=='h' and 'review' not in row:
        expected = {k:v for k,v in match.items() if k not in ('review','member_id')}
    if row != expected:
        raise ValueError('inherited candidate/review/receipt/result changed')
    return True


def check_dispatch_gate(flow):
    _,evidence = check_binding(flow)
    if flow.config.development_acceptance:
        from .development_acceptance import check_plan
        check_plan(flow,evidence)
    elif evidence['unresolved'] or flow.ledger.data.get('continuation_unresolved_requests'):
        raise BudgetStop('inherited interrupted request usage/account settlement unknown; no API dispatch')
    flow.config.check_dispatch()
    return evidence


def prepare(flow):
    flow.assert_current()
    evidence = source_evidence(flow)
    if (flow.directory/'Continuation_binding.json').exists():
        check_binding(flow)
        if not (flow.directory/'Offline_continuation_ready.json').exists():
            raise ValueError('incomplete offline preparation; preserve it and use a new target directory')
        return flow.read('Offline_continuation_ready.json','Offline_continuation_ready')
    if flow.ledger.data['records'] or (flow.directory/'H_frozen.json').exists():
        raise ValueError('continuation target must be empty before binding')
    binding = flow.write('Continuation_binding.json','Continuation_binding',**binding_payload(flow,evidence))
    resumed = None
    if flow.config.development_acceptance:
        from .development_acceptance import check_resume
        resumed = check_resume(flow,evidence)
    flow.ledger.data.update(records=deepcopy((resumed or evidence)['ledger']['records']),
        continuation_binding_hash=binding['artifact_sha256'],
        continuation_unresolved_requests=evidence['unresolved'])
    flow.ledger.save()
    account = deepcopy((resumed or evidence)['quota'])
    if resumed:
        account.update(halted=False,development_settlement_reconciliation=resumed['settlement_audit'])
        account.pop('stop_reason',None)
    account.update(identity=flow.ledger.identity,continuation_binding_hash=binding['artifact_sha256'])
    if evidence['unresolved'] and not flow.config.development_acceptance:
        account.update(halted=True,stop_reason='inherited sent request settlement unknown; no new dispatch')
    atomic_json(flow.directory/'platform_quota.json',account)
    source = evidence['generated']
    generated = flow.write('H_candidates.json','H_candidates',**{k:v for k,v in source.items()
        if k not in ('kind','mode','context','artifact_sha256')})
    frozen = flow.write('H_frozen.json','H_frozen',**{**{k:v for k,v in evidence['H'].items()
        if k not in ('kind','mode','context','artifact_sha256','source_hash')},
        'source_hash':generated['artifact_sha256'],'original_frozen_hash':evidence['H']['artifact_sha256'],
        'continuation_binding_hash':binding['artifact_sha256']})
    members = tuple(checked_candidate(r['candidate'],'h') for r in frozen['members'])
    seed = evidence['seed']; folder = flow.directory/f'r{seed}/INIT'
    engine = V5BudgetedSearch(folder,arm='INIT',config=flow.config.u_search(seed),members=members,
        evaluator=lambda c: (_ for _ in ()).throw(AssertionError('offline: no evaluation')),
        transport=OfflineTransport(flow.config),context=flow.context,
        init_phase=f'r{seed}/init',search_phase=f'r{seed}/B0',ledger=flow.ledger,
        experiment=flow.config,training_names=flow.dataset.names['train'])
    state = deepcopy(evidence['checkpoint']); state['signature'] = engine.signature
    state.update(population=evidence['rows'],init_cursor=evidence['init_cursor'],inflight=None,
                 continuation_binding_hash=binding['artifact_sha256'])
    if evidence['reuse_shared_complete']:
        state['phase']='evolution'
    if evidence['checkpoint']['inflight']:
        state['attempts'].append({'id':evidence['checkpoint']['inflight']['id'],
            'operator':'I1','parents':[],'status':'interrupted',
            'error':'sent before interruption; usage unknown; never replay'})
    engine.state = state
    from fjsp_usage.research.evolution import _tuple_tree
    engine.rng.setstate(_tuple_tree(state['rng'])); engine._save()
    journal = deepcopy(evidence['journal']); journal['identity'] = engine.initial_requests.data['identity']
    for record in journal['requests'].values():
        if record['status']=='pending':
            record.update(status='interrupted',error='inherited uncertain sent request; never replay')
    atomic_json(engine.initial_requests.path,journal)
    shared = None
    if evidence['reuse_shared_complete']:
        shared = flow.write(f'r{seed}/Shared_initial.json','Shared_initial',seed=seed,
            H_hash=frozen['artifact_sha256'],training_files=list(flow.dataset.names['train']),
            population=evidence['rows'])
    if resumed:
        engine = V5BudgetedSearch(flow.directory/f'r{seed}/P',arm='P',config=flow.config.u_search(seed),
            members=members,evaluator=lambda c: (_ for _ in ()).throw(AssertionError('offline: no evaluation')),
            transport=OfflineTransport(flow.config),context=flow.context,kind='U',initial=evidence['rows'],
            init_phase=f'r{seed}/init',search_phase=f'r{seed}/P',ledger=flow.ledger,
            experiment=flow.config,training_names=flow.dataset.names['train'])
        state=deepcopy(resumed['checkpoint']);state['signature']=engine.signature
        state['children']=resumed['imported_children']
        engine.state=state;engine.rng.setstate(_tuple_tree(state['rng']));engine._save()
        journal=deepcopy(resumed['journal']);journal['identity']=engine.evolution_requests.data['identity']
        atomic_json(engine.evolution_requests.path,journal)
        flow.write('Development_search_resume.json','Development_search_resume',
            source=flow.config.development_acceptance['search_resume_source'],
            consumed_evolution_slots=len(state['attempts']),imported_children=state['children'],
            settlement_audit=resumed['settlement_audit'],notice='No replay, no regenerated child, unknown wire usage/reservations preserved.')
    ready = flow.write('Offline_continuation_ready.json','Offline_continuation_ready',
        continuation_binding_hash=binding['artifact_sha256'],H_hash=frozen['artifact_sha256'],
        original_H_hash=evidence['H']['artifact_sha256'],H_members=len(frozen['members']),
        inherited_U=len(evidence['rows']),initialization_cursor=evidence['init_cursor'],
        next_request_id=f'INIT/init/{evidence["init_cursor"]:06d}',
        budget=flow.ledger.summary(),new_model_requests=0,new_instance_evaluations=0,
        formal_holdout_reads=0,dispatch_ready=(not evidence['unresolved'] or bool(flow.config.development_acceptance)) and flow.config.real_requests_authorized,
        unresolved_requests=evidence['unresolved'],four_arms_started=False,
        shared_initial_complete=shared is not None,
        shared_initial_hash=shared['artifact_sha256'] if shared else None,
        declared_search_change=evidence['search_change'])
    flow.progress('OFFLINE_CONTINUATION_PREPARED',dispatch_ready=ready['dispatch_ready'],
                  inherited_U=ready['inherited_U'],initialization_cursor=ready['initialization_cursor'])
    return ready
