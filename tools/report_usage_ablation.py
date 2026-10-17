#!/usr/bin/env python3
"""Derived tables only; no evaluator, provider, dataset parser or billing access."""
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/usage-v22-mechanism-ablation-301-20261017-v1'
ARCHIVE = ROOT / 'docs/usage-space/real-gpt61-301'


def read(path):
    return json.loads(path.read_text())


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def table(name, rows):
    with (OUT / name).open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def outcome(left, right):
    return 'win' if left < right else 'loss' if left > right else 'tie'


def paired(left, right):
    right = {r['file']: r for r in right}
    counts = Counter(outcome(r['makespan'], right[r['file']]['makespan']) for r in left)
    return {k: counts[k] for k in ('win', 'loss', 'tie')}


def costs(result):
    rows = result['instances']
    failed = not result['valid']
    return {'valid': result['valid'], 'fitness': result['fitness'], 'completed_instances': len(rows),
        'failed_instance': result.get('failed_instance'),
        'single_solve_seconds': sum(r['single_solve_seconds'] for r in rows),
        'recheck_seconds': sum(r['deterministic_recheck_seconds'] for r in rows),
        'primary_wall_seconds': result['primary_evaluation_seconds'],
        'primary_h_calls': sum(sum(r['single_h_calls']) for r in rows) if rows and 'single_h_calls' in rows[0] else None,
        'recheck_h_calls': sum(sum(r['deterministic_recheck_h_calls']) for r in rows) if rows and 'deterministic_recheck_h_calls' in rows[0] else None,
        'failed_instance_h_calls_unknown': failed,
        'h_scoring_seconds': sum(r.get('selected_h_scoring_seconds', 0.) for r in rows) if rows and 'selected_h_scoring_seconds' in rows[0] else None,
        'combination_processing_seconds': sum(r.get('combination_processing_seconds', 0.) for r in rows) if rows and 'combination_processing_seconds' in rows[0] else None,
        'cost_scope': 'complete primary/recheck' if not failed else 'certified success prefix; failed instance incomplete cost unknown'}


def behavior(result):
    supports, modes, dominants, values = Counter(), Counter(), Counter(), {}
    support_switches = 0
    for row in result['instances']:
        previous = None
        for mode, support, weights, dominant in row.get('decision_support_weights', []):
            key = ','.join(map(str, support))
            supports[key] += 1
            modes[mode] += 1
            dominants[dominant] += 1
            if previous is not None and previous != key:
                support_switches += 1
            previous = key
            for member, weight in zip(support, weights):
                values.setdefault(member, []).append(weight)
    return {'support_counts': dict(supports), 'mode_counts': dict(modes),
            'dominant_counts': dict(dominants), 'within_instance_support_switches': support_switches,
            'normalized_positive_weight_ranges': {i: [min(v), max(v)] for i, v in values.items()},
            'steps': sum(modes.values()), 'action_counterfactual_trace': 'not recorded; unknown'}


