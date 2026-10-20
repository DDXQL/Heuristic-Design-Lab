#!/usr/bin/env python3
"""B2 engineering adapter. prepare/check are offline; execution needs new approval.

The old H01 science, prompts, search, validation and evaluator are imported intact.
No account, tariff or invoice client is constructed by this entry point.
"""
import argparse
import hashlib
from dataclasses import dataclass
import json
from pathlib import Path

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_result, check_seal
from fjsp_usage.research_real.budget import BudgetLedger, BudgetStop, request_history
from fjsp_usage.research_real.config import ExperimentConfig, fingerprint
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.usage_v2.fixed_h import source_h, wrapper, validate_declaration
from tools import h01_weight_search as old

ROOT = old.ROOT
LEGACY = old.DEFAULT
VERSION = 'H01-alpha-search-seed501-local-requests-v2-20261020'
DEFAULT = ROOT/'runs/h01-state-weight-search-seed501-local-v2-20261020'
BATCH_VERSION = 'H01-alpha-search-seed501-batch-retry-v3-20261020'
BATCH_DEFAULT = ROOT/'runs/h01-state-weight-search-seed501-batch-v3-20261020'
BATCH_POLICY = {'version':'batch-api-attempts-v1','logical_candidate_cap':20,
                'api_attempt_cap':30,'per_candidate_attempt_cap':3,'retry_backoff_seconds':[2,5]}
REBIND = {
    'code/fjsp_usage/research_real/budget.py': 'engineering: local request ledger',
    'code/fjsp_usage/research_real/config.py': 'engineering: explicit budget declaration',
    'code/fjsp_usage/research_real/workflow.py': 'engineering: client dispatch split',
    'code/fjsp_usage/usage_v2/access.py': 'engineering: durable response recorder',
    'code/fjsp_usage/usage_v2/config.py': 'engineering: new protocol/fixed-H declaration',
    'code/fjsp_usage/usage_v2/registration.py': 'engineering: local client branch',
    'code/fjsp_usage/usage_v2/workflow.py': 'engineering: H binding and report routing',
    'experiments/tier2/usage_v2/run.py': 'engineering: local CLI stages',
    'code/fjsp_usage/research_real/real_transport.py': 'engineering: structured transient network evidence; no transport retries',
    'code/fjsp_usage/research_real/conditional_research.py': 'engineering: pinned asset reads can omit old writer gate; hashes and provenance remain strict',
}
REPORT = 'tools/h01_weight_report.py'
ENGINEERING_FIELDS = {'experiment_version', 'real_requests_authorized', 'request_budget',
                      'fixed_h_source', 'platform_quota_ceiling', 'platform_quota_reservation'}


def science(payload):
    return json.loads(json.dumps({k:v for k,v in payload.items() if k not in ENGINEERING_FIELDS}))


@dataclass(frozen=True)
class Config(old.Config):
    experiment_version: str = VERSION
    fixed_h_source: dict | None = None

    def __post_init__(self):
        ExperimentConfig.__post_init__(self)
        original = old.common.read(LEGACY/'config.pending.json')
        batch = self.request_budget == BATCH_POLICY
        if (self.experiment_version != (BATCH_VERSION if batch else VERSION) or self.request_budget is None
                or science(self.payload()) != science(original)):
            raise ValueError('B2 science/model/search fields must equal the frozen H01 protocol')
        validate_declaration(self)


