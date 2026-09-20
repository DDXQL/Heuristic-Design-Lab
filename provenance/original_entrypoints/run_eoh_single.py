"""Run EoH for one general FJSP priority rule under a frozen protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import shlex
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from llm4ad.base import TextFunctionProgramConverter
from llm4ad.method.eoh import EoH, EoHProfiler
from llm4ad.task.optimization.fjsp_set import FJSPSetEvaluation
from llm4ad.tools.llm.llm_api_https import HttpsApi

from preflight import read_split, run_preflight


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = Path(__file__).with_name('single_rule_config.json')


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: object) -> None:
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def verified_config(path: Path, *, require_api: bool = False) -> tuple[dict, str]:
    expected = path.with_suffix('.sha256').read_text().strip()
    actual = sha256(path)
    if expected != actual:
        raise ValueError('single-rule config SHA256 mismatch')
    config = json.loads(path.read_text())
    base = ROOT / config['base_fjsp_config']
    if sha256(base) != config['base_fjsp_config_sha256']:
        raise ValueError('base FJSP config changed')
    for name, expected_hash in config['source_sha256'].items():
        if sha256(ROOT / name) != expected_hash:
            raise ValueError(f'source hash mismatch: {name}')
    data_root = Path(config['data_root'])
    for name in config['split']['train'] + config['split']['validation']:
        if sha256(data_root / name) != config['data_file_sha256'][name]:
            raise ValueError(f'data hash mismatch: {name}')
    comparison = ROOT / config['comparison']['eohs_rule']
    if sha256(comparison) != config['comparison']['eohs_rule_sha256']:
        raise ValueError('EoH-S comparison rule changed')
    if require_api:
        if os.getenv('EOHS_MODEL') != config['model']:
            raise ValueError('EOHS_MODEL differs from frozen model')
        if not os.getenv('EOHS_API_HOST') or not os.getenv('EOHS_API_KEY'):
            raise ValueError('local API environment is incomplete')
    return config, actual


def collect_samples(run_dir: Path, expected_length: int) -> list[dict]:
    records = []
    for path in sorted((run_dir / 'samples').glob('samples_*.json')):
        if path.name == 'samples_best.json':
            continue
        for item in json.loads(path.read_text()):
            score, vector = item.get('score'), item.get('score_list')
            valid = (isinstance(score, (int, float)) and not isinstance(score, bool)
                     and math.isfinite(score) and isinstance(vector, list)
                     and len(vector) == expected_length
                     and all(isinstance(value, (int, float)) and math.isfinite(value)
                             for value in vector))
            records.append({'sample_order': item['sample_order'], 'valid': valid,
                            'training_mean_score': score if valid else None,
                            'training_score_vector': vector if valid else None,
                            'sample_log': str(path.relative_to(run_dir)),
                            'function': item.get('function')})
    return sorted(records, key=lambda item: item['sample_order'])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--stage', choices=('smoke', 'formal'), required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    config, config_hash = verified_config(args.config, require_api=True)
    budget = config['stages'][args.stage]
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    data_root = Path(config['data_root'])

    split_copy = run_dir / 'split.json'
    write_json(split_copy, config['split'])
    preflight = run_preflight(data_root, split_copy)
    write_json(run_dir / 'preflight.json', preflight)
    paths = read_split(split_copy, data_root)[1]
    run_config = {
        'experiment': config['experiment'], 'stage': args.stage,
        'single_rule_config_sha256': config_hash,
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                            text=True).strip(),
        'git_status_before_run': subprocess.check_output(['git', 'status', '--short'],
                                                         cwd=ROOT, text=True).strip(),
        'python': sys.version.split()[0], 'numpy': np.__version__,
        'platform': platform.platform(), 'model': config['model'],
        'budget': budget, 'training_instance_order': config['split']['train'],
        'validation_instance_order': config['split']['validation'],
        'test_evaluated': False,
        'command': 'PYTHONPATH=code ' + shlex.join(['.venv/bin/python', *sys.argv]),
    }
    write_json(run_dir / 'run_config.json', run_config)
    (run_dir / 'single_rule_config.json').write_bytes(args.config.read_bytes())
    (run_dir / 'single_rule_config.sha256').write_text(config_hash + '\n')

    random.seed(budget['seed'])
    np.random.seed(budget['seed'] % (2 ** 32))
    evaluation = FJSPSetEvaluation(paths['train'],
                                   timeout_seconds=budget['timeout_seconds'])
    host = os.getenv('EOHS_API_HOST')
    key = os.environ.pop('EOHS_API_KEY', None)
    model = os.getenv('EOHS_MODEL')
    options = {'thinking': {'type': 'disabled'}} if host == 'api.deepseek.com' else {}
    llm = HttpsApi(host=host, key=key, model=model, timeout=60, **options)
    del key
    method = EoH(
        llm=llm, evaluation=evaluation,
        profiler=EoHProfiler(log_dir=str(run_dir), log_style='simple',
                             create_random_path=False, evaluation_name='FJSP',
                             method_name='EoH-single'),
        max_sample_nums=budget['max_sample_nums'],
        max_generations=budget['max_generations'], pop_size=budget['pop_size'],
        num_samplers=budget['num_samplers'], num_evaluators=budget['num_evaluators'],
        debug_mode=budget['debug_mode'])
    start = time.perf_counter()
    method.run()
    generation_seconds = time.perf_counter() - start

    samples = collect_samples(run_dir, len(paths['train']))
    population = [item for item in method._population.population
                  if isinstance(item.score, (int, float)) and math.isfinite(item.score)]
    if method._tot_sample_nums != budget['max_sample_nums'] or len(samples) != budget['max_sample_nums']:
        raise RuntimeError(f'incomplete budget: method={method._tot_sample_nums}, logs={len(samples)}, '
                           f'expected={budget["max_sample_nums"]}')
    if len(population) != budget['pop_size']:
        raise RuntimeError('final population size differs from frozen pop_size')
    export = run_dir / 'final_population'
    export.mkdir()
    manifest = []
    for index, function in enumerate(population):
        program = TextFunctionProgramConverter.function_to_program(function,
                                                                    method._template_program)
        if program is None:
            raise ValueError('failed to reconstruct final program')
        source = str(program)
        source_path = export / f'candidate_{index}.py'
        source_path.write_text(source, encoding='utf-8')
        matching = [item for item in samples if item['function'] == str(function)]
        manifest.append({'population_index': index, 'source_file': source_path.name,
                         'source_sha256': sha256(source_path),
                         'training_mean_score': float(function.score),
                         'training_score_vector': list(function.score_list),
                         'sample_order': matching[-1]['sample_order'] if matching else None,
                         'algorithm': function.algorithm})
    write_json(export / 'manifest.json', {'stage': args.stage,
                                          'population_size': len(manifest),
                                          'members': manifest})
    invalid = [item['sample_order'] for item in samples if not item['valid']]
    result = {'status': 'completed', 'stage': args.stage,
              'sample_count': method._tot_sample_nums,
              'valid_candidate_count': len(samples) - len(invalid),
              'invalid_candidate_count': len(invalid),
              'invalid_candidate_rate': len(invalid) / len(samples),
              'invalid_sample_orders': invalid,
              'final_generation': method._population.generation,
              'final_population_size': len(population),
              'generation_runtime_seconds': generation_seconds,
              'samples': [{key: value for key, value in item.items() if key != 'function'}
                          for item in samples],
              'test_evaluated': False}
    write_json(run_dir / 'generation_result.json', result)
    print(json.dumps({key: result[key] for key in
                      ('stage', 'sample_count', 'invalid_candidate_count',
                       'final_generation', 'final_population_size',
                       'generation_runtime_seconds')}, indent=2))


if __name__ == '__main__':
    main()
