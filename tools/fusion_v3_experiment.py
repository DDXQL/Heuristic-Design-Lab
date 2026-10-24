"""Independent Borda batch: <=3 strategies, 63 pairs,126 passes; no APIs.

Reuse frozen V2 data checks, compilation, lifecycle classification and guards.
V1/V2 modules are never monkeypatched. Unknown reservations always stop.
"""
import argparse
from collections import Counter,defaultdict
from dataclasses import asdict
import gzip
import importlib
import inspect
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import random
import resource
from statistics import fmean
import time
import types

from fjsp_usage.fusion_v3 import VERSION
from fjsp_usage.fusion_v3.execution import construct_rank_schedule,fixed_borda,fuse_rank
from fjsp_usage.fusion_v3.ranking import borda_scores,ws_certificate
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.locking import RunLock
from tools import fusion_v2_experiment as v2

ROOT=v2.ROOT
DEFAULT=ROOT/'runs/fusion-v3-borda-train21-seed501-20261024-v1'
DIAGNOSIS=ROOT/'reports'/DEFAULT.name/'diagnosis'
NEW_MODULES=('fjsp_usage.fusion_v3','fjsp_usage.fusion_v3.ranking','fjsp_usage.fusion_v3.execution',
             'tools.fusion_v3_experiment','tools.fusion_v3_diagnose','tools.fusion_v3_report')


def specs():
    return [{'id':f'H{a}_H{b}_BORDA','pair':[a,b],'operator':'BORDA'} for a,b in v2.PAIRS]


def witness(protocol):
    original=v2.source_witness(protocol)
    rows=original['modules']
    for name in NEW_MODULES:
        module=importlib.import_module(name);path=Path(module.__file__).resolve()
        if v2.sha(path)!=protocol['source_files'][str(path.relative_to(ROOT))]:
            raise ValueError('new loaded source hash mismatch: '+name)
        compiled=compile(path.read_bytes(),str(path),'exec',dont_inherit=True,optimize=0)
        definitions={c.co_name:c for c in compiled.co_consts if isinstance(c,types.CodeType)}
        functions={}
        for key,fn in vars(module).items():
            if inspect.isfunction(fn) and (fn.__module__==name or key in definitions):
                if key not in definitions or v2.code_identity(fn.__code__)!=v2.code_identity(definitions[key]):
                    raise ValueError('new loaded function mismatch: '+name+'.'+key)
                functions[key]=v2.code_identity(fn.__code__)
        rows[name]={'file':str(path),'source_sha256':v2.sha(path),'loaded_functions':functions}
    return {'pid':os.getpid(),'modules':rows,'identity':digest(rows)}


def prepare(directory):
    if directory.exists() or directory.parent!=ROOT/'runs':raise ValueError('new direct runs child required')
    source=v2.check(v2.DEFAULT)
    diagnosis=v2.read(DIAGNOSIS/'Diagnosis.json')
    if diagnosis['selected_mechanism']!='BORDA_MIDRANK_RAW':raise ValueError('behavior selection gate not passed')
    if diagnosis['source_protocol_sha256']!=v2.sha(v2.DEFAULT/'Protocol.json'):
        raise ValueError('diagnosis source protocol differs')
    directory.mkdir();(directory/'inputs/train').mkdir(parents=True);(directory/'evidence').mkdir()
    for name in ('H_frozen.json','References.json'):
        (directory/name).write_bytes((v2.DEFAULT/name).read_bytes())
    for row in source['instances']:
        path=directory/row['relative_path'];path.write_bytes((v2.DEFAULT/row['relative_path']).read_bytes())
    source_files=dict(source['source_files'])
    for module in NEW_MODULES:
        path=Path(importlib.import_module(module).__file__).resolve()
        source_files[str(path.relative_to(ROOT))]=v2.sha(path)
    for name in ('tests/test_fusion_v3.py','docs/FUSION_V3_BORDA_PROTOCOL.md','experiments/tier2/fusion_v3/run.py'):
        source_files[name]=v2.sha(ROOT/name)
    protected=dict(source['protected_files'])
    for path in (v2.DEFAULT/'Protocol.json',v2.DEFAULT/'Protocol.sha256',v2.DEFAULT/'checkpoint.json',
                 v2.DEFAULT/'H_frozen.json',v2.DEFAULT/'References.json'):
        protected[str(path.relative_to(ROOT))]=v2.sha(path)
    history={}
    checkpoint=v2.read(v2.DEFAULT/'checkpoint.json')
    for spec in v2.specs():
        path=v2.DEFAULT/checkpoint['strategies'][spec['id']]['result_path']
        if v2.sha(path)!=checkpoint['strategies'][spec['id']]['result_sha256']:
            raise ValueError('historical V2 result identity differs')
        history[spec['id']]={'path':str(path.relative_to(ROOT)),'sha256':v2.sha(path)}
        protected[str(path.relative_to(ROOT))]=v2.sha(path)
    for path in sorted(DIAGNOSIS.glob('*')):
        protected[str(path.relative_to(ROOT))]=v2.sha(path)
    p={'version':VERSION,'strategies':specs(),'seed':501,'instances':source['instances'],
       'operator':'BORDA_MIDRANK_RAW','points':'sum(two*strictly_lower + equal_count - one) over two raw columns',
       'tie':'exact raw score equality -> midrank; final first maximum in unchanged legal enumeration',
       'support':'exactly two equal positive indicators; .5/.5 fixed; previous member min support id',
       'normalization':'ordinal percentile; integer equivalent retained to avoid floating rank ties',
       'instance_timeout':15,'evaluation_cap':63,'solve_pass_cap':126,'API_cap':0,
       'source_V2_protocol_sha256':v2.sha(v2.DEFAULT/'Protocol.json'),'source_V2_directory':str(v2.DEFAULT),
       'source_files':source_files,'protected_files':protected,'history':history,'H_order':source['H_order'],
       'H_sha256':v2.sha(directory/'H_frozen.json'),'References_sha256':v2.sha(directory/'References.json'),
       'authorization':'user 2026-10-24 autonomous diagnosis/one mechanism/<=3 fixed strategies/63 evaluations/126 passes; no LLM, evolution or holdouts',
       'failure_policy':'any instance failure => complete Fitness null; no timeout reevaluation; unknown state/identity/budget stop',
       'metrics':'mean -Cmax/unrounded V5 LB; descriptive train21 results only',
       'diagnostics':'first-pass full states/matrices; offline same-state recombination; no additional solve/H calls',
       'cost_caveat':'same V2 traced-first/untraced-recheck boundaries; timeout is not pure fusion runtime'}
    atomic_json(directory/'Protocol.json',p);(directory/'Protocol.sha256').write_text(v2.sha(directory/'Protocol.json')+'\n')
    atomic_json(directory/'Expected_loaded_identity.json',witness(p))
    atomic_json(directory/'checkpoint.json',{'protocol_sha256':v2.sha(directory/'Protocol.json'),'phase':'prepared','strategies':{}})
    return p


