"""Independent B1 adapter. prepare/check/report offline; run needs new approval.

No edits to old protocols, core evolution, execution, H or financial mechanisms.
"""
import argparse
from dataclasses import dataclass, asdict
import json
from pathlib import Path
from statistics import fmean

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.evolution import Search
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.config import ExperimentConfig, fingerprint
from fjsp_usage.research_real.attempt_budget import AttemptJournal
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.assets import checked_candidate
from fjsp_usage.research_real.initialization import initialization_prompt
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.usage_v2.fixed_h import validate_declaration
from fjsp_usage.usage_v2.search import UsageSearch
from tools import b1_usage_prompts as prompts
from tools import h01_weight_local as b2

ROOT = b2.ROOT
VERSION = 'B1-full-H-free-search-batch-v1-20261021'
DEFAULT = ROOT/'runs/b1-full-h-free-seed501-k2-v1-20261021'
POLICY = {'version':'batch-api-attempts-v1','logical_candidate_cap':40,'api_attempt_cap':60,
          'per_candidate_attempt_cap':3,'retry_backoff_seconds':[2,5]}
read = b2.old.common.read
sha = b2.old.common.sha


@dataclass(frozen=True)
class Config(ExperimentConfig):
    experiment_version: str = VERSION
    fixed_h_source: dict | None = None

    def search_arms(self): return ('B',)

    def default_phase_caps(self): return {'r501/init':20,'r501/B':20}

    def __post_init__(self):
        super().__post_init__()
        if (self.experiment_version != VERSION or self.H_size != 10 or self.population_size != 5
                or self.cross_parents not in (2,3,5) or self.mutation_parents != 1
                or self.seeds != (501,) or self.generations != 2 or self.attempts_per_generation != 10
                or self.initialization_cap != 20 or self.total_request_cap != 40
                or self.instance_timeout != 15 or self.training_diagnostics or self.request_budget != POLICY):
            raise ValueError('independent B1 N5/k2,3,5/two-generation/40-logical-60-attempt contract required')
        validate_declaration(self)
        if self.mode=='real':
            original=read(b2.BATCH_DEFAULT/'config.pending.json')
            allowed={'experiment_version','cross_parents','initialization_cap','total_request_cap',
                     'phase_request_caps','request_budget','real_requests_authorized'}
            current=json.loads(json.dumps(self.payload()))
            if {k:v for k,v in current.items() if k not in allowed}!={k:v for k,v in original.items() if k not in allowed}:
                raise ValueError('unapproved model/data/evaluation/search parameter change from B2 source')


def pending_config(cross_parents=2):
    old = read(b2.BATCH_DEFAULT/'config.pending.json')
    return Config.from_dict({**old,'experiment_version':VERSION,'cross_parents':cross_parents,
        'initialization_cap':20,'total_request_cap':40,'phase_request_caps':{'r501/init':20,'r501/B':20},
        'request_budget':dict(POLICY),'real_requests_authorized':False})


