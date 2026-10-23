"""Trusted callable U -> (operator, frozen-size vector), with V1 score semantics.

This is an execution interface, not an extension of the LLM closed AST language.
SELECT vectors are member scores; WEIGHTED_SUM vectors are weights. MAX/MIN use
two equal positive support indicators: unequal weights are rejected, never ignored.
"""
from dataclasses import dataclass
import math
import numbers
import time

from fjsp_usage.offline_v2 import _SchedulingState, lower_bound_v5
from fjsp_usage.research.protocol import digest
from fjsp_usage.usage_v2.execution import (
    UsageOutputError, NormalizationError, decode_output, combine_scores,
)
from llm4ad.task.optimization.fjsp_set.scheduler import (
    Schedule, ScheduledOperation, validate_schedule,
)
from . import OPERATORS, VERSION


def decode_fusion(output, size):
    if type(output) is not tuple or len(output) != 2:
        raise UsageOutputError('V2 requires exact (operator, vector) tuple')
    operator, vector = output
    if type(operator) is not str or operator not in ('SELECT',) + OPERATORS:
        raise UsageOutputError('unknown V2 operator')
    decoded = decode_output((0 if operator == 'SELECT' else 1, vector), size)
    if operator in ('MAX', 'MIN'):
        support = decoded['support']
        if len(support) != 2 or vector[support[0]] != vector[support[1]]:
            raise UsageOutputError('MAX/MIN require exactly two equal positive support indicators')
    return dict(decoded, operator=operator)


def fuse_scores(columns, weights, support, operator):
    if operator not in ('SELECT',) + OPERATORS:
        raise UsageOutputError('unknown fusion operator')
    if not support or len(support) > 2 or any(i not in columns for i in support):
        raise UsageOutputError('one/two available member columns required')
    length = len(columns[support[0]])
    if not length or any(len(columns[i]) != length for i in support):
        raise NormalizationError('nonempty aligned action columns required')
    if any(isinstance(v, bool) or not isinstance(v, numbers.Real) or not math.isfinite(v)
           for i in support for v in columns[i]):
        raise NormalizationError('finite real H columns required')
    if (operator == 'SELECT' and len(support) != 1 or
            operator in ('MAX', 'MIN') and len(support) != 2):
        raise UsageOutputError('operator/support mismatch')
    if operator == 'SELECT':
        return combine_scores(columns, weights, support)
    if any(type(w) not in (int, float) or not math.isfinite(w) or w < 0 for w in weights):
        raise UsageOutputError('finite nonnegative normalized weights required')
    if (any(i >= len(weights) or weights[i] <= 0 for i in support)
            or any(w != 0 for i, w in enumerate(weights) if i not in support)
            or not math.isclose(math.fsum(weights), 1, rel_tol=0, abs_tol=1e-15)):
        raise NormalizationError('weights must retain support and unit sum')
    scores, info = combine_scores(columns, weights, support)
    if operator in ('MAX', 'MIN'):
        if weights[support[0]] != weights[support[1]]:
            raise UsageOutputError('unweighted extrema require equal indicators')
        operation = max if operator == 'MAX' else min
        scores = tuple(operation(info['normalized'][i][a] for i in support)
                       for a in range(length))
    return scores, info


def fixed_policy(pair, operator, size=10):
    if (type(pair) is not tuple or len(pair) != 2 or pair[0] >= pair[1]
            or any(type(i) is not int or not 0 <= i < size for i in pair)
            or operator not in OPERATORS):
        raise ValueError('ordered distinct in-range fixed pair and fusion operator required')
    vector = tuple(.5 if i in pair else 0. for i in range(size))
    return lambda *state: (operator, vector)


def v1_adapter(usage):
    """Explicit adapter preserves original output validation and numerical values."""
    def adapted(*state):
        output = usage(*state)
        if type(output) is not tuple or len(output) != 2 or type(output[0]) is not int:
            raise UsageOutputError('invalid V1 output')
        if output[0] not in (0, 1):
            raise UsageOutputError('invalid V1 mode')
        return ('SELECT' if output[0] == 0 else 'WEIGHTED_SUM', output[1])
    return adapted


@dataclass(frozen=True)
class FusionResult:
    schedule: Schedule
    selected_members: tuple
    lower_bound: float
    score: float
    decisions: tuple
    member_calls: tuple


def construct_fusion_schedule(instance, heuristics, usage, *, trace=None, cost=None):
    members = tuple(heuristics)
    if not members or not all(callable(h) for h in members) or not callable(usage):
        raise ValueError('nonempty callable H and callable U required')
    state = _SchedulingState(instance)
    calls = [0] * len(members)
    decisions = []
    for step in range(state.total_operations):
        features = state.features()
        try:
            output = usage(*features)
        except Exception as exc:
            raise UsageOutputError(f'U exception at step {step}') from exc
        decoded = decode_fusion(output, len(members))
        actions, inputs = [], []
        for j, job in enumerate(instance.jobs):
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
        if not actions:
            raise ValueError('no legal action')
        started = time.perf_counter()
        columns = {}
        for i in decoded['support']:
            values = []
            for args in inputs:
                raw = members[i](*args)
                calls[i] += 1
                if isinstance(raw, bool) or not isinstance(raw, numbers.Real):
                    raise ValueError('h must return a real scalar')
                try:
                    value = float(raw)
                except (ValueError, TypeError, OverflowError) as exc:
                    raise ValueError('h must return finite scalar') from exc
                if not math.isfinite(value):
                    raise ValueError('nonfinite selected h score')
                values.append(value)
            columns[i] = tuple(values)
        scoring_seconds = time.perf_counter() - started
        started = time.perf_counter()
        scores, normal = fuse_scores(columns, decoded['weights'], decoded['support'], decoded['operator'])
        winner = max(range(len(actions)), key=lambda a: scores[a])
        fusion_seconds = time.perf_counter() - started
        chosen = actions[winner]
        if trace is not None:
            # Full physical state, not only the seven aggregate features. Columns
            # for ALL legal actions permit actual same-state counterfactuals.
            snapshot = {'cursors': tuple(state.cursors), 'job_ready': tuple(state.job_ready),
                        'machine_ready': tuple(state.machine_ready),
                        'previous_heuristic': features.previous_heuristic,
                        'scheduled': sorted((a.job, a.operation, a.machine, a.start, a.end)
                                            for a in state.scheduled)}
            trace({'step': step, 'state': dict(features._asdict()), 'physical_state': snapshot,
                   'state_sha256': digest(snapshot), 'operator': decoded['operator'],
                   'support': decoded['support'], 'weights': decoded['weights'],
                   'actions': actions, 'columns': columns, 'normalized': normal.get('normalized', {}),
                   'scores': scores, 'winner': winner, 'chosen': chosen})
        j, o, machine, start, end = chosen
        state.scheduled.append(ScheduledOperation(*chosen))
        state.cursors[j] += 1
        state.job_ready[j] = end
        state.machine_ready[machine] = end
        state.selected_members.append(decoded['dominant'])
        decisions.append((decoded['operator'], decoded['vector'], decoded['support'],
                          decoded['weights'], decoded['dominant']))
        if cost is not None:
            cost({'h_scoring_seconds': scoring_seconds, 'fusion_seconds': fusion_seconds})
    schedule = Schedule(tuple(state.scheduled), max(a.end for a in state.scheduled))
    validate_schedule(instance, schedule)
    bound = lower_bound_v5(instance)
    return FusionResult(schedule, tuple(state.selected_members), bound,
                        -schedule.makespan/bound, tuple(decisions), tuple(calls))