def check(directory):
    p=v2.read(directory/'Protocol.json')
    if v2.sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip():raise ValueError('V3 protocol hash differs')
    if (p['version']!=VERSION or p['seed']!=501 or p['strategies']!=specs() or
        (p['evaluation_cap'],p['solve_pass_cap'],p['API_cap'],p['instance_timeout'])!=(63,126,0,15)):
        raise ValueError('V3 scope/budget mismatch')
    v2.check(v2.DEFAULT)
    if p['source_V2_protocol_sha256']!=v2.sha(v2.DEFAULT/'Protocol.json'):raise ValueError('V2 source changed')
    for name,expected in {**p['source_files'],**p['protected_files']}.items():
        if v2.sha(ROOT/name)!=expected:raise ValueError('frozen V3/source asset changed: '+name)
    for name,key in (('H_frozen.json','H_sha256'),('References.json','References_sha256')):
        if v2.sha(directory/name)!=p[key]:raise ValueError('copied asset changed')
    original=v2.read(v2.DEFAULT/'Protocol.json')
    if p['instances']!=original['instances'] or p['H_order']!=original['H_order']:raise ValueError('H/train21 changed')
    for row in p['instances']:
        path=(directory/row['relative_path']).resolve()
        if not path.is_relative_to(directory/'inputs/train') or v2.sha(path)!=row['sha256']:raise ValueError('training copy changed')
    if witness(p)['identity']!=v2.read(directory/'Expected_loaded_identity.json')['identity']:
        raise ValueError('V3 loaded identity mismatch')
    return p


