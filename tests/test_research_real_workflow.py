from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation
from fjsp_usage.research.candidates import validate_code, H_ARGS, U_ARGS
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.assets import seal, load_h, check_result
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig
from fjsp_usage.research_real.fixtures import fixture_server, fixture_response
from fjsp_usage.research_real.staged_evaluation import StagedDataset, create_synthetic_dataset
from fjsp_usage.research_real.workflow import Workflow, ARMS
from fjsp_usage.research_real.report import write_report, statistics
from fjsp_usage.research_real.runtime import evaluate

ROOT = Path(__file__).resolve().parents[1]


def reseal(asset):
    return seal({k:v for k,v in asset.items() if k != 'artifact_sha256'})


def setup(directory, endpoint, seeds=(1,2)):
    manifest = create_synthetic_dataset(Path(directory)/'fixtures', count=1)
    c = ExperimentConfig(provider=ProviderConfig(endpoint, 'HANDWRITTEN-HTTP-TEST'), H_size=2,
        H_initialization_cap=3, H_generations=1, H_attempts=10,
        population_size=3, cross_parents=2, initialization_cap=3,
        attempts_per_generation=10, generations=1, seeds=seeds, total_request_cap=100)
    dataset = StagedDataset(manifest, project_root=manifest.parent, mode='synthetic')
    return Workflow(Path(directory)/'run', config=c, dataset=dataset, project_root=ROOT)


class RealWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.server = fixture_server()
        cls.endpoint, cls.traffic = cls.server.__enter__()
        cls.flow = setup(cls.temp.name, cls.endpoint)
        cls.flow.generate_h()
        cls.flow.freeze_h()
        cls.flow.search_all()
        cls.flow.select()
        cls.flow.freeze()
        cls.flow.test()
        cls.report = write_report(cls.flow)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None,None,None)
        cls.temp.cleanup()

    def test_paired_repeat_assets_operator_quotas_and_receipts(self):
        flow = self.flow
        self.assertTrue(self.report['all_planned_succeeded'])
        self.assertEqual(len(self.traffic['requests']), 98)
        self.assertEqual(flow.ledger.summary()['request_slots'], 98)
        H, members = flow.h_asset()
        self.assertEqual(len(members), 2)
        for seed in flow.config.seeds:
            initial, rows = flow.population(f'r{seed}/Shared_initial.json', 'Shared_initial', H['artifact_sha256'])
            self.assertEqual(len(rows), 3)
            initial_requests = json.loads((flow.directory/f'r{seed}/INIT/budgeted_initial_requests.json').read_text())
            self.assertEqual(len(initial_requests['requests']), 3)
            for request in initial_requests['requests'].values():
                self.assertNotIn('def priority', request['prompt'])
                self.assertNotIn('highest finite score', request['prompt'])
            for arm in ARMS:
                population, rows = flow.population(f'r{seed}/{arm}/Final_population.json', 'Final_population', H['artifact_sha256'])
                self.assertEqual(population['shared_initial_hash'], initial['artifact_sha256'])
                state = json.loads((flow.directory/f'r{seed}/{arm}/checkpoint.json').read_text())
                counts = Counter(r['operator'] for r in state['attempts'])
                self.assertEqual(counts, Counter(dict.fromkeys(('E1','E2','M1','M2','M3'), 2))
                    if arm in ('B0','B1') else Counter({'CROSS':5,'MUTATE':5}))
                allowed_parents = {r['id'] for r in initial['population']}
                for attempt in state['attempts']:
                    self.assertTrue(set(attempt['parents']) <= allowed_parents)
                    self.assertEqual(len(attempt['parents']), 2 if attempt['operator'] in ('CROSS','E1','E2') else 1)
                for row in rows:
                    self.assertTrue(row['training_result']['valid'])
                    self.assertTrue(row['receipt']['send_confirmed'])

    def test_completed_resume_never_sends_or_evaluates_and_test_has_no_client(self):
        flow = Workflow(self.flow.directory, config=self.flow.config, dataset=self.flow.dataset, project_root=ROOT)
        before = len(self.traffic['requests'])
        with (patch('fjsp_usage.research_real.workflow.JsonCandidateTransport', side_effect=AssertionError('no provider')),
              patch('fjsp_usage.research_real.staged_evaluation.evaluate', side_effect=AssertionError('no reevaluation'))):
            flow.generate_h()
            flow.freeze_h()
            flow.search_all()
            flow.select()
            flow.freeze()
            flow.test()
            write_report(flow)
        self.assertEqual(len(self.traffic['requests']), before)
        self.assertIsNone(flow._client)

    def test_h_rejects_mock_missing_member_bool_id_wrong_key_unreviewed(self):
        H, _ = self.flow.h_asset()
        def check(asset, mode='synthetic'):
            load_h(asset, mode=mode, context=self.flow.context, size=2, names=self.flow.dataset.names['train'])
        mutations = []
        missing = deepcopy(H); missing['members'].pop(); mutations.append(missing)
        bad_id = deepcopy(H); bad_id['members'][0]['member_id'] = True; mutations.append(bad_id)
        gap = deepcopy(H); gap['members'][1]['member_id'] = 3; mutations.append(gap)
        key = deepcopy(H); key['members'][0]['candidate']['key'] = 'bad'; mutations.append(key)
        unreviewed = deepcopy(H); unreviewed['members'][0].pop('review'); mutations.append(unreviewed)
        duplicate = deepcopy(H); duplicate['members'][1] = {**duplicate['members'][0], 'member_id':1}; mutations.append(duplicate)
        samples = deepcopy(H); samples['members'][0]['review']['samples'][0]['score'] += 1; mutations.append(samples)
        for asset in mutations:
            with self.subTest(asset=asset.get('kind')), self.assertRaises(ValueError):
                check(reseal(asset))
        with self.assertRaises(ValueError):
            check(H, 'real')
        promoted = deepcopy(H); promoted['mode'] = 'real'
        with self.assertRaises(ValueError):
            check(reseal(promoted), 'real')
        damaged = deepcopy(H); damaged['member_count'] = 99
        with self.assertRaises(ValueError):
            check(damaged)

    def test_only_final_population_validation_and_no_unfrozen_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow = setup(tmp, 'http://127.0.0.1:1/c', seeds=(1,))
            self.assertEqual(flow.dataset.opened, [])
            for split in ('validation', 'test'):
                with self.assertRaises(ValueError):
                    flow.dataset.load(split)
            self.assertEqual(flow.dataset.opened, [])
            with self.assertRaises(FileNotFoundError):
                flow.test()
            gate = seal({'kind':'Search_complete', 'mode':'synthetic', 'context':flow.context,
                'dataset_hash':flow.dataset.key, 'population_hashes':['final'], 'reference_H_hash':'h'})
            with self.assertRaises(ValueError):
                flow.dataset.load('validation', context=flow.context, gate=gate, population_hash='archive-child')
            self.assertEqual(flow.dataset.opened, [])
            self.assertEqual(len(flow.dataset.load('validation', context=flow.context, gate=gate, population_hash='final')), 1)

    def test_final_population_cannot_replace_train_evidence_or_source_id(self):
        flow = self.flow
        path = flow.directory/'r1/B0/Final_population.json'
        original = path.read_bytes()
        H, _ = flow.h_asset()
        try:
            forged = json.loads(original)
            row = forged['population'][0]
            row['id'] += '-forged'
            atomic_json(path, reseal(forged))
            with self.assertRaises(ValueError):
                flow.population('r1/B0/Final_population.json', 'Final_population', H['artifact_sha256'])
            forged = json.loads(original)
            row = forged['population'][0]
            row['training_result']['instances'][0]['makespan'] += 1
            record = row['training_result']['instances'][0]
            record['score'] = -record['makespan']/record['lower_bound']
            row['training_result']['fitness'] = record['score']
            row['fitness'], row['scores'] = record['score'], [record['score']]
            atomic_json(path, reseal(forged))
            with self.assertRaises(ValueError):
                flow.population('r1/B0/Final_population.json', 'Final_population', H['artifact_sha256'])
        finally:
            path.write_bytes(original)

    def test_validation_selects_full_population_with_stable_tie_and_fixed_h(self):
        selection = self.flow.read('Selection_complete.json', 'Selection_complete')
        for entry in selection['entries']:
            star = self.flow.read(f'r{entry["seed"]}/{entry["arm"]}/U_star.json', 'U_star')
            valid = [r for r in star['validation_results'] if r['result']['valid']]
            expected = min(valid, key=lambda r: (-r['result']['fitness'], r['id']))
            self.assertEqual(star['row']['id'], expected['id'])
            self.assertEqual(len(star['validation_results']), 3)
        valid_h = [r for r in selection['fixed_h_validation'] if r['result']['valid']]
        self.assertEqual(selection['fixed_h'], min(valid_h, key=lambda r: (-r['result']['fitness'], r['member_id'])))

    def test_freeze_rejects_asset_code_and_data_change_even_with_cached_results(self):
        flow = self.flow
        for path in (flow.directory/'H_frozen.json', flow.directory/'r1/B0/U_star.json'):
            original = path.read_bytes()
            try:
                damaged = json.loads(original)
                if 'members' in damaged:
                    damaged['members'][0]['candidate']['code'] += '\n# change'
                else:
                    damaged['row']['candidate']['code'] += '\n# change'
                atomic_json(path, reseal(damaged))
                with self.assertRaises(ValueError): flow.test()
            finally:
                path.write_bytes(original)
        for split in ('train','validation','test'):
            path = flow.dataset.paths[split][0]
            original = path.read_bytes()
            try:
                path.write_bytes(original+b'\n# altered input\n')
                with self.assertRaises(ValueError): flow.test()
            finally:
                path.write_bytes(original)
        with patch('fjsp_usage.research_real.workflow.fingerprint', return_value={'changed':True}):
            with self.assertRaises(ValueError): flow.test()

    def test_all_invalid_validation_is_failure_no_fallback_or_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'run'
            shutil.copytree(self.flow.directory, target)
            for name in ('Selection_complete.json','Experiment_frozen.json','Test_complete.json'):
                (target/name).unlink()
            flow = Workflow(target, config=self.flow.config, dataset=self.flow.dataset, project_root=ROOT)
            invalid = {'valid':False, 'total_instances':1, 'instances':[], 'fitness':None, 'error_type':'TestFixtureFailure'}
            with patch.object(flow, 'stage_eval', return_value=invalid), patch.object(flow, 'client', side_effect=AssertionError('no model')):
                selection = flow.select()
                self.assertTrue(all(r['selection_status'] == 'selection_failed' for r in selection['entries']))
                self.assertIsNone(selection['fixed_h'])
                flow.freeze()
                tested = flow.test()
                self.assertTrue(all(r['test_result'] is None for r in tested['entries']))
                report = write_report(flow)
                self.assertFalse(report['all_planned_succeeded'])
                self.assertTrue(all(r['mean'] is None for r in report['statistics']['groups'].values()))

    def test_report_retains_failures_pair_counts_null_cost_and_separate_timing(self):
        entries = deepcopy(self.report['entries'])
        entries[0]['test_result'] = None
        entries[1]['test_result'] = {'valid':False, 'fitness':None, 'total_instances':1, 'instances':[]}
        stats = statistics(entries, self.flow.config.seeds)
        self.assertEqual(stats['paired_differences']['B0-B1']['actual_pairs'], 1)
        self.assertEqual(stats['groups']['B0']['failed_seeds'], [1])
        self.assertEqual(stats['groups']['B1']['failure_rate'], .5)
        self.assertEqual(len(entries), 8)
        self.assertTrue(all(p['cost_estimate'] is None for p in self.report['budget']['phases'].values()))
        self.assertGreater(self.report['timing']['test_single_solve_seconds_sum'], 0)
        self.assertGreater(self.report['timing']['test_deterministic_recheck_seconds_sum'], 0)
        for entry in self.report['entries']:
            self.assertTrue(all(r['feasible'] for r in entry['test_result']['instances']))


