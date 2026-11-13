#!/usr/bin/env python3
"""One bounded real-evaluator concurrency acceptance; never requests a model."""
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE))
import api_guard
api_guard.install()

import argparse
import ast
import csv
from dataclasses import asdict
import hashlib
import json
import os
import platform
import signal
import time

PLAN=HERE/'plan.json'


def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
    tmp.replace(path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def verify_overlay():
    release=read(ROOT/'release.json')
    for name,expected in release['files'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or (ROOT/name).is_symlink() or sha(path)!=expected:
            raise ValueError('solve acceptance overlay changed: '+name)
    return release


def prepare(base):
    plan=read(PLAN);overlay=verify_overlay();base=Path(base).resolve()
    if (len(plan['instances'])!=2 or len(plan['U'])!=2
            or plan['modes']!=[{'id':'serial','workers':1},{'id':'parallel','workers':2}]
            or plan['candidate_evaluations']!=4 or plan['instance_timeout_seconds']!=30
            or plan['API_requests']!=0 or plan['automatic_retries']!=0):
        raise ValueError('unreviewed bounded acceptance plan')
    resource_plan=plan['resources']
    if (any(type(resource_plan[k]) is not int or resource_plan[k]<=0 for k in resource_plan)
            or resource_plan['cpus']<3 or resource_plan['numeric_threads']!=1
            or resource_plan['Slurm_seconds']<=resource_plan['application_seconds']):
        raise ValueError('invalid declared resource allocation')
    if sha(base/'release.json')!=plan['base_manifest_sha256']:raise ValueError('admitted base release changed')
    release=read(base/'release.json')
    if release['commit']!=plan['base_commit']:raise ValueError('wrong public executor')
    for name,expected in release['files'].items():
        source=(base/name).resolve()
        if not source.is_relative_to(base) or (base/name).is_symlink() or sha(source)!=expected:
            raise ValueError('base release source changed: '+name)
    sys.path[:0]=[str(base/'code'),str(base)]
    from heuristic_design.core import evolution_v1 as e,state_a_v3 as state,routing_state_a_v3 as language
    from heuristic_design.core.storage import digest
    from heuristic_design.problems import routing_fixtures as fixtures
    from llm4ad.task.optimization.fjsp_set.instances import load_instance
    hpath=base/'preparations/fjsp-long/H_frozen.json'
    mpath=base/'preparations/fjsp-long/train21.manifest.json'
    if sha(hpath)!=plan['h_file_sha256'] or sha(mpath)!=plan['train_manifest_sha256']:raise ValueError('H/train manifest changed')
    manifest=read(mpath)
    if [v['file'] for v in plan['instances']]!=[v['file'] for v in manifest['instances'][:2]]:raise ValueError('non-score selection rule changed')
    hs=[r['candidate'] for r in read(hpath)['members']]
    if len(hs)!=10 or [h['key'] for h in hs]!=plan['H_keys']:raise ValueError('frozen H order changed')
    fixtures.compile_members('fjsp',hs)  # static validation/compile; no H execution
    data=[]
    for row in plan['instances']:
        source=base/row['base_path']
        if sha(source)!=row['sha256']:raise ValueError('selected instance changed')
        obj=load_instance(source)
        value={'machines':obj.machine_count,'jobs':[[[list(a) for a in op.alternatives] for op in job] for job in obj.jobs]}
        data.append({'file':row['file'],'split':'train','value':value,'sha256':digest(value),'source_sha256':row['sha256']})
    references=fixtures.precheck_instances('fjsp',data)  # static LB, no construction
    if plan['state_schema']!=state.schema_id('fjsp') or plan['u_abi']!=language.ABI:
        raise ValueError('wrong full-state interface')
    us=[{**row,'candidate':asdict(language.validate(row['code'],row['provenance'],len(hs)))} for row in plan['U']]
    # Verify the frozen evaluator really has exactly two solve() call sites in
    # its single instance loop; checks do not invoke either call.
    path=base/'code/heuristic_design/core/routing_evaluation.py'
    tree=ast.parse(path.read_text());worker=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_worker')
    calls=[n for n in ast.walk(worker) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='solve']
    if len(calls)!=2 or plan['native_solves_per_instance']!=2 or plan['max_physical_solves']!=2*2*2*2:
        raise ValueError('native first/recheck call count differs from 16-pass declaration')
    config={'problem':'fjsp','evaluation_mode':'solve','api_mode':'disabled','recording_mode':'full',
            'window':10,'enabled_groups':['construction','action_cost','trajectory','usage'],
            'instance_timeout_seconds':plan['instance_timeout_seconds'],
            'execution_contract':{'acceptance_only':True,'allocated_cpus':resource_plan['cpus']},
            'api_concurrency':0,'evaluation_concurrency':2}
    return {**plan,'config':config,'members':hs,'instances':data,'references':references,'U':us,
            'state_schema':state.schema_id('fjsp'),'state_spec_sha256':state.SPEC_SHA256,'u_abi':language.ABI,
            'source_files':e.source_identity(),'overlay_files':overlay['files'],'overlay_manifest_sha256':sha(ROOT/'release.json')}


def max_active(intervals):
    events=[(a,1) for a,b in intervals]+[(b,-1) for a,b in intervals]
    peak=active=0
    for _,delta in sorted(events):active+=delta;peak=max(peak,active)
    return peak


def physical_receipts(directory):
    rows=[]
    for path in (directory/'physical-solves').glob('*.jsonl'):
        rows.extend(json.loads(line) for line in path.read_text().splitlines())
    starts=[r for r in rows if r['event']=='started'];ends=[r for r in rows if r['event']=='completed']
    return rows,{'confirmed_started':len(starts),'confirmed_completed':len(ends),
                 'confirmed_failed':sum(r['event']=='failed' for r in rows)}


def evaluate_results(protocol,results,synthetic=False):
    from heuristic_design.core import evolution_v1 as e
    from heuristic_design.problems.routing_fixtures import decode_instance
    from llm4ad.task.optimization.fjsp_set.scheduler import Schedule,ScheduledOperation,validate_schedule
    for result in results.values():
        if not result['valid']:raise ValueError('one candidate invalid; entire bounded acceptance stops')
        if not synthetic:
            e._validate_result(result,protocol)
            for row,instance in zip(result['instances'],protocol['instances']):
                if row['captured_solves']!=2 or row['semantic_sha256']!=row['recheck_semantic_sha256']:
                    raise ValueError('first/recheck mismatch')
                # Independent feasibility check of the stored schedule is a
                # pure validator, not an additional construction/solve.
                solution=row['solution']
                schedule=Schedule(tuple(ScheduledOperation(**v) for v in solution['operations']),solution['makespan'])
                validate_schedule(decode_instance('fjsp',instance),schedule)


def coordinate(directory,p,evaluator,*,synthetic=False):
    from heuristic_design.core import evolution_v1 as e
    directory=Path(directory).resolve()
    if directory.exists():raise ValueError('acceptance identity already exists; no replay or budget reset')
    directory.mkdir(parents=True);(directory/'physical-solves').mkdir()
    lock=directory/'.solve-check.lock'
    fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    save(directory/'Protocol.json',p)
    state={'identity':sha(directory/'Protocol.json'),'phase':'running','reserved_solves':0,'reservations':{},
           'source':'SYNTHETIC_OFFLINE_TEST_ONLY' if synthetic else 'REAL_EVALUATOR_ENGINEERING_ACCEPTANCE',
           'started':time.time(),'deadline':time.time()+p['resources']['application_seconds']}
    save(directory/'checkpoint.json',state)
    stopped=[False];handlers={}
    for sig in (signal.SIGINT,signal.SIGTERM):handlers[sig]=signal.signal(sig,lambda *a:stopped.__setitem__(0,True))
    all_results={};modes={};normal=False;controller_CPU_started=time.process_time()
    try:
        for mode in p['modes']:
            # Two declared instance rows, each sharing T30 across both solves.
            bound=(2 if mode['workers']==1 else 1)*(len(p['instances'])*30+2)+5
            if stopped[0] or time.time()+bound>state['deadline']:raise RuntimeError('stop/deadline before reserving next wave')
            verify_overlay()
            tasks=[{'id':mode['id']+'/'+u['id'],'candidate':u['candidate'],'U':u['id']} for u in p['U']]
            # Serial has two one-task waves; parallel has one two-task wave.
            waves=[[t] for t in tasks] if mode['workers']==1 else [tasks]
            began=time.monotonic();mode_results={}
            for wave in waves:
                if stopped[0]:raise RuntimeError('stop before next candidate')
                cost=len(wave)*len(p['instances'])*2
                if state['reserved_solves']+cost>p['max_physical_solves']:raise ValueError('entire wave exceeds solve cap')
                for t in wave:state['reservations'][t['id']]={'status':'reserved','reserved_solves':len(p['instances'])*2}
                state['reserved_solves']+=cost;save(directory/'checkpoint.json',state)
                os.environ['HDL_SOLVE_CHECK_OUTPUT']=str(directory);os.environ['HDL_SOLVE_CHECK_MODE']=mode['id']
                responses=e._batch(evaluator,wave,mode['workers'],{**p,'run_directory':str(directory)})
                errors=[]
                for task in wave:
                    receipt=responses[task['id']];slot=state['reservations'][task['id']]
                    save(directory/'task-receipts'/(task['id'].replace('/','-')+'.json'),receipt)
                    if receipt['ok']:
                        value=receipt['value'];all_results[task['id']]=value;mode_results[task['U']]=value
                        slot.update(status='settled' if value['valid'] else 'invalid',valid=value['valid'])
                        if not value['valid']:errors.append(task['id']+': invalid')
                    else:slot['status']='unknown';errors.append(task['id']+': infrastructure failure')
                save(directory/'checkpoint.json',state)
                if errors:raise RuntimeError('; '.join(errors))
                evaluate_results(p,mode_results,synthetic)
                verify_overlay()
            modes[mode['id']]={'wall_seconds':time.monotonic()-began,'results':mode_results}
        comparison=[]
        for u in p['U']:
            a=modes['serial']['results'][u['id']];b=modes['parallel']['results'][u['id']]
            for left,right in zip(a['instances'],b['instances']):
                keys=('file','raw_cost','reference','score','semantic_sha256','recheck_semantic_sha256')
                if any(left[k]!=right[k] for k in keys):raise ValueError('serial/parallel deterministic result mismatch')
                comparison.append({'U':u['id'],**{k:left[k] for k in keys},'serial_parallel_equal':True})
        counts={'confirmed_started':0,'confirmed_completed':0,'confirmed_failed':0}
        statistics={}
        if not synthetic:
            events,counts=physical_receipts(directory)
            if counts!={'confirmed_started':16,'confirmed_completed':16,'confirmed_failed':0}:
                raise ValueError('physical-call receipts incomplete; retain all reservations as charged')
            for mode in p['modes']:
                values=list(modes[mode['id']]['results'].values())
                intervals=[(r['lifecycle']['started_monotonic'],r['lifecycle']['finished_monotonic']) for r in values]
                peak=max_active(intervals)
                statistics[mode['id']]={'actual_process_peak':peak,'pids':[r['lifecycle']['pid'] for r in values],
                    'worker_peak_rss_bytes':max(row['worker_peak_rss_bytes'] for r in values for row in r['instances']),
                    'native_solve_CPU_seconds':sum(r['CPU_seconds'] for r in events if r['mode']==mode['id'] and r['event']=='completed'),
                    'wall_seconds':modes[mode['id']]['wall_seconds']}
                if peak!=mode['workers']:raise ValueError('requested child-process concurrency not observed')
        facts={'passed':True,'kind':state['source'],'comparison':comparison,'modes':statistics,
               'physical_solves':counts,'reserved_solves':state['reserved_solves'],'max_physical_solves':16,
               'API':api_guard.check(),'job_id':os.environ.get('SLURM_JOB_ID'),'host':platform.node(),
               'scope':p['scope'],'formal_training_score':False,'automatic_retries':0,
               'requested_resources':p['resources'],'actual_resources':p.get('actual_resources'),
               'Slurm':p.get('Slurm'),'controller_CPU_seconds':time.process_time()-controller_CPU_started}
        import meter
        facts['controller_peak_rss_bytes']=meter.peak_rss()
        with (directory/'per-instance.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['mode','U','file','raw_cost','reference','J','captured_solves',
                                             'primary_seconds','recheck_seconds','worker_peak_rss_bytes'])
            writer.writeheader()
            for mode in p['modes']:
                for uid,result in modes[mode['id']]['results'].items():
                    for row in result['instances']:
                        writer.writerow({'mode':mode['id'],'U':uid,'file':row['file'],'raw_cost':row['raw_cost'],
                            'reference':row['reference'],'J':row['score'],'captured_solves':row.get('captured_solves'),
                            'primary_seconds':row.get('solve_seconds'),'recheck_seconds':row.get('recheck_solve_seconds'),
                            'worker_peak_rss_bytes':row.get('worker_peak_rss_bytes')})
        state['phase']='completed';save(directory/'acceptance.json',facts);normal=True
    except BaseException as error:
        state.update(phase='stopped',error_type=type(error).__name__,error=str(error),automatic_retry=False)
        _,counts=physical_receipts(directory)
        save(directory/'failure.json',{'state':state,'physical_call_receipts':counts,
            'reserved_unconfirmed_or_incomplete':state['reserved_solves']-counts['confirmed_completed'],
            'unknown_is_not_zero':True,'automatic_retry':False})
        raise
    finally:
        save(directory/'checkpoint.json',state)
        for sig,handler in handlers.items():signal.signal(sig,handler)
        os.environ.pop('HDL_SOLVE_CHECK_OUTPUT',None);os.environ.pop('HDL_SOLVE_CHECK_MODE',None)
        if normal:lock.unlink()
        files={str(v.relative_to(directory)):sha(v) for v in directory.rglob('*') if v.is_file()}
        save(directory/'results-manifest.json',{'files':files,'kind':state['source']})
    return facts


# A spawn child imports this file before executing the unchanged evaluator.
if os.environ.get('HDL_SOLVE_CHECK_OUTPUT'):
    import meter
    meter.install(os.environ['HDL_SOLVE_CHECK_OUTPUT'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['check','run'])
    parser.add_argument('--base-root',type=Path);parser.add_argument('--allow-solves',action='store_true')
    parser.add_argument('--approve-solves',type=int)
    args=parser.parse_args();plan=read(PLAN);base=args.base_root or Path(plan['base_release'])
    p=prepare(base)
    if args.action=='check':
        print(json.dumps({'offline':True,'actual_solves':0,'API':api_guard.check(),'max_physical_solves':16,
              'instances':[{'file':r['file'],'sha256':r['source_sha256']} for r in p['instances']],
              'references':p['references'],'native_call_sites':2,'state_schema':p['state_schema'],
              'state_spec_sha256':p['state_spec_sha256'],'u_abi':p['u_abi'],'resources':p['resources'],
              'U':[{'id':u['id'],'key':u['candidate']['key']} for u in p['U']]},indent=2));return
    if not args.allow_solves or args.approve_solves!=16:raise PermissionError('explicit --allow-solves --approve-solves 16 required')
    if not os.environ.get('SLURM_JOB_ID') or ROOT!=Path(p['remote_release']):raise ValueError('real acceptance only in the declared Slurm release')
    from heuristic_design.core.execution_contract import resources
    from heuristic_design.core.routing_evaluation import evaluate_task
    p['actual_resources']=resources(p['config'])
    p['Slurm']={key:os.environ.get(key) for key in ('SLURM_JOB_ID','SLURM_CPUS_PER_TASK','SLURM_MEM_PER_NODE','SLURM_NTASKS','SLURM_JOB_PARTITION')}
    if p['Slurm'].get('SLURM_MEM_PER_NODE') and int(p['Slurm']['SLURM_MEM_PER_NODE'])<p['resources']['memory_mib']:
        raise ValueError('Slurm memory allocation below the declared 2048 MiB')
    result=coordinate(ROOT/'run',p,evaluate_task)
    print(json.dumps({'passed':result['passed'],'physical_solves':result['physical_solves'],'API':result['API']},indent=2))


if __name__=='__main__':
    try:main()
    except Exception as error:print(type(error).__name__+': '+str(error),file=sys.stderr);raise SystemExit(2)
