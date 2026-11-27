"""Frozen scheme A observation. No solver, H, model or reference calculation."""
import math
from statistics import fmean, pstdev

from .constructive_state import History as _History, freeze, plain
from .storage import digest

VERSION = 'common-state-a-v2'
WINDOW = 10
PROBLEMS = ('fjsp', 'tsp', 'obp')
NUMERIC_FIELDS = (
    'construction_progress', 'legal_action_count',
    'remaining_demand_mean', 'remaining_demand_std',
    'resource_commitment_mean', 'resource_commitment_std',
    'action_delta_mean', 'action_delta_std', 'recent_delta_mean', 'recent_delta_std',
)
AUXILIARY_FIELDS = ('previous_h_token', 'has_history', 'history_count', 'recent_history_count')
FIELDS = NUMERIC_FIELDS + AUXILIARY_FIELDS
DEFINITIONS = {
    'construction_progress': 'committed decisions / public total decisions, [0,1)',
    'legal_action_count': 'number of legal commit actions, positive integer, unnormalized',
    'remaining_demand_mean': 'mean of normalized lowest remaining demand of visible unfinished objects, [0,1]',
    'remaining_demand_std': 'population std of that same demand list, [0,0.5]',
    'resource_commitment_mean': 'mean of normalized committed shares over all defined carriers, [0,1]',
    'resource_commitment_std': 'population std of that same carrier list, [0,0.5]',
    'action_delta_mean': 'mean normalized partial-objective increment over all current legal actions, [0,1]',
    'action_delta_std': 'population std of that same action list, [0,0.5]',
    'recent_delta_mean': 'mean of last up to 10 actually committed normalized increments, [0,1]; first None',
    'recent_delta_std': 'population std of that same history window, [0,0.5]; first None',
    'previous_h_token': 'last committed H category; first None; not a quality rank',
    'has_history': 'whether a real action has been committed, bool',
    'history_count': 'all committed decisions, nonnegative integer',
    'recent_history_count': 'min(10, history_count), nonnegative integer',
}
ADAPTATIONS = {
    'fjsp': {
        'decisions': 'all operations; append-only operation-machine commits',
        'demand': 'unfinished jobs: sum of remaining operation minimum durations / B',
        'resource': 'all machines: ready time / B, unused machines zero',
        'delta': '(max(current makespan, candidate finish)-current makespan) / Pmax',
        'scale': 'B=sum of each operation maximum eligible duration; Pmax=instance maximum duration',
        'visibility': 'all jobs, eligible machines and processing times known before solve',
        'cost': 'one-time O(total alternatives) preprocessing; each observation O(jobs+machines+actions+10)',
    },
    'tsp': {
        'decisions': 'n-1 next-city choices, start 0; forced return excluded from history',
        'demand': 'each unvisited city: min distance to another unvisited city or start / dmax',
        'resource': 'all cities: current open-path degree / 2',
        'delta': 'current-to-candidate edge distance / dmax',
        'scale': 'dmax=max distance in fixed symmetric nonnegative matrix; dmax>0',
        'visibility': 'whole distance matrix public; no continuation or reference route read',
        'cost': 'O(n^2) precheck; each observation O(unvisited^2+n+10); reuse matrix',
    },
    'obp': {
        'decisions': 'N publicly known from start; each arrival is one placement',
        'demand': 'singleton current item size / bin capacity, std=0 available',
        'resource': 'all opened bins used capacity / capacity, full bins included; empty list missing',
        'delta': '0 for fitting old bins; if none fits exactly one new-bin action with delta=1',
        'scale': 'public fixed bin capacity; bin-count increments already 0 or 1',
        'visibility': 'only current item, public N, opened bins and past actions; no future items',
        'cost': 'each observation O(opened bins+10); no lookahead',
    },
}
SPEC = {
    'version': VERSION, 'numeric_fields': NUMERIC_FIELDS, 'auxiliary_fields': AUXILIARY_FIELDS,
    'definitions': DEFINITIONS, 'adaptations': ADAPTATIONS, 'window': WINDOW,
    'timing': 'enumerate legal actions -> observe -> U chooses one H -> only chosen H scores -> commit -> history',
    'statistics': 'population std; same list for each mean/std pair; singleton std zero; no history padding',
    'missing': 'None+availability false only for absent objects: first history and OBP unopened resources',
    'constants': 'constant/redundant/singleton zero is available; no disabled groups in scheme A',
    'invalid': 'reject invalid scales, nonfinite or out-of-range inputs; never treat invalid as missing',
    'u_readable': FIELDS + ('availability',),
    'host_only': ('problem_id', 'schema_id', 'spec_sha256', 'window', 'missing_reason'),
    'score_interface': 'final mean((cost-reference)/reference), minimize; no quality labels in observation',
    'numeric_tolerance': 'packet scalar validation tolerates 1e-12 for floating arithmetic; never clips',
}
SPEC_SHA256 = digest(SPEC)


def schema_id(problem):
    if problem not in PROBLEMS:
        raise ValueError('unknown scheme-A problem')
    return VERSION + '-' + problem


