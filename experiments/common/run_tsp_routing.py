#!/usr/bin/env python3
"""TSP common-state routing entry. Default: fixed offline smoke evaluation."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
# ===== 参数区：配置相对自身文件解析；本入口不创建或继承任何付费授权 =====
CONFIG=ROOT/'experiments/common/configs/tsp-routing-smoke.fixed.json'
RUN_ROOT=ROOT/'runs'
RUN_PREFIX='tsp-common-routing'
REPORT_REQUEST_NODES=[50,100,150,200,220]  # 报告阈值，不增加搜索预算；新运行时冻结
# ===== 参数区结束：复用既有执行、恢复和导出 =====
import argparse
from datetime import datetime
import json
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core import evolution_v1 as e, routing
from heuristic_design.core.evolution_export import export
from heuristic_design.core.storage import read
from heuristic_design.core.terminal_ops import settings, inputs, snapshot
from heuristic_design.problems import routing_fixtures as fixtures
from heuristic_design.problems.tsp.h_build import check_frozen, VERSION as H_VERSION
from heuristic_design.problems.tsp.reporting import initialize_u_analysis,u_snapshot,safe_report,session_start,session_end


def preflight(path):
    c=settings(path)
    if c['problem']!='tsp' or c['evaluation_mode']!='solve':raise ValueError('TSP solve configuration required')
    hs,data,origin=inputs(c)
    if hs is None or data is None:raise ValueError('explicit H and data required; no implicit fixture fallback')
    fixtures.compile_members('tsp',hs)
    h_document=read(c['h_file'])
    if isinstance(h_document,dict) and h_document.get('kind')==H_VERSION:
        check_frozen(c['h_file'],real=c['api_mode']=='real')
    refs=fixtures.precheck_instances('tsp',data)  # references only; no policy evaluation
    imports=read(c['p0_file']) if c['p0_file'] else None
    if c['initialization']=='import':
        if not isinstance(imports,list) or len(imports)!=c['population_size']:raise ValueError('exactly N P0 declarations required')
        keys=[routing.checked(r['candidate'],len(hs)).key for r in imports if r.get('source')]
        if len(keys)!=len(imports) or len(keys)!=len(set(keys)):raise ValueError('distinct sourced P0 required')
    evo=2*c['population_size']*c['generations']
    init=c['population_size'] if c['initialization']=='import' else min(c['initialization_candidate_cap'],c['initialization_request_cap'])
    return c,{'problem':'tsp','state_schema':e.schema_id('tsp'),'H_count':len(hs),
        'instances':len(data),'city_counts':sorted({len(r['value']['coordinates']) for r in data}),
        'generation_transport':c['api_mode'],'evaluation_mode':'solve','recording_mode':c['recording_mode'],
        'initialization_candidate_upper_bound':init,'evolution_slots':evo,
        'max_candidate_instance_rows':(init+evo)*len(data),'max_solve_passes':2*(init+evo)*len(data),
        'api_attempt_cap':c['api_attempt_cap'],'real_requests_authorized':c['real_requests_authorized'],
        'policy_solves':0,'API_requests':0,'references_computed':len(refs),'input_provenance':origin,
        'notice':'NN reference precheck only; Mock generation is not an LLM. No quality claim.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=CONFIG)
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--allow-api',action='store_true')
    parser.add_argument('--approve-budget',type=int,help='separate U-only cumulative attempt cap, must match config')
    parser.add_argument('--max-tasks',type=int)
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument('--check-only',action='store_true')
    for action in ('status','pause','resume','export'):actions.add_argument('--'+action,type=Path)
    args=parser.parse_args();token=None;directory=None
    try:
        if args.max_tasks is not None and args.max_tasks<1:raise ValueError('max-tasks must be positive')
        existing=next((getattr(args,k) for k in ('status','pause','resume','export') if getattr(args,k)),None)
        if existing:
            directory=existing.resolve()
            if args.status:result=snapshot(directory,problem='tsp')
            elif args.pause:
                snapshot(directory,problem='tsp');result=e.request_pause(directory)
            elif args.export:
                snapshot(directory,problem='tsp');result=export(directory)
            else:
                p,s=e.check(directory)
                if p['config']['problem']!='tsp' or s['phase']!='paused':raise ValueError('resume requires a paused TSP run')
                if p['config']['api_mode']=='real' and args.approve_budget!=p['config']['api_attempt_cap']:
                    raise PermissionError('resume must acknowledge original total U attempt cap; never reset it')
                token=session_start(directory,'resume')
                result=e.run(directory,max_tasks=args.max_tasks,allow_api=args.allow_api,on_progress=u_snapshot)
                export(directory)
        else:
            c,facts=preflight(args.config)
            print(json.dumps(facts,ensure_ascii=False,indent=2))
            if args.check_only:return 0
            if c['api_mode']=='real' and args.allow_api and args.approve_budget==c['api_attempt_cap']:
                c['real_requests_authorized']=True
            # Gate before creating a run directory. No authorization file is written.
            from heuristic_design.llm.routing_transport import preflight as transport_check
            transport_check(c,args.allow_api)
            stamp=datetime.now(ZoneInfo('Asia/Manila')).strftime('%Y%m%d-%H%M%S-%f')
            directory=(args.run_dir or RUN_ROOT/f'{RUN_PREFIX}-{stamp}-{uuid4().hex[:8]}').resolve()
            if not directory.is_relative_to(ROOT/'runs'):raise ValueError('new run must stay in this worktree runs/')
            e.prepare(directory,c)
            initialize_u_analysis(directory,request_nodes=REPORT_REQUEST_NODES)
            (directory/'Launcher_snapshot.py').write_bytes(Path(__file__).read_bytes())
            print(json.dumps({'run_directory':str(directory)},ensure_ascii=False),flush=True)
            token=session_start(directory,'run')
            result=e.run(directory,max_tasks=args.max_tasks,allow_api=args.allow_api,on_progress=u_snapshot)
            export(directory)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        print(f'运行目录：{directory}\n导出：{directory/"exports"}')
        return 2 if result.get('phase')=='initialization_incomplete' else 0
    except (ValueError,FileNotFoundError,FileExistsError,PermissionError) as exc:
        print(f'TSP启动停止：{type(exc).__name__}: {exc}',file=sys.stderr);return 2
    finally:
        if token:
            session_end(directory,token)
            safe_report(directory)


if __name__=='__main__':raise SystemExit(main())
