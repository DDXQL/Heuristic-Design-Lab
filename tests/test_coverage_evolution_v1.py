"""Mock-only lineage, caps, frozen parents, and deterministic safe recovery."""
from dataclasses import asdict
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from heuristic_design.core import evolution_v1 as e
from heuristic_design.core import routing
from heuristic_design.core.storage import read, write


def imports(n, k=3):
    return [{'source':f'handwritten-development-fixture-{i}',
             'candidate':asdict(routing.validate(f'def use_heuristics(state):\n    fixture_tag = {i}\n    return {i%k}\n',member_count=k))} for i in range(n)]


def settings(n=5,g=3,**kw):
    return dict(population_size=n,generations=g,generation_request_cap=2*n*g,**kw)


def semantic(s):
    return {k:s[k] for k in ('population','rng','generations','seen','generation_requests','initialization_requests','initialization_complete','completed_tasks')}


class Tests(unittest.TestCase):
    def test_subject_coverage_n5_n10_and_odd_population(self):
        for n in (3,5,10):
            pop=[{'id':str(i),'candidate':r['candidate'],'fitness':i} for i,r in enumerate(imports(n))]
            tasks=e.plan_generation(pop,1,random.Random(501))
            self.assertEqual(len(tasks),2*n)
            for row in pop:
                pair=[t for t in tasks if t['subject']==row['id']]
                self.assertEqual([t['operator'] for t in pair],['CROSS','MUTATE'])
                self.assertEqual(pair[0]['parents'][0],row['id'])
                self.assertNotEqual(*pair[0]['parents'])
                self.assertEqual(pair[1]['parents'],[row['id']])
                self.assertEqual(pair[1]['parent_keys'],[row['candidate']['key']])

    def test_three_generations_mock_and_pause_resume_same_plan_rng_population(self):
        with tempfile.TemporaryDirectory() as t:
            a,b=Path(t)/'a',Path(t)/'b'
            for folder in (a,b): e.prepare(folder,settings(initialization='import'),imports=imports(5))
            self.assertEqual(e.run(a)['phase'],'completed')
            self.assertEqual(e.run(b,max_tasks=18)['phase'],'paused')
            self.assertEqual(e.run(b)['phase'],'completed')
            pa,sa=e.check(a);pb,sb=e.check(b)
            self.assertEqual(semantic(sa),semantic(sb))
            g3=read(a/'plans/G003.json')
            self.assertTrue(any(r['id'].startswith('G002') for r in g3['population']))
            self.assertEqual(sa['generation_requests'],30)
            self.assertEqual(sa['initialization_requests'],0)
            for i in range(1,4):self.assertEqual(read(a/f'plans/G{i:03d}.json'),read(b/f'plans/G{i:03d}.json'))

    def test_llm_init_budget_duplicate_invalid_failure_no_baseline_borrow(self):
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'caps'
            faults={'INIT-0000':'duplicate','INIT-0001':'duplicate','INIT-0002':'invalid','INIT-0003':'failure'}
            e.prepare(a,settings(initialization_candidate_cap=4,initialization_request_cap=4,mock_faults=faults))
            r=e.run(a);s=e.check(a)[1]
            self.assertEqual(r['phase'],'initialization_incomplete')
            self.assertEqual(len(s['population']),1)
            self.assertEqual(s['initialization_requests'],4)
            self.assertEqual(s['generation_requests'],0)
            self.assertEqual(s['tasks']['INIT-0001']['failure'],'AST_duplicate')
            self.assertIsNone(s['tasks']['INIT-0001']['fitness'])
            self.assertEqual(s['tasks']['INIT-0002']['failure'],'parse_or_constraint')
            self.assertEqual(s['tasks']['INIT-0003']['failure'],'mock_transport')
            with self.assertRaises(ValueError):e.prepare(Path(t)/'bad',settings(initialization='import'),imports=imports(4))
            bad=imports(5);bad[1]=bad[0]
            with self.assertRaises(ValueError):e.prepare(Path(t)/'bad2',settings(initialization='import'),imports=bad)

    def test_20_generations_n10_and_separate_init_budget(self):
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'twenty'
            e.prepare(a,settings(n=10,g=20,api_concurrency=4,evaluation_concurrency=4))
            result=e.run(a)
            p,s=e.check(a)
            self.assertEqual(result['phase'],'completed')
            self.assertEqual(s['initialization_requests'],10)
            self.assertEqual(s['generation_requests'],400)
            self.assertEqual(len(s['generations']),20)
            self.assertEqual(len(s['population']),10)
            self.assertTrue(all(len(read(a/r['path'])['tasks'])==20 for r in s['plans'].values()))

    def test_out_of_order_concurrency_does_not_change_survival_or_caps(self):
        with tempfile.TemporaryDirectory() as t:
            a,b=Path(t)/'serial',Path(t)/'parallel'
            for directory,width in [(a,1),(b,4)]:
                e.prepare(directory,settings(api_concurrency=width,evaluation_concurrency=width,mock_reverse_delay=True))
                e.run(directory)
            sa,sb=e.check(a)[1],e.check(b)[1]
            self.assertEqual(semantic(sa),semantic(sb))
            receipts=[read(x) for x in (b/'batch-receipts').glob('*.json')]
            self.assertTrue(any(r['response_completion_order']!=r['semantics_commit_order'] for r in receipts))
            for tid,ta in sa['tasks'].items():
                tb=sb['tasks'][tid]
                self.assertEqual(ta.get('candidate'),tb.get('candidate'))
                self.assertEqual((ta['parents'],ta['fitness'],ta['valid']),(tb['parents'],tb['fitness'],tb['valid']))

    def test_cpu_width_independent_from_request_width_and_invalid_evaluations(self):
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'independent'
            e.prepare(a,settings(api_concurrency=1,evaluation_concurrency=4,
                        mock_faults={'G001-000-CROSS':'invalid_evaluation'}))
            e.run(a)
            s=e.check(a)[1]
            self.assertIsNone(s['tasks']['G001-000-CROSS']['fitness'])
            self.assertFalse(s['tasks']['G001-000-CROSS']['valid'])
            receipts=[read(x) for x in (a/'batch-receipts').glob('*.json')]
            self.assertTrue(any(len(r['evaluation_completion_order'])==4 for r in receipts))

    def test_partial_initialization_export_reports_actual_best_valid_candidate(self):
        from heuristic_design.core.evolution_export import export
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'partial'
            e.prepare(a,settings(api_concurrency=4))
            self.assertEqual(e.run(a,max_tasks=4)['phase'],'paused')
            s=e.check(a)[1]
            result=export(a)
            self.assertEqual(result['champion'],e.ranked(s['population'])[0])
            self.assertEqual(result['generation'],0)

    def test_legacy_or_changed_identity_and_ambiguous_send_are_not_replayed(self):
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/'unknown';e.prepare(a,settings())
            s=read(a/'checkpoint.json');s['tasks']['unknown']={'status':'request_reserved'};e.save(a,s)
            with patch.object(e,'mock_generate',side_effect=AssertionError('NO RESEND')):
                with self.assertRaisesRegex(ValueError,'in-flight'):e.run(a)
            b=Path(t)/'changed';e.prepare(b,settings());s=read(b/'checkpoint.json');s['version']='legacy';e.save(b,s)
            with self.assertRaisesRegex(ValueError,'identity'):e.run(b)
            with self.assertRaises(ValueError):e.config({'api_mode':'real'})



