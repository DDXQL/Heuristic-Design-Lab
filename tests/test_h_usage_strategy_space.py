"""Independent expected outputs/actions for the existing strategy-space API."""
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research.candidates import compile_candidate
from fjsp_usage.research.protocol import digest
from fjsp_usage.research.scheduler import construct_usage_schedule as legacy_schedule
from fjsp_usage.research_real.prompts import prompt_manifest as legacy_manifest
from fjsp_usage.usage_v2.execution import construct_usage_schedule, decode_output, UsageOutputError
from fjsp_usage.usage_v2.exports import export_prompts, preview_parents
from fjsp_usage.usage_v2.prompts import prompt_sections, prompt_manifest, CROSS, MUTATE, PROMPT_VERSION
from fjsp_usage.usage_v2.strategy_examples import strategy_candidates, toy_instance, toy_members, write_strategy_examples


class StrategySpaceTests(unittest.TestCase):
    def test_scoring_has_nonlinear_formula_and_condition_but_executes_single_member(self):
        fn = compile_candidate(strategy_candidates(10)['score-select'])
        # These are handwritten scalar probes, not sampled benchmark states.
        def decoded(p, previous, std=0.1):
            return decode_output(fn(p, .4, .2, std, .25, .125, previous), 10)
        self.assertEqual(decoded(.4, 0)['support'], (0,))
        self.assertEqual(decoded(.8, 0)['support'], (1,))
        self.assertEqual(decoded(.49, 0, 0)['support'], (0,))
        self.assertEqual(decoded(.49, 1, 0)['support'], (1,))
        self.assertEqual(decoded(.5, 0, 0)['support'], (0,))  # Exact tie.
        self.assertEqual(sum(decoded(.8, 0)['weights']), 1)

    def test_state_weight_ratios_match_independent_fractions(self):
        fn = compile_candidate(strategy_candidates()['state-weights'])
        for p, expected in ((0., (Fraction(3, 5), Fraction(2, 5))),
                (.5, (Fraction(2, 5), Fraction(3, 5))),
                (.75, (Fraction(3, 10), Fraction(7, 10)))):
            decoded = decode_output(fn(p, 1., .1, 0., 0., 0., -1), 3)
            self.assertEqual(decoded['support'], (0, 1))
            for actual, wanted in zip(decoded['weights'][:2], expected):
                self.assertAlmostEqual(actual, float(wanted), places=14)

    def test_state_mode_support_weights_and_dominant_are_separate(self):
        fn = compile_candidate(strategy_candidates()['state-support-mode'])
        first = decode_output(fn(0., 1., .2, .1, 0., 0., -1), 3)
        early = decode_output(fn(.25, .4, .2, .1, .25, .125, 2), 3)
        late = decode_output(fn(.75, .4, .2, .1, .25, .125, 0), 3)
        self.assertEqual((first['mode'], first['support'], first['dominant']), (0, (2,), 2))
        self.assertEqual((early['mode'], early['support'], early['dominant']), (1, (0, 1), 0))
        self.assertEqual((late['mode'], late['support'], late['dominant']), (1, (1, 2), 1))
        for d in (early, late):
            self.assertAlmostEqual(d['weights'][d['support'][0]], .55)
            self.assertAlmostEqual(d['weights'][d['support'][1]], .45)
        with self.assertRaises(UsageOutputError):
            decode_output(fn(.25, .4, .2, .1, .25, .125, 2), 3, allowed_modes=(0,))

    def test_complete_toy_first_actions_match_independent_matrix(self):
        expected = {'constant-select': (1, 0), 'score-select': (0, 0),
            'fixed-dual': (0, 1), 'state-weights': (0, 1), 'state-support-mode': (1, 0)}
        members = [compile_candidate(h) for h in toy_members()]
        for name, c in strategy_candidates().items():
            with self.subTest(name=name):
                trace = []
                result = construct_usage_schedule(toy_instance(), members, compile_candidate(c), trace=trace.append)
                self.assertEqual((result.schedule.operations[0].job, result.schedule.operations[0].machine), expected[name])
                self.assertEqual(len(result.schedule.operations), 3)
                self.assertEqual(result, construct_usage_schedule(toy_instance(), members, compile_candidate(c)))
                self.assertEqual([x['state']['previous_heuristic'] for x in trace], [-1, *result.selected_members[:-1]])
                expected_calls = tuple(sum(t['action_count'] for t in trace if i in t['support']) for i in range(3))
                self.assertEqual(result.member_calls, expected_calls)
                if name in ('fixed-dual', 'state-weights'):
                    self.assertAlmostEqual(trace[0]['actions'][1]['score'], float(Fraction(17, 25)))

    def test_complete_toy_reaches_weight_and_support_changes(self):
        members = [compile_candidate(h) for h in toy_members()]
        trace = []
        weighted = construct_usage_schedule(toy_instance(), members,
            compile_candidate(strategy_candidates()['state-weights']), trace=trace.append)
        self.assertEqual([d[2] for d in weighted.decisions], [(0, 1)] * 3)
        self.assertEqual(len({d[3] for d in weighted.decisions}), 3)
        changing = construct_usage_schedule(toy_instance(), members,
            compile_candidate(strategy_candidates()['state-support-mode']))
        self.assertEqual([d[0] for d in changing.decisions], [0, 1, 1])
        self.assertEqual([d[2] for d in changing.decisions], [(2,), (0, 1), (1, 2)])

    def test_scored_select_is_exactly_legacy_choice_on_same_states(self):
        c = strategy_candidates()['score-select']
        members = [compile_candidate(h) for h in toy_members()]
        # Independent scalar selector, with no tuple/argmax implementation reuse.
        def selector(p, ratio, mean, std, ready_mean, ready_std, previous):
            q0 = 1 - p
            q1 = p + 2 * (std / (1 + mean)) ** 2 + (.05 if previous == 1 else 0)
            return 1 if q1 > q0 else 0
        old = []; new = []
        left = legacy_schedule(toy_instance(), members, selector, trace=old.append)
        right = construct_usage_schedule(toy_instance(), members, compile_candidate(c), trace=new.append, allowed_modes=(0,))
        self.assertEqual(left.schedule, right.schedule)
        self.assertEqual(left.selected_members, right.selected_members)
        self.assertEqual(left.score, right.score)
        self.assertEqual([x['state'] for x in old], [x['state'] for x in new])
        self.assertEqual([x['chosen'] for x in old], [x['chosen'] for x in new])

    def test_K10_sources_never_score_unused_members(self):
        def unused(*args):
            raise AssertionError('unused fixture member executed')
        members = [compile_candidate(h) for h in toy_members()] + [unused] * 7
        for c in strategy_candidates(10).values():
            result = construct_usage_schedule(toy_instance(), members, compile_candidate(c))
            self.assertEqual(result.member_calls[3:], (0,) * 7)


