"""Geometric, language, mixture and deterministic state checks."""
import math,tempfile,unittest
from pathlib import Path
import numpy as np
from heuristic_design.problems.tsp import candidates as c
from heuristic_design.problems.tsp.solver import distances,tour_length,nearest_neighbor,construct
from heuristic_design.core import mixing as m
from heuristic_design.problems.tsp.campaign import manual_pool,static_candidate
from heuristic_design.problems.tsp.data import generate
from heuristic_design.core.storage import read,sha
from heuristic_design.core.results import validate_complete


class Tests(unittest.TestCase):
    def test_triangle_closing_edge_and_square_ties(self):
        d=distances([[0,0],[1,0],[0,1]]);tour,length=nearest_neighbor(d)
        self.assertEqual(tour,(0,1,2,0));self.assertAlmostEqual(length,2+math.sqrt(2))
        d=distances([[0,0],[1,0],[1,1],[0,1]]);self.assertEqual(nearest_neighbor(d),((0,1,2,3,0),4.))
        for bad in [(0,1,2,0),(1,0,2,3,1),(0,1,1,3,0)]:
            with self.assertRaises(ValueError):tour_length(d,bad)

    def test_NN_rule_and_recheck(self):
        for n in [3,4,9,50]:
            d=distances(np.random.default_rng(n).random((n,2)));h=c.compile_candidate(c.checked(manual_pool()[0]['candidate'],1),1)
            r=construct(d,[h],lambda *x:(0,(1,)))
            self.assertEqual((r.tour,r.length),nearest_neighbor(d));self.assertEqual(r,construct(d,[h],lambda *x:(0,(1,))))
            self.assertEqual(r.tour,construct(d,[h],lambda *x:(1,(3,))).tour)

    def test_states_and_remaining_excludes_candidate(self):
        d=distances([[0,0],[1,0],[1,1],[0,1]]);r=construct(d,[lambda *x:1],lambda *s:(0,(1,)))
        self.assertEqual(r.tour,(0,1,2,3,0));self.assertEqual([t['state']['progress'] for t in r.trace],[0,1/3,2/3])
        self.assertEqual([t['state']['previous_heuristic'] for t in r.trace],[-1,0,0])
        self.assertEqual(r.trace[-1]['action_features'][0]['mean_remaining_distance'],0)
        self.assertEqual(r.trace[-1]['action_features'][0]['nearest_remaining_distance'],0)
        self.assertAlmostEqual(r.trace[0]['action_features'][0]['mean_remaining_distance'],(1+math.sqrt(2))/(2*math.sqrt(2)))

    def test_mixture_parity_and_invalid_outputs(self):
        from fjsp_usage.usage_v2.execution import decode_output,combine_scores
        for out in [(0,(-2,-2,0)),(1,(0,3,0)),(1,(1e100,1e-100,0)),(1,(1,1,0))]:self.assertEqual(m.decode_output(out,3),decode_output(out,3))
        cols={0:(2.,2.,2.),1:(-3.,0.,9.)};self.assertEqual(m.combine_scores(cols,(.3,.7),(0,1)),combine_scores(cols,(.3,.7),(0,1)))
        self.assertEqual(m.combine_scores(cols,(.3,.7),(0,))[0],cols[0])
        for out in [(1,(0,0,0)),(1,(1,1,1)),(1,(-1,2,0)),(True,(1,0,0)),(0,[1,0,0]),(0,(float('nan'),0,0))]:
            with self.assertRaises(ValueError):m.decode_output(out,3)

    def test_language(self):
        good=static_candidate((0,1),3);self.assertEqual(c.compile_candidate(c.checked(good,3),3)(0,0,0,0,-1),(1,(1,1,0)))
        for body in ['import os\n','def priority('+', '.join(c.H_ARGS)+'):\n return distance_current.real\n','def priority('+', '.join(c.H_ARGS)+'):\n while True: pass\n return 1\n']:
            with self.assertRaises(c.CandidateError):c.validate(body,kind='h')
        d=distances([[0,0],[1,0],[0,1]])
        for h in [lambda *x:True,lambda *x:float('inf')]:
            with self.assertRaises(ValueError):construct(d,[h],lambda *x:(0,(1,)))

    def test_data(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'data';m=generate(p);self.assertEqual([len(m[k]) for k in ['train','validation','confirmation','transfer']],[20,10,20,10])
            self.assertEqual(len({r['coordinate_sha256'] for rows in m.values() for r in rows}),60)
            for rows in m.values():
                for r in rows:self.assertEqual(sha(p/r['path']),r['sha256']);self.assertEqual(len(read(p/r['path'])['coordinates']),r['cities'])
            with self.assertRaises(ValueError):generate(p)

    def test_no_prefix_fitness(self):
        r={'valid':True,'fitness':-1.,'total_instances':2,'instances':[{'file':'a','score':-1.}]}
        with self.assertRaises(ValueError):validate_complete(r,[{'file':'a'},{'file':'b'}])

    def test_original_operator_instructions_and_independent_context(self):
        from heuristic_design.core.operators import CROSS,MUTATE
        from fjsp_usage.usage_v2.prompts import CROSS as a,MUTATE as b
        from heuristic_design.problems.tsp.prompts import build
        self.assertEqual((CROSS,MUTATE),(a,b))
        members=[r['candidate'] for r in manual_pool()[:2]]
        t=build({'candidate_kind':'U'},{'operator':'I1'},[],members)
        self.assertNotIn('PARENT 0',t)
        parents=[{'id':'p1','candidate':static_candidate((0,),2)},{'id':'p2','candidate':static_candidate((1,),2)}]
        text=build({'candidate_kind':'U'},{'operator':'CROSS'},parents,members)
        self.assertIn(CROSS.replace('selection relationship','usage relationship').replace('selector','usage program').replace('complete-schedule','complete-tour'),text)
        self.assertNotIn('train_fitness',text)

    def test_preview_never_calls_transport_or_solver(self):
        from unittest.mock import patch
        from heuristic_design.problems.tsp.campaign import load_config,ROOT
        with patch('socket.socket.connect',side_effect=AssertionError('NO NETWORK')),patch('heuristic_design.problems.tsp.solver.construct',side_effect=AssertionError('NO SOLVE')),patch('heuristic_design.llm.legacy.JsonCandidateTransport',side_effect=AssertionError('NO CLIENT')):
            config=load_config(ROOT/'experiments/tsp/configs/pilot-real.json')
        self.assertEqual(config['api_attempt_cap'],75)

    def test_global_50_75_budget_survives_journal_reopen(self):
        from heuristic_design.llm.legacy import ClientConfig,AttemptJournal
        from fjsp_usage.research_real.budget import BudgetStop
        from heuristic_design.problems.tsp.campaign import load_config,ROOT
        class Transport:
            identity='MOCK_BUDGET_TEST';secret='';redact=staticmethod(str)
            def __init__(self):self.sent=0
            def preflight(self,prompt):pass
            def dispatch(self,key,prompt,*,kind='U',on_sent):
                self.sent+=1;on_sent()
                n=int(key.split('/task')[-1].split('/')[0])
                if n<25 and key.endswith('/attempt/01'):raise TimeoutError('MOCK temporary failure')
                return {'text':'MOCK first complete response','usage':None}
        config=ClientConfig({'config':load_config(ROOT/'experiments/tsp/configs/pilot-mock.json'),'budgets':{'logical_generation':50}})
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'journal.json';transport=Transport()
            def journal():return AttemptJournal(path,config=config,context='MOCK',phase='batch',transport=transport,sleep=lambda x:None)
            j=journal()
            for n in range(50):
                self.assertEqual(j.request('task'+str(n),'same prompt',kind='h' if n<10 else 'U')['status'],'completed')
                if n==29:j=journal()
            self.assertEqual((j.calls,j.attempt_count,transport.sent),(50,75,75))
            self.assertEqual(j.request('task49','same prompt')['text'],'MOCK first complete response')
            with self.assertRaises(BudgetStop):j.request('extra','p')
            self.assertEqual(transport.sent,75)

    def test_bound_config_change_is_rejected(self):
        import json,shutil
        from heuristic_design.problems.tsp import campaign as camp
        from heuristic_design.core.storage import write
        with tempfile.TemporaryDirectory(dir=camp.ROOT/'runs',prefix='tsp-identity-') as t:
            config=Path(t)/'c.json';shutil.copyfile(camp.ROOT/'experiments/tsp/configs/pilot-mock.json',config)
            run=Path(t).with_name(Path(t).name+'-campaign')
            try:
                camp.prepare(config,run)
                value=read(config);value['real_requests_authorized']=True;write(config,value)
                with self.assertRaises(ValueError):camp.check(run)
                self.assertFalse((run/'API_attempts.json').exists())
            finally:shutil.rmtree(run)

    def test_description_wrapper_compatibility_never_changes_code(self):
        code=manual_pool()[0]['candidate']['code']
        a=c.parse('{A numeric rule.}\n```python\n'+code+'```','h',1)
        b=c.parse('A numeric rule.\n\n```python\n'+code+'```','h',1)
        self.assertEqual(a,b);self.assertEqual(a.code,c.validate(code,'A numeric rule.','h',1).code)
        for text in ['```python\n'+code+'```','A rule.\n```python\n'+code+'```\nextra text','A rule.\n```python\n'+code+'```\n```python\n'+code+'```']:
            with self.assertRaises(c.CandidateError):c.parse(text,'h',1)
