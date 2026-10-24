"""Independent, capped T30 supplemental evaluation. No model/provider paths.

Reuses frozen H compilation and SELECT/WS scheduling kernel. Stages: accept,
prepare, check, run, report. Old runs are read-only; no cache credit for nine
contemporaneous full evaluations. Completed reservations are never repeated.
"""
import argparse
from dataclasses import asdict
import importlib
import inspect
import multiprocessing as mp
import os
from pathlib import Path
import random
import resource
from statistics import fmean
import sys
import time
import types

from fjsp_usage.baseline_supplemental import VERSION,specs
from fjsp_usage.baseline_supplemental.lifecycle import collect,classify
from fjsp_usage.baseline_supplemental.validation import ledger,compare_historical
from fjsp_usage.baseline_a.policies import policy
from fjsp_usage.baseline_a.validation import validate_result
from fjsp_usage.fusion_v2.execution import construct_fusion_schedule
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.locking import RunLock
from tools import tier2_baseline_a as b

v2=b.v2;ROOT=b.ROOT;BASE=b.DEFAULT
DEFAULT=ROOT/'runs/baseline-a-supplemental-T30-seed501-20261024-v1'
REPORT=ROOT/'reports'/DEFAULT.name
AUDIT=ROOT/'reports/baseline-a-provenance-timeout-audit-20261024-v1'
MODULES=('fjsp_usage.baseline_supplemental','fjsp_usage.baseline_supplemental.lifecycle',
         'fjsp_usage.baseline_supplemental.validation','tools.baseline_a_supplemental',
         'tools.baseline_a_supplemental_report')


def guard(directory):
    rows=v2.read(BASE/'Protocol.json')['instances']
    roots=(directory,BASE,b.old.DEFAULT,b.old.v3.DEFAULT,v2.DEFAULT)
    return v2.local_guard([ROOT/'data/fjsp'/r['file'] for r in rows]+
                         [root/r['relative_path'] for root in roots for r in rows])


def witness(p):
    rows=b.witness(p)['modules']
    for name in MODULES:
        module=importlib.import_module(name);path=Path(module.__file__).resolve()
        if v2.sha(path)!=p['source_files'][str(path.relative_to(ROOT))]:raise ValueError('T30 source mismatch')
        code=compile(path.read_bytes(),str(path),'exec',dont_inherit=True,optimize=0)
        defs={c.co_name:c for c in code.co_consts if isinstance(c,types.CodeType)};functions={}
        for key,fn in vars(module).items():
            if inspect.isfunction(fn) and (fn.__module__==name or key in defs):
                if key not in defs or v2.code_identity(fn.__code__)!=v2.code_identity(defs[key]):
                    raise ValueError('T30 loaded function mismatch: '+name+'.'+key)
                functions[key]=v2.code_identity(fn.__code__)
        rows[name]={'file':str(path),'source_sha256':v2.sha(path),'loaded_functions':functions}
    from fjsp_usage.baseline_supplemental import lifecycle
    if (lifecycle.WAIT,lifecycle.GRACE)!=(30,2.0):raise ValueError('loaded lifecycle constants changed')
    return {'pid':os.getpid(),'modules':rows,'identity':digest(rows)}


def accept():
    """Run only synthetic/offline tests; no formal train solves."""
    import unittest
    from tests import test_baseline_supplemental as tests
    from tests.test_baseline_a import StaticTests
    if (REPORT/'Offline_acceptance.json').exists():raise ValueError('acceptance evidence exists; do not overwrite')
    REPORT.mkdir(exist_ok=True)
    suite=unittest.defaultTestLoader.loadTestsFromModule(tests)
    # Essential V1 regression and cached H01 matrix replay, not old lifecycle runs.
    for name in ('test_single_raw_scores_and_double_independent_normalization',
                 'test_native_single_and_v1_two_member_deterministic_compatibility',
                 'test_H01_all21_cache_and_recorded_matrix_v1_replay'):
        suite.addTest(StaticTests(name))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    files={str(Path(importlib.import_module(n).__file__).resolve().relative_to(ROOT)) for n in MODULES}
    files.update(('tests/test_baseline_supplemental.py','docs/BASELINE_A_SUPPLEMENTAL_T30.md',
                  'experiments/tier2/baseline_supplemental/run.py'))
    receipt={'passed':result.wasSuccessful(),'tests_run':result.testsRun,'failures':len(result.failures),
        'errors':len(result.errors),'files':{n:v2.sha(ROOT/n) for n in sorted(files)},
        'mock_receipts':tests.RECEIPTS,'formal_train_solves':0,'API_requests':0,
        'scope':'Synthetic process messages/toy schedules +recorded H01 matrix V1 replay; no train scheduling'}
    atomic_json(REPORT/'Offline_acceptance.json',receipt)
    if not receipt['passed']:raise ValueError('offline acceptance failed')


