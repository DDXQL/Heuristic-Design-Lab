"""Only terminal (mode, literal scalar tuple) is added to the closed language."""
import ast
from dataclasses import dataclass
import hashlib
from fjsp_usage.research.candidates import Candidate, CandidateError, validate_code, U_ARGS
from . import VERSION

@dataclass(frozen=True)
class UsageCandidate(Candidate):
    interface_version: str
    member_count: int


def validate_usage_code(code, *, description='', kind='U', interface_version=VERSION, member_count=None):
    if kind != 'U' or interface_version != VERSION:
        raise CandidateError('unsupported usage interface/kind')
    if len(code.encode('utf-8')) > 24576:
        raise CandidateError('code too large')
    try: tree = ast.parse(code)
    except (SyntaxError, RecursionError, ValueError) as exc: raise CandidateError('invalid Python') from exc
    if len(tree.body)!=1 or not isinstance(tree.body[0],ast.FunctionDef):
        raise CandidateError('one function only')
    f=tree.body[0]
    if f.name!='use_heuristics' or f.returns is not None:
        raise CandidateError('use_heuristics required; no return annotation')
    allowed_tuple_ids=set(); sizes=set()
    for node in ast.walk(f):
        if isinstance(node,ast.Return):
            v=node.value
            if not isinstance(v,ast.Tuple) or len(v.elts)!=2 or not isinstance(v.elts[1],ast.Tuple):
                raise CandidateError('return exactly (mode, (scalar, ...))')
            allowed_tuple_ids.update((id(v),id(v.elts[1])))
            sizes.add(len(v.elts[1].elts))
    if len(sizes)!=1 or min(sizes,default=0)<1:
        raise CandidateError('all returns require one nonempty fixed vector length')
    size=next(iter(sizes))
    if member_count is not None and (type(member_count) is not int or size!=member_count):
        raise CandidateError('vector length must equal frozen H size')
    for node in ast.walk(tree):
        if isinstance(node,ast.Tuple) and id(node) not in allowed_tuple_ids:
            raise CandidateError('tuples permitted only as terminal output structure')
    if len(list(ast.walk(tree)))>2000: raise CandidateError('too many syntax nodes')
    # Validate every scalar via the unchanged numerical validator. This tree is
    # NEVER executed; replacing the tuple with max merely exposes all operands.
    probe=ast.parse(code); probe.body[0].name='select_heuristic'
    class Probe(ast.NodeTransformer):
        def visit_Return(self,node):
            value=node.value
            node.value=ast.Call(ast.Name('max',ast.Load()),[value.elts[0]]+value.elts[1].elts,[])
            return node
    validate_code(ast.unparse(ast.fix_missing_locations(Probe().visit(probe))),kind='U')
    for arg in f.args.args: arg.annotation=None
    if f.body and isinstance(f.body[0],ast.Expr) and isinstance(f.body[0].value,ast.Constant) and isinstance(f.body[0].value.value,str):
        f.body.pop(0)
    canonical=ast.unparse(tree)+'\n'
    key=hashlib.sha256((VERSION+'\n'+str(size)+'\n'+ast.dump(tree,include_attributes=False)).encode()).hexdigest()
    return UsageCandidate(description,canonical,key,'U',VERSION,size)
