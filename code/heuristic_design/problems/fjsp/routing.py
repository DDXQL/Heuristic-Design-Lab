"""Pure-route FJSP constructor using the frozen append-only action semantics."""
from dataclasses import dataclass
import math
import numbers
import time

from fjsp_usage.offline_v2 import _SchedulingState, lower_bound_v5
from llm4ad.task.optimization.fjsp_set.scheduler import Schedule, ScheduledOperation, validate_schedule
from heuristic_design.core.constructive_state import History, GROUPS, plain
from heuristic_design.core.routing import route_token
from .common_state import precheck, actions_and_inputs, extract


@dataclass(frozen=True)
class RouteResult:
    schedule: Schedule
    score: float
    trace: tuple
    h_calls: tuple
    observation_seconds: float
    member_sequence: tuple = ()


def construct(instance, heuristics, usage, *, window=10, enabled_groups=tuple(GROUPS), trace=True):
    precheck(instance)
    members = tuple(heuristics)
    if not members or not all(callable(h) for h in members) or not callable(usage):
        raise ValueError('nonempty callable H and U required')
    state = _SchedulingState(instance)
    history = History(state.total_operations, len(members), window)
    rows, calls, observation = [], [0] * len(members), 0.
    for step in range(state.total_operations):
        actions, inputs = actions_and_inputs(state)
        started = time.perf_counter()
        packet = extract(state, history, actions, enabled_groups)
        observation += time.perf_counter() - started
        member = route_token(usage(packet), len(members))
        scores = []
        for args in inputs:
            value = members[member](*args)
            calls[member] += 1
            if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(float(value)):
                raise ValueError('finite real H score required')
            scores.append(float(value))
        winner = max(range(len(actions)), key=lambda j: scores[j])  # exact legacy first max
        chosen = actions[winner]
        j, o, m, start, end = chosen
        partial = max(state.machine_ready)
        delta = (max(partial, end) - partial) / state.time_scale
        if trace:
            rows.append({'step': step, 'state': plain(packet), 'member_id': member,
                         'actions': actions, 'raw_scores': scores, 'chosen': chosen,
                         'committed_delta': delta, 'h_calls': {member: len(actions)}})
        state.scheduled.append(ScheduledOperation(*chosen))
        state.cursors[j] += 1
        state.job_ready[j] = end
        state.machine_ready[m] = end
        state.selected_members.append(member)
        history.commit(member, delta)
    schedule = Schedule(tuple(state.scheduled), max(state.machine_ready))
    validate_schedule(instance, schedule)
    return RouteResult(schedule, -schedule.makespan / lower_bound_v5(instance),
                       tuple(rows), tuple(calls), observation, tuple(state.selected_members))
