"""Six fixed progress switches, independent source and budget protocol.

Reuses V3 scheduling/Borda and all legacy identity checks. Only lifecycle normal
exit grace changes; no source monkeypatch, old result adoption or H05 reevaluation.
"""
import argparse
from dataclasses import asdict
import gzip
import importlib
import inspect
import json
import multiprocessing as mp
import os
from pathlib import Path
import random
import resource
from statistics import fmean
import time
import types

from fjsp_usage.fusion_v4 import VERSION
from fjsp_usage.fusion_v4.policies import specs,progress_policy
from fjsp_usage.fusion_v4.lifecycle import collect,classify
from fjsp_usage.fusion_v3.execution import construct_rank_schedule
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.locking import RunLock
from tools import fusion_v3_experiment as v3

v2=v3.v2;ROOT=v3.ROOT
DEFAULT=ROOT/'runs/fusion-v4-progress-switch-seed501-20261024-v1'
REPORT=ROOT/'reports'/DEFAULT.name
MODULES=('fjsp_usage.fusion_v4','fjsp_usage.fusion_v4.lifecycle','fjsp_usage.fusion_v4.policies',
         'tools.fusion_v4_experiment','tools.fusion_v4_report')


def witness(protocol):
    rows=v3.witness(protocol)['modules']
    for name in MODULES:
        module=importlib.import_module(name);path=Path(module.__file__).resolve()
        if v2.sha(path)!=protocol['source_files'][str(path.relative_to(ROOT))]:raise ValueError('V4 source hash mismatch')
        compiled=compile(path.read_bytes(),str(path),'exec',dont_inherit=True,optimize=0)
        definitions={c.co_name:c for c in compiled.co_consts if isinstance(c,types.CodeType)};functions={}
        for key,fn in vars(module).items():
            if inspect.isfunction(fn) and (fn.__module__==name or key in definitions):
                if key not in definitions or v2.code_identity(fn.__code__)!=v2.code_identity(definitions[key]):
                    raise ValueError('V4 loaded function differs: '+name+'.'+key)
                functions[key]=v2.code_identity(fn.__code__)
        rows[name]={'file':str(path),'source_sha256':v2.sha(path),'loaded_functions':functions}
    return {'pid':os.getpid(),'modules':rows,'identity':digest(rows)}


def accept():
    from tests.test_fusion_v4 import delayed_cleanup_worker
    if (REPORT/'Lifecycle_acceptance.json').exists():raise ValueError('acceptance evidence already exists')
    REPORT.mkdir(exist_ok=True)
    old_receipts=[];new_receipts=[]
    old_rows,old_failure,old_life=v2.collect_with_lifecycle(mp.get_context('spawn'),delayed_cleanup_worker,
        None,(),(),('MOCK',),15,None,lambda r:old_receipts.append(dict(r)))
    new_rows,new_failure,new_life=collect(mp.get_context('spawn'),delayed_cleanup_worker,
        None,(),(),('MOCK',),15,None,lambda r:new_receipts.append(dict(r)))
    passed=(old_rows==new_rows==[{'file':'MOCK','value':7}] and old_failure is None and new_failure is None
            and old_life['exitcode']==-15 and new_life['exitcode']==0 and new_life['alive'] is False
            and new_life['deadline_seconds']==15 and new_life['exit_grace_used'] is True)
    evidence={'passed':passed,'scope':'real spawned synthetic row +0.25s post-send cleanup; no FJSP/API',
        'old_receipts':old_receipts,'new_receipts':new_receipts,
        'frozen_files':{n:v2.sha(ROOT/n) for n in ('code/fjsp_usage/fusion_v4/lifecycle.py',
            'tests/test_fusion_v4.py','tools/b1_timeout_boundary.py')},
        'contract':'poll15 unchanged;2s grace starts only after all rows; normal exit0/end identity still required'}
    atomic_json(REPORT/'Lifecycle_acceptance.json',evidence)
    if not passed:raise ValueError('lifecycle acceptance failed; no formal experiment allowed')
    print({'passed':passed,'old_exitcode':old_life['exitcode'],'new_exitcode':new_life['exitcode'],
           'new_exit_wait_seconds':new_life['exit_wait_observed_seconds']})


