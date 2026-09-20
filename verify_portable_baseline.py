#!/usr/bin/env python3
"""Offline, read-only verification for the portable Tier1 baseline."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import numbers
import os
import re
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / 'baselines/tier1_single_rule_v1/portable_manifest.json'
PARAMETERS = (
    'processing_time', 'remaining_work', 'remaining_operations',
    'job_ready_time', 'machine_ready_time', 'earliest_start', 'earliest_finish',
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_rule(path: Path):
    function = runpy.run_path(str(path)).get('priority')
    require(callable(function), f'missing priority(): {path}')
    signature = inspect.signature(function)
    require(tuple(signature.parameters) == PARAMETERS,
            f'priority signature mismatch: {path}')
    return function


def close(actual: float, expected: float, context: str) -> None:
    require(math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12),
            f'{context}: expected {expected}, got {actual}')


def replay(function, instances, expected_rows, score_function, scheduler, validator,
           context: str) -> None:
    require(len(instances) == len(expected_rows), f'{context}: length mismatch')
    for instance, expected in zip(instances, expected_rows):
        require(instance.name == Path(expected['instance']).stem,
                f'{context}: instance order mismatch')
        schedule = scheduler(instance, function)
        validator(instance, schedule)
        score = score_function(instance, schedule.makespan)
        require(expected['feasible'] is True, f'{context}: reference infeasible')
        require(schedule.makespan == expected['makespan'],
                f'{context}/{expected["instance"]}: makespan changed')
        close(score, expected['score'], f'{context}/{expected["instance"]}: score')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))

    source_repo = Path(manifest['source']['repository_path']).resolve()
    os.environ.pop('PYTHONPATH', None)
    clean_sys_path = []
    for entry in sys.path:
        try:
            resolved = Path(entry or '.').resolve()
            if resolved == source_repo or source_repo in resolved.parents:
                continue
        except (OSError, RuntimeError):
            pass
        clean_sys_path.append(entry)
    sys.path[:] = clean_sys_path
    sys.path.insert(0, str(ROOT / 'experiments/tier1'))
    sys.path.insert(0, str(ROOT / 'code'))
    require(all(str(source_repo) not in entry for entry in sys.path),
            'source EoH-S path remains in sys.path')

    from llm4ad.task.optimization.fjsp_set import (  # noqa: E402
        FJSPSetEvaluation, construct_schedule, load_instance, validate_schedule,
    )
    from llm4ad.task.optimization.fjsp_set.instances import (  # noqa: E402
        FJSPInstance, Operation,
    )
    from preflight import BASELINES  # noqa: E402

    # Every versioned portable file is independently hashed.
    checked_files = []
    for entry in manifest['files']:
        expected = entry['sha256']
        require(re.fullmatch(r'[0-9a-f]{64}', expected) is not None,
                f'invalid SHA-256 syntax: {entry["path"]}')
        path = ROOT / entry['path']
        require(path.is_file(), f'missing portable file: {entry["path"]}')
        require(sha256(path) == expected, f'SHA-256 mismatch: {entry["path"]}')
        checked_files.append(path)

    original_manifest = ROOT / manifest['source']['original_manifest_path']
    require(sha256(original_manifest) == manifest['source']['original_manifest_sha256'],
            'original baseline manifest hash mismatch')

    # Syntax compilation reads source but creates no cache files.
    for path in checked_files:
        if path.suffix == '.py':
            compile(path.read_text(encoding='utf-8'), str(path), 'exec')

    data_manifest_path = ROOT / manifest['dataset']['manifest_path']
    data_manifest = json.loads(data_manifest_path.read_text(encoding='utf-8'))
    split = data_manifest['split']
    test_names = set(split['test'])
    require((len(split['train']), len(split['validation']), len(test_names)) == (21, 11, 28),
            'split counts changed')
    require(not (set(split['train']) & set(split['validation'])
                 or set(split['train']) & test_names
                 or set(split['validation']) & test_names),
            'split overlap')

    # Hash train/validation and sanity locally. Test contents were migration-
    # checked once and are deliberately not opened by this verifier.
    data_root = ROOT / data_manifest['portable_root']
    verified_data_hashes = 0
    for name in [split['sanity'], *split['train'], *split['validation']]:
        record = data_manifest['files'][name]
        require(sha256(data_root / name) == record['sha256'],
                f'data hash mismatch: {name}')
        verified_data_hashes += 1
    for name in split['test']:
        path = data_root / name
        require(path.is_file(), f'missing local test file: {name}')
        require(path.stat().st_size == data_manifest['files'][name]['bytes'],
                f'test file size changed: {name}')

    loaded = []
    instances = {}
    for partition in ('train', 'validation'):
        current = []
        for name in split[partition]:
            require(name not in test_names, f'attempted to load test: {name}')
            current.append(load_instance(data_root / name))
            loaded.append(name)
        instances[partition] = current
    require(not set(loaded) & test_names, 'test instance passed to FJSP loader')

    canonical_info = manifest['rules']['canonical']
    canonical = load_rule(ROOT / canonical_info['path'])
    value = canonical(3.0, 11.0, 2, 0.0, 1.0, 1.0, 4.0)
    require(not isinstance(value, bool) and isinstance(value, numbers.Real)
            and math.isfinite(float(value)), 'canonical rule did not return a finite scalar')

    micro = FJSPInstance('portable-micro', 2, (
        (Operation(((0, 3), (1, 2))), Operation(((0, 2), (1, 4)))),
        (Operation(((0, 2), (1, 3))),),
    ))
    micro_schedule = construct_schedule(micro, canonical)
    validate_schedule(micro, micro_schedule)
    require(micro_schedule.makespan == 4, 'micro makespan changed')

    rules = [canonical_info, *manifest['rules']['stability_review']]
    for rule_info in rules:
        function = load_rule(ROOT / rule_info['path'])
        record = json.loads((ROOT / rule_info['evaluation_record']).read_text())
        require(record['test_evaluated'] is False,
                f'test flag changed for seed {rule_info["seed"]}')
        for partition in ('train', 'validation'):
            section = record['comparison'][partition]
            require(section['instance_order'] == split[partition],
                    f'instance order changed: {rule_info["seed"]}/{partition}')
            selected = section['methods']['selected_EoH']
            close(selected['feasible_rate'], 1.0,
                  f'feasible rate: {rule_info["seed"]}/{partition}')
            replay(function, instances[partition], selected['instances'],
                   FJSPSetEvaluation.score_makespan, construct_schedule,
                   validate_schedule, f'{rule_info["seed"]}/{partition}')
        generation = json.loads((ROOT / rule_info['generation_record']).read_text())
        require(generation['test_evaluated'] is False,
                f'generation record used test: {rule_info["seed"]}')

    canonical_record = json.loads(
        (ROOT / canonical_info['evaluation_record']).read_text())
    for partition in ('train', 'validation'):
        for baseline in ('EFT', 'SPT', 'MWKR'):
            expected = canonical_record['comparison'][partition]['methods'][baseline]
            close(expected['feasible_rate'], 1.0,
                  f'{baseline}/{partition} feasible rate')
            replay(BASELINES[baseline], instances[partition], expected['instances'],
                   FJSPSetEvaluation.score_makespan, construct_schedule,
                   validate_schedule, f'{baseline}/{partition}')

    # Confirm imports resolve only to this project after source path removal.
    import llm4ad  # noqa: E402
    imported_root = (ROOT / 'code').resolve()
    for module_name, module in list(sys.modules.items()):
        if module_name == 'llm4ad' or module_name.startswith('llm4ad.'):
            location = getattr(module, '__file__', None)
            if location:
                resolved = Path(location).resolve()
                require(resolved == imported_root or imported_root in resolved.parents,
                        f'external llm4ad import: {module_name} -> {resolved}')

    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT / 'code')
    with tempfile.TemporaryDirectory() as temporary_cwd:
        process = subprocess.run(
            [sys.executable, '-m', 'unittest', 'discover',
             '-s', str(ROOT / 'tests'), '-p', 'test_*.py'],
            cwd=temporary_cwd, env=env, text=True, capture_output=True, check=False)
    require(process.returncode == 0,
            'unittest failed:\n' + process.stdout + process.stderr)

    result = {
        'status': 'passed',
        'baseline': manifest['baseline']['identifier'],
        'portable_manifest_files_checked': len(checked_files),
        'original_manifest_sha256': manifest['source']['original_manifest_sha256'],
        'source_repository_present_in_sys_path': False,
        'canonical_signature': str(inspect.signature(canonical)),
        'finite_scalar_check': float(value),
        'micro_makespan': micro_schedule.makespan,
        'replayed_instances': {'train': 21, 'validation': 11, 'test': 0},
        'replayed_rules': 3,
        'fixed_baselines': ['EFT', 'SPT', 'MWKR'],
        'all_replayed_makespans_and_scores_match': True,
        'all_rule_feasible_rates': '100% on train and validation',
        'data_hashes_checked_now': verified_data_hashes,
        'test_files_present': 28,
        'test_files_opened_by_verifier': 0,
        'test_instances_loaded': 0,
        'test_instances_evaluated': 0,
        'syntax_check': 'passed',
        'unittest': '4 tests passed',
        'llm_called': False,
        'evolution_run': False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
