"""Independent B1-NS preparation / authorized run; science reuses B1-1C intact."""
import argparse
from dataclasses import dataclass, replace
import json
from pathlib import Path

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_result
from fjsp_usage.research_real.attempt_budget import CIRCUIT_VERSION
from fjsp_usage.research_real.budget import BudgetStop, validate_usage
from fjsp_usage.research_real.config import ExperimentConfig, fingerprint
from fjsp_usage.research_real.initialization import initialization_prompt
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.real_transport import JsonCandidateTransport, TransportError
from fjsp_usage.usage_v2.fixed_h import validate_declaration
from tools import b1_usage_local as b1
from tools import b1_usage_prompts as prompts
from tools.t1_d2_prompt_ab import TimedRecorder

ROOT = b1.ROOT
SOURCE = b1.DEFAULT
SOURCE_SHA = 'd5ec72d53583c8dd5829b6a9d8f002511956c346127aad99348e1485f8e3e898'
VERSION = 'B1-NS-full-H-free-seed501-k2-v1-20261022'
DEFAULT = ROOT/'runs/b1-ns-full-h-free-seed501-k2-v1-20261022'
ENV_FILE = (ROOT.parent/'FJSP-Heuristic-Research/.env.leafapi.local').resolve()
POLICY = {**b1.POLICY, 'version': CIRCUIT_VERSION, 'protocol_error_circuit_threshold': 3}
ENGINEERING = {'code/fjsp_usage/research_real/attempt_budget.py',
    'code/fjsp_usage/research_real/budget.py', 'code/fjsp_usage/research_real/real_transport.py',
    'code/fjsp_usage/usage_v2/access.py', 'tools/b1_usage_local.py'}
TOOLS = ('tools/b1_nonstream_local.py', 'tools/b1_usage_local.py', 'tools/b1_usage_prompts.py',
    'tools/h01_weight_local.py', 'tools/h01_weight_search.py', 'tools/h01_weight_report.py',
    'tools/usage_mechanism_ablation.py', 'tools/t1_d1_diagnostic.py', 'tools/t1_d2_prompt_ab.py')
read, sha = b1.read, b1.sha


def baseline():
    if sha(SOURCE/'Protocol.json') != SOURCE_SHA: raise ValueError('B1-1C baseline protocol changed')
    p = read(SOURCE/'Protocol.json')
    if p['config'] != read(SOURCE/'config.pending.json'): raise ValueError('B1 baseline config differs')
    return p


@dataclass(frozen=True)
class Config(ExperimentConfig):
    experiment_version: str = VERSION
    fixed_h_source: dict | None = None

    def search_arms(self): return ('B',)

    def default_phase_caps(self): return {'r501/init':20,'r501/B':20}

    def __post_init__(self):
        super().__post_init__(); validate_declaration(self)
        if (self.experiment_version != VERSION or self.request_budget != POLICY
                or self.population_size != 5 or self.cross_parents != 2 or self.mutation_parents != 1
                or self.seeds != (501,) or self.generations != 2 or self.attempts_per_generation != 10
                or self.initialization_cap != 20 or self.total_request_cap != 40 or self.H_size != 10
                or self.instance_timeout != 15 or self.training_diagnostics
                or self.provider.stream_response is not False):
            raise ValueError('frozen B1-NS science and 40/60/3 request policy required')
        if self.mode == 'real':
            old = baseline()['config']
            expected = {**old, 'experiment_version': VERSION, 'request_budget': POLICY,
                'real_requests_authorized': self.real_requests_authorized,
                'provider': {**old['provider'], 'stream_response': False}}
            if digest(self.payload()) != digest(expected):
                raise ValueError('B1 science/model/prompt/evaluation parameter change forbidden')


def pending_config():
    old = baseline()['config']
    return Config.from_dict({**old, 'experiment_version': VERSION, 'request_budget': POLICY,
        'real_requests_authorized': False, 'provider': {**old['provider'], 'stream_response': False}})


