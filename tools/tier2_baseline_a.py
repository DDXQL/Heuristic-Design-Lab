"""Reusable static Baseline-A evaluator, frozen 10 singles +45 equal WS pairs.

No supplier imports, no new scheduling kernel, no holdout data. New solves reuse
V2 SELECT/WS and V4 lifecycle. All legacy records remain read-only.
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
import time
import types

from fjsp_usage.baseline_a import VERSION
from fjsp_usage.baseline_a.policies import specs,policy
from fjsp_usage.baseline_a.validation import validate_result,validate_ledger
from fjsp_usage.fusion_v2.execution import construct_fusion_schedule
from fjsp_usage.fusion_v4.lifecycle import collect,classify
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.locking import RunLock
from tools import fusion_v4_experiment as old
from tools.baseline_a_audit import audit_inputs,extract

v2=old.v2;ROOT=old.ROOT
DEFAULT=ROOT/'runs/tier2-baseline-a-train21-seed501-20261024-v1'
REPORT=ROOT/'reports'/DEFAULT.name
MODULES=('fjsp_usage.baseline_a','fjsp_usage.baseline_a.policies','fjsp_usage.baseline_a.validation',
         'tools.baseline_a_audit','tools.tier2_baseline_a','tools.tier2_baseline_a_report')


def witness(protocol):
    modules=old.witness(protocol)['modules']
    for name in MODULES:
        module=importlib.import_module(name);path=Path(module.__file__).resolve()
        if v2.sha(path)!=protocol['source_files'][str(path.relative_to(ROOT))]:raise ValueError('Baseline-A source mismatch')
        compiled=compile(path.read_bytes(),str(path),'exec',dont_inherit=True,optimize=0)
        definitions={c.co_name:c for c in compiled.co_consts if isinstance(c,types.CodeType)};functions={}
        for key,fn in vars(module).items():
            if inspect.isfunction(fn) and (fn.__module__==name or key in definitions):
                if key not in definitions or v2.code_identity(fn.__code__)!=v2.code_identity(definitions[key]):
                    raise ValueError('Baseline-A loaded function differs: '+name+'.'+key)
                functions[key]=v2.code_identity(fn.__code__)
        modules[name]={'file':str(path),'source_sha256':v2.sha(path),'loaded_functions':functions}
    return {'pid':os.getpid(),'modules':modules,'identity':digest(modules)}


def train_guard(directory):
    instances=v2.read(old.DEFAULT/'Protocol.json')['instances']
    paths=[ROOT/'data/fjsp'/r['file'] for r in instances]
    for root in (directory,old.DEFAULT,old.v3.DEFAULT,v2.DEFAULT):
        paths.extend(root/r['relative_path'] for r in instances)
    return v2.local_guard(paths)


def audit():
    path=REPORT/'Cache_audit.json'
    if path.exists():raise ValueError('audit already exists; do not overwrite frozen evidence')
    REPORT.mkdir(exist_ok=True);guard=train_guard(DEFAULT);result=audit_inputs()
    if any(guard.values()):raise ValueError('audit accessed forbidden resource')
    result['network_guard']=guard;atomic_json(path,result)
    print(result['summary'])


def prepare(directory):
    if directory.exists() or directory.parent!=ROOT/'runs':raise ValueError('new independent direct runs child required')
    original=old.check(old.DEFAULT);a=v2.read(REPORT/'Cache_audit.json');tests=v2.read(REPORT/'Offline_tests.json')
    if tests['result']!='OK' or tests['tests_sha256']!=v2.sha(ROOT/'tests/test_baseline_a.py'):
        raise ValueError('offline tests gate not passed/current')
    for n,h in a['protected_files'].items():
        if v2.sha(ROOT/n)!=h:raise ValueError('audited evidence changed: '+n)
    directory.mkdir();(directory/'inputs/train').mkdir(parents=True);(directory/'evidence').mkdir();(directory/'cache').mkdir()
    for row in original['instances']:(directory/row['relative_path']).write_bytes((old.DEFAULT/row['relative_path']).read_bytes())
    (directory/'H_frozen.json').write_bytes((old.DEFAULT/'H_frozen.json').read_bytes())
    atomic_json(directory/'Historical_references.json',a['references'])
    cache={};entries={}
    for identifier,record in a['cache'].items():
        result=extract(v2.read(ROOT/record['source_file']),record['selector'])
        validate_result(result,original['instances'],record['level'])
        path=directory/'cache'/(identifier+'.json');atomic_json(path,result)
        cache[identifier]={**record,'result_path':str(path.relative_to(directory)),'sha256':v2.sha(path)}
        entries[identifier]={'status':'completed','origin':'cache','valid':True,'reserved_evaluations':0,'reserved_solve_passes':0,
            'result_path':cache[identifier]['result_path'],'result_sha256':cache[identifier]['sha256']}
    sources=dict(original['source_files'])
    for name in MODULES:
        path=Path(importlib.import_module(name).__file__).resolve();sources[str(path.relative_to(ROOT))]=v2.sha(path)
    for name in ('tests/test_baseline_a.py','docs/TIER2_BASELINE_A_PROTOCOL.md','experiments/tier2/baseline_a/run.py'):
        sources[name]=v2.sha(ROOT/name)
    protected={**original['protected_files'],**a['protected_files']}
    for path in (old.DEFAULT/'Protocol.json',old.DEFAULT/'Protocol.sha256',old.DEFAULT/'checkpoint.json',
                 REPORT/'Cache_audit.json',REPORT/'Offline_tests.json'):
        protected[str(path.relative_to(ROOT))]=v2.sha(path)
    p={'version':VERSION,'base_commit':'eace08f','seed':501,'strategies':specs(),'instances':original['instances'],
       'H_order':original['H_order'],'H_sha256':v2.sha(directory/'H_frozen.json'),
       'references_sha256':v2.sha(directory/'Historical_references.json'),
       'source_files':sources,'protected_files':protected,'cache':cache,
       'missing_strategies':a['missing_strategies'],'new_evaluation_cap':861,'new_solve_pass_cap':1722,
       'absolute_evaluation_cap':1155,'absolute_solve_pass_cap':2310,'LLM_API_cap':0,
       'result_wait_seconds':15,'normal_post_result_exit_grace_seconds':2.0,
       'science':'V1 raw-score single SELECT; two independent minmax columns +.5/.5 WS; no new operator/state/weight',
       'fitness':'arithmetic mean of all21 -Cmax/LB; unrounded existing LB; any failure null, no prefix fitness',
       'cache_contract':a['cache_evidence_limit'],
       'new_timeout_contract':'V4 original poll15; two passes share instance deadline; only confirmed terminated ordinary timeout invalid/continue',
       'stop_contract':'source/loaded identity mismatch, unknown process terminal, unknown reservation, budget mismatch stops; no retry or timeout extension',
       'diagnostics':'no extra solves; no full matrices; physical and commit hashes/cost captured during original two passes',
       'Oracle':'A3 posthoc per-instance best of ten complete certified single H only; diagnostic, not online or global dynamic upper bound',
       'authorization':'user Baseline-A continuous local static evaluation/report/commit/push; no LLM/evolution/holdout'}
    atomic_json(directory/'Protocol.json',p);(directory/'Protocol.sha256').write_text(v2.sha(directory/'Protocol.json')+'\n')
    atomic_json(directory/'Expected_loaded_identity.json',witness(p))
    atomic_json(directory/'checkpoint.json',{'protocol_sha256':v2.sha(directory/'Protocol.json'),'phase':'prepared','strategies':entries})
    check(directory)


def check(directory):
    p=v2.read(directory/'Protocol.json')
    if v2.sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip():raise ValueError('protocol hash changed')
    if (p['version']!=VERSION or p['seed']!=501 or p['strategies']!=specs()
        or (p['new_evaluation_cap'],p['new_solve_pass_cap'],p['absolute_evaluation_cap'],p['absolute_solve_pass_cap'],p['LLM_API_cap'])!=(861,1722,1155,2310,0)
        or (p['result_wait_seconds'],p['normal_post_result_exit_grace_seconds'])!=(15,2.0)):
        raise ValueError('Baseline-A fixed scope mismatch')
    original=old.check(old.DEFAULT)
    if p['instances']!=original['instances'] or p['H_order']!=original['H_order']:raise ValueError('train/H identity changed')
    if p['missing_strategies']!=[s for s in specs() if s['id'] not in p['cache']] or len(p['cache'])!=14:
        raise ValueError('cache/missing enumeration mismatch')
    for n,h in {**p['source_files'],**p['protected_files']}.items():
        if v2.sha(ROOT/n)!=h:raise ValueError('frozen source/asset changed: '+n)
    for name,key in (('H_frozen.json','H_sha256'),('Historical_references.json','references_sha256')):
        if v2.sha(directory/name)!=p[key]:raise ValueError('copied asset changed')
    for r in p['instances']:
        path=directory/r['relative_path']
        if not path.resolve().is_relative_to(directory/'inputs/train') or v2.sha(path)!=r['sha256']:
            raise ValueError('train copy hash/path mismatch')
    for row in p['cache'].values():
        if v2.sha(directory/row['result_path'])!=row['sha256']:raise ValueError('copied cache changed')
    if witness(p)['identity']!=v2.read(directory/'Expected_loaded_identity.json')['identity']:raise ValueError('loaded identity mismatch')
    return p


def worker(pipe,payload,members,instances,names,allowed_modes):
    directory=Path(payload['directory']);p=payload['protocol'];spec=payload['spec'];folder=directory/'evidence'/spec['id']
    guard=v2.local_guard([directory/r['relative_path'] for r in p['instances']])
    try:
        atomic_json(folder/'before.json',witness(p));random.seed(501)
        rules=tuple(v2.compile_candidate(m) for m in members);usage=policy(spec)
        for name,instance in zip(names,instances):
            stem=folder/Path(name).stem;started=time.monotonic();cpu=time.process_time()
            progress={'file':name,'first_started':True,'recheck_started':False,'completed':False}
            atomic_json(stem.with_suffix('.progress.json'),progress);cost=[];t=time.perf_counter()
            first=construct_fusion_schedule(instance,rules,usage,cost=cost.append)
            single=time.perf_counter()-t;first_cost=list(cost);cost.clear()
            progress.update(first_completed=True,recheck_started=True);atomic_json(stem.with_suffix('.progress.json'),progress)
            t=time.perf_counter();second=construct_fusion_schedule(instance,rules,usage,cost=cost.append)
            recheck=time.perf_counter()-t
            if first!=second:raise ValueError('full solve/recheck disagreement')
            physical=v2.physical(first.schedule);second_physical=v2.physical(second.schedule)
            if physical!=second_physical:raise ValueError('physical recheck mismatch')
            row={'file':name,'makespan':first.schedule.makespan,'lower_bound':first.lower_bound,'score':first.score,
                'feasible':True,'captured_solves':2,'single_solve_seconds':single,'deterministic_recheck_seconds':recheck,
                'single_h_calls':list(first.member_calls),'recheck_h_calls':list(second.member_calls),
                'first_costs':{k:sum(c[k] for c in first_cost) for k in ('h_scoring_seconds','fusion_seconds')},
                'recheck_costs':{k:sum(c[k] for c in cost) for k in ('h_scoring_seconds','fusion_seconds')},
                'physical_schedule':physical,'physical_schedule_sha256':digest(physical),
                'recheck_physical_schedule_sha256':digest(second_physical),'commit_sequence_sha256':digest(asdict(first.schedule)),
                'instance_worker_seconds':time.monotonic()-started,'instance_CPU_seconds':time.process_time()-cpu,
                'peak_RSS_bytes_macos':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'network_guard':dict(guard)}
            atomic_json(stem.with_suffix('.result.json'),row);progress['completed']=True;atomic_json(stem.with_suffix('.progress.json'),progress)
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
    try:
        p=check(directory)
        if (directory/'Stop.json').exists():raise ValueError('persistent stop; no automatic restart')
        state=v2.read(directory/'checkpoint.json');validate_ledger(state,p,v2.read,v2.sha,directory)
        guard=train_guard(directory)
        members=tuple(v2.checked_candidate(m['candidate'],'h') for m in v2.read(directory/'H_frozen.json')['members'])
        instances=tuple(v2.load_instance(directory/r['relative_path']) for r in p['instances']);names=tuple(r['file'] for r in p['instances'])
        for spec in specs():
            if spec['id'] in state['strategies']:continue
            check(directory);used=validate_ledger(state,p,v2.read,v2.sha,directory)
            if used+21>p['new_evaluation_cap']:raise ValueError('evaluation budget exceeded')
            folder=directory/'evidence'/spec['id']
            if folder.exists():raise ValueError('orphan evidence; no automatic repeat')
            folder.mkdir();state['phase']='running'
            state['strategies'][spec['id']]={'status':'reserved','origin':'new','reserved_evaluations':21,'reserved_solve_passes':42}
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
            if boundary['decision']=='stop':raise ValueError('Baseline-A boundary stop: '+boundary['reason'])
            validate_result(result,p['instances'],'modern')
            if failure and boundary['decision']!='candidate_invalid_continue':raise ValueError('unclassified strategy failure')
            network=folder/'network_guard.json'
            if result['valid'] and (not network.exists() or any(v2.read(network).values())):raise ValueError('worker guard missing/failure')
            result['boundary']=boundary;atomic_json(folder/'result.json',result)
            state['strategies'][spec['id']].update(status='completed',valid=result['valid'],result_path=str((folder/'result.json').relative_to(directory)),
                result_sha256=v2.sha(folder/'result.json'))
            atomic_json(directory/'checkpoint.json',state)
            print({'strategy':spec['id'],'valid':result['valid'],'fitness':result['fitness'],'complete_instances':len(rows),
                'failed_instance':result.get('failed_instance'),'seconds':result['primary_evaluation_seconds'],'boundary':boundary['decision']},flush=True)
        state['phase']='completed';atomic_json(directory/'checkpoint.json',state);atomic_json(directory/'Network_guard.json',guard)
        validate_ledger(state,p,v2.read,v2.sha,directory)
    except BaseException as exc:
        if not (directory/'Stop.json').exists():atomic_json(directory/'Stop.json',{'error_type':type(exc).__name__,'error':str(exc),'automatic_retry':False})
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',choices=('audit','prepare','check','run','report'))
    parser.add_argument('--run-dir',type=Path,default=DEFAULT);args=parser.parse_args();directory=args.run_dir.resolve()
    if directory.parent!=ROOT/'runs':raise ValueError('direct runs child required')
    if args.stage=='audit':audit()
    elif args.stage=='prepare':prepare(directory);print('PREPARED',directory)
    elif args.stage=='check':check(directory);print('PASS',directory)
    else:
        with RunLock(directory):
            if args.stage=='run':run(directory)
            else:
                from tools.tier2_baseline_a_report import report
                print(report(directory))
