#!/usr/bin/env python3
"""H10 entry: default blocked real build; explicit budget approval is terminal-only."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
CONFIG=ROOT/'experiments/common/configs/tsp-h10.real.pending.json'
RUN_ROOT=ROOT/'runs'
RUN_PREFIX='tsp-h10'
import argparse
from contextlib import redirect_stdout,redirect_stderr
from datetime import datetime
import json
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.problems.tsp import h_build as h
from heuristic_design.problems.tsp.reporting import safe_report, session_start, session_end
from heuristic_design.core import execution
from heuristic_design.core.storage import read
from experiments.common._single_run import _Tee


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=CONFIG)
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--approve-budget',type=int,help='explicit new H-only request cap, must match config; no inherited grants')
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument('--check-only',action='store_true')
    for action in ('status','pause','resume','report'):actions.add_argument('--'+action,type=Path)
    args=parser.parse_args();directory=None;token=None
    try:
        existing=next((getattr(args,k) for k in ('status','pause','resume','report') if getattr(args,k)),None)
        adapter=h.Adapter()
        if existing:
            directory=existing.resolve()
            if args.status:
                p,s=h.protocol_state(directory)
                j=read(directory/'API_attempts.json') if (directory/'API_attempts.json').exists() else {'api_attempts':{}}
                print(json.dumps({**adapter.summary(directory),'reserved_attempts':len(j['api_attempts']),
                    'API_attempt_cap':p['config']['api_attempt_cap'],'writer_lock':(directory/'.execution.lock').exists(),
                    'freeze':read(directory/'H_build_outcome.json') if (directory/'H_build_outcome.json').exists() else None},ensure_ascii=False,indent=2));return 0
            if args.pause:print(execution.stop(directory,adapter=adapter));return 0
            if args.report:return 0 if safe_report(directory) else 2
            p=adapter.check_run(directory)
            if p['config']['api_mode']=='real' and args.approve_budget!=p['config']['api_attempt_cap']:
                raise PermissionError('resume needs original total --approve-budget; remaining budget never resets')
        else:
            c,data,refs,origin=h.preflight(args.config)
            print(json.dumps({'config':str(args.config.resolve()),'origin_mode':c['api_mode'],'final_H_count':10,
               'logical_candidate_cap':c['candidate_cap'],'API_attempt_cap':c['api_attempt_cap'],
               'max_candidate_instance_rows':c['candidate_cap']*len(data),'max_solve_passes':2*c['candidate_cap']*len(data),
               'instances':len(data),'selection':h.METRICS['selection'],'H_evolution_generations':0,
               'real_requests_authorized':False,'requests_sent':0,'policy_solves':0,'references_computed':len(refs)},ensure_ascii=False,indent=2))
            if args.check_only:return 0
            stamp=datetime.now(ZoneInfo('Asia/Manila')).strftime('%Y%m%d-%H%M%S-%f')
            directory=(args.run_dir or RUN_ROOT/f'{RUN_PREFIX}-{stamp}-{uuid4().hex[:8]}').resolve()
            h.prepare(directory,args.config,approve_budget=args.approve_budget)
        print(f'运行目录：{directory}',flush=True)
        token=session_start(directory,'resume' if args.resume else 'run')
        with (directory/'terminal.log').open('a') as log,redirect_stdout(_Tee(sys.stdout,log)),redirect_stderr(_Tee(sys.stderr,log)):
            result=execution.start(directory,adapter=adapter,resume=bool(args.resume),
                allow_api=args.approve_budget is not None,background=False)
            print(json.dumps(adapter.summary(directory,write_files=True),ensure_ascii=False,indent=2))
        return 0 if result['phase']=='paused' or ((directory/'H_frozen.json').exists() and result['phase']=='completed') else 2
    except Exception as exc:
        print(f'H构建停止：{type(exc).__name__}: {exc}',file=sys.stderr);return 2
    finally:
        if token:session_end(directory,token)
        if token:safe_report(directory)


if __name__=='__main__':raise SystemExit(main())
