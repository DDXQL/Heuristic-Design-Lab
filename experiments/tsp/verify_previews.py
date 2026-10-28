#!/usr/bin/env python3
"""Exercise actual old/new CLI previews with network and solvers forbidden."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'code')]
from contextlib import redirect_stdout,redirect_stderr,ExitStack
import io,json,runpy
from unittest.mock import patch
from heuristic_design.problems.tsp import solver,operations
from tools import experiment_ops

commands=[
 ['experiments/tsp/manage.py','--help'],
 ['experiments/manage.py','--problem','tsp','--help'],
 ['experiments/manage.py','--problem','tsp','doctor'],
 ['experiments/tsp/manage.py','check','--config','experiments/tsp/configs/pilot-real.json'],
 ['experiments/manage.py','--problem','tsp','plan','--config','experiments/tsp/configs/pilot-mock.json'],
 ['experiments/manage.py','--problem','fjsp','--help'],
 ['experiments/manage.py','--problem','fjsp','doctor'],
 ['experiments/fjsp/manage.py','check','--config','experiments/fjsp/configs/fixed-toy.json'],
 ['experiments/manage.py','--problem','fjsp','plan','--config','experiments/fjsp/configs/fixed-toy.json'],
 ['experiments/manage.py','--problem','tsp','--state-schema','constructive-common-v0-draft','doctor']]
results=[]
with ExitStack() as stack:
    for name in ['socket.socket.connect','socket.create_connection']:
        stack.enter_context(patch(name,side_effect=AssertionError('NO NETWORK')))
    stack.enter_context(patch.object(solver,'construct',side_effect=AssertionError('NO TSP SOLVE')))
    stack.enter_context(patch.object(experiment_ops.certified,'construct_usage_schedule',side_effect=AssertionError('NO FJSP SOLVE')))
    stack.enter_context(patch.object(operations,'JsonCandidateTransport',side_effect=AssertionError('NO API CLIENT')))
    for args in commands:
        output,error=io.StringIO(),io.StringIO();exitcode=0
        with patch('sys.argv',args),redirect_stdout(output),redirect_stderr(error):
            try:runpy.run_path(str(ROOT/args[0]),run_name='__main__')
            except SystemExit as exc:exitcode=exc.code or 0
        expected=2 if 'constructive-common-v0-draft' in args else 0
        assert exitcode==expected,(args,exitcode,error.getvalue())
        results.append({'command':args,'exitcode':exitcode,'expected':expected,'stdout':output.getvalue(),'stderr':error.getvalue()})
path=ROOT/'reports/TSP最新成果迁移-20261028-v1/CLI_preview_checks.json'
path.write_text(json.dumps({'passed':True,'commands':results,'API_calls':0,'solves':0,'guard':'real CLI paths; sockets, transport constructor and both solvers forbidden'},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'passed':True,'commands':len(results),'API_calls':0,'solves':0}))