def worker(pipe,payload,members,instances,names,allowed_modes):
    directory=Path(payload['directory']);p=payload['protocol'];spec=payload['spec'];folder=directory/'evidence'/spec['id']
    guard=v2.local_guard([directory/r['relative_path'] for r in p['instances']])
    try:
        atomic_json(folder/'before.json',witness(p));random.seed(501)
        rules=tuple(v2.compile_candidate(m) for m in members);policy=fixed_borda(tuple(spec['pair']))
        for name,instance in zip(names,instances):
            stem=folder/Path(name).stem;started=time.monotonic();cpu=time.process_time()
            progress={'file':name,'first_started':True,'recheck_started':False,'completed':False}
            atomic_json(stem.with_suffix('.progress.json'),progress)
            traces=[];cost=[];t=time.perf_counter()
            first=construct_rank_schedule(instance,rules,policy,trace=traces.append,cost=cost.append)
            first_seconds=time.perf_counter()-t;first_cost=list(cost);cost.clear()
            progress.update(first_completed=True,first_solve_seconds=first_seconds,recheck_started=True)
            atomic_json(stem.with_suffix('.progress.json'),progress);t=time.perf_counter()
            second=construct_rank_schedule(instance,rules,policy,cost=cost.append);recheck_seconds=time.perf_counter()-t
            if first!=second:raise ValueError('V3 nondeterministic full result')
            physical=v2.physical(first.schedule)
            if physical!=v2.physical(second.schedule):raise ValueError('V3 physical recheck mismatch')
            trace_path=stem.with_suffix('.trace.jsonl.gz');t=time.perf_counter()
            with gzip.open(trace_path,'wt',encoding='utf-8',compresslevel=1) as handle:
                for row in traces:handle.write(json.dumps(row,separators=(',',':'),allow_nan=False)+'\n')
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
                 'trace_states':len(traces),'network_guard':dict(guard)}
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
    if (directory/'Stop.json').exists():raise ValueError('persistent V3 stop; no automatic retry')
    state=v2.read(directory/'checkpoint.json')
    if state['protocol_sha256']!=v2.sha(directory/'Protocol.json') or not set(state['strategies'])<={s['id'] for s in specs()}:
        raise ValueError('checkpoint identity/scope mismatch')
    for record in state['strategies'].values():
        if record['status']!='completed':raise ValueError('uncertain reservation; do not repeat')
        if v2.sha(directory/record['result_path'])!=record['result_sha256']:raise ValueError('saved result changed')
    allowed=[path for row in p['instances'] for path in (directory/row['relative_path'],
        v2.DEFAULT/row['relative_path'],ROOT/'data/fjsp'/row['file'])]
    guard=v2.local_guard(allowed)
    members=tuple(v2.checked_candidate(r['candidate'],'h') for r in v2.read(directory/'H_frozen.json')['members'])
    instances=tuple(v2.load_instance(directory/r['relative_path']) for r in p['instances']);names=tuple(r['file'] for r in p['instances'])
    try:
        for spec in specs():
            if spec['id'] in state['strategies']:continue
            check(directory);folder=directory/'evidence'/spec['id']
            if folder.exists():raise ValueError('orphan evidence cannot be adopted')
            folder.mkdir();state['phase']='running'
            state['strategies'][spec['id']]={'status':'reserved','reserved_evaluations':21,'reserved_solve_passes':42}
            if sum(x['reserved_evaluations'] for x in state['strategies'].values())>63:raise ValueError('budget exceeded')
            atomic_json(directory/'checkpoint.json',state)
            expected={**p['source_files'],**p['protected_files']};start={n:v2.sha(ROOT/n) for n in expected};t=time.monotonic()
            rows,failure,life=v2.collect_with_lifecycle(mp.get_context('spawn'),worker,
                {'directory':str(directory),'protocol':p,'spec':spec},members,instances,names,15,None,
                lambda receipt:atomic_json(folder/'lifecycle.json',receipt))
            result={'valid':failure is None,'fitness':fmean(r['score'] for r in rows) if failure is None else None,
                'instances':rows,'total_instances':21,'primary_evaluation_seconds':time.monotonic()-t,**(failure or {})}
            atomic_json(folder/'raw_result.json',result);check(directory)
            boundary=v2.classify_boundary(result,before=v2.read(folder/'before.json') if (folder/'before.json').exists() else None,
                after=v2.read(folder/'after.json') if (folder/'after.json').exists() else None,lifecycle=life,
                expected_identity=v2.read(directory/'Expected_loaded_identity.json')['identity'],expected_files=expected,
                start_files=start,end_files={n:v2.sha(ROOT/n) for n in expected},worker_failure=(folder/'worker_failure.json').exists())
            atomic_json(folder/'boundary.json',boundary)
            if boundary['decision']=='stop':raise ValueError('V3 boundary stop: '+boundary['reason'])
            v2.validate_rows(rows,p);v2.check_result(result,names)
            for row in rows:
                if v2.sha(directory/row['trace_path'])!=row['trace_sha256']:raise ValueError('trace changed')
            result['boundary']=boundary;atomic_json(folder/'result.json',result)
            state['strategies'][spec['id']].update(status='completed',valid=result['valid'],
                result_path=str((folder/'result.json').relative_to(directory)),result_sha256=v2.sha(folder/'result.json'))
            atomic_json(directory/'checkpoint.json',state)
            print(json.dumps({'strategy':spec['id'],'valid':result['valid'],'fitness':result['fitness'],
                              'completed_instances':len(rows),'seconds':result['primary_evaluation_seconds']}),flush=True)
        state['phase']='completed';atomic_json(directory/'checkpoint.json',state);atomic_json(directory/'Network_guard.json',guard)
    except BaseException as exc:
        atomic_json(directory/'Stop.json',{'error_type':type(exc).__name__,'error':str(exc),'automatic_retry':False})
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',choices=('prepare','check','run','report'))
    parser.add_argument('--run-dir',type=Path,default=DEFAULT);args=parser.parse_args();directory=args.run_dir.resolve()
    if directory.parent!=ROOT/'runs':raise ValueError('independent runs child required')
    if args.stage=='prepare':prepare(directory);print('PREPARED',directory)
    elif args.stage=='check':check(directory);print('PASS',directory)
    else:
        with RunLock(directory):
            if args.stage=='run':run(directory)
            else:
                from tools.fusion_v3_report import report
                print(report(directory))
