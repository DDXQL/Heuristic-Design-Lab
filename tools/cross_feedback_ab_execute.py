"""Authorized execution supplement; reuses frozen CROSS A/B tasks verbatim.

No fee certification prerequisite. Original protocol, fee stop and zero ledgers
stay immutable. New journal inherits their zero consumption and keeps 30/40/2.
"""
import argparse
from dataclasses import asdict
import importlib
import inspect
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
import types
import unittest

from fjsp_usage.research.events import atomic_json as write
from fjsp_usage.research.protocol import digest
from fjsp_usage.research.candidates import parse_response, CandidateError, compile_candidate
from fjsp_usage.research_real.assets import checked_candidate
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig
from fjsp_usage.research_real.attempt_budget import AttemptJournal, CIRCUIT_VERSION
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.real_transport import JsonCandidateTransport
from fjsp_usage.usage_v2.access import WireRecorder
from fjsp_usage.usage_v2.execution import construct_usage_schedule
from fjsp_usage.usage_v2 import VERSION as INTERFACE
from fjsp_usage.baseline_supplemental.lifecycle import collect, classify
from fjsp_usage.baseline_a.validation import validate_result
from tools import cross_feedback_ab as frozen
from tools import baseline_a_supplemental as s

ROOT=frozen.ROOT;BASE=frozen.DEFAULT;DIRECTORY=BASE/'execution-v2';REPORT=frozen.REPORT/'execution-v2'
VERSION='cross-feedback-execution-fee-waiver-v2-20261025'
MODULE='tools.cross_feedback_ab_execute'
POLICY={'version':CIRCUIT_VERSION,'logical_candidate_cap':30,'api_attempt_cap':40,
        'per_candidate_attempt_cap':2,'retry_backoff_seconds':[2], 'protocol_error_circuit_threshold':3}
EXTRA=('tools/cross_feedback_ab_execute.py','tools/cross_feedback_ab_execution_report.py',
       'tests/test_cross_feedback_ab_execute.py')
read=frozen.read;sha=frozen.sha


def clock():return {'wall':time.time(),'monotonic':time.monotonic(),'CPU':time.process_time()}


def event(kind,**values):
    with (DIRECTORY/'Events.jsonl').open('a') as f:
        f.write(json.dumps({'event':kind,**clock(),**values})+'\n');f.flush();os.fsync(f.fileno())


def config(p):
    return ExperimentConfig(provider=ProviderConfig(**p['provider']),mode='real',real_requests_authorized=True,
        H_size=10,population_size=5,cross_parents=2,mutation_parents=1,seeds=(501,),
        generations=1,attempts_per_generation=10,initialization_cap=5,total_request_cap=30,
        instance_timeout=30,request_budget=POLICY)


def attest_module(name,p):
    m=importlib.import_module(name);path=Path(m.__file__).resolve();relative=str(path.relative_to(ROOT))
    if sha(path)!=p['source_files'][relative]:raise ValueError('execution source changed: '+relative)
    raw=compile(path.read_bytes(),str(path),'exec',dont_inherit=True,optimize=0)
    defs={c.co_name:c for c in raw.co_consts if isinstance(c,types.CodeType)};functions={}
    for key,fn in vars(m).items():
        if inspect.isfunction(fn) and fn.__module__==name:
            if key not in defs or s.v2.code_identity(fn.__code__)!=s.v2.code_identity(defs[key]):
                raise ValueError('loaded function identity mismatch: '+key)
            functions[key]=s.v2.code_identity(fn.__code__)
        if inspect.isclass(fn) and fn.__module__==name and key in defs:
            methods={c.co_name:c for c in defs[key].co_consts if isinstance(c,types.CodeType)}
            for attr,value in vars(fn).items():
                if isinstance(value,(classmethod,staticmethod)):value=value.__func__
                if inspect.isfunction(value) and attr in methods:
                    if s.v2.code_identity(value.__code__)!=s.v2.code_identity(methods[attr]):raise ValueError('loaded method mismatch')
                    functions[key+'.'+attr]=s.v2.code_identity(value.__code__)
    return {'file':str(path),'source_sha256':sha(path),'loaded_functions':functions}


def witness(p):
    modules=s.witness(p)['modules'];modules[MODULE]=attest_module(MODULE,p)
    return {'pid':os.getpid(),'modules':modules,'identity':digest(modules)}


