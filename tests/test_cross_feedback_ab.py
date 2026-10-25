"""Synthetic dictionaries, prompt rendering and pure budgets; zero solves/API."""
from copy import deepcopy
from dataclasses import asdict
from statistics import fmean
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fjsp_usage.cross_feedback_ab import (validate_parent, render, feedback, plan,
    reserve_cost, fee_gate, EvidenceError, FeeStop)
from fjsp_usage.research.candidates import validate_code, U_ARGS
from fjsp_usage.usage_v2 import VERSION
from tools import b1_usage_prompts


def parent(index, makespan=2):
    vector = tuple(1. if j == index else 0. for j in range(10))
    code = 'def use_heuristics('+', '.join(U_ARGS)+'):\n    return (0, '+repr(vector)+')\n'
    c = validate_code(code, description='Synthetic test only', interface_version=VERSION, member_count=10)
    row = {'id': f'toy_{index}', 'candidate': asdict(c), 'fitness': -float(makespan)}
    r = {'valid': True, 'total_instances': 1, 'fitness': row['fitness'],
         'instances': [{'file': 'SYNTHETIC', 'lower_bound': 1., 'makespan': makespan,
                        'score': -float(makespan), 'feasible': True}]}
    return row, r


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.members = [SimpleNamespace(description='Frozen H placeholder', code='def priority():\n    return 1.0\n') for _ in range(10)]
        self.context = {'H_order': [str(i) for i in range(10)], 'seed': 501, 'science': 'synthetic test only'}
        self.instances = [{'file': 'SYNTHETIC', 'LB': 1.}]
        for target in ['socket.socket.connect', 'fjsp_usage.research_real.runtime.evaluate',
                       'llm4ad.task.optimization.fjsp_set.instances.load_instance',
                       'fjsp_usage.research_real.real_transport.JsonCandidateTransport.dispatch']:
            p = patch(target, side_effect=AssertionError('NO API OR SOLVE IN OFFLINE TEST'))
            p.start(); self.addCleanup(p.stop)

    def test_A_is_current_template_byte_for_byte(self):
        parents = [parent(0)[0], parent(1, 3)[0]]
        self.assertEqual(render('A', parents, self.members), b1_usage_prompts.build_prompt('B', 'CROSS', parents, self.members))

    def test_B_is_only_inserted_fact_block_and_order_unchanged(self):
        parents = [parent(0)[0], parent(1, 3)[0]]
        before = deepcopy(parents)
        a = render('A', parents, self.members)
        block = feedback(-2., -3.)
        b = render('B', parents, self.members, [-2., -3.])
        self.assertEqual(b.replace(block, '', 1), a)
        self.assertEqual(parents, before)
        self.assertLess(b.index('PARENT 0\n'), b.index('PARENT 1\n'))
        self.assertLess(b.index('COMPLETE TRAIN21'), b.index('Compare how the supplied parents'))
        self.assertNotIn('COMPLETE TRAIN21', a)

    def test_delta_direction_negative_and_equal(self):
        self.assertIn('= -1.0.', feedback(-2., -3.))
        self.assertIn('= 1.0.', feedback(-3., -2.))
        self.assertIn('= 0.0.', feedback(-2., -2.))
        for bad in [float('inf'), float('nan'), True, None]:
            with self.assertRaises(EvidenceError): feedback(bad, -1.)

    def test_no_fallback_no_init_mutate_no_C(self):
        parents = [parent(0)[0], parent(1)[0]]
        with self.assertRaises(EvidenceError): render('B', parents, self.members)
        with self.assertRaises(EvidenceError): render('B', parents, self.members, [-1., -1.])
        for op in ['I1', 'MUTATE']:
            with self.assertRaises(EvidenceError): render('B', parents, self.members, [-2., -2.], operator=op)
        with self.assertRaises(EvidenceError): render('C', parents, self.members)

    def test_original_init_mutation_unchanged_without_feedback(self):
        p = parent(0)[0]
        for op, parents in [('I1', []), ('MUTATE', [p])]:
            self.assertNotIn('COMPLETE TRAIN21', b1_usage_prompts.build_prompt('B', op, parents, self.members))

    def test_complete_parent_validation(self):
        p, r = parent(0)
        self.assertEqual(validate_parent(p, r, self.instances, self.context, self.context).key, p['candidate']['key'])

    def test_incomplete_invalid_context_LB_key_and_fitness_fail(self):
        p, r = parent(0)
        bads = []
        for field, value in [('valid', False), ('fitness', -1.), ('instances', []), ('total_instances', 21)]:
            bad = deepcopy(r); bad[field] = value; bads.append((p, bad, self.context))
        bad = deepcopy(r); bad['instances'][0]['lower_bound'] = 2.; bads.append((p, bad, self.context))
        bad = deepcopy(p); bad['candidate']['key'] = 'wrong'; bads.append((bad, r, self.context))
        bads.append((p, r, {**self.context, 'seed': 999}))
        for row, result, ctx in bads:
            with self.assertRaises(EvidenceError): validate_parent(row, result, self.instances, ctx, self.context)

    def test_plan_five_pairs_three_repeats_and_no_score_input(self):
        p = plan(['p3', 'p1', 'p5', 'p2', 'p4'])
        self.assertEqual(p, plan(['p1', 'p2', 'p3', 'p4', 'p5']))
        self.assertEqual(len(p['pairs']), 5); self.assertEqual(len(p['tasks']), 30)
        self.assertEqual(len({frozenset(x['parents']) for x in p['pairs']}), 5)
        for a, b in zip(p['tasks'][::2], p['tasks'][1::2]):
            self.assertEqual((a['pair_id'], a['repeat_id'], a['parents']), (b['pair_id'], b['repeat_id'], b['parents']))
            self.assertEqual({a['condition'], b['condition']}, {'A', 'B'})
        self.assertEqual(sorted(x['dispatch_position'] for x in p['tasks']), list(range(1, 31)))

    def test_small_pool_shrinks_no_other_source(self):
        self.assertEqual(len(plan(['a', 'b', 'c'])['pairs']), 3)
        self.assertEqual(len(plan(['a'])['tasks']), 0)
        with self.assertRaises(EvidenceError): plan(['a', 'a'])

    def test_fee_gate_refuses_engineering_envelope(self):
        with self.assertRaises(FeeStop): fee_gate({'certified_provider_upper_bound': False, 'points': 410000})
        with self.assertRaisesRegex(FeeStop, 'CNY'):
            fee_gate({'live_model_and_tariff_verified': True})

    def test_unknown_fees_keep_hold_caps_and_no_replay(self):
        l = {'attempts': {}}
        l = reserve_cost(l, 'a1', 'a', 10.)
        self.assertIsNone(l['attempts']['a1']['actual_CNY'])
        l = reserve_cost(l, 'b1', 'b', 10.)
        with self.assertRaises(FeeStop): reserve_cost(l, 'c1', 'c', .01)
        with self.assertRaises(FeeStop): reserve_cost(l, 'a1', 'a', 1.)
        l = {'attempts': {}}
        l = reserve_cost(l, 'a1', 'a', 1.)
        l = reserve_cost(l, 'a2', 'a', 1.)
        with self.assertRaises(FeeStop): reserve_cost(l, 'a3', 'a', 1.)

    def test_corrupt_monetary_ledger_fails(self):
        l = {'attempts': {'a': {'task_id': 'x', 'reserved_CNY': 1., 'actual_CNY': -1.}}}
        with self.assertRaises(FeeStop): reserve_cost(l, 'b', 'b', 1.)


if __name__ == '__main__': unittest.main()
