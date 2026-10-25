"""Isolated CROSS A/B preparation: no API, solver, I1 or MUTATE changes.

An explicit fee proof is required before real dispatch. The old engineering
risk envelope and public currency display settings do not constitute that proof.
"""
from copy import deepcopy
from decimal import Decimal
from itertools import combinations
import math
import random
from statistics import fmean

from fjsp_usage.research.candidates import validate_code
from fjsp_usage.research.protocol import digest
from fjsp_usage.usage_v2 import VERSION as INTERFACE

VERSION = 'cross-fitness-feedback-ab-v1-20261025'
PAIR_SEED = 2026102501
ORDER_SEED = 2026102502
CAPS = {'logical_candidates': 30, 'api_attempts': 40, 'per_candidate_attempts': 2,
        'cost_CNY': 20, 'program_instances': 630, 'solve_passes': 1260,
        'launch_window_seconds': 21600}


class EvidenceError(ValueError):
    pass


class FeeStop(RuntimeError):
    pass


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_parent(row, result, instances, context, expected_context):
    """Read-only validation; does not evaluate a parent to repair evidence."""
    if context != expected_context or not context or len(context.get('H_order', [])) != 10:
        raise EvidenceError('parent scientific context mismatch')
    candidate = row['candidate']
    checked = validate_code(candidate['code'], description=candidate['description'], kind='U',
                            interface_version=INTERFACE, member_count=10)
    if (candidate.get('kind') != 'U' or candidate.get('interface_version') != INTERFACE
            or candidate.get('member_count') != 10 or checked.key != candidate['key']):
        raise EvidenceError('parent source/interface/key mismatch')
    rows = result.get('instances', [])
    if (result.get('valid') is not True or result.get('total_instances') != len(instances)
            or not instances or len(rows) != len(instances)
            or len({r['file'] for r in rows}) != len(instances)
            or [r['file'] for r in rows] != [r['file'] for r in instances]):
        raise EvidenceError('complete ordered parent evaluation required; no prefix or fallback')
    for actual, expected in zip(rows, instances):
        if (not finite(actual.get('lower_bound')) or actual['lower_bound'] != expected['LB']
                or actual['lower_bound'] <= 0 or type(actual.get('makespan')) is not int
                or actual['makespan'] <= 0 or actual.get('feasible') is not True
                or actual.get('score') != -actual['makespan'] / actual['lower_bound']):
            raise EvidenceError('parent instance/LB/score mismatch')
    fitness = result.get('fitness')
    if (not finite(fitness) or row.get('fitness') != fitness
            or fitness != fmean(r['score'] for r in rows)):
        raise EvidenceError('parent full Fitness mismatch')
    return checked


def feedback(first, second):
    if not finite(first) or not finite(second):
        raise EvidenceError('finite complete parent Fitness required')
    return ('COMPLETE TRAIN21 EVALUATION FEEDBACK\n'
            f'parent_1 (PARENT 0) complete train21 Fitness = {first!r}.\n'
            f'parent_2 (PARENT 1) complete train21 Fitness = {second!r}.\n'
            f'delta = Fitness(parent_2) - Fitness(parent_1) = {second-first!r}.\n'
            'Higher Fitness is better.\n'
            'Whole-program Fitness differences do not establish a causal effect of a specific state branch; '
            'explanations for proposed modifications are hypotheses to be tested.\n')


def render(condition, parents, members, fitness_values=None, *, operator='CROSS'):
    """A is byte-identical to the current B1 CROSS. B adds one fact block."""
    from tools import b1_usage_prompts as current
    from fjsp_usage.usage_v2.prompts import CROSS
    if operator != 'CROSS' or condition not in ('A', 'B') or len(parents) != 2:
        raise EvidenceError('this independent adapter only supports two-parent CROSS A/B')
    base = current.build_prompt('B', 'CROSS', parents, members)
    if condition == 'A':
        return base
    if fitness_values is None or len(fitness_values) != 2:
        raise EvidenceError('B cannot silently fall back without complete matching Fitness')
    if any(p['fitness'] != f for p, f in zip(parents, fitness_values)):
        raise EvidenceError('B Fitness not bound to actual ordered parent rows')
    operator_text = CROSS.replace('selection relationship', 'usage relationship').replace('selector', 'usage program')
    marker = '\n' + operator_text + '\n'
    if base.count(marker) != 1:
        raise EvidenceError('current CROSS boundary changed')
    return base.replace(marker, '\n' + feedback(*fitness_values) + operator_text + '\n', 1)


