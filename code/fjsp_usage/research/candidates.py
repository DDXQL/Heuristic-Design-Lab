"""Parse a single candidate and admit only a closed numerical Python subset.

This deliberately narrower language is versioned, and shared by every arm.
AST-normalised keys remove comments, annotations and docstrings, not semantics.
"""

import ast
from dataclasses import dataclass
import hashlib
import re

U_ARGS = ('progress', 'candidate_pair_ratio', 'remaining_work_mean',
          'remaining_work_std', 'machine_ready_mean', 'machine_ready_std',
          'previous_heuristic')
H_ARGS = ('processing_time', 'remaining_work', 'remaining_operations',
          'job_ready_time', 'machine_ready_time', 'earliest_start', 'earliest_finish')
BUILTINS = ('abs', 'min', 'max', 'int', 'float', 'round', 'range')


class CandidateError(ValueError):
    pass


@dataclass(frozen=True)
class Candidate:
    description: str
    code: str
    key: str
    kind: str


def parse_response(response: str, *, kind='U') -> Candidate:
    if not isinstance(response, str) or len(response.encode('utf-8')) > 32768:
        raise CandidateError('response must be text of at most 32 KiB')
    match = re.fullmatch(r'\s*\{([^{}]+)\}\s*```python\s*\n(.*?)\n```\s*',
                         response, flags=re.DOTALL)
    if not match:
        raise CandidateError('expected one {description} and one python block only')
    description, code = match.groups()
    description = description.strip()
    if len(description) > 1000 or len(re.findall(r'[!?。！？]+|(?<!\d)\.(?!\d)', description)) > 3:
        raise CandidateError('description must contain at most three sentences')
    return validate_code(code, description=description, kind=kind)


def validate_code(code: str, *, description='', kind='U') -> Candidate:
    if kind not in ('U', 'h'):
        raise CandidateError('unknown candidate kind')
    if len(code.encode('utf-8')) > 24576:
        raise CandidateError('code too large')
    try:
        tree = ast.parse(code)
    except (SyntaxError, RecursionError, ValueError) as exc:
        raise CandidateError('invalid Python') from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise CandidateError('one function only; imports and top-level code forbidden')
    function = tree.body[0]
    expected = U_ARGS if kind == 'U' else H_ARGS
    name = 'select_heuristic' if kind == 'U' else 'priority'
    args = function.args
    if (function.name != name or tuple(a.arg for a in args.args) != expected
            or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg
            or args.defaults or args.kw_defaults or function.decorator_list
            or getattr(function, 'type_params', ())):
        raise CandidateError(f'exact interface required: {name}{expected}')
    types = ('float',) * 6 + ('int',) if kind == 'U' else (
        'float', 'float', 'int', 'float', 'float', 'float', 'float')
    for arg, annotation in zip(args.args, types):
        if arg.annotation and (not isinstance(arg.annotation, ast.Name)
                               or arg.annotation.id != annotation):
            raise CandidateError('incorrect parameter annotation')
        arg.annotation = None
    if function.returns and (not isinstance(function.returns, ast.Name)
                             or function.returns.id != ('int' if kind == 'U' else 'float')):
        raise CandidateError('incorrect return annotation')
    function.returns = None
    if function.body and isinstance(function.body[0], ast.Expr) and isinstance(
            function.body[0].value, ast.Constant) and isinstance(function.body[0].value.value, str):
        function.body.pop(0)
    if not function.body or not any(isinstance(n, ast.Return) for n in ast.walk(function)):
        raise CandidateError('a return is required')

    def returns_on_all_paths(block):
        last = block[-1] if block else None
        return isinstance(last, ast.Return) or (isinstance(last, ast.If)
            and returns_on_all_paths(last.body) and returns_on_all_paths(last.orelse))

    if not returns_on_all_paths(function.body):
        raise CandidateError('end the function with return or an if/else returning on both paths')
    allowed = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
               ast.Assign, ast.AugAssign, ast.If, ast.While, ast.For, ast.Break,
               ast.Continue, ast.Pass, ast.Expr, ast.Name, ast.Load, ast.Store,
               ast.Constant, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
               ast.IfExp, ast.Call, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
               ast.Mod, ast.Pow, ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or,
               ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)
    nodes = list(ast.walk(tree))
    if len(nodes) > 2000 or sum(isinstance(n, ast.FunctionDef) for n in nodes) != 1:
        raise CandidateError('too many syntax nodes')
    locals_ = set(expected)
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if not node.id.isidentifier() or '_' == node.id[0] or node.id in BUILTINS:
                raise CandidateError('invalid local identifier')
            locals_.add(node.id)
    for node in nodes:
        if not isinstance(node, allowed):
            raise CandidateError(f'forbidden syntax: {type(node).__name__}')
        if isinstance(node, ast.Name):
            if node.id.startswith('_') or node.id not in locals_ | set(BUILTINS):
                raise CandidateError(f'external name forbidden: {node.id}')
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in BUILTINS or node.keywords:
                raise CandidateError('only explicit numeric builtins may be called')
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float, bool) or abs(node.value) > 1e9:
                raise CandidateError('only bounded numeric/boolean constants allowed')
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exponent = node.right
            if not isinstance(exponent, ast.Constant) or type(exponent.value) is not int or not 0 <= exponent.value <= 8:
                raise CandidateError('power exponent must be a literal integer in [0,8]')
    canonical = ast.unparse(tree) + '\n'
    key = hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()
    return Candidate(description, canonical, key, kind)


def compile_candidate(candidate: Candidate):
    # No import, attributes, containers, recursion, global/nonlocal or dynamic eval
    # can pass the validator. Builtins are explicitly closed, not inherited.
    import builtins
    checked = validate_code(candidate.code, description=candidate.description, kind=candidate.kind)
    if checked.key != candidate.key:
        raise CandidateError('candidate key mismatch')
    import math

    def bounded(value):
        if isinstance(value, range):
            return value
        if type(value) not in (int, float, bool) or abs(value) > 1e100:
            raise ValueError('numeric intermediate exceeds the research language limit')
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('non-finite numeric intermediate')
        return value

    class Limits(ast.NodeTransformer):
        def visit_BinOp(self, node):
            self.generic_visit(node)
            return ast.Call(ast.Name('_bounded', ast.Load()), [node], [])

        visit_Call = visit_BinOp
        visit_UnaryOp = visit_BinOp

        def visit_AugAssign(self, node):
            replacement = ast.Assign([node.target], ast.BinOp(
                ast.Name(node.target.id, ast.Load()), node.op, node.value))
            return self.visit(replacement)

    tree = ast.fix_missing_locations(Limits().visit(ast.parse(checked.code)))

    def safe_round(value, ndigits=0):
        # Python integer round may construct 10**abs(ndigits) internally before
        # the post-operation numeric guard. Bound it BEFORE that allocation.
        if type(ndigits) is not int or abs(ndigits) > 100:
            raise ValueError('round ndigits must be a built-in int in [-100,100]')
        return round(value, ndigits)

    numerical_builtins = {name: getattr(builtins, name) for name in BUILTINS}
    numerical_builtins['round'] = safe_round
    namespace = {'__builtins__': numerical_builtins,
                 '_bounded': bounded}
    exec(compile(tree, '<restricted-candidate>', 'exec'), namespace)
    return namespace['select_heuristic' if candidate.kind == 'U' else 'priority']
