"""Bounded update-frequency comparison, reusing P prompts/search/evaluation."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import random
from fjsp_usage.research.evolution import select_parents
from fjsp_usage.research.sets import ranked
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from .assets import check_seal,validate_row,seal
from .budget import BudgetStop
from .config import fingerprint
from .search import V5BudgetedSearch
from .single_fair import FairWorkflow,file_sha,read,verify_final_receipts
from .single_experiments import budget_inventory,worktree_roots

VERSION='single-ID-update-frequency-v1'
SCOPE='fixed-H-single-ID-update-frequency-train-only'
CYCLE=['CROSS']*5+['MUTATE']*5
SOURCE_NAMES=('protocol.json','config.single.authorized.json','H_frozen.json',
    'r201/Shared_initial.json','r201/INIT/checkpoint.json','r201/INIT/budgeted_initial_requests.json',
    'History_binding.json','Final_budget_handoff.json','budget.json','platform_quota.json',
    'Metadata_global_pacing.json','Invoice_query_pacing.json')


def validate_declaration(c):
    d=c.conditional_research
    fields={'version','source_run','source_files_sha256','risk_policy','scope_approval',
        'lifetime_request_cap','history_binding','authorization','operator_cycle',
        'arm_search','execution_order','historical_reference'}
    if (set(d)!=fields or c.mode!='real' or c.purpose!='research' or c.seeds!=(201,)
        or c.population_size!=5 or c.H_size!=10 or c.cross_parents!=5 or c.mutation_parents!=1
        or c.generations!=3 or c.attempts_per_generation!=10 or c.initialization_cap!=5
        or c.total_request_cap!=60 or c.instance_timeout!=15 or not c.training_diagnostics
        or c.platform_quota_ceiling!=30000000 or c.platform_quota_reservation!=1000000
        or c.platform_quota_query_interval<75 or c.phase_request_caps is not None
        or c.development_h_source or c.development_continuation_source or c.development_acceptance
        or d['lifetime_request_cap']!=300 or d['operator_cycle']!=CYCLE
        or d['arm_search']!={'A':{'generations':1,'attempts_per_generation':30},
                            'B':{'generations':3,'attempts_per_generation':10}}
        or d['execution_order']!=[['A',10],['B',10],['A',20],['B',20],['A',30],['B',30]]
        or set(d['source_files_sha256'])!=set(SOURCE_NAMES)
        or Path(d['source_run']).name!=d['source_run'] or d['source_run'] in ('.','..')):
        raise ValueError('update v1 requires seed201/N5/60 calls and exact A30 vs B10x3 cycle')
    ref=d['historical_reference']
    if (not isinstance(ref,dict) or set(ref)!={'run','files_sha256'}
        or Path(ref['run']).name!=ref['run'] or ref['run'] in ('.','..')
        or set(ref['files_sha256'])!={'protocol.json','r201/Shared_initial.json'}
        or any(not isinstance(h,str) or len(h)!=64 or any(x not in '0123456789abcdef' for x in h)
               for h in [*d['source_files_sha256'].values(),*ref['files_sha256'].values()])):
        raise ValueError('bounded source/reference SHA256 identities required')
    if c.real_requests_authorized:
        a=d['authorization']
        if (not a or a.get('approved') is not True or a.get('scope')!=SCOPE
            or a.get('max_new_requests')!=60 or not a.get('authorization_excerpt')
            or not d['history_binding']):
            raise ValueError('current-task authorization and inherited history required')
    elif d['authorization'] is not None:raise ValueError('pending config cannot contain approval')


def source_bundle(root,c,dataset):
    d=c.conditional_research;p=Path(root)/'runs'/d['source_run']
    if (p/'.writer.lock').exists():raise BudgetStop('source caller active')
    docs={}
    for name,h in d['source_files_sha256'].items():
        if file_sha(p/name)!=h:raise BudgetStop('source changed: '+name)
        docs[name]=read(p/name)
    old=docs['protocol.json'];H=docs['H_frozen.json'];U=docs['r201/Shared_initial.json']
    check_seal(H,kind='H_frozen',mode='real',context=digest(old))
    check_seal(U,kind='Shared_initial',mode='real',context=digest(old))
    from .prompts import prompt_manifest
    if (old['dataset']!=dataset.metadata or old['config']['provider']!=c.payload()['provider']
        or old['config']['instance_timeout']!=c.instance_timeout
        or old['config']['review_timeout']!=c.review_timeout or old['prompt_pack']!=prompt_manifest()
        or old['config']['conditional_research']['risk_policy']!=d['risk_policy']
        or H['scope_approval']!=d['scope_approval'] or U['H_hash']!=H['artifact_sha256']
        or H['training_files']!=list(dataset.names['train']) or U['training_files']!=H['training_files']
        or len(U['population'])!=5 or H['member_count']!=10):
        raise ValueError('source H/U/provider/prompt/data/evaluation differs')
    now=fingerprint(root)
    if any(now[k]!=old['implementation'][k] for k in ('python','platform','dependencies','version')):
        raise ValueError('cached evaluations require identical runtime/dependencies')
    # Audited new-version routing only. Old scheduling/state/scoring/search/P
    # prompts remain byte-identical; old protocol fingerprints are not rewritten.
    routing={'code/fjsp_usage/research_real/config.py','code/fjsp_usage/research_real/conditional_research.py'}
    for n,h in old['implementation']['files'].items():
        if n not in routing and now['files'].get(n)!=h:raise ValueError('cached dependency changed: '+n)
    members=[]
    from fjsp_usage.research.candidates import Candidate
    for i,row in enumerate(H['members']):
        h=validate_row(row,dataset.names['train'],'real','h');review=row['review']
        if (row['member_id']!=i or review['reviewed_code_key']!=h.key
            or review['sample_sha256']!=digest(review['samples']) or not review['reviewer']):
            raise ValueError('H numbering/review binding changed')
        members.append(Candidate(review['description'],h.code,h.key,'h'))
    journal=docs['r201/INIT/budgeted_initial_requests.json']['requests'];ledger=docs['budget.json']['records']
    for row in U['population']:
        validate_row(row,dataset.names['train'],'real','U');r=journal[row['id']];b=ledger[r['global_key']]
        if (not b['send_confirmed'] or r['status']!='completed' or r['text']!=row['receipt']['response_text']
            or r['usage']!=row['receipt']['usage'] or row['receipt']['ledger_identity']!=docs['budget.json']['identity']):
            raise ValueError('shared U request provenance differs')
    if len({m.key for m in members})!=10 or len({x['candidate']['key'] for x in U['population']})!=5:
        raise ValueError('source code keys are not distinct')
    rng=docs['r201/INIT/checkpoint.json']['rng']
    if digest(rng)!=digest(random.Random(201).getstate()):raise ValueError('unexpected source parent RNG state')
    return docs,tuple(members),rng


def bind_history(root,c,dataset,*,inventory=None):
    docs,_,_=source_bundle(root,c,dataset);source=Path(root)/'runs'/c.conditional_research['source_run']
    old=docs['History_binding.json'];check_seal(old,kind='Fair_history_binding',mode='real')
    for n,h in old['files_sha256'].items():
        if file_sha(n)!=h:raise BudgetStop('inherited historical evidence changed')
    h=docs['Final_budget_handoff.json'];native=docs['budget.json'];quota=docs['platform_quota.json']
    if (h.get('real_caller_active') is not False or h.get('registered_generation_phases_complete') is not True
        or h['budget_sha256']!=file_sha(source/'budget.json') or h['budget_identity']!=native['identity']
        or h['quota_halted'] or h['unknown_new_fee_keys'] or h['unknown_new_fee_holds']
        or h['old_account_hold']!=old['retained_account_hold']
        or any(x['status'] in ('pending','reserved') for x in native['records'].values())):
        raise BudgetStop('source has unresolved/active calls or inconsistent handoff')
    files=dict(old['files_sha256']);missing=list(old.get('historical_invoice_group_missing_keys',[]))
    points=verify_final_receipts(source,native,quota,files,missing)
    if points!=h['known_new_points']:raise BudgetStop('source cost differs from invoices')
    expected={**old['real_budget_inventory'],native['identity']:file_sha(source/'budget.json')}
    current=inventory() if inventory else budget_inventory(worktree_roots(root))
    if current!=expected:raise BudgetStop('unregistered/active cross-worktree consumption')
    slots=old['historical_request_slots']+len(native['records'])
    sends=old['historical_confirmed_sends']+sum(bool(x.get('send_confirmed')) for x in native['records'].values())
    if (slots!=h['summary']['lifetime_request_slots'] or sends!=h['summary']['lifetime_confirmed_sends']
        or slots+60>300):raise BudgetStop('cumulative budget inconsistent/insufficient')
    for n in SOURCE_NAMES:files[str(source/n)]=file_sha(source/n)
    return seal({**{k:v for k,v in old.items() if k!='artifact_sha256'},'files_sha256':files,
        'real_budget_inventory':expected,'historical_request_slots':slots,'historical_confirmed_sends':sends,
        'historical_token_charges':old['historical_token_charges']+
            [x['usage'] if x.get('usage') is not None else x['reservation'] for x in native['records'].values()],
        'latest_saved_account_used':max(h['latest_verified_used_points'],quota['observed_used']),
        'metadata_floor':docs['Metadata_global_pacing.json']['last_finished_at'],
        'invoice_floor':docs['Invoice_query_pacing.json']['last_finished_at'],
        'metadata_interval':max(old['metadata_interval'],docs['Metadata_global_pacing.json']['interval']),
        'invoice_interval':max(old['invoice_interval'],docs['Invoice_query_pacing.json']['interval']),
        'historical_invoice_group_missing_keys':missing})


class UpdateSearch(V5BudgetedSearch):
    def _prepare(self,*,initial):
        if initial:raise BudgetStop('reused P0 only; no initialization requests')
        if self.state['inflight'] is not None:return
        local=self.state['cursor'];index=self.state['generation']*self.config.attempts_per_generation+local
        operator=CYCLE[index%10]
        parents=select_parents(self.state['population'],5 if operator=='CROSS' else 1,self.rng)
        identifier=f'{self.arm}/g{self.state["generation"]:04d}/{local:06d}'
        self.state['inflight']={'id':identifier,'operator':operator,'parents':[x['id'] for x in parents],
            'initial':False,'prompt':self._build_prompt('P',operator,parents,self.members,kind='U')}
        self._save()

    def milestone(self):
        n=len(self.state['attempts'])
        if not n or n%10:return
        p=self.directory/f'Milestone_{n:02d}.json'
        elite=ranked(self.state['population']+self.state['children'])[:5]
        sends=sum(bool(x.get('send_confirmed')) for x in self.ledger.data['records'].values()
                  if x['phase']==self.evolution_requests.phase)
        value={'arm':self.arm,'attempt_slots':n,'confirmed_sends':sends,
            'actual_parent_pool':deepcopy(self.state['population']),
            'observed_elites':deepcopy(elite),'incumbent':deepcopy(elite[0]),
            'actual_survival_updates':self.state['generation'],'rng_sha256':digest(self.state['rng']),
            'note':'A at10/20: observed_elites diagnostic only; actual parents remain P0. No feedback to prompts.'}
        if p.exists():
            if read(p)!=value:raise ValueError('milestone identity changed')
        else:atomic_json(p,value)

    def run_until(self,limit):
        if limit not in (10,20,30):raise ValueError('registered ten-slot boundaries only')
        if self.state['phase']=='initialization':raise ValueError('source P0 required')
        while True:
            if self.state['cursor']==self.config.attempts_per_generation:
                self.state['population']=ranked(self.state['population']+self.state['children'])[:5]
                self.state['children']=[];self.state['cursor']=0;self.state['generation']+=1;self._save()
                self.events.emit('generation',arm=self.arm,generation=self.state['generation'],
                    population_ids=[x['id'] for x in self.state['population']])
            if len(self.state['attempts']) in (10,20,30):self.milestone()
            if self.state['generation']==self.config.generations:
                self.state['phase']='completed';self._save();return self.report()
            if len(self.state['attempts'])>=limit:return self.report()
            self._prepare(initial=False);self._attempt()


class UpdateWorkflow(FairWorkflow):
    def h_asset(self):
        if not hasattr(self,'_bound_source'):
            self._bound_source=source_bundle(self.project_root,self.config,self.dataset)
        docs,members,_=self._bound_source
        H=self.read('H_frozen.json','H_frozen')
        old=docs['H_frozen.json']
        if (H['members']!=old['members'] or H['source_H_hash']!=old['artifact_sha256']
            or H['scope_approval']!=old['scope_approval'] or H['training_files']!=old['training_files']):
            raise ValueError('reused H changed')
        return H,members

    def shared_asset(self):
        H,_=self.h_asset();docs,_,rng=self._bound_source
        shared=self.read('r201/Shared_initial.json','Shared_initial');old=docs['r201/Shared_initial.json']
        saved_rng=read(self.directory/'Parent_rng_initial.json')
        if (shared['population']!=old['population'] or shared['source_shared_hash']!=old['artifact_sha256']
            or shared['H_hash']!=H['artifact_sha256'] or shared['training_files']!=old['training_files']
            or saved_rng!={'rng':rng,'sha256':digest(rng),'seed':201}):
            raise ValueError('shared P0/provenance/parent RNG changed')
        return shared

    def check(self):
        super().check();self.shared_asset()

    def initialize_u(self,*args,**kwargs):raise BudgetStop('no new initial U requests permitted')

    def engine(self,arm):
        if arm not in ('A','B'):raise ValueError('registered A/B only')
        _,members=self.h_asset();shared=self.shared_asset()
        cfg=replace(self.config.u_search(201),**self.config.conditional_research['arm_search'][arm])
        return UpdateSearch(self.directory/f'r201/{arm}',arm=arm,config=cfg,members=members,
            evaluator=lambda c:self.train_eval(c,members),transport=self.client(),context=self.context,
            kind='U',initial=shared['population'],init_phase='r201/init',search_phase=f'r201/{arm}',
            ledger=self.ledger,experiment=self.config,training_names=self.dataset.names['train'])

    def run_training(self):
        for arm,limit in self.config.conditional_research['execution_order']:
            engine=self.engine(arm);engine.run_until(limit)
            if engine.state['phase']=='completed':
                self.write(f'r201/{arm}/Final_population.json','Final_population',arm=arm,seed=201,
                    H_hash=self.read('H_frozen.json','H_frozen')['artifact_sha256'],
                    shared_initial_hash=self.read('r201/Shared_initial.json','Shared_initial')['artifact_sha256'],
                    training_files=list(self.dataset.names['train']),population=engine.export_rows())
