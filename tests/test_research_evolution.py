"""Budgets, leakage boundaries, generation semantics and crash recovery."""

from dataclasses import replace
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))
sys.path.insert(0, str(ROOT))
from experiments.tier2.research_v1.run_offline import demo_members
from fjsp_usage.research.candidates import U_ARGS, compile_candidate, validate_code
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.evolution import Search, select_parents
from fjsp_usage.research.prompts import build_prompt
from fjsp_usage.research.protocol import SearchConfig
from fjsp_usage.research.requests import MockTransport, RequestJournal
from fjsp_usage.research.sets import complementary_survival, export_mock_set


def evaluator(candidate):
    # Same fitness intentionally: never dedup candidates merely by score.
    return {'valid': True, 'total_instances': 2, 'fitness': -1.5,
            'instances': [{'score': -1.}, {'score': -2.}]}


class RecordingMock(MockTransport):
    def __init__(self):
        self.calls = []
    def __call__(self, key, prompt, *, kind='U'):
        self.calls.append((key, prompt))
        return super().__call__(key, prompt, kind=kind)


class ResearchEvolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = SearchConfig(population_size=2, cross_parents=2, generations=2,
                                   initialization_cap=4)
        self.members = demo_members()

    def search(self, directory, *, arm='P', transport=None, initial=None, evaluate=evaluator, config=None):
        return Search(directory, arm=arm, config=config or self.config, members=self.members,
                      evaluator=evaluate, transport=transport or RecordingMock(),
                      context='fixture-data-and-source-lock', initial=initial)

    def test_four_arms_share_initial_and_use_five_or_two_operators(self):
        init = self.search(self.directory / 'init', arm='INIT')
        self.assertTrue(init.initialize())
        population = init.state['population']
        self.assertEqual(len(population), 2)  # equal fitness does not collapse to one
        for arm in ('B0', 'B1', 'B2', 'P'):
            transport = RecordingMock()
            search = self.search(self.directory / arm, arm=arm, transport=transport, initial=population)
            report = search.run()
            self.assertEqual(report['evolution_requests'], 20)
            self.assertEqual(report['initialization_requests'], 0)
            attempts = search.state['attempts']
            first = attempts[:10]
            self.assertTrue(all(set(a['parents']) <= {p['id'] for p in population} for a in first))
            counts = {op: sum(a['operator'] == op for a in first) for op in {a['operator'] for a in first}}
            self.assertEqual(counts, {'E1': 2, 'E2': 2, 'M1': 2, 'M2': 2, 'M3': 2}
                             if arm in ('B0', 'B1') else {'CROSS': 5, 'MUTATE': 5})
            for _, prompt in transport.calls:
                self.assertEqual('H MEMBER 0' in prompt, arm != 'B0')
                self.assertNotIn('"score":', prompt)

    def test_rank_weights_remain_original_after_each_draw(self):
        population = [{'id': str(i), 'fitness': -i} for i in range(4)]
        class ChooseFirst:
            def __init__(self): self.seen = []
            def choices(self, pool, *, weights, k):
                self.seen.append(tuple(weights))
                return [0]
        rng = ChooseFirst()
        selected = select_parents(population, 3, rng)
        self.assertEqual([p['id'] for p in selected], ['0', '1', '2'])
        self.assertEqual(rng.seen, [(1/4, 1/5, 1/6, 1/7), (1/5, 1/6, 1/7), (1/6, 1/7)])

    def test_resume_matches_uninterrupted_without_repeat_call_or_evaluation(self):
        evaluations = []
        def counted(candidate):
            evaluations.append(candidate.key)
            return evaluator(candidate)
        transport = RecordingMock()
        interrupted = self.search(self.directory / 'partial', transport=transport, evaluate=counted)
        interrupted.run(stop_after_attempts=7)
        resumed = self.search(self.directory / 'partial', transport=transport, evaluate=counted)
        report = resumed.run()
        reference = self.search(self.directory / 'reference')
        expected = reference.run()
        self.assertEqual(report['population'], expected['population'])
        self.assertEqual(resumed.state['attempts'], reference.state['attempts'])
        self.assertEqual(len(transport.calls), 22)
        self.assertEqual(len(evaluations), 22)
        resumed.run()
        self.assertEqual(len(transport.calls), 22)
        self.assertEqual(len(evaluations), 22)
        with self.assertRaises(ValueError):
            self.search(self.directory / 'partial', config=replace(self.config, seed=2))

    def test_duplicate_invalid_failure_consume_attempts_without_supplement(self):
        class Duplicate(MockTransport):
            def __call__(self, key, prompt, *, kind='U'):
                return super().__call__('INIT/init/0', prompt, kind=kind)
        search = self.search(self.directory / 'duplicates', transport=Duplicate())
        self.assertFalse(search.initialize())
        self.assertEqual(search.report()['initialization_requests'], 4)
        self.assertEqual(search.report()['evaluations_reserved'], 1)
        self.assertEqual(len(search.state['population']), 1)

    def test_request_failure_pending_and_hard_budget_are_durable(self):
        calls = []
        def failure(key, prompt, *, kind):
            calls.append(key)
            raise TimeoutError('mock network deadline')
        path = self.directory / 'requests.json'
        journal = RequestJournal(path, cap=2, transport=failure, identity='test')
        self.assertEqual(journal.request('0', 'prompt')['status'], 'failed')
        self.assertEqual(journal.request('0', 'prompt')['status'], 'failed')
        self.assertEqual(calls, ['0'])
        journal.request('1', 'prompt')
        with self.assertRaises(ValueError): journal.request('2', 'prompt')
        journal.data['requests']['1']['status'] = 'pending'
        atomic_json(path, journal.data)
        resumed = RequestJournal(path, cap=2, transport=failure, identity='test')
        self.assertEqual(resumed.request('1', 'prompt')['status'], 'interrupted')
        self.assertEqual(calls, ['0', '1'])
        with self.assertRaises(ValueError): resumed.request('0', 'changed prompt')

    def test_uncertain_evaluation_not_repeated_after_crash(self):
        def crash(candidate): raise KeyboardInterrupt()
        directory = self.directory / 'crash'
        first = self.search(directory, evaluate=crash)
        with self.assertRaises(KeyboardInterrupt): first.initialize()
        transport = RecordingMock()
        repeated = []
        def later(candidate):
            repeated.append(candidate.key)
            return evaluator(candidate)
        resumed = self.search(directory, transport=transport, evaluate=later)
        self.assertTrue(resumed.initialize())
        self.assertEqual(len(transport.calls), 2)  # pending first response reused
        self.assertEqual(len(repeated), 2)
        self.assertEqual(resumed.state['attempts'][0]['error_type'], 'InterruptedEvaluation')

    def test_prompts_never_include_parent_fitness_and_initial_never_H_details(self):
        c = validate_code('def select_heuristic(' + ', '.join(U_ARGS) + '):\n    return 0')
        parent = {'candidate': {'description': 'Select zero.', 'code': c.code},
                  'fitness': 'SECRET_REWARD', 'scores': ['SECRET_INSTANCE_LABEL']}
        for arm in ('B0', 'B1', 'B2', 'P'):
            initial = build_prompt(arm, 'I1', [], self.members)
            self.assertNotIn('H MEMBER', initial)
            prompt = build_prompt(arm, 'M1', [parent], self.members)
            self.assertNotIn('SECRET_REWARD', prompt)
            self.assertNotIn('SECRET_INSTANCE_LABEL', prompt)

    def test_complementary_set_beats_selecting_top_mean_and_refuses_missing_K(self):
        rows = [{'id': 'a', 'fitness': -2., 'scores': [-1., -3.]},
                {'id': 'b', 'fitness': -2.1, 'scores': [-1.1, -3.1]},
                {'id': 'c', 'fitness': -2.2, 'scores': [-3.4, -1.]}]
        selected = complementary_survival(rows, 2)
        self.assertEqual([r['id'] for r in selected], ['a', 'c'])
        with self.assertRaises(ValueError):
            export_mock_set(self.directory / 'set.json', [], size=2,
                            training_files=['x', 'y'], audit_sha256='audit')


if __name__ == '__main__':
    unittest.main()
