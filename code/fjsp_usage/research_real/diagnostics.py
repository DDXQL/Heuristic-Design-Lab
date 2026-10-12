"""Local result summaries, never feedback to the model or selection rules."""

from collections import Counter
import math
from statistics import fmean


def member_usage(selected_members, size):
    if type(size) is not int or size < 2:
        raise ValueError('member count must be an integer >= 2')
    if any(type(k) is not int or not 0 <= k < size for k in selected_members):
        raise ValueError('invalid recorded member id')
    counts = Counter(selected_members)
    switches = sum(a != b for a, b in zip(selected_members, selected_members[1:]))
    transitions = max(0, len(selected_members)-1)
    return {'steps': len(selected_members), 'counts': [counts[i] for i in range(size)],
            'switches': switches, 'transitions': transitions,
            'switch_rate': switches/transitions if transitions else 0.0,
            'note': 'diagnostic only; more switching is not better'}


def h_complementarity(rows, names):
    """Whole-instance envelope, explicitly NOT a state-level oracle."""
    vectors = [row['scores'] for row in rows]
    if (len(rows) < 2 or not names or any(len(v) != len(names) or
            any(type(x) not in (int, float) or not math.isfinite(x) for x in v) for v in vectors)):
        raise ValueError('at least two complete finite training vectors required')
    envelope = [max(v[i] for v in vectors) for i in range(len(names))]
    best_single = max(fmean(v) for v in vectors)
    contribution = []
    for k, row in enumerate(rows):
        others = [max(v[i] for j, v in enumerate(vectors) if j != k) for i in range(len(names))]
        contribution.append({'member_id': row.get('member_id', k), 'candidate_id': row['id'],
            'mean_score': fmean(vectors[k]),
            'tied_best_instances': sum(x == y for x, y in zip(vectors[k], envelope)),
            'strictly_best_instances': sum(x > y for x, y in zip(vectors[k], others)),
            'leave_one_out_mean_gain': fmean(a-b for a, b in zip(envelope, others))})
    return {'training_files': list(names), 'score_matrix': vectors,
            'best_fixed_member_mean': best_single, 'whole_instance_envelope_mean': fmean(envelope),
            'envelope_gain_over_best_fixed_member': fmean(envelope)-best_single,
            'members': contribution,
            'note': 'train diagnostic requiring one whole solve per h; not a U performance bound or state label; zero gain is retained'}


def training_curve(state, initial_rows):
    """Include failed/duplicate slots on x-axis; shared init is a separate cost."""
    fitness = {row['id']: row['fitness'] for row in initial_rows}
    best = max(fitness.values()) if fitness else None
    curve = [{'evolution_attempts': 0, 'best_train_fitness': best}]
    better, compared, unavailable = 0, 0, []
    for slot, attempt in enumerate(state['attempts'], 1):
        if attempt['status'] == 'valid':
            cached = state['evaluations'].get(attempt['id'])
            if not cached or not cached['result'].get('valid'):
                raise ValueError('valid attempt missing valid evaluation evidence')
            value = cached['result']['fitness']
            fitness[attempt['id']] = value
            best = value if best is None else max(best, value)
            parents = attempt['parents']
            if parents and all(p in fitness for p in parents):
                compared += 1
                better += value > max(fitness[p] for p in parents)
            elif parents:
                unavailable.append(attempt['id'])
        curve.append({'evolution_attempts': slot, 'best_train_fitness': best,
                      'candidate_status': attempt['status']})
    return {'curve': curve, 'valid_children_with_parent_scores': compared,
            'children_strictly_better_than_all_parents': better,
            'parent_comparison_unavailable': unavailable,
            'note': 'x-axis includes every evolution attempt, including failure/duplicate; shared initial generation excluded'}


def fixed_h_comparisons(entries, seeds, fixed_result, arms):
    reports = {}
    for arm in arms:
        differences, excluded = [], []
        for seed in seeds:
            row = next(r for r in entries if r['seed'] == seed and r['arm'] == arm)
            result = row.get('test_result')
            if result and result['valid'] and fixed_result and fixed_result['valid']:
                differences.append({'seed': seed, 'difference': result['fitness']-fixed_result['fitness']})
            else:
                excluded.append(seed)
        reports[arm] = {'planned_repeats': len(seeds), 'actual_comparisons': len(differences),
            'differences': differences, 'mean_difference': fmean(d['difference'] for d in differences) if differences else None,
            'excluded_seeds': excluded,
            'note': 'positive means U has better mean normalized score; one common validation-selected fixed h, not independent random references'}
    return reports