def main():
    plan, complete = read(OUT / 'Plan.json'), read(OUT / 'Evaluation_complete.json')
    for path, expected in plan['pins'].items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
            raise ValueError(f'original evidence changed: {path}')
    names, bounds = plan['names'], complete['bounds']
    fixed = read(OUT / 'Fixed_H_reused.json')
    for h in fixed:
        result = h['result']
        assert result['valid'] and [r['file'] for r in result['instances']] == names
        for row in result['instances']:
            assert math.isclose(row['lower_bound'], bounds[row['file']], rel_tol=1e-12)
            assert math.isclose(row['score'], -row['makespan']/bounds[row['file']], rel_tol=1e-12)
        assert math.isclose(result['fitness'], fmean(r['score'] for r in result['instances']), rel_tol=1e-12)
    best_h = max(fixed, key=lambda x: x['result']['fitness'])
    assert best_h['id'] == 'H0'
    h0 = {r['file']: r for r in best_h['result']['instances']}
    index = read(ARCHIVE / 'All_generated_candidates.json')
    manifest = read(ARCHIVE / 'Final_evidence_manifest.json')
    for relative in ('All_generated_candidates.json', 'All_instance_results.csv'):
        assert hashlib.sha256((ARCHIVE / relative).read_bytes()).hexdigest() == manifest['archive_files_sha256'][relative]
    all_rows = list(csv.DictReader((ARCHIVE / 'All_instance_results.csv').open()))
    valid = [c for c in index if c['profile']['complete_train_valid']]
    all_comparisons, u_summary, profiles = [], [], []
    for candidate in valid:
        rows = [r for r in all_rows if r['candidate_id'] == candidate['id']]
        assert len(rows) == 21 and [r['file'] for r in rows] == names
        for row in rows:
            assert row['candidate_complete_train_valid'] == 'True'
            row['makespan'], row['score'] = int(row['makespan']), float(row['score'])
            assert math.isclose(float(row['lower_bound']), bounds[row['file']], rel_tol=1e-12)
            assert math.isclose(row['score'], -row['makespan']/bounds[row['file']], rel_tol=1e-12)
        fitness = fmean(r['score'] for r in rows)
        assert math.isclose(fitness, candidate['fitness'], rel_tol=1e-12)
        p = candidate['profile']
        form = ('dynamic-pair MIX' if p['dual_support_varies_on_train'] else 'fixed-pair MIX') if p['MIX_steps'] else ('score SELECT' if p['selection_vectors_not_one_hot'] else 'one-hot SELECT')
        wins = paired(rows, best_h['result']['instances'])
        u_summary.append({'candidate_id': candidate['id'], 'form': form, 'fitness': fitness,
            'fitness_minus_H0': fitness-best_h['result']['fitness'], **wins,
            **{f'{status}_instances': ';'.join(r['file'] for r in rows if outcome(r['makespan'], h0[r['file']]['makespan']) == status) for status in ('win', 'loss', 'tie')}})
        profiles.append({'id': candidate['id'], 'form': form, **p})
        for h in fixed:
            for row, reference in zip(rows, h['result']['instances']):
                assert row['file'] == reference['file']
                all_comparisons.append({'candidate_id': candidate['id'], 'fixed_h': h['id'],
                    'file': row['file'], 'U_makespan': row['makespan'], 'H_makespan': reference['makespan'],
                    'Cmax_U_minus_H': row['makespan']-reference['makespan'],
                    'score_U_minus_H': row['score']-reference['score'], 'outcome_U': outcome(row['makespan'], reference['makespan'])})
    assert len(valid) == 20
    table('All_U_vs_fixed_H.csv', all_comparisons)
    table('All_U_vs_H0.csv', [r for r in all_comparisons if r['fixed_h'] == 'H0'])
    table('All_U_vs_H0_summary.csv', u_summary)
    all_summary = []
    for candidate in valid:
        for h in fixed:
            rows = [r for r in all_comparisons if r['candidate_id'] == candidate['id'] and r['fixed_h'] == h['id']]
            counts = Counter(r['outcome_U'] for r in rows)
            all_summary.append({'candidate_id': candidate['id'], 'fixed_h': h['id'],
                'fitness_U_minus_H': fmean(r['score_U_minus_H'] for r in rows),
                **{k: counts[k] for k in ('win', 'loss', 'tie')}})
    table('All_U_vs_fixed_H_summary.csv', all_summary)
    write('Existing_valid_U_profiles.json', profiles)
    versions, result_rows, summaries, usages = {}, [], [], {}
    for version in plan['versions']:
        key = version['id']
        result = read(OUT / 'results' / f'{key}.json')
        assert [r['file'] for r in result['instances']] == names[:len(result['instances'])]
        for row in result['instances']:
            assert row['feasible'] is True
            assert math.isclose(row['lower_bound'], bounds[row['file']], rel_tol=1e-12)
            assert math.isclose(row['score'], -row['makespan']/bounds[row['file']], rel_tol=1e-12)
            assert row['single_h_calls'] == row['deterministic_recheck_h_calls']
            assert len(row['decision_support_weights']) == row['member_usage']['steps']
        if result['valid']:
            assert len(result['instances']) == 21
            assert math.isclose(result['fitness'], fmean(r['score'] for r in result['instances']), rel_tol=1e-12)
        else:
            assert result['fitness'] is None
        versions[key] = result
        if version['reused']:
            archived = [r for r in all_rows if r['candidate_id'] == version['original_id']]
            assert [(r['file'], int(r['makespan'])) for r in archived] == [(r['file'], r['makespan']) for r in result['instances']]
        usages[key] = behavior(result)
        summaries.append({'id': key, 'kind': version['variant'], 'reused': version['reused'],
            **costs(result), **paired(result['instances'], best_h['result']['instances'])})
    for h in fixed:
        summaries.append({'id': h['id'], 'kind': 'fixed h', 'reused': True,
            **costs(h['result']), **paired(h['result']['instances'], best_h['result']['instances'])})
        versions[h['id']] = h['result']
    for key, result in versions.items():
        by_name = {r['file']: r for r in result['instances']}
        for name in names:
            row = by_name.get(name, {})
            result_rows.append({'id': key, 'candidate_complete_valid': result['valid'], 'file': name,
                'instance_status': 'complete' if row else 'failed' if name == result.get('failed_instance') else 'not_reached',
                'makespan': row.get('makespan'), 'lower_bound': bounds[name], 'score': row.get('score'),
                'Cmax_minus_H0': row['makespan']-h0[name]['makespan'] if row else None,
                'outcome_vs_H0': outcome(row['makespan'], h0[name]['makespan']) if row else None,
                'single_solve_seconds': row.get('single_solve_seconds'),
                'recheck_seconds': row.get('deterministic_recheck_seconds'),
                'single_h_calls': sum(row['single_h_calls']) if 'single_h_calls' in row else None,
                'recheck_h_calls': sum(row['deterministic_recheck_h_calls']) if 'deterministic_recheck_h_calls' in row else None})
    table('Ablation_and_fixed_H_summary.csv', summaries)
    table('Ablation_and_fixed_H_instances.csv', result_rows)
    pairs = []
    for prefix in ('B5', 'B3'):
        original = versions[f'{prefix}_original']
        for other in ('equal', 'winner'):
            result = versions[f'{prefix}_{other}']
            shared = min(len(result['instances']), len(original['instances']))
            pairs.append({'original': f'{prefix}_original', 'intervention': other,
                'both_complete_valid': original['valid'] and result['valid'],
                'intervention_fitness_minus_original': result['fitness']-original['fitness'] if result['valid'] and original['valid'] else None,
                'comparison_scope': 'complete train21' if result['valid'] and original['valid'] else 'success prefix only; not full fitness',
                **paired(result['instances'][:shared], original['instances'][:shared])})
    table('Paired_interventions.csv', pairs)
    write('Ablation_behavior.json', usages)
    timeout_rows = []
    for key, item in read(OUT / 'Historical_timeouts.json').items():
        result = item['result']
        timeout_rows.append({'id': key, 'failed_instance': result['failed_instance'], 'error_type': result['error_type'],
            **costs(result), 'timeout_observed_seconds': result['parent_observed_instance_seconds'],
            'existing_prefix_diagnostic_seconds': result.get('diagnostic_evaluation_seconds'),
            'failed_instance_single_solve_seconds': None, 'failed_instance_recheck_seconds': None})
    table('Historical_timeout_costs.csv', timeout_rows)
    write('Analysis_checks.json', {'all_20_valid_U_checked': True, 'all_10_fixed_h_checked': True,
        'common_train21_and_unrounded_LB': True, 'best_fixed_h': best_h['id'],
        'H0_fitness': best_h['result']['fitness'], 'U_better_than_H0_mean': sum(r['fitness_minus_H0'] > 0 for r in u_summary),
        'original_pins_unchanged': True, 'new_full_evaluations': 4,
        'new_model_requests': 0, 'holdout_file_contents_opened': False})
    print(json.dumps({'checks': read(OUT / 'Analysis_checks.json'), 'pairs': pairs,
          'ablation': summaries[:6]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
