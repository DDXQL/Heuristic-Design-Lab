"""Training-only paired controller with existing journals, H and quota gates."""
import json
from dataclasses import asdict
from pathlib import Path
from statistics import fmean
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.workflow import Workflow
from fjsp_usage.research_real.assets import checked_candidate,check_seal,check_result
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.runtime import evaluate
from fjsp_usage.research_real.training_report import attempt_categories
from .config import ARMS,protocol
from .search import UsageSearch
from . import VERSION

class UsageWorkflow(Workflow):
    _protocol=staticmethod(protocol)

    def h_asset(self):
        if self.config.mode=='real':return super().h_asset()
        asset=self.read('Handwritten_H_fixture.json','Handwritten_H_fixture')
        members=tuple(checked_candidate(m,'h') for m in asset['members'])
        if len(members)!=self.config.H_size:raise ValueError('fixture H size mismatch')
        return asset,members

    def train_eval(self,candidate,members,*,allowed_modes=(0,)):
        self.dataset.verify('train')
        if self._train is None:self._train=self.dataset.load('train')
        return check_result(evaluate(candidate,members,self._train,self.dataset.names['train'],
            timeout=self.config.instance_timeout,diagnostics=self.config.training_diagnostics,
            allowed_modes=allowed_modes),self.dataset.names['train'])

    def search_engine(self,folder,arm,members,search_config,init_phase,search_phase,initial=None):
        allowed=self.config.allowed_modes(arm)
        return UsageSearch(self.directory/folder,arm=arm,config=search_config,members=members,
            evaluator=lambda c:self.train_eval(c,members,allowed_modes=allowed),transport=self.client(),
            context=self.context,kind='U',initial=initial,init_phase=init_phase,search_phase=search_phase,
            ledger=self.ledger,experiment=self.config,training_names=self.dataset.names['train'])

    def population(self,name,kind,H_hash):
        asset,rows=super().population(name,kind,H_hash)
        for row in rows:
            c=checked_candidate(row['candidate'],'U')
            if getattr(c,'interface_version',None)!=VERSION or c.member_count!=self.config.H_size:
                raise ValueError('population usage interface or ordered H size mismatch')
        return asset,rows

    def initialize_u(self,seed,*,max_new_requests=None):
        self.assert_current()
        if type(seed) is not int or seed not in self.config.seeds:raise ValueError('undeclared seed')
        H,members=self.h_asset();repeat=f'r{seed}';name=repeat+'/Shared_initial.json'
        if (self.directory/name).exists():return {'status':'initialized','asset':self.population(name,'Shared_initial',H['artifact_sha256'])[0]}
        status_name=repeat+'/Initialization_status.json'
        if (self.directory/status_name).exists():
            status=self.read(status_name,'Initialization_status')
            if status['H_hash']!=H['artifact_sha256'] or status['seed']!=seed:raise ValueError('initialization failure binding changed')
            return {'status':status['status'],'asset':None}
        engine=self.search_engine(repeat+'/INIT','INIT',members,self.config.u_search(seed),repeat+'/init',repeat+'/A')
        try:valid=engine.initialize(stop_after_attempts=max_new_requests);failure='initialization_failed'
        except BudgetStop as exc:valid=False;failure='initialization_budget_stopped';self.progress('BUDGET_STOP',reason=str(exc))
        if valid is None:return {'status':'initialization_paused','asset':None}
        if not valid:
            self.write(status_name,'Initialization_status',seed=seed,status=failure,H_hash=H['artifact_sha256'],search_report=engine.report())
            return {'status':failure,'asset':None}
        rows=engine.export_rows()
        # Shared population is evaluated SELECT-only and remains identical in both arms.
        for r in rows:
            if any(x['member_usage']['MIX_steps'] for x in r['training_result']['instances']):raise ValueError('shared initial population must execute SELECT only')
        asset=self.write(name,'Shared_initial',seed=seed,H_hash=H['artifact_sha256'],
            training_files=list(self.dataset.names['train']),population=rows,u_interface_version=VERSION,allowed_modes=[0])
        self.progress('USAGE_SHARED_SELECT_INITIALIZED',seed=seed)
        return {'status':'initialized','asset':asset}

    def search_arm(self,seed,arm):
        if arm not in ARMS:raise ValueError('two-arm experiment permits A/B only')
        initialized=self.initialize_u(seed)
        if initialized['status']!='initialized':return {'seed':seed,'arm':arm,'status':initialized['status'],'population_hash':None}
        H,members=self.h_asset();initial=initialized['asset'];folder=f'r{seed}/{arm}';name=folder+'/Final_population.json'
        if (self.directory/name).exists():
            asset,_=self.population(name,'Final_population',H['artifact_sha256'])
            if asset['shared_initial_hash']!=initial['artifact_sha256']:raise ValueError('shared P0 changed')
        else:
            engine=self.search_engine(folder,arm,members,self.config.u_search(seed),f'r{seed}/init',f'r{seed}/{arm}',initial=initial['population'])
            try:report=engine.run()
            except BudgetStop as exc:
                self.progress('USAGE_ARM_BUDGET_STOPPED',seed=seed,arm=arm,reason=str(exc))
                return {'seed':seed,'arm':arm,'status':'budget_stopped','population_hash':None}
            if report['phase']!='completed':raise ValueError('unfinished generation')
            asset=self.write(name,'Final_population',seed=seed,arm=arm,H_hash=H['artifact_sha256'],
                shared_initial_hash=initial['artifact_sha256'],training_files=list(self.dataset.names['train']),
                population=engine.export_rows(),search_report={k:v for k,v in report.items() if k!='population'},
                u_interface_version=VERSION,allowed_modes=list(self.config.allowed_modes(arm)))
        self.progress('USAGE_ARM_COMPLETED',seed=seed,arm=arm)
        return {'seed':seed,'arm':arm,'status':'completed','population_hash':asset['artifact_sha256']}

    def search_all(self):
        self.assert_current()
        entries=[self.search_arm(s,a) for s in self.config.seeds for a in ARMS]
        result=self.write('Usage_train_search_complete.json','Usage_train_search_complete',
            seeds=list(self.config.seeds),entries=entries,holdouts_evaluated=False)
        self.training_report()
        return result

    def stage_eval(self,*args,**kwargs):raise ValueError('usage-v2 pilot is training-only; no validation/test entry')
    def select(self):raise ValueError('usage-v2 pilot has no validation selection stage')
    def test(self):raise ValueError('usage-v2 pilot has no test stage')
    def freeze(self):raise ValueError('usage-v2 pilot cannot freeze a final test policy')
    def generate_h(self):raise ValueError('usage-v2 reuses fixed H; no H generation')

    def training_report(self):
        self.assert_current();entries=[];initial=[]
        for s in self.config.seeds:
            for arm in ('INIT',*ARMS):
                p=self.directory/f'r{s}/{arm}/checkpoint.json'
                if not p.exists():record={'seed':s,'arm':arm,'status':'not_started','categories':{}}
                else:
                    state=json.loads(p.read_text());journal='budgeted_initial_requests.json' if arm=='INIT' else 'budgeted_evolution_requests.json'
                    jpath=p.parent/journal;requests=json.loads(jpath.read_text())['requests'] if jpath.exists() else {}
                    all_evals=[]
                    for identifier,cached in state['evaluations'].items():
                        raw=requests.get(identifier,{})
                        all_evals.append({'id':identifier,**cached,'generation_response':raw.get('text'),
                            'request_key':raw.get('global_key'),'token_usage':raw.get('usage'),
                            'journal_elapsed_seconds':raw.get('elapsed_seconds'),
                            'provider_roundtrip_seconds':raw.get('response_metadata',{}).get('provider_roundtrip_seconds')})
                    results=[x['result'] for x in all_evals if 'result' in x]
                    rows=[r for result in results for r in result.get('instances',[])]
                    usages=[r.get('member_usage',{}) for r in rows]
                    dual=sum(u.get('dual_member_steps',0) for u in usages)
                    record={'seed':s,'arm':arm,'status':state['phase'],'generation':state['generation'],
                        'attempts':state['attempts'],'categories':attempt_categories(state),
                        'population':state['population'],'all_evaluations':all_evals,'all_requests':requests,
                        'inflight':state['inflight'],'mean_population_train_fitness':fmean(r['fitness'] for r in state['population']) if state['population'] else None,
                        'usage':{'SELECT_steps':sum(u.get('SELECT_steps',0) for u in usages),
                            'MIX_steps':sum(u.get('MIX_steps',0) for u in usages),'dual_steps':dual,
                            'no_valid_dual_execution_observed':dual==0},
                        'cost':{key:sum(r[key] for r in rows if key in r) for key in
                            ('single_solve_seconds','deterministic_recheck_seconds','combination_processing_seconds','recheck_combination_processing_seconds','selected_h_scoring_seconds')},
                        'primary_evaluation_seconds':sum(r['primary_evaluation_seconds'] for r in results if 'primary_evaluation_seconds' in r),
                        'certified_h_calls':{pass_name:sum(sum(r[pass_name]) for r in rows if pass_name in r)
                            for pass_name in ('single_h_calls','deterministic_recheck_h_calls','diagnostic_h_calls')},
                        'unknown_failed_h_calls':None if any(not r.get('valid',False) or not r.get('diagnostic_complete',False) for r in results) else 0,
                        'independent_diagnostic_seconds':sum(r.get('diagnostic_evaluation_seconds',0) for r in results),
                        'failed_evaluation_count':sum(not r.get('valid',False) for r in results),
                        'missing_failed_solve_costs':'unknown; partial successful-row totals do not include uncertified failed solve/recheck pairs'}
                (initial if arm=='INIT' else entries).append(record)
        if self.config.mode=='real':
            from fjsp_usage.research_real.conditional_research import history_summary
            history=history_summary(self.project_root,self.config)
            fixed=self.read('Conditional_H_reassessment.json','Conditional_H_reassessment')['rows'] if (self.directory/'Conditional_H_reassessment.json').exists() else []
        else:history=None;fixed=[]
        return self.write('Usage_training_report.json','Usage_training_report',entries=entries,initialization=initial,
            fixed_member_training=fixed,budget=self.ledger.summary(),historical_budget=history,
            claim='training-only preliminary experiment' if self.config.mode=='real' else 'handwritten synthetic fixture; not real generation or research evidence',
            real_generation_completed=any(x['status']!='not_started' for x in initial) and self.config.mode=='real',
            holdouts_evaluated=False,comparison='A SELECT only; B SELECT or MIX; equal request budget is not equal total compute cost')
