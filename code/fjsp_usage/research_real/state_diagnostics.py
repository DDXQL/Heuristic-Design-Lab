"""Sound, deliberately incomplete interval proofs and observational coverage.

Unknown expressions stay unknown. No branch is rejected, no code is repaired,
no samples are treated as universal equivalence. Proofs assume legal V5 states.
"""
import ast
import math
from collections import Counter
from fjsp_usage.research.candidates import U_ARGS, validate_code

VERSION = 'V5-state-bounds-and-coverage-v1-20261011'
BOUND_TEXT = '''Provable bounds in nonterminal legal states (positive processing times):
0 <= progress < 1; 0 < candidate_pair_ratio <= 1.
0 < remaining_work_mean <= 1; 0 <= remaining_work_std <= 0.5.
0 <= machine_ready_mean <= 1; 0 <= machine_ready_std <= 0.5.
previous_heuristic is -1 only at the first step, otherwise a categorical id in [0,K).
All normalized remaining-work values and machine end times lie in [0,1].
Remaining-work values are restricted to unfinished jobs and their sum is <=1:
with a active jobs, mean <=1/a and std <=sqrt(a-1)/a (a=1 gives std=0).
For either pair mean=m, std=s, s*s <= m*(1-m).
Thus s/(1+m) <=sqrt(2)/4 (approximately 0.353554), not an unnormalized dispersion.
These are conservative global bounds, not typical training ranges or state-level winners.
A condition outside these bounds cannot fire. A condition inside may still never fire in training.
Use thresholds/relations compatible with the actual normalized scale; constant selectors remain legal.
'''


def state_contract():
    return {'version': VERSION, 'text': BOUND_TEXT,
            'intervals': {**{k: [0., 1.] for k in (U_ARGS[0], U_ARGS[1], U_ARGS[2], U_ARGS[4])},
                          U_ARGS[3]: [0., .5], U_ARGS[5]: [0., .5]},
            'proof': ['Each actual duration <= its operation maximum; by induction every append end <=sum committed durations <=T.',
                      'Unfinished shortest-work sums <=T; each is positive, sum/T<=1.',
                      'For x in [0,1], population variance <=mean(x)*(1-mean(x))<=1/4.',
                      'Max sqrt(m*(1-m))/(1+m) is sqrt(2)/4 at m=1/3.',
                      'Candidate count positive and <=sum of per-job maximum alternatives; calls stop before t=Q.'],
            'floating_point_note': 'Exact bounds describe real arithmetic; interval proofs round arithmetic outward. Trace checks tolerate 1e-12.',
            'not_inputs': ['T', 'C', 'active_job_count']}


def predicates(tree):
    found = [n for n in ast.walk(tree) if isinstance(n, (ast.Compare, ast.If, ast.IfExp, ast.While))]
    found.sort(key=lambda n: (n.lineno, n.col_offset, type(n).__name__))
    return [(str(i), n) for i, n in enumerate(found)]


def instrument(tree):
    ids = {id(n): key for key, n in predicates(tree)}
    class Observe(ast.NodeTransformer):
        def wrap(self, key, expression):
            return ast.copy_location(ast.Call(ast.Name('_observe', ast.Load()),
                    [ast.Constant(int(key)), expression], []), expression)
        def visit_Compare(self, n):
            key = ids[id(n)]; self.generic_visit(n)
            return self.wrap(key, n)
        def visit_If(self, n):
            key = ids[id(n)]; self.generic_visit(n); n.test = self.wrap(key, n.test); return n
        visit_IfExp = visit_If
        visit_While = visit_If
    return Observe().visit(tree)


class Bounds(tuple):
    """Interval plus a proved identity retained only by value-preserving ops."""
    def __new__(cls, lo, hi, origin=None):
        value = super().__new__(cls, (lo, hi))
        value.origin = origin
        return value

    def __getnewargs__(self):
        return self[0], self[1], self.origin


def _out(lo, hi, origin=None):
    if not math.isfinite(lo) or not math.isfinite(hi):
        return None
    return Bounds(math.nextafter(lo, -math.inf), math.nextafter(hi, math.inf), origin)


def interval(node, env):
    try:
        return _interval(node, env)
    except (ArithmeticError, ValueError, TypeError, RecursionError):
        # Analysis is incomplete by design. An overflowing unreachable
        # expression must not crash search or turn a legal candidate invalid.
        return None


