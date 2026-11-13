#!/usr/bin/env python3
"""Frozen-engine Mock acceptance; no credential option or real mode exists."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(Path(__file__).resolve().parent),str(ROOT/'code'),str(ROOT)]
import guard
guard.install()  # spawn children install the same boundary before their target

import argparse
import copy
import hashlib
import json
import os
import platform
import time


def verify_release():
    r=json.loads((ROOT/'release.json').read_text())
    if r['commit']!='923781f05686f1899c24fd7899fb3bc6b1df1562':raise ValueError('wrong frozen engine release')
    for name,expected in r['files'].items():
        p=(ROOT/name).resolve()
        if not p.is_relative_to(ROOT) or (ROOT/name).is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            raise ValueError('release hash/path mismatch: '+name)
    return r


def check():
    release=verify_release()
    import numpy,pytz,tqdm
    from heuristic_design.core import evolution_v1 as e
    from experiments.common.run_frozen import check_only
    expected=check_only(ROOT/'experiments/fjsp_long/research.pending.json')
    if expected['ready'] or not expected['pending']:raise ValueError('research draft unexpectedly became runnable')
    c=settings(1,2);e.config(c)
    return {'environment':'import_passed','protocol_check':'unfrozen_expected_rejection',
            'protocol_pending':expected['pending'],'engine_commit':release['commit'],
            'python':platform.python_version(),'dependencies':{'numpy':numpy.__version__,'pytz':pytz.__version__,'tqdm':tqdm.__version__},
            'isolation':guard.assert_isolated()}


def settings(api,cpu):
    value=json.loads((ROOT/'experiments/fjsp_long/mock.json').read_text())['settings']
    c=copy.deepcopy(value)
    c.update(api_concurrency=api,evaluation_concurrency=cpu,mock_reverse_delay=True)
    c['execution_contract'].update(group='cluster-noapi-acceptance',run_id='cluster-noapi-mock',
                                  window_seconds=1800,segment_seconds=600,drain_seconds=120)
    guard.preflight(c,False)
    return c


def semantic(s):
    return {k:s[k] for k in ('population','rng','generations','seen','generation_requests',
            'initialization_requests','initialization_complete','completed_tasks')}


def run(output):
    checked=check()
    if os.environ.get('SLURM_JOB_ID') is None and not os.environ.get('HDL_LOCAL_OFFLINE_ACCEPTANCE'):
        raise ValueError('Mock compute belongs on a Slurm compute node; local tests require explicit offline test switch')
    output=Path(output).resolve()
    if not output.is_relative_to(ROOT/'acceptance') or output.exists():raise ValueError('new isolated acceptance directory required')
    output.mkdir(parents=True)
    from heuristic_design.core import evolution_v1 as e
    from heuristic_design.core.execution_export import export
    from heuristic_design.core.storage import read,write,digest,sha
    import heuristic_design.problems.routing_fixtures as fixtures
    fixtures.solve=guard.deny
    states=[];cases={}
    for name,api,cpu,resume in (('serial',1,1,False),('parallel',2,2,False),('resume',1,2,True)):
        directory=output/name
        e.prepare(directory,settings(api,cpu))
        if resume:
            first=e.run(directory,max_tasks=3)
            if first['phase']!='paused' or first['completed_tasks']!=3:raise AssertionError('pause prefix mismatch')
            clock=read(directory/'Run_clock.json');checkpoint=read(directory/'checkpoint.json')
            write(output/'pause-receipt.json',{'checkpoint':checkpoint,'clock':clock,'writer_lock_released':not (directory/'.coordinator.lock').exists()})
        result=e.run(directory)
        p,s=e.check(directory);states.append(semantic(s))
        if result['phase']!='completed' or (s['initialization_requests'],s['generation_requests'])!=(2,7):raise AssertionError('Mock attempt plan mismatch')
        if resume and read(directory/'Run_clock.json')!=clock:raise AssertionError('resume changed original deadline')
        summary=export(directory,p,s)
        receipts=[read(directory/r['path'])['mock_worker'] for r in s['evaluations'].values()]
        if any(v['real_solves'] or v['model_requests'] or v['pid']==os.getpid() for v in receipts):raise AssertionError('non-Mock process receipt')
        intervals=sorted((v['started_at'],v['finished_at']) for v in receipts)
        overlap=any(b[0]<a[1] for a,b in zip(intervals,intervals[1:]))
        calls_overlap=False
        for batch_path in (directory/'batch-receipts').glob('*.json'):
            batch=read(batch_path)
            times=sorted((v['started_at_unix'],v['finished_at_unix']) for v in batch['evaluation_task_timings'].values())
            calls_overlap=calls_overlap or any(b[0]<a[1] for a,b in zip(times,times[1:]))
        if cpu==1 and calls_overlap or cpu==2 and not calls_overlap:
            raise AssertionError('configured evaluation concurrency not observed')
        cases[name]={'phase':result['phase'],'semantic_sha256':digest(states[-1]),
                     'protocol_sha256':sha(directory/'Protocol.json'),'worker_count':len({v['pid'] for v in receipts}),
                     'worker_overlap_observed':overlap,'evaluation_calls_overlap':calls_overlap,'summary':summary,
                     'writer_lock_released':not (directory/'.coordinator.lock').exists()}
    if not states[0]==states[1]==states[2]:raise AssertionError('serial/parallel/resume semantics differ')
    facts={'kind':'NO_API_SYNTHETIC_ACCEPTANCE_NOT_RESEARCH','passed':True,
           'engine_commit':checked['engine_commit'],'environment':checked,'cases':cases,
           'serial_parallel_resume_equal':True,'isolation':guard.assert_isolated(),
           'job_id':os.environ.get('SLURM_JOB_ID'),'host':platform.node()}
    write(output/'acceptance.json',facts)
    files={str(p.relative_to(output)):sha(p) for p in output.rglob('*') if p.is_file()}
    write(output/'results-manifest.json',{'files':files,'engine_commit':checked['engine_commit']})
    return {'passed':True,'output':str(output),'job_id':facts['job_id'],
            'serial_parallel_resume_equal':True,'isolation':facts['isolation']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['check','run']);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:
        value=check() if args.action=='check' else run(args.output)
        print(json.dumps(value,ensure_ascii=False,indent=2))
    except Exception as exc:
        print(json.dumps({'passed':False,'category':'environment_or_Mock_acceptance_error',
                          'error_type':type(exc).__name__,'error':str(exc)},ensure_ascii=False),file=sys.stderr)
        raise SystemExit(2)