def prepare(directory):
    if directory.exists() or directory.parent!=ROOT/'runs':raise ValueError('new independent runs child required')
    source=v3.check(v3.DEFAULT);a=v2.read(REPORT/'Lifecycle_acceptance.json');tests=v2.read(REPORT/'Offline_tests.json')
    if not a['passed'] or tests['result']!='OK':raise ValueError('offline acceptance gate not passed')
    for name,h in a['frozen_files'].items():
        if v2.sha(ROOT/name)!=h:raise ValueError('acceptance source changed')
    if tests['tests_sha256']!=v2.sha(ROOT/'tests/test_fusion_v4.py'):raise ValueError('tests source changed')
    checkpoint=v2.read(v3.DEFAULT/'checkpoint.json');accepted=checkpoint['strategies']['H0_H1_BORDA']
    if accepted['status']!='completed' or not accepted['valid']:raise ValueError('certified H01 Borda baseline missing')
    borda_path=v3.DEFAULT/accepted['result_path']
    if v2.sha(borda_path)!=accepted['result_sha256']:raise ValueError('Borda baseline changed')
    borda=v2.read(borda_path);v2.check_result(borda,[r['file'] for r in source['instances']])
    ws_path=v2.DEFAULT/'evidence/H0_H1_WEIGHTED_SUM/result.json'
    ws=v2.read(ws_path);v2.check_result(ws,[r['file'] for r in source['instances']])
    if not ws['valid'] or not borda['valid']:raise ValueError('complete fixed baselines required')
    directory.mkdir();(directory/'inputs/train').mkdir(parents=True);(directory/'evidence').mkdir()
    for name in ('H_frozen.json','References.json'):(directory/name).write_bytes((v3.DEFAULT/name).read_bytes())
    for row in source['instances']:(directory/row['relative_path']).write_bytes((v3.DEFAULT/row['relative_path']).read_bytes())
    source_files=dict(source['source_files'])
    for name in MODULES:
        path=Path(importlib.import_module(name).__file__).resolve();source_files[str(path.relative_to(ROOT))]=v2.sha(path)
    for name in ('tests/test_fusion_v4.py','docs/FUSION_V4_PROGRESS_PROTOCOL.md','experiments/tier2/fusion_v4/run.py'):
        source_files[name]=v2.sha(ROOT/name)
    protected=dict(source['protected_files'])
    for path in (v3.DEFAULT/'Protocol.json',v3.DEFAULT/'Protocol.sha256',v3.DEFAULT/'checkpoint.json',
                 v3.DEFAULT/'Stop.json',v3.DEFAULT/'H_frozen.json',v3.DEFAULT/'References.json',borda_path,ws_path,
                 REPORT/'Lifecycle_acceptance.json',REPORT/'Offline_tests.json'):
        protected[str(path.relative_to(ROOT))]=v2.sha(path)
    for name in ('before.json','after.json','boundary.json','lifecycle.json','raw_result.json'):
        path=v3.DEFAULT/'evidence/H0_H5_BORDA'/name
        protected[str(path.relative_to(ROOT))]=v2.sha(path)
    p={'version':VERSION,'base_commit':'270e068','seed':501,'strategies':specs(),'instances':source['instances'],
        'H_order':source['H_order'],'source_files':source_files,'protected_files':protected,
        'H_sha256':v2.sha(directory/'H_frozen.json'),'References_sha256':v2.sha(directory/'References.json'),
        'source_V3_protocol_sha256':v2.sha(v3.DEFAULT/'Protocol.json'),
        'fixed_baselines':{'WS':{'path':str(ws_path.relative_to(ROOT)),'sha256':v2.sha(ws_path)},
                           'BORDA':{'path':str(borda_path.relative_to(ROOT)),'sha256':v2.sha(borda_path)}},
        'evaluation_cap':126,'solve_pass_cap':252,'API_cap':0,'instance_result_wait_seconds':15,
        'normal_exit_grace_seconds':2.0,'failure_cleanup_join_seconds':.05,
        'switch_rule':'progress<threshold uses first, equality/greater uses late; one nominal switch per instance',
        'constant_conditions':'H0/H1 .5/.5; old kernel, raw-score midrank Borda, independent minmax WS, same legal order/LB/Fitness',
        'authorization':'user next-round continuous lifecycle repair/mock +exact six progress policies; no LLM, evolution, holdout or new operator',
        'acceptance':'complete rows +after identity +exit0; extending post-result shutdown never extends acceptance of results',
        'failure':'full Fitness null on any failure; confirmed timeout invalid; unknown identity/terminal/budget stops; no retries',
        'old_quarantine':'H0/H5 remains rejected; no adoption, reevaluation or budget transfer',
        'diagnostics':'first-pass matrices only; same-state recombination and shared-prefix first divergence; no extra solves/H calls',
        'analysis':'train21 descriptive; six predeclared comparisons, no posthoc threshold extension or confirmatory generalization'}
    atomic_json(directory/'Protocol.json',p);(directory/'Protocol.sha256').write_text(v2.sha(directory/'Protocol.json')+'\n')
    atomic_json(directory/'Expected_loaded_identity.json',witness(p))
    atomic_json(directory/'checkpoint.json',{'protocol_sha256':v2.sha(directory/'Protocol.json'),'phase':'prepared','strategies':{}})