def _interval(node, env):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float, bool):
        return float(node.value), float(node.value)
    if isinstance(node, ast.Name): return env.get(node.id)
    if isinstance(node, ast.UnaryOp):
        a = interval(node.operand, env)
        if a is None: return None
        if isinstance(node.op, ast.USub): return _out(-a[1], -a[0])
        if isinstance(node.op, ast.UAdd): return a
    if isinstance(node, ast.IfExp): return union(interval(node.body, env), interval(node.orelse, env))
    if isinstance(node, ast.BinOp):
        a, b = interval(node.left, env), interval(node.right, env)
        if a is None or b is None: return None
        if isinstance(node.op, ast.Add):
            origin = None
            for x,y in ((a,b),(b,a)):
                if y == (1.,1.) and getattr(x,'origin',None) in ('remaining_work_mean','machine_ready_mean'):
                    origin = x.origin + '+1'
            return _out(a[0]+b[0], a[1]+b[1], origin)
        if isinstance(node.op, ast.Sub): return _out(a[0]-b[1], a[1]-b[0])
        if isinstance(node.op, ast.Mult):
            v = [x*y for x in a for y in b]; return _out(min(v), max(v))
        if isinstance(node.op, ast.Div) and not b[0] <= 0 <= b[1]:
            pair = (getattr(a,'origin',None),getattr(b,'origin',None))
            if pair in (('remaining_work_std','remaining_work_mean+1'),
                        ('machine_ready_std','machine_ready_mean+1')):
                # Joint variance inequality, carried through float(), aliases
                # and clipping only when clipping preserves the legal domain.
                # Allow rounding slack rather than proving an ulp-level boundary.
                return Bounds(0., math.sqrt(2)/4 + 1e-12)
            v = [x/y for x in a for y in b]; return _out(min(v), max(v))
        if isinstance(node.op, ast.Pow) and isinstance(node.right, ast.Constant):
            p = node.right.value
            v = [a[0]**p, a[1]**p]
            if p % 2 == 0 and a[0] <= 0 <= a[1]: v.append(0. if p else 1.)
            return _out(min(v), max(v))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        args = [interval(a, env) for a in node.args]
        if not args or any(a is None for a in args): return None
        name = node.func.id
        if name == 'abs' and len(args) == 1:
            a = args[0]; return (0. if a[0] <= 0 <= a[1] else min(abs(x) for x in a), max(abs(x) for x in a))
        if name in ('min', 'max'):
            f = min if name == 'min' else max
            lo,hi = f(a[0] for a in args), f(a[1] for a in args)
            origin = None
            for i,a in enumerate(args):
                tag = getattr(a,'origin',None)
                # Matching intervals alone are NOT proof of value equality.
                # Preserve identities only for harmless clipping or aliases.
                if tag and all(j==i or getattr(b,'origin',None)==tag or
                    (b[0]>=a[1] if name=='min' else b[1]<=a[0]) for j,b in enumerate(args)):
                    origin = tag
                    break
            return Bounds(lo,hi,origin)
        if name == 'float' and len(args) == 1: return args[0]
        if name == 'int' and len(args) == 1: return float(int(args[0][0])), float(int(args[0][1]))
        # round/floor/modulo/loops remain unknown rather than invent bounds.
    return None


def union(a, b):
    if a is None or b is None: return None
    origin = getattr(a,'origin',None) if getattr(a,'origin',None)==getattr(b,'origin',None) else None
    return Bounds(min(a[0],b[0]),max(a[1],b[1]),origin)


