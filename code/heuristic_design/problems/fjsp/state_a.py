"""Scheme A sensors for the existing append-only FJSP executor."""
from heuristic_design.core.state_a import observe
from .common_state import precheck, actions_and_inputs


class Sensors:
    def __init__(self, instance):
        precheck(instance)
        self.instance = instance
        self.pmax = max(p for job in instance.jobs for op in job for _, p in op.alternatives)
        self.time_bound = sum(max(p for _, p in op.alternatives) for job in instance.jobs for op in job)
        self.decisions = instance.operation_count

    def extract(self, state, history, actions):
        if (state.instance is not self.instance or history.decisions != self.decisions
                or history.count != sum(state.cursors) or history.count != len(state.scheduled)):
            raise ValueError('FJSP state/history mismatch')
        partial = max(state.machine_ready)
        return observe('fjsp', history=history,
            demands=(state.remaining_work[j][o] / self.time_bound
                     for j, o in enumerate(state.cursors) if o < len(self.instance.jobs[j])),
            commitments=(x / self.time_bound for x in state.machine_ready),
            action_deltas=((max(partial, a[4]) - partial) / self.pmax for a in actions))

    def delta(self, partial, finish):
        return (max(partial, finish) - partial) / self.pmax
