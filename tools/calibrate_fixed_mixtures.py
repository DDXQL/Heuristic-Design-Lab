#!/usr/bin/env python3
"""Manual 4-pair x 3-weight train grid, reusing the frozen ablation evaluator."""
import argparse
from dataclasses import asdict
from itertools import combinations
import json
import math
from pathlib import Path
from statistics import fmean

from fjsp_usage.research.candidates import U_ARGS, validate_code
from fjsp_usage.research_real.assets import check_result, check_seal
from fjsp_usage.usage_v2 import VERSION
from tools import usage_mechanism_ablation as common
from tools.report_usage_ablation import costs, outcome, table

ROOT = common.ROOT
OUT = ROOT / 'reports/usage-fixed-pair-weight-grid-20261018-v1'
OLD = common.OUT
PEER = ROOT.parent / 'FJSP-Heuristic-Research-u-single-experiments'
FAIR = PEER / 'runs/single-ID-gpt61-fair-seed201-v2'
LEGACY = PEER / 'runs/single-ID-gpt61-paired-training-20261014-v1'
PAIRS = ((0, 1), (0, 2), (0, 3), (3, 6))
WEIGHTS = ((.25, .75), (.5, .5), (.75, .25))


def grid():
    rows = []
    for a, b in PAIRS:
        for wa, wb in WEIGHTS:
            vector = [0.] * 10
            vector[a], vector[b] = wa, wb
            code = ('def use_heuristics(' + ', '.join(U_ARGS) + '):\n'
                    '    return (1, (' + ', '.join(map(repr, vector)) + '))\n')
            candidate = validate_code(code, description='Manual fixed-pair weight grid',
                interface_version=VERSION, member_count=10)
            rows.append({'id': f'H{a}_H{b}_w{int(100*wa):02d}_{int(100*wb):02d}',
                'pair': [a, b], 'weights': [wa, wb], 'candidate': asdict(candidate),
                'reused': False, 'origin': 'human-specified parameter grid; not LLM evolution'})
    return rows


def peer_finished():
    complete = common.read(FAIR / 'Search_complete.json')
    check_seal(complete, kind='Search_complete', mode='real')
    entries = complete['entries']
    if (len(entries) != 4 or {r['arm'] for r in entries} != {'B0', 'B1', 'B2', 'P'}
            or any(r['status'] != 'completed' for r in entries)
            or common.read(FAIR / 'progress.json')['stage'] != 'SEARCH_COMPLETE'
            or any('lock' in p.name.lower() for p in FAIR.iterdir() if p.is_file())):
        raise ValueError('peer fair batch not complete or run lock present')
    return {'run': str(FAIR), 'search_complete_sha256': common.sha(FAIR / 'Search_complete.json'),
            'entries': [{k: r[k] for k in ('seed', 'arm', 'status')} for r in entries],
            'no_run_lock': True}


