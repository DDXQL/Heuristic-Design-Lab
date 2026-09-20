"""Select one final EoH rule on validation and compare it on train/validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import runpy
import shutil
import statistics
import time
from pathlib import Path

from llm4ad.task.optimization.fjsp_set import (
    FJSPSetEvaluation, construct_schedule, load_instance,
)

from preflight import BASELINES
from run_eoh_single import DEFAULT_CONFIG, ROOT, sha256, verified_config, write_json


def evaluate_function(function, names: list[str], data_root: Path) -> dict:
    rows = []
    for name in names:
        instance = load_instance(data_root / name)
        start = time.perf_counter()
        try:
            schedule = construct_schedule(instance, function)
            score = FJSPSetEvaluation.score_makespan(instance, schedule.makespan)
            row = {'instance': name, 'jobs': len(instance.jobs),
                   'machines': instance.machine_count,
                   'operations': instance.operation_count,
                   'lower_bound': instance.lower_bound, 'feasible': True,
                   'makespan': schedule.makespan, 'score': score, 'error': None}
        except Exception as exc:
            row = {'instance': name, 'jobs': len(instance.jobs),
                   'machines': instance.machine_count,
                   'operations': instance.operation_count,
                   'lower_bound': instance.lower_bound, 'feasible': False,
                   'makespan': None, 'score': None,
                   'error': f'{type(exc).__name__}: {str(exc)[:500]}'}
        row['runtime_seconds'] = time.perf_counter() - start
        rows.append(row)
    feasible = [row for row in rows if row['feasible']]
    scores = [row['score'] for row in feasible]
    makespans = [row['makespan'] for row in feasible]
    runtimes = [row['runtime_seconds'] for row in rows]
    return {'count': len(rows), 'feasible_count': len(feasible),
            'feasible_rate': len(feasible) / len(rows),
            'mean_score': statistics.fmean(scores) if scores else None,
            'median_score': statistics.median(scores) if scores else None,
            'mean_makespan': statistics.fmean(makespans) if makespans else None,
            'median_makespan': statistics.median(makespans) if makespans else None,
            'total_runtime_seconds': sum(runtimes), 'instances': rows}


def summarize_rows(rows: list[dict]) -> dict:
    scores = [row['score'] for row in rows if row['feasible']]
    makespans = [row['makespan'] for row in rows if row['feasible']]
    return {'count': len(rows),
            'feasible_rate': len(scores) / len(rows),
            'mean_score': statistics.fmean(scores) if scores else None,
            'median_score': statistics.median(scores) if scores else None,
            'mean_makespan': statistics.fmean(makespans) if makespans else None,
            'median_makespan': statistics.median(makespans) if makespans else None}


def compare(selected: list[dict], reference: list[dict]) -> dict:
    pairs = [(a, b) for a, b in zip(selected, reference)
             if a['feasible'] and b['feasible']]
    wins = sum(a['makespan'] < b['makespan'] for a, b in pairs)
    ties = sum(a['makespan'] == b['makespan'] for a, b in pairs)
    losses = sum(a['makespan'] > b['makespan'] for a, b in pairs)
    score_diffs = [a['score'] - b['score'] for a, b in pairs]
    relative = [(b['makespan'] - a['makespan']) / b['makespan'] for a, b in pairs]
    return {'paired_count': len(pairs), 'wins_ties_losses': [wins, ties, losses],
            'mean_score_difference': statistics.fmean(score_diffs) if pairs else None,
            'median_score_difference': statistics.median(score_diffs) if pairs else None,
            'mean_relative_makespan_improvement': statistics.fmean(relative) if pairs else None,
            'median_relative_makespan_improvement': statistics.median(relative) if pairs else None}


def group_comparison(methods: dict[str, dict], fields: tuple[str, ...]) -> dict:
    labels: dict[str, list[int]] = {}
    selected = methods['selected_EoH']['instances']
    for index, row in enumerate(selected):
        label = 'x'.join(str(row[field]) for field in fields)
        labels.setdefault(label, []).append(index)
    output = {}
    for label, indices in sorted(labels.items()):
        summaries = {name: summarize_rows([result['instances'][i] for i in indices])
                     for name, result in methods.items()}
        comparisons = {name: compare([selected[i] for i in indices],
                                     [result['instances'][i] for i in indices])
                       for name, result in methods.items() if name != 'selected_EoH'}
        output[label] = {'methods': summaries, 'selected_vs': comparisons}
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    config, config_hash = verified_config(args.config)
    run_dir = args.run_dir.resolve()
    output_path = run_dir / 'evaluation_result.json'
    selection_path = run_dir / 'selection.json'
    selected_path = run_dir / 'selected_rule.py'
    if any(path.exists() for path in (output_path, selection_path, selected_path)):
        raise FileExistsError('single-rule evaluation outputs already exist')
    if sha256(run_dir / 'single_rule_config.json') != config_hash:
        raise ValueError('generation run used another single-rule config')
    manifest = json.loads((run_dir / 'final_population/manifest.json').read_text())
    members = manifest['members']
    if len(members) != config['stages'][manifest['stage']]['pop_size']:
        raise ValueError('unexpected final population size')
    data_root = Path(config['data_root'])
    evaluated: dict[str, dict[str, dict]] = {'train': {}, 'validation': {}}
    functions = {}
    for member in members:
        source = run_dir / 'final_population' / member['source_file']
        if sha256(source) != member['source_sha256']:
            raise ValueError(f'candidate source changed: {source.name}')
        functions[member['population_index']] = runpy.run_path(str(source))['priority']
        for partition in ('train', 'validation'):
            evaluated[partition][f"candidate_{member['population_index']}"] = evaluate_function(
                functions[member['population_index']], config['split'][partition], data_root)
    valid = []
    for member in members:
        result = evaluated['validation'][f"candidate_{member['population_index']}"]
        if result['feasible_count'] == len(config['split']['validation']) and math.isfinite(result['mean_score']):
            valid.append((result['mean_score'], -member['population_index'], member))
    if not valid:
        raise RuntimeError('no final-population candidate is valid on all validation instances')
    selected = max(valid)[2]
    selected_source = run_dir / 'final_population' / selected['source_file']
    shutil.copyfile(selected_source, selected_path)
    selection = {'single_rule_config_sha256': config_hash,
                 'candidate_pool': config['selection']['candidate_pool'],
                 'criterion': config['selection']['criterion'],
                 'tie_break': config['selection']['tie_break'],
                 'population_index': selected['population_index'],
                 'source_file': selected['source_file'],
                 'source_sha256': sha256(selected_source),
                 'validation_mean_score': evaluated['validation'][
                     f"candidate_{selected['population_index']}"]['mean_score'],
                 'test_evaluated': False}
    write_json(selection_path, selection)

    eohs_source = ROOT / config['comparison']['eohs_rule']
    reference_functions = {name: BASELINES[name] for name in ('EFT', 'SPT', 'MWKR')}
    reference_functions['EoHS_heuristic_0'] = runpy.run_path(str(eohs_source))['priority']
    selected_function = functions[selected['population_index']]
    comparisons = {}
    for partition in ('train', 'validation'):
        methods = {'selected_EoH': evaluate_function(selected_function,
                                                      config['split'][partition], data_root)}
        for name, function in reference_functions.items():
            methods[name] = evaluate_function(function, config['split'][partition], data_root)
        selected_rows = methods['selected_EoH']['instances']
        pairwise = {name: compare(selected_rows, result['instances'])
                    for name, result in methods.items() if name != 'selected_EoH'}
        exact = group_comparison(methods, ('jobs', 'machines'))
        jobs = group_comparison(methods, ('jobs',))
        machines = group_comparison(methods, ('machines',))
        absolute_worst = min(exact, key=lambda label:
                             exact[label]['methods']['selected_EoH']['mean_score'])
        eft_gap_worst = min(exact, key=lambda label:
                            exact[label]['selected_vs']['EFT']['mean_score_difference'])
        comparisons[partition] = {
            'instance_order': config['split'][partition], 'methods': methods,
            'selected_vs': pairwise, 'by_jobs_x_machines': exact,
            'by_jobs': jobs, 'by_machines': machines,
            'worst_groups': {
                'minimum_selected_mean_score': absolute_worst,
                'minimum_mean_score_gap_vs_EFT': eft_gap_worst,
            }}
    result = {'status': 'completed', 'stage': manifest['stage'],
              'single_rule_config_sha256': config_hash,
              'final_population_evaluation': evaluated,
              'selection': selection, 'comparison': comparisons,
              'test_evaluated': False}
    write_json(output_path, result)
    print(json.dumps({'selected_population_index': selected['population_index'],
                      'validation_mean_score': selection['validation_mean_score'],
                      'train_mean_score': comparisons['train']['methods']['selected_EoH']['mean_score'],
                      'test_evaluated': False}, indent=2))


if __name__ == '__main__':
    main()