class B1Search(UsageSearch):
    _build_prompt = staticmethod(prompts.build_prompt)

    def __init__(self,directory,*,experiment,training_names,verify=lambda:None,**kwargs):
        self.experiment,self.training_names,self.verify = experiment,tuple(training_names),verify
        directory=Path(directory);checkpoint=directory/'checkpoint.json';journal_path=directory/'batch_requests.json'
        if checkpoint.exists() and not journal_path.exists():
            state=read(checkpoint)
            if state['attempts'] or state['inflight'] or state['evaluations']:
                raise ValueError('missing batch journal; never reset consumed or uncertain attempts')
        if journal_path.exists() and not checkpoint.exists() and read(journal_path)['requests']:
            raise ValueError('orphan batch journal; checkpoint recovery must not restart P0')
        Search.__init__(self,directory,**kwargs)
        # One durable budget for BOTH initialisation and evolution; no per-stage reset.
        journal = AttemptJournal(self.directory/'batch_requests.json',config=experiment,
            context=kwargs['context'],phase='r501/B',transport=kwargs['transport'])
        self.initial_requests = self.evolution_requests = self.ledger = journal

    def _initial_prompt(self,prompt,index):
        return initialization_prompt(prompt,self.state['population'],index,
            instruction=prompts.NOVELTY,interface_version='U-usage-v2-select-or-mix-20261012')

    def _prepare(self,*,initial):
        self.verify()
        if self.state['inflight'] is None: self.ledger.ensure_capacity()
        if not initial:
            key=str(self.state['generation'])
            snapshot=[{k:r[k] for k in ('id','fitness','candidate')} for r in self.state['population']]
            pools=self.state.setdefault('generation_parent_pools',{})
            if key in pools and pools[key] != snapshot:
                raise ValueError('generation parent population changed within generation')
            pools[key]=snapshot
            self.state.setdefault('population_snapshots',{})['P'+key]=snapshot
        super()._prepare(initial=initial)
        pending=self.state['inflight'];operator=pending['operator']
        expected=0 if initial else self.config.cross_parents if operator=='CROSS' else 1
        if len(pending['parents']) != expected or len(set(pending['parents'])) != expected:
            raise ValueError('configured distinct parent count did not reach request')
        pending.update(cross_parents=self.config.cross_parents,generation=self.state['generation'],
                       expected_children=1)
        self._save()
        path=self.directory/'prompts'/pending['id'].replace('/','_')
        if path.exists() and path.read_text()!=pending['prompt']:raise ValueError('saved prompt changed')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(pending['prompt'])

    def _attempt(self):
        self.verify()
        pending=dict(self.state['inflight'])
        super()._attempt()
        self.state['attempts'][-1].update(cross_parents=self.config.cross_parents,
            generation=pending['generation'],expected_children=1)
        self.events.emit('b1_operator',**self.state['attempts'][-1]);self._save()

    def run(self,**kwargs):
        super().run(**kwargs)
        if self.state['phase']=='completed':
            self.state.setdefault('population_snapshots',{})['P'+str(self.state['generation'])]=[
                {k:r[k] for k in ('id','fitness','candidate')} for r in self.state['population']]
            self._save()
        return self.report()

    def report(self):
        requests=self.ledger.data['requests'];initial=sum('/init/' in k for k in requests)
        evaluations=[]
        for identifier,cache in self.state['evaluations'].items():
            result=cache.get('result',{});rows=result.get('instances',[])
            evaluations.append({'id':identifier,'status':cache['status'],'valid':result.get('valid'),
                'fitness':result.get('fitness'),'completed_instances':len(rows),
                'failed_instance':result.get('failed_instance'),'error_type':result.get('error_type'),
                'primary_evaluation_seconds':result.get('primary_evaluation_seconds'),
                'certified_successful_prefix_costs':{k:sum(sum(r[k]) if isinstance(r[k],list) else r[k]
                    for r in rows if k in r) for k in ('single_solve_seconds','deterministic_recheck_seconds',
                    'single_h_calls','deterministic_recheck_h_calls')},
                'failed_instance_cost_unknown':not result.get('valid',False),
                'full_result':'checkpoint.json: evaluations/'+identifier})
        return {**Search.report(self),'research_stage':'B1','cross_parents':self.config.cross_parents,
            'mutation_parents':1,'population_size':5,'initialization_requests':initial,
            'evolution_requests':len(requests)-initial,'api_attempt_budget':self.ledger.summary(),
            'population_snapshots':self.state.get('population_snapshots',{}),
            'lineage':self.state['attempts'],'mode':self.experiment.mode,
            'all_evaluations':evaluations,
            'mean_population_fitness':fmean(r['fitness'] for r in self.state['population']) if self.state['population'] else None,
            'claim':'training exploration only; no single-factor B1/B2 performance attribution'}

    def export_rows(self):
        # Batch receipts explicitly refer to the FIRST accepted attempt, not a legacy ledger record.
        rows=[]
        for row in self.state['population']:
            record=self.ledger.data['requests'][row['id']]
            attempt=self.ledger.data['api_attempts'][record['accepted_attempt_id']]
            if record['status']!='completed' or attempt['status']!='completed' or not attempt['send_confirmed']:
                raise ValueError('missing confirmed accepted response provenance')
            c=checked_candidate(row['candidate'],'U')
            parsed=self._parse_candidate(record['text'])
            if parsed.key!=c.key:raise ValueError('accepted response/source differs')
            rows.append({**row,'training_result':self.state['evaluations'][row['id']]['result'],
                'batch_provenance':{'mode':self.experiment.mode,'journal_identity':self.ledger.identity,
                    'logical_id':row['id'],'accepted_attempt_id':record['accepted_attempt_id'],
                    'response_id':record['response_id'],'response_sha256':digest(record['text']),
                    'model':self.experiment.provider.model,'cross_parents':self.config.cross_parents}})
        return rows


