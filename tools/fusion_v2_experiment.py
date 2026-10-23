"""Bounded local-only V2 feasibility experiment. No supplier/client imports.

prepare -> check -> run -> report. Nine fixed train21 strategies, two solves per
instance, durable reservations, before/after loaded-source witnesses and terminal
process receipts. No unknown interrupted task is automatically repeated.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import csv
import gzip
import hashlib
import importlib
import inspect
import itertools
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import platform
import random
import resource
from statistics import fmean
import sys
import time
import types

from fjsp_usage.fusion_v2 import VERSION, OPERATORS
from fjsp_usage.fusion_v2.execution import construct_fusion_schedule, fixed_policy, fuse_scores
from fjsp_usage.offline_v2 import lower_bound_v5
from fjsp_usage.research.candidates import compile_candidate
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import checked_candidate, check_result, check_seal
from fjsp_usage.research_real.locking import RunLock
from llm4ad.task.optimization.fjsp_set.instances import load_instance
from tools.b1_timeout_boundary import collect_with_lifecycle, classify_boundary

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'runs/fusion-v2-train21-seed501-20261023-v2'
B2 = ROOT / 'runs/h01-state-weight-search-seed501-batch-v3-20261020'
PAIRS = ((0, 1), (0, 5), (5, 9))
MODULES = ('fjsp_usage.fusion_v2', 'fjsp_usage.fusion_v2.execution',
           'fjsp_usage.offline_v2', 'fjsp_usage.usage_v2.execution',
           'fjsp_usage.research.candidates', 'fjsp_usage.research.protocol',
           'fjsp_usage.research.events', 'fjsp_usage.research_real.assets',
           'fjsp_usage.research_real.locking', 'tools.b1_timeout_boundary',
           'tools.fusion_v2_experiment', 'llm4ad.task.optimization.fjsp_set.instances',
           'llm4ad.task.optimization.fjsp_set.scheduler')


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def specs():
    return [{'id': f'H{a}_H{b}_{op}', 'pair': [a, b], 'operator': op}
            for a, b in PAIRS for op in OPERATORS]


def physical(schedule):
    return {'makespan': schedule.makespan, 'operations': sorted(
        [x.job, x.operation, x.machine, x.start, x.end] for x in schedule.operations)}


def code_identity(code):
    def constant(value):
        if isinstance(value, types.CodeType):
            return code_identity(value)
        if isinstance(value, tuple):
            return [constant(x) for x in value]
        if isinstance(value, frozenset):
            return sorted(map(repr, value))
        return repr(value)
    return digest({k: code.co_code.hex() if k == 'co_code' else
                   [constant(v) for v in code.co_consts] if k == 'co_consts' else getattr(code, k)
                   for k in ('co_code', 'co_consts', 'co_names', 'co_varnames', 'co_freevars',
                             'co_cellvars', 'co_argcount', 'co_posonlyargcount',
                             'co_kwonlyargcount', 'co_flags')})


def source_witness(protocol):
    rows = {}
    for name in MODULES:
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        relative = str(path.relative_to(ROOT))
        if sha(path) != protocol['source_files'][relative]:
            raise ValueError('loaded source hash differs: ' + name)
        compiled = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True, optimize=0)
        definitions = {x.co_name: x for x in compiled.co_consts if isinstance(x, types.CodeType)}
        functions = {}
        for key, value in vars(module).items():
            if inspect.isfunction(value) and (value.__module__ == name or key in definitions):
                if key not in definitions or code_identity(value.__code__) != code_identity(definitions[key]):
                    raise ValueError('loaded function differs from source: ' + name + '.' + key)
                functions[key] = code_identity(value.__code__)
            if inspect.isclass(value) and value.__module__ == name and key in definitions:
                methods = {x.co_name: x for x in definitions[key].co_consts if isinstance(x, types.CodeType)}
                for method, fn in vars(value).items():
                    if isinstance(fn, (classmethod, staticmethod)):
                        fn = fn.__func__
                    if inspect.isfunction(fn) and method in methods:
                        if code_identity(fn.__code__) != code_identity(methods[method]):
                            raise ValueError('loaded method differs from source')
                        functions[key + '.' + method] = code_identity(fn.__code__)
        rows[name] = {'file': str(path), 'source_sha256': sha(path), 'loaded_functions': functions}
    return {'pid': os.getpid(), 'modules': rows, 'identity': digest(rows)}


def local_guard(allowed_data):
    """Audit deny network connects/DNS and any non-training .fjsp open."""
    allowed = {str(Path(x).resolve()) for x in allowed_data}
    events = {'network_attempts_blocked': 0, 'nontrain_opens_blocked': 0}
    def audit(event, args):
        if event in ('socket.connect', 'socket.connect_ex', 'socket.getaddrinfo', 'socket.sendto'):
            events['network_attempts_blocked'] += 1
            raise RuntimeError('V2 forbids all remote network access')
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0]))
            if path.suffix == '.fjsp' and str(path.resolve()) not in allowed:
                events['nontrain_opens_blocked'] += 1
                raise RuntimeError('V2 forbids non-training FJSP access')
    sys.addaudithook(audit)
    return events


def prepare(directory):
    if directory.parent != ROOT / 'runs' or directory.exists():
        raise ValueError('new independent runs child required; no overwrite')
    plan = read(B2 / 'Plan.json')
    frozen = check_seal(read(B2 / 'H_frozen.json'), kind='H_frozen', mode='real')
    members = [checked_candidate(m['candidate'], 'h') for m in frozen['members']]
    if len(members) != 10 or [m.key for m in members] != plan['H_order']:
        raise ValueError('H code/order differs from B2')
    manifest_path = ROOT / 'data/fjsp_manifest.json'
    manifest = read(manifest_path)
    names = plan['names']
    if len(names) != 21 or names != manifest['split']['train'] or sha(manifest_path) != plan['dataset']['manifest_sha256']:
        raise ValueError('original train21 identity/order differs')
    # Historical evolution changed four API/accounting modules. They are never
    # imported by this runner. Every inherited local scheduling dependency must match.
    science = ('code/fjsp_usage/offline_v2.py', 'code/fjsp_usage/usage_v2/execution.py',
               'code/fjsp_usage/research/candidates.py',
               'code/llm4ad/task/optimization/fjsp_set/instances.py',
               'code/llm4ad/task/optimization/fjsp_set/scheduler.py')
    for name in science:
        if sha(ROOT / name) != plan['pins'][name]:
            raise ValueError('historical scheduling science pin differs: ' + name)
    changes = [n for n, h in plan['pins'].items() if not (ROOT / n).is_file() or sha(ROOT / n) != h]
    permitted = {'code/fjsp_usage/research_real/attempt_budget.py', 'code/fjsp_usage/research_real/budget.py',
                 'code/fjsp_usage/research_real/real_transport.py', 'code/fjsp_usage/usage_v2/access.py'}
    if set(changes) - permitted:
        raise ValueError('unexplained historical pin drift: ' + repr(changes))
    initial = read(B2 / 'Initial_population.json')
    references = {}
    for key, identifier in (('H0', 'MANUAL/init/alpha_100'), ('H01_equal', 'MANUAL/init/alpha_050')):
        entry = next(x for x in initial if x['id'] == identifier)
        candidate = checked_candidate(entry['candidate'], 'U')
        check_result(entry['training_result'], names)
        if candidate.member_count != 10 or entry['fitness'] != entry['training_result']['fitness']:
            raise ValueError('reference code/result identity mismatch')
        references[key] = {k: entry[k] for k in ('id', 'candidate', 'fitness', 'training_result')}
    sources = {str(Path(importlib.import_module(n).__file__).resolve().relative_to(ROOT)) for n in MODULES}
    sources |= {'experiments/tier2/fusion_v2/run.py', 'tests/test_fusion_v2.py', 'docs/FUSION_V2_PROTOCOL.md'}
    source_files = {n: sha(ROOT / n) for n in sorted(sources)}
    # Protect bounded original assets and all source pins without rewriting any.
    protected = {n: sha(ROOT / n) for n in plan['pins'] if (ROOT / n).is_file()}
    for path in (B2 / 'Plan.json', B2 / 'H_frozen.json', B2 / 'Initial_population.json', manifest_path):
        protected[str(path.relative_to(ROOT))] = sha(path)
    for run in ('b1-full-h-free-seed501-k2-v1-20261021',
                'b1-ns-full-h-free-seed501-k2-v1-20261022', 'b1-ns-recovery-B-v1-20261022',
                'b1-ns-timeout-boundary-preparation-v1-20261023'):
        folder = ROOT / 'runs' / run
        for name in ('protocol.json', 'Protocol.json', 'checkpoint.json', 'r501/B/checkpoint.json'):
            path = folder / name
            if path.is_file():
                protected[str(path.relative_to(ROOT))] = sha(path)
    directory.mkdir()
    (directory / 'inputs/train').mkdir(parents=True)
    (directory / 'evidence').mkdir()
    rows = []
    for name in names:
        source = ROOT / 'data/fjsp' / name
        expected = manifest['files'][name]['sha256']
        if sha(source) != expected:
            raise ValueError('training source hash differs')
        target = directory / 'inputs/train' / name
        target.write_bytes(source.read_bytes())
        instance = load_instance(target)
        rows.append({'file': name, 'sha256': expected, 'relative_path': 'inputs/train/' + name,
                     'LB': lower_bound_v5(instance), 'operations': instance.operation_count})
    atomic_json(directory / 'H_frozen.json', frozen)
    atomic_json(directory / 'References.json', references)
    protocol = {'version': VERSION, 'seed': 501, 'pairs': [list(p) for p in PAIRS], 'operators': list(OPERATORS),
                'strategies': specs(), 'instances': rows, 'H_order': plan['H_order'],
                'H_sha256': sha(directory / 'H_frozen.json'), 'references_sha256': sha(directory / 'References.json'),
                'source_B2': str(B2.relative_to(ROOT)), 'source_B2_plan_sha256': sha(B2 / 'Plan.json'),
                'source_files': source_files, 'protected_files': protected,
                'historical_nonexecution_API_module_drift': changes,
                'instance_timeout': 15, 'evaluation_cap': 189, 'solve_pass_cap': 378, 'api_cap': 0,
                'fitness': 'arithmetic mean of -Cmax/LB, all21-or-null; unrounded V5 LB',
                'formal_cache_reuse': False,
                'reference_reuse': 'original B2 frozen H, data, local evaluator pins; copied complete results, no new baseline solve',
                'diagnostics': 'full first-solve states/all action columns on all9 source trajectories; recombine offline, no extra H calls or solves',
                'statistics': 'descriptive paired deltas and win/loss/tie; no confirmatory p-values on searched train21',
                'authorization': {'scope': 'user 2026-10-23 continuous V2 local code/tests/mock/FJSP/analysis/report/commit/push',
                                  'real_LLM_requests': False, 'paid_services': False,
                                  'holdout_access': False}}
    atomic_json(directory / 'Protocol.json', protocol)
    (directory / 'Protocol.sha256').write_text(sha(directory / 'Protocol.json') + '\n')
    witness = source_witness(protocol)
    atomic_json(directory / 'Expected_loaded_identity.json', witness)
    atomic_json(directory / 'checkpoint.json', {'protocol_sha256': sha(directory / 'Protocol.json'),
                                               'phase': 'prepared', 'strategies': {}})
    return protocol


def check(directory):
    p = read(directory / 'Protocol.json')
    if sha(directory / 'Protocol.json') != (directory / 'Protocol.sha256').read_text().strip():
        raise ValueError('protocol identity changed')
    if (p['version'] != VERSION or p['seed'] != 501 or p['strategies'] != specs()
            or p['operators'] != list(OPERATORS) or p['pairs'] != [list(x) for x in PAIRS]
            or (p['evaluation_cap'], p['solve_pass_cap'], p['api_cap'], p['instance_timeout']) != (189, 378, 0, 15)):
        raise ValueError('fixed V2 scope/budget changed')
    for name, expected in {**p['protected_files'], **p['source_files']}.items():
        if sha(ROOT / name) != expected:
            raise ValueError('frozen file changed: ' + name)
    for name, expected in (('H_frozen.json', p['H_sha256']), ('References.json', p['references_sha256'])):
        if sha(directory / name) != expected:
            raise ValueError('bound asset changed: ' + name)
    if len(p['instances']) != 21 or len({r['file'] for r in p['instances']}) != 21:
        raise ValueError('exact train21 required')
    manifest = read(ROOT / 'data/fjsp_manifest.json')
    if [r['file'] for r in p['instances']] != manifest['split']['train']:
        raise ValueError('non-training or changed instance order')
    for row in p['instances']:
        path = (directory / row['relative_path']).resolve()
        if not path.is_relative_to(directory / 'inputs/train') or sha(path) != row['sha256']:
            raise ValueError('frozen train input changed')
    witness = source_witness(p)
    expected = read(directory / 'Expected_loaded_identity.json')
    if witness['identity'] != expected['identity']:
        raise ValueError('loaded/source identity differs from preparation')
    return p


def worker(pipe, payload, members, instances, names, allowed_modes):
    directory = Path(payload['directory'])
    folder = directory / 'evidence' / payload['spec']['id']
    protocol = payload['protocol']
    guard = local_guard([directory / row['relative_path'] for row in protocol['instances']])
    try:
        random.seed(501)
        atomic_json(folder / 'before.json', source_witness(protocol))
        rules = tuple(compile_candidate(m) for m in members)
        spec = payload['spec']
        policy = fixed_policy(tuple(spec['pair']), spec['operator'])
        for instance, name in zip(instances, names):
            started = time.perf_counter()
            cpu_start = time.process_time()
            stem = folder / Path(name).stem
            progress = {'file': name, 'first_started': True, 'recheck_started': False, 'completed': False}
            atomic_json(stem.with_suffix('.progress.json'), progress)
            traces, costs = [], []
            t = time.perf_counter()
            first = construct_fusion_schedule(instance, rules, policy, trace=traces.append, cost=costs.append)
            first_seconds = time.perf_counter() - t
            first_costs = list(costs)
            costs.clear()
            progress['recheck_started'] = True
            atomic_json(stem.with_suffix('.progress.json'), progress)
            t = time.perf_counter()
            second = construct_fusion_schedule(instance, rules, policy, cost=costs.append)
            recheck_seconds = time.perf_counter() - t
            if first != second:
                raise ValueError('nondeterministic full fusion result')
            first_physical, second_physical = physical(first.schedule), physical(second.schedule)
            if first_physical != second_physical:
                raise ValueError('physical schedule recheck mismatch')
            t = time.perf_counter()
            trace_path = stem.with_suffix('.trace.jsonl.gz')
            with gzip.open(trace_path, 'wt', encoding='utf-8', compresslevel=1) as handle:
                for trace in traces:
                    handle.write(json.dumps(trace, separators=(',', ':'), allow_nan=False) + '\n')
            trace_write_seconds = time.perf_counter() - t
            row = {'file': name, 'makespan': first.schedule.makespan, 'lower_bound': first.lower_bound,
                   'score': first.score, 'feasible': True, 'captured_solves': 2,
                   'single_solve_seconds': first_seconds, 'deterministic_recheck_seconds': recheck_seconds,
                   'first_trace_write_seconds': trace_write_seconds,
                   'instance_worker_seconds': time.perf_counter() - started,
                   'instance_CPU_seconds': time.process_time() - cpu_start,
                   'peak_RSS_native_units': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   'single_h_calls': list(first.member_calls), 'recheck_h_calls': list(second.member_calls),
                   'first_costs': {k: sum(x[k] for x in first_costs) for k in ('h_scoring_seconds', 'fusion_seconds')},
                   'recheck_costs': {k: sum(x[k] for x in costs) for k in ('h_scoring_seconds', 'fusion_seconds')},
                   'physical_schedule': first_physical, 'physical_schedule_sha256': digest(first_physical),
                   'recheck_physical_schedule_sha256': digest(second_physical),
                   'commit_sequence_sha256': digest(asdict(first.schedule)),
                   'trace_path': str(trace_path.relative_to(directory)), 'trace_sha256': sha(trace_path),
                   'trace_states': len(traces), 'network_guard': dict(guard)}
            atomic_json(stem.with_suffix('.result.json'), row)
            progress['completed'] = True
            atomic_json(stem.with_suffix('.progress.json'), progress)
            if name == names[-1]:
                atomic_json(folder / 'after.json', source_witness(protocol))
            pipe.send(row)
    except BaseException as exc:
        atomic_json(folder / 'worker_failure.json', {'error_type': type(exc).__name__, 'error': str(exc)})
        atomic_json(folder / 'after.json', source_witness(protocol))
        pipe.send({'error_type': type(exc).__name__, 'error': str(exc)[:1000]})
    finally:
        try:
            if not (folder / 'after.json').exists():
                atomic_json(folder / 'after.json', source_witness(protocol))
            atomic_json(folder / 'network_guard.json', guard)
        finally:
            pipe.close()


def validate_rows(rows, protocol):
    for result, expected in zip(rows, protocol['instances']):
        if (result['file'] != expected['file'] or result['lower_bound'] != expected['LB']
                or result['captured_solves'] != 2 or result['feasible'] is not True
                or result['score'] != -result['makespan']/expected['LB']
                or digest(result['physical_schedule']) != result['physical_schedule_sha256']
                or result['physical_schedule_sha256'] != result['recheck_physical_schedule_sha256']
                or result['single_h_calls'] != result['recheck_h_calls']
                or result['trace_states'] != expected['operations']):
            raise ValueError('result identity/LB/score/physical recheck mismatch')
        if any(result['network_guard'].values()):
            raise ValueError('forbidden access attempted')


def run(directory):
    protocol = check(directory)
    if (directory / 'Stop.json').exists():
        raise ValueError('persistent stop evidence requires review; no automatic continuation')
    guard = local_guard([path for row in protocol['instances'] for path in
                         (directory / row['relative_path'], ROOT / 'data/fjsp' / row['file'])])
    state = read(directory / 'checkpoint.json')
    if state['protocol_sha256'] != sha(directory / 'Protocol.json') or not set(state['strategies']) <= {s['id'] for s in specs()}:
        raise ValueError('checkpoint identity/cap mismatch')
    for identifier, record in state['strategies'].items():
        if record['status'] != 'completed':
            raise ValueError('uncertain prior reservation; never automatically repeat')
        if sha(directory / record['result_path']) != record['result_sha256']:
            raise ValueError('saved result changed')
    members = tuple(checked_candidate(row['candidate'], 'h') for row in read(directory / 'H_frozen.json')['members'])
    instances = tuple(load_instance(directory / row['relative_path']) for row in protocol['instances'])
    names = tuple(row['file'] for row in protocol['instances'])
    expected_identity = read(directory / 'Expected_loaded_identity.json')['identity']
    try:
        for spec in specs():
            if spec['id'] in state['strategies']:
                continue
            check(directory)
            folder = directory / 'evidence' / spec['id']
            if folder.exists():
                raise ValueError('orphan evidence without reservation')
            folder.mkdir()
            state['phase'] = 'running'
            state['strategies'][spec['id']] = {'status': 'reserved', 'reserved_evaluations': 21,
                                             'reserved_solve_passes': 42, 'started_unix': time.time()}
            if len(state['strategies']) * 21 > 189:
                raise ValueError('evaluation budget exceeded')
            atomic_json(directory / 'checkpoint.json', state)
            expected_files = {**protocol['protected_files'], **protocol['source_files']}
            start_files = {n: sha(ROOT / n) for n in expected_files}
            t = time.monotonic()
            rows, failure, lifecycle = collect_with_lifecycle(
                mp.get_context('spawn'), worker,
                {'directory': str(directory), 'protocol': protocol, 'spec': spec}, members,
                instances, names, 15, None, lambda receipt: atomic_json(folder / 'lifecycle.json', receipt))
            result = {'valid': failure is None, 'fitness': fmean(r['score'] for r in rows) if failure is None else None,
                      'instances': rows, 'total_instances': 21, 'primary_evaluation_seconds': time.monotonic()-t,
                      **(failure or {})}
            atomic_json(folder / 'raw_result.json', result)
            check(directory)
            end_files = {n: sha(ROOT / n) for n in expected_files}
            boundary = classify_boundary(result,
                before=read(folder / 'before.json') if (folder / 'before.json').exists() else None,
                after=read(folder / 'after.json') if (folder / 'after.json').exists() else None,
                lifecycle=lifecycle, expected_identity=expected_identity,
                expected_files=expected_files, start_files=start_files, end_files=end_files,
                worker_failure=(folder / 'worker_failure.json').exists())
            atomic_json(folder / 'boundary.json', boundary)
            if boundary['decision'] == 'stop':
                raise ValueError('evaluation boundary stop: ' + boundary['reason'])
            validate_rows(rows, protocol)
            check_result(result, names)
            for row in rows:
                if sha(directory / row['trace_path']) != row['trace_sha256']:
                    raise ValueError('raw trace changed')
            # Real train21 regression on the existing H01 equal reference. No
            # extra solves and no acceptance based only on a mean Fitness.
            if spec['id'] == 'H0_H1_WEIGHTED_SUM' and result['valid']:
                reference = read(directory / 'References.json')['H01_equal']['training_result']
                for new, old in zip(rows, reference['instances']):
                    if any(new[k] != old[k] for k in ('file', 'makespan', 'lower_bound', 'score')):
                        raise ValueError('V1 historical H01 equality regression failed')
                    if old.get('physical_schedule_sha256') and new['physical_schedule_sha256'] != old['physical_schedule_sha256']:
                        raise ValueError('V1 historical physical schedule mismatch')
            result['boundary'] = boundary
            atomic_json(folder / 'result.json', result)
            state['strategies'][spec['id']].update(status='completed', valid=result['valid'],
                result_path=str((folder / 'result.json').relative_to(directory)),
                result_sha256=sha(folder / 'result.json'))
            atomic_json(directory / 'checkpoint.json', state)
            print(json.dumps({'strategy': spec['id'], 'valid': result['valid'], 'fitness': result['fitness'],
                              'instances': len(rows), 'seconds': result['primary_evaluation_seconds']}), flush=True)
        state['phase'] = 'completed'
        atomic_json(directory / 'checkpoint.json', state)
        atomic_json(directory / 'Network_guard.json', guard)
    except BaseException as exc:
        atomic_json(directory / 'Stop.json', {'error_type': type(exc).__name__, 'error': str(exc),
                                            'time_unix': time.time(), 'automatic_retry': False})
        raise


def csv_write(path, rows):
    if not rows:
        return
    with Path(path).open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def report(directory):
    protocol = check(directory)
    state = read(directory / 'checkpoint.json')
    output = ROOT / 'reports' / directory.name
    output.mkdir(exist_ok=True)
    references = read(directory / 'References.json')
    baselines = {key: {r['file']: r for r in value['training_result']['instances']}
                 for key, value in references.items()}
    result_map, instance_rows, rankings, all_states = {}, [], [], []
    physical_groups = defaultdict(list)
    pair_instance_physical = defaultdict(dict)
    for spec in specs():
        record = state['strategies'].get(spec['id'])
        if not record or record['status'] != 'completed':
            continue
        path = directory / record['result_path']
        if sha(path) != record['result_sha256']:
            raise ValueError('result digest differs')
        result = read(path)
        validate_rows(result['instances'], protocol)
        check_result(result, [r['file'] for r in protocol['instances']])
        result_map[spec['id']] = result
        rows = result['instances']
        rankings.append({'strategy': spec['id'], 'pair': '/'.join(map(str, spec['pair'])),
            'operator': spec['operator'], 'valid': result['valid'], 'completed_instances': len(rows),
            'fitness': result['fitness'],
            'delta_F_vs_H0': result['fitness']-references['H0']['fitness'] if result['valid'] else None,
            'delta_F_vs_H01_equal': result['fitness']-references['H01_equal']['fitness'] if result['valid'] else None,
            'Cmax_sum': sum(r['makespan'] for r in rows) if result['valid'] else None,
            'first_seconds': sum(r['single_solve_seconds'] for r in rows),
            'recheck_seconds': sum(r['deterministic_recheck_seconds'] for r in rows),
            'primary_wall_seconds': result['primary_evaluation_seconds'],
            'CPU_seconds': sum(r['instance_CPU_seconds'] for r in rows),
            'H_calls_two_passes': sum(sum(r['single_h_calls'])+sum(r['recheck_h_calls']) for r in rows),
            'error_type': result.get('error_type')})
        if result['valid']:
            physical_groups[digest([r['physical_schedule_sha256'] for r in rows])].append(spec['id'])
        for row in rows:
            pair_instance_physical[row['file']][spec['id']] = row['physical_schedule_sha256']
            instance_rows.append({'strategy': spec['id'], 'file': row['file'], 'Cmax': row['makespan'],
                'LB': row['lower_bound'], 'score': row['score'],
                'H0_Cmax': baselines['H0'][row['file']]['makespan'],
                'H01_equal_Cmax': baselines['H01_equal'][row['file']]['makespan'],
                'delta_Cmax_vs_H0': row['makespan']-baselines['H0'][row['file']]['makespan'],
                'delta_Cmax_vs_H01_equal': row['makespan']-baselines['H01_equal'][row['file']]['makespan'],
                'delta_F_vs_H0': row['score']-baselines['H0'][row['file']]['score'],
                'delta_F_vs_H01_equal': row['score']-baselines['H01_equal'][row['file']]['score'],
                'physical_schedule_sha256': row['physical_schedule_sha256'],
                'single_seconds': row['single_solve_seconds'], 'recheck_seconds': row['deterministic_recheck_seconds']})
            trace_path = directory / row['trace_path']
            if sha(trace_path) != row['trace_sha256']:
                raise ValueError('trace digest differs')
            with gzip.open(trace_path, 'rt', encoding='utf-8') as handle:
                for line in handle:
                    trace = json.loads(line)
                    if digest(trace['physical_state']) != trace['state_sha256']:
                        raise ValueError('full common-state digest differs')
                    columns = {int(i): tuple(v) for i, v in trace['columns'].items()}
                    support = tuple(trace['support'])
                    decisions, ties = {}, {}
                    for op in OPERATORS:
                        scores, _ = fuse_scores(columns, trace['weights'], support, op)
                        index = max(range(len(scores)), key=lambda n: scores[n])
                        decisions[op] = index
                        ties[op] = sum(x == scores[index] for x in scores)
                        if op == spec['operator'] and (index != trace['winner'] or tuple(scores) != tuple(trace['scores'])):
                            raise ValueError('offline recombination differs from executed decision')
                    # Nonnegative WS endpoints are single H; on two columns MAX
                    # always chooses one endpoint action under exact stable ties.
                    endpoints = [max(range(len(columns[i])), key=lambda n: columns[i][n]) for i in support]
                    all_states.append({'source_strategy': spec['id'], 'file': row['file'], 'step': trace['step'],
                        'pair': '/'.join(map(str, spec['pair'])), 'state_sha256': trace['state_sha256'],
                        'action_count': len(trace['actions']),
                        **{op+'_action_index': decisions[op] for op in OPERATORS},
                        **{op+'_ties_at_max': ties[op] for op in OPERATORS},
                        'MAX_diff_WS': decisions['MAX'] != decisions['WEIGHTED_SUM'],
                        'MIN_diff_WS': decisions['MIN'] != decisions['WEIGHTED_SUM'],
                        'MAX_diff_MIN': decisions['MAX'] != decisions['MIN'],
                        'MAX_is_member_top_action': decisions['MAX'] in endpoints,
                        'MIN_is_member_top_action': decisions['MIN'] in endpoints})
    rankings.sort(key=lambda x: (x['fitness'] is not None, x['fitness'] if x['fitness'] is not None else -math.inf), reverse=True)
    diagnostics = []
    # Report source-conditioned counts and deduplicated union separately. A state
    # key includes instance, full physical state and previous member, not 7D only.
    for pair in ('0/1', '0/5', '5/9'):
        group = [r for r in all_states if r['pair'] == pair]
        pools = {source: [r for r in group if r['source_strategy'] == source]
                 for source in sorted({r['source_strategy'] for r in group})}
        unique = {(r['file'], r['state_sha256']): r for r in group}
        pools['UNION_DEDUPLICATED'] = list(unique.values())
        for source, values in pools.items():
            diagnostics.append({'pair': pair, 'source': source, 'states': len(values),
                **{k: sum(bool(r[k]) for r in values) for k in
                   ('MAX_diff_WS', 'MIN_diff_WS', 'MAX_diff_MIN', 'MAX_is_member_top_action', 'MIN_is_member_top_action')},
                **{op+'_tied_states': sum(r[op+'_ties_at_max'] > 1 for r in values) for op in OPERATORS}})
    comparisons = []
    for pair in PAIRS:
        base = f'H{pair[0]}_H{pair[1]}_'
        ws = result_map.get(base+'WEIGHTED_SUM')
        for op in ('MAX', 'MIN'):
            other = result_map.get(base+op)
            if not ws or not other or not ws['valid'] or not other['valid']:
                continue
            diffs = [a['score']-b['score'] for a, b in zip(other['instances'], ws['instances'])]
            comparisons.append({'pair': '/'.join(map(str, pair)), 'operator_vs_WS': op,
                'delta_F': fmean(diffs), 'wins': sum(x > 0 for x in diffs),
                'losses': sum(x < 0 for x in diffs), 'ties': sum(x == 0 for x in diffs),
                'different_physical_schedules': sum(a['physical_schedule_sha256'] != b['physical_schedule_sha256']
                    for a, b in zip(other['instances'], ws['instances']))})
    physical_pairs = []
    for a, b in itertools.combinations(sorted(result_map), 2):
        physical_pairs.append({'strategy_a': a, 'strategy_b': b,
            'same_physical_instances': sum(values.get(a) is not None and values.get(a) == values.get(b)
                                           for values in pair_instance_physical.values())})
    progress = [read(path) for path in (directory/'evidence').glob('*/*.progress.json')]
    costs = {'reserved_evaluations': sum(r['reserved_evaluations'] for r in state['strategies'].values()),
             'started_first_solves': sum(r['first_started'] for r in progress),
             'started_rechecks': sum(r['recheck_started'] for r in progress),
             'completed_pairs': sum(r['completed'] for r in progress),
             'API_requests': 0, 'additional_diagnostic_solves': 0, 'additional_diagnostic_H_calls': 0,
             'primary_wall_seconds': sum(r['primary_wall_seconds'] for r in rankings),
             'successful_instance_CPU_seconds': sum(r['CPU_seconds'] for r in rankings),
             'H_calls_two_passes': sum(r['H_calls_two_passes'] for r in rankings),
             'raw_trace_bytes': sum(p.stat().st_size for p in (directory/'evidence').glob('*/*.trace.jsonl.gz')),
             'RSS_units': 'bytes on macOS; KiB on Linux; per-worker high-water mark, not additive',
             'timing_boundary': 'first solve includes state/column recording; recheck has no traces; serialization and startup reported separately/within primary wall',
             'failed_or_uncertified_cost': 'unknown where not recorded, never zero-filled'}
    if costs['reserved_evaluations'] > 189 or costs['started_first_solves']+costs['started_rechecks'] > 378:
        raise ValueError('observed evaluation budget exceeded')
    summary = {'version': VERSION, 'phase': state['phase'], 'protocol_sha256': sha(directory/'Protocol.json'),
               'rankings': rankings, 'operator_comparisons': comparisons, 'same_state_diagnostics': diagnostics,
               'full_train_physical_groups': list(physical_groups.values()), 'costs': costs,
               'valid_strategies': sum(r['valid'] for r in rankings), 'expected_strategies': 9,
               'reference_fitness': {k: v['fitness'] for k, v in references.items()},
               'boundary': 'train21 feasibility only; no LLM discovery/dynamic policy/generalization claim',
               'MAX_expression_boundary': 'MAX may differ from equal WS but always returns a selected member top action; not evidence of actions outside arbitrary nonnegative WS incl endpoints',
               'MIN_expression_boundary': 'different actions from equal WS alone do not prove nonrepresentability by all WS weights'}
    csv_write(output/'Ranking.csv', rankings)
    csv_write(output/'Instances.csv', instance_rows)
    csv_write(output/'Common_state_summary.csv', diagnostics)
    csv_write(output/'Operator_comparisons.csv', comparisons)
    csv_write(output/'Physical_schedule_pairs.csv', physical_pairs)
    with gzip.open(output/'Common_state_actions.csv.gz', 'wt', encoding='utf-8') as handle:
        if all_states:
            writer = csv.DictWriter(handle, fieldnames=list(all_states[0]))
            writer.writeheader()
            writer.writerows(all_states)
    atomic_json(output/'Summary.json', summary)
    atomic_json(output/'Protocol.json', protocol)
    atomic_json(output/'Reference_provenance.json', {'source': str(B2.relative_to(ROOT)),
        'source_plan_sha256': protocol['source_B2_plan_sha256'], 'references': references,
        'local_scheduling_pins_match_B2': True, 'new_baseline_solves': 0})
    # Preserve compact raw result/identity receipts in Git; larger first-pass
    # action matrices remain in the independent run, with per-file hashes.
    evidence = output/'raw'
    evidence.mkdir(exist_ok=True)
    artifacts = {}
    for spec in specs():
        folder = directory/'evidence'/spec['id']
        if not folder.exists():
            continue
        for name in ('result.json', 'before.json', 'after.json', 'lifecycle.json', 'boundary.json', 'worker_failure.json'):
            path = folder/name
            if path.exists():
                target = evidence/(spec['id']+'__'+name)
                target.write_bytes(path.read_bytes())
        for path in sorted(folder.glob('*')):
            artifacts[str(path.relative_to(directory))] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    atomic_json(output/'Artifact_index.json', {'run_directory': str(directory), 'files': artifacts})
    lines = ['# Tier 2 V2 融合算子可行性实验', '',
        '固定 H、train21、seed501；三个预先指定成员对，各评价 WEIGHTED_SUM(0.5/0.5)、MAX、MIN。',
        '全部双成员逐列沿用 V1 min–max，常量列归零；精确同分沿用合法动作原枚举首项。',
        '归一化 SUM 与等权加权和只差正常数比例，故不单列。SELECT/单正项加权保持原始 H 分数。', '',
        '## 完整训练结果', '', '| 策略 | Fitness | 相对 H0 | 相对 H0/H1 等权 |', '|---|---:|---:|---:|']
    for r in rankings:
        lines.append(f"| {r['strategy']} | {r['fitness'] if r['fitness'] is not None else '无效'} | {r['delta_F_vs_H0']} | {r['delta_F_vs_H01_equal']} |")
    lines += ['', '## 同成员对算子比较', '', '| 成员对 | 算子相对等权 | ΔFitness | 胜/负/平 | 不同物理排程实例 |', '|---|---|---:|---|---:|']
    for r in comparisons:
        lines.append(f"| {r['pair']} | {r['operator_vs_WS']} | {r['delta_F']:+.12f} | {r['wins']}/{r['losses']}/{r['ties']} | {r['different_physical_schedules']} |")
    lines += ['', '## 相同状态动作差异', '',
        '每个首解状态保存完整物理状态、全部合法动作和两个 H 的原始评分；离线在同一矩阵上计算三种算子的选择。',
        '分别报告三种来源轨迹和去重并集；并集不是均匀随机状态样本。动作差异只表示局部决策差异，不表示续排收益。', '',
        '| 成员对 | 去重状态数 | MAX≠WS | MIN≠WS | MAX≠MIN |', '|---|---:|---:|---:|---:|']
    for r in diagnostics:
        if r['source'] == 'UNION_DEDUPLICATED':
            lines.append(f"| {r['pair']} | {r['states']} | {r['MAX_diff_WS']} | {r['MIN_diff_WS']} | {r['MAX_diff_MIN']} |")
    lines += ['', '## 行为、成本和证据边界', '',
        f"完整 train21 物理排程行为组：{len(physical_groups)}；分组见 Summary.json，逐实例相同数见 Physical_schedule_pairs.csv。",
        f"正式预留 {costs['reserved_evaluations']} 项；实际首解 {costs['started_first_solves']} 遍，复检 {costs['started_rechecks']} 遍。",
        f"主评价 wall time {costs['primary_wall_seconds']:.3f} 秒；成功实例 CPU {costs['successful_instance_CPU_seconds']:.3f} 秒。",
        f"两遍 H 调用 {costs['H_calls_two_passes']}；API=0，新增诊断求解=0，诊断额外 H 调用=0。",
        '首解包含状态/评分记录开销，复检不记录；跨策略耗时仅为串行本机描述性比较。异常和进程终态见 raw/。',
        'MAX 取两列归一化评分的最大值，往往产生更多顶端同分；结果会依赖被冻结的精确同分规则。',
        '数学上 MAX 的最终动作必为某个成员的首选动作，故可由某个单成员端点实现；不同于等权不等于超出所有加权和的动作能力。',
        'MIN 可选择折衷动作；本报告未仅凭不同于等权就声称超出全部连续权重空间。',
        '训练集已用于研究开发，本轮不作确认性显著性或独立泛化结论；没有读取 validation11/test28。',
        '本轮固定策略均为人工构造，不是 LLM 发现；接口支持可信 U 按状态切换算子/成员/权重，但未扩展模型 AST 或进行演化。', '',
        '## 复现', '', '```bash',
        'PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v2/run.py prepare --run-dir runs/新的独立目录',
        'PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v2/run.py check --run-dir runs/新的独立目录',
        'PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v2/run.py run --run-dir runs/新的独立目录',
        'PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v2/run.py report --run-dir runs/新的独立目录',
        '```', '', 'prepare 固定协议；run 不重复已完成或未知中断的预留任务。所有原始评分矩阵位于 Artifact_index.json 指向的独立 runs 目录。']
    (output/'REPORT_ZH.md').write_text('\n'.join(lines)+'\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'check', 'run', 'report'))
    parser.add_argument('--run-dir', type=Path, default=DEFAULT)
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    if directory.parent != ROOT/'runs':
        raise ValueError('direct child of project runs required')
    if args.stage == 'prepare':
        prepare(directory)
        print('PREPARED', directory)
    elif args.stage == 'check':
        check(directory)
        print('PASS', directory)
    else:
        with RunLock(directory):
            if args.stage == 'run':
                run(directory)
            else:
                result = report(directory)
                print({'phase': result['phase'], 'valid_strategies': result['valid_strategies'], 'costs': result['costs']})