def prepare():
    protocol, dataset, frozen, reassessment, members, names = common.inputs()
    dataset.verify('train')
    versions = grid()
    proof = peer_finished()
    OUT.mkdir(parents=True, exist_ok=False)
    (OUT / 'sources').mkdir()
    (OUT / 'results').mkdir()
    fixed = [{'id': f'H{i}', 'source_id': frozen['members'][i]['id'],
              'code_key': members[i].key, 'result': reassessment['rows'][i]['result']}
             for i in (0, 1, 2, 3, 6)]
    common.write(OUT / 'Fixed_H_reused.json', fixed)
    pins = [common.RUN / n for n in ('protocol.json', 'H_frozen.json', 'Conditional_H_reassessment.json')]
    pins += [ROOT / 'data/fjsp_manifest.json', OLD / 'Plan.json', OLD / 'Ablation_and_fixed_H_summary.csv']
    pins += [ROOT / p for p in protocol['implementation']['files']]
    pins += list(dataset.paths['train'])
    for row in versions:
        source = OUT / 'sources' / (row['id'] + '.py')
        source.write_text(row['candidate']['code'])
        row['source_sha256'] = common.sha(source)
        pins.append(source)
    # Only the selected old champion is read; no account/billing files or clients.
    legacy_source = LEGACY / 'candidate_exports/INIT_init_000004.py'
    legacy_candidate = validate_code(legacy_source.read_text(), kind='U')
    checkpoint = common.read(LEGACY / 'r201/INIT/checkpoint.json')
    population_row = next(r for r in checkpoint['population'] if r['id'] == 'INIT/init/000004')
    legacy_result = checkpoint['evaluations']['INIT/init/000004']['result']
    check_result(legacy_result, names)
    if (legacy_candidate.key != population_row['candidate']['key']
            or [r['candidate']['key'] for r in common.read(LEGACY / 'H_frozen.json')['members']]
               != [m.key for m in members]):
        raise ValueError('legacy champion/H identity mismatch')
    common.write(OUT / 'Historical_references.json', {
        'legacy': {'run': str(LEGACY), 'id': 'INIT/init/000004', 'code_key': legacy_candidate.key,
            'source_sha256': common.sha(legacy_source),
            'checkpoint_sha256': common.sha(LEGACY / 'r201/INIT/checkpoint.json'),
            'valid': legacy_result['valid'], 'fitness': legacy_result['fitness'],
            'instances': [{k: v for k, v in r.items() if k in
                ('file', 'makespan', 'lower_bound', 'score', 'single_solve_seconds',
                 'deterministic_recheck_seconds')} for r in legacy_result['instances']]},
        'mixture_ablation_report': str(OLD.relative_to(ROOT)),
        'scope': 'historical references only, no reevaluation or equal-search-budget claim'})
    config = {'version': 'fixed-four-pair-three-weight-training-grid-v1', 'pairs': PAIRS,
        'raw_weights': WEIGHTS, 'manual_parameter_search': True, 'new_model_requests': 0,
        'new_instance_generation': False, 'holdout_access': False, 'instance_timeout': 15,
        'candidates': 12, 'candidate_instance_cap': 252, 'successful_schedule_cap': 504,
        'independent_diagnostic_replay': False, 'peer_completion': proof,
        'physical_schedule_schema': 'operations sorted by (job,operation): [job,operation,machine,start,end], all IDs zero-based; separate commit-sequence hash',
        'evaluation_order': [r['id'] for r in versions]}
    common.write(OUT / 'Config.json', config)
    pins += [OUT / 'Config.json', OUT / 'Fixed_H_reused.json', OUT / 'Historical_references.json',
             Path(__file__).resolve(), ROOT / 'tools/usage_mechanism_ablation.py',
             ROOT / 'tools/report_usage_ablation.py']
    common.write(OUT / 'Plan.json', {'original_run': str(common.RUN.relative_to(ROOT)),
        'names': names, 'versions': versions, 'H_order': [m.key for m in members],
        'new_full_evaluations': 12, 'new_model_requests': 0, 'timeout_seconds': 15,
        'pins': {str(p.relative_to(ROOT)): common.sha(p) for p in pins},
        'score': protocol['fitness'], 'peer_completion': proof})
    print('Frozen 12 manual candidates; five fixed-h evaluations reused; zero solves so far.', flush=True)


def check_ready():
    plan = common.read(OUT / 'Plan.json')
    if peer_finished() != plan['peer_completion']:
        raise ValueError('peer completion identity changed')
    if [(r['id'], r['candidate']['key']) for r in grid()] != [
            (r['id'], r['candidate']['key']) for r in plan['versions']]:
        raise ValueError('grid changed after freeze')