def directory_path(directory):
    directory = Path(directory).resolve()
    if directory.parent != ROOT/'runs' or not directory.name.startswith('b1-ns-'):
        raise ValueError('new registered b1-ns-* run required')
    for n in ('Protocol.json','Protocol.sha256','config.pending.json','H_source_binding.json',
              'B1_NS_authorization.json','r501/B','wire_responses','received_responses','send_times',
              'Search_status.json','Final_or_partial_population.json','B1_NS_training_report.json'):
        if not (directory/n).resolve().is_relative_to(directory): raise ValueError('B1-NS path escape')
    return directory


class CompleteNonstreamTransport:
    """Strict profile + evidence adapter; the public client alone sends HTTP."""
    def __init__(self, inner, directory):
        self.inner, self.directory = inner, Path(directory)
        self.config, self.secret, self.redact = inner.config, inner.secret, inner.redact
        self.identity = digest({'inner': inner.identity, 'profile': VERSION})
        if self.config.provider.stream_response: raise ValueError('nonstream client required')

    def preflight(self, prompt): return self.inner.preflight(prompt)

    @staticmethod
    def protocol_evidence(metadata):
        # v2-T1's legacy flag name feeds its existing GENERIC protocol counter.
        # protocol_kind explicitly prevents reporting this as an observed SSE.
        return {**metadata, 'protocol_kind': 'nonstream_json',
                'stream_protocol_anomaly': True, 'failure_class': 'protocol_incompatible'}

    def dispatch(self, key, prompt, *, kind='U', on_sent=lambda:None):
        try: reply = self.inner.dispatch(key, prompt, kind=kind, on_sent=on_sent)
        except Exception as exc:
            m = getattr(exc, 'metadata', {}) or {}
            if (m.get('http_status') == 200 and not m.get('temporary_network_failure')
                    and m.get('failure_class') not in ('permanent','temporary')
                    and not str(exc).startswith('total network deadline exceeded')):
                m = self.protocol_evidence(m)
            if m.get('model') is not None and m['model'] != self.config.provider.expected_response_model:
                m = {**m, 'global_safety_error': 'response_model_identity_mismatch'}
            exc.metadata = m; raise
        from hashlib import sha256
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_json(self.directory/(sha256(key.encode()).hexdigest()+'.json'), reply)
        m = reply.get('metadata') or {}
        if (validate_usage(reply.get('usage')) is None or m.get('finish_reason') != 'stop'
                or m.get('model') != self.config.provider.expected_response_model
                or not isinstance(m.get('id'), str) or not m['id']):
            exc = TransportError('complete text/usage/stop/locked response identity required')
            exc.usage = reply.get('usage'); exc.metadata = self.protocol_evidence(m)
            if m.get('model') != self.config.provider.expected_response_model:
                exc.metadata['global_safety_error'] = 'response_model_identity_mismatch'
            raise exc
        return reply


class NSSearch(b1.B1Search):
    request_phase = VERSION+'/r501/B'

    def _attempt(self):
        super()._attempt()
        latest = self.ledger.data['requests'][self.state['attempts'][-1]['id']]
        a = self.ledger.data['api_attempts'][latest['attempt_ids'][-1]]
        reason = (a.get('metadata') or {}).get('global_safety_error')
        if reason and not self.ledger.data['halt_reason']:
            self.ledger.data['halt_reason'] = reason; self.ledger.save()
        if self.ledger.data['halt_reason']:
            raise BudgetStop(self.ledger.data['halt_reason'])  # Candidate/checkpoint already durable.

    def report(self):
        return {**super().report(), 'experiment_version': VERSION, 'stream_response': False,
            'request_identity': 'journal identity + independently namespaced attempt ID',
            'no_D4_or_other_U_injection': True}


