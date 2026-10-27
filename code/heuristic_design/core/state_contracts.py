"""Version boundaries only: no new sensors, online U inputs or cache migration.

Legacy solvers remain unchanged. The proposed common representation is disabled;
making it executable requires a new candidate ABI, evaluator and frozen protocol.
"""
from dataclasses import dataclass, asdict
import hashlib
import json
import math

@dataclass(frozen=True)
class StateSchema:
    schema_id: str
    problem_id: str
    fields: tuple[str, ...]
    phase: str = 'construction'
    executable: bool = True

    @property
    def definition_sha256(self):
        return _digest(asdict(self))

FJSP_LEGACY = StateSchema('fjsp-seven-v1-legacy', 'fjsp', (
    'progress', 'candidate_pair_ratio', 'remaining_work_mean',
    'remaining_work_std', 'machine_ready_mean', 'machine_ready_std', 'previous_heuristic'))
TSP_LEGACY = StateSchema('tsp-five-v1-legacy', 'tsp', (
    'progress', 'current_to_start', 'mean_distance_current',
    'std_distance_current', 'previous_heuristic'))
COMMON_DRAFT = StateSchema('constructive-common-v0-draft', 'cross-problem-draft', (
    'construction_progress', 'action_breadth_fraction', 'committed_objective_fraction'),
    executable=False)
SCHEMAS = {s.schema_id: s for s in (FJSP_LEGACY, TSP_LEGACY, COMMON_DRAFT)}
LEGACY_BY_PROBLEM = {'fjsp': FJSP_LEGACY.schema_id, 'tsp': TSP_LEGACY.schema_id}

def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def require_executable_schema(problem_id, schema_id=None):
    if schema_id is None:
        schema_id = LEGACY_BY_PROBLEM.get(problem_id)
    schema = SCHEMAS.get(schema_id)
    if schema is None or not schema.executable:
        raise ValueError('unknown or disabled state schema; no fallback to legacy')
    if schema.problem_id != problem_id:
        raise ValueError('problem/state schema mismatch')
    return schema

def legacy_packet(problem_id, values, *, member_count, schema_id=None):
    """Validate an explicit metadata envelope; does not call or alter online U."""
    schema = require_executable_schema(problem_id, schema_id)
    if type(member_count) is not int or member_count < 1:
        raise ValueError('explicit positive H count required')
    if type(values) not in (tuple, list) or len(values) != len(schema.fields):
        raise ValueError('state dimension mismatch; missing values cannot be filled with zero')
    for value in values[:-1]:
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('legacy scalar must be finite in [0,1]')
    if not 0 <= values[0] < 1:
        raise ValueError('terminal state must not invoke U')
    if problem_id == 'fjsp' and values[1] <= 0:
        raise ValueError('a decision must have at least one legal action')
    previous = values[-1]
    if type(previous) is not int or not -1 <= previous < member_count:
        raise ValueError('invalid legacy previous member id')
    return {'problem_id': problem_id, 'schema_id': schema.schema_id,
            'schema_sha256': schema.definition_sha256, 'phase': schema.phase,
            'fields': schema.fields, 'values': tuple(values)}

def make_binding(*, problem_id, state_schema, policy_sha256, h_order, data_order,
                 reference_sha256, solve_seed, u_interface, action_schema,
                 objective, normalization, tie_rule, evaluator_sha256):
    """Future NEW protocols must bind all these before using the new cache helper.

    This helper deliberately cannot reinterpret any historical cache/checkpoint.
    Ordered hashes include the member numbering and dataset order. Reference hash
    binds LB/NN values and rules; evaluator hash binds result acceptance semantics.
    """
    if not isinstance(state_schema, str) or not state_schema:
        raise ValueError('cache requires an explicit state schema')
    if any(type(order) not in (list, tuple) for order in (h_order, data_order)):
        raise ValueError('identity order must be a list or tuple, not a scalar')
    schema = require_executable_schema(problem_id, state_schema)
    payload = dict(problem_id=problem_id, state_schema=state_schema,
                   state_schema_sha256=schema.definition_sha256,
                   policy_sha256=policy_sha256, h_order=list(h_order), data_order=list(data_order),
                   reference_sha256=reference_sha256, solve_seed=solve_seed,
                   u_interface=u_interface, action_schema=action_schema, objective=objective,
                   normalization=normalization, tie_rule=tie_rule, evaluator_sha256=evaluator_sha256)
    if type(solve_seed) is not int or solve_seed < 0:
        raise ValueError('explicit nonnegative solve seed required')
    for key in ('h_order', 'data_order'):
        if not payload[key] or any(not isinstance(x, str) or not x for x in payload[key]):
            raise ValueError('nonempty ordered identity list required: ' + key)
    for key, value in payload.items():
        if key not in ('h_order', 'data_order', 'solve_seed') and (not isinstance(value, str) or not value):
            raise ValueError('explicit nonempty identity required: ' + key)
    return {'version': 'state-cache-binding-v1', 'payload': payload, 'sha256': _digest(payload)}

def assert_same_binding(expected, recorded):
    for binding in (expected, recorded):
        if (not isinstance(binding, dict) or binding.get('version') != 'state-cache-binding-v1'
                or not isinstance(binding.get('payload'), dict)
                or binding.get('sha256') != _digest(binding['payload'])):
            raise ValueError('missing or changed state/cache identity; never infer from old cache')
        payload = binding['payload']
        if not isinstance(payload.get('state_schema'), str) or not payload['state_schema']:
            raise ValueError('missing explicit state schema')
        schema = require_executable_schema(payload.get('problem_id'), payload.get('state_schema'))
        if payload.get('state_schema_sha256') != schema.definition_sha256:
            raise ValueError('state definition changed')
    if expected != recorded:
        raise ValueError('problem/state/policy/scientific identity mismatch; new run required')
    return True