def accept():
    REPORT.mkdir(exist_ok=True)
    if (REPORT/'Offline_acceptance.json').exists():raise ValueError('acceptance exists')
    suite=unittest.defaultTestLoader.loadTestsFromNames(['tests.test_cross_feedback_ab','tests.test_cross_feedback_ab_execute'])
    with (REPORT/'Offline_acceptance.log').open('w') as f:result=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
    write(REPORT/'Offline_acceptance.json',{'passed':result.wasSuccessful(),'tests_run':result.testsRun,
        'failures':len(result.failures),'errors':len(result.errors),'files':{n:sha(ROOT/n) for n in EXTRA},
        'real_API':0,'formal_solves':0,'scope':'mock journal/transport, synthetic T30 lifecycle, same kernel toy and detached launcher'})
    if not result.wasSuccessful():raise ValueError('offline acceptance failed')


def bind():
    p=frozen.check()  # does NOT call the superseded fee preflight
    if DIRECTORY.exists():raise ValueError('execution supplement already exists; no reset')
    a=read(REPORT/'Offline_acceptance.json')
    if not a['passed'] or any(sha(ROOT/n)!=h for n,h in a['files'].items()):raise ValueError('offline code changed')
    for name in ('API_cost_ledger.json','Evaluation_ledger.json'):
        old=read(BASE/name)
        if old.get('attempts') or old.get('evaluations'):raise ValueError('old consumption is not zero')
    if read(BASE/'checkpoint.json')['logical_started']!=0:raise ValueError('prior tasks already started')
    parent_protocol=read(s.DEFAULT/'Protocol.json')
    sources={**parent_protocol['source_files'],**p['source_files'],**a['files']}
    from tools.t1_d1_diagnostic import RUNTIME
    sources.update({n:sha(ROOT/n) for n in RUNTIME})
    sources.update({n:sha(ROOT/n) for n in ('code/fjsp_usage/usage_v2/access.py','code/fjsp_usage/research_real/leafapi.py')})
    previous={str((BASE/n).relative_to(ROOT)):sha(BASE/n) for n in ('Protocol.json','Protocol.sha256','Tasks.json',
        'Parents.json','H_frozen.json','Fee_stop.json','checkpoint.json','API_cost_ledger.json','Evaluation_ledger.json','Authorization.json')}
    previous.update({str((BASE/'prompts'/n).relative_to(ROOT)):h for n,h in p['prompt_sha256'].items()})
    DIRECTORY.mkdir()
    authority={'approved':True,'origin':'current human user message continuing a1ad625, 2026-10-25',
        'authorization_change':'cancel 20 CNY cap AND all currency, billable-token, account-encumbrance and fee-reservation prerequisites',
        'retained_caps':{'logical_candidates':30,'API_attempts':40,'attempts_per_candidate':2,
                         'program_instances':630,'solve_passes':1260,'launch_seconds':21600},
        'no_new_sampling_no_A4_no_C_no_push':True,
        'window':'explicit new <=6h window from this execution first run; historical stop untouched'}
    write(DIRECTORY/'Authorization.json',authority)
    binding={'version':VERSION,'base_protocol_sha256':sha(BASE/'Protocol.json'),'base_commit':'a1ad6257be9e531edad9ba39f11353bb85e98111',
        'source_files':sources,'protected_files':{**p['protected_files'],**previous},'provider':p['provider'],
        'authorization_sha256':sha(DIRECTORY/'Authorization.json'),'acceptance_sha256':sha(REPORT/'Offline_acceptance.json'),
        'config':config(p).payload(),'inherited_API_attempts':0,'inherited_logical_started':0,
        'wait_seconds':30,'exit_grace_seconds':2.,'launch_seconds':21600,'solve_seed':501,
        'new_evaluation_cap':630,'new_solve_pass_cap':1260,
        'runtime_invalid':'known U output/numeric errors require exact before/after identity, exit0 and stopped receiver; null Fitness; no retries',
        'clock_gap':'abs(wall_delta-monotonic_delta)>2s quarantines active result and stops new starts; no auto re-evaluation',
        'cost':'best effort start/end metadata and receipt matching; CNY unknown permitted; never a dispatch gate',
        'analysis':p['analysis'],'task_plan_sha256':sha(BASE/'Tasks.json')}
    write(DIRECTORY/'Execution_binding.json',binding);(DIRECTORY/'Execution_binding.sha256').write_text(sha(DIRECTORY/'Execution_binding.json')+'\n')
    write(DIRECTORY/'Expected_loaded_identity.json',witness(binding))
    write(DIRECTORY/'checkpoint.json',{'binding_sha256':sha(DIRECTORY/'Execution_binding.json'),'phase':'ready',
        'tasks':{},'evaluations':{},'cursor':0})
    check()


