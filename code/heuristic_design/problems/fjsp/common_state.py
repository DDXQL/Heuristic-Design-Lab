"""Read-only legal action arithmetic shared by new observation and execution."""
import math
from heuristic_design.core.constructive_state import observe, GROUPS


def precheck(instance):
    if (type(instance.machine_count) is not int or instance.machine_count < 1
            or not instance.jobs or any(not job for job in instance.jobs)):
        raise ValueError('nonempty jobs and positive machines required')
    for job in instance.jobs:
        for op in job:
            if not op.alternatives or len({m for m, _ in op.alternatives}) != len(op.alternatives):
                raise ValueError('nonempty unique alternatives required')
            for m, p in op.alternatives:
                if (type(m) is not int or not 0 <= m < instance.machine_count
                        or type(p) is not int or p <= 0):
                    raise ValueError('positive integer processing times and valid machines required')
    scale = sum(max(p for _, p in op.alternatives) for job in instance.jobs for op in job)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('invalid FJSP cost scale')


def actions_and_inputs(state):
    actions, inputs = [], []
    for j, job in enumerate(state.instance.jobs):
        o = state.cursors[j]
        if o == len(job):
            continue
        for machine, duration in job[o].alternatives:
            start = max(state.job_ready[j], state.machine_ready[machine])
            end = start + duration
            actions.append((j, o, machine, start, end))
            inputs.append((float(duration), float(state.remaining_work[j][o]), len(job)-o,
                           float(state.job_ready[j]), float(state.machine_ready[machine]),
                           float(start), float(end)))
    return actions, inputs


def extract(state, history, actions, enabled_groups=tuple(GROUPS)):
    partial = max(state.machine_ready)
    return observe('fjsp', history=history, action_bound=state.candidate_bound,
                   partial_cost=partial, scale=state.time_scale,
                   action_deltas=(max(partial, a[4]) - partial for a in actions),
                   enabled_groups=enabled_groups)
