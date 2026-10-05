#!/usr/bin/env python3
"""Offline interface demonstration only: hand-written U and demo H = (EFT, SPT)."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'code'))

from experiments.tier1.preflight import earliest_finish_time, shortest_processing_time
from fjsp_usage.offline_v1 import EXPERIMENT_VERSION, StateSummary, construct_usage_schedule
from llm4ad.task.optimization.fjsp_set import load_instance

# Reuse the existing hand-written baselines, not the frozen generated rules.
# This tuple is an interface demonstration, NOT an EoH-S-generated heuristic set.
DEMO_H = (earliest_finish_time, shortest_processing_time)
DEMO_H_NAMES = ('EFT', 'SPT')


def constant_u(state: StateSummary) -> int:
    """Always choose demo member 0 (EFT)."""
    return 0


def state_u(state: StateSummary) -> int:
    """Choose EFT when machine ready times differ, otherwise choose SPT.

    This deterministic illustration has no learned parameters or quality claim.
    """
    ready = state.machine_ready_times
    return 0 if max(ready) > min(ready) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', type=Path, default=Path(__file__).with_name('tiny.fjsp'))
    parser.add_argument('--selector', choices=('constant', 'state', 'both'), default='both')
    args = parser.parse_args()
    instance = load_instance(args.instance)
    selectors = {'constant': constant_u, 'state': state_u}
    results = {}
    for name, selector in selectors.items():
        if args.selector not in ('both', name):
            continue
        result = construct_usage_schedule(instance, DEMO_H, selector)
        results[name] = {
            'selected_members': result.selected_members,
            'feasible': True,  # constructor has run the independent Tier1 validator
            'makespan': result.schedule.makespan,
            'score': result.score,
            'operations': [asdict(op) for op in result.schedule.operations],
        }
    print(json.dumps({
        'experiment_version': EXPERIMENT_VERSION,
        'heuristic_set_status': 'hand-written interface demo; not an EoH-S-generated set',
        'H': dict(enumerate(DEMO_H_NAMES)),
        'instance': instance.name,
        'lower_bound': instance.lower_bound,
        'llm_called': False,
        'evolution_run': False,
        'results': results,
    }, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
