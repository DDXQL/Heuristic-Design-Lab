"""Engineering vector-H ABI, selectable only after the OBP protocol approves it.

Input is current item and ALL FEASIBLE bin capacities in permanent-ID order, never an arrival stream.
Only one bounded comprehension over the provided bin vector is admitted.
"""
import ast
import math
from heuristic_design.core.storage import digest
from heuristic_design.problems.tsp.candidates import Candidate,CandidateError,BUILTINS
ARGS=('item_size','remaining_capacities')
ABI='obp-vector-feasible-h-v2'
SAFE={**BUILTINS,'sum':sum,'len':len,'range':range,'tuple':tuple}


def validate(code,description=''):
    if not isinstance(code,str) or len(code.encode())>24576:raise CandidateError('bounded vector H source required')
    tree=ast.parse(code)
    if len(tree.body)!=1 or not isinstance(tree.body[0],ast.FunctionDef):raise CandidateError('one vector priority function required')
    f=tree.body[0];a=f.args
    if f.name!='priority' or tuple(x.arg for x in a.args)!=ARGS or a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults or a.kw_defaults or f.decorator_list:raise CandidateError('exact vector H signature required')
    for x in a.args:x.annotation=None
    f.returns=None
    if f.body and isinstance(f.body[0],ast.Expr) and isinstance(f.body[0].value,ast.Constant) and isinstance(f.body[0].value.value,str):f.body.pop(0)
    allowed=(ast.Module,ast.FunctionDef,ast.arguments,ast.arg,ast.Return,ast.Assign,ast.If,ast.Name,ast.Load,ast.Store,ast.Constant,
      ast.BinOp,ast.UnaryOp,ast.BoolOp,ast.Compare,ast.IfExp,ast.Call,ast.Subscript,ast.List,ast.Tuple,ast.ListComp,ast.comprehension,
      ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.Mod,ast.Pow,ast.UAdd,ast.USub,ast.Not,ast.And,ast.Or,ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE)
    nodes=list(ast.walk(tree));locals_=set(ARGS)
    if len(nodes)>2000:raise CandidateError('too many nodes')
    for n in nodes:
        if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store):
            if n.id.startswith('_') or n.id in SAFE or n.id in ARGS:raise CandidateError('invalid vector H local')
            locals_.add(n.id)
    for n in nodes:
        if not isinstance(n,allowed):raise CandidateError('forbidden vector H syntax '+type(n).__name__)
        if isinstance(n,ast.Name) and (n.id.startswith('_') or n.id not in locals_|set(SAFE)|{'priority'}):raise CandidateError('external vector H name')
        if isinstance(n,ast.Assign) and any(not isinstance(x,ast.Name) for x in n.targets):raise CandidateError('no input/bin mutation')
        if isinstance(n,ast.Call) and (not isinstance(n.func,ast.Name) or n.func.id not in SAFE or n.keywords):raise CandidateError('closed numerical builtins only')
        if isinstance(n,ast.Constant) and (type(n.value) not in (int,float,bool) or not math.isfinite(n.value) or abs(n.value)>1e6):raise CandidateError('bounded numerical literals only')
        if isinstance(n,ast.BinOp) and isinstance(n.op,ast.Pow) and (not isinstance(n.right,ast.Constant) or type(n.right.value) is not int or not 0<=n.right.value<=8):raise CandidateError('bounded literal exponent')
        if isinstance(n,ast.ListComp):
            if len(n.generators)!=1 or any(isinstance(x,ast.ListComp) for x in ast.walk(n.elt)):raise CandidateError('one bounded bin comprehension only')
            g=n.generators[0]
            if g.is_async or g.ifs or not isinstance(g.target,ast.Name):raise CandidateError('one ordered score per input bin required')
            direct=isinstance(g.iter,ast.Name) and g.iter.id=='remaining_capacities'
            indexed=isinstance(g.iter,ast.Call) and ast.dump(g.iter,include_attributes=False)==ast.dump(ast.parse('range(len(remaining_capacities))',mode='eval').body,include_attributes=False)
            if not direct and not indexed:raise CandidateError('comprehension may iterate only current bin vector')
        if isinstance(n,ast.Subscript) and (not isinstance(n.value,ast.Name) or n.value.id!='remaining_capacities'):raise CandidateError('only bin-capacity indexing allowed')
    def returns(block):return bool(block) and (isinstance(block[-1],ast.Return) or isinstance(block[-1],ast.If) and returns(block[-1].body) and returns(block[-1].orelse))
    if not returns(f.body):raise CandidateError('all vector H paths must return')
    canonical=ast.unparse(tree)+'\n';return Candidate(description,canonical,digest({'ABI':ABI,'AST':ast.dump(tree,include_attributes=False)}),'h')


def compile_candidate(c):
    checked=validate(c.code,c.description)
    if c.key!=checked.key:raise CandidateError('vector H identity changed')
    namespace={'__builtins__':SAFE};exec(compile(checked.code,'<obp-closed-vector-H>','exec'),namespace)
    return namespace['priority']