def prepare(directory,cross_parents=2):
    if directory.parent!=ROOT/'runs' or directory.exists():raise ValueError('new independent runs child required')
    config=pending_config(cross_parents)
    dataset,H,members=b2.data_and_h(config,directory)  # provenance/samples only; never schedules train.
    b2_plan=read(b2.BATCH_DEFAULT/'Plan.json')
    if dataset.metadata!=b2_plan['dataset'] or [m.key for m in members]!=b2_plan['H_order']:
        raise ValueError('fixed H/data identity differs')
    directory.mkdir()
    atomic_json(directory/'config.pending.json',config.payload())
    atomic_json(directory/'H_source_binding.json',H)
    for op,parents in [('I1',[]),('CROSS',[{'id':f'PREVIEW/{i}','candidate':{'description':'MOCK prompt preview only; not P0',
        'code':'PREVIEW SOURCE ONLY'}} for i in range(cross_parents)]),('MUTATE',[{'id':'PREVIEW/0','candidate':{
        'description':'MOCK prompt preview only; not P0','code':'PREVIEW SOURCE ONLY'}}])]:
        path=directory/'prompt_templates'/(op+'.txt');path.parent.mkdir(exist_ok=True)
        path.write_text(prompts.build_prompt('B',op,parents,members))
    pins={**b2_plan['pins'],**{str(p.relative_to(ROOT)):sha(p) for p in directory.rglob('*') if p.is_file()}}
    pins.update({n:sha(ROOT/n) for n in ('tools/b1_usage_local.py','tools/b1_usage_prompts.py',
        'tools/usage_mechanism_ablation.py','tests/test_b1_usage_local.py')})
    protocol={'version':VERSION,'mode':'real','stage':'B1','cross_parents':cross_parents,
        'config':config.payload(),'dataset':dataset.metadata,'train_names':list(dataset.names['train']),
        'H_order':[m.key for m in members],'source_B2_plan_sha256':sha(b2.BATCH_DEFAULT/'Plan.json'),
        'implementation':fingerprint(ROOT),'prompt_pack':prompts.manifest(),'pins':pins,
        'fitness':'complete train21 mean(-Cmax/unrounded-V5-LB)','allowed_modes':[0,1],
        'timing':'first solve and deterministic recheck share 15 seconds per instance; no observation replay',
        'initialisation':'free LLM, no inherited/manual U; stop at five complete valid AST-unique U or twenty logical slots',
        'selection':'original select_parents and ranked parent+child top5; five CROSS and five MUTATE each generation',
        'B2_differences':{'H_space':'H0..H9, not just H0/H1','initialisation':'new free LLM U, not manual alpha pool',
            'cross_parents':{'B2':5,'B1':cross_parents},'budget':'initialisation<=20 plus evolution20; shared40logical/60attempt',
            'prompt':'new B1 I1 includes all H and SELECT/MIX; crossover/mutation instructions reused, no numeric fitness'},
        'data_boundary':'train21 only; validation11 development-exposed; test28 consumed; no selection using holdouts',
        'comparison_limit':'B1/B2 differ in H space, initialisation and crossover count; not isolated causal effects',
        'real_execution_authorized':False}
    atomic_json(directory/'Protocol.json',protocol)
    (directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    for p in directory.rglob('*'):
        if p.is_file():p.chmod(0o444)
    return protocol


def check(directory):
    if directory.parent!=ROOT/'runs':raise ValueError('registered project run required')
    protocol=read(directory/'Protocol.json')
    if sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip() or protocol['version']!=VERSION:
        raise ValueError('protocol identity changed')
    for n,h in protocol['pins'].items():
        if sha(ROOT/n)!=h:raise ValueError('frozen file changed: '+n)
    config=Config.from_dict(read(directory/'config.pending.json'))
    if (protocol['config']!=json.loads(json.dumps(config.payload())) or protocol['cross_parents']!=config.cross_parents
            or protocol['prompt_pack']!=prompts.manifest() or protocol['implementation']!=fingerprint(ROOT)
            or protocol['source_B2_plan_sha256']!=sha(b2.BATCH_DEFAULT/'Plan.json')):
        raise ValueError('config/source/runtime differs')
    dataset,H,members=b2.data_and_h(config,directory)
    if (dataset.metadata!=protocol['dataset'] or list(dataset.names['train'])!=protocol['train_names']
            or [m.key for m in members]!=protocol['H_order'] or H!=read(directory/'H_source_binding.json')):
        raise ValueError('fixed H or data differs')
    return protocol,config,dataset,members


def require_execution(directory):
    # Authorization precedes evaluator creation, data loading, credentials and provider construction.
    auth=directory/'B1_1_authorization.json'
    if not auth.exists():raise BudgetStop('B1-1 not authorized; engineering and Mock only')
    protocol,config,dataset,members=check(directory)
    expected={'stage':'B1-1','approved':True,'person':'DDXQL','protocol_sha256':sha(directory/'Protocol.json'),
        'cross_parents':config.cross_parents,'logical_candidate_cap':40,'api_attempt_cap':60,'per_candidate_attempt_cap':3}
    if read(auth)!=expected or read(auth).get('approved') is not True:raise BudgetStop('B1 scope approval differs')
    payload=config.payload();payload['real_requests_authorized']=True
    return protocol,Config.from_dict(payload),dataset,members


def run(directory,env_file):
    protocol,config,dataset,members=require_execution(directory)
    if not env_file:raise ValueError('explicit local credential file required for authorized execution only')
    from fjsp_usage.research_real.leafapi import load_local_key, KEY_ENV
    import os
    os.environ[KEY_ENV]=load_local_key(env_file)
    transport=b2.client(directory,config,lambda:check(directory))
    instances=dataset.load('train')
    from tools.usage_mechanism_ablation import evaluate_with_schedules
    from fjsp_usage.research_real.assets import check_result
    def evaluate(c):
        dataset.verify('train')
        return check_result(evaluate_with_schedules(c,members,instances,dataset.names['train'],
            timeout=15,diagnostics=False,allowed_modes=(0,1)),dataset.names['train'])
    engine=B1Search(directory/'r501/B',experiment=config,training_names=dataset.names['train'],
        verify=lambda:check(directory),arm='B',config=config.u_search(501),members=members,
        evaluator=evaluate,transport=transport,context=sha(directory/'Protocol.json'))
    try:engine.run()
    finally:
        atomic_json(directory/'Search_status.json',engine.report())
        atomic_json(directory/'Final_or_partial_population.json',engine.export_rows())


def report(directory):
    protocol,config,_,_=check(directory)
    path=directory/'Search_status.json'
    result=read(path) if path.exists() else {'mode':'real','phase':'not_started','cross_parents':config.cross_parents,
        'real_requests':0,'formal_evaluations':0}
    atomic_json(directory/'B1_training_report.json',{'protocol_sha256':sha(directory/'Protocol.json'),
        'cross_parents':config.cross_parents,'status':result,'comparison_limit':protocol['comparison_limit']})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=('prepare','check','run','report'))
    p.add_argument('--run-dir',type=Path,default=DEFAULT)
    p.add_argument('--cross-parents',type=int,choices=(2,3,5),default=2)
    p.add_argument('--env-file',type=Path)
    a=p.parse_args();directory=a.run_dir.resolve()
    if a.stage=='prepare':prepare(directory,a.cross_parents)
    elif a.stage=='check':
        _,c,_,_=check(directory);print({'cross_parents':c.cross_parents,'protocol_sha256':sha(directory/'Protocol.json'),
            'authorization_present':(directory/'B1_1_authorization.json').exists(),'checkpoint_present':(directory/'r501/B/checkpoint.json').exists()})
    elif a.stage=='run':
        require_execution(directory)
        with RunLock(directory):run(directory,a.env_file)
    else:
        with RunLock(directory):print(report(directory)['phase'])


if __name__=='__main__':main()