def check():
    p=frozen.check();b=read(DIRECTORY/'Execution_binding.json')
    if sha(DIRECTORY/'Execution_binding.json')!=(DIRECTORY/'Execution_binding.sha256').read_text().strip():raise ValueError('binding changed')
    for n,h in {**b['source_files'],**b['protected_files']}.items():
        if sha(ROOT/n)!=h:raise ValueError('frozen source/provenance changed: '+n)
    if (b['base_protocol_sha256']!=sha(BASE/'Protocol.json') or b['task_plan_sha256']!=sha(BASE/'Tasks.json')
        or b['authorization_sha256']!=sha(DIRECTORY/'Authorization.json') or b['acceptance_sha256']!=sha(REPORT/'Offline_acceptance.json')):
        raise ValueError('execution authorization/tasks mismatch')
    if digest(config(p).payload())!=digest(b['config']) or witness(b)['identity']!=read(DIRECTORY/'Expected_loaded_identity.json')['identity']:
        raise ValueError('loaded/config identity changed')
    return p,b


def certify(result,kwargs):
    """Use existing T30 success/timeout checks; independently certify U runtime failures."""
    known={'UsageOutputError','NormalizationError'}
    if result.get('error_type') not in known:return classify(result,**kwargs)
    l=kwargs['lifecycle'];before=kwargs['before'];after=kwargs['after'];expected=kwargs['expected_identity']
    valid=lambda x:isinstance(x,dict) and x.get('identity')==digest(x.get('modules',{}))==expected
    boundary=(kwargs['expected_files']==kwargs['start_files']==kwargs['end_files'] and bool(kwargs['expected_files']))
    if (not boundary or kwargs.get('worker_failure') or not valid(before) or not valid(after)
        or before['pid']!=after['pid'] or l.get('pid')!=before['pid'] or l.get('status')!='terminal'
        or l.get('alive') is not False or l.get('exitcode')!=0 or l.get('receiver_thread_stopped') is not True
        or l.get('deadline_seconds')!=30 or l.get('exit_grace_seconds')!=2. or l.get('trigger') is not None
        or result.get('valid') is not False or result.get('fitness') is not None
        or l.get('all_results_received') is not False or l.get('rows_received')!=len(result['instances'])
        or any(not r['timely'] for r in l.get('instance_receives',[]))):
        return {'decision':'stop','reason':'runtime_failure_identity_or_exit_not_certified','fitness':None}
    return {'decision':'candidate_invalid_continue','reason':'certified_U_runtime_failure','fitness':None}