def prepare(directory):
    if directory.exists() or directory.parent!=ROOT/'runs':raise ValueError('new direct runs child only')
    original=b.check(BASE);oldstate=v2.read(BASE/'checkpoint.json');b.validate_ledger(oldstate,original,v2.read,v2.sha,BASE)
    acceptance=v2.read(REPORT/'Offline_acceptance.json')
    if not acceptance['passed']:raise ValueError('offline gate failed')
    for n,h in acceptance['files'].items():
        if v2.sha(ROOT/n)!=h:raise ValueError('accepted implementation changed: '+n)
    directory.mkdir();(directory/'inputs/train').mkdir(parents=True);(directory/'evidence').mkdir()
    (directory/'H_frozen.json').write_bytes((BASE/'H_frozen.json').read_bytes())
    for r in original['instances']:(directory/r['relative_path']).write_bytes((BASE/r['relative_path']).read_bytes())
    sources={**original['source_files'],**acceptance['files']}
    protected=dict(original['protected_files'])
    for root in (BASE,b.REPORT,AUDIT):
        for path in sorted(root.rglob('*')):
            if path.is_file():protected[str(path.relative_to(ROOT))]=v2.sha(path)
    protected[str((REPORT/'Offline_acceptance.json').relative_to(ROOT))]=v2.sha(REPORT/'Offline_acceptance.json')
    historical={id:{'path':str((BASE/e['result_path']).relative_to(ROOT)),'sha256':e['result_sha256']}
                for id,e in oldstate['strategies'].items()}
    p={'version':VERSION,'base_commit':'df28b3de1211efee9c973f49e355af074ec94a1c','seed':501,
       'strategies':specs(),'instances':original['instances'],'H_order':original['H_order'],
       'H_sha256':v2.sha(directory/'H_frozen.json'),'source_files':sources,'protected_files':protected,
       'historical_results':historical,'evaluation_cap':189,'solve_pass_cap':378,'API_cap':0,
       'instance_result_wait_seconds':30,'normal_exit_grace_seconds':2.,'retries':0,
       'deadline_scope':'complete recv/deserialisation <=30s; first wait includes child startup; two solves and row delivery share deadline; final after identity before row send; exit grace only after ALL rows',
       'change_from_draft':'Reader thread bounds complete recv, unlike old poll/recv soft deadline. No late row accepted; unresolved reader is stop. No changes to scientific kernel.',
       'science':'frozen H10/train21; V1 raw single SELECT and independent current-action minmax columns .5/.5 WS; original legal/tie rules, unrounded LB and complete mean(-Cmax/LB)',
       'failure':'any failed instance =>full Fitness null; confirmed timeout invalid/continue; unknown PID/reader/source/exit/budget or historical/scientific mismatch STOP; no retries',
       'diagnostics':'phase timestamps and physical/commit hashes within original two solves; no extra scheduling or H calls',
       'cache':'no cache credit for nine new strategies; historical caches are read-only references; composite ranking labels T15/T30 sources',
       'authorization':'user current supplemental continuous nine fixed full21/2pass, max189/378, no LLM/holdout/evolution; only design future static search'}
    atomic_json(directory/'Protocol.json',p);(directory/'Protocol.sha256').write_text(v2.sha(directory/'Protocol.json')+'\n')
    atomic_json(directory/'Expected_loaded_identity.json',witness(p))
    atomic_json(directory/'checkpoint.json',{'protocol_sha256':v2.sha(directory/'Protocol.json'),'phase':'prepared','strategies':{}})
    check(directory)


