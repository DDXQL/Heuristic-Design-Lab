"""Tier2-Offline-Prototype-v1: select one heuristic per scheduling step.

This explicit experiment version mirrors Tier1's append-only construction and
seven action features, but adds a state-level selector outside the action loop.
It is not the frozen seven-feature wrapper and does not generate H or U.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from typing import Callable, Sequence

from llm4ad.task.optimization.fjsp_set import FJSPSetEvaluation, FJSPInstance
from llm4ad.task.optimization.fjsp_set.scheduler import (
    Schedule, ScheduledOperation, validate_schedule,
)

EXPERIMENT_VERSION = 'Tier2-Offline-Prototype-v1'
Priority = Callable[[float, float, int, float, float, float, float], float]


@dataclass(frozen=True)
class StateSummary:
    """Immutable pre-decision snapshot for U, never an individual action.

    step counts already scheduled operations (zero-based). Per-job tuples keep
    original job order; completed jobs have zero remaining work/operations.
    candidate_count counts all eligible next-operation/machine pairs.
    """

    step: int
    total_operations: int
    remaining_operations: tuple[int, ...]
    remaining_work: tuple[int, ...]
    job_ready_times: tuple[int, ...]
    machine_ready_times: tuple[int, ...]
    candidate_count: int


Selector = Callable[[StateSummary], int]


class InvalidSelectionError(ValueError):
    """U raised an exception or did not return an in-range built-in int."""


@dataclass(frozen=True)
class UsageResult:
    schedule: Schedule
    selected_members: tuple[int, ...]
    score: float


def construct_usage_schedule(instance: FJSPInstance, heuristics: Sequence[Priority],
                             selector: Selector) -> UsageResult:
    """Call U once, score all legal actions with H[U(state)], then commit one.

    IDs are zero-based, with type(id) is int (bool and numpy integers rejected).
    Invalid selectors fail immediately with no fallback or retry. Rules retain
    Tier1's seven-feature contract and finite real scalar validation.
    """
    members = tuple(heuristics)
    if not members or not all(callable(member) for member in members):
        raise ValueError('H must be a nonempty sequence of callable rules')
    if not callable(selector):
        raise ValueError('U must be callable')

    cursors = [0] * len(instance.jobs)
    job_ready = [0] * len(instance.jobs)
    machine_ready = [0] * instance.machine_count
    # Same definition as Tier1, plus a zero suffix for completed jobs.
    remaining_work = [tuple(sum(min(duration for _, duration in op.alternatives)
                                for op in job[index:]) for index in range(len(job) + 1))
                      for job in instance.jobs]
    scheduled = []
    selected_members = []

    for step in range(instance.operation_count):
        state = StateSummary(
            step=step,
            total_operations=instance.operation_count,
            remaining_operations=tuple(len(job) - cursors[j]
                                       for j, job in enumerate(instance.jobs)),
            remaining_work=tuple(work[cursors[j]] for j, work in enumerate(remaining_work)),
            job_ready_times=tuple(job_ready),
            machine_ready_times=tuple(machine_ready),
            candidate_count=sum(len(job[cursors[j]].alternatives)
                                for j, job in enumerate(instance.jobs) if cursors[j] < len(job)),
        )
        try:
            member_id = selector(state)
        except Exception as exc:
            raise InvalidSelectionError(f'U raised an exception at step {step}') from exc
        if type(member_id) is not int or not 0 <= member_id < len(members):
            raise InvalidSelectionError(
                f'U must return a built-in int in [0, {len(members)}) at step {step}')
        priority = members[member_id]
        selected_members.append(member_id)

        best_score = -math.inf
        best_action = None
        # Keep Tier1's stable enumeration and exact-tie behavior.
        for job_index, job in enumerate(instance.jobs):
            operation_index = cursors[job_index]
            if operation_index == len(job):
                continue
            for machine, duration in job[operation_index].alternatives:
                start = max(job_ready[job_index], machine_ready[machine])
                end = start + duration
                raw_score = priority(
                    float(duration), float(remaining_work[job_index][operation_index]),
                    len(job) - operation_index, float(job_ready[job_index]),
                    float(machine_ready[machine]), float(start), float(end),
                )
                if isinstance(raw_score, bool) or not isinstance(raw_score, numbers.Real):
                    raise ValueError('priority must return a real scalar number')
                try:
                    score = float(raw_score)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError('priority must return a finite scalar number') from exc
                if not math.isfinite(score):
                    raise ValueError('priority returned a non-finite score')
                if score > best_score:
                    best_score = score
                    best_action = (job_index, operation_index, machine, start, end)
        if best_action is None:
            raise ValueError('no schedulable operation-machine pair')
        job_index, operation_index, machine, start, end = best_action
        scheduled.append(ScheduledOperation(job_index, operation_index, machine, start, end))
        cursors[job_index] += 1
        job_ready[job_index] = end
        machine_ready[machine] = end

    schedule = Schedule(tuple(scheduled), max(entry.end for entry in scheduled))
    validate_schedule(instance, schedule)
    return UsageResult(schedule, tuple(selected_members),
                       FJSPSetEvaluation.score_makespan(instance, schedule.makespan))
