"""Research executor with opt-in, bounded traces, using the unchanged V5 state.

The loop mirrors offline_v2 and frozen Tier1 action/tie semantics. This new
experiment version adds observation without changing those existing executors.
"""

import math
import numbers
from typing import Sequence
from llm4ad.task.optimization.fjsp_set import FJSPInstance
from llm4ad.task.optimization.fjsp_set.scheduler import Schedule, ScheduledOperation, validate_schedule
from fjsp_usage.offline_v2 import (
    Priority, Selector, UsageResult, InvalidSelectionError, _SchedulingState, lower_bound_v5,
)


def construct_usage_schedule(instance: FJSPInstance, heuristics: Sequence[Priority],
                             selector: Selector, *, trace=None, max_actions=1000) -> UsageResult:
    """One U call, then only H[k] scores all legal actions, then one commit.

    Invalid IDs/exceptions fail without retry or fallback. Terminal states never
    call U. Functions must be trusted, deterministic and free of mutable state.
    """
    members = tuple(heuristics)
    if type(max_actions) is not int or max_actions < 0:
        raise ValueError('max_actions must be a nonnegative built-in int')
    if not members or not all(callable(member) for member in members):
        raise ValueError('H must be a nonempty sequence of callable rules')
    if not callable(selector):
        raise ValueError('U must be callable')
    state = _SchedulingState(instance)
    for step in range(state.total_operations):
        try:
            features = state.features()
            member_id = selector(*features)
        except Exception as exc:
            raise InvalidSelectionError(f'U raised an exception at step {step}') from exc
        if type(member_id) is not int or not 0 <= member_id < len(members):
            raise InvalidSelectionError(
                f'U must return a built-in int in [0, {len(members)}) at step {step}')
        priority = members[member_id]
        best_score = -math.inf
        best_action = None
        actions = []
        action_count = 0
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
                action_count += 1
                if trace is not None and len(actions) < max_actions:
                    actions.append({'job': job_index, 'operation': operation_index,
                                    'machine': machine, 'start': start, 'end': end,
                                    'processing_time': duration, 'score': score})
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
        if trace is not None:
            trace({'step': step, 'state': dict(features._asdict()),
                   'member_id': member_id, 'action_count': action_count,
                   'actions': actions, 'actions_truncated': len(actions) < action_count,
                   'chosen': dict(zip(('job', 'operation', 'machine', 'start', 'end'), best_action))})

    schedule = Schedule(tuple(state.scheduled), max(entry.end for entry in state.scheduled))
    validate_schedule(instance, schedule)
    lower_bound = lower_bound_v5(instance)
    return UsageResult(schedule, tuple(state.selected_members), lower_bound,
                       -float(schedule.makespan) / lower_bound)
