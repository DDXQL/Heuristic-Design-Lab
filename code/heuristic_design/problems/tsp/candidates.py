"""Closed scalar numerical AST with problem-specific signatures and tuple U."""
import ast
from dataclasses import dataclass
import hashlib
import math
import re

H_ARGS=('distance_current','distance_start','mean_remaining_distance','nearest_remaining_distance','progress')
U_ARGS=('progress','current_to_start','mean_distance_current','std_distance_current','previous_heuristic')
BUILTINS={'abs':abs,'min':min,'max':max,'int':int,'float':float,'round':round}


class CandidateError(ValueError):pass


@dataclass(frozen=True)
class Candidate:
    description:str
    code:str
    key:str
    kind:str


def validate(code,description='',kind='U',member_count=5):
    if kind not in ('h','U') or not isinstance(code,str) or len(code.encode())>24576:raise CandidateError('kind/code size')
    try:tree=ast.parse(code)
    except (SyntaxError,ValueError,RecursionError) as exc:raise CandidateError('invalid Python') from exc
    if len(tree.body)!=1 or not isinstance(tree.body[0],ast.FunctionDef):raise CandidateError('exactly one function')
    f=tree.body[0];args=H_ARGS if kind=='h' else U_ARGS;name='priority' if kind=='h' else 'use_heuristics'
    a=f.args
    if (f.name!=name or tuple(x.arg for x in a.args)!=args or a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults or a.kw_defaults or f.decorator_list or getattr(f,'type_params',())):raise CandidateError('exact signature required: '+name+str(args))
    for x in a.args:x.annotation=None
    f.returns=None
    if f.body and isinstance(f.body[0],ast.Expr) and isinstance(f.body[0].value,ast.Constant) and isinstance(f.body[0].value.value,str):f.body.pop(0)
    def returns(block):
        if not block:return False
        return isinstance(block[-1],ast.Return) or isinstance(block[-1],ast.If) and returns(block[-1].body) and returns(block[-1].orelse)
    if not returns(f.body):raise CandidateError('all paths must end in return')
    allowed=(ast.Module,ast.FunctionDef,ast.arguments,ast.arg,ast.Return,ast.Assign,ast.If,ast.Name,ast.Load,ast.Store,ast.Constant,ast.BinOp,ast.UnaryOp,ast.BoolOp,ast.Compare,ast.IfExp,ast.Call,ast.Tuple,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.Mod,ast.Pow,ast.UAdd,ast.USub,ast.Not,ast.And,ast.Or,ast.Eq,ast.NotEq,ast.Lt,ast.LtE,ast.Gt,ast.GtE)
    nodes=list(ast.walk(tree));locals_=set(args)
    if len(nodes)>2000:raise CandidateError('too many syntax nodes')
    for n in nodes:
        if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store):
            if n.id.startswith('_') or n.id in BUILTINS:raise CandidateError('invalid local name')
            locals_.add(n.id)
    permitted_tuples=set()
    for n in nodes:
        if isinstance(n,ast.Return) and kind=='U':
            v=n.value
            if not isinstance(v,ast.Tuple) or len(v.elts)!=2 or not isinstance(v.elts[1],ast.Tuple) or len(v.elts[1].elts)!=member_count:raise CandidateError('return exact (mode, K-tuple)')
            permitted_tuples.update([id(v),id(v.elts[1])])
    for n in nodes:
        if not isinstance(n,allowed):raise CandidateError('forbidden syntax: '+type(n).__name__)
        if isinstance(n,ast.Tuple) and id(n) not in permitted_tuples:raise CandidateError('tuples only in terminal U output')
        if isinstance(n,ast.Name) and (n.id.startswith('_') or n.id not in locals_|set(BUILTINS)):raise CandidateError('external name')
        if isinstance(n,ast.Call) and (not isinstance(n.func,ast.Name) or n.func.id not in BUILTINS or n.keywords):raise CandidateError('numeric builtins only')
        if isinstance(n,ast.Constant) and (type(n.value) not in (int,float,bool) or not math.isfinite(n.value) or abs(n.value)>1e9):raise CandidateError('bounded numeric constants only')
        if isinstance(n,ast.Assign) and any(not isinstance(t,ast.Name) for t in n.targets):raise CandidateError('scalar assignments only')
        if isinstance(n,ast.BinOp) and isinstance(n.op,ast.Pow) and (not isinstance(n.right,ast.Constant) or type(n.right.value) is not int or not 0<=n.right.value<=8):raise CandidateError('literal exponent 0..8')
    canonical=ast.unparse(tree)+'\n';key=hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest()
    return Candidate(description,canonical,key,kind)


def parse(text,kind,member_count):
    if not isinstance(text,str) or len(text.encode())>32768:raise CandidateError('response max 32KiB')
    match=re.fullmatch(r'\s*\{([^{}]+)\}\s*```python\s*\n(.*?)\n```\s*',text,re.S)
    if not match:raise CandidateError('one {description} followed by one python block')
    description,code=match.groups()
    if len(description)>1000:raise CandidateError('description too long')
    return validate(code,description.strip(),kind,member_count)


def compile_candidate(c,member_count):
    checked=validate(c.code,c.description,c.kind,member_count)
    if checked.key!=c.key:raise CandidateError('candidate key changed')
    def bounded(x):
        if type(x) not in (int,float,bool) or not math.isfinite(x) or abs(x)>1e100:raise ValueError('numeric limit')
        return x
    class Limits(ast.NodeTransformer):
        def visit_BinOp(self,n):
            self.generic_visit(n);return ast.Call(ast.Name('_bounded',ast.Load()),[n],[])
        visit_UnaryOp=visit_BinOp
        visit_Call=visit_BinOp
    def safe_round(value,ndigits=None):
        if ndigits is None:return round(value)
        if type(ndigits) is not int or abs(ndigits)>100:raise ValueError('round limit')
        return round(value,ndigits)
    tree=ast.fix_missing_locations(Limits().visit(ast.parse(c.code)));ns={'__builtins__':{**BUILTINS,'round':safe_round},'_bounded':bounded}
    exec(compile(tree,'<tsp-closed-numeric>','exec'),ns)
    return ns['priority' if c.kind=='h' else 'use_heuristics']


def checked(value,k):
    c=validate(value['code'],value['description'],value['kind'],k)
    if c.key!=value['key']:raise CandidateError('canonical identity mismatch')
    return c