def prepare(directory):
    directory = directory_path(directory)
    if directory.exists(): raise ValueError('never overwrite a preparation or old batch')
    old = baseline(); config = pending_config(); changes = []
    for name, expected in old['pins'].items():
        actual = sha(ROOT/name)
        if actual != expected:
            if name not in ENGINEERING: raise ValueError('scientific frozen input changed: '+name)
            changes.append({'file': name, 'old_sha256': expected, 'new_sha256': actual,
                'classification': 'transport/budget/evidence/receipt namespace; science unchanged'})
    dataset, H, members = b1.b2.data_and_h(config, directory)
    if (dataset.metadata != old['dataset'] or list(dataset.names['train']) != old['train_names']
            or [m.key for m in members] != old['H_order'] or H != read(SOURCE/'H_source_binding.json')):
        raise ValueError('original H/data identity differs')
    directory.mkdir()
    atomic_json(directory/'config.pending.json', config.payload())
    atomic_json(directory/'H_source_binding.json', H)
    for op in ('I1','CROSS','MUTATE'):
        raw = (SOURCE/'prompt_templates'/f'{op}.txt').read_bytes()
        path = directory/'prompt_templates'/f'{op}.txt'; path.parent.mkdir(exist_ok=True); path.write_bytes(raw)
    first = initialization_prompt(prompts.build_prompt('B','I1',[],members), [], 0,
        instruction=prompts.NOVELTY, interface_version='U-usage-v2-select-or-mix-20261012')
    original_first = (SOURCE/'r501/B/prompts/B_init_000000').read_bytes()
    if first.encode() != original_first: raise ValueError('initial full Prompt bytes differ')
    (directory/'Initial_request_000000.txt').write_bytes(original_first)
    atomic_json(directory/'Engineering_rebind.json', changes)
    implementation = fingerprint(ROOT)
    pins = {**implementation['files'], **{n: sha(ROOT/n) for n in TOOLS},
            **{str(f.relative_to(ROOT)):sha(f) for f in directory.rglob('*') if f.is_file()}}
    protocol = {**{k: old[k] for k in ('dataset','train_names','H_order','fitness','allowed_modes','timing',
        'initialisation','selection','data_boundary','comparison_limit')},
        'version': VERSION, 'stage': 'B1-NS', 'run_directory': str(directory), 'config': config.payload(),
        'source_B1_protocol_sha256': SOURCE_SHA, 'pins': pins, 'implementation': implementation,
        'prompt_pack': prompts.manifest(), 'cross_parents': 2,
        'transport_delta': {'stream_response': [True,False], 'stream_options': 'omitted',
            'request_budget_version': [b1.POLICY['version'], CIRCUIT_VERSION],
            'protocol_error_circuit_threshold': 3, 'unknown_delivery': 'charged; halt without retry',
            'complete_profile': 'strict nonempty id/locked model/stop/validated usage',
            'namespace': NSSearch.request_phase, 'protocol_counter_legacy_flag': 'stream_protocol_anomaly; protocol_kind=nonstream_json'},
        'credential_source': str(ENV_FILE), 'real_execution_authorized': False,
        'new_P0': 'free original INIT only; no old B1/B2/D4 or handwritten seeds', 'actual_cost': None}
    atomic_json(directory/'Protocol.json', protocol)
    (directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    atomic_json(directory/'Authorization.template.json', approval(directory, False))
    return check(directory)


def check(directory):
    directory = directory_path(directory); p = read(directory/'Protocol.json')
    if (sha(directory/'Protocol.json') != (directory/'Protocol.sha256').read_text().strip()
            or p['version'] != VERSION or p['run_directory'] != str(directory)
            or p['source_B1_protocol_sha256'] != SOURCE_SHA or p['prompt_pack'] != prompts.manifest()):
        raise ValueError('B1-NS frozen protocol differs')
    for n,h in p['pins'].items():
        if sha(ROOT/n) != h: raise ValueError('frozen input/code differs: '+n)
    config = Config.from_dict(read(directory/'config.pending.json'))
    if digest(config.payload()) != digest(p['config']) or fingerprint(ROOT) != p['implementation']:
        raise ValueError('B1-NS runtime/config differs')
    dataset,H,members = b1.b2.data_and_h(config,directory)
    if (dataset.metadata != p['dataset'] or list(dataset.names['train']) != p['train_names']
            or [m.key for m in members] != p['H_order'] or H != read(directory/'H_source_binding.json')):
        raise ValueError('B1-NS frozen H/data differs')
    return p,config,dataset,members


def approval(directory, approved):
    return {'stage':'B1-NS','approved':approved,'person':'DDXQL',
        'protocol_sha256':sha(Path(directory)/'Protocol.json'),'cross_parents':2,
        'logical_candidate_cap':40,'api_attempt_cap':60,'per_candidate_attempt_cap':3,
        'protocol_error_circuit_threshold':3,'unknown_cost_risk_accepted':approved}


def require_execution(directory):
    directory=directory_path(directory);auth=directory/'B1_NS_authorization.json'
    if not auth.exists(): raise BudgetStop('B1-NS not authorized; offline engineering only')
    if read(auth) != approval(directory,True): raise BudgetStop('B1-NS approval scope differs')
    p,c,d,m=check(directory)
    return p,replace(c,real_requests_authorized=True),d,m


def training_evaluator(dataset, members, names):
    names=tuple(names)
    if len(names)!=21 or tuple(dataset.names['train'])!=names:
        raise ValueError('exact frozen ordered train21 required')
    instances=dataset.load('train')
    if len(instances)!=21: raise ValueError('incomplete train21 load')
    from tools.usage_mechanism_ablation import evaluate_with_schedules
    def evaluate(candidate):
        dataset.verify('train')
        return check_result(evaluate_with_schedules(candidate,members,instances,names,
            timeout=15,diagnostics=False,allowed_modes=(0,1)),names)
    return evaluate


def run(directory, env_file):
    p,c,dataset,members=require_execution(directory)
    if env_file is None or Path(env_file).resolve()!=ENV_FILE: raise ValueError('original credential source required')
    from fjsp_usage.research_real.leafapi import load_local_key,KEY_ENV
    import os
    os.environ[KEY_ENV]=load_local_key(env_file)
    profile=CompleteNonstreamTransport(JsonCandidateTransport(c),directory/'received_responses')
    transport=TimedRecorder(profile,directory/'wire_responses',lambda:check(directory))
    evaluator=training_evaluator(dataset,members,p['train_names'])
    engine=NSSearch(directory/'r501/B',experiment=c,training_names=p['train_names'],
        verify=lambda:check(directory),arm='B',config=c.u_search(501),members=members,
        evaluator=evaluator,transport=transport,context=sha(directory/'Protocol.json'))
    try: engine.run()
    except BudgetStop as exc:
        atomic_json(directory/'Stop_record.json',{'reason':str(exc),'no_automatic_resume_or_budget_reset':True})
    finally:
        atomic_json(directory/'Search_status.json',engine.report())
        atomic_json(directory/'Final_or_partial_population.json',engine.export_rows())


def report(directory):
    p,c,_,_=check(directory);path=directory/'Search_status.json'
    status=read(path) if path.exists() else {'phase':'not_started','real_requests':0,'formal_evaluations':0}
    result={'protocol_sha256':sha(directory/'Protocol.json'),'experiment_version':VERSION,
        'status':status,'stream_response':False,'request_budget':c.request_budget,
        'stop_record':read(directory/'Stop_record.json') if (directory/'Stop_record.json').exists() else None,
        'training_only':True,'actual_cost':None,'no_diagnostic_U_in_population':True}
    atomic_json(directory/'B1_NS_training_report.json',result);return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=('prepare','check','run','report'))
    p.add_argument('--run-dir',type=Path,default=DEFAULT);p.add_argument('--env-file',type=Path)
    a=p.parse_args();directory=directory_path(a.run_dir)
    if a.stage=='prepare':prepare(directory)
    elif a.stage=='check':
        _,c,_,_=check(directory);print({'protocol_sha256':sha(directory/'Protocol.json'),
            'authorized':(directory/'B1_NS_authorization.json').exists(),'stream':c.provider.stream_response})
    elif a.stage=='report':
        with RunLock(directory):print(report(directory)['status']['phase'])
    else:
        require_execution(directory)
        with RunLock(directory):run(directory,a.env_file)


if __name__=='__main__':main()
