"""Isolated real candidate solves with complete-row T30 lifecycle certification.

Independent candidates can run concurrently; instances within each worker stay
serial. Workers return data through pipes; they never edit the global ledger.
"""
import multiprocessing as mp
import os
from pathlib import Path
import resource
import socket
import sys
import time

from .storage import digest, sha, write
from .lifecycle import collect

ROOT = Path(__file__).resolve().parents[3]


def semantic_row(row):
    return {k:row[k] for k in ('file','score','solution','trace','h_calls')}


def _worker(pipe,payload,members,instances,names,allowed_modes):
    from heuristic_design.problems.routing_fixtures import solve
    def deny(*args,**kwargs): raise PermissionError('offline evaluation worker network forbidden')
    socket.socket.connect = deny
    socket.create_connection = deny
    try:
        c=payload['config']
        expected=payload['source_files']
        before={name:sha(ROOT/name) for name in expected}
        if before != expected:raise RuntimeError('worker source identity mismatch')
        for instance,name in zip(instances,names):
            first=solve(c['problem'],instance,members,payload['candidate'],window=c['window'],enabled_groups=c['enabled_groups'])
            second=solve(c['problem'],instance,members,payload['candidate'],window=c['window'],enabled_groups=c['enabled_groups'])
            if semantic_row(first) != semantic_row(second):raise ValueError('full solve/recheck mismatch')
            after={name:sha(ROOT/name) for name in expected}
            if before != after:raise RuntimeError('worker source changed during evaluation')
            rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # macOS bytes; Linux KiB. Store bytes in either environment.
            peak=int(rss if sys.platform=='darwin' else rss*1024)
            pipe.send({**first,'recheck_semantic_sha256':digest(semantic_row(second)),
                       'semantic_sha256':digest(semantic_row(first)),
                       'recheck_solve_seconds':second['solve_seconds'],
                       'recheck_observation_seconds':second['observation_seconds'],
                       'captured_solves':2,'feasible':True,'worker_peak_rss_bytes':peak,
                       'source_before_sha256':digest(before),'source_after_sha256':digest(after)})
    except BaseException as exc:
        pipe.send({'error_type':type(exc).__name__,'error':str(exc)[:500]})
    finally:
        pipe.close()


def evaluate_task(task,p):
    directory=Path(p['run_directory'])
    folder=directory/'worker-receipts'/task['id']
    folder.mkdir(parents=True,exist_ok=False)
    payload={'candidate':task['candidate'],'config':p['config'],'source_files':p['source_files']}
    started=time.perf_counter()
    rows,failure,life=collect(mp.get_context('spawn'),_worker,payload,p['members'],p['instances'],
        [r['file'] for r in p['instances']],p['config']['instance_timeout_seconds'],(0,),
        lambda receipt:write(folder/'lifecycle.json',receipt))
    elapsed=time.perf_counter()-started
    # Incomplete/uncertified cleanup is infrastructure ambiguity, never ordinary
    # bad candidate quality. It must stop the coordinator.
    if life['alive'] or not life['receiver_thread_stopped']:
        raise RuntimeError('unknown worker termination; no automatic continuation')
    if failure:
        if life['trigger'] != 'parent_complete_result_timeout' and failure.get('error_type') in ('RuntimeError','WorkerExit'):
            raise RuntimeError('uncertified worker/source failure: '+str(failure))
        result={'valid':False,'fitness':None,'mock':False,'instances':rows,
                'failure':failure,'lifecycle':life,'evaluation_seconds':elapsed}
    else:
        if life['exitcode'] != 0 or life['cleanup'] != ['join_exit_grace_2.0']:
            raise RuntimeError('worker normal exit not certified')
        if len(rows) != len(p['instances']) or [r['file'] for r in rows] != [r['file'] for r in p['instances']]:
            raise RuntimeError('incomplete evaluation result')
        for row in rows:
            if (row['semantic_sha256'] != row['recheck_semantic_sha256'] or row['captured_solves'] != 2
                    or row['source_before_sha256'] != row['source_after_sha256']):
                raise RuntimeError('solve/recheck/source receipts mismatch')
        behavior=[[t['member_id'] for t in row['trace']] for row in rows]
        result={'valid':True,'fitness':sum(r['score'] for r in rows)/len(rows),'mock':False,
                'instances':rows,'behavior_sha256':digest(behavior),'behavior':behavior,
                'lifecycle':life,'evaluation_seconds':elapsed}
    if any(sha(ROOT/name)!=value for name,value in p['source_files'].items()):
        raise RuntimeError('parent source changed during worker execution')
    write(folder/'result.json',result)
    return result
