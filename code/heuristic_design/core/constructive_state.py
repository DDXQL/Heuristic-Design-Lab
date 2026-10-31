"""Constructive common v1: pre-action observations, post-action history.

No H calls, lookahead completions, LB, or outer-search information is observed.
Missing/disabled fields are None, with an explicit reason and availability mask.
"""
from collections import deque
from statistics import fmean, pstdev
from types import MappingProxyType
import math

from .storage import digest

VERSION = 'constructive-common-v1'
GROUPS = {
    'construction': ('construction_progress', 'action_breadth_fraction',
                     'committed_objective_fraction'),
    'action_cost': ('action_delta_min', 'action_delta_mean', 'action_delta_std',
                    'action_delta_max', 'action_delta_best_gap'),
    'trajectory': ('last_action_delta', 'recent_delta_mean', 'recent_delta_std'),
    'usage': ('current_h_run_fraction', 'recent_h_switch_fraction'),
}
NUMERIC_FIELDS = tuple(f for group in GROUPS.values() for f in group)
HISTORY_FIELDS = ('previous_h_token', 'usage_fraction', 'has_history',
                  'history_count', 'recent_history_count')
FIELDS = NUMERIC_FIELDS + HISTORY_FIELDS
DEFINITIONS = {
    'construction_progress': 'executed optional decisions / D',
    'action_breadth_fraction': 'legal action count / fixed action bound C',
    'committed_objective_fraction': 'committed partial objective / B',
    'action_delta_min': 'min((C(s+a)-C(s))/B) over legal actions',
    'action_delta_mean': 'population mean of normalized legal action deltas',
    'action_delta_std': 'population std of normalized legal action deltas',
    'action_delta_max': 'max normalized legal action delta',
    'action_delta_best_gap': 'second order statistic minus first; ties zero; singleton missing',
    'last_action_delta': 'last committed normalized objective increment; first missing',
    'recent_delta_mean': 'mean of last min(W, history_count) committed increments',
    'recent_delta_std': 'population std of same window; one sample std=0',
    'current_h_run_fraction': 'consecutive previous-H decisions / D; first missing',
    'recent_h_switch_fraction': 'adjacent H changes / adjacent pairs in last W selections; <2 missing',
    'previous_h_token': 'previous H category in this frozen problem-specific H order; first None',
    'usage_fraction': 'per-H cumulative count / executed decisions; first None',
    'has_history': 'whether any optional action was committed',
    'history_count': 'all committed optional actions',
    'recent_history_count': 'min(W, history_count)',
}
SPEC = {'version': VERSION, 'definitions': DEFINITIONS, 'default_window': 10,
        'scales': {'fjsp': 'D=Q; B=sum(max processing per operation); C=sum(max alternatives per job)',
                   'tsp': 'D=n-1; B=n*Dmax; C=n-1; closing edge forced, excluded from history'},
        'timing': 'observe before U, then selected H only, commit, update history; no terminal U',
        'precheck': 'reject zero/nonfinite scales or invalid instance independently of policy',
        'missing': 'None + availability false + reason; no silent zero imputation'}
SPEC_SHA256 = digest(SPEC)


def schema_id(problem):
    if problem not in ('fjsp', 'tsp'):
        raise ValueError('unknown common-state problem')
    return VERSION + '-' + problem


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


def plain(value):
    if isinstance(value, (dict, type(MappingProxyType({})))):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


class History:
    def __init__(self, decisions, members, window=10):
        if any(type(x) is not int or x < 1 for x in (decisions, members, window)):
            raise ValueError('positive integer D, H count and W required')
        self.decisions, self.members, self.window = decisions, members, window
        self.counts = [0] * members
        self.recent = deque(maxlen=window)
        self.count = self.run = 0
        self.previous = None

    def commit(self, member, delta):
        if type(member) is not int or not 0 <= member < self.members:
            raise ValueError('illegal routed H token')
        if type(delta) not in (int, float) or not math.isfinite(delta) or not 0 <= delta <= 1:
            raise ValueError('invalid committed normalized delta')
        if self.count >= self.decisions:
            raise ValueError('history already terminal')
        self.run = self.run + 1 if member == self.previous else 1
        self.previous = member
        self.counts[member] += 1
        self.count += 1
        self.recent.append((member, float(delta)))


def observe(problem, *, history, action_bound, partial_cost, scale, action_deltas,
            enabled_groups=tuple(GROUPS)):
    """Construct an immutable snapshot from read-only action arithmetic."""
    if not set(enabled_groups) <= set(GROUPS) or len(set(enabled_groups)) != len(enabled_groups):
        raise ValueError('unknown or repeated feature group')
    if 'construction' not in enabled_groups:
        raise ValueError('construction group is mandatory in v1')
    if (type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0
            or type(action_bound) is not int or action_bound <= 0):
        raise ValueError('precheck requires positive fixed B and C')
    if history.count >= history.decisions:
        raise ValueError('terminal state has no U invocation')
    deltas = tuple(float(x) / scale for x in action_deltas)
    if not deltas or len(deltas) > action_bound:
        raise ValueError('nonterminal legal action count outside fixed bound')
    cost = partial_cost / scale
    if not math.isfinite(cost) or not 0 <= cost <= 1 or any(not math.isfinite(x) or not 0 <= x <= 1 for x in deltas):
        raise ValueError('nonfinite or out-of-bound cost')
    ordered = sorted(deltas)
    recent = tuple(history.recent)
    hs = tuple(h for h, _ in recent)
    ds = tuple(d for _, d in recent)
    values = dict(zip(GROUPS['construction'],
                      (history.count / history.decisions, len(deltas) / action_bound, cost)))
    values.update(zip(GROUPS['action_cost'],
                      (ordered[0], fmean(deltas), pstdev(deltas), ordered[-1],
                       ordered[1] - ordered[0] if len(ordered) >= 2 else None)))
    values.update(last_action_delta=ds[-1] if ds else None,
                  recent_delta_mean=fmean(ds) if ds else None,
                  recent_delta_std=pstdev(ds) if ds else None,
                  current_h_run_fraction=history.run / history.decisions if hs else None,
                  recent_h_switch_fraction=(sum(a != b for a, b in zip(hs, hs[1:])) / (len(hs)-1)) if len(hs) >= 2 else None,
                  previous_h_token=history.previous,
                  usage_fraction=tuple(n / history.count for n in history.counts) if hs else None,
                  has_history=history.count > 0, history_count=history.count,
                  recent_history_count=len(recent))
    reasons = {k: ('singleton_action' if k == 'action_delta_best_gap' else
                   'insufficient_adjacent_history' if k == 'recent_h_switch_fraction' else
                   'no_history') for k, v in values.items() if v is None}
    for group, fields in GROUPS.items():
        if group not in enabled_groups:
            for field in fields:
                values[field] = None
                reasons[field] = 'feature_group_disabled'
    if 'usage' not in enabled_groups:
        for field in ('previous_h_token', 'usage_fraction'):
            values[field] = None
            reasons[field] = 'feature_group_disabled'
    return freeze({**values, 'availability': {k: v is not None for k, v in values.items()},
                   'missing_reason': reasons, 'problem_id': problem,
                   'schema_id': schema_id(problem), 'spec_sha256': SPEC_SHA256,
                   'window': history.window, 'enabled_groups': tuple(enabled_groups)})