class BehaviorFirstTests(unittest.TestCase):
    """Pure data only: never invoke generation, solving or engine.run."""
    @staticmethod
    def row(tid,fitness,group):
        return {'id':tid,'fitness':fitness,'behavior_sha256':group}

    def test_default_policy_is_original_survival(self):
        from heuristic_design.core.search import survive
        pop=[self.row('p',4,'a'),self.row('q',3,'a')];children=[self.row('r',2,'b')]
        self.assertEqual(e.config({})['survival_policy'],'fitness')
        self.assertEqual(e.select_survivors(pop,children,{'population_size':2}),survive(pop,children,2))

    def test_explicit_policy_preserves_global_elite_and_group_best(self):
        from heuristic_design.core.search import survive_behavior_first
        pop=[self.row('a',10,'x'),self.row('b',9,'x')]
        children=[self.row('c',8,'y'),self.row('d',7,'z'),self.row('e',6,'y')]
        selected=survive_behavior_first(pop,children,3)
        self.assertEqual([r['id'] for r in selected],['a','c','d'])
        self.assertEqual(e.select_survivors(pop,children,{'population_size':3,'survival_policy':'behavior_first'}),selected)

    def test_too_few_groups_fill_ranked_candidates_to_N(self):
        from heuristic_design.core.search import survive_behavior_first
        pool=[self.row('a',10,'x'),self.row('b',9,'x'),self.row('c',8,'x'),self.row('d',1,'y'),self.row('e',0,'y')]
        selected=survive_behavior_first(pool,[],4)
        self.assertEqual([r['id'] for r in selected],['a','b','c','d'])
        self.assertEqual(len(selected),4)

    def test_single_group_matches_original_ranking(self):
        from heuristic_design.core.search import survive_behavior_first,survive
        pool=[self.row(str(i),i,'same') for i in range(9)]
        self.assertEqual(survive_behavior_first(pool,[],5),survive(pool,[],5))

    def test_fixed_ID_ties_and_input_completion_order_do_not_change_result(self):
        from copy import deepcopy
        from heuristic_design.core.search import survive_behavior_first
        pool=[self.row('a',10,'x'),self.row('b',10,'y'),self.row('c',10,'x'),self.row('d',9,'z')]
        original=deepcopy(pool);expected=['a','b','d']
        for seed in range(20):
            shuffled=deepcopy(pool);random.Random(seed).shuffle(shuffled)
            self.assertEqual([r['id'] for r in survive_behavior_first(shuffled[:2],shuffled[2:],3)],expected)
        self.assertEqual(pool,original)

    def test_reject_unknown_policy_missing_identity_duplicate_ID_or_bad_size(self):
        from heuristic_design.core.search import survive_behavior_first
        for value in ('typo',None,False):
            with self.assertRaises(ValueError):e.config({'survival_policy':value})
        with self.assertRaises(ValueError):e.select_survivors([],[],{'population_size':2,'survival_policy':'typo'})
        for pool,n in (([{'id':'a','fitness':1}],1),([self.row('a',1,'x')]*2,2),
                       ([self.row('a',1,'x')],2),([self.row('a',1,'x')],True)):
            with self.assertRaises(ValueError):survive_behavior_first(pool,[],n)

if __name__=='__main__':unittest.main()
