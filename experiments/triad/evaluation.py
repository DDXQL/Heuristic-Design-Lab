"""Problem worker over the admitted T30 complete-row lifecycle, two passes only."""
import math
import multiprocessing as mp
import os
from pathlib import Path
import resource
import socket
import sys
import time
from heuristic_design.core.lifecycle import collect
from heuristic_design.core.storage import read,write,sha,digest
from . import problems
ROOT=Path(__file__).resolve().parents[2]


def event(path,row):
    import json
    with Path(path).open('a') as f:f.write(json.dumps({**row,'pid':os.getpid(),'at':time.time()})+'\n');f.flush();os.fsync(f.fileno())


def _worker(pipe,payload,members,instances,names,allowed_modes):
    def deny(*a,**k):raise PermissionError('evaluation worker network prohibited')
    socket.socket.connect=deny;socket.create_connection=deny
    try:
        sources=payload['source_files'];before={n:sha(ROOT/n) for n in sources}
        if before!=sources:raise RuntimeError('worker source changed')
        for spec,name,ref in zip(instances,names,payload['references']):
            started=time.monotonic();cpu=time.process_time();results=[]
            for phase in ('first','recheck'):
                event(payload['solve_events'],{'event':'started','instance':name,'pass':phase})
                try:row=problems.solve_row(spec,members,payload['candidate'],payload['config'],ref['reference'])
                except BaseException:
                    event(payload['solve_events'],{'event':'failed','instance':name,'pass':phase});raise
                event(payload['solve_events'],{'event':'completed','instance':name,'pass':phase});results.append(row)
            if results[0]!=results[1]:raise ValueError('deterministic independent recheck differs')
            after={n:sha(ROOT/n) for n in sources}
            if after!=before:raise RuntimeError('worker source changed during evaluation')
            rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            pipe.send({**results[0],'captured_solves':2,'semantic_sha256':digest(results[0]),'recheck_semantic_sha256':digest(results[1]),
              'feasible':True,'worker_pid':os.getpid(),'worker_peak_rss_bytes':int(rss if sys.platform=='darwin' else rss*1024),
              'worker_CPU_seconds':time.process_time()-cpu,'complete_row_seconds':time.monotonic()-started,
              'source_before_sha256':digest(before),'source_after_sha256':digest(after)})
    except BaseException as x:pipe.send({'error_type':type(x).__name__,'error':str(x)[:500]})
    finally:pipe.close()


def evaluate(task,p):
    d=Path(p['run_directory']);folder=d/'worker-receipts'/task['id'];folder.mkdir(parents=True,exist_ok=False)
    payload=dict(config=p['config'],candidate=task['candidate'],references=p['references'],source_files=p['source_files'],solve_events=str(folder/'physical-solves.jsonl'))
    start=time.monotonic()
    rows,failure,life=collect(mp.get_context('spawn'),_worker,payload,p['members'],p['instances'],[r['file'] for r in p['instances']],30,(0,),lambda x:write(folder/'lifecycle.json',x))
    if life['alive'] or not life['receiver_thread_stopped']:raise RuntimeError('unknown worker termination; no replay')
    if failure and failure.get('error_type') in ('RuntimeError','WorkerExit'):raise RuntimeError('evaluation infrastructure failure: '+str(failure))
    valid=failure is None
    if valid and (life['exitcode']!=0 or life['cleanup']!=['join_exit_grace_2.0']):raise RuntimeError('uncertified worker exit')
    result=dict(valid=valid,fitness=-sum(r['score'] for r in rows)/len(rows) if valid else None,instances=rows,mock=False,lifecycle=life,failure=failure,evaluation_seconds=time.monotonic()-start)
    write(folder/'result.json',result);return result


def validate(result,instances,problem,action_policy=None):
    rows=result['instances']
    if type(result['valid']) is not bool or len(rows)>len(instances) or [r['file'] for r in rows]!=[r['file'] for r in instances[:len(rows)]]:raise ValueError('validity / ordered-prefix mismatch')
    if result['valid']:
        if len(rows)!=len(instances) or result['fitness']!=-sum(r['score'] for r in rows)/len(rows):raise ValueError('complete J-min vector / internal -J mismatch')
    elif result['fitness'] is not None:raise ValueError('incomplete candidate cannot have objective')
    if any(type(r['score']) not in (int,float) or not math.isfinite(r['score']) for r in rows):raise ValueError('nonfinite objective')
    if result.get('mock'):return
    from heuristic_design.core.state_a_v3 import score_final_cost
    for spec,r in zip(instances,rows):
        if r['score']!=score_final_cost(r['raw_cost'],r['reference']) or r['captured_solves']!=2 or r['semantic_sha256']!=r['recheck_semantic_sha256'] or r['source_before_sha256']!=r['source_after_sha256']:raise ValueError('J / first-recheck-source certification mismatch')
        semantic={k:r[k] for k in ('file','solution','raw_cost','reference','score','member_sequence','h_calls')}
        if digest(semantic)!=r['semantic_sha256']:raise ValueError('semantic row changed')
        if problem=='obp':
            problems.validate_obp_solution(spec['value'],r['solution'],action_policy)
            if r['raw_cost']!=r['solution']['bin_count']:raise ValueError('raw bin cost differs')
        elif problem=='tsp':
            from heuristic_design.problems.tsp.solver import distances,tour_length
            if r['raw_cost']!=tour_length(distances(spec['value']['coordinates']),r['solution']['tour']):raise ValueError('raw tour cost differs')
        else:
            from llm4ad.task.optimization.fjsp_set.scheduler import Schedule,ScheduledOperation,validate_schedule
            schedule=Schedule(tuple(ScheduledOperation(**v) for v in r['solution']['operations']),r['solution']['makespan'])
            validate_schedule(problems.fixtures.decode_instance('fjsp',spec),schedule)
            if r['raw_cost']!=schedule.makespan:raise ValueError('raw makespan differs')
