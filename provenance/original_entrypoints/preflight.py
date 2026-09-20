"""Deterministic hand-written checks before any FJSP LLM call."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from llm4ad.task.optimization.fjsp_set import (
    FJSPSetEvaluation, construct_schedule, load_instance, validate_schedule,
)


def shortest_processing_time(processing_time, remaining_work, remaining_operations,
                             job_ready_time, machine_ready_time, earliest_start,
                             earliest_finish):
    return -processing_time


def earliest_finish_time(processing_time, remaining_work, remaining_operations,
                         job_ready_time, machine_ready_time, earliest_start,
                         earliest_finish):
    return -earliest_finish


def most_remaining_work(processing_time, remaining_work, remaining_operations,
                        job_ready_time, machine_ready_time, earliest_start,
                        earliest_finish):
    return remaining_work


BASELINES = {
    'SPT': shortest_processing_time,
    'EFT': earliest_finish_time,
    'MWKR': most_remaining_work,
}


def read_split(split_path: Path, data_root: Path) -> tuple[dict, dict[str, list[Path]]]:
    split = json.loads(split_path.read_text(encoding='utf-8'))
    names = [split['sanity']] + [name for part in ('train', 'validation', 'test')
                                 for name in split[part]]
    if len(names) != len(set(names)):
        raise ValueError('split contains duplicate instance names')
    paths = {part: [data_root / name for name in split[part]]
             for part in ('train', 'validation', 'test')}
    paths['sanity'] = [data_root / split['sanity']]
    for group in paths.values():
        for path in group:
            if not path.is_file():
                raise FileNotFoundError(path)
    if not paths['train'] or not paths['validation'] or not paths['test']:
        raise ValueError('train/validation/test must all be nonempty')
    return split, paths


def run_preflight(data_root: Path, split_path: Path) -> dict:
    split, paths = read_split(split_path, data_root)
    sanity = load_instance(paths['sanity'][0])
    if sanity.operation_count != 3 or sanity.lower_bound != 4:
        raise AssertionError('the known sample instance changed')

    sample_results = {}
    for name, rule in BASELINES.items():
        schedule = construct_schedule(sanity, rule)
        validate_schedule(sanity, schedule)
        sample_results[name] = {
            'makespan': schedule.makespan,
            'score': FJSPSetEvaluation.score_makespan(sanity, schedule.makespan),
            'schedule': [vars(entry) for entry in schedule.operations],
        }
    if sample_results['EFT']['makespan'] != 4 or sample_results['SPT']['makespan'] != 6:
        raise AssertionError('known sample baseline makespans changed')
    if not sample_results['EFT']['score'] > sample_results['SPT']['score']:
        raise AssertionError('higher score must mean lower makespan')

    evaluation = FJSPSetEvaluation(paths['train'])
    training_results = {}
    for name, rule in BASELINES.items():
        outcomes = []
        for path, instance in zip(paths['train'], evaluation.instances):
            schedule, score = evaluation.evaluate_instance(instance, rule)
            outcomes.append({'instance': path.name, 'makespan': schedule.makespan,
                             'lower_bound': instance.lower_bound, 'score': score})
        vector = evaluation.evaluate(rule)
        if len(vector) != len(paths['train']) or not all(math.isfinite(x) for x in vector):
            raise AssertionError('training scores must be finite and aligned')
        if vector != [outcome['score'] for outcome in outcomes]:
            raise AssertionError('batch and single-instance scores disagree')
        training_results[name] = {'score_vector': vector, 'instances': outcomes}

    return {
        'split': {part: [path.name for path in group] for part, group in paths.items()},
        'source_note': split['source'],
        'sanity': {'instance': paths['sanity'][0].name, 'lower_bound': sanity.lower_bound,
                   'baselines': sample_results},
        'training_baselines': training_results,
        'checks': ['known sample makespans', 'schedule feasibility',
                   'score direction', 'single/batch equality', 'finite aligned vectors'],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path,
                        default=Path(__file__).resolve().parents[3].parent / '2.4.4/_pdata/fjsp')
    parser.add_argument('--split', type=Path, default=Path(__file__).with_name('split.json'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = run_preflight(args.data_dir, args.split)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            raise FileExistsError(args.output)
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'sanity_makespans': {name: data['makespan']
                                         for name, data in result['sanity']['baselines'].items()},
                      'training_vectors': {name: data['score_vector']
                                           for name, data in result['training_baselines'].items()},
                      'checks': result['checks']}, indent=2))


if __name__ == '__main__':
    main()
