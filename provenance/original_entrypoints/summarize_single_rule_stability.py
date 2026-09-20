"""Create the fixed three-seed Tier1 single-rule stability summary."""

from __future__ import annotations

import hashlib
import json
import shutil
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / 'logs/fjsp_tier1_single_rule/stability_3seeds'
RUNS = [
    (2026092002, ROOT / 'logs/fjsp_tier1_single_rule/formal01',
     ROOT / 'examples/training/fjsp_set/single_rule_config.json', 0),
    (2026092003, ROOT / 'logs/fjsp_tier1_single_rule/formal_seed_2026092003',
     ROOT / 'examples/training/fjsp_set/single_rule_seed_2026092003.json', 0),
    (2026092004, ROOT / 'logs/fjsp_tier1_single_rule/formal_seed_2026092004',
     ROOT / 'examples/training/fjsp_set/single_rule_seed_2026092004.json', 1),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def distribution(values: list[float]) -> dict:
    return {'values': values, 'mean': statistics.fmean(values),
            'sample_standard_deviation': statistics.stdev(values),
            'median': statistics.median(values),
            'minimum': min(values), 'maximum': max(values),
            'range_width': max(values) - min(values)}


def comparison_row(evaluation: dict, partition: str) -> dict:
    section = evaluation['comparison'][partition]
    return {
        'methods': {name: {'mean_score': value['mean_score'],
                           'feasible_rate': value['feasible_rate'],
                           'total_runtime_seconds': value['total_runtime_seconds']}
                    for name, value in section['methods'].items()},
        'selected_vs': section['selected_vs'],
        'worst_groups': section['worst_groups'],
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=False)
    runs = []
    loaded = []
    for seed, run_dir, config_path, retries in RUNS:
        config_hash = sha256(config_path)
        if config_path.with_suffix('.sha256').read_text().strip() != config_hash:
            raise ValueError(f'config SHA mismatch for seed {seed}')
        generation = json.loads((run_dir / 'generation_result.json').read_text())
        evaluation = json.loads((run_dir / 'evaluation_result.json').read_text())
        selection = json.loads((run_dir / 'selection.json').read_text())
        run_config = json.loads((run_dir / 'run_config.json').read_text())
        if run_config['budget']['seed'] != seed:
            raise ValueError(f'run seed mismatch for {seed}')
        if generation['test_evaluated'] or evaluation['test_evaluated'] or selection['test_evaluated']:
            raise ValueError('test data was evaluated in a stability run')
        selected = run_dir / 'selected_rule.py'
        if sha256(selected) != selection['source_sha256']:
            raise ValueError(f'selected source changed for seed {seed}')
        copied = OUTPUT / f'selected_rule_seed_{seed}.py'
        shutil.copyfile(selected, copied)
        evaluation_runtime = sum(
            result['total_runtime_seconds']
            for partition in ('train', 'validation')
            for result in evaluation['final_population_evaluation'][partition].values()
        ) + sum(
            result['total_runtime_seconds']
            for partition in ('train', 'validation')
            for result in evaluation['comparison'][partition]['methods'].values()
        )
        item = {
            'seed': seed, 'run_dir': str(run_dir.relative_to(ROOT)),
            'config': str(config_path.relative_to(ROOT)), 'config_sha256': config_hash,
            'selected_population_index': selection['population_index'],
            'selected_rule': str(selected.relative_to(ROOT)),
            'selected_rule_sha256': selection['source_sha256'],
            'valid_candidates': generation['valid_candidate_count'],
            'invalid_candidates': generation['invalid_candidate_count'],
            'invalid_candidate_rate': generation['invalid_candidate_rate'],
            'evaluated_llm_candidates': generation['sample_count'],
            'observed_transport_retry_requests': retries,
            'generation_runtime_seconds': generation['generation_runtime_seconds'],
            'recorded_evaluation_runtime_seconds': evaluation_runtime,
            'recorded_total_runtime_seconds': generation['generation_runtime_seconds'] + evaluation_runtime,
            'train': comparison_row(evaluation, 'train'),
            'validation': comparison_row(evaluation, 'validation'),
        }
        runs.append(item)
        loaded.append((seed, evaluation))

    metrics = {}
    paths = {
        'train_mean_score': lambda run: run['train']['methods']['selected_EoH']['mean_score'],
        'validation_mean_score': lambda run: run['validation']['methods']['selected_EoH']['mean_score'],
        'train_score_gap_vs_EFT': lambda run: run['train']['selected_vs']['EFT']['mean_score_difference'],
        'validation_score_gap_vs_EFT': lambda run: run['validation']['selected_vs']['EFT']['mean_score_difference'],
        'train_relative_makespan_improvement_vs_EFT': lambda run: run['train']['selected_vs']['EFT']['mean_relative_makespan_improvement'],
        'validation_relative_makespan_improvement_vs_EFT': lambda run: run['validation']['selected_vs']['EFT']['mean_relative_makespan_improvement'],
        'generation_runtime_seconds': lambda run: run['generation_runtime_seconds'],
        'recorded_total_runtime_seconds': lambda run: run['recorded_total_runtime_seconds'],
    }
    for name, getter in paths.items():
        metrics[name] = distribution([getter(run) for run in runs])

    per_instance = {}
    per_instance_paired = {}
    group_summary = {}
    for partition in ('train', 'validation'):
        first = loaded[0][1]['comparison'][partition]
        instance_rows = []
        paired_rows = []
        for index, name in enumerate(first['instance_order']):
            seed_rows = []
            paired_seed_rows = []
            for seed, evaluation in loaded:
                methods = evaluation['comparison'][partition]['methods']
                selected = methods['selected_EoH']['instances'][index]
                eft = methods['EFT']['instances'][index]
                outcome = ('win' if selected['makespan'] < eft['makespan'] else
                           'loss' if selected['makespan'] > eft['makespan'] else 'tie')
                seed_rows.append({'seed': seed, 'selected_makespan': selected['makespan'],
                                  'EFT_makespan': eft['makespan'],
                                  'selected_score': selected['score'], 'EFT_score': eft['score'],
                                  'score_difference': selected['score'] - eft['score'],
                                  'relative_makespan_improvement':
                                      (eft['makespan'] - selected['makespan']) / eft['makespan'],
                                  'outcome': outcome})
                method_values = {
                    method: {
                        'makespan': values['instances'][index]['makespan'],
                        'score': values['instances'][index]['score'],
                        'feasible': values['instances'][index]['feasible'],
                    }
                    for method, values in methods.items()
                }
                comparisons = {}
                for baseline in ('EFT', 'SPT', 'MWKR', 'EoHS_heuristic_0'):
                    base = method_values[baseline]
                    comparisons[baseline] = {
                        'score_difference': selected['score'] - base['score'],
                        'relative_makespan_improvement':
                            (base['makespan'] - selected['makespan']) / base['makespan'],
                        'outcome': ('win' if selected['makespan'] < base['makespan'] else
                                    'loss' if selected['makespan'] > base['makespan'] else 'tie'),
                    }
                paired_seed_rows.append({
                    'seed': seed,
                    'methods': method_values,
                    'selected_vs': comparisons,
                })
            instance_rows.append({
                'instance': name, 'jobs': first['methods']['selected_EoH']['instances'][index]['jobs'],
                'machines': first['methods']['selected_EoH']['instances'][index]['machines'],
                'seeds': seed_rows,
                'aggregate': {
                    'mean_selected_score': statistics.fmean(x['selected_score'] for x in seed_rows),
                    'mean_score_difference': statistics.fmean(x['score_difference'] for x in seed_rows),
                    'mean_relative_makespan_improvement': statistics.fmean(
                        x['relative_makespan_improvement'] for x in seed_rows),
                    'wins_ties_losses': [sum(x['outcome'] == outcome for x in seed_rows)
                                         for outcome in ('win', 'tie', 'loss')],
                }})
            paired_rows.append({
                'instance': name,
                'jobs': first['methods']['selected_EoH']['instances'][index]['jobs'],
                'machines': first['methods']['selected_EoH']['instances'][index]['machines'],
                'seeds': paired_seed_rows,
            })
        per_instance[partition] = instance_rows
        per_instance_paired[partition] = paired_rows
        labels = first['by_jobs_x_machines'].keys()
        groups = {}
        for label in labels:
            seed_rows = []
            for seed, evaluation in loaded:
                group = evaluation['comparison'][partition]['by_jobs_x_machines'][label]
                selected = group['methods']['selected_EoH']
                eft = group['methods']['EFT']
                seed_rows.append({'seed': seed, 'instance_count': selected['count'],
                                  'selected_mean_score': selected['mean_score'],
                                  'EFT_mean_score': eft['mean_score'],
                                  'score_difference': group['selected_vs']['EFT']['mean_score_difference'],
                                  'relative_makespan_improvement': group['selected_vs']['EFT']['mean_relative_makespan_improvement'],
                                  'wins_ties_losses': group['selected_vs']['EFT']['wins_ties_losses']})
            groups[label] = {'seeds': seed_rows,
                             'aggregate': {
                                 'mean_selected_score': statistics.fmean(x['selected_mean_score'] for x in seed_rows),
                                 'sample_standard_deviation_selected_score': statistics.stdev(x['selected_mean_score'] for x in seed_rows),
                                 'mean_score_difference_vs_EFT': statistics.fmean(x['score_difference'] for x in seed_rows),
                                 'mean_relative_makespan_improvement_vs_EFT': statistics.fmean(x['relative_makespan_improvement'] for x in seed_rows),
                                 'wins_ties_losses': [sum(x['wins_ties_losses'][i] for x in seed_rows)
                                                      for i in range(3)]}}
        group_summary[partition] = groups

    eft_validation = runs[0]['validation']['methods']['EFT']['mean_score']
    summary = {
        'status': 'completed',
        'protocol_sha256': sha256(ROOT / 'examples/training/fjsp_set/single_rule_stability_config.json'),
        'test_evaluated': False,
        'runs': runs,
        'validation_runs_better_than_EFT': sum(
            run['validation']['methods']['selected_EoH']['mean_score'] > eft_validation
            for run in runs),
        'validation_run_count': len(runs), 'EFT_validation_mean_score': eft_validation,
        'cross_seed_distributions': metrics,
        'candidate_counts': {
            'evaluated': sum(run['evaluated_llm_candidates'] for run in runs),
            'valid': sum(run['valid_candidates'] for run in runs),
            'invalid': sum(run['invalid_candidates'] for run in runs),
            'invalid_rate': sum(run['invalid_candidates'] for run in runs) /
                            sum(run['evaluated_llm_candidates'] for run in runs)},
        'llm_calls': {
            'framework_recorded_evaluated_candidate_calls': sum(
                run['evaluated_llm_candidates'] for run in runs),
            'observed_failed_transport_retry_requests': sum(
                run['observed_transport_retry_requests'] for run in runs),
            'minimum_http_request_attempts': sum(run['evaluated_llm_candidates'] +
                                                 run['observed_transport_retry_requests']
                                                 for run in runs),
            'limitation': 'raw HTTP attempts and parse failures were not instrumented; the exact transport-level call count cannot be recovered'},
        'runtime': {
            'generation_seconds': sum(run['generation_runtime_seconds'] for run in runs),
            'recorded_evaluation_seconds': sum(run['recorded_evaluation_runtime_seconds'] for run in runs),
            'recorded_total_seconds': sum(run['recorded_total_runtime_seconds'] for run in runs)},
        'per_instance_vs_EFT': per_instance,
        'per_instance_paired_all_baselines': per_instance_paired,
        'by_jobs_x_machines_vs_EFT': group_summary,
    }
    out = OUTPUT / 'stability_summary.json'
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    checksums = [f'{sha256(path)}  {path.name}' for path in sorted(OUTPUT.iterdir())]
    (OUTPUT / 'checksums.sha256').write_text('\n'.join(checksums) + '\n')
    print(json.dumps({'output': str(out),
                      'validation_better_than_EFT': summary['validation_runs_better_than_EFT'],
                      'candidate_counts': summary['candidate_counts'],
                      'recorded_total_seconds': summary['runtime']['recorded_total_seconds']}, indent=2))


if __name__ == '__main__':
    main()