def check(directory):
    p=v2.read(directory/'Protocol.json')
    if v2.sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip():raise ValueError('V4 protocol hash changed')
    if (p['version']!=VERSION or p['seed']!=501 or p['strategies']!=specs() or
        (p['evaluation_cap'],p['solve_pass_cap'],p['API_cap'],p['instance_result_wait_seconds'],p['normal_exit_grace_seconds'])!=(126,252,0,15,2.0)):
        raise ValueError('V4 fixed scope mismatch')
    original=v3.check(v3.DEFAULT)
    if p['instances']!=original['instances'] or p['H_order']!=original['H_order']:raise ValueError('H/train conditions changed')
    for name,h in {**p['source_files'],**p['protected_files']}.items():
        if v2.sha(ROOT/name)!=h:raise ValueError('frozen source/asset changed: '+name)
    for name,key in (('H_frozen.json','H_sha256'),('References.json','References_sha256')):
        if v2.sha(directory/name)!=p[key]:raise ValueError('copied asset changed')
    for row in p['instances']:
        path=(directory/row['relative_path']).resolve()
        if not path.is_relative_to(directory/'inputs/train') or v2.sha(path)!=row['sha256']:raise ValueError('train copy mismatch')
    if witness(p)['identity']!=v2.read(directory/'Expected_loaded_identity.json')['identity']:raise ValueError('V4 loaded identity mismatch')
    return p