def audit_peer(directory, config, plan):
    """Terminal native journals, not bills; explicitly stopped 30/60 is valid.

    A prepared inflight prompt is acceptable only when no native reservation or
    request exists. It is recorded, never resumed or imported into this batch.
    """
    peer = Path(config.request_budget['history_source']['directory'])
    if (peer/'.writer.lock').exists():
        raise BudgetStop('peer still has a writer')
    p = old.common.read(peer/'protocol.json')
    h = old.common.read(peer/'Final_budget_handoff.json')
    ledger = old.common.read(peer/'budget.json')
    status = check_seal(old.common.read(peer/'Update_status.json'),kind='Update_status',mode='real',context=digest(p))
    if (h.get('real_caller_active') is not False or status['status'] not in ('completed','stopped_or_not_started')
            or (status['status'] != 'completed' and not status.get('stop_reason'))
            or h['budget_identity'] != ledger['identity'] or h['budget_sha256'] != old.common.sha(peer/'budget.json')
            or ledger['identity'] != digest({'config':p['config'],'context':digest(p)})
            or p['dataset'] != plan['dataset'] or p['config']['provider'] != config.payload()['provider']):
        raise BudgetStop('peer terminal, identity, data or generation parameters differ')
    keys, prepared, files = set(), [], [peer/n for n in ('protocol.json','budget.json','Update_status.json','Final_budget_handoff.json')]
    for arm in ('A','B'):
        folder = peer/f'r201/{arm}'
        files += [folder/'checkpoint.json',folder/'budgeted_evolution_requests.json']
        checkpoint = old.common.read(files[-2]); journal = old.common.read(files[-1])['requests']
        attempts = checkpoint['attempts']
        if (len(attempts) != len(journal) or {a['id'] for a in attempts} != set(journal)
                or status['arms'][arm]['slots'] != len(journal)):
            raise BudgetStop('peer attempt/journal/summary differs')
        for identifier,row in journal.items():
            key = row['global_key']; native = ledger['records'].get(key)
            if (key != f'r201/{arm}/{identifier}' or not native
                    or native['phase'] != f'r201/{arm}'
                    or row['status'] not in ('completed','failed','interrupted')
                    or any(row.get(k) != native.get(k) for k in ('status','usage','prompt_key'))
                    or row['prompt_key'] != digest({'prompt':row['prompt'],'kind':'U'})):
                raise BudgetStop('peer per-request native evidence differs or remains pending')
            keys.add(key)
        pending = checkpoint.get('inflight')
        if pending:
            key = f'r201/{arm}/'+pending['id']
            if pending['id'] in journal or key in ledger['records']:
                raise BudgetStop('peer inflight dispatch unresolved')
            wire = peer/'wire_responses'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
            if wire.exists():
                raise BudgetStop('peer prepared request has wire evidence')
            prepared.append({'id':pending['id'],'state':'prepared_only_not_sent; preserved, not resumed'})
    if keys != set(ledger['records']) or h['summary']['request_slots'] != len(keys):
        raise BudgetStop('orphan or omitted native request')
    sends = sum(r.get('send_confirmed',False) for r in ledger['records'].values())
    if sends != h['summary']['confirmed_sends']:
        raise BudgetStop('peer confirmed-send count differs')
    history = request_history(config,ROOT,exclude=directory)
    return {'status':status['status'],'native_slots':len(keys),'confirmed_sends':sends,
            'prepared_only':prepared,'history':history,'billing_queried':False,
            'files_sha256':{str(f):old.common.sha(f) for f in files}}


def data_and_h(config, directory):
    dataset = StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
    dataset.verify('train')  # File identity only; does not parse or schedule instances.
    H,members = source_h(config,dataset,fingerprint(ROOT),target=directory)
    from fjsp_usage.research.candidates import Candidate
    members = tuple(Candidate(row['review']['description'],m.code,m.key,'h')
                    for row,m in zip(H['members'],members))
    return dataset,H,members


def audit_legacy_inputs(legacy_plan):
    changes = []
    for name,expected in legacy_plan['pins'].items():
        actual = old.common.sha(ROOT/name)
        if actual != expected:
            if name not in REBIND and name != REPORT:
                raise ValueError('unapproved scientific/input identity change: '+name)
            changes.append({'file':name,'old_sha256':expected,'new_sha256':actual,
                'classification':REBIND.get(name,'report/export only: local budget and lineage reporting')})
    return changes


