"""Regression for observed shared-init repeats; no provider or real datasets."""

from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from fjsp_usage.research.candidates import U_ARGS, validate_code
from fjsp_usage.research.evolution import Search
from fjsp_usage.research.protocol import SearchConfig
from fjsp_usage.research_real.initialization import initialization_prompt, selector_signature
from fjsp_usage.research_real.preparation import preview_members
from fjsp_usage.research_real.prompts import build_prompt, prompt_manifest
from fjsp_usage.research_real.search import V5BudgetedSearch


def code(body):
    return 'def select_heuristic(' + ', '.join(U_ARGS) + '):\n    ' + body + '\n'


def row(body):
    return {'id': 'source-id', 'candidate': asdict(validate_code(code(body),
        description='SECRET_DESCRIPTION')), 'fitness': 'SECRET_FITNESS',
        'scores': ['SECRET_SCORE'], 'error': 'SECRET_ERROR'}


class RecordedResponses:
    identity = 'handwritten-novelty-fixture'

    def __init__(self, bodies):
        self.bodies, self.calls = bodies, []

    def __call__(self, key, prompt, *, kind):
        self.calls.append((key, prompt))
        return {'text': '{Independent selector.}\n```python\n' +
                code(self.bodies[len(self.calls)-1]) + '```', 'usage': None}


class PolicyHarness(V5BudgetedSearch):
    """Use real V5 hooks with base offline journals; budget covered separately."""
    _evaluate_once = Search._evaluate_once

    def __init__(self, directory, *, transport, evaluator, arm='INIT', initial=None):
        Search.__init__(self, directory, arm=arm,
            config=SearchConfig(population_size=2, cross_parents=2, generations=1,
                                initialization_cap=3),
            members=preview_members(), transport=transport, evaluator=evaluator,
            context=prompt_manifest(), initial=initial)


class InitializationNoveltyTests(unittest.TestCase):
    def test_observed_constant_wrappers_consume_slot_but_not_evaluation(self):
        transport = RecordedResponses(['return 0', 'return int(0)', 'return 1'])
        evaluations = []
        def evaluate(candidate):
            evaluations.append(candidate.key)
            return {'valid': True, 'fitness': -1., 'total_instances': 1,
                    'instances': [{'score': -1.}]}
        with tempfile.TemporaryDirectory() as tmp:
            search = PolicyHarness(tmp, transport=transport, evaluator=evaluate)
            self.assertTrue(search.initialize())
            self.assertEqual(len(transport.calls), 3)
            self.assertEqual(len(evaluations), 2)
            self.assertEqual([a['status'] for a in search.state['attempts']],
                             ['valid', 'duplicate', 'valid'])
            self.assertEqual(search.state['attempts'][1]['duplicate_of'], 'INIT/init/000000')
            self.assertEqual(search.state['attempts'][1]['category'], 'narrow_equivalence_duplicate')
            self.assertTrue(all(not a['parents'] for a in search.state['attempts']))
            self.assertNotIn('ARCHIVED SELECTOR ', transport.calls[0][1])
            self.assertIn('return 0', transport.calls[1][1])
            resumed = PolicyHarness(tmp, transport=transport, evaluator=evaluate)
            self.assertTrue(resumed.initialize())
            self.assertEqual(len(transport.calls), 3)

    def test_same_scores_do_not_collapse_distinct_state_policies(self):
        a = 'return 0 if progress < 0.5 else 1'
        b = 'return 0 if candidate_pair_ratio < 0.5 else 1'
        self.assertNotEqual(selector_signature(code(a)), selector_signature(code(b)))
        self.assertNotEqual(selector_signature(code('return 0')), selector_signature(code('return 1')))
        self.assertNotEqual(selector_signature(code('return 0')),
                            selector_signature(code('x = 0\n    return int(x)')))
        transport = RecordedResponses([a, b])
        def evaluate(candidate):
            return {'valid': True, 'fitness': -1., 'total_instances': 1,
                    'instances': [{'score': -1.}]}
        with tempfile.TemporaryDirectory() as tmp:
            search = PolicyHarness(tmp, transport=transport, evaluator=evaluate)
            self.assertTrue(search.initialize())
            self.assertEqual(len(search.state['population']), 2)
            self.assertEqual(len(transport.calls), 2)

    def test_existing_AST_dedup_and_candidate_keys_are_preserved(self):
        a, b = code('return 0'), code('return int(0)')
        self.assertNotEqual(validate_code(a).key, validate_code(b).key)
        self.assertEqual(selector_signature(a), selector_signature(b))
        self.assertEqual(selector_signature(a), selector_signature(a + '# comment\n'))
        self.assertEqual(selector_signature(code('return -2')), selector_signature(code('return int(-2)')))
        self.assertNotEqual(selector_signature(code('return True')), selector_signature(code('return 1')))

    def test_archive_is_code_only_order_independent_and_unranked(self):
        members = preview_members()
        base = build_prompt('B0', 'I1', [], members)
        rows = [row('return 0'), row('return 1')]
        prompt = initialization_prompt(base, rows, 2)
        self.assertEqual(prompt, initialization_prompt(base, rows[::-1], 2))
        for secret in ('SECRET_DESCRIPTION', 'SECRET_FITNESS', 'SECRET_SCORE', 'SECRET_ERROR',
                       'H MEMBER', 'def priority(', 'PARENT 0'):
            self.assertNotIn(secret, prompt)
        self.assertIn('not parents', prompt)
        self.assertIn('constant selector remains legal', prompt)
        self.assertNotEqual(prompt, initialization_prompt(base, rows, 3))

    def test_archive_byte_cap_does_not_truncate_functions(self):
        prompt = initialization_prompt('base', [row('return 0')], 1, max_archive_bytes=1)
        self.assertNotIn('ARCHIVED SELECTOR ', prompt)
        self.assertIn('omitted by byte limit: 1', prompt)
        full = initialization_prompt('base', [row('return 0')], 1)
        self.assertEqual(full.count('```'), 2)

    def test_saved_inflight_prompt_survives_resume(self):
        transport = RecordedResponses(['return 0'])
        with tempfile.TemporaryDirectory() as tmp:
            search = PolicyHarness(tmp, transport=transport, evaluator=lambda c: None)
            search._prepare(initial=True)
            saved = search.state['inflight'].copy()
            resumed = PolicyHarness(tmp, transport=transport, evaluator=lambda c: None)
            resumed._prepare(initial=True)
            self.assertEqual(resumed.state['inflight'], saved)
            self.assertEqual(transport.calls, [])

    def test_policy_is_only_shared_U_initialization(self):
        search = object.__new__(V5BudgetedSearch)
        search.state = {'seen': {}, 'population': [row('return 0')],
                        'inflight': {'initial': True}}
        candidate = validate_code(code('return int(0)'))
        for arm, kind in (('H', 'h'), ('B0', 'U'), ('B1', 'U'), ('B2', 'U'), ('P', 'U')):
            search.arm, search.kind = arm, kind
            self.assertEqual(search._initial_prompt('base', 0), 'base')
            self.assertIsNone(search._duplicate_of(candidate))
        search.arm, search.kind = 'INIT', 'U'
        self.assertEqual(search._duplicate_of(candidate), 'source-id')
        self.assertNotEqual(search._initial_prompt('base', 0), 'base')
        search.state['inflight']['initial'] = False
        self.assertIsNone(search._duplicate_of(candidate))


if __name__ == '__main__':
    unittest.main()
