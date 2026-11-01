"""TSP compact receipts, physical parity and terminal roundtrip, with no network."""
import csv
from dataclasses import asdict
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from heuristic_design.core import evolution_v1 as e, routing
from heuristic_design.core.evolution_export import export
from heuristic_design.core.storage import read, digest
from heuristic_design.problems import routing_fixtures as fixtures
from heuristic_design.problems.tsp.routing import construct
from heuristic_design.problems.tsp.solver import distances, nearest_neighbor, SCALE, tour_length
from experiments.common.run_tsp_routing import preflight, CONFIG, main, ROOT


def p0():
    return [{'source':'handwritten-test','candidate':asdict(routing.validate(
        f'def use_heuristics(state):\n    return {i}\n',member_count=3))} for i in (0,1)]


class Tests(unittest.TestCase):
    def test_full_compact_parity_sequence_closure_and_selected_calls(self):
        for n in (3,4,12):
            d=distances(np.random.default_rng(n).random((n,2)))
            def first(dc,*rest):return -dc
            def second(dc,*rest):return dc
            u=lambda s:0 if s['construction_progress']<.5 else 1
            a=construct(d,[first,second],u,trace=True)
            b=construct(d,[first,second],u,trace=False)
            self.assertEqual((a.tour,a.length,a.score,a.h_calls,a.member_sequence),
                             (b.tour,b.length,b.score,b.h_calls,b.member_sequence))
            self.assertEqual(b.trace,())
            self.assertEqual(len(b.member_sequence),n-1)
            self.assertEqual(list(b.member_sequence),[r['member_id'] for r in a.trace])
            self.assertEqual(sum(b.h_calls),n*(n-1)//2)
            self.assertEqual(b.length,tour_length(d,b.tour))
            self.assertIsNone(a.trace[0]['state']['previous_h_token'])
            self.assertFalse(a.trace[-1]['state']['availability']['action_delta_best_gap'])
            self.assertEqual(a.trace[-1]['state']['history_count'],n-2)
            self.assertLess(a.trace[-1]['state']['construction_progress'],1)
            def forbidden(*args):raise AssertionError('unselected H called')
            nn=construct(d,[first,forbidden],lambda s:0,trace=False)
            self.assertEqual(nn.tour,nearest_neighbor(d)[0]);self.assertEqual(nn.score,-1)
            self.assertEqual(nn.h_calls[1],0)

    def test_ties_distance_scale_and_state_scale(self):
        d=distances([[0,0],[1,0],[0,1],[1,1]])
        result=construct(d,[lambda *args:0],lambda s:0)
        self.assertEqual(result.tour,(0,1,2,3,0))
        row=result.trace[0]
        self.assertEqual(row['action_features'][0][0],1/SCALE)
        self.assertEqual(row['state']['action_delta_min'],1/(4*SCALE))
        self.assertEqual(row['committed_delta'],1/(4*SCALE))

    def test_prompt_contains_tsp_task_and_original_parents(self):
        parent={'id':'original','candidate':p0()[0]['candidate']}
        prompt=routing.build_prompt('tsp',{'operator':'CROSS'},[parent],fixtures.members('tsp'))
        for text in ('closed edge included','sqrt(2)','n-1','NN_length','smallest city ID',
                     'forced closing edge','mean_remaining_distance','No MIX','original',parent['candidate']['key']):
            self.assertIn(text,prompt)
        self.assertNotIn('flexible job shop',prompt)

    def test_preflight_explicit_inputs_and_budget(self):
        c,facts=preflight(CONFIG)
        self.assertEqual((facts['H_count'],facts['instances'],facts['max_solve_passes']),(5,2,12))
        self.assertFalse(c['real_requests_authorized'])
        pending=CONFIG.parent/'tsp-routing-real.pending.json'
        c,facts=preflight(pending)
        self.assertEqual((facts['api_attempt_cap'],facts['max_solve_passes']),(220,8800))
        with patch('heuristic_design.llm.routing_transport.preflight',side_effect=AssertionError('preflight must not dispatch')):
            preflight(pending)

    def test_real_template_blocked_before_creating_run_even_with_cli_gate(self):
        directory=ROOT/'runs/test-unapproved-tsp-never-created'
        self.assertFalse(directory.exists())
        with patch.object(sys,'argv',['run_tsp_routing.py','--config',str(CONFIG.parent/'tsp-routing-real.pending.json'),
                    '--allow-api','--run-dir',str(directory)]), \
                patch.object(socket.socket,'connect',side_effect=AssertionError('NO NETWORK')):
            self.assertEqual(main(),2)
        self.assertFalse(directory.exists())

    def test_solver_receipts_pause_resume_exports_and_parallel_parity(self):
        with tempfile.TemporaryDirectory() as t, patch.object(socket.socket,'connect',side_effect=AssertionError('NO NETWORK')):
            outputs=[]
            for mode,width in [('full',1),('compact',2)]:
                folder=Path(t)/mode
                e.prepare(folder,{'problem':'tsp','population_size':2,'initialization':'import',
                    'generations':1,'generation_request_cap':4,'evaluation_mode':'solve',
                    'recording_mode':mode,'evaluation_concurrency':width,'api_concurrency':1},imports=p0())
                paused=e.run(folder,max_tasks=1);self.assertEqual(paused['phase'],'paused')
                self.assertEqual(e.run(folder)['phase'],'completed')
                p,s=e.check(folder)
                for ev in s['evaluations'].values():
                    value=read(folder/ev['path']);self.assertTrue(value['valid'])
                    for row in value['instances']:
                        self.assertEqual(row['semantic_sha256'],row['recheck_semantic_sha256'])
                        self.assertEqual(row['captured_solves'],2)
                        self.assertEqual(len(row['member_sequence']),len(row['solution']['tour'])-2)
                        if mode=='compact':self.assertEqual(row['trace'],[])
                    self.assertEqual(value['behavior_sha256'],digest(value['behavior']))
                report=export(folder);outputs.append((s['population'],s['generations']))
                self.assertEqual(report['real_API_calls'],0)
                self.assertEqual((folder/'exports/champion.py').read_text(),report['champion']['candidate']['code'])
                with (folder/'exports/per_instance.csv').open() as f:
                    rows=list(csv.DictReader(f))
                self.assertEqual(len(rows),12)
                for row in rows:
                    self.assertEqual(len(json.loads(row['member_sequence'])),len(json.loads(row['tour']))-2)
                self.assertEqual(export(folder),report)
            self.assertEqual(outputs[0],outputs[1])


if __name__=='__main__':unittest.main()
