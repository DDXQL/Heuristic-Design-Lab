"""Fixed 3 x (IND20/EVO20) H01 experiment. Independent journals and T30 adapter.

Original H01 CROSS/MUTATE prompts, rank parent sampler and elitist generation
survival are reused unchanged. Only safe lifecycle/accounting is independent.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import json
import multiprocessing as mp
import os
from pathlib import Path
import random
import signal
from statistics import fmean
import subprocess
import sys
import time

from fjsp_usage.research.candidates import CandidateError, parse_response, U_ARGS
from fjsp_usage.research.events import atomic_json as write
from fjsp_usage.research.protocol import digest
from fjsp_usage.research.evolution import select_parents, _tuple_tree
from fjsp_usage.research.sets import ranked
from fjsp_usage.research_real.assets import checked_candidate
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig
from fjsp_usage.research_real.attempt_budget import AttemptJournal, CIRCUIT_VERSION
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.real_transport import JsonCandidateTransport
from fjsp_usage.usage_v2.access import WireRecorder
from fjsp_usage.usage_v2 import VERSION as INTERFACE
from fjsp_usage.baseline_a.validation import validate_result
from tools import cross_feedback_ab_execute as certified
from tools import h01_weight_search as legacy
from tools import h01_progress_baseline as baseline

ROOT = Path(__file__).resolve().parents[1]
NAME = 'ind-vs-evo-h01-train21-seed501-20261026-v1'
RUN = ROOT/'runs'/NAME
REPORT = ROOT/'reports'/NAME
B2 = baseline.B2
MODULE = 'tools.ind_evo_h01'
SEEDS = (2026102511, 2026102512, 2026102513)
ORDER_SEED = 2026102510
POLICY = {'version':CIRCUIT_VERSION,'logical_candidate_cap':20,'api_attempt_cap':30,
          'per_candidate_attempt_cap':2,'retry_backoff_seconds':[2],'protocol_error_circuit_threshold':3}
EXTRA = ('tools/ind_evo_h01.py','tools/ind_evo_h01_report.py','tests/test_ind_evo_h01.py',
         'docs/IND_EVO_H01_PROTOCOL_V1.md')
INITIAL = ('There are no parents. Create an independent deterministic H0/H1 weight policy from the given state interface.\n'
           'Member ids do not imply quality. Do not assert that any id is better at a particular stage.\n')
read = baseline.read
sha = baseline.sha


def now(): return {'wall':time.time(),'monotonic':time.monotonic(),'CPU':time.process_time()}


def context(members):
    text=legacy.H_CONTEXT.replace('The host calls the chosen h for each legal action.',
        'The host calls only the positive-weight H0/H1 members for each legal action.')
    for i in (0,1):
        text+=f'\nH MEMBER {i}\nReviewed behavior: {members[i].description}\nCode:\n{members[i].code}\n'
    return text


def independent_prompt(members):
    return '\n'.join((legacy.TASK,context(members),'',INITIAL,legacy.NEW_OUTPUT,
                      'def use_heuristics('+', '.join(U_ARGS)+'):'))


def plan():
    rng=random.Random(ORDER_SEED);tasks=[]
    for start in range(0,20,2):
        repeats=[1,2,3];rng.shuffle(repeats)
        for repeat in repeats:
            arms=['IND','EVO'];rng.shuffle(arms)
            for arm in arms:
                for slot in range(start,start+2):
                    tasks.append({'task_id':f'r{repeat}_{arm}_s{slot:02d}','repeat':repeat,'arm':arm,
                                  'slot':slot,'position':len(tasks)+1})
    return tasks


def config(p):
    return ExperimentConfig(provider=ProviderConfig(**p['provider']),mode='real',real_requests_authorized=True,
        H_size=10,population_size=5,cross_parents=5,mutation_parents=1,generations=2,
        attempts_per_generation=10,initialization_cap=5,seeds=(501,),instance_timeout=30,
        total_request_cap=20,request_budget=POLICY)


def controller_witness(p):
    names=(MODULE,'tools.h01_weight_search','fjsp_usage.research.evolution','fjsp_usage.research.sets',
           'fjsp_usage.research_real.attempt_budget','fjsp_usage.research_real.real_transport',
           'fjsp_usage.usage_v2.access')
    rows={n:certified.attest_module(n,p) for n in names}
    return {'modules':rows,'identity':digest(rows)}


def initial_unit(p0,seed):
    return {'population':ranked(deepcopy(p0)),'children':[],'generation':0,'cursor':0,
            'seen':{p['candidate']['key']:p['id'] for p in p0},'rng':random.Random(seed).getstate(),
            'attempts':[],'snapshots':{'P0':[p['id'] for p in ranked(p0)]},'budget_partial':False}


def parents_for(unit,slot):
    if unit['generation'] != slot//10 or unit['cursor'] != slot%10: raise ValueError('EVO generation cursor mismatch')
    rng=random.Random();rng.setstate(_tuple_tree(unit['rng']))
    op='CROSS' if slot%10<5 else 'MUTATE'
    parents=select_parents(unit['population'],5 if op=='CROSS' else 1,rng)
    unit['rng']=rng.getstate()
    return op,parents


def advance(unit,task,entry,child):
    unit['attempts'].append(task['task_id'])
    if task['arm']!='EVO':return None
    if child is not None:unit['children'].append(child)
    unit['cursor']+=1
    if unit['cursor']!=10:return None
    before=[r['id'] for r in unit['population']]
    combined=unit['population']+unit['children']
    unit['population']=ranked(combined)[:5];unit['children']=[]
    unit['generation']+=1;unit['cursor']=0
    after=[r['id'] for r in unit['population']]
    unit['snapshots']['P'+str(unit['generation'])]=after
    return {'generation':unit['generation'],'before':before,'after':after,
            'entered':[id for id in after if id not in before]}


def accept():
    import unittest
    REPORT.mkdir(exist_ok=True)
    if (REPORT/'Offline_acceptance.json').exists():raise ValueError('acceptance already exists')
    suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_ind_evo_h01')
    with (REPORT/'Offline_acceptance.log').open('w') as f:
        result=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
    write(REPORT/'Offline_acceptance.json',{'passed':result.wasSuccessful(),'tests':result.testsRun,
        'failures':len(result.failures),'errors':len(result.errors),'files':{n:sha(ROOT/n) for n in EXTRA},
        'real_API':0,'formal_solves':0,'scope':'mock journal, synthetic evolution, exact prompt and interface checks; existing T30 acceptance reused'})
    if not result.wasSuccessful():raise ValueError('offline acceptance failed')


def prepare():
    if RUN.exists():raise ValueError('no re-prepare or resampling')
    a=read(REPORT/'Offline_acceptance.json')
    if not a['passed'] or any(sha(ROOT/n)!=h for n,h in a['files'].items()):raise ValueError('acceptance/source mismatch')
    base=baseline.check();prior=read(certified.DIRECTORY/'Execution_binding.json')
    h=read(baseline.RUN/'H_frozen.json');b2plan=read(B2/'Plan.json')
    if [r['candidate']['key'] for r in h['members']]!=b2plan['H_order']:raise ValueError('B2 H order mismatch')
    core=('code/fjsp_usage/offline_v2.py','code/fjsp_usage/usage_v2/execution.py',
          'code/fjsp_usage/research/candidates.py','code/llm4ad/task/optimization/fjsp_set/instances.py',
          'code/llm4ad/task/optimization/fjsp_set/scheduler.py','tools/h01_weight_search.py')
    protected={}
    for n in core:
        if sha(ROOT/n)!=b2plan['pins'][n]:raise ValueError('legacy H01 science/prompt mismatch '+n)
    hashes=read(ROOT/'reports'/B2.name/'Original_result_hashes.json')
    original=read(B2/'Initial_population.json');p0=[];p0_sources=[];cache={}
    RUN.mkdir();(RUN/'cache').mkdir();(RUN/'inputs/train').mkdir(parents=True)
    (RUN/'templates').mkdir();(RUN/'H_frozen.json').write_bytes((baseline.RUN/'H_frozen.json').read_bytes())
    for r in base['instances']:(RUN/r['relative_path']).write_bytes((baseline.RUN/r['relative_path']).read_bytes())
    for percent in (0,25,50,75,100):
        row=next(r for r in original if r['id']==f'MANUAL/init/alpha_{percent:03d}')
        c=legacy.validate(row['candidate']['code'],row['candidate']['description'])
        if c.key!=row['candidate']['key'] or c!=legacy.constant(percent):raise ValueError('P0 exact constant identity')
        path=B2/'results'/f'alpha_{percent:03d}.json';result=read(path)
        if sha(path)!=hashes[str(path.relative_to(ROOT))] or result!=row['training_result']:raise ValueError('P0 source result mismatch')
        level='legacy_single' if percent in (0,100) else 'legacy_pair'
        validate_result(result,base['instances'],level)
        if row['fitness']!=result['fitness'] or row['scores']!=[r['score'] for r in result['instances']]:raise ValueError('P0 scores binding')
        p0.append({k:deepcopy(row[k]) for k in ('id','candidate','fitness','scores')})
        target=RUN/'cache'/(c.key+'.json');target.write_bytes(path.read_bytes())
        cache[c.key]={'status':'completed','origin':'P0_legacy','result_path':str(target.relative_to(RUN)),
                      'result_sha256':sha(target),'reserved_instances':0,'reserved_solves':0,'level':level}
        p0_sources.append({'id':row['id'],'alpha':percent/100,'key':c.key,'fitness':row['fitness'],
            'source':str(path.relative_to(ROOT)),'source_sha256':sha(path),'level':level,
            'endpoint_equivalence':next(v for v in b2plan['versions'] if v['alpha']==percent/100).get('reuse')})
        protected[str(path.relative_to(ROOT))]=sha(path)
    members=[checked_candidate(m['candidate'],'h') for m in h['members']]
    ind=independent_prompt(members);(RUN/'templates/IND.txt').write_text(ind)
    for op in ('CROSS','MUTATE'):
        parents=ranked(p0) if op=='CROSS' else ranked(p0)[:1]
        (RUN/'templates'/(op+'_P0_example.txt')).write_text(legacy.build_prompt('B',op,parents,members))
    write(RUN/'P0.json',p0);write(RUN/'P0_sources.json',p0_sources);write(RUN/'Tasks.json',plan())
    # External references are never supplied to generation or parent selection.
    oldcp=B2/'r501/B/checkpoint.json'
    if sha(oldcp)!=hashes[str(oldcp.relative_to(ROOT))]:raise ValueError('historical B2 checkpoint changed')
    cp=read(oldcp);champ=max(cp['population'],key=lambda r:r['fitness'])
    write(RUN/'External_quality_references.json',{'B2':{'id':champ['id'],'candidate_key':champ['candidate']['key'],
         'result':cp['evaluations'][champ['id']]['result']},'simple_dynamic':read(baseline.REPORT/'Summary.json')['best_dynamic']})
    for f in (B2/'Plan.json',B2/'Initial_population.json',B2/'H_frozen.json',oldcp,
              ROOT/'reports'/B2.name/'Original_result_hashes.json',baseline.RUN/'Protocol.json',
              baseline.REPORT/'Summary.json',REPORT/'Offline_acceptance.json',
              certified.DIRECTORY/'Execution_binding.json'):
        protected[str(f.relative_to(ROOT))]=sha(f)
    authority={'origin':'current human IND vs EVO full protocol and resume message',
        'real_API_authorized':True,'repeats':3,'logical_per_arm_repeat':20,'logical_total':120,
        'API_attempt_per_arm_repeat':30,'API_attempt_per_candidate':2,'API_attempt_total':180,
        'CNY_gate':False,'fee_information_unknown_allowed':True,'launch_seconds':21600,
        'no_A4_no_CROSS_feedback_no_simple_rule_expansion_no_push':True}
    write(RUN/'Authorization.json',authority)
    sources={**prior['source_files'],**base['source_files'],**a['files']}
    for n in ('tools/h01_weight_search.py','code/fjsp_usage/research/evolution.py','code/fjsp_usage/research/sets.py'):
        sources[n]=sha(ROOT/n)
    assets={str(f.relative_to(RUN)):sha(f) for f in RUN.rglob('*') if f.is_file()}
    p={'version':NAME,'base_commit':'eafd4e227461a1d35c53cc758c64b1251f11984d',
       'provider':prior['provider'],'search_seeds':list(SEEDS),'solve_seed':501,'order_seed':ORDER_SEED,
       'model_seed':None,'model_seed_notice':'no seed sent; repeat ids are not strict paired stochastic outputs',
       'source_files':sources,'protected_files':protected,'assets':assets,'instances':base['instances'],
       'H_order':base['H_order'],'P0_sources':p0_sources,'request_policy':POLICY,
       'new_physical_instance_cap':2520,'new_solve_pass_cap':5040,'P0_new_solves':0,
       'P0_historical_cost_notice':'five common archived full-train policies, 105 instance evaluations/210 passes logically; endpoint raw-H equivalence and legacy receipts disclosed; not free prior',
       'evaluation':'same complete T30 receiver + 2s exit grace, source witnesses, solve/recheck and modern validation for both arms',
       'legacy_engine':'original select_parents rank weights 1/(N+rank), frozen generation; CROSS5/MUTATE1; first5 CROSS then5 MUTATE; ranked(parent+valid_novel_children)[:5] at generation end; tie id unchanged B/g... vs MANUAL/init...',
       'duplicate':'both arms per-search seen includes P0 and all admitted ASTs; duplicate consumes slot, no new child insertion; certified score may be reported from cache; no inferred functional equivalence',
       'cache':'P0 five verified legacy quality records + this campaign exact AST/context only; cross-arm/repeat sharing disclosed; no historical champions used as new candidates',
       'safety_change_from_old_engine':'unknown request/evaluation never silently invalidated: stop; no change to selection/generation/survival logic',
       'launch_seconds':21600,'task_reserve_seconds':1294,'maximum_transport_failure_streak':3,
       'clock_gap_seconds':2,'analysis':'three search repeats, full curves incl P0 and new-only quality/admission; failures null; no significance/generalization claim; no sample extension'}
    config(p);write(RUN/'Protocol.json',p);(RUN/'Protocol.sha256').write_text(sha(RUN/'Protocol.json')+'\n')
    write(RUN/'Solver_expected_identity.json',certified.witness(p))
    write(RUN/'Controller_expected_identity.json',controller_witness(p))
    state={'protocol_sha256':sha(RUN/'Protocol.json'),'phase':'prepared','cursor':0,'tasks':{},
           'evaluations':cache,'units':{f'r{r}_{arm}':initial_unit(p0,seed) for r,seed in enumerate(SEEDS,1) for arm in ('IND','EVO')},
           'transport_failure_streak':0}
    write(RUN/'checkpoint.json',state);check();ledger(state,p);print('FROZEN',sha(RUN/'Protocol.json'),flush=True)


def check():
    p=read(RUN/'Protocol.json')
    if sha(RUN/'Protocol.json')!=(RUN/'Protocol.sha256').read_text().strip():raise ValueError('protocol identity')
    for n,h in {**p['source_files'],**p['protected_files']}.items():
        if sha(ROOT/n)!=h:raise ValueError('frozen source/provenance changed '+n)
    for n,h in p['assets'].items():
        if sha(RUN/n)!=h:raise ValueError('frozen asset changed '+n)
    if read(RUN/'Tasks.json')!=plan() or p['search_seeds']!=list(SEEDS):raise ValueError('fixed plan/seeds changed')
    if controller_witness(p)['identity']!=read(RUN/'Controller_expected_identity.json')['identity']:raise ValueError('controller loaded identity')
    if certified.witness(p)['identity']!=read(RUN/'Solver_expected_identity.json')['identity']:raise ValueError('solver loaded identity')
    return p


def ledger(state,p):
    if state['protocol_sha256']!=sha(RUN/'Protocol.json') or not 0<=state['cursor']<=120:raise ValueError('checkpoint identity/cursor')
    used=0
    for key,r in state['evaluations'].items():
        if r['status']!='completed':raise BudgetStop('unknown evaluation reservation; no replay')
        if (r['reserved_instances'],r['reserved_solves'])!=((0,0) if r['origin']=='P0_legacy' else (21,42)):
            raise ValueError('evaluation budget ledger mismatch')
        path=RUN/r['result_path']
        if not path.resolve().is_relative_to(RUN) or sha(path)!=r['result_sha256']:raise ValueError('saved result identity')
        validate_result(read(path),p['instances'],r['level'])
        if r['origin']!='P0_legacy':used+=21
    if used>2520:raise ValueError('physical evaluation cap')
    prefix=read(RUN/'Tasks.json')[:state['cursor']]
    if set(state['tasks'])!={t['task_id'] for t in prefix}:
        raise BudgetStop('uncommitted task boundary; no automatic slot replay')
    for task in prefix:
        if state['tasks'].get(task['task_id'],{}).get('status') not in ('completed','not_started_attempt_cap'):
            raise BudgetStop('unknown task state; no replay')
    if any(v['status']=='pending' for v in state['tasks'].values()):raise BudgetStop('unknown inflight task; requires review')
    return used


def evaluate(candidate,state,p,owner):
    key=candidate.key
    if key in state['evaluations']:return read(RUN/state['evaluations'][key]['result_path']),True
    if sum(r['reserved_instances'] for r in state['evaluations'].values())+21>2520:raise BudgetStop('physical cap')
    folder=RUN/'evaluations'/key;folder.mkdir(parents=True,exist_ok=False)
    state['evaluations'][key]={'status':'reserved','origin':'new','owner_task':owner,'reserved_instances':21,'reserved_solves':42,'level':'modern'}
    write(RUN/'checkpoint.json',state)
    members=tuple(checked_candidate(m['candidate'],'h') for m in read(RUN/'H_frozen.json')['members'])
    paths=[RUN/r['relative_path'] for r in p['instances']]
    instances=tuple(certified.s.v2.load_instance(x) for x in paths);names=[r['file'] for r in p['instances']]
    expected={**p['source_files'],**p['protected_files']};start={n:sha(ROOT/n) for n in expected};t=now()
    rows,failure,life=certified.collect(mp.get_context('spawn'),certified.worker,
        {'folder':str(folder),'binding':p,'candidate':asdict(candidate),'train_paths':[str(x) for x in paths]},
        members,instances,names,30,(1,),lambda r:write(folder/'lifecycle.json',r))
    result={'valid':failure is None,'fitness':fmean(r['score'] for r in rows) if failure is None else None,
        'instances':rows,'total_instances':21,'primary_evaluation_seconds':time.monotonic()-t['monotonic'],**(failure or {})}
    write(folder/'raw_result.json',result)
    boundary=certified.certify(result,dict(before=read(folder/'before.json') if (folder/'before.json').exists() else None,
        after=read(folder/'after.json') if (folder/'after.json').exists() else None,lifecycle=life,
        expected_identity=read(RUN/'Solver_expected_identity.json')['identity'],expected_files=expected,
        start_files=start,end_files={n:sha(ROOT/n) for n in expected},worker_failure=(folder/'worker_failure.json').exists()))
    write(folder/'boundary.json',boundary)
    if boundary['decision']=='stop':raise BudgetStop('evaluation boundary '+boundary['reason'])
    validate_result(result,p['instances'],'modern');end=now()
    gap=(end['wall']-t['wall'])-(end['monotonic']-t['monotonic'])
    if abs(gap)>2:
        write(folder/'Clock_quarantine.json',{'before':t,'after':end,'gap':gap,'accepted':False})
        raise BudgetStop('clock quarantine; no reevaluation')
    result['boundary']=boundary;write(folder/'result.json',result)
    state['evaluations'][key].update(status='completed',result_path=str((folder/'result.json').relative_to(RUN)),result_sha256=sha(folder/'result.json'))
    write(RUN/'checkpoint.json',state);return result,False


def event(kind,**data):
    with (RUN/'Events.jsonl').open('a') as f:
        f.write(json.dumps({'event':kind,**now(),**data})+'\n');f.flush();os.fsync(f.fileno())


def metadata(label,secret):
    from fjsp_usage.research_real.leafapi import query_status
    data={'label':label,'at':now(),'inference_requests':0}
    try:data['account']=query_status(secret,quota_path='/api/usage/token/',include_models=False)
    except Exception as e:data['account']={'error_type':type(e).__name__}
    try:data['invoices']=legacy.query_group_invoices(secret)
    except Exception as e:data['invoices']={'error_type':type(e).__name__}
    write(RUN/'metadata'/(label+'.json'),data)
    return data


class Transport:
    def __init__(self,inner,deadline):
        self.inner=inner;self.directory=inner.directory;self.identity=inner.identity;self.deadline=deadline
        self.redact=inner.redact
    def preflight(self,prompt):
        if time.time()>=self.deadline:raise BudgetStop('persistent request deadline')
        check();self.inner.preflight(prompt)
    def dispatch(self,*args,**kwargs):return self.inner.dispatch(*args,**kwargs)


def execute_task(task,state,p,journal,members):
    uid=f'r{task["repeat"]}_{task["arm"]}';unit=state['units'][uid]
    if len(unit['attempts'])!=task['slot']:raise BudgetStop('per-search cursor mismatch')
    t=now();entry={**task,'status':'pending','started':t,'parents':[],'generation':task['slot']//10}
    if task['arm']=='IND':op='I1';parents=[];prompt=independent_prompt(members)
    else:
        op,parents=parents_for(unit,task['slot']);prompt=legacy.build_prompt('B',op,parents,members)
    entry.update(operator=op,parents=[r['id'] for r in parents],parent_pool=[r['id'] for r in unit['population']] if task['arm']=='EVO' else [],
                 parent_code_keys=[r['candidate']['key'] for r in parents])
    state['tasks'][task['task_id']]=entry;write(RUN/'checkpoint.json',state)
    path=RUN/'prompts'/(task['task_id']+'.txt');path.parent.mkdir(exist_ok=True);path.write_text(prompt)
    record=journal.request(task['task_id'],prompt,kind='U')
    entry.update(API_attempts=len(record['attempt_ids']),generation_status=record['status'],
                 status='completed',outcome='transport_failed',fitness=None,admitted=False,duplicate=False,cache_hit=False)
    halt=journal.data['halt_reason']
    if halt=='uncertain_dispatch_requires_review':
        entry['status']='unknown_request';write(RUN/'checkpoint.json',state)
        raise BudgetStop('API halt '+halt)
    child=None
    if record['status']=='completed':
        (RUN/'responses').mkdir(exist_ok=True);write(RUN/'responses'/(task['task_id']+'.json'),record)
        state['transport_failure_streak']=0
        try:
            parsed=parse_response(record['text'],kind='U',interface_version=INTERFACE,member_count=10)
            candidate=legacy.validate(parsed.code,parsed.description)
        except CandidateError as e:entry.update(outcome='parse_or_constraint_error',error=str(e)[:1000])
        else:
            entry['candidate']=asdict(candidate);entry['code_key']=candidate.key
            prior=unit['seen'].get(candidate.key);entry['duplicate']=prior is not None
            source_id=f'B/g{task["slot"]//10:04d}/{task["slot"]%10:06d}' if task['arm']=='EVO' else task['task_id']
            entry['source_id']=source_id
            if prior is not None:
                entry.update(outcome='duplicate',duplicate_of=prior)
                cached=state['evaluations'].get(candidate.key)
                if cached and cached['status']=='completed':
                    result=read(RUN/cached['result_path']);entry.update(fitness=result['fitness'],certified_valid=result['valid'],cache_hit=True,evaluation_key=candidate.key)
            else:
                unit['seen'][candidate.key]=source_id
                result,hit=evaluate(candidate,state,p,task['task_id'])
                entry.update(outcome='valid' if result['valid'] else 'invalid_evaluation',fitness=result['fitness'],
                    certified_valid=result['valid'],cache_hit=hit,evaluation_key=candidate.key)
                if result['valid']:
                    entry['admitted']=True
                    child={'id':source_id,'candidate':asdict(candidate),'fitness':result['fitness'],
                           'scores':[r['score'] for r in result['instances']]}
    else:state['transport_failure_streak']+=1
    end=now();gap=(end['wall']-t['wall'])-(end['monotonic']-t['monotonic'])
    if abs(gap)>2:
        entry.update(clock_quarantined=True,fitness=None,certified_valid=False,admitted=False,outcome='clock_quarantined')
        write(RUN/'Clock_quarantine.json',{'task':task['task_id'],'before':t,'after':end,'gap':gap})
        raise BudgetStop('task clock quarantine')
    generation=advance(unit,task,entry,child);entry['finished']=end
    state['cursor']+=1;write(RUN/'checkpoint.json',state)
    event('task_committed',task=task['task_id'],outcome=entry['outcome'],cursor=state['cursor'])
    if generation:event('generation_update',unit=uid,**generation)
    if halt:raise BudgetStop('API halt '+halt)
    if state['transport_failure_streak']>=3:raise BudgetStop('three consecutive failed logical transports; API unavailable')


def run():
    p=check()
    if (RUN/'End_summary.json').exists():return
    if (RUN/'Stop.json').exists():raise BudgetStop('persistent Stop')
    fd=os.open(RUN/'.execution.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'pid':os.getpid(),'at':now()},f)
    signal.signal(signal.SIGHUP,signal.SIG_IGN);state=read(RUN/'checkpoint.json');normal=False;keep=None;wire=None
    try:
        ledger(state,p)
        if not (RUN/'Run_clock.json').exists():
            if state.get('clock_sha256'):raise BudgetStop('persistent clock missing')
            t=now();write(RUN/'Run_clock.json',{'start':t,'deadline':t['wall']+21600,'reserve_seconds':1294})
            state['clock_sha256']=sha(RUN/'Run_clock.json');write(RUN/'checkpoint.json',state)
        if sha(RUN/'Run_clock.json')!=state['clock_sha256']:raise BudgetStop('clock identity')
        clock=read(RUN/'Run_clock.json');deadline=clock['deadline']
        if deadline!=clock['start']['wall']+21600:raise BudgetStop('window changed')
        keep=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        write(RUN/'Run_identity.json',{'pid':os.getpid(),'ppid':os.getppid(),'sid':os.getsid(0),'at':now()})
        from fjsp_usage.research_real.leafapi import load_local_key
        os.environ['LEAFAPI_API_KEY']=load_local_key(ROOT.parent/'FJSP-Heuristic-Research/.env.leafapi.local')
        wire=WireRecorder(JsonCandidateTransport(config(p)),RUN/'wire_responses',verify=check)
        transport=Transport(wire,deadline)
        journals={u:AttemptJournal(RUN/'journals'/(u+'.json'),config=config(p),context=sha(RUN/'Protocol.json'),
                   phase=NAME+'/'+u,transport=transport) for u in state['units']}
        (RUN/'metadata').mkdir(exist_ok=True)
        if not (RUN/'metadata/start.json').exists():
            q=metadata('start',wire.secret)
            if q.get('account',{}).get('quota',{}).get('total_available',1)<=0:raise BudgetStop('account balance insufficient')
        members=tuple(checked_candidate(m['candidate'],'h') for m in read(RUN/'H_frozen.json')['members'])
        tasks=read(RUN/'Tasks.json');event('run_started',deadline=deadline)
        while state['cursor']<len(tasks):
            check();ledger(state,p)
            if time.time()+p['task_reserve_seconds']>deadline:state['phase']='deadline_partial';break
            if (RUN/'Pause_request.json').exists():state['phase']='paused_boundary';break
            task=tasks[state['cursor']];uid=f'r{task["repeat"]}_{task["arm"]}';j=journals[uid]
            if j.attempt_count>=30 or state['units'][uid]['budget_partial']:
                state['units'][uid]['budget_partial']=True
                state['tasks'][task['task_id']]={**task,'status':'not_started_attempt_cap','fitness':None}
                state['cursor']+=1;write(RUN/'checkpoint.json',state);continue
            if sum(v.attempt_count for v in journals.values())>=180:state['phase']='attempt_cap_partial';break
            execute_task(task,state,p,j,members)
            if state['cursor']%10==0:metadata(f'after_{state["cursor"]:03d}',wire.secret)
        else:state['phase']='completed' if all(len(u['attempts'])==20 for u in state['units'].values()) else 'plan_exhausted_with_partial_units'
        write(RUN/'checkpoint.json',state);ledger(state,p);normal=True
    except BaseException as e:
        state['phase']='stopped';write(RUN/'checkpoint.json',state)
        write(RUN/'Stop.json',{'error_type':type(e).__name__,'error':str(e)[:1500],'at':now(),'automatic_retry':False})
        event('stopped',error_type=type(e).__name__,error=str(e)[:500])
    finally:
        if wire is not None:metadata('end',wire.secret)
        if keep is not None:
            keep.terminate()
            try:keep.wait(timeout=2)
            except subprocess.TimeoutExpired:keep.kill();keep.wait()
        write(RUN/'End_summary.json',{'phase':state['phase'],'cursor':state['cursor'],'end':now(),
             'lock_retained':not normal,'caffeinate_cleaned':keep is not None,'API_journal_summary':
             {u:j.summary() for u,j in journals.items()} if 'journals' in locals() else {}})
        if normal:(RUN/'.execution.lock').unlink()
        try:
            from tools.ind_evo_h01_report import report
            report()
        except BaseException as e:write(RUN/'Report_error.json',{'error_type':type(e).__name__,'error':str(e)[:1000]})


def launch():
    check()
    if any((RUN/n).exists() for n in ('Launch_identity.json','Run_clock.json','End_summary.json','.execution.lock')):
        raise BudgetStop('already started or unknown; no implicit replay')
    env={**os.environ,'PYTHONPATH':str(ROOT/'code')+':'+str(ROOT),'PYTHONDONTWRITEBYTECODE':'1'}
    pid=certified.detach([sys.executable,'-B','-c','from '+MODULE+' import run; run()'],RUN/'Console.log',env=env)
    write(RUN/'Launch_identity.json',{'pid':pid,'at':now(),'method':'verified detached session/files/SIGHUP ignore'})
    print(json.dumps({'launched':pid,'run':str(RUN)}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',choices=('accept','prepare','check','launch','run','report'))
    stage=parser.parse_args().stage
    if stage=='accept':accept()
    elif stage=='prepare':prepare()
    elif stage=='check':p=check();ledger(read(RUN/'checkpoint.json'),p);print('PASS')
    elif stage=='launch':launch()
    elif stage=='run':run()
    else:
        from tools.ind_evo_h01_report import report
        report()


if __name__=='__main__':main()