def report():
    plan = common.read(OUT / 'Plan.json')
    complete = common.read(OUT / 'Evaluation_complete.json')
    common.verify_pins(plan)
    fixed = {r['id']: r['result'] for r in common.read(OUT / 'Fixed_H_reused.json')}
    summaries, instances, comparisons, weight_rows = [], [], [], []
    results = {}
    for version in plan['versions']:
        key, (a, b) = version['id'], version['pair']
        result = common.read(OUT / 'results' / f'{key}.json')
        check_result(result, plan['names'])
        for row in result['instances']:
            if (row['physical_schedule_sha256'] != row['recheck_physical_schedule_sha256']
                    or row['single_h_calls'] != row['deterministic_recheck_h_calls']
                    or row['captured_solves'] != 2
                    or row['makespan'] != row['physical_schedule']['makespan']
                    or not math.isclose(row['lower_bound'], complete['bounds'][row['file']], rel_tol=1e-12)):
                raise ValueError('schedule/cost/bound certification failed')
        results[key] = result
        best_member = max((f'H{a}', f'H{b}'), key=lambda h: fixed[h]['fitness'])
        envelope = [{'file': x['file'], 'makespan': min(x['makespan'], y['makespan']),
            'score': max(x['score'], y['score'])} for x, y in zip(fixed[f'H{a}']['instances'], fixed[f'H{b}']['instances'])]
        references = {'H0': fixed['H0']['instances'], 'member_a': fixed[f'H{a}']['instances'],
                      'member_b': fixed[f'H{b}']['instances'], 'pair_envelope': envelope}
        summaries.append({'id': key, 'pair': f'{a},{b}', 'weight_a': version['weights'][0],
            'weight_b': version['weights'][1], **costs(result), 'best_fixed_component': best_member,
            'fitness_minus_H0': result['fitness']-fixed['H0']['fitness'] if result['valid'] else None,
            'fitness_minus_best_component': result['fitness']-fixed[best_member]['fitness'] if result['valid'] else None,
            'fitness_minus_pair_envelope': result['fitness']-fmean(x['score'] for x in envelope) if result['valid'] else None,
            'error_type': result.get('error_type')})
        indexed = {r['file']: r for r in result['instances']}
        for name in plan['names']:
            row = indexed.get(name)
            status = 'complete' if row else 'failed' if name == result.get('failed_instance') else 'not_reached'
            instances.append({'id': key, 'candidate_complete_valid': result['valid'], 'file': name,
                'instance_status': status, 'makespan': row['makespan'] if row else None,
                'lower_bound': complete['bounds'][name], 'score': row['score'] if row else None,
                'single_solve_seconds': row['single_solve_seconds'] if row else None,
                'recheck_seconds': row['deterministic_recheck_seconds'] if row else None,
                'single_h_calls': sum(row['single_h_calls']) if row else None,
                'recheck_h_calls': sum(row['deterministic_recheck_h_calls']) if row else None,
                'physical_schedule_sha256': row['physical_schedule_sha256'] if row else None,
                'commit_sequence_sha256': row['commit_sequence_sha256'] if row else None})
            for label, reference in references.items():
                ref = next(x for x in reference if x['file'] == name)
                comparisons.append({'id': key, 'candidate_complete_valid': result['valid'], 'file': name,
                    'instance_status': status, 'reference': label, 'grid_makespan': row['makespan'] if row else None,
                    'reference_makespan': ref['makespan'], 'Cmax_grid_minus_reference': row['makespan']-ref['makespan'] if row else None,
                    'score_grid_minus_reference': row['score']-ref['score'] if row else None,
                    'outcome_grid': outcome(row['makespan'], ref['makespan']) if row else None})
    for a, b in PAIRS:
        versions = [v for v in plan['versions'] if v['pair'] == [a, b]]
        for x, y in combinations(versions, 2):
            left = {r['file']: r for r in results[x['id']]['instances']}
            right = {r['file']: r for r in results[y['id']]['instances']}
            for name in plan['names']:
                l, r = left.get(name), right.get(name)
                weight_rows.append({'left': x['id'], 'right': y['id'], 'file': name,
                    'both_candidates_complete_valid': results[x['id']]['valid'] and results[y['id']]['valid'],
                    'both_instances_complete': bool(l and r),
                    'same_makespan': l['makespan'] == r['makespan'] if l and r else None,
                    'same_physical_schedule': l['physical_schedule_sha256'] == r['physical_schedule_sha256'] if l and r else None,
                    'same_commit_sequence': l['commit_sequence_sha256'] == r['commit_sequence_sha256'] if l and r else None})
    win_rows = []
    for summary in summaries:
        for label in ('H0', 'member_a', 'member_b', 'pair_envelope'):
            rows = [r for r in comparisons if r['id'] == summary['id'] and r['reference'] == label]
            counts = {k: sum(r['outcome_grid'] == k for r in rows) for k in ('win', 'loss', 'tie')}
            win_rows.append({'id': summary['id'], 'reference': label, 'complete_valid': summary['valid'],
                'scope': 'train21' if summary['valid'] else 'certified success prefix only; no complete fitness',
                **counts, **{k+'_instances': ';'.join(r['file'] for r in rows if r['outcome_grid'] == k) for k in counts}})
    for name, rows in [('Grid_summary.csv', summaries), ('Grid_instances.csv', instances),
        ('Instance_comparisons.csv', comparisons), ('Win_loss_tie.csv', win_rows),
        ('Weight_schedule_comparisons.csv', weight_rows)]:
        table(name, rows, out=OUT)
    valid = [r for r in summaries if r['valid']]
    best = max(valid, key=lambda r: r['fitness']) if valid else None
    common.write(OUT / 'Analysis.json', {'best': best, 'valid_candidates': len(valid),
        'failed_candidates': [r['id'] for r in summaries if not r['valid']],
        'above_H0': [r['id'] for r in valid if r['fitness_minus_H0'] > 0],
        'above_best_fixed_component': [r['id'] for r in valid if r['fitness_minus_best_component'] > 0],
        'summaries': summaries, 'new_model_requests': 0})
    print(json.dumps({'valid': len(valid), 'best': best, 'above_H0': [r['id'] for r in valid if r['fitness_minus_H0'] > 0]}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'evaluate', 'report'))
    args = parser.parse_args()
    if args.stage == 'prepare':
        prepare()
    elif args.stage == 'evaluate':
        check_ready()
        common.run_evaluations(OUT, evaluator=common.evaluate_with_schedules,
            before_candidate=check_ready, keep_decisions=False, result_indent=None)
    else:
        report()
