"""Mathematics, V1 regression, dynamic interface and fail-closed V2 lifecycle."""
from dataclasses import asdict
import math
import multiprocessing as mp
from pathlib import Path
import random
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.fusion_v2.execution import (
    construct_fusion_schedule, decode_fusion, fixed_policy, fuse_scores, v1_adapter,
)
from fjsp_usage.usage_v2.execution import (
    construct_usage_schedule, decode_output, combine_scores, UsageOutputError, NormalizationError,
)
from fjsp_usage.research.protocol import digest
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation
from tools.b1_timeout_boundary import classify_boundary, collect_with_lifecycle
from tools.fusion_v2_experiment import MODULES, ROOT, source_witness, specs, worker


def toy():
    return FJSPInstance('fusion-toy', 2, (
        (Operation(((0, 2), (1, 3))), Operation(((0, 5), (1, 6)))),
        (Operation(((0, 4),)),)))


class FusionTests(unittest.TestCase):
    def test_math_and_independent_full_column_normalization(self):
        columns = {0: (10, 6, 0), 1: (0, 80, 100)}
        expected = {'WEIGHTED_SUM': (.5, .7, .5), 'MAX': (1., .8, 1.), 'MIN': (0., .6, 0.)}
        for op, target in expected.items():
            scores, info = fuse_scores(columns, (.5, .5), (0, 1), op)
            self.assertEqual(info['normalized'], {0: (1, .6, 0), 1: (0, .8, 1)})
            for a, b in zip(scores, target):
                self.assertAlmostEqual(a, b)
        self.assertEqual(max(range(3), key=lambda a: expected['WEIGHTED_SUM'][a]), 1)
        self.assertEqual(max(range(3), key=lambda a: expected['MAX'][a]), 0)

    def test_min_can_express_an_action_no_linear_weight_can_choose(self):
        # WS: mean of endpoint scores is always .7, above the compromise .6.
        columns = {0: (1, .4, .6, 0), 1: (.4, 1, .6, 0)}
        minimum, _ = fuse_scores(columns, (.5, .5), (0, 1), 'MIN')
        self.assertEqual(max(range(4), key=lambda a: minimum[a]), 2)
        self.assertGreater((1 + .4)/2, .6)
        for alpha in (0, .1, .25, .5, .75, .9, 1):
            scores = [alpha*columns[0][a]+(1-alpha)*columns[1][a] for a in range(4)]
            self.assertNotEqual(max(range(4), key=lambda a: scores[a]), 2)

    def test_action_sizes_constants_and_large_finite_values(self):
        for op in ('WEIGHTED_SUM', 'MAX', 'MIN'):
            self.assertEqual(fuse_scores({0: (5,), 1: (6,)}, (.5, .5), (0, 1), op)[0], (0.,))
            scores, _ = fuse_scores({0: (5, 5, 5), 1: (0, 5, 10)}, (.5, .5), (0, 1), op)
            self.assertEqual(scores, {'WEIGHTED_SUM': (0, .25, .5), 'MAX': (0, .5, 1), 'MIN': (0, 0, 0)}[op])
            scores, _ = fuse_scores({0: (-1e308, 1e308), 1: (0, 1)}, (.5, .5), (0, 1), op)
            self.assertEqual(scores, (0, 1))
        for columns in ({0: (), 1: ()}, {0: (1, 2), 1: (2,)},
                        {0: (math.nan,), 1: (0,)}, {0: (math.inf,), 1: (0,)},
                        {0: (True,), 1: (0,)}):
            with self.assertRaises(NormalizationError):
                fuse_scores(columns, (.5, .5), (0, 1), 'MAX')

    def test_output_weights_modes_indices_and_nonfinite_guards(self):
        invalid = [('MAX', (1, 0, 0)), ('MIN', (1, 2, 0)), ('WEIGHTED_SUM', (1, 1, 1)),
                   ('WEIGHTED_SUM', (0, 0, 0)), ('WEIGHTED_SUM', (-1, 1, 0)),
                   ('WEIGHTED_SUM', (1e100, 1e-300, 0)), ('SUM', (1, 1, 0)),
                   ('MAX', (1, 1)), ('MAX', (1, math.inf, 0)), ('MAX', (1, math.nan, 0)),
                   ('MAX', (1, True, 0)), ('MAX', (1, 1e101, 0)), (True, (1, 1, 0))]
        for output in invalid:
            with self.subTest(output=output), self.assertRaises((UsageOutputError, NormalizationError)):
                decode_fusion(output, 3)
        self.assertEqual(decode_fusion(('SELECT', (-2, -1, -3)), 3)['support'], (1,))
        self.assertEqual(decode_fusion(('SELECT', (0, 0, 0)), 3)['support'], (0,))
        self.assertEqual(decode_fusion(('WEIGHTED_SUM', (0, 4, 0)), 3)['weights'], (0, 1, 0))
        for weights in ((-.5, 1.5), (0, 0), (math.nan, .5), (1, 1)):
            with self.assertRaises((UsageOutputError, NormalizationError)):
                fuse_scores({0: (0, 1), 1: (1, 0)}, weights, (0, 1), 'WEIGHTED_SUM')

    def test_v1_exact_scheduler_regression_dynamic_and_single_support(self):
        rules = (lambda p,w,n,j,m,s,f: -f, lambda p,w,n,j,m,s,f: w-p, lambda *s: 3.)
        policies = (lambda *s: (0, (0, 0, 0)), lambda *s: (0, (-3, -1, -2)),
                    lambda *s: (1, (0, 1, 0)), lambda *s: (1, (.25, .75, 0)),
                    lambda p,*s: (1, (p+.1, 1-p, 0)),
                    lambda p,c,w,d,m,v,prev: (0, (1,0,0)) if prev == -1 else (1, (0,1,1)))
        for policy in policies:
            old_trace, new_trace = [], []
            old = construct_usage_schedule(toy(), rules, policy, trace=old_trace.append)
            new = construct_fusion_schedule(toy(), rules, v1_adapter(policy), trace=new_trace.append)
            self.assertEqual(asdict(old.schedule), asdict(new.schedule))
            self.assertEqual(old.selected_members, new.selected_members)
            self.assertEqual(old.member_calls, new.member_calls)
            self.assertEqual(old.score, new.score)
            self.assertEqual([r['state'] for r in old_trace], [r['state'] for r in new_trace])
            self.assertEqual([r['chosen'] for r in new_trace],
                             [tuple(r['chosen'][k] for k in ('job','operation','machine','start','end')) for r in old_trace])

    def test_v1_random_matrix_bitwise_regression_and_sum_order(self):
        rng = random.Random(501)
        for n in (1, 2, 3, 7, 100):
            for _ in range(10):
                columns = {0: tuple(rng.uniform(-100,100) for _ in range(n)),
                           1: tuple(rng.uniform(-1e5,1e5) for _ in range(n))}
                weights = decode_output((1, (.3, .7)), 2)['weights']
                self.assertEqual(combine_scores(columns, weights, (0,1)),
                                 fuse_scores(columns, weights, (0,1), 'WEIGHTED_SUM'))
                scores, info = fuse_scores(columns, (.5,.5), (0,1), 'WEIGHTED_SUM')
                summed = [info['normalized'][0][i]+info['normalized'][1][i] for i in range(n)]
                self.assertEqual(max(range(n), key=lambda i:scores[i]), max(range(n), key=lambda i:summed[i]))

    def test_exact_ties_enumeration_previous_member_and_determinism(self):
        rules = (lambda *a: 5., lambda *a: 5., lambda *a: 0.)
        for op in ('WEIGHTED_SUM', 'MAX', 'MIN'):
            trace = []
            first = construct_fusion_schedule(toy(), rules, fixed_policy((0,1), op, 3), trace=trace.append)
            self.assertEqual(trace[0]['chosen'][:3], (0, 0, 0))
            self.assertEqual([r['state']['previous_heuristic'] for r in trace], [-1, 0, 0])
            random.seed(501)
            second = construct_fusion_schedule(toy(), rules, fixed_policy((0,1), op, 3))
            self.assertEqual(first, second)

    def test_dynamic_operator_extension_and_h_failures(self):
        rules = (lambda *a: 1., lambda *a: 0.)
        policy = lambda progress,*s: ('MAX' if progress < .5 else 'MIN', (1,1))
        result = construct_fusion_schedule(toy(), rules, policy)
        self.assertEqual([d[0] for d in result.decisions], ['MAX','MAX','MIN'])
        for value in (math.nan, math.inf, True, '1'):
            with self.assertRaises(ValueError):
                construct_fusion_schedule(toy(), (lambda *a: value, rules[1]), fixed_policy((0,1), 'MAX', 2))

    def test_normal_timeout_and_identity_failure_classification(self):
        witness = {'pid': 7, 'modules': {'executor': 'pinned'}}
        witness['identity'] = digest(witness['modules'])
        life = {'status':'terminal','alive':False,'exitcode':0,'pid':7}
        kwargs = dict(before=witness, after=witness, lifecycle=life, expected_identity=witness['identity'],
                      expected_files={'x':'hash'}, start_files={'x':'hash'}, end_files={'x':'hash'})
        self.assertEqual(classify_boundary({'valid':True,'fitness':-2}, **kwargs)['decision'], 'original_result_checks_required')
        self.assertEqual(classify_boundary({'valid':True,'fitness':-2}, **dict(kwargs, after=None))['decision'], 'stop')
        timeout = {'valid':False,'fitness':None,'error_type':'Timeout',
                   'error':'whole-instance deadline exceeded','failed_instance':'toy'}
        terminal = dict(life, exitcode=-signal.SIGTERM, trigger='parent_poll_timeout', deadline_seconds=15, cleanup=['terminate'])
        self.assertEqual(classify_boundary(timeout, **dict(kwargs, after=None, lifecycle=terminal))['decision'], 'candidate_invalid_continue')
        for changed in (dict(kwargs, before=None), dict(kwargs, end_files={}),
                        dict(kwargs, lifecycle=dict(life, alive=True)), dict(kwargs, worker_failure=True)):
            self.assertEqual(classify_boundary(timeout, **changed)['decision'], 'stop')

    def test_loaded_source_detects_runtime_monkeypatch(self):
        pins = {str(Path(__import__('importlib').import_module(n).__file__).resolve().relative_to(ROOT)): '' for n in MODULES}
        from tools.fusion_v2_experiment import sha
        protocol = {'source_files': {p: sha(ROOT/p) for p in pins}}
        source_witness(protocol)
        with patch('fjsp_usage.fusion_v2.execution.fixed_policy', lambda *a: None):
            with self.assertRaisesRegex(ValueError, 'loaded function differs'):
                source_witness(protocol)

    def test_spawn_worker_full_mock_preserves_all_evidence(self):
        from fjsp_usage.research.candidates import validate_code, H_ARGS
        from tools.fusion_v2_experiment import sha, read
        pins = {str(Path(__import__('importlib').import_module(n).__file__).resolve().relative_to(ROOT))
                for n in MODULES}
        protocol = {'source_files': {p: sha(ROOT/p) for p in pins},
                    'instances': [{'relative_path': 'inputs/train/toy.fjsp'}]}
        members = tuple(validate_code('def priority('+', '.join(H_ARGS)+'):\n    return -'+H_ARGS[-1]+'\n', kind='h')
                        for _ in range(10))
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            spec = specs()[0]
            folder = directory/'evidence'/spec['id']
            folder.mkdir(parents=True)
            receipts = []
            rows, failure, lifecycle = collect_with_lifecycle(mp.get_context('spawn'), worker,
                {'directory': str(directory), 'protocol': protocol, 'spec': spec}, members,
                (toy(),), ('toy.fjsp',), 15, None, receipts.append)
            self.assertIsNone(failure)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['captured_solves'], 2)
            self.assertEqual(rows[0]['physical_schedule_sha256'], rows[0]['recheck_physical_schedule_sha256'])
            self.assertEqual(lifecycle['exitcode'], 0)
            self.assertFalse(lifecycle['alive'])
            self.assertEqual(receipts[0]['status'], 'started')
            self.assertEqual(receipts[-1]['status'], 'terminal')
            self.assertEqual(read(folder/'before.json')['identity'], read(folder/'after.json')['identity'])
            self.assertEqual(rows[0]['network_guard'], {'network_attempts_blocked': 0, 'nontrain_opens_blocked': 0})

    def test_offline_guard_denies_network_and_holdout_in_subprocess(self):
        code = """from tools.fusion_v2_experiment import local_guard
import socket, tempfile
from pathlib import Path
d=Path(tempfile.mkdtemp())
original=d/'original'/'train.fjsp'; copied=d/'copied'/'train.fjsp'
original.parent.mkdir(); copied.parent.mkdir()
original.write_text('same train'); copied.write_text('same train')
g=local_guard([original,copied])
assert original.read_text()==copied.read_text()=='same train'
for f in (lambda: socket.getaddrinfo('example.com',443), lambda: open('/tmp/test28.fjsp')):
    try: f()
    except RuntimeError: pass
    else: raise AssertionError('guard did not block')
assert g == {'network_attempts_blocked':1,'nontrain_opens_blocked':1}
"""
        done = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(specs()), 9)


if __name__ == '__main__':
    unittest.main()
