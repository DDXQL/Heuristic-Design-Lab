#!/usr/bin/env python3
"""Independent J-min single-H EoH. Default check-only; real work is manual Slurm only."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'deploy/eoh-baseline'),str(ROOT/'code'),str(ROOT)]
import eoh_gap as e
from heuristic_design.core import execution
from experiments.common._single_run import _Tee


def runtime_key(c):
    # Called ONLY after a frozen protocol + explicit cumulative approval, on a compute node.
    if c['api_mode']=='mock':return
    if not os.environ.get('SLURM_JOB_ID'):raise PermissionError('real EoH requires the manually submitted Slurm allocation')
    path=Path(c['credential_file'])
    if not path.is_absolute() or path.is_symlink() or path.stat().st_mode & 0o077:raise PermissionError('runtime credential must be a private regular file')
    if not path.is_file():raise PermissionError('credential is not a regular file')
    key=path.read_text().strip()
    if not key or '\n' in key:raise ValueError('runtime credential format invalid')
    os.environ[c['provider']['api_key_env']]=key


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['check-only','prepare','run','status','pause','resume','report'],nargs='?',default='check-only')
    ap.add_argument('--config',type=Path,default=ROOT/'deploy/eoh-baseline/research.pending.json')
    ap.add_argument('--run-dir',type=Path,default=ROOT/'runs/fjsp-eoh-J-baseline-20261113-r1')
    ap.add_argument('--allow-api',action='store_true');ap.add_argument('--approve-budget',type=int)
    args=ap.parse_args();d=args.run_dir.resolve();adapter=e.Adapter()
    if args.action=='check-only':
        if args.allow_api or args.approve_budget is not None:raise PermissionError('check-only never carries API approval')
        print(json.dumps(e.check(args.config),ensure_ascii=False,indent=2));return 0
    if args.action in ('status','pause','report'):
        if args.allow_api or args.approve_budget is not None:raise PermissionError('read/control operation never carries API approval')
        adapter.check_run(d)
        value=execution.stop(d,adapter=adapter) if args.action=='pause' else e.export(d) if args.action=='report' else adapter.summary(d)
        print(json.dumps(value,ensure_ascii=False,indent=2));return 0
    if args.action=='resume':
        p=adapter.check_run(d);c=p['config'];e.authorize(c,args.approve_budget,args.allow_api,original_deadline=e.read(d/'Run_clock.json')['deadline'])
        runtime_key(c)
    else:
        if args.action=='run' and d.exists():
            p=adapter.check_run(d);c=p['config']
            e.authorize(c,args.approve_budget,args.allow_api)
            runtime_key(c)
        else:
            c,data,refs,origin,todo=e.preflight(args.config)
            if todo:raise PermissionError('PROTOCOL_UNFROZEN: '+', '.join(todo))
            e.authorize(c,args.approve_budget,args.allow_api)
            if args.action=='prepare':
                # File-only prepare: no credential read, dispatch or Slurm.
                e.prepare(d,args.config,approve_budget=args.approve_budget,allow_api=args.allow_api)
                print(json.dumps({'prepared':True,'run_directory':str(d),'API_requests':0,'actual_solves':0,'credential_reads':0}));return 0
            runtime_key(c)
            e.prepare(d,args.config,approve_budget=args.approve_budget,allow_api=args.allow_api)
    p=adapter.check_run(d)
    if p['config']['api_mode']=='real':
        if int(os.environ.get('SLURM_CPUS_PER_TASK','0'))<p['config']['resources']['cpus']:raise ValueError('allocation CPU below frozen plan')
        adapter.segment_deadline=time.monotonic()+p['config']['resources']['walltime_seconds']-120
    with (d/'terminal.log').open('a') as log,redirect_stdout(_Tee(sys.stdout,log)),redirect_stderr(_Tee(sys.stderr,log)):
        value=execution.start(d,adapter=adapter,resume=args.action=='resume',allow_api=args.allow_api)
        print(json.dumps(value,ensure_ascii=False))
    print(json.dumps(e.export(d),ensure_ascii=False,indent=2))
    return 0 if value['phase'] in ('completed','paused') else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__,'error':str(exc),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
