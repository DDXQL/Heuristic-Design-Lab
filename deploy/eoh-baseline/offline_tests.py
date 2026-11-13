#!/usr/bin/env python3
"""Finite synthetic receipts only. Network, real transport and solve entry points fail closed."""
from pathlib import Path
import ast
import copy
import json
import os
import socket
import sys
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'deploy/eoh-baseline'),str(ROOT/'code'),str(ROOT)]
import eoh_gap as e
from heuristic_design.core import execution
from heuristic_design.problems import routing_fixtures
from heuristic_design.llm import strict_nonstream


def deny(*args,**kwargs):raise AssertionError('OFFLINE TEST: real API / network / solver forbidden')


def main():
    stamp=time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid())
    report=ROOT/'reports/fjsp-eoh-gap-prep-20261113'/('offline-'+stamp);report.mkdir(parents=True)
    template=e.read(e.HERE/'mock.json');cases={};dirs={}
    def config(name,**values):
        c=copy.deepcopy(template);c.update(values);c['data_manifest']=str(ROOT/'preparations/eoh-gap/train21.manifest.json')
        path=report/(name+'.json');e.write(path,c);return path
    def run(name,**values):
        path=config(name,**values);d=ROOT/'runs'/('eoh-J-OFFLINE-'+stamp+'-'+name);dirs[name]=str(d)
        e.prepare(d,path);a=e.Adapter();result=execution.start(d,adapter=a);e.export(d)
        return d,result
    with patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny),\
         patch.object(strict_nonstream.StrictNonstreamTransport,'__init__',deny),\
         patch.object(routing_fixtures,'solve',deny),patch.object(e,'evaluate_task',deny):
        # Explicitly no runtime-key helper import/read. Saved auth remains false.
        pending=e.check(e.HERE/'research.pending.json')
        assert pending['environment_check']=='passed' and pending['protocol_check']=='unfrozen_expected_rejection'
        try:e.prepare(ROOT/'runs'/('forbidden-'+stamp),e.HERE/'research.pending.json')
        except PermissionError as x:assert 'PROTOCOL_UNFROZEN' in str(x)
        else:raise AssertionError('pending protocol prepared')
        cases['pending_rejection_separate_from_environment']=True
        d,result=run('normal');assert result['phase']=='completed',e.read(d/'Stop.json') if (d/'Stop.json').exists() else result
        p,s=e.protocol_state(d);summary=e.Adapter().summary(d)
        assert summary['initialization_attempts']==2 and summary['evolution_attempts']==8 and summary['request_reservations']==10
        assert summary['remaining_cumulative_requests']==2 and summary['actual_API_confirmed_sends']==0 and summary['confirmed_native_solve_passes']==0
        values=list(s['tasks'].values());best=min((t for t in values if t['valid']),key=lambda t:(t['J'],t['id']))
        assert summary['champion_id']==best['id'] and summary['best_J']==best['J']
        assert [t['operator'] for t in values[2:]]==['E1','E2','M1','M2']*2
        for t in values:
            if t['valid']:assert t['fitness']==-t['J']
        curve=e.read(d/'analysis/J_curve.json');finite=[r['best_J'] for r in curve if r['best_J'] is not None]
        assert all(b<=a for a,b in zip(finite,finite[1:]))
        assert summary['native_population_duplicates']>0 # equal-J is native diversity policy
        cases['separate_caps_J_min_native_operators_and_equal_J_penalty']=summary
        paused,result=run('pause',pause_after_tasks=5);assert result['phase']=='paused'
        before=e.read(paused/'Run_clock.json');a=e.Adapter();resumed=execution.start(paused,adapter=a,resume=True)
        assert resumed['phase']=='completed' and e.read(paused/'Run_clock.json')==before
        e.export(paused);_,ss=e.protocol_state(paused)
        def identity(state):
            return [{k:t.get(k) for k in ('id','operator','parents','parent_keys','J','fitness','candidate','native_population_duplicate','cache_hit')} for t in state['tasks'].values()]
        assert identity(s)==identity(ss) and s['eoh']==ss['eoh']
        assert not (paused/'.execution.lock').exists()
        cases['pause_resume_exact_native_rng_population_candidates_and_deadline']=True
        bad,result=run('faults',mock_faults={'H-0003':'failure','H-0004':'invalid','H-0005':'duplicate','H-0006':'invalid_evaluation'})
        assert result['phase']=='completed',result
        q=e.Adapter().summary(bad)
        assert q['failed_transport_attempts']==1 and q['AST_duplicates']>=1 and q['cached_evaluations']>=1 and q['scientific_failures']>=3 and q['automatic_retries']==0
        assert q['request_reservations']==q['initialization_attempts']+q['evolution_attempts']
        cases['failures_duplicates_cached_evaluation_no_refill_no_retry']=q
        failed,result=run('three-transport-failures',mock_faults={'H-0002':'failure','H-0003':'failure','H-0004':'failure'})
        assert result['phase']=='paused' and result['cursor']==5
        cases['three_failures_safe_pause_no_automatic_restart']=True
        # Reuse native mechanism for structural source duplicates and exact final ties.
        fs=[e.old.native.make_function(best['candidate'],name,-0.1) for name in ('H-0002','H-0001')]
        pop=e.old.native.Population(2);pop.register_function(fs[0]);pop.register_function(fs[1]);assert fs[1].score==float('-inf')
        ties=[{'id':'H-0002','J':0.1},{'id':'H-0001','J':0.1}]
        assert min(ties,key=lambda t:(t['J'],t['id']))['id']=='H-0001'
        cases['native_duplicate_and_final_exact_tie_policy']=True
        # Verify real mapping statically/arithmetically; no real schedule construction.
        assert e.state_a_v3.score_final_cost(106,70)==(106-70)/70
        tree=ast.parse((ROOT/'code/heuristic_design/core/routing_evaluation.py').read_text())
        worker=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_worker')
        assert len([n for n in ast.walk(worker) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='solve'])==2
        cases['frozen_evaluator_two_solve_calls_shared_T30_and_J_arithmetic']=True
        # Unknown reservation / lock must fail; never delete or replay it.
        locked=ROOT/'runs'/('eoh-J-OFFLINE-'+stamp+'-unknown');e.prepare(locked,config('unknown'))
        (locked/'.execution.lock').write_text('{"state":"unknown"}')
        try:execution.start(locked,adapter=e.Adapter())
        except ValueError:pass
        else:raise AssertionError('unknown lock ignored')
        assert (locked/'.execution.lock').exists();dirs['unknown-preserved']=str(locked)
        cases['unknown_lock_preserved_no_replay']=True
    value=dict(passed=True,kind='PURE_OFFLINE_SYNTHETIC_RECEIPTS',API_requests=0,actual_solves=0,credential_reads=0,
               protected=['socket connect','real transport constructor','real evaluate_task','routing solve'],cases=cases,evidence=dirs)
    e.write(report/'result.json',value);e.write(ROOT/'reports/fjsp-eoh-gap-prep-20261113/latest-offline.json',value)
    print(json.dumps({'passed':True,'report':str(report/'result.json'),'API_requests':0,'actual_solves':0},indent=2))


if __name__=='__main__':main()
