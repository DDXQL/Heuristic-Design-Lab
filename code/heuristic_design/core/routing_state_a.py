"""Closed U language bound to scheme A; old routing ABI is never reinterpreted."""
import ast
import json
from collections import Counter
from collections.abc import Mapping

from . import routing as language
from .state_a import (FIELDS, DEFINITIONS, ADAPTATIONS, SPEC_SHA256, WINDOW,
                      validate_packet, schema_id)

ABI = 'pure-routing-state-a-v2'
CandidateError = language.CandidateError
_CONTRACT = dict(_fields=FIELDS, _abi=ABI, _spec=SPEC_SHA256)


def validate(code, description='', member_count=10):
    return language.validate(code, description, member_count, **_CONTRACT)


def checked(row, members):
    return language.checked(row, members, **_CONTRACT)


def parse(text, members):
    return language.parse(text, members, **_CONTRACT)


class _Tracked(Mapping):
    def __init__(self, data, counts, prefix=''):
        self.data, self.counts, self.prefix = data, counts, prefix

    def __getitem__(self, key):
        value = self.data[key]
        if key == 'availability' and not self.prefix:
            return _Tracked(value, self.counts, 'availability.')
        self.counts[self.prefix + key] += 1
        return value

    def __iter__(self):
        return iter(self.data)

    def __len__(self):
        return len(self.data)


def compile_candidate(candidate, members, *, reads=None):
    """Optional Counter records actual scalar and mask reads, never calls H."""
    fn = language.compile_candidate(candidate, members, **_CONTRACT)
    if reads is not None and not isinstance(reads, Counter):
        raise ValueError('reads must be a Counter or None')

    def route(packet):
        validate_packet(packet, members)
        return fn(_Tracked(packet, reads) if reads is not None else packet)
    return route


def inspect_reads(code, member_count=10):
    """Syntactic references only; an unused branch is not a runtime read."""
    candidate = validate(code, member_count=member_count)
    values, masks = set(), set()
    for node in ast.walk(ast.parse(candidate.code)):
        if not isinstance(node, ast.Subscript):
            continue
        base = node.value
        if isinstance(base, ast.Name) and base.id == 'state' and node.slice.value != 'availability':
            values.add(node.slice.value)
        elif isinstance(base, ast.Subscript):
            masks.add(node.slice.value)
    return {'abi': ABI, 'spec_sha256': SPEC_SHA256, 'code_key': candidate.key,
            'value_fields': sorted(values), 'availability_fields': sorted(masks)}


def build_prompt(problem, task, parents, members, *, window=WINDOW):
    from .operators import CROSS, MUTATE
    schema_id(problem)
    if type(window) is not int or window != WINDOW or not members:
        raise ValueError('fixed window=10 and nonempty frozen H pool required')
    instruction = {'INIT': 'Design one new pure selector.', 'CROSS': CROSS, 'MUTATE': MUTATE}[task['operator']]
    # Validate original parents before showing them under the new interface.
    for row in parents:
        checked(row['candidate'], len(members))
    details = {
        'fjsp': (
            'Construct an append-only FJSP schedule. Start=max(job_ready,machine_ready), finish=start+duration. '
            'Only selected H scores all next-operation/eligible-machine actions; highest raw score wins, '
            'exact ties follow job then frozen machine-alternative enumeration. H arguments unchanged: '
            'processing_time, remaining_work, remaining_operations, job_ready_time, machine_ready_time, '
            'earliest_start, earliest_finish. Minimize final makespan. Evaluation reference is fixed LB_v5, '
            'max(longest minimum job workload,total minimum workload/machine_count), with no ceiling.'),
        'tsp': (
            'Construct a symmetric TSP tour, fixed start 0, choose one unvisited city each step. '
            'Only selected H scores candidates; highest raw score wins, ties smallest city ID. '
            'H scalar arguments retain distance_current, distance_start, mean_remaining_distance, '
            'nearest_remaining_distance (distances / sqrt(2) for the existing unit-square task), and progress. '
            'U distances use instance dmax instead. Forced closing edge contributes to final tour cost '
            'but not state history. Reference is an externally frozen LKH length, never computed by U.'),
        'obp': (
            'Place one currently arrived item into a fitting opened bin. Only if none fits, one new-bin '
            'action is legal. H(item_size,remaining_capacity) scores each legal bin, highest wins, '
            'ties first opened-bin index. Total item count is public from the start; future sizes/order '
            'must never be read. Minimize final bin count; lower-bound reference is fixed externally.'),
    }
    return '\n'.join((
        f'Problem {problem}; ABI {ABI}; state spec {SPEC_SHA256}.', details[problem],
        'Return a short description then exactly one fenced python function: def use_heuristics(state):',
        f'Return one built-in int H category in 0..{len(members)-1}. No MIX, H preview, rollouts or execution-time LLM.',
        'Only scalar locals, if/else, arithmetic, comparisons, abs/min/max/int/float. No imports, loops, '
        'attributes, collections, arbitrary calls or state mutation. Read only literal state["field"] '
        'and state["availability"]["field"]. Host metadata is not readable.',
        json.dumps(DEFINITIONS, ensure_ascii=False, sort_keys=True),
        json.dumps(ADAPTATIONS[problem], ensure_ascii=False, sort_keys=True),
        'Window is the last up to 10 actual commits, before this decision, no zero padding. '
        'None means no statistical object: first history or OBP no opened bins. Guard missing reads. '
        'Constant/redundant/singleton-zero values are available; all ten fields stay present. '
        'TSP degree statistics are determined by stage and size. OBP demand/action std=0; '
        'recent binary std is determined by recent mean. Resource commitment is not a universal utilization.',
        'Action deltas describe partial-objective costs, not per-H reward or final quality. '
        'Evaluation J=mean((final_cost-fixed_positive_reference)/fixed_positive_reference), MINIMIZE, '
        'over the complete declared instance set. Any failed instance invalidates the whole candidate; '
        'no successful-prefix average or zero imputation. H IDs are categories, not quality ranks.',
        'Frozen H order, descriptions and code:', json.dumps(members, ensure_ascii=False, sort_keys=True),
        instruction, 'Original parents:',
        json.dumps([{'id': p['id'], 'candidate': p['candidate']} for p in parents], ensure_ascii=False, sort_keys=True),
    ))