def check(directory):
    p=v2.read(directory/'Protocol.json')
    if v2.sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip():raise ValueError('protocol changed')
    if (p['version']!=VERSION or p['seed']!=501 or p['strategies']!=specs()
        or (p['evaluation_cap'],p['solve_pass_cap'],p['API_cap'],p['instance_result_wait_seconds'],p['normal_exit_grace_seconds'],p['retries'])!=(189,378,0,30,2.,0)):
        raise ValueError('frozen nine-strategy T30 scope mismatch')
    for n,h in {**p['source_files'],**p['protected_files']}.items():
        if v2.sha(ROOT/n)!=h:raise ValueError('source/evidence identity mismatch: '+n)
    if v2.sha(directory/'H_frozen.json')!=p['H_sha256']:raise ValueError('H asset changed')
    frozen=v2.read(directory/'H_frozen.json')
    if [m['candidate']['key'] for m in frozen['members']]!=p['H_order']:raise ValueError('H order changed')
    for r in p['instances']:
        path=directory/r['relative_path']
        if not path.resolve().is_relative_to(directory/'inputs/train') or v2.sha(path)!=r['sha256']:raise ValueError('train changed')
    if witness(p)['identity']!=v2.read(directory/'Expected_loaded_identity.json')['identity']:raise ValueError('loaded identity mismatch')
    return p


def phase(stem,progress,key):
    progress[key]=time.monotonic();atomic_json(stem.with_suffix('.progress.json'),progress)


def worker(pipe,payload,members,instances,names,allowed_modes):
    directory=Path(payload['directory']);p=payload['protocol'];spec=payload['spec'];folder=directory/'evidence'/spec['id']
    network=v2.local_guard([directory/r['relative_path'] for r in p['instances']]);startup=time.monotonic()
    try:
        atomic_json(folder/'before.json',witness(p));random.seed(501)
        rules=tuple(v2.compile_candidate(m) for m in members);usage=policy(spec)
        atomic_json(folder/'worker_ready.json',{'pid':os.getpid(),'startup_started':startup,'ready':time.monotonic()})
        for name,instance in zip(names,instances):
            stem=folder/Path(name).stem;started=time.monotonic();cpu=time.process_time()
            progress={'file':name,'first_started':True,'recheck_started':False,'completed':False,'worker_started':started}
            phase(stem,progress,'first_start');cost=[];t=time.perf_counter()
            first=construct_fusion_schedule(instance,rules,usage,cost=cost.append)
            single=time.perf_counter()-t;first_cost=list(cost);cost.clear()
            progress.update(first_completed=True,first_solve_seconds=single,recheck_started=True)
            phase(stem,progress,'first_end');phase(stem,progress,'recheck_start');t=time.perf_counter()
            second=construct_fusion_schedule(instance,rules,usage,cost=cost.append)
            recheck=time.perf_counter()-t;progress['recheck_solve_seconds']=recheck;phase(stem,progress,'recheck_end')
            if first!=second:raise ValueError('full solve/recheck disagreement')
            physical=v2.physical(first.schedule);second_physical=v2.physical(second.schedule)
            if physical!=second_physical:raise ValueError('physical recheck mismatch')
            phase(stem,progress,'consistency_and_physical_end')
            row={'file':name,'makespan':first.schedule.makespan,'lower_bound':first.lower_bound,'score':first.score,
                 'feasible':True,'captured_solves':2,'single_solve_seconds':single,'deterministic_recheck_seconds':recheck,
                 'single_h_calls':list(first.member_calls),'recheck_h_calls':list(second.member_calls),
                 'first_costs':{k:sum(c[k] for c in first_cost) for k in ('h_scoring_seconds','fusion_seconds')},
                 'recheck_costs':{k:sum(c[k] for c in cost) for k in ('h_scoring_seconds','fusion_seconds')},
                 'physical_schedule':physical,'physical_schedule_sha256':digest(physical),
                 'recheck_physical_schedule_sha256':digest(second_physical),'commit_sequence_sha256':digest(asdict(first.schedule)),
                 'instance_worker_seconds':time.monotonic()-started,'instance_CPU_seconds':time.process_time()-cpu,
                 'peak_RSS_bytes_macos':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'network_guard':dict(network)}
            atomic_json(stem.with_suffix('.result.json'),row);progress['completed']=True;phase(stem,progress,'result_write_end')
            if name==names[-1]:
                phase(stem,progress,'after_identity_start');atomic_json(folder/'after.json',witness(p));phase(stem,progress,'after_identity_end')
            phase(stem,progress,'send_start');pipe.send(row);phase(stem,progress,'send_end')
    except BaseException as exc:
        atomic_json(folder/'worker_failure.json',{'error_type':type(exc).__name__,'error':str(exc)})
        atomic_json(folder/'after.json',witness(p));pipe.send({'error_type':type(exc).__name__,'error':str(exc)})
    finally:
        try:
            if not (folder/'after.json').exists():atomic_json(folder/'after.json',witness(p))
            atomic_json(folder/'network_guard.json',network)
        finally:pipe.close()