def prepare(directory, *, batch_retries=False):
    original = old.common.read(LEGACY/'config.pending.json')
    legacy_plan = old.common.read(LEGACY/'Plan.json')
    peer = old.PEER_RUN; source = old.common.RUN
    payload = {**original,'experiment_version':BATCH_VERSION if batch_retries else VERSION,'real_requests_authorized':False,
        'platform_quota_ceiling':None,'platform_quota_reservation':None,
        'request_budget':dict(BATCH_POLICY) if batch_retries else {'version':'local-request-budget-v1','lifetime_request_cap':300,
            'history_source':{'directory':str(peer), **{n+'_sha256':old.common.sha(peer/(n+'.json')) for n in ('protocol','budget')}}},
        'fixed_h_source':{'version':'usage-frozen-H-source-v1','directory':str(source),
            'files_sha256':{n:old.common.sha(source/n) for n in ('protocol.json','H_frozen.json','Conditional_H_reassessment.json')}}}
    config = Config.from_dict(payload)
    changes = audit_legacy_inputs(legacy_plan)
    dataset,H,members = data_and_h(config,directory)
    if dataset.metadata != legacy_plan['dataset'] or [m.key for m in members] != legacy_plan['H_order']:
        raise ValueError('frozen H order or dataset changed')
    peer_audit = None if batch_retries else audit_peer(directory,config,legacy_plan)
    initial = old.common.read(LEGACY/'Initial_population.json')
    if [r['id'] for r in initial] != legacy_plan['initial_ids']:
        raise ValueError('initial source identities changed')
    for row,percent in zip(initial,old.INITIAL):
        candidate = old.constant(percent)
        if candidate.key != row['candidate']['key'] or candidate.code != row['candidate']['code']:
            raise ValueError('manual initial source changed')
        check_result(row['training_result'],legacy_plan['names'])
        if row['fitness'] != row['training_result']['fitness'] or row['scores'] != [r['score'] for r in row['training_result']['instances']]:
            raise ValueError('initial fitness not bound to full source results')
    for op,parents in (('CROSS',initial),('MUTATE',[initial[2]])):
        if old.build_prompt('B',op,parents,members) != (LEGACY/'prompt_templates'/f'{op}.txt').read_text():
            raise ValueError('original prompt bytes changed')
    directory.mkdir(parents=True,exist_ok=False)
    for folder in ('results','sources','prompt_templates'):
        (directory/folder).mkdir()
        for f in (LEGACY/folder).iterdir():
            if f.is_file() and f.suffix in ('.py','.json','.txt'):
                (directory/folder/f.name).write_bytes(f.read_bytes())
    for name in ('Initial_population.json','H_context.json'):
        (directory/name).write_bytes((LEGACY/name).read_bytes())
    atomic_json(directory/'config.pending.json',config.payload())
    plan = {**{k:v for k,v in legacy_plan.items() if k != 'pins'},'version':config.experiment_version,
        'scientific_protocol':old.VERSION,'legacy_preparation':str(LEGACY),
        'budget_policy':config.request_budget['version'],'real_execution_authorized':False,
        'start_condition':('new B2-1 user confirmation; this run is single-writer; no historical/global budget or cross-worktree gate' if batch_retries else
            'new B2-1 user confirmation; peer explicitly stopped/completed and released; pinned local cumulative history valid'),
        'identity_changes':changes,'legacy_plan_sha256':old.common.sha(LEGACY/'Plan.json'),
        'peer_terminal_audit_digest':digest(peer_audit)}
    paths = {ROOT/n for n in legacy_plan['pins']} | {LEGACY/'Plan.json',Path(__file__).resolve(),
        ROOT/'tests/test_h01_weight_local.py',ROOT/'code/fjsp_usage/usage_v2/fixed_h.py'}
    if batch_retries:
        plan.pop('peer_run',None)
        plan.pop('peer_terminal_audit_digest',None)
        plan.update(new_model_request_cap=30,new_logical_candidate_cap=20,new_api_attempt_cap=30,
                    per_candidate_attempt_cap=3,global_history_gate=False,cross_worktree_lock_gate=False)
        paths |= {ROOT/'code/fjsp_usage/research_real/attempt_budget.py',ROOT/'tests/test_h01_attempt_retries.py'}
    paths |= {p for p in directory.rglob('*') if p.is_file()}
    plan['pins'] = {str(p.relative_to(ROOT)):old.common.sha(p) for p in sorted(paths)}
    atomic_json(directory/'Plan.json',plan)
    if not batch_retries:atomic_json(directory/'Peer_terminal_audit.json',peer_audit)
    # Engineering preview, explicitly not an execution-protocol H_frozen asset.
    atomic_json(directory/'H_source_binding.json',wrapper(config,digest(plan),H))
    atomic_json(directory/('B2_0_1_readiness.json' if batch_retries else 'B2_0_readiness.json'),{
        'stage':'B2-0.1 engineering preparation only' if batch_retries else 'B2-0 engineering preparation only',
        'new_model_requests':0,'new_train_evaluations':0,'real_execution_authorized':False,
        'science_equal':True,'prompt_bytes_equal':True,'H_and_data_equal':True,
        'historical_request_slots':None if batch_retries else peer_audit['history']['historical_request_slots'],
        'global_history_gate':not batch_retries,'cross_worktree_lock_gate':not batch_retries,
        'planned_api_attempt_cap':30 if batch_retries else 20,'logical_candidate_cap':20,
        'per_candidate_attempt_cap':3 if batch_retries else 1,
        'actual_cost':None,'next':'B2-1 requires new explicit user confirmation'})


