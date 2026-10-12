"""V5 information boundaries, local diagnostics and no-API preparation."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research.evolution import Search
from fjsp_usage.research.prompts import build_prompt as legacy_prompt
from fjsp_usage.research_real.config import ExperimentConfig
from fjsp_usage.research_real.diagnostics import (member_usage, h_complementarity,
                                                training_curve, fixed_h_comparisons)
from fjsp_usage.research_real.preparation import (preview_members, preview_parents,
    draft_configs, calibrate_training, write_preparation)
from fjsp_usage.research_real.prompts import build_prompt, prompt_sections, prompt_manifest
from fjsp_usage.research_real.search import BudgetedSearch, V5BudgetedSearch
from fjsp_usage.research_real.staged_evaluation import StagedDataset, create_synthetic_dataset

ROOT = Path(__file__).resolve().parents[1]


class V5PromptTests(unittest.TestCase):
    def setUp(self):
        self.members, self.parents = preview_members(), preview_parents()

    def test_literal_bound_from_real_smoke_failure_is_explained_without_relaxing_validator(self):
        from fjsp_usage.research.candidates import H_ARGS, validate_code, CandidateError
        code = 'def priority(' + ', '.join(H_ARGS) + '):\n    return -min(processing_time, 1e90)\n'
        with self.assertRaises(CandidateError): validate_code(code,kind='h')
        self.assertEqual(validate_code(code.replace('1e90','1e9'),kind='h').kind,'h')
        for arm,kind,members in (('H','h',()),('B0','U',self.members),('P','U',self.members)):
            output = prompt_sections(arm,'I1',(),members,kind=kind)['output_and_interface']
            self.assertIn('numeric literal in source code',output)
            self.assertIn('absolute value <=1e9',output)
            self.assertIn('runtime intermediate limit',output)

    def test_H_information_identical_in_B1_B2_P_and_defines_action_inputs(self):
        sections = [prompt_sections(a, 'E1' if a == 'B1' else 'CROSS', self.parents, self.members)
                    for a in ('B1','B2','P')]
        self.assertEqual(sections[0]['task_and_H'], sections[1]['task_and_H'])
        self.assertEqual(sections[1]['task_and_H'], sections[2]['task_and_H'])
        common = sections[0]['task_and_H']
        for definition in ('processing_time:', 'remaining_work:', 'remaining_operations:',
                           'job_ready_time:', 'machine_ready_time:', 'earliest_start=', 'earliest_finish='):
            self.assertIn(definition, common)
        self.assertIn('RAW, unnormalised', common)
        self.assertIn('NOT additional U inputs', common)
        self.assertIn('HIGHER scores win', common)
        for i, member in enumerate(self.members):
            self.assertIn(f'H MEMBER {i}', common)
            self.assertIn(member.code, common)
            self.assertIn(member.description, common)

    def test_B2_and_P_differ_only_in_operator_for_both_operators(self):
        for op, pp in (('CROSS', self.parents), ('MUTATE', self.parents[:1])):
            with self.subTest(operator=op):
                b = prompt_sections('B2', op, pp, self.members)
                p = prompt_sections('P', op, pp, self.members)
                self.assertNotEqual(b.pop('operator'), p.pop('operator'))
                self.assertEqual(b, p)
        self.assertIn('AT LEAST TWO', build_prompt('P', 'CROSS', self.parents, self.members))
        mutation = build_prompt('P', 'MUTATE', self.parents[:1], self.members)
        self.assertIn('ONE MAIN MODIFICATION HYPOTHESIS', mutation)
        self.assertIn('rewrite the WHOLE function', mutation)
        self.assertNotIn('propose a local change', mutation)

    def test_initial_is_neutral_and_B0_receives_no_H_details(self):
        prompts = [build_prompt(a, 'I1', [], self.members) for a in ('B0','B1','B2','P')]
        self.assertEqual(len(set(prompts)), 1)
        for prompt in prompts + [build_prompt('B0','E1', self.parents, self.members)]:
            self.assertNotIn('H MEMBER', prompt)
            self.assertNotIn('def priority(', prompt)
            self.assertNotIn('processing_time:', prompt)
            self.assertIn('total operation count of the instance', prompt)
            self.assertNotIn('scheduled operations/N', prompt)
        with self.assertRaises(ValueError):
            build_prompt('P','I1', self.parents, self.members)

    def test_parent_evaluation_metadata_does_not_enter_prompt(self):
        changed = deepcopy(self.parents)
        for p in changed:
            p.update(fitness='SECRET_REWARD', scores=['SECRET_STATE_LABEL'], error='SECRET_ERROR')
        for arm, op in (('B0','E1'), ('B1','E1'), ('B2','CROSS'), ('P','CROSS')):
            self.assertEqual(build_prompt(arm,op,changed,self.members),
                             build_prompt(arm,op,self.parents,self.members))
        with self.assertRaises(ValueError):
            build_prompt('P','CROSS',self.parents[:1],self.members)
        with self.assertRaises(ValueError):
            build_prompt('P','MUTATE',self.parents,self.members)

    def test_legacy_engine_and_pilot_keep_legacy_pack(self):
        args = ('P','MUTATE',self.parents[:1],self.members)
        self.assertEqual(Search._build_prompt(*args), legacy_prompt(*args))
        self.assertEqual(BudgetedSearch._build_prompt(*args), legacy_prompt(*args))
        self.assertEqual(V5BudgetedSearch._build_prompt(*args), build_prompt(*args))
        self.assertNotEqual(build_prompt(*args), legacy_prompt(*args))
        self.assertEqual(prompt_manifest()['model_calls_per_candidate'], 1)


class LocalDiagnosticsTests(unittest.TestCase):
    def test_member_usage_and_bool_rejection(self):
        result = member_usage([0,1,1,0], 2)
        self.assertEqual(result['counts'], [2,2])
        self.assertEqual(result['switches'], 2)
        self.assertEqual(result['transitions'], 3)
        self.assertAlmostEqual(result['switch_rate'], 2/3)
        self.assertEqual(member_usage([1],2)['switch_rate'], 0)
        with self.assertRaises(ValueError): member_usage([False],2)

    def test_H_envelope_and_zero_contribution_retained(self):
        rows = [{'id':'a','scores':[-1.,-3.]}, {'id':'b','scores':[-3.,-1.]},
                {'id':'c','scores':[-2.,-2.]}]
        d = h_complementarity(rows, ['x','y'])
        self.assertEqual(d['envelope_gain_over_best_fixed_member'], 1.)
        self.assertEqual([r['leave_one_out_mean_gain'] for r in d['members']], [.5,.5,0.])
        self.assertEqual([r['strictly_best_instances'] for r in d['members']], [1,1,0])
        with self.assertRaises(ValueError): h_complementarity(rows,['x'])

    def test_curve_counts_failed_and_duplicate_slots_and_parent_improvement(self):
        state = {'attempts': [
            {'id':'c1','status':'valid','parents':['initial']},
            {'id':'dup','status':'duplicate','parents':['initial']},
            {'id':'bad','status':'invalid','parents':['initial']},
            {'id':'c2','status':'valid','parents':['c1']}],
            'evaluations': {'c1':{'result':{'valid':True,'fitness':-1.5}},
                            'c2':{'result':{'valid':True,'fitness':-1.7}}}}
        d = training_curve(state, [{'id':'initial','fitness':-2.}])
        self.assertEqual([p['best_train_fitness'] for p in d['curve']], [-2.,-1.5,-1.5,-1.5,-1.5])
        self.assertEqual(d['valid_children_with_parent_scores'], 2)
        self.assertEqual(d['children_strictly_better_than_all_parents'], 1)
        state['evaluations'].pop('c2')
        with self.assertRaises(ValueError): training_curve(state, [{'id':'initial','fitness':-2.}])

    def test_fixed_reference_comparison_keeps_failed_seeds(self):
        entries = [{'seed':1,'arm':'P','test_result':{'valid':True,'fitness':-1.}},
                   {'seed':2,'arm':'P','test_result':None}]
        d = fixed_h_comparisons(entries,(1,2),{'valid':True,'fitness':-2.},('P',))['P']
        self.assertEqual(d['actual_comparisons'],1)
        self.assertEqual(d['mean_difference'],1.)
        self.assertEqual(d['excluded_seeds'],[2])


class OfflinePreparationTests(unittest.TestCase):
    def test_draft_caps_equal_phase_sum_and_dispatch_disabled(self):
        drafts = draft_configs()
        self.assertEqual(drafts['paired-pilot'].total_request_cap,150)
        self.assertEqual(drafts['formal'].total_request_cap,12210)
        for c in drafts.values():
            decoded = ExperimentConfig.from_dict(c.payload())
            self.assertEqual(decoded.total_request_cap,sum(decoded.phase_caps().values()))
            self.assertEqual(len({v for k,v in decoded.phase_caps().items()
                                  if k.rsplit('/',1)[-1] in ('B0','B1','B2','P')}),1)
            with self.assertRaises(ValueError): decoded.check_dispatch()

    def test_export_opens_no_instances_and_constructs_no_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = create_synthetic_dataset(Path(tmp)/'fixtures',count=1)
            dataset = StagedDataset(manifest, project_root=manifest.parent, mode='synthetic')
            path = Path(tmp)/'prepare'
            with patch('fjsp_usage.research_real.workflow.JsonCandidateTransport', side_effect=AssertionError('no API')):
                plan = write_preparation(path,root=ROOT,dataset=dataset)
            self.assertEqual(dataset.opened,[])
            self.assertEqual(plan['model_requests'],0)
            self.assertEqual(len(plan['prompt_previews']),18)
            self.assertTrue(plan['preview_fits_configured_bytes'])
            self.assertFalse(json.loads((path/'config.formal.draft.json').read_text())['real_requests_authorized'])
            with self.assertRaises(ValueError): write_preparation(path,root=ROOT,dataset=dataset)

    def test_calibration_train_only_with_single_h_equivalence(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = create_synthetic_dataset(Path(tmp)/'fixtures',count=1)
            dataset = StagedDataset(manifest, project_root=manifest.parent, mode='synthetic')
            with patch('fjsp_usage.research_real.workflow.JsonCandidateTransport', side_effect=AssertionError('no API')):
                report = calibrate_training(dataset,timeout=3)
            self.assertEqual(dataset.opened,[('train','train_0.fjsp')])
            self.assertTrue(report['all_batches_valid'])
            self.assertTrue(all(r['constant_U_matches_single_h'] for r in report['constant_equivalence']))
            self.assertEqual(report['holdout_instances_opened'],0)
            for batch in report['selector_results'].values():
                usage = batch['instances'][0]['member_usage']
                self.assertEqual(sum(usage['counts']),3)
                self.assertEqual(usage['steps'],3)


if __name__ == '__main__':
    unittest.main()
