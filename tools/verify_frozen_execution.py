#!/usr/bin/env python3
"""Persist synthetic-receipt evidence. All real requests and solves forbidden."""
import os
for _key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS'):
    os.environ[_key]='1'
import argparse
import contextlib
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import sys
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core import evolution_v1 as engine
from heuristic_design.core.execution_export import export
from heuristic_design.core.storage import read,sha,write,digest


def verify(run_root,report):
    run_root=Path(run_root).resolve();report=Path(report).resolve()
    if run_root.exists() or report.exists():raise FileExistsError('new evidence directories required')
    run_root.mkdir(parents=True);report.mkdir(parents=True)
    spec=importlib.util.spec_from_file_location('test_frozen_execution_offline',ROOT/'tests/test_frozen_execution_offline.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with (report/'unit-tests.txt').open('w') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
    if not result.wasSuccessful():raise AssertionError('offline tests failed; evidence retained')
    facts={'label':'MOCK_OFFLINE_ENGINEERING_ONLY','model_requests':0,'constructive_solves':0,
           'unit_tests':result.testsRun,'cases':{},'assertions':{},'runtime_sources':engine.source_identity()}
    base=read(ROOT/'experiments/fjsp_long/mock.json')['settings'];states=[]
    for name,api,cpu,pause in (('serial',1,1,False),('parallel',2,2,False),('resume',1,2,True)):
        c=copy.deepcopy(base);c.update(api_concurrency=api,evaluation_concurrency=cpu,mock_reverse_delay=True)
        d=run_root/name
        with patch.object(socket.socket,'connect',side_effect=AssertionError('NO NETWORK')):
            engine.prepare(d,c)
            with (report/(name+'-console.jsonl')).open('w') as stream,contextlib.redirect_stdout(stream):
                if pause:
                    r=engine.run(d,max_tasks=3);assert r['phase']=='paused'
                    write(report/'safe-pause.json',read(d/'checkpoint.json'))
                result=engine.run(d)
        p,s=engine.check(d);states.append(module.semantic(s))
        export(d,p,s);shutil.copytree(d/'exports',report/name)
        shutil.copytree(d/'milestones',report/name/'milestones')
        receipts=[read(d/v['path']).get('mock_worker') for v in s['evaluations'].values()]
        write(report/name/'process-receipts.json',receipts)
        write(report/name/'Protocol.json',p)
        facts['cases'][name]={'phase':result['phase'],'initialization_attempts':s['initialization_requests'],
            'evolution_attempts':s['generation_requests'],'protocol_sha256':sha(d/'Protocol.json'),
            'semantic_sha256':digest(states[-1]),'run_directory':str(d),
            'separate_processes':len({r['pid'] for r in receipts}),
            'new_state':p['state_schema'],'u_abi':p['u_abi']}
    facts['assertions']['serial_parallel_resume_semantics_equal']=states[0]==states[1]==states[2]
    facts['assertions']['exact_evolution_attempt_prefix']=all(r['evolution_attempts']==7 for r in facts['cases'].values())
    facts['assertions']['all_v3']=all(r['new_state']=='common-state-a-v3-fjsp' for r in facts['cases'].values())
    assert all(facts['assertions'].values())
    write(report/'acceptance.json',facts)
    return {k:facts[k] for k in ('label','unit_tests','model_requests','constructive_solves','cases','assertions')}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(verify(args.run_root,args.report),ensure_ascii=False,indent=2))