def run(directory):
    try:
        p=check(directory)
        if (directory/'Stop.json').exists():raise ValueError('persistent stop; no automatic restart')
        state=v2.read(directory/'checkpoint.json');ledger(state,p,v2.read,v2.sha,directory)
        if state['phase']=='completed':
            print('ALREADY_COMPLETED_NO_NEW_EVALUATIONS',flush=True);return
        network=guard(directory)
        members=tuple(v2.checked_candidate(m['candidate'],'h') for m in v2.read(directory/'H_frozen.json')['members'])
        instances=tuple(v2.load_instance(directory/r['relative_path']) for r in p['instances']);names=tuple(r['file'] for r in p['instances'])
        for spec in specs():
            id=spec['id']
            if id in state['strategies']:continue
            check(directory);used=ledger(state,p,v2.read,v2.sha,directory)
            if used+21>189:raise ValueError('evaluation budget exceeded')
            folder=directory/'evidence'/id
            if folder.exists():raise ValueError('orphan evidence; cannot automatically repeat')
            folder.mkdir();state['phase']='running'
            state['strategies'][id]={'status':'reserved','reserved_evaluations':21,'reserved_solve_passes':42}
            atomic_json(directory/'checkpoint.json',state)
            expected={**p['source_files'],**p['protected_files']};start={n:v2.sha(ROOT/n) for n in expected};t=time.monotonic()
            rows,failure,life=collect(mp.get_context('spawn'),worker,{'directory':str(directory),'protocol':p,'spec':spec},
                members,instances,names,30,None,lambda r:atomic_json(folder/'lifecycle.json',r))
            result={'valid':failure is None,'fitness':fmean(r['score'] for r in rows) if failure is None else None,
                    'instances':rows,'total_instances':21,'primary_evaluation_seconds':time.monotonic()-t,**(failure or {})}
            atomic_json(folder/'raw_result.json',result);check(directory)
            boundary=classify(result,before=v2.read(folder/'before.json') if (folder/'before.json').exists() else None,
                after=v2.read(folder/'after.json') if (folder/'after.json').exists() else None,lifecycle=life,
                expected_identity=v2.read(directory/'Expected_loaded_identity.json')['identity'],expected_files=expected,
                start_files=start,end_files={n:v2.sha(ROOT/n) for n in expected},worker_failure=(folder/'worker_failure.json').exists())
            atomic_json(folder/'boundary.json',boundary)
            if boundary['decision']=='stop':raise ValueError('T30 boundary stop: '+boundary['reason'])
            validate_result(result,p['instances'],'modern')
            compare_historical(id,result,v2.read(ROOT/p['historical_results'][id]['path']))
            if result['valid'] and (not (folder/'network_guard.json').exists() or any(v2.read(folder/'network_guard.json').values())):
                raise ValueError('worker guard missing/violation')
            result['boundary']=boundary;atomic_json(folder/'result.json',result)
            state['strategies'][id].update(status='completed',valid=result['valid'],
                result_path=str((folder/'result.json').relative_to(directory)),result_sha256=v2.sha(folder/'result.json'))
            atomic_json(directory/'checkpoint.json',state)
            print({'strategy':id,'valid':result['valid'],'fitness':result['fitness'],'instances':len(rows),
                   'failed_instance':result.get('failed_instance'),'seconds':result['primary_evaluation_seconds']},flush=True)
        state['phase']='completed';atomic_json(directory/'checkpoint.json',state);atomic_json(directory/'Network_guard.json',network)
        ledger(state,p,v2.read,v2.sha,directory)
    except BaseException as exc:
        if not (directory/'Stop.json').exists():atomic_json(directory/'Stop.json',{'error_type':type(exc).__name__,'error':str(exc),'automatic_retry':False})
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',choices=('accept','prepare','check','run','report'))
    parser.add_argument('--run-dir',type=Path,default=DEFAULT);args=parser.parse_args();directory=args.run_dir.resolve()
    if directory.parent!=ROOT/'runs' or directory.name!=DEFAULT.name:raise ValueError('fixed supplemental run directory required')
    network=guard(directory)
    if args.stage=='accept':accept()
    elif args.stage=='prepare':prepare(directory);print('FROZEN',v2.sha(directory/'Protocol.json'))
    elif args.stage=='check':check(directory);print('PASS')
    else:
        with RunLock(directory):
            if args.stage=='run':run(directory)
            else:
                from tools.baseline_a_supplemental_report import report
                report(directory)
    if any(network.values()):raise ValueError('parent guard violation')


if __name__=='__main__':main()
