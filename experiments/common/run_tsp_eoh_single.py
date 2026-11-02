#!/usr/bin/env python3
"""Bounded TSP EoH single-H training. Default: check-only and real requests OFF."""
from pathlib import Path
import argparse
from contextlib import redirect_stdout, redirect_stderr
import json
import sys

ROOT=Path(__file__).resolve().parents[2]
CONFIG=ROOT/'experiments/common/configs/tsp-eoh-single.real.pending.json'
RUN=ROOT/'runs/tsp-eoh-single-real-20261102-01'
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.problems.tsp import eoh_single as e
from heuristic_design.problems.tsp.eoh_reporting import safe_report, report
from heuristic_design.problems.tsp.reporting import session_start,session_end
from heuristic_design.core import execution
from experiments.common._single_run import _Tee


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=CONFIG);parser.add_argument('--run-dir',type=Path,default=RUN)
    parser.add_argument('--allow-api',action='store_true');parser.add_argument('--approve-budget',type=int)
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument('--check-only',action='store_true');actions.add_argument('--run',action='store_true')
    for name in ('status','pause','resume','report'):actions.add_argument('--'+name,type=Path)
    args=parser.parse_args();token=None;directory=None
    try:
        adapter=e.Adapter()
        existing=next((getattr(args,k) for k in ('status','pause','resume','report') if getattr(args,k)),None)
        if existing:
            directory=existing.resolve()
            if args.status:print(json.dumps(adapter.summary(directory),ensure_ascii=False,indent=2));return 0
            if args.pause:print(execution.stop(directory,adapter=adapter));return 0
            if args.report:print(report(directory));return 0
            p=adapter.check_run(directory)
            if p['config']['api_mode']=='real' and (not args.allow_api or args.approve_budget!=p['config']['api_attempt_cap']):
                raise PermissionError('resume must acknowledge ORIGINAL EoH cap; no inherited grants or reset')
        else:
            c,data,refs,origin,binding=e.preflight(args.config)
            print(json.dumps(dict(mode=c['api_mode'],real_requests_authorized=False,API_requests=0,policy_solves=0,
                instances=len(data),references_computed=len(refs),N=c['population_size'],operators=['I1',*e.OPERATORS],
                api_attempt_cap=c['api_attempt_cap'],per_candidate_attempt_cap=1,
                initialization_HTTP_cap=c['initialization_request_cap'],native_initialization_evaluated_cap=c['initialization_sample_cap'],
                native_max_generations=None,max_candidate_instance_rows=c['candidate_cap']*len(data),
                max_solve_passes=2*c['candidate_cap']*len(data),comparison={k:v for k,v in binding.items() if k!='files'}),ensure_ascii=False,indent=2))
            if not args.run:return 0  # --check-only is also the no-action default
            directory=args.run_dir.resolve()
            e.prepare(directory,args.config,approve_budget=args.approve_budget,allow_api=args.allow_api)
        print(f'运行目录：{directory}',flush=True)
        token=session_start(directory,'resume' if args.resume else 'run')
        with (directory/'terminal.log').open('a') as log,redirect_stdout(_Tee(sys.stdout,log)),redirect_stderr(_Tee(sys.stderr,log)):
            result=execution.start(directory,adapter=adapter,resume=bool(args.resume),allow_api=args.allow_api,background=False)
            print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['phase'] in ('completed','paused') else 2
    except Exception as exc:
        print(f'EoH入口停止：{type(exc).__name__}: {exc}',file=sys.stderr);return 2
    finally:
        if token:
            session_end(directory,token)
            print(json.dumps(safe_report(directory),ensure_ascii=False))


if __name__=='__main__':raise SystemExit(main())