def worker(pipe,payload,members,instances,names,allowed_modes):
    os.environ.pop('LEAFAPI_API_KEY',None)
    folder=Path(payload['folder']);b=payload['binding'];network=s.v2.local_guard(payload['train_paths'])
    try:
        write(folder/'before.json',witness(b));random.seed(501)
        rules=tuple(compile_candidate(m) for m in members);usage=compile_candidate(checked_candidate(payload['candidate'],'U'))
        for name,instance in zip(names,instances):
            stem=folder/Path(name).stem;progress={'file':name,'first_started':True,'recheck_started':False,'completed':False}
            s.phase(stem,progress,'first_start');cost=[];started=time.perf_counter()
            first=construct_usage_schedule(instance,rules,usage,cost=cost.append);single=time.perf_counter()-started
            firstcost=cost[:];cost.clear();progress.update(first_completed=True,recheck_started=True,first_solve_seconds=single)
            s.phase(stem,progress,'first_end');s.phase(stem,progress,'recheck_start');started=time.perf_counter()
            second=construct_usage_schedule(instance,rules,usage,cost=cost.append);recheck=time.perf_counter()-started
            s.phase(stem,progress,'recheck_end')
            if first!=second:raise ValueError('complete solve/recheck mismatch')
            physical=s.v2.physical(first.schedule);again=s.v2.physical(second.schedule)
            if physical!=again:raise ValueError('physical recheck mismatch')
            row={'file':name,'makespan':first.schedule.makespan,'lower_bound':first.lower_bound,'score':first.score,
                 'feasible':True,'captured_solves':2,'single_solve_seconds':single,'deterministic_recheck_seconds':recheck,
                 'single_h_calls':list(first.member_calls),'recheck_h_calls':list(second.member_calls),
                 'physical_schedule':physical,'physical_schedule_sha256':digest(physical),
                 'recheck_physical_schedule_sha256':digest(again),'commit_sequence_sha256':digest(asdict(first.schedule)),
                 'member_usage':{'dominant_counts':[first.selected_members.count(i) for i in range(len(members))],
                                 'steps':len(first.selected_members)},
                 'first_costs':firstcost,'recheck_costs':cost[:],'network_guard':dict(network)}
            write(stem.with_suffix('.result.json'),row);progress['completed']=True;s.phase(stem,progress,'result_write_end')
            if name==names[-1]:write(folder/'after.json',witness(b))
            pipe.send(row)
    except BaseException as exc:
        candidate_error=type(exc).__name__ in ('UsageOutputError','NormalizationError')
        write(folder/('candidate_failure.json' if candidate_error else 'worker_failure.json'),
              {'error_type':type(exc).__name__,'error':str(exc)[:500]})
        write(folder/'after.json',witness(b));pipe.send({'error_type':type(exc).__name__,'error':str(exc)[:500]})
    finally:
        try:write(folder/'network_guard.json',network)
        finally:pipe.close()


def evaluate(candidate,key,state,p,b):
    if key in state['evaluations']:raise BudgetStop('evaluation reserved already; no automatic repeat')
    if len(state['evaluations'])*21+21>630:raise BudgetStop('physical evaluation budget')
    folder=DIRECTORY/'evaluations'/key;folder.mkdir(parents=True,exist_ok=False)
    state['evaluations'][key]={'status':'reserved','reserved_program_instances':21,'reserved_solve_passes':42}
    write(DIRECTORY/'checkpoint.json',state)
    members=tuple(checked_candidate(x['candidate'],'h') for x in read(BASE/'H_frozen.json')['members'])
    paths=[s.DEFAULT/r['relative_path'] for r in p['science']['instances']]
    instances=tuple(s.v2.load_instance(path) for path in paths);names=[r['file'] for r in p['science']['instances']]
    expected={**b['source_files'],**b['protected_files']};start={n:sha(ROOT/n) for n in expected};beg=clock()
    rows,failure,life=collect(mp.get_context('spawn'),worker,{'folder':str(folder),'binding':b,
        'candidate':asdict(candidate),'train_paths':[str(x) for x in paths]},members,instances,names,30,(0,1),
        lambda receipt:write(folder/'lifecycle.json',receipt))
    result={'valid':failure is None,'fitness':fmean(r['score'] for r in rows) if failure is None else None,
            'total_instances':21,'instances':rows,'primary_evaluation_seconds':time.monotonic()-beg['monotonic'],**(failure or {})}
    write(folder/'raw_result.json',result)
    boundary=certify(result,dict(before=read(folder/'before.json') if (folder/'before.json').exists() else None,
        after=read(folder/'after.json') if (folder/'after.json').exists() else None,lifecycle=life,
        expected_identity=read(DIRECTORY/'Expected_loaded_identity.json')['identity'],expected_files=expected,start_files=start,
        end_files={n:sha(ROOT/n) for n in expected},worker_failure=(folder/'worker_failure.json').exists()))
    write(folder/'boundary.json',boundary)
    if boundary['decision']=='stop':raise BudgetStop('evaluation boundary: '+boundary['reason'])
    validate_result(result,p['science']['instances'],'modern')
    end=clock();gap=(end['wall']-beg['wall'])-(end['monotonic']-beg['monotonic'])
    if abs(gap)>2:
        write(folder/'Clock_quarantine.json',{'before':beg,'after':end,'gap':gap,'accepted':False})
        raise BudgetStop('clock gap; result quarantined without re-evaluation')
    result['boundary']=boundary;write(folder/'result.json',result)
    state['evaluations'][key].update(status='completed',result_path=str((folder/'result.json').relative_to(DIRECTORY)),result_sha256=sha(folder/'result.json'))
    write(DIRECTORY/'checkpoint.json',state);return result