def plan(parent_ids, pair_seed=PAIR_SEED, order_seed=ORDER_SEED):
    """Only ids, not scores: uniform sample without replacement, fixed orientation."""
    if len(set(parent_ids)) != len(parent_ids):
        raise EvidenceError('duplicate parent IDs')
    rng = random.Random(pair_seed)
    available = list(combinations(sorted(parent_ids), 2))
    chosen = rng.sample(available, min(5, len(available)))
    pairs = []
    for index, pair in enumerate(chosen, 1):
        ordered = list(pair)
        if rng.getrandbits(1):
            ordered.reverse()
        pairs.append({'pair_id': f'pair_{index:02d}', 'parents': ordered})
    ordering = random.Random(order_seed)
    units = [(p, repeat) for p in pairs for repeat in range(1, 4)]
    ordering.shuffle(units)
    orientations = [i % 2 == 0 for i in range(len(units))]
    ordering.shuffle(orientations)
    tasks = []
    for (pair, repeat), a_first in zip(units, orientations):
        for condition in (('A', 'B') if a_first else ('B', 'A')):
            tasks.append({'task_id': f'{pair["pair_id"]}_r{repeat}_{condition}',
                          'pair_id': pair['pair_id'], 'repeat_id': repeat,
                          'condition': condition, 'parents': pair['parents'][:],
                          'dispatch_position': len(tasks) + 1})
    return {'pair_seed': pair_seed, 'order_seed': order_seed, 'pairs': pairs, 'tasks': tasks,
            'sampling': 'uniform without replacement over all unordered pairs; orientation once per pair',
            'dispatch': 'paired adjacent A/B, balanced first arm, shuffled units'}


def fee_gate(proof):
    """Never infer CNY conversion or a billable-token ceiling from a risk estimate."""
    reasons = []
    if proof.get('CNY_conversion_verified') is not True:
        reasons.append('platform_units_to_actual_CNY_not_verified')
    if proof.get('billable_token_upper_bound_verified') is not True:
        reasons.append('input_output_reasoning_cache_billing_upper_bound_not_verified')
    if proof.get('live_model_and_tariff_verified') is not True:
        reasons.append('live_model_or_tariff_not_verified')
    if proof.get('other_task_account_encumbrance_verified') is not True:
        reasons.append('other_task_account_encumbrance_not_verified')
    if reasons:
        raise FeeStop('; '.join(reasons))
    # A caller still needs a separately accepted monetary reservation/settlement adapter.
    if proof.get('monetary_adapter_accepted') is not True:
        raise FeeStop('monetary_reservation_settlement_adapter_not_accepted')
    return True


def reserve_cost(ledger, attempt_id, task_id, worst_CNY):
    """Pure accounting primitive for future verified bounds; unknown costs retain holds."""
    if not finite(worst_CNY) or worst_CNY <= 0:
        raise FeeStop('positive verified per-request ceiling required')
    rows = ledger['attempts']
    if attempt_id in rows or len(rows) >= CAPS['api_attempts']:
        raise FeeStop('attempt replay or attempt cap')
    if sum(r['task_id'] == task_id for r in rows.values()) >= CAPS['per_candidate_attempts']:
        raise FeeStop('per-logical-candidate attempt cap')
    if len({r['task_id'] for r in rows.values()} | {task_id}) > CAPS['logical_candidates']:
        raise FeeStop('logical candidate cap')
    for r in rows.values():
        if (not finite(r['reserved_CNY']) or r['reserved_CNY'] <= 0
                or r.get('actual_CNY') is not None and
                (not finite(r['actual_CNY']) or not 0 <= r['actual_CNY'] <= r['reserved_CNY'])):
            raise FeeStop('unknown or inconsistent monetary ledger')
    charged = sum((Decimal(str(r.get('actual_CNY') if r.get('actual_CNY') is not None
                               else r['reserved_CNY'])) for r in rows.values()), Decimal(0))
    if charged + Decimal(str(worst_CNY)) > Decimal(str(CAPS['cost_CNY'])):
        raise FeeStop('20 CNY conservative reservation exhausted')
    updated = deepcopy(ledger)
    updated['attempts'][attempt_id] = {'task_id': task_id, 'reserved_CNY': worst_CNY,
                                     'actual_CNY': None, 'status': 'reserved_unknown'}
    return updated


def protocol_key(value):
    return digest(value)
