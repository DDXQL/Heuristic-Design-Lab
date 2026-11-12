"""Scheme A: unchanged ten scalars plus four per-H committed-history vectors."""
import math

from . import state_a as base
from .constructive_state import freeze, plain
from .storage import digest

VERSION = 'common-state-a-v3'
U_ABI = 'pure-routing-state-a-v3'
WINDOW = base.WINDOW
PROBLEMS = base.PROBLEMS
NUMERIC_FIELDS = base.NUMERIC_FIELDS
H_FIELDS = ('h_usage_count', 'h_recent_usage_count', 'h_last_use_gap_fraction', 'h_recent_delta_mean')
FIELDS = base.FIELDS + H_FIELDS
H_DEFINITIONS = {
    'h_usage_count': 'K nonnegative integer counts of successful commits controlled by each H; never used=0, available',
    'h_recent_usage_count': 'K integer counts in the same last min(10,t) GLOBAL commits; zero available; also sample counts for h_recent_delta_mean',
    'h_last_use_gap_fraction': 'K values (t-last_commit_index[h])/D in [0,1); last step=0; never used=None, item unavailable',
    'h_recent_delta_mean': 'K means of actual normalized deltas controlled by H in the GLOBAL ten-commit window, [0,1]; no recent sample=None, item unavailable; real zero available',
}
SPEC = {
    'version': VERSION, 'u_abi': U_ABI, 'base_spec_sha256': base.SPEC_SHA256,
    'scalar_fields': base.FIELDS, 'h_fields': H_FIELDS, 'h_definitions': H_DEFINITIONS,
    'member_order': 'one immutable K-vector per field, in the frozen problem-specific H order',
    'availability': 'base fields use bool masks; H fields use K bool masks under availability[field][literal_H_index]',
    'window': WINDOW, 'history_scope': 'reset for each instance and each candidate solve; only real successful commits',
    'timing': 'observe before U; only selected H scores; commit action; then update selected-H history',
    'delta_scales': 'unchanged v2: FJSP partial makespan/Pmax; TSP chosen edge/dmax excluding closure; OBP new bins 0/1',
    'missing': 'counts always available; gap missing for never used; delta mean missing for no recent samples',
    'read_boundary': 'literal member indices only; no H calls, offline quality priors, lookahead, vectors returned, loops or writes',
    'score_interface': 'unchanged relative-gap-min, final complete-instance cost only',
    'cost': 'commit O(1), observe/output O(K+10), memory O(K+10), in addition to v2 sensors',
}
SPEC_SHA256 = digest(SPEC)
score_final_cost = base.score_final_cost


def schema_id(problem):
    if problem not in PROBLEMS:
        raise ValueError('unknown scheme-A-v3 problem')
    return VERSION + '-' + problem


class History(base.History):
    def __init__(self, decisions, members, window=WINDOW):
        super().__init__(decisions, members, window)
        self.last_use = [None] * members

    def commit(self, member, delta):
        # Inherited checks happen before any mutation. Counting unit is a commit,
        # not the selected H's multiple per-action scoring function calls.
        super().commit(member, delta)
        self.last_use[member] = self.count


def extend_packet(packet, history):
    if not isinstance(history, History):
        raise ValueError('v3 history required; do not infer it from an old packet')
    base.validate_packet(packet, history.members)
    if packet['history_count'] != history.count:
        raise ValueError('packet/history count mismatch')
    counts, sums = [0] * history.members, [0.] * history.members
    for member, delta in history.recent:
        counts[member] += 1
        sums[member] += delta
    vectors = {
        'h_usage_count': tuple(history.counts),
        'h_recent_usage_count': tuple(counts),
        'h_last_use_gap_fraction': tuple((history.count - last) / history.decisions if last is not None else None
                                         for last in history.last_use),
        'h_recent_delta_mean': tuple(total / n if n else None for total, n in zip(sums, counts)),
    }
    masks = {field: tuple(v is not None for v in values) for field, values in vectors.items()}
    reasons = dict(packet['missing_reason'])
    for field, reason in (('h_last_use_gap_fraction', 'never_used'), ('h_recent_delta_mean', 'no_recent_samples')):
        if any(v is None for v in vectors[field]):
            reasons[field] = tuple(reason if v is None else None for v in vectors[field])
    result = freeze({**dict(packet), **vectors, 'availability': {**dict(packet['availability']), **masks},
                     'missing_reason': reasons, 'schema_id': schema_id(packet['problem_id']),
                     'spec_sha256': SPEC_SHA256})
    validate_packet(result, history.members)
    return result


