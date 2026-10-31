#!/usr/bin/env python3
"""Common-state terminal entry: Mock, fixed evaluation and gated real search."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core import evolution_v1 as e
from heuristic_design.core.storage import read
from heuristic_design.core.constructive_state import schema_id, SPEC_SHA256
from heuristic_design.core.terminal_ops import settings, inputs, snapshot


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--problem',choices=['fjsp','tsp'],required=True)
    p.add_argument('action',choices=['doctor','preview','prepare','run','resume','status','pause','export'])
    p.add_argument('--config',type=Path)
    p.add_argument('--run-dir',type=Path)
    p.add_argument('--p0-file',type=Path)
    p.add_argument('--max-tasks',type=int,help='safe pause after at least this many tasks; drain current batch')
    p.add_argument('--output',type=Path)
    p.add_argument('--allow-api',action='store_true',help='real run/resume only; also requires frozen config authorization and credentials')
    p.add_argument('--wait',action='store_true',help='pause: wait until writer releases lock')
    p.add_argument('--wait-seconds',type=float,default=300)
    args=p.parse_args()
    if args.max_tasks is not None and args.max_tasks<1:p.error('--max-tasks must be positive')
    try:
        if args.action=='doctor':
            import os
            c=settings(args.config) if args.config else e.config({'problem':args.problem})
            if c['problem']!=args.problem:raise ValueError('CLI/config problem mismatch')
            hs,data,origin=inputs(c)
            if hs is not None:
                from heuristic_design.problems.routing_fixtures import compile_members
                compile_members(args.problem,hs)
            if data is not None:
                from heuristic_design.problems.routing_fixtures import precheck_instances
                precheck_instances(args.problem,data)
            result={'problem':args.problem,'state_schema':schema_id(args.problem),'state_spec_sha256':SPEC_SHA256,
                    'abi':e.ABI,'real_transport_available':True,'network_requests_sent':0,
                    'configured_mode':c['api_mode'],'config_authorized':c['real_requests_authorized'],
                    'credential_present':bool(os.environ.get((c.get('provider') or {}).get('api_key_env',''))),
                    'input_provenance':origin,'default_concurrency':{'api':1,'evaluation':1}}
        elif args.action in ('preview','prepare'):
            if not args.config:p.error('--config required')
            c=settings(args.config)
            if c['problem']!=args.problem:raise ValueError('CLI/config problem mismatch')
            if args.action=='preview':
                result={'config':c,'evolution_candidates':2*c['population_size']*c['generations'],
                        'initialization_budget_separate':True,'requests_sent':0,'solves':0}
            else:
                if not args.run_dir:p.error('--run-dir required')
                result=e.prepare(args.run_dir,c,imports=read(args.p0_file) if args.p0_file else None)
        else:
            if not args.run_dir:p.error('--run-dir required')
            if args.action=='status':
                print(json.dumps(snapshot(args.run_dir,problem=args.problem),ensure_ascii=False,indent=2))
                return
            if args.action=='pause':
                # Control messages must be writable while the coordinator has
                # legitimate in-flight reservations; check() rejects these.
                protocol=read(args.run_dir/'Protocol.json')
                if protocol.get('version')!=e.VERSION or protocol['config']['problem']!=args.problem:
                    raise ValueError('foreign pause target')
                result=e.request_pause(args.run_dir)
                if args.wait:
                    import time
                    deadline=time.monotonic()+args.wait_seconds
                    while (args.run_dir/'.coordinator.lock').exists():
                        if time.monotonic()>=deadline:raise ValueError('pause requested but writer still active; inspect status, do not kill or resend')
                        time.sleep(.1)
                    result['status']=snapshot(args.run_dir,problem=args.problem)
                print(json.dumps(result,ensure_ascii=False,indent=2))
                return
            protocol,state=e.check(args.run_dir.resolve())
            if protocol['config']['problem']!=args.problem:raise ValueError('CLI/run problem mismatch')
            if args.action in ('run','resume'):
                expected=('prepared',) if args.action=='run' else ('paused',)
                if state['phase'] not in expected:raise ValueError('use run for prepared / resume for paused only')
                result=e.run(args.run_dir,max_tasks=args.max_tasks,allow_api=args.allow_api)
            elif args.action=='pause':result=e.request_pause(args.run_dir)
            else:
                from heuristic_design.core.evolution_export import export
                result=export(args.run_dir,args.output)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,FileExistsError,FileNotFoundError,PermissionError) as exc:
        p.error(str(exc))


if __name__=='__main__':main()
