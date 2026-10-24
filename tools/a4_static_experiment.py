"""Prospective A4 formal adapter. prepare/run require future human approval.

Current task may execute audit-records and synthetic-acceptance ONLY. Imported
modules contain no provider transport/client paths; no prompts or U evolution.
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

from fjsp_usage.a4_static import VERSION,SEARCH_SEEDS,QUERIES,SPACE_SIZE,LOGICAL_EVALUATIONS,SOLVE_PASSES
from fjsp_usage.a4_static.authorization import require_approval
from fjsp_usage.a4_static.model import decode,ticket,policy,output
from fjsp_usage.a4_static.engine import Campaign,read,write,sha,sample_indices
from fjsp_usage.baseline_supplemental.lifecycle import collect,classify
from fjsp_usage.baseline_a.validation import validate_result
from fjsp_usage.fusion_v2.execution import construct_fusion_schedule,v1_adapter
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.locking import RunLock
from tools import baseline_a_supplemental as s

ROOT=s.ROOT
AUDIT=ROOT/'reports/a4-evidence-protocol-20261024-v1'
DEFAULT=ROOT/'runs/a4-static-rs60x5-train21-seed501-v1'
MODULES=('fjsp_usage.a4_static','fjsp_usage.a4_static.model','fjsp_usage.a4_static.engine',
    'fjsp_usage.a4_static.authorization','tools.a4_static_experiment','tools.a4_static_report')


def no_data_guard():
    return s.v2.local_guard([])


def formal_guard(directory):
    rows=read(s.DEFAULT/'Protocol.json')['instances']
    roots=(directory,s.DEFAULT,s.BASE,s.b.old.DEFAULT,s.b.old.v3.DEFAULT,s.v2.DEFAULT)
    return s.v2.local_guard([ROOT/'data/fjsp'/r['file'] for r in rows]+
                          [base/r['relative_path'] for base in roots for r in rows])


def witness(p):
    rows=s.witness(p)['modules']
    for name in MODULES:
        module=importlib.import_module(name);path=Path(module.__file__).resolve()
        if sha(path)!=p['source_files'][str(path.relative_to(ROOT))]:raise ValueError('A4 frozen source mismatch')
        code=compile(path.read_bytes(),str(path),'exec',dont_inherit=True,optimize=0)
        defs={c.co_name:c for c in code.co_consts if isinstance(c,types.CodeType)};functions={}
        for key,fn in vars(module).items():
            if inspect.isfunction(fn) and (fn.__module__==name or key in defs):
                if key not in defs or s.v2.code_identity(fn.__code__)!=s.v2.code_identity(defs[key]):raise ValueError('A4 loaded function mismatch')
                functions[key]=s.v2.code_identity(fn.__code__)
            if inspect.isclass(fn) and fn.__module__==name and key in defs:
                methods={c.co_name:c for c in defs[key].co_consts if isinstance(c,types.CodeType)}
                for method,f in vars(fn).items():
                    if isinstance(f,(classmethod,staticmethod)):f=f.__func__
                    if inspect.isfunction(f) and method in methods:
                        if s.v2.code_identity(f.__code__)!=s.v2.code_identity(methods[method]):raise ValueError('A4 loaded method mismatch')
                        functions[key+'.'+method]=s.v2.code_identity(f.__code__)
        rows[name]={'file':str(path),'source_sha256':sha(path),'loaded_functions':functions}
    return {'pid':os.getpid(),'modules':rows,'identity':digest(rows)}


def prepare(directory,authorization):
    approval=require_approval(read(authorization))  # BEFORE any formal draw/data read
    if directory!=DEFAULT or directory.exists():raise ValueError('new fixed A4 directory required')
    acceptance=read(AUDIT/'Synthetic_acceptance.json')
    if not acceptance['passed']:raise ValueError('synthetic gate missing')
    for n,h in acceptance['files'].items():
        if sha(ROOT/n)!=h:raise ValueError('acceptance implementation changed')
    # Blind generation: sizes and search seeds only; NO result/cache objects.
    plans=[sample_indices(SPACE_SIZE,QUERIES,seed) for seed in SEARCH_SEEDS]
    source=read(s.DEFAULT/'Protocol.json');cache=read(AUDIT/'Verified_quality_cache_index.json')
    if cache['H_order']!=source['H_order'] or cache['instances']!=source['instances']:raise ValueError('audited science differs')
    protected=dict(source['protected_files'])
    for row in read(AUDIT/'Source_manifest.json')['inputs']:
        if sha(ROOT/row['path'])!=row['sha256']:raise ValueError('audited evidence changed')
        protected[row['path']]=row['sha256']
    for path in (AUDIT/'Verified_quality_cache_index.json',AUDIT/'Source_manifest.json',AUDIT/'Synthetic_acceptance.json'):
        protected[str(path.relative_to(ROOT))]=sha(path)
    a123=read(AUDIT/'A1_A3_verified.json');grid_summary=read(AUDIT/'Grid_summary.json')
    for path in (AUDIT/'A1_A3_verified.json',AUDIT/'Grid_summary.json'):
        protected[str(path.relative_to(ROOT))]=sha(path)
    sources={**source['source_files'],**acceptance['files']}
    p={'version':VERSION,'mode':'formal','space_size':SPACE_SIZE,'queries_per_repeat':QUERIES,
       'search_seeds':list(SEARCH_SEEDS),'solve_seed':501,'instances':source['instances'],'H_order':source['H_order'],
       'H_sha256':source['H_sha256'],'source_files':sources,'protected_files':protected,
       'authorization':approval,'authorization_sha256':sha(authorization),'new_evaluation_cap':LOGICAL_EVALUATIONS,
       'new_solve_pass_cap':SOLVE_PASSES,'LLM_API_cap':0,'result_wait_seconds':30,'exit_grace_seconds':2.,
       'wall_launch_budget_seconds':21600,'minimum_launch_allowance_seconds':650,
       'cache_index_sha256':sha(AUDIT/'Verified_quality_cache_index.json'),
       'external_reference_fitness':{'Best_Single':a123['best_single_fitness'],'Best_Equal_Pair':a123['best_equal_pair_fitness'],
            'Single_H_Oracle':a123['single_H_Oracle_fitness'],'H01_grid_best':grid_summary['best']['fitness'],'historical_B2':grid_summary['B2_fitness']},
       'cache_scope':'complete historical quality evidence with provenance; no T15 negative cache at T30; same-campaign confirmed T30 failures memoized',
       'semantics':'canonical grid k/20 lower-ID weight, partner exactly1-alpha; raw SELECT endpoints; no epsilon/drop/state dependence',
       'sampling':'uniform without replacement over865 canonical policies, independent repeat seeds; no score feedback or free incumbent'}
    campaign=Campaign.create(directory,p,plans)
    (directory/'inputs/train').mkdir(parents=True)
    for r in p['instances']:(directory/r['relative_path']).write_bytes((s.DEFAULT/r['relative_path']).read_bytes())
    (directory/'H_frozen.json').write_bytes((s.DEFAULT/'H_frozen.json').read_bytes())
    (directory/'Authorization.json').write_bytes(Path(authorization).read_bytes())
    (directory/'Cache_index.json').write_bytes((AUDIT/'Verified_quality_cache_index.json').read_bytes())
    p=read(directory/'Protocol.json');write(directory/'Expected_loaded_identity.json',witness(p))
    (directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    check(directory)


def check(directory,validate_journal=True):
    p=read(directory/'Protocol.json');require_approval(p['authorization'])
    if (p['version']!=VERSION or p['mode']!='formal' or p['space_size']!=865 or p['queries_per_repeat']!=60
        or p['search_seeds']!=list(SEARCH_SEEDS) or p['solve_seed']!=501
        or (p['new_evaluation_cap'],p['new_solve_pass_cap'],p['LLM_API_cap'],p['result_wait_seconds'],p['exit_grace_seconds'],p['wall_launch_budget_seconds'])!=(6300,12600,0,30,2.,21600)):
        raise ValueError('fixed A4 scope changed')
    if sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip():raise ValueError('protocol hash')
    for n,h in {**p['source_files'],**p['protected_files']}.items():
        if sha(ROOT/n)!=h:raise ValueError('source/evidence mismatch: '+n)
    for name,key in [('H_frozen.json','H_sha256'),('Authorization.json','authorization_sha256'),('Cache_index.json','cache_index_sha256')]:
        if sha(directory/name)!=p[key]:raise ValueError('frozen asset mismatch')
    for r in p['instances']:
        path=directory/r['relative_path']
        if not path.resolve().is_relative_to(directory/'inputs/train') or sha(path)!=r['sha256']:raise ValueError('data mismatch')
    if witness(p)['identity']!=read(directory/'Expected_loaded_identity.json')['identity']:raise ValueError('loaded identity')
    if validate_journal:Campaign(directory).validate()
    return p


def worker(pipe,payload,members,instances,names,allowed_modes):
    directory=Path(payload['directory']);folder=Path(payload['folder']);p=payload['protocol']
    guard=s.v2.local_guard([directory/r['relative_path'] for r in p['instances']])
    try:
        mode,vector=output(payload['spec'])
        write(folder/'Frozen_policy.json',{'spec':payload['spec'],'ticket':ticket(payload['spec']),'mode':mode,'raw_vector':list(vector)})
        write(folder/'before.json',witness(p));random.seed(501)
        rules=tuple(s.v2.compile_candidate(m) for m in members);usage=v1_adapter(policy(payload['spec']))
        for name,instance in zip(names,instances):
            stem=folder/Path(name).stem;t=time.monotonic();cpu=time.process_time()
            progress={'file':name,'first_started':True,'recheck_started':False,'completed':False,'worker_started':t}
            s.phase(stem,progress,'first_start');cost=[];beg=time.perf_counter()
            first=construct_fusion_schedule(instance,rules,usage,cost=cost.append);single=time.perf_counter()-beg
            first_cost=cost[:];cost.clear();progress.update(first_completed=True,recheck_started=True,first_solve_seconds=single)
            s.phase(stem,progress,'first_end');s.phase(stem,progress,'recheck_start');beg=time.perf_counter()
            second=construct_fusion_schedule(instance,rules,usage,cost=cost.append);recheck=time.perf_counter()-beg
            s.phase(stem,progress,'recheck_end')
            if first!=second:raise ValueError('two-solve mismatch')
            physical=s.v2.physical(first.schedule);again=s.v2.physical(second.schedule)
            if physical!=again:raise ValueError('physical recheck mismatch')
            row={'file':name,'makespan':first.schedule.makespan,'lower_bound':first.lower_bound,'score':first.score,
                 'feasible':True,'captured_solves':2,'single_solve_seconds':single,'deterministic_recheck_seconds':recheck,
                 'single_h_calls':list(first.member_calls),'recheck_h_calls':list(second.member_calls),
                 'physical_schedule':physical,'physical_schedule_sha256':digest(physical),
                 'recheck_physical_schedule_sha256':digest(again),'commit_sequence_sha256':digest(asdict(first.schedule)),
                 'first_costs':{k:sum(c[k] for c in first_cost) for k in ('h_scoring_seconds','fusion_seconds')},
                 'recheck_costs':{k:sum(c[k] for c in cost) for k in ('h_scoring_seconds','fusion_seconds')},
                 'instance_worker_seconds':time.monotonic()-t,'instance_CPU_seconds':time.process_time()-cpu,
                 'peak_RSS_bytes_macos':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'network_guard':dict(guard)}
            write(stem.with_suffix('.result.json'),row);progress['completed']=True;s.phase(stem,progress,'result_write_end')
            if name==names[-1]:write(folder/'after.json',witness(p))
            pipe.send(row)
    except BaseException as exc:
        write(folder/'worker_failure.json',{'error_type':type(exc).__name__,'error':str(exc)})
        write(folder/'after.json',witness(p));pipe.send({'error_type':type(exc).__name__,'error':str(exc)})
    finally:
        try:
            if not (folder/'after.json').exists():write(folder/'after.json',witness(p))
            write(folder/'network_guard.json',guard)
        finally:pipe.close()


def run(directory):
    if (directory/'Stop.json').exists():raise ValueError('persistent Stop; no automatic resume')
    p=check(directory);campaign=Campaign(directory);_,_,state,_=campaign.validate()
    if state['phase'] in ('completed','wall_budget_stopped'):return
    clock_path=directory/'Run_clock.json'
    if not clock_path.exists():
        if 'run_clock_sha256' in state:raise ValueError('run clock missing')
        started=time.time();write(clock_path,{'start_utc_epoch':started,'deadline_utc_epoch':started+21600})
        state['run_clock_sha256']=sha(clock_path);write(directory/'checkpoint.json',state)
    elif state.get('run_clock_sha256')!=sha(clock_path):raise ValueError('unknown/mismatched run clock')
    clock=read(clock_path)
    if clock['deadline_utc_epoch']!=clock['start_utc_epoch']+21600:raise ValueError('wall allowance changed')
    if time.time()<clock['start_utc_epoch']:raise ValueError('wall clock moved backwards')
    index={ticket(e['spec']):e for e in read(directory/'Cache_index.json')['entries']}
    memo={q['ticket']:q for q in state['queries']}
    members=tuple(s.v2.checked_candidate(m['candidate'],'h') for m in read(directory/'H_frozen.json')['members'])
    instances=None;names=tuple(r['file'] for r in p['instances'])
    def evaluate(index_id,folder,reserve):
        nonlocal instances
        check(directory,validate_journal=False)
        if index_id in memo:
            prior=memo[index_id];path=directory/prior['result_path']
            if sha(path)!=prior['result_sha256']:raise ValueError('memo identity')
            return read(path),'campaign_cache',{'kind':'campaign_memo','path':str(path),'sha256':sha(path)}
        if index_id in index:
            record=index[index_id];path=ROOT/record['path']
            if sha(path)!=record['sha256']:raise ValueError('historical cache identity')
            result=read(path)
            if not result['valid']:raise ValueError('T15 failure cannot be adopted at T30')
            from fjsp_usage.a4_static.engine import validate_result as validate_core
            validate_core(result,p['instances'])
            return result,'historical_cache',{'kind':'accepted_historical_quality','source':record,
                'warning':'historical quality reuse, NOT contemporaneous T30 timing/terminal evidence'}
        reserve()
        if instances is None:instances=tuple(s.v2.load_instance(directory/r['relative_path']) for r in p['instances'])
        evidence=folder/'evidence';evidence.mkdir();expected={**p['source_files'],**p['protected_files']}
        before_files={n:sha(ROOT/n) for n in expected};started=time.monotonic()
        rows,failure,life=collect(mp.get_context('spawn'),worker,{'directory':str(directory),'folder':str(evidence),
            'protocol':p,'spec':decode(index_id)},members,instances,names,30,None,lambda x:write(evidence/'lifecycle.json',x))
        result={'valid':failure is None,'fitness':fmean(r['score'] for r in rows) if failure is None else None,
            'total_instances':21,'instances':rows,'primary_evaluation_seconds':time.monotonic()-started,**(failure or {})}
        write(evidence/'raw_result.json',result);check_sources(p)
        frozen_policy=read(evidence/'Frozen_policy.json');mode,vector=output(decode(index_id))
        if frozen_policy!={'spec':decode(index_id),'ticket':index_id,'mode':mode,'raw_vector':list(vector)}:
            raise ValueError('child policy identity mismatch')
        boundary=classify(result,before=read(evidence/'before.json') if (evidence/'before.json').exists() else None,
            after=read(evidence/'after.json') if (evidence/'after.json').exists() else None,lifecycle=life,
            expected_identity=read(directory/'Expected_loaded_identity.json')['identity'],expected_files=expected,
            start_files=before_files,end_files={n:sha(ROOT/n) for n in expected},worker_failure=(evidence/'worker_failure.json').exists())
        write(evidence/'boundary.json',boundary)
        if boundary['decision']=='stop':raise ValueError('A4 process boundary: '+boundary['reason'])
        validate_result(result,p['instances'],'modern')
        if result['valid'] and (not (evidence/'network_guard.json').exists() or any(read(evidence/'network_guard.json').values())):
            raise ValueError('worker guard missing/violated')
        result['boundary']=boundary
        provenance={'kind':'new_T30','boundary':boundary,'evidence_sha256':{
            str(path.relative_to(folder)):sha(path) for path in evidence.iterdir() if path.is_file()}}
        return result,'new',provenance
    # Update memo only from durable completed queries; never from reservations.
    def evaluated(index_id,folder,reserve):
        value=evaluate(index_id,folder,reserve)
        return value
    # Campaign.execute commits each result. Re-enter one slot at a time to refresh
    # the memo from the committed ledger, including confirmed T30 invalidity.
    while True:
        _,_,state,flat=campaign.validate()
        if len(state['queries'])==len(flat) or state['phase'] in ('completed','wall_budget_stopped'):break
        campaign.execute(evaluated,limit=1,clock=time.time,wall_deadline=clock['deadline_utc_epoch'])
        _,_,state,_=campaign.validate();memo={q['ticket']:q for q in state['queries']}
    if state['phase']=='running' and len(state['queries'])==len(flat):
        state['phase']='completed';write(directory/'checkpoint.json',state)


def check_sources(p):
    for n,h in {**p['source_files'],**p['protected_files']}.items():
        if sha(ROOT/n)!=h:raise ValueError('source/evidence changed: '+n)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('audit-records','synthetic-acceptance','prepare','check','run','report'))
    parser.add_argument('--run-dir',type=Path,default=DEFAULT);parser.add_argument('--authorization-file',type=Path)
    args=parser.parse_args();d=args.run_dir.resolve()
    if args.stage in ('audit-records','synthetic-acceptance'):
        network=no_data_guard()
        if args.stage=='audit-records':
            from tools.a4_static_audit import audit
            audit()
        else:
            from tests.test_a4_static import acceptance
            acceptance()
    else:
        if d!=DEFAULT:raise ValueError('fixed prospective run directory required')
        auth=args.authorization_file if args.stage=='prepare' else d/'Authorization.json'
        if auth is None:raise PermissionError('future explicit --authorization-file required')
        require_approval(read(auth))
        network=formal_guard(d)
        if args.stage=='prepare':prepare(d,auth)
        else:
            with RunLock(d):
                try:
                    if args.stage=='check':check(d)
                    elif args.stage=='run':run(d)
                    else:
                        from tools.a4_static_report import report
                        check(d);report(d,ROOT/'reports'/d.name)
                except BaseException as exc:
                    if args.stage=='run' and not (d/'Stop.json').exists():
                        write(d/'Stop.json',{'type':type(exc).__name__,'error':str(exc),'automatic_retry':False})
                    raise
    if any(network.values()):raise ValueError('forbidden network/data attempt')


if __name__=='__main__':main()
