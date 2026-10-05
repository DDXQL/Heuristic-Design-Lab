#!/usr/bin/env python3
"""Evaluate hand-written demo U on the fixed train split only; no learning/LLM."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'code'))

from experiments.tier1.preflight import earliest_finish_time, shortest_processing_time
from fjsp_usage.offline_v2 import EXPERIMENT_VERSION
from fjsp_usage.training_v2 import TrainingEvaluation

DEMO_H = (earliest_finish_time, shortest_processing_time)
DEMO_H_NAMES = ('EFT', 'SPT')


def constant_u(progress: float, candidate_pair_ratio: float,
               remaining_work_mean: float, remaining_work_std: float,
               machine_ready_mean: float, machine_ready_std: float,
               previous_heuristic: int) -> int:
    """Always select EFT; all seven state arguments still use the V5 contract."""
    return 0


def state_u(progress: float, candidate_pair_ratio: float,
            remaining_work_mean: float, remaining_work_std: float,
            machine_ready_mean: float, machine_ready_std: float,
            previous_heuristic: int) -> int:
    """EFT if machine ends differ, otherwise SPT; no quality claim or learning."""
    return 0 if machine_ready_std > 0.0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selector', choices=('constant', 'state', 'both'), default='both')
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'runs/tier2_offline_v2/training_demo.json')
    args = parser.parse_args()
    evaluation = TrainingEvaluation(ROOT / 'data/fjsp_manifest.json', project_root=ROOT)
    selectors = {'constant': constant_u, 'state': state_u}
    results = {name: asdict(evaluation.evaluate(DEMO_H, selector))
               for name, selector in selectors.items() if args.selector in ('both', name)}
    source_paths = (
        'code/fjsp_usage/offline_v2.py', 'code/fjsp_usage/training_v2.py',
        'experiments/tier2/offline_v2/run_training_demo.py',
        'experiments/tier2/offline_v2/manifest.json',
        'experiments/tier1/preflight.py',
        'code/llm4ad/task/optimization/fjsp_set/instances.py',
        'code/llm4ad/task/optimization/fjsp_set/scheduler.py',
    )
    report = {
        'experiment_version': EXPERIMENT_VERSION,
        'status': 'offline interface and batch demonstration; not research results',
        'split': 'train',
        'H': dict(enumerate(DEMO_H_NAMES)),
        'H_status': 'fixed hand-written demo; not an EoH-S-generated set',
        'U_status': 'hand-written deterministic functions; no training or selection',
        'lower_bound_protocol': 'V5 literal max(max_job_min_work, total_min_work / M), no ceil',
        'dataset_manifest_sha256': evaluation.manifest_sha256,
        'training_instance_sha256': evaluation.training_hashes,
        'source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source_paths},
        'validation_evaluated': False,
        'test_evaluated': False,
        'llm_called': False,
        'evolution_run': False,
        'results': results,
    }
    output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding='utf-8')
    print(output, end='')
    if not all(result['valid'] for result in results.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
