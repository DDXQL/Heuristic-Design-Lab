"""Deterministic append-only FJSP constructor and independent feasibility check."""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from typing import Callable

from .instances import FJSPInstance


@dataclass(frozen=True)
class ScheduledOperation:
    job: int
    operation: int
    machine: int
    start: int
    end: int


@dataclass(frozen=True)
class Schedule:
    operations: tuple[ScheduledOperation, ...]
    makespan: int


def construct_schedule(instance: FJSPInstance, priority: Callable[..., float]) -> Schedule:
    """Select the highest-scoring ready operation/machine pair at each step."""
    cursors = [0] * len(instance.jobs)
    job_ready = [0] * len(instance.jobs)
    machine_ready = [0] * instance.machine_count
    remaining_work = [tuple(sum(min(duration for _, duration in op.alternatives)
                                for op in job[index:]) for index in range(len(job)))
                      for job in instance.jobs]
    scheduled = []

    for _ in range(instance.operation_count):
        best_score = -math.inf
        best_action = None
        # Stable order is the tie rule: lower job index, then lower machine index.
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
    return schedule


def validate_schedule(instance: FJSPInstance, schedule: Schedule) -> None:
    """Recheck every operation, precedence edge, machine interval and makespan."""
    if len(schedule.operations) != instance.operation_count:
        raise ValueError('schedule does not contain every operation')
    seen = set()
    job_operations = [[] for _ in instance.jobs]
    machine_operations = [[] for _ in range(instance.machine_count)]
    for entry in schedule.operations:
        if not 0 <= entry.job < len(instance.jobs):
            raise ValueError('invalid job index')
        if not 0 <= entry.operation < len(instance.jobs[entry.job]):
            raise ValueError('invalid operation index')
        key = (entry.job, entry.operation)
        if key in seen:
            raise ValueError('operation scheduled twice')
        seen.add(key)
        alternatives = dict(instance.jobs[entry.job][entry.operation].alternatives)
        if entry.machine not in alternatives or entry.start < 0:
            raise ValueError('invalid machine assignment or start time')
        if entry.end - entry.start != alternatives[entry.machine]:
            raise ValueError('processing duration mismatch')
        job_operations[entry.job].append(entry)
        machine_operations[entry.machine].append(entry)

    for entries in job_operations:
        entries.sort(key=lambda entry: entry.operation)
        for previous, current in zip(entries, entries[1:]):
            if current.start < previous.end:
                raise ValueError('job precedence violation')
    for entries in machine_operations:
        entries.sort(key=lambda entry: entry.start)
        for previous, current in zip(entries, entries[1:]):
            if current.start < previous.end:
                raise ValueError('machine overlap')
    if schedule.makespan != max(entry.end for entry in schedule.operations):
        raise ValueError('makespan mismatch')
