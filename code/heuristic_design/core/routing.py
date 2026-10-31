"""Closed, loop-free pure routing ABI. The host owns all state and H calls."""
import ast
from dataclasses import dataclass
import math
import re

from .constructive_state import FIELDS, DEFINITIONS, SPEC, SPEC_SHA256
from .storage import digest

ABI = 'pure-routing-state-v1'
BUILTINS = {'abs': abs, 'min': min, 'max': max, 'int': int, 'float': float}


class CandidateError(ValueError):
    pass


@dataclass(frozen=True)
class Candidate:
    description: str
    code: str
    key: str
    abi: str = ABI


def route_token(value, members):
    if type(value) is not int or not 0 <= value < members:
        raise ValueError('U must return one built-in int H token in range')
    return value


def validate(code, description='', member_count=10):
    if type(member_count) is not int or member_count < 1 or not isinstance(code, str) or len(code.encode()) > 24576:
        raise CandidateError('bounded code and positive H count required')
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise CandidateError('invalid routing Python') from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise CandidateError('exactly one function required')
    f = tree.body[0]
    a = f.args
    if (f.name != 'use_heuristics' or [x.arg for x in a.args] != ['state']
            or a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults
            or a.kw_defaults or f.decorator_list or f.returns
            or any(x.annotation for x in a.args) or getattr(f, 'type_params', ())):
        raise CandidateError('exact unannotated signature use_heuristics(state)')
    allowed = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
               ast.Assign, ast.If, ast.Name, ast.Load, ast.Store, ast.Constant,
               ast.Subscript, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
               ast.IfExp, ast.Call, ast.Add, ast.Sub, ast.Mult, ast.Div,
               ast.FloorDiv, ast.Mod, ast.UAdd, ast.USub, ast.Not, ast.And,
               ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
               ast.Is, ast.IsNot)
    nodes = list(ast.walk(tree))
    if len(nodes) > 1500:
        raise CandidateError('routing AST too large')
    locals_ = set()
    parent = {id(child): n for n in nodes for child in ast.iter_child_nodes(n)}
    for n in nodes:
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            if n.id == 'state' or n.id in BUILTINS or n.id.startswith('_'):
                raise CandidateError('reserved local name')
            locals_.add(n.id)
    for n in nodes:
        if not isinstance(n, allowed):
            raise CandidateError('forbidden routing syntax: ' + type(n).__name__)
        if isinstance(n, ast.Name):
            p = parent.get(id(n))
            if n.id == 'state':
                if not isinstance(p, ast.Subscript) or p.value is not n:
                    raise CandidateError('state only through approved literal reads')
            elif n.id in BUILTINS:
                if not isinstance(p, ast.Call) or p.func is not n:
                    raise CandidateError('builtins only as numeric calls')
            elif n.id not in locals_ or n.id.startswith('_'):
                raise CandidateError('external name forbidden')
        if isinstance(n, ast.Assign) and (len(n.targets) != 1 or not isinstance(n.targets[0], ast.Name)):
            raise CandidateError('only scalar local assignment')
        if isinstance(n, ast.Call) and (not isinstance(n.func, ast.Name) or n.func.id not in BUILTINS or n.keywords):
            raise CandidateError('numeric builtins only')
        if isinstance(n, ast.Subscript):
            if not isinstance(n.ctx, ast.Load) or not isinstance(n.slice, ast.Constant):
                raise CandidateError('only literal read-only state access')
            k, v = n.slice.value, n.value
            if isinstance(v, ast.Name) and v.id == 'state':
                if k not in FIELDS + ('availability',):
                    raise CandidateError('unknown state field')
                if k in ('availability', 'usage_fraction'):
                    p = parent.get(id(n))
                    # usage_fraction may also be compared to None for availability.
                    if k == 'availability' and (not isinstance(p, ast.Subscript) or p.value is not n):
                        raise CandidateError('availability requires a named scalar mask')
            elif isinstance(v, ast.Subscript) and isinstance(v.value, ast.Name) and v.value.id == 'state' and isinstance(v.slice, ast.Constant):
                base = v.slice.value
                if not ((base == 'availability' and type(k) is str and k in FIELDS)
                        or (base == 'usage_fraction' and type(k) is int and 0 <= k < member_count)):
                    raise CandidateError('mask name or usage vector index outside contract')
            else:
                raise CandidateError('arbitrary containers and aliases forbidden')
        if isinstance(n, ast.Constant):
            p = parent.get(id(n))
            if isinstance(p, ast.Subscript) and p.slice is n:
                continue
            if n.value is not None and (type(n.value) not in (bool,int,float) or not math.isfinite(n.value) or abs(n.value) > 1e9):
                raise CandidateError('bounded numeric/None constants only')
    def returns(block):
        return bool(block) and (isinstance(block[-1], ast.Return) or
            isinstance(block[-1], ast.If) and returns(block[-1].body) and returns(block[-1].orelse))
    if not returns(f.body):
        raise CandidateError('all paths require return')
    canonical = ast.unparse(tree) + '\n'
    return Candidate(description, canonical, digest({'abi': ABI, 'spec': SPEC_SHA256,
                       'members': member_count, 'ast': ast.dump(tree, include_attributes=False)}))