class StrategyPromptTests(unittest.TestCase):
    def test_full_prompt_guidance_and_mode_only_difference(self):
        members = toy_members(); parents = preview_parents(3)
        for op in ('I1', 'CROSS', 'MUTATE'):
            selected = [] if op == 'I1' else parents if op == 'CROSS' else parents[:1]
            a = prompt_sections('A', op, selected, members)
            b = prompt_sections('B', op, selected, members)
            self.assertIn('member scores, active members, weights and mode may depend', a['task'])
            self.assertIn('linear or nonlinear local expressions', a['task'])
            self.assertIn('no formula, phase partition or program skeleton', a['task'])
            self.assertIn('score formula may contain if', a['task'])
            self.assertIn('does not select top-two', a['task'])
            self.assertEqual([key for key in a if a[key] != b[key]], [] if op == 'I1' else ['allowed_modes'])
            if op != 'I1':
                self.assertIn('member-score formulas', a['operator'])
                self.assertIn('weight', a['operator'])
            else:
                self.assertNotIn('H MEMBER', a['H_context'])
                self.assertIn('SELECT (0) ONLY', a['allowed_modes'])

    def test_prompt_fingerprint_tracks_the_edited_operators_and_old_pack_stays_old(self):
        manifest = prompt_manifest()
        self.assertEqual(manifest['version'], PROMPT_VERSION)
        self.assertEqual(manifest['sections']['cross'], digest(CROSS))
        self.assertEqual(manifest['sections']['mutate'], digest(MUTATE))
        self.assertEqual(legacy_manifest()['version'], 'V5-FJSP-selector-prompts-v5-state-bounds-20261011')

    def test_complete_exports_with_source_archive_send_no_requests(self):
        from fjsp_usage.research_real.initialization import initialization_prompt
        from fjsp_usage.usage_v2.prompts import build_prompt, NOVELTY
        with tempfile.TemporaryDirectory() as tmp, patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            exported = export_prompts(Path(tmp) / 'prompts', toy_members(), 262144)
            self.assertEqual([row['changed_sections'] for row in exported['comparison']], [[], ['allowed_modes'], ['allowed_modes']])
            self.assertEqual((Path(tmp) / 'prompts/A.I1.txt').read_text(), (Path(tmp) / 'prompts/B.I1.txt').read_text())
            parent = {'candidate': asdict(strategy_candidates()['score-select']),
                'fitness': 'FORBIDDEN_PARENT_FITNESS_METADATA'}
            archived = initialization_prompt(build_prompt('INIT', 'I1', [], toy_members()), [parent], 1,
                instruction=NOVELTY, interface_version=parent['candidate']['interface_version'])
            self.assertIn('Archive entries included: 1', archived)
            self.assertIn(parent['candidate']['code'], archived)
            self.assertNotIn('H MEMBER', archived)
            self.assertNotIn('FORBIDDEN_PARENT_FITNESS_METADATA', archived)

    def test_offline_examples_have_explicit_provenance_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp, patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            directory = Path(tmp) / 'examples'
            report = write_strategy_examples(directory)
            self.assertEqual(report['complete_feasible_schedules'], 5)
            self.assertEqual(report['deterministic_rechecks'], 5)
            self.assertEqual(report['model_requests'], 0)
            self.assertEqual(report['benchmark_files_opened'], [])
            self.assertIn('Handwritten', report['notice'])
            with self.assertRaises(FileExistsError):
                write_strategy_examples(directory)

    def test_offline_bundle_rejects_other_worktree_and_runs_paths(self):
        from experiments.tier2.usage_v2.offline_strategy_space import local_output, ROOT
        for path in (ROOT / 'runs/new-space', ROOT.parent / 'other-worktree-output', ROOT / 'code/output'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                local_output(path)


if __name__ == '__main__':
    unittest.main()