def validate_state(state,plans):
    if state['cursor']>len(plans) or len(state['tasks'])>30 or len(state['evaluations'])*21>630:raise BudgetStop('state/caps corrupt')
    for index,task in enumerate(plans[:state['cursor']]):
        row=state['tasks'].get(task['task_id'])
        if row is None or row.get('status') not in ('parse_invalid','transport_failed','evaluated','cache'):
            raise BudgetStop('nonterminal task cursor')
    for key,row in state['evaluations'].items():
        if row['status']!='completed':raise BudgetStop('unknown evaluation reservation; no replay')
        if sha(DIRECTORY/row['result_path'])!=row['result_sha256']:raise BudgetStop('certified result changed')


def metadata(label,secret):
    """Best effort only: no currency/tariff/encumbrance gating or fee release."""
    from fjsp_usage.research_real.leafapi import query_status
    from tools.h01_weight_search import query_group_invoices
    try:q=query_status(secret,quota_path='/api/usage/token/',include_models=False)
    except Exception as exc:q={'error_type':type(exc).__name__}
    write(DIRECTORY/('Account_'+label+'.json'),q)
    try:i=query_group_invoices(secret)
    except Exception as exc:i={'error_type':type(exc).__name__}
    write(DIRECTORY/('Invoices_'+label+'.json'),i)
    return q


class DeadlineTransport:
    def __init__(self,inner,deadline):
        self.inner=inner;self.directory=inner.directory;self.identity=inner.identity;self.deadline=deadline
        self.redact=inner.redact
    def preflight(self,prompt):
        if time.time()>=self.deadline:raise BudgetStop('persistent launch deadline reached before API attempt')
        check();self.inner.preflight(prompt)
    def dispatch(self,*args,**kwargs):return self.inner.dispatch(*args,**kwargs)