class History(_History):
    """Same commit semantics as v1, fixed W and a distinct observation contract."""
    def __init__(self, decisions, members, window=WINDOW):
        if type(window) is not int or window != WINDOW:
            raise ValueError('scheme A freezes window=10; new window requires a new contract')
        super().__init__(decisions, members, window)


def _units(values, *, allow_empty=False):
    values = tuple(values)
    if not values and not allow_empty:
        raise ValueError('nonterminal object list must not be empty')
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
        raise ValueError('normalized inputs must be finite numbers in [0,1]')
    return values


def _pair(values):
    return (fmean(values), pstdev(values)) if values else (None, None)


def observe(problem, *, history, demands, commitments, action_deltas):
    """All lists already normalized; no H evaluation or state mutation."""
    schema = schema_id(problem)
    if not isinstance(history, History) or history.window != WINDOW or history.count >= history.decisions:
        raise ValueError('nonterminal scheme-A history required')
    demands = _units(demands)
    commitments = _units(commitments, allow_empty=(problem == 'obp'))
    deltas = _units(action_deltas)
    recent = tuple(d for _, d in history.recent)
    return _assemble_packet(problem, schema, history, (
        history.count / history.decisions, len(deltas),
        *_pair(demands), *_pair(commitments), *_pair(deltas), *_pair(recent),
    ))


def _assemble_packet(problem, schema, history, numeric_values):
    values = dict(zip(NUMERIC_FIELDS, numeric_values))
    values.update(previous_h_token=history.previous, has_history=history.count > 0,
                  history_count=history.count, recent_history_count=len(history.recent))
    missing = {k: ('no_opened_bins' if k.startswith('resource_commitment_') else 'no_history')
               for k, v in values.items() if v is None}
    packet = freeze({**values, 'availability': {k: v is not None for k, v in values.items()},
                     'missing_reason': missing, 'problem_id': problem, 'schema_id': schema,
                     'spec_sha256': SPEC_SHA256, 'window': WINDOW})
    validate_packet(packet, history.members)
    return packet


def validate_packet(packet, member_count):
    """Reject stale identities and masks, without changing any observation."""
    if type(member_count) is not int or member_count < 1:
        raise ValueError('positive H count required')
    if set(packet) != set(FIELDS) | {'availability', 'missing_reason', 'problem_id', 'schema_id', 'spec_sha256', 'window'}:
        raise ValueError('scheme-A packet field mismatch')
    if (packet['schema_id'] != schema_id(packet['problem_id']) or packet['spec_sha256'] != SPEC_SHA256
            or type(packet['window']) is not int or packet['window'] != WINDOW):
        raise ValueError('scheme-A state identity mismatch')
    if set(packet['availability']) != set(FIELDS):
        raise ValueError('availability field mismatch')
    for key in FIELDS:
        flag, value = packet['availability'][key], packet[key]
        if type(flag) is not bool or flag != (value is not None):
            raise ValueError('value/availability mismatch: ' + key)
        if key in NUMERIC_FIELDS and value is not None:
            if key == 'legal_action_count':
                if type(value) is not int or value < 1:
                    raise ValueError('positive integer legal action count required')
            elif (type(value) not in (int, float) or not math.isfinite(value)
                  or not -1e-12 <= value <= (0.5 if key.endswith('_std') else 1) + 1e-12):
                raise ValueError('state scalar out of range: ' + key)
    if packet['construction_progress'] is None or not 0 <= packet['construction_progress'] < 1:
        raise ValueError('nonterminal progress required')
    count, recent = packet['history_count'], packet['recent_history_count']
    if type(count) is not int or count < 0 or type(recent) is not int or recent != min(WINDOW, count):
        raise ValueError('history counts inconsistent')
    if type(packet['has_history']) is not bool or packet['has_history'] != (count > 0):
        raise ValueError('history flag inconsistent')
    if (count == 0) != (packet['construction_progress'] == 0):
        raise ValueError('progress/history count inconsistent')
    previous = packet['previous_h_token']
    if count > 0 and (type(previous) is not int or not 0 <= previous < member_count):
        raise ValueError('invalid previous H category')
    absent = set()
    if count == 0:
        absent.update(('previous_h_token', 'recent_delta_mean', 'recent_delta_std'))
    if packet['problem_id'] == 'obp' and count == 0:
        absent.update(('resource_commitment_mean', 'resource_commitment_std'))
    if {k for k in FIELDS if packet[k] is None} != absent:
        raise ValueError('only genuinely absent statistical objects may be missing')
    reasons = {k: ('no_opened_bins' if k.startswith('resource_commitment_') else 'no_history') for k in absent}
    if dict(packet['missing_reason']) != reasons:
        raise ValueError('missing reasons inconsistent')
    return True


def score_final_cost(cost, reference):
    """Arithmetic only. The caller supplies an already frozen positive reference."""
    if (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0
            or type(reference) not in (int, float) or not math.isfinite(reference) or reference <= 0):
        raise ValueError('finite nonnegative cost and positive frozen reference required')
    return (cost - reference) / reference