def pins_check(directory):
    plan = old.common.read(directory/'Plan.json')
    if plan['version'] not in (VERSION,BATCH_VERSION) or plan['scientific_protocol'] != old.VERSION:
        raise ValueError('new B2 protocol identity required')
    for name,sha in plan['pins'].items():
        if old.common.sha(ROOT/name) != sha:
            raise ValueError('new frozen input/source changed: '+name)
    config = Config.from_dict(old.common.read(directory/'config.pending.json'))
    if config.experiment_version != plan['version']:raise ValueError('plan/config version differs')
    return plan


def check(directory):
    plan = pins_check(directory)
    config = Config.from_dict(old.common.read(directory/'config.pending.json'))
    old.check_evaluation_runtime(plan)
    dataset,H,members = data_and_h(config,directory)
    if dataset.metadata != plan['dataset'] or [m.key for m in members] != plan['H_order']:
        raise ValueError('science identity changed')
    if old.common.read(directory/'H_source_binding.json') != wrapper(config,digest(plan),H):
        raise ValueError('frozen H wrapper changed')
    if config.experiment_version != BATCH_VERSION:
        audit = audit_peer(directory,config,plan)
        if audit != old.common.read(directory/'Peer_terminal_audit.json') or digest(audit) != plan['peer_terminal_audit_digest']:
            raise BudgetStop('peer handoff evidence changed; explicit new binding required')
    return plan,config,members


def require_execution(directory):
    plan,config,members = check(directory)
    auth_path = directory/'B2_1_authorization.json'
    if not auth_path.exists():
        raise BudgetStop('B2-1 not authorized: engineering acceptance must not execute grid/search')
    auth = old.common.read(auth_path)
    expected = {'stage':'B2-1','approved':True,'person':'DDXQL',
                'plan_sha256':old.common.sha(directory/'Plan.json'),'max_new_requests':20}
    if config.experiment_version == BATCH_VERSION:
        expected.pop('max_new_requests');expected.update(logical_candidate_cap=20,api_attempt_cap=30,per_candidate_attempt_cap=3)
    if auth != expected:
        raise BudgetStop('B2-1 authorization binding differs')
    payload = config.payload();payload['real_requests_authorized'] = True
    return plan,Config.from_dict(payload),members


def client(directory,config,verify):
    from fjsp_usage.research_real.real_transport import JsonCandidateTransport
    from fjsp_usage.usage_v2.access import WireRecorder
    config.check_dispatch()
    return WireRecorder(JsonCandidateTransport(config),directory/'wire_responses',verify)


def make_search(directory,config,plan,members,transport,evaluator):
    # Reuse the same checkpoint, source-key dedup, per-generation selection and
    # durable request journal. The new ledger context includes the frozen plan.
    protocol = json.loads(json.dumps({'version':config.experiment_version,'config':config.payload(),'plan_sha256':old.common.sha(directory/'Plan.json')}))
    path = directory/'protocol.json'
    if path.exists() and old.common.read(path) != protocol:
        raise ValueError('registered protocol changed')
    atomic_json(path,protocol)
    context = digest(protocol)
    if config.experiment_version == BATCH_VERSION:
        return batch_search(directory,config,plan,members,transport,evaluator,context)
    ledger = BudgetLedger(directory/'budget.json',config,context)
    searcher = old.WeightSearch(directory/'r501/B',arm='B',config=config.u_search(501),members=members,
        evaluator=evaluator,transport=transport,context=context,
        initial=old.common.read(directory/'Initial_population.json'),init_phase='r501/init',
        search_phase=old.PHASE,ledger=ledger,experiment=config,training_names=plan['names'])
    return searcher,ledger


