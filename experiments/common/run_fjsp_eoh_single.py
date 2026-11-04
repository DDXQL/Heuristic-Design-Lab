#!/usr/bin/env python3
"""FJSP native EoH. Default check-only; manual new-budget approval required."""
from pathlib import Path
import argparse,json,sys
from contextlib import redirect_stdout,redirect_stderr
ROOT=Path(__file__).resolve().parents[2]
CONFIG=ROOT/'experiments/common/configs/fjsp-eoh-single.real.json'
RUN=ROOT/'runs/fjsp-eoh-single-nonstream-20261104-01'
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.problems.fjsp import eoh_single as e
from heuristic_design.core import execution
from experiments.common._single_run import _Tee

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config',type=Path,default=CONFIG);ap.add_argument('--run-dir',type=Path,default=RUN)
    ap.add_argument('--allow-api',action='store_true');ap.add_argument('--approve-budget',type=int)
    group=ap.add_mutually_exclusive_group()
    for name in ('run','check-only'):group.add_argument('--'+name,action='store_true')
    for name in ('status','pause','resume','report'):group.add_argument('--'+name,type=Path)
    args=ap.parse_args();directory=None
    try:
        if (args.allow_api or args.approve_budget is not None) and not (args.run or args.resume):raise ValueError('approval flags require --run or --resume')
        existing=next((getattr(args,k) for k in ('status','pause','resume','report') if getattr(args,k)),None)
        if existing:
            directory=existing.resolve();adapter=e.Adapter();p=adapter.check_run(directory)
            if args.status:print(json.dumps(adapter.summary(directory),ensure_ascii=False,indent=2));return 0
            if args.pause:print(json.dumps(execution.stop(directory,adapter=adapter),ensure_ascii=False));return 0
            if args.report:print(json.dumps(e.export(directory),ensure_ascii=False,indent=2));return 0
            if p['config']['api_mode']=='real':
                if not args.allow_api or type(args.approve_budget) is not int or args.approve_budget!=p['config']['api_attempt_cap']:
                    raise PermissionError('resume must acknowledge ORIGINAL cumulative cap; never an additional budget')
            elif args.allow_api or args.approve_budget is not None:raise PermissionError('Mock resume cannot carry paid approval')
        else:
            c,data,refs,origin,binding=e.preflight(args.config)
            print(json.dumps(dict(mode=c['api_mode'],evaluation_mode=c['evaluation_mode'],real_requests_authorized=False,
              instances=len(data),policy_solves=0,API_requests=0,population_size=c['population_size'],
              operators=['I1',*e.native.OPERATORS],total_attempt_cap=c['api_attempt_cap'],initialization_HTTP_subcap=c['initialization_request_cap'],
              initialization_evaluated_ceiling=c['initialization_sample_cap'],max_generations=None,
              api_concurrency=c['api_concurrency'],evaluation_concurrency=c['evaluation_concurrency'],stop_policy=e.STOP_POLICY,
              max_candidate_instance_rows=c['api_attempt_cap']*len(data),max_solve_passes=2*c['api_attempt_cap']*len(data),
              transport_status=e.transport_status(c) if c['api_mode']=='real' else 'Mock_no_network',comparison=binding),ensure_ascii=False,indent=2))
            if not args.run:return 0
            directory=args.run_dir.resolve();e.prepare(directory,args.config,approve_budget=args.approve_budget,allow_api=args.allow_api)
        with (directory/'terminal.log').open('a') as log,redirect_stdout(_Tee(sys.stdout,log)),redirect_stderr(_Tee(sys.stderr,log)):
            result=execution.start(directory,adapter=e.Adapter(),resume=bool(args.resume),allow_api=args.allow_api)
            print(json.dumps(result,ensure_ascii=False,indent=2))
        e.export(directory);print(f'运行目录：{directory}\n日志：{directory / "terminal.log"}\n结果：{directory / "analysis"}')
        return 0 if result['phase'] in ('completed','paused') else 2
    except Exception as exc:
        print(f'FJSP EoH停止：{type(exc).__name__}: {exc}',file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