def checked(row, members):
    if row.get('abi') != ABI:
        raise CandidateError('old or foreign routing ABI')
    c = validate(row['code'], row['description'], members)
    if c.key != row['key']:
        raise CandidateError('routing identity changed')
    return c


def parse(text, members):
    if not isinstance(text, str) or len(text.encode()) > 32768 or text.count('```') != 2:
        raise CandidateError('one bounded fenced Python response required')
    m = re.fullmatch(r'\s*(.*?)\s*```python\s*\n(.*?)\n```\s*', text, re.S)
    if not m or not m[1].strip() or len(m[1]) > 1000:
        raise CandidateError('description then one Python function required')
    return validate(m[2], m[1].strip(), members)


def compile_candidate(c, members):
    checked(c.__dict__, members)
    def bounded(v):
        if type(v) not in (int,float,bool) or not math.isfinite(v) or abs(v) > 1e100:
            raise ValueError('routing numeric limit')
        return v
    class Limits(ast.NodeTransformer):
        def visit_BinOp(self, n):
            self.generic_visit(n)
            return ast.Call(ast.Name('_bounded', ast.Load()), [n], [])
        visit_UnaryOp = visit_BinOp
        visit_Call = visit_BinOp
    tree = ast.fix_missing_locations(Limits().visit(ast.parse(c.code)))
    ns = {'__builtins__': BUILTINS, '_bounded': bounded}
    exec(compile(tree, '<closed-pure-router-v1>', 'exec'), ns)
    function = ns['use_heuristics']
    def route(state):
        return route_token(function(state), members)
    return route


def build_prompt(problem, task, parents, members, *, window=10, enabled_groups=None):
    from .operators import CROSS, MUTATE
    import json
    operation = task['operator']
    instruction = {'CROSS': CROSS, 'MUTATE': MUTATE,
                   'INIT': 'Design one new state-dependent pure routing program.'}[operation]
    task_definition = ''
    if problem == 'fjsp':
        task_definition = (
            'Task: constructive flexible job shop scheduling (FJSP). Each job has ordered operations; '
            'each operation has eligible machines and positive processing times. Minimize final makespan Cmax. '
            'A legal action chooses a job next operation and one eligible machine. Append without insertion: '
            'start=max(job_ready_time,machine_ready_time); finish=start+processing_time. '
            'U selects exactly one H; only that H scores all current legal actions. Select the largest raw '
            'priority; exact ties use first enumeration order (job order, then frozen machine-alternative order). '
            'H arguments: processing_time is duration on this machine; remaining_work is the sum of shortest '
            'eligible durations for this and later operations of this job; remaining_operations includes '
            'the current operation; job_ready_time and machine_ready_time are the last committed finish times; '
            'earliest_start and earliest_finish are this action start and finish. '
            'Partial objective C(s)=max(machine_ready_time); action delta is '
            '(max(C(s),earliest_finish)-C(s))/B, not a quality reward or prediction. '
            'All training instances must solve and recheck successfully. Fitness is the arithmetic mean '
            'of -Cmax/LB over the complete declared training set, maximized. '
            'LB=max(max_j w_j,sum_j w_j/M), w_j=sum_o min_m processing_time; no rounding. '
            'LB is an evaluation reference, not a state field. State scales: '+SPEC['scales']['fjsp']+'. '
            'Observe before routing, commit one action, then update history; no terminal U call. '
            'Do not use old seven-argument U signatures or MIX outputs. '
            'Use the exact unannotated signature def use_heuristics(state):; no type annotations.'
        )
    return '\n'.join([
        f'Problem: {problem}. ABI: {ABI}. State spec: {SPEC_SHA256}.',
        task_definition,
        'Return a short description and exactly one fenced python function use_heuristics(state).',
        f'Return one built-in integer H token 0..{len(members)-1}. No MIX, vectors, tools or LLM calls at execution.',
        'Only numeric locals, if/else, scalar arithmetic, comparisons and numeric builtins abs/min/max/int/float.',
        'No loops, attributes, imports, arbitrary calls, collections or writes to state.',
        'Read state["field"], state["availability"]["field"], state["usage_fraction"][literal_index].',
        'Missing fields are None; guard by availability. H IDs are categories, not ordered quality values.',
        f'Window W={window}; enabled feature groups={enabled_groups}.',
        json.dumps(DEFINITIONS, ensure_ascii=False, sort_keys=True),
        'Cost increments are committed burden, not reward; no state-level performance evidence is provided.',
        'H ordered identities and descriptions (order frozen; no universal quality-rank prior):',
        json.dumps(members, ensure_ascii=False, sort_keys=True),
        instruction,
        'Frozen original parents (fitness affects external survival only; no invented state-level reward):',
        json.dumps([{'id': p['id'], 'candidate': p['candidate']} for p in parents], ensure_ascii=False, sort_keys=True),
    ])