def worker(pipe,payload,members,instances,names,allowed_modes):
    directory=Path(payload['directory']);p=payload['protocol'];spec=payload['spec'];folder=directory/'evidence'/spec['id']
    guard=v2.local_guard([directory/r['relative_path'] for r in p['instances']])
    try:
        atomic_json(folder/'before.json',witness(p));random.seed(501)
        rules=tuple(v2.compile_candidate(m) for m in members);policy=progress_policy(spec)
        for name,instance in zip(names,instances):
            stem=folder/Path(name).stem;started=time.monotonic();cpu=time.process_time()
            progress={'file':name,'first_started':True,'recheck_started':False,'completed':False}
            atomic_json(stem.with_suffix('.progress.json'),progress);traces=[];cost=[];t=time.perf_counter()
            first=construct_rank_schedule(instance,rules,policy,trace=traces.append,cost=cost.append)
            first_seconds=time.perf_counter()-t;first_cost=list(cost);cost.clear()
            progress.update(first_completed=True,first_solve_seconds=first_seconds,recheck_started=True)
            atomic_json(stem.with_suffix('.progress.json'),progress);t=time.perf_counter()
            second=construct_rank_schedule(instance,rules,policy,cost=cost.append);recheck_seconds=time.perf_counter()-t
            if first!=second:raise ValueError('dynamic full result mismatch')
            physical=v2.physical(first.schedule)
            if physical!=v2.physical(second.schedule):raise ValueError('physical recheck mismatch')
            trace_path=stem.with_suffix('.trace.jsonl.gz');t=time.perf_counter()
            with gzip.open(trace_path,'wt',encoding='utf-8',compresslevel=1) as handle:
                for trace in traces:handle.write(json.dumps(trace,separators=(',',':'),allow_nan=False)+'\n')
            operators=[d[0] for d in first.decisions]
            row={'file':name,'makespan':first.schedule.makespan,'lower_bound':first.lower_bound,'score':first.score,
                'feasible':True,'captured_solves':2,'single_solve_seconds':first_seconds,
                'deterministic_recheck_seconds':recheck_seconds,'trace_write_seconds':time.perf_counter()-t,
                'instance_worker_seconds':time.monotonic()-started,'instance_CPU_seconds':time.process_time()-cpu,
                'peak_RSS_native_units':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                'single_h_calls':list(first.member_calls),'recheck_h_calls':list(second.member_calls),
                'first_costs':{k:sum(c[k] for c in first_cost) for k in ('h_scoring_seconds','fusion_seconds')},
                'recheck_costs':{k:sum(c[k] for c in cost) for k in ('h_scoring_seconds','fusion_seconds')},
                'physical_schedule':physical,'physical_schedule_sha256':digest(physical),
                'recheck_physical_schedule_sha256':digest(v2.physical(second.schedule)),
                'commit_sequence_sha256':digest(asdict(first.schedule)),
                'trace_path':str(trace_path.relative_to(directory)),'trace_sha256':v2.sha(trace_path),
                'trace_states':len(traces),'network_guard':dict(guard),
                'operator_counts':{op:operators.count(op) for op in ('WEIGHTED_SUM','BORDA')},
                'operator_switches':sum(a!=b for a,b in zip(operators,operators[1:]))}
            atomic_json(stem.with_suffix('.result.json'),row);progress['completed']=True
            atomic_json(stem.with_suffix('.progress.json'),progress)
            if name==names[-1]:atomic_json(folder/'after.json',witness(p))
            pipe.send(row)
    except BaseException as exc:
        atomic_json(folder/'worker_failure.json',{'error_type':type(exc).__name__,'error':str(exc)})
        atomic_json(folder/'after.json',witness(p));pipe.send({'error_type':type(exc).__name__,'error':str(exc)})
    finally:
        try:
            if not (folder/'after.json').exists():atomic_json(folder/'after.json',witness(p))
            atomic_json(folder/'network_guard.json',guard)
        finally:pipe.close()