class FailureWorkflowTests(unittest.TestCase):
    def test_initialization_failure_retains_all_repeats_no_arm_requests_or_refill(self):
        def duplicate_u(payload, index):
            result = fixture_response(payload, index)
            if payload['kind'] == 'U':
                result['text'] = '{Constant duplicate fixture.}\n```python\ndef select_heuristic(' + ', '.join(U_ARGS) + '):\n    return 0\n```'
            return result
        with fixture_server(responder=duplicate_u) as (endpoint, traffic), tempfile.TemporaryDirectory() as tmp:
            flow = setup(tmp, endpoint)
            flow.generate_h(); flow.freeze_h()
            gate = flow.search_all()
            self.assertEqual(len(gate['entries']), 8)
            self.assertTrue(all(r['status'] == 'initialization_failed' for r in gate['entries']))
            self.assertEqual(len(traffic['requests']), 18)
            self.assertTrue(all('/B0/' not in p['request_id'] and '/B1/' not in p['request_id']
                                and '/B2/' not in p['request_id'] and '/P/' not in p['request_id'] for p in traffic['requests']))
            flow.search_all()
            flow.select(); flow.freeze(); flow.test()
            report = write_report(flow)
            self.assertEqual(len(traffic['requests']), 18)
            self.assertFalse(report['all_planned_succeeded'])
            self.assertTrue(all(g['valid_repeats'] == 0 for g in report['statistics']['groups'].values()))

    def test_failed_suffix_and_illegal_values_invalidate_whole_batch_and_loop_is_killed(self):
        first = FJSPInstance('first', 1, ((Operation(((0,2),)),),))
        second = FJSPInstance('second', 1, ((Operation(((0,3),)),),))
        h = validate_code('def priority(' + ', '.join(H_ARGS) + '):\n    return -processing_time if processing_time < 3 else 1/0', kind='h')
        result = evaluate(h, (), (first,second), ('first','second'))
        self.assertFalse(result['valid']); self.assertIsNone(result['fitness'])
        self.assertEqual(len(result['instances']), 1)
        check_result(result, ('first','second'))
        good_h = validate_code('def priority(' + ', '.join(H_ARGS) + '):\n    return -processing_time', kind='h')
        for value in ('True','0.0','-1','2','1/0'):
            candidate = validate_code('def select_heuristic(' + ', '.join(U_ARGS) + '):\n    return '+value)
            result = evaluate(candidate, (good_h,good_h), (first,), ('first',))
            self.assertFalse(result['valid']); self.assertIsNone(result['fitness'])
        candidate = validate_code('def select_heuristic(' + ', '.join(U_ARGS) + '):\n    while True:\n        pass\n    return 0')
        started = time.monotonic()
        result = evaluate(candidate, (good_h,good_h), (first,), ('first',), timeout=.4)
        self.assertEqual(result['error_type'], 'Timeout')
        self.assertLess(time.monotonic()-started, 3)


if __name__ == '__main__':
    unittest.main()