def run():
    p,b=check()
    if (DIRECTORY/'End_summary.json').exists():return
    if (DIRECTORY/'Stop.json').exists():raise BudgetStop('persistent execution Stop')
    lock=DIRECTORY/'.execution.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'pid':os.getpid(),'start':clock()},f)
    write(DIRECTORY/'Run_identity.json',{'pid':os.getpid(),'ppid':os.getppid(),'sid':os.getsid(0),'start':clock()})
    signal.signal(signal.SIGHUP,signal.SIG_IGN);keepawake=None;normal=False;state=read(DIRECTORY/'checkpoint.json')
    try:
        cp=DIRECTORY/'Run_clock.json'
        if not cp.exists():
            if state.get('run_clock_sha256'):raise BudgetStop('persistent clock missing')
            now=time.time();write(cp,{'start_utc_epoch':now,'deadline_utc_epoch':now+21600,'authority_sha256':b['authorization_sha256']})
            state['run_clock_sha256']=sha(cp);write(DIRECTORY/'checkpoint.json',state)
        elif state.get('run_clock_sha256')!=sha(cp):raise BudgetStop('clock identity mismatch; never reset')
        window=read(cp);deadline=window['deadline_utc_epoch']
        if deadline!=window['start_utc_epoch']+21600:raise BudgetStop('clock budget changed')
        keepawake=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        plans=read(BASE/'Tasks.json')['tasks'];validate_state(state,plans)
        from fjsp_usage.research_real.leafapi import load_local_key
        os.environ['LEAFAPI_API_KEY']=load_local_key(ROOT.parent/'FJSP-Heuristic-Research/.env.leafapi.local')
        wire=WireRecorder(JsonCandidateTransport(config(p)),DIRECTORY/'wire_responses',verify=check)
        transport=DeadlineTransport(wire,deadline)
        journal=AttemptJournal(DIRECTORY/'API_attempts.json',config=config(p),context=sha(DIRECTORY/'Execution_binding.json'),
                               phase='cross-feedback-ab',transport=transport)
        if not (DIRECTORY/'Account_start.json').exists():
            q=metadata('start',wire.secret)
            if q.get('quota',{}).get('total_available',1)<=0:raise BudgetStop('API account balance insufficient')
        event('run_started',deadline=deadline)
        while state['cursor']<len(plans):
            check();validate_state(state,plans)
            if time.time()>=deadline:
                state['phase']='deadline_partial';break
            if (DIRECTORY/'Pause_request.json').exists():state['phase']='paused_at_boundary';break
            task=plans[state['cursor']];id=task['task_id'];beg=clock()
            entry=state['tasks'].setdefault(id,{**task,'status':'request_started','started':beg})
            write(DIRECTORY/'checkpoint.json',state);prompt=(BASE/'prompts'/(id+'.txt')).read_text()
            record=journal.request(id,prompt,kind='U')
            if journal.data['halt_reason']:raise BudgetStop(journal.data['halt_reason'])
            entry['generation_status']=record['status'];entry['attempts']=len(record['attempt_ids'])
            if record['status']!='completed':entry.update(status='transport_failed',fitness=None)
            else:
                response=DIRECTORY/'responses'/(id+'.json');response.parent.mkdir(exist_ok=True)
                write(response,record)  # first complete response durable BEFORE parsing/quality
                try:child=parse_response(record['text'],kind='U',interface_version=INTERFACE,member_count=10)
                except CandidateError as exc:entry.update(status='parse_invalid',fitness=None,error=str(exc))
                else:
                    entry['candidate']=asdict(child);key=child.key
                    if key in state['evaluations']:
                        cached=state['evaluations'][key]
                        if cached['status']!='completed':raise BudgetStop('unknown cached evaluation')
                        result=read(DIRECTORY/cached['result_path']);entry['status']='cache'
                    else:
                        result=evaluate(child,key,state,p,b);entry['status']='evaluated'
                    entry.update(valid=result['valid'],fitness=result['fitness'],evaluation_key=key)
            end=clock();gap=(end['wall']-beg['wall'])-(end['monotonic']-beg['monotonic'])
            if abs(gap)>2:
                entry['clock_quarantined']=True;entry['certified_comparison_eligible']=False
                write(DIRECTORY/'checkpoint.json',state)
                raise BudgetStop('candidate generation/evaluation clock gap; quarantine for manual audit')
            entry['finished']=end;state['cursor']+=1;write(DIRECTORY/'checkpoint.json',state)
            event('task_committed',id=id,status=entry['status'],cursor=state['cursor'])
        else:state['phase']='completed'
        write(DIRECTORY/'checkpoint.json',state);normal=True
    except BaseException as exc:
        state['phase']='stopped';write(DIRECTORY/'checkpoint.json',state)
        write(DIRECTORY/'Stop.json',{'error_type':type(exc).__name__,'error':str(exc)[:1000],'at':clock(),'automatic_retry':False})
        event('stopped',error_type=type(exc).__name__,error=str(exc)[:300])
    finally:
        if 'wire' in locals():metadata('end',wire.secret)
        if keepawake is not None:
            keepawake.terminate()
            try:keepawake.wait(timeout=2)
            except subprocess.TimeoutExpired:keepawake.kill();keepawake.wait()
        write(DIRECTORY/'End_summary.json',{'phase':state['phase'],'cursor':state['cursor'],'end':clock(),
            'task_count':len(state['tasks']),'new_unique_evaluations':len(state['evaluations']),
            'lock_retained':not normal,'caffeinate_cleaned':keepawake is not None})
        if normal:lock.unlink()
        from tools.cross_feedback_ab_execution_report import report
        report()


def detach(command,log,cwd=ROOT,env=None):
    with Path(log).open('ab',buffering=0) as out:
        return subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=out,
                                start_new_session=True,close_fds=True).pid


def launch():
    check()
    if any((DIRECTORY/n).exists() for n in ('Launch_identity.json','Run_clock.json','End_summary.json','.execution.lock')):
        raise BudgetStop('one-shot launch already started/unknown; no implicit replay')
    env={**os.environ,'PYTHONPATH':str(ROOT/'code')+':'+str(ROOT),'PYTHONDONTWRITEBYTECODE':'1'}
    pid=detach([sys.executable,'-B','-c','from '+MODULE+' import run; run()'],DIRECTORY/'Console.log',env=env)
    write(DIRECTORY/'Launch_identity.json',{'pid':pid,'launcher_pid':os.getpid(),'at':clock(),'method':'new session, files not pipes; SIGHUP ignored in worker'})
    print(json.dumps({'launched_pid':pid,'directory':str(DIRECTORY)}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',choices=('accept','bind','check','launch','run'))
    args=parser.parse_args()
    if args.stage=='accept':accept()
    elif args.stage=='bind':bind()
    elif args.stage=='check':check()
    elif args.stage=='launch':launch()
    else:importlib.import_module(MODULE).run()


if __name__=='__main__':main()