def run(directory):
    p=check(directory)
    if (directory/'Stop.json').exists():raise ValueError('persistent stop; no automatic retry')
    state=v2.read(directory/'checkpoint.json')
    if state['protocol_sha256']!=v2.sha(directory/'Protocol.json') or not set(state['strategies'])<={s['id'] for s in specs()}:
        raise ValueError('checkpoint identity/scope mismatch')
    for record in state['strategies'].values():
        if record['status']!='completed':raise ValueError('unknown reservation; do not repeat')
        if v2.sha(directory/record['result_path'])!=record['result_sha256']:raise ValueError('saved result changed')
    allowed=[path for row in p['instances'] for path in (directory/row['relative_path'],v3.DEFAULT/row['relative_path'],
        v2.DEFAULT/row['relative_path'],ROOT/'data/fjsp'/row['file'])]
    guard=v2.local_guard(allowed)
    members=tuple(v2.checked_candidate(r['candidate'],'h') for r in v2.read(directory/'H_frozen.json')['members'])
    instances=tuple(v2.load_instance(directory/r['relative_path']) for r in p['instances']);names=tuple(r['file'] for r in p['instances'])
    try:
        for spec in specs():
            if spec['id'] in state['strategies']:continue
            check(directory);folder=directory/'evidence'/spec['id']
            if folder.exists():raise ValueError('orphan evidence')
            folder.mkdir();state['phase']='running'
            state['strategies'][spec['id']]={'status':'reserved','reserved_evaluations':21,'reserved_solve_passes':42}
            if sum(r['reserved_evaluations'] for r in state['strategies'].values())>126:raise ValueError('budget exceeded')
            atomic_json(directory/'checkpoint.json',state)
            expected={**p['source_files'],**p['protected_files']};start={n:v2.sha(ROOT/n) for n in expected};t=time.monotonic()
            rows,failure,life=collect(mp.get_context('spawn'),worker,{'directory':str(directory),'protocol':p,'spec':spec},
                members,instances,names,15,None,lambda receipt:atomic_json(folder/'lifecycle.json',receipt))
            result={'valid':failure is None,'fitness':fmean(r['score'] for r in rows) if failure is None else None,
                'instances':rows,'total_instances':21,'primary_evaluation_seconds':time.monotonic()-t,**(failure or {})}
            atomic_json(folder/'raw_result.json',result);check(directory)
            boundary=classify(result,before=v2.read(folder/'before.json') if (folder/'before.json').exists() else None,
                after=v2.read(folder/'after.json') if (folder/'after.json').exists() else None,lifecycle=life,
                expected_identity=v2.read(directory/'Expected_loaded_identity.json')['identity'],expected_files=expected,
                start_files=start,end_files={n:v2.sha(ROOT/n) for n in expected},worker_failure=(folder/'worker_failure.json').exists())
            atomic_json(folder/'boundary.json',boundary)
            if boundary['decision']=='stop':raise ValueError('V4 boundary stop: '+boundary['reason'])
            v2.validate_rows(rows,p);v2.check_result(result,names)
            for row in rows:
                if v2.sha(directory/row['trace_path'])!=row['trace_sha256']:raise ValueError('trace changed')
                if row['operator_switches']!=1 or not all(row['operator_counts'].values()):raise ValueError('actual operator policy not verified')
            result['boundary']=boundary;atomic_json(folder/'result.json',result)
            state['strategies'][spec['id']].update(status='completed',valid=result['valid'],
                result_path=str((folder/'result.json').relative_to(directory)),result_sha256=v2.sha(folder/'result.json'))
            atomic_json(directory/'checkpoint.json',state)
            print(json.dumps({'strategy':spec['id'],'valid':result['valid'],'fitness':result['fitness'],
                'instances':len(rows),'primary_seconds':result['primary_evaluation_seconds'],'exit_wait_seconds':life['exit_wait_observed_seconds']}),flush=True)
        state['phase']='completed';atomic_json(directory/'checkpoint.json',state);atomic_json(directory/'Network_guard.json',guard)
    except BaseException as exc:
        atomic_json(directory/'Stop.json',{'error_type':type(exc).__name__,'error':str(exc),'automatic_retry':False});raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',choices=('accept','prepare','check','run','report'))
    parser.add_argument('--run-dir',type=Path,default=DEFAULT);args=parser.parse_args();directory=args.run_dir.resolve()
    if directory.parent!=ROOT/'runs':raise ValueError('direct runs child required')
    if args.stage=='accept':accept()
    elif args.stage=='prepare':prepare(directory);print('PREPARED',directory)
    elif args.stage=='check':check(directory);print('PASS',directory)
    else:
        with RunLock(directory):
            if args.stage=='run':run(directory)
            else:
                from tools.fusion_v4_report import report
                print(report(directory))