class BatchWeightSearch(old.WeightSearch):
    """Same Search engine and WeightSearch operators; only the journal changes."""
    def __init__(self,directory,*,experiment,training_names,**kwargs):
        from fjsp_usage.research.evolution import Search
        from fjsp_usage.research_real.attempt_budget import AttemptJournal
        self.experiment,self.training_names = experiment,tuple(training_names)
        Search.__init__(self,directory,**kwargs)
        self.evolution_requests = AttemptJournal(self.directory/'budgeted_evolution_requests.json',
            config=experiment,context=kwargs['context'],phase=old.PHASE,transport=kwargs['transport'])
        self.ledger = self.evolution_requests

    def _prepare(self,*,initial):
        if self.state['inflight'] is None:self.evolution_requests.ensure_capacity()
        super()._prepare(initial=initial)

    def report(self):
        return {**super().report(),'api_attempt_budget':self.evolution_requests.summary()}


def batch_search(directory,config,plan,members,transport,evaluator,context):
    engine = BatchWeightSearch(directory/'r501/B',arm='B',config=config.u_search(501),members=members,
        evaluator=evaluator,transport=transport,context=context,
        initial=old.common.read(directory/'Initial_population.json'),experiment=config,training_names=plan['names'])
    return engine,engine.evolution_requests


def execute(directory,stage,env_file=None):
    plan,config,members = require_execution(directory)
    if stage == 'grid':
        # The old grid routine can be reused with its identity/history readers
        # redirected; its once-only started markers and evaluator stay intact.
        from unittest.mock import patch
        dataset = StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
        H = old.common.read(directory/'H_source_binding.json')
        with patch.object(old,'pins_check',side_effect=pins_check), \
             patch.object(old,'check_history',side_effect=lambda d:check(d) if config.experiment_version==BATCH_VERSION else audit_peer(d,config,plan)), \
             patch.object(old.common,'inputs',return_value=(None,dataset,H,None,members,plan['names'])):
            old.grid_evaluate(directory)
        return
    if not (directory/'Grid_complete.json').exists():
        raise BudgetStop('reference grid must be completed first')
    from fjsp_usage.research_real.leafapi import load_local_key, KEY_ENV
    import os
    if not env_file:
        raise ValueError('--env-file required for B2-1 only')
    os.environ[KEY_ENV] = load_local_key(env_file)
    transport = client(directory,config,lambda:check(directory))
    dataset = StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
    instances = dataset.load('train')
    searcher,ledger = make_search(directory,config,plan,members,transport,
        lambda c:old.evaluate_weight(c,members,instances,plan['names']))
    _,source,_ = data_and_h(config,directory)
    bound_H = wrapper(config,digest(old.common.read(directory/'protocol.json')),source)
    if (directory/'H_frozen.json').exists() and old.common.read(directory/'H_frozen.json') != bound_H:
        raise ValueError('execution H binding changed')
    atomic_json(directory/'H_frozen.json',bound_H)
    try:
        atomic_json(directory/'Search_status.json',searcher.run())
    except Exception as exc:
        atomic_json(directory/'Search_status.json',{**searcher.report(),'stop_reason':transport.redact(str(exc))[:500]})
        raise
    finally:
        atomic_json(directory/'Budget_summary.json',ledger.summary())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=('prepare','check','grid','search','report'))
    p.add_argument('--run-dir',type=Path);p.add_argument('--env-file',type=Path)
    p.add_argument('--batch-retries',action='store_true',help='prepare a NEW B2-0.1 20/30/3 batch')
    args = p.parse_args();directory = (args.run_dir or (BATCH_DEFAULT if args.batch_retries else DEFAULT)).resolve()
    if directory.parent != ROOT/'runs' or directory == LEGACY:
        p.error('a new independent runs/ directory is required')
    if args.stage == 'prepare':
        prepare(directory,batch_retries=args.batch_retries)
    elif args.stage == 'check':
        plan,config,_ = check(directory)
        print(json.dumps({'status':'engineering ready; B2-1 remains unauthorized','version':config.experiment_version,
            'science_equal':True,'logical_candidate_cap':20,'api_attempt_cap':config.request_budget.get('api_attempt_cap',20),
            'per_candidate_attempt_cap':config.request_budget.get('per_candidate_attempt_cap',1),
            'actual_cost':None},ensure_ascii=False))
    elif args.stage == 'report':
        from tools.h01_weight_report import report
        report(directory,plan_reader=pins_check,version=pins_check(directory)['version'])
    else:
        with RunLock(directory):execute(directory,args.stage,args.env_file)


if __name__ == '__main__':main()