def truth(node, env):
    if isinstance(node, ast.Constant): return bool(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        t = truth(node.operand, env); return None if t is None else not t
    if isinstance(node, ast.BoolOp):
        vals = [truth(v, env) for v in node.values]
        if isinstance(node.op, ast.And):
            return False if False in vals else True if all(v is True for v in vals) else None
        return True if True in vals else False if all(v is False for v in vals) else None
    if isinstance(node, ast.Compare):
        terms = [node.left] + node.comparators; vals = []
        for left, op, right in zip(terms, node.ops, terms[1:]):
            a, b = interval(left, env), interval(right, env)
            if a is None or b is None: vals.append(None); continue
            if ast.dump(left)==ast.dump(right):
                vals.append(isinstance(op,(ast.Eq,ast.LtE,ast.GtE)))
                continue
            lo, hi, bl, bh = *a, *b
            t = None
            if isinstance(op, ast.Gt): t = False if hi <= bl else True if lo > bh else None
            elif isinstance(op, ast.GtE): t = False if hi < bl else True if lo >= bh else None
            elif isinstance(op, ast.Lt): t = False if lo >= bh else True if hi < bl else None
            elif isinstance(op, ast.LtE): t = False if lo > bh else True if hi <= bl else None
            elif isinstance(op, (ast.Eq, ast.NotEq)):
                t = False if hi < bl or lo > bh else True if lo == hi == bl == bh else None
                if isinstance(op, ast.NotEq) and t is not None: t = not t
            vals.append(t)
        return False if False in vals else True if all(v is True for v in vals) else None
    return None


def static_diagnostics(code, size, *, interface_version=None):
    checked = validate_code(code, kind='U', interface_version=interface_version,
                            member_count=size if interface_version else None); tree = ast.parse(checked.code)
    rows = {}; ids = {id(n): key for key, n in predicates(tree)}
    env = {k: Bounds(*v,origin=k) for k,v in state_contract()['intervals'].items()}
    env['previous_heuristic'] = (-1., float(size-1))
    def expression(node, scope):
        if isinstance(node, ast.IfExp):
            t = truth(node.test, scope)
            rows[ids[id(node)]] = {'line': node.lineno, 'expression': ast.unparse(node.test), 'kind': 'IfExp',
                'proof': 'always_false' if t is False else 'always_true' if t is True else 'not_proven'}
        if isinstance(node, ast.Compare):
            t = truth(node, scope)
            rows[ids[id(node)]] = {'line': node.lineno, 'expression': ast.unparse(node), 'kind': 'comparison',
                'proof': 'always_false' if t is False else 'always_true' if t is True else 'not_proven',
                'operands': [None if (bound := interval(x, scope)) is None else list(bound)
                             for x in [node.left]+node.comparators]}
        for child in ast.iter_child_nodes(node): expression(child, scope)
    def block(nodes, scope):
        scope = dict(scope)
        for n in nodes:
            if isinstance(n, (ast.If, ast.While)):
                if isinstance(n, ast.While):
                    for child in ast.walk(n):
                        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store): scope[child.id] = None
                t = truth(n.test, scope)
                rows[ids[id(n)]] = {'line': n.lineno, 'expression': ast.unparse(n.test), 'kind': type(n).__name__,
                    'proof': 'always_false' if t is False else 'always_true' if t is True else 'not_proven'}
                expression(n.test, scope)
                a, b = block(n.body, scope), block(n.orelse, scope)
                # No path assumptions. Joined assignments stay conservative.
                scope = a if t is True and not isinstance(n,ast.While) else b if t is False else {
                    k: union(a.get(k), b.get(k)) for k in a.keys() | b.keys()}
            elif isinstance(n, ast.For):
                for child in ast.walk(n):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store): scope[child.id] = None
                block(n.body, scope); block(n.orelse, scope)
            else:
                expression(n, scope)
                if isinstance(n, ast.Assign):
                    value = interval(n.value, scope)
                    for target in n.targets: scope[target.id] = value
                elif isinstance(n, ast.AugAssign): scope[n.target.id] = None
        return scope
    block(tree.body[0].body, env)
    # Ternary predicates need the same IDs as runtime, even when their parent
    # assignment/return is outside a statement branch.
    for key,n in predicates(tree):
        if key not in rows:
            rows[key] = {'line': n.lineno, 'expression': ast.unparse(n.test), 'kind': type(n).__name__, 'proof': 'not_proven'}
    return {'version': VERSION, 'code_key': checked.key, 'predicates': {k: rows[k] for k,_ in predicates(tree)},
            'note': 'Interval proofs only, conditional on a legal state reaching this expression; not_proven does not mean reachable. No rejection or semantic dedup.'}


class Coverage:
    def __init__(self, candidate, size):
        self.static = static_diagnostics(candidate.code, size,
            interface_version=getattr(candidate, 'interface_version', None))
        self.counts = {k: Counter() for k in self.static['predicates']}
    def observe(self, key, value):
        self.counts[str(key)]['true' if bool(value) else 'false'] += 1
        return value
    def report(self):
        result = {}
        for key, row in self.static['predicates'].items():
            c = self.counts[key]; seen = c['true'] + c['false']
            result[key] = {**row, 'evaluations': seen, 'true': c['true'], 'false': c['false'],
                'observation': 'not_evaluated_on_this_split' if not seen else
                    'never_true_on_this_split' if not c['true'] else 'observed_true_on_this_split'}
        return {'version': VERSION, 'predicates': result,
                'note': 'Observed on this trajectory only; zero coverage does not prove impossibility or equivalence.'}