def observe(problem, *, history, demands, commitments, action_deltas):
    return extend_packet(base.observe(problem, history=history, demands=demands,
                         commitments=commitments, action_deltas=action_deltas), history)


def validate_packet(packet, members):
    if type(members) is not int or members < 1:
        raise ValueError('positive H count required')
    if (packet.get('schema_id') != schema_id(packet.get('problem_id')) or packet.get('spec_sha256') != SPEC_SHA256
            or set(packet) != set(base.FIELDS) | set(H_FIELDS) | set(base.SPEC['host_only']) | {'availability'}):
        raise ValueError('v3 state identity or field mismatch')
    if set(packet['availability']) != set(FIELDS):
        raise ValueError('v3 availability field mismatch')
    projected = {k: v for k, v in packet.items() if k not in H_FIELDS}
    projected.update(schema_id=base.schema_id(packet['problem_id']), spec_sha256=base.SPEC_SHA256,
                     availability={k: packet['availability'][k] for k in base.FIELDS},
                     missing_reason={k: v for k, v in packet['missing_reason'].items() if k not in H_FIELDS})
    base.validate_packet(projected, members)
    for field in H_FIELDS:
        values, masks = packet[field], packet['availability'][field]
        if (not isinstance(values, (tuple, list)) or not isinstance(masks, (tuple, list))
                or len(values) != members or len(masks) != members):
            raise ValueError('v3 vector length mismatch: ' + field)
        if any(type(flag) is not bool or flag != (value is not None) for value, flag in zip(values, masks)):
            raise ValueError('v3 per-item availability mismatch: ' + field)
    cumulative, recent = packet['h_usage_count'], packet['h_recent_usage_count']
    for field, limit in (('h_usage_count', packet['history_count']), ('h_recent_usage_count', packet['recent_history_count'])):
        if any(type(v) is not int or not 0 <= v <= limit for v in packet[field]) or sum(packet[field]) != limit:
            raise ValueError('v3 count vector inconsistent: ' + field)
    expected_reasons = dict(projected['missing_reason'])
    for field, reason in (('h_last_use_gap_fraction', 'never_used'), ('h_recent_delta_mean', 'no_recent_samples')):
        reasons = []
        for i, value in enumerate(packet[field]):
            absent = cumulative[i] == 0 if field == 'h_last_use_gap_fraction' else recent[i] == 0
            if absent != (value is None):
                raise ValueError('v3 absent object incorrectly encoded: ' + field)
            if not absent and (type(value) not in (int, float) or not math.isfinite(value)
                               or not 0 <= value <= 1 or (field == 'h_last_use_gap_fraction' and value >= 1)):
                raise ValueError('v3 value out of range: ' + field)
            reasons.append(reason if absent else None)
        if any(x is not None for x in reasons):
            expected_reasons[field] = tuple(reasons)
    if plain(packet['missing_reason']) != plain(expected_reasons):
        raise ValueError('v3 missing reasons inconsistent')
    for i in range(members):
        if recent[i] > cumulative[i]:
            raise ValueError('recent use count exceeds all-history count')
        gap = packet['h_last_use_gap_fraction'][i]
        if gap is not None and (gap > packet['construction_progress']
                                or (gap == 0) != (i == packet['previous_h_token'])):
            raise ValueError('last-use gap disagrees with committed history')
    n = packet['recent_history_count']
    if n and not math.isclose(sum((v or 0.) * k for v, k in zip(packet['h_recent_delta_mean'], recent)) / n,
                              packet['recent_delta_mean'], rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError('per-H means disagree with global recent mean')
    return True
