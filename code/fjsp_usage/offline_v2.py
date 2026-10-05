"""Versioned V5 seven-scalar U interface for trusted, offline demonstrations.

The frozen Tier1 constructor and offline_v1 remain unchanged. This constructor
mirrors Tier1 action semantics; its state inputs and unrounded LB follow V5.
This is an interface boundary, not a sandbox for generated Python programs.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Callable, NamedTuple, Sequence

from llm4ad.task.optimization.fjsp_set import FJSPInstance
from llm4ad.task.optimization.fjsp_set.scheduler import (
    Schedule, ScheduledOperation, validate_schedule,
)

EXPERIMENT_VERSION = 'Tier2-Offline-V5-Interface-v2'
Priority = Callable[[float, float, int, float, float, float, float], float]
Selector = Callable[[float, float, float, float, float, float, int], int]


class StateFeatures(NamedTuple):
    """Internal immutable snapshot, unpacked into seven scalar arguments to U."""

    progress: float
    candidate_pair_ratio: float
    remaining_work_mean: float
    remaining_work_std: float
    machine_ready_mean: float
    machine_ready_std: float
    previous_heuristic: int


class InvalidSelectionError(ValueError):
    """U failed or returned something other than an in-range built-in int."""


@dataclass(frozen=True)
class UsageResult:
    schedule: Schedule
    selected_members: tuple[int, ...]
    lower_bound: float
    score: float


def lower_bound_v5(instance: FJSPInstance) -> float:
    """V5 literal LB: max(longest shortest-work job, total shortest work / M).

    Unlike frozen Tier1's integer LB, do not ceil the total-load term.
    """
    work = [sum(min(p for _, p in op.alternatives) for op in job)
            for job in instance.jobs]
    return max(float(max(work)), sum(work) / instance.machine_count)


class _SchedulingState:
    """Full state stays in the executor; U receives only features() scalars."""

    def __init__(self, instance: FJSPInstance):
        self.instance = instance
        self.total_operations = instance.operation_count
        self.time_scale = sum(max(p for _, p in op.alternatives)
                              for job in instance.jobs for op in job)
        self.candidate_bound = sum(max(len(op.alternatives) for op in job)
                                   for job in instance.jobs)
        self.cursors = [0] * len(instance.jobs)
        self.job_ready = [0] * len(instance.jobs)
        self.machine_ready = [0] * instance.machine_count
        self.remaining_work = []
        for job in instance.jobs:
            suffix = [0] * (len(job) + 1)
            for index in range(len(job) - 1, -1, -1):
                suffix[index] = suffix[index + 1] + min(p for _, p in job[index].alternatives)
            self.remaining_work.append(tuple(suffix))
        self.scheduled: list[ScheduledOperation] = []
        self.selected_members: list[int] = []

    def features(self) -> StateFeatures:
        if len(self.scheduled) == self.total_operations:
            raise ValueError('terminal state has no U invocation')
        active = [j for j, job in enumerate(self.instance.jobs)
                  if self.cursors[j] < len(job)]
        work = [self.remaining_work[j][self.cursors[j]] / self.time_scale for j in active]
        ready = [value / self.time_scale for value in self.machine_ready]
        candidate_count = sum(len(self.instance.jobs[j][self.cursors[j]].alternatives)
                              for j in active)
        return StateFeatures(
            len(self.scheduled) / self.total_operations,
            candidate_count / self.candidate_bound,
            fmean(work), pstdev(work), fmean(ready), pstdev(ready),
            self.selected_members[-1] if self.selected_members else -1,
        )


def construct_usage_schedule(instance: FJSPInstance, heuristics: Sequence[Priority],
                             selector: Selector) -> UsageResult:
    """One U call, then only H[k] scores all legal actions, then one commit.

    Invalid IDs/exceptions fail without retry or fallback. Terminal states never
    call U. Functions must be trusted, deterministic and free of mutable state.
    """
    members = tuple(heuristics)
    if not members or not all(callable(member) for member in members):
        raise ValueError('H must be a nonempty sequence of callable rules')
    if not callable(selector):
        raise ValueError('U must be callable')
    state = _SchedulingState(instance)
    for step in range(state.total_operations):
        try:
            member_id = selector(*state.features())
        except Exception as exc:
            raise InvalidSelectionError(f'U raised an exception at step {step}') from exc
        if type(member_id) is not int or not 0 <= member_id < len(members):
            raise InvalidSelectionError(
                f'U must return a built-in int in [0, {len(members)}) at step {step}')
        priority = members[member_id]
        best_score = -math.inf
        best_action = None
        # Same seven unnormalised action features and stable enumeration as Tier1.
        for job_index, job in enumerate(instance.jobs):
            operation_index = state.cursors[job_index]
            if operation_index == len(job):
                continue
            for machine, duration in job[operation_index].alternatives:
                start = max(state.job_ready[job_index], state.machine_ready[machine])
                end = start + duration
                raw_score = priority(
                    float(duration), float(state.remaining_work[job_index][operation_index]),
                    len(job) - operation_index, float(state.job_ready[job_index]),
                    float(state.machine_ready[machine]), float(start), float(end),
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
        state.scheduled.append(ScheduledOperation(*best_action))
        state.cursors[job_index] += 1
        state.job_ready[job_index] = end
        state.machine_ready[machine] = end
        state.selected_members.append(member_id)

    schedule = Schedule(tuple(state.scheduled), max(entry.end for entry in state.scheduled))
    validate_schedule(instance, schedule)
    lower_bound = lower_bound_v5(instance)
    return UsageResult(schedule, tuple(state.selected_members), lower_bound,
                       -float(schedule.makespan) / lower_bound)
