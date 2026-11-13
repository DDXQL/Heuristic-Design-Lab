"""Domain adapters. No scheduler, API client or public state definitions here."""
import ast
from dataclasses import asdict
from fractions import Fraction
import math
from pathlib import Path
import re
from heuristic_design.core.storage import read,sha,digest
from heuristic_design.core import state_a_v3 as state,routing_state_a_v3 as u_language
from heuristic_design.problems import routing_fixtures as fixtures
from heuristic_design.problems.tsp import candidates as tsp_h
from fjsp_usage.research import candidates as fjsp_h

OBP_ARGS=('item_size','remaining_capacity')


def h_args(problem,abi=None):return ('item_size','remaining_capacities') if problem=='obp' and abi=='obp-vector-h-v1' else fjsp_h.H_ARGS if problem=='fjsp' else tsp_h.H_ARGS if problem=='tsp' else OBP_ARGS


def validate_h(problem,code,description=''):
    if problem=='fjsp':return fjsp_h.validate_code(code,description=description,kind='h')
    if problem=='tsp':return tsp_h.validate(code,description,'h',1)
    # Reuse the existing closed numerical AST validator, changing only the ABI.
    tree=ast.parse(code);f=tree.body[0] if len(tree.body)==1 else None
    if isinstance(f,ast.FunctionDef) and tuple(a.arg for a in f.args.args)==('item_size','remaining_capacities'):
        from . import obp_h
        return obp_h.validate(code,description)
    if not isinstance(f,ast.FunctionDef) or tuple(a.arg for a in f.args.args)!=OBP_ARGS:raise ValueError('OBP requires priority(item_size, remaining_capacity)')
    if any(isinstance(n,ast.Name) and n.id in tsp_h.H_ARGS for n in ast.walk(tree)):raise ValueError('reserved numerical-validator bridge name in OBP H')
    allowed=set(OBP_ARGS)|set(tsp_h.BUILTINS)|{n.id for n in ast.walk(tree) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
    if any(isinstance(n,ast.Name) and n.id not in allowed for n in ast.walk(tree)):raise ValueError('OBP external name')
    names=dict(zip(OBP_ARGS,tsp_h.H_ARGS[:2]))
    class Rename(ast.NodeTransformer):
        def visit_Name(self,n):return ast.copy_location(ast.Name(names.get(n.id,n.id),n.ctx),n)
    bridge=Rename().visit(tree);bridge.body[0].args.args=[ast.arg(arg=a) for a in tsp_h.H_ARGS]
    checked=tsp_h.validate(ast.unparse(bridge),description,'h',1)
    inverse={v:k for k,v in names.items()}
    class Restore(ast.NodeTransformer):
        def visit_Name(self,n):return ast.copy_location(ast.Name(inverse.get(n.id,n.id),n.ctx),n)
    restored=Restore().visit(ast.parse(checked.code));restored.body[0].args.args=[ast.arg(arg=a) for a in OBP_ARGS]
    canonical=ast.unparse(restored)+'\n'
    return tsp_h.Candidate(description,canonical,digest({'ABI':'obp-two-scalar-h-v1','AST':ast.dump(restored,include_attributes=False)}),'h')


def checked_h(problem,row):
    c=validate_h(problem,row['code'],row['description'])
    if c.key!=row['key'] or row['kind']!='h':raise ValueError('H identity mismatch')
    return c


def parse_h(problem,text):
    if problem=='fjsp':return fjsp_h.parse_response(text,kind='h')
    if problem=='tsp':return tsp_h.parse(text,'h',1)
    match=re.fullmatch(r'\s*(.*?)\s*```python\s*\n(.*?)\n```\s*',text,re.S)
    if not match or text.count('```')!=2:raise ValueError('one description and complete python fence required')
    desc,code=match.groups();desc=desc.strip().strip('{}').strip()
    if not desc or len(desc)>1000:raise ValueError('description required')
    return validate_h(problem,code,desc)


def compile_h(problem,row):
    c=checked_h(problem,row)
    if problem=='fjsp':return fjsp_h.compile_candidate(c)
    if problem=='tsp':return tsp_h.compile_candidate(c,1)
    tree=ast.parse(c.code)
    if tuple(a.arg for a in tree.body[0].args.args)==('item_size','remaining_capacities'):
        from . import obp_h
        return obp_h.compile_candidate(c)
    names=dict(zip(OBP_ARGS,tsp_h.H_ARGS[:2]))
    class Rename(ast.NodeTransformer):
        def visit_Name(self,n):return ast.copy_location(ast.Name(names.get(n.id,n.id),n.ctx),n)
    tree=Rename().visit(tree);tree.body[0].args.args=[ast.arg(arg=a) for a in tsp_h.H_ARGS]
    fn=tsp_h.compile_candidate(tsp_h.validate(ast.unparse(tree),c.description,'h',1),1)
    return lambda item,remaining:fn(item,remaining,0.,0.,0.)


def validate_obp_instance(value):
    if set(value)!={'capacity','items'} or type(value['capacity']) not in (int,float) or not math.isfinite(value['capacity']) or value['capacity']<=0:raise ValueError('OBP instance requires capacity and ordered items')
    if not value['items'] or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<x<=value['capacity'] for x in value['items']):raise ValueError('OBP arrivals must be finite in (0,capacity]')


def obp_lower_bound(value,policy):
    validate_obp_instance(value)
    if policy!='volume_ceiling':raise ValueError('unapproved/unsupported OBP bound; no guessed reference')
    ratio=sum((Fraction(str(x)) for x in value['items']),Fraction(0))/Fraction(str(value['capacity']))
    return (ratio.numerator+ratio.denominator-1)//ratio.denominator


def validate_obp_solution(instance,solution,action_policy):
    validate_obp_instance(instance);items=instance['items'];cap=instance['capacity'];used=[0]*len(items) if action_policy=='preallocated_empty_bins' else []
    if set(solution)!={'placements','used','bin_count'} or len(solution['placements'])!=len(items):raise ValueError('one OBP placement per arrival required')
    for item,b in zip(items,solution['placements']):
        if type(b) is not int or not 0<=b<=(len(used)-1 if action_policy=='preallocated_empty_bins' else len(used)):raise ValueError('invalid / noncanonical OBP bin')
        fitting=[i for i,x in enumerate(used) if x+item<=cap]
        if b==len(used):
            if action_policy=='fit_only_else_new' and fitting:raise ValueError('new bin forbidden while an old bin fits')
            used.append(item)
        else:
            if b not in fitting:raise ValueError('capacity violation')
            used[b]+=item
    if used!=solution['used'] or sum(x>0 for x in used)!=solution['bin_count']:raise ValueError('bin count/load mismatch')


def state_provider(c):
    delivery=c.get('state_delivery')
    if c['problem']!='obp':return None
    if not isinstance(delivery,dict):raise ValueError('OBP state delivery required; action-domain change cannot reuse old assumptions')
    if c['mode']=='real' and (delivery.get('status')!='delivered_code' or c['obp_actions'] not in delivery.get('supported_actions',[])):raise ValueError('D08 conditional definition is not a delivered action-compatible state module')
    module=delivery['module'];path=Path(delivery['file'])
    if sha(path)!=delivery['sha256'] or delivery['action_policy']!=c['obp_actions']:raise ValueError('OBP action/state binding mismatch')
    import importlib
    provider=importlib.import_module(module)
    if Path(provider.__file__).resolve()!=path.resolve():raise ValueError('state module/file identity differs')
    if not callable(getattr(provider,'extract',None)):raise ValueError('state delivery must export extract(current_item, opened_used, capacity, history)')
    return provider


def solve_obp(instance,hs,u,c):
    # Only this host owns the full stream. H and U see one arrival/current state.
    validate_obp_instance(instance);provider=state_provider(c);history=state.History(len(instance['items']),len(hs));used=[0]*len(instance['items']) if c['obp_actions']=='preallocated_empty_bins' else [];placements=[];sequence=[];calls=[0]*len(hs)
    for item in instance['items']:
        packet,actions=provider.extract(item,tuple(used),instance['capacity'],history)
        state.validate_packet(packet,len(hs))
        fitting=tuple(i for i,x in enumerate(used) if x+item<=instance['capacity'])
        policy=c['obp_actions']
        if policy=='fit_only_else_new':expected=fitting or (len(used),)
        elif policy=='fit_and_one_virtual_new':expected=fitting+(len(used),)
        elif policy=='preallocated_empty_bins':expected=fitting
        else:raise ValueError('OBP action domain still pending; preallocated-empty-bin ABI needs a delivered adapter')
        if tuple(actions)!=expected:raise ValueError('delivered OBP state/action enumeration differs from frozen policy')
        member=u_language.language.route_token(u(packet),len(hs))
        scores=[]
        vector=None
        if c['obp_h_abi']=='obp-vector-h-v1':
            capacities=tuple(instance['capacity']-x for x in used)+( (instance['capacity'],) if policy!='preallocated_empty_bins' else ())
            vector=hs[member](item,capacities);calls[member]+=1
            if not isinstance(vector,(tuple,list)) or len(vector)!=len(capacities):raise ValueError('vector H must return one score per declared bin')
        elif c['obp_h_abi']!='obp-two-scalar-h-v1':raise ValueError('OBP H ABI pending / unsupported')
        for b in actions:
            remaining=instance['capacity']-used[b] if b<len(used) else instance['capacity']
            score=vector[b] if vector is not None else hs[member](item,remaining)
            if vector is None:calls[member]+=1
            if type(score) not in (int,float) or not math.isfinite(score):raise ValueError('nonfinite OBP H priority')
            scores.append(score)
        b=actions[max(range(len(actions)),key=lambda i:scores[i])];delta=int(b==len(used) or used[b]==0)
        if b==len(used):used.append(item)
        else:used[b]+=item
        placements.append(b);sequence.append(member);history.commit(member,delta)
    result={'placements':placements,'used':used,'bin_count':sum(x>0 for x in used)}
    validate_obp_solution(instance,result,c['obp_actions'])
    return result,sequence,calls


def load_inputs(c):
    problem=c['problem'];manifest=read(c['data_manifest'])
    if manifest['problem']!=problem or manifest['split']!='train':raise ValueError('only explicit training manifest is allowed')
    rows=[]
    for item in manifest['instances']:
        source=(Path(c['data_manifest']).parent/item['path']).resolve()
        if sha(source)!=item['sha256']:raise ValueError('instance content changed')
        if problem=='fjsp':
            from llm4ad.task.optimization.fjsp_set.instances import load_instance
            obj=load_instance(source);value={'machines':obj.machine_count,'jobs':[[[list(a) for a in op.alternatives] for op in job] for job in obj.jobs]}
        else:value=read(source)
        if problem=='obp':validate_obp_instance(value)
        rows.append({'file':item.get('file',source.name),'split':'train','value':value,'sha256':digest(value),'source_sha256':item['sha256']})
    if not rows or c['instance_count']!=len(rows):raise ValueError('declared instance count differs')
    if problem=='fjsp':refs=fixtures.precheck_instances(problem,rows)
    elif problem=='obp':refs=[{'file':r['file'],'reference':obp_lower_bound(r['value'],c['obp_bound'])} for r in rows];state_provider(c)
    else:
        packet=read(c['reference_file'])
        if packet.get('kind')=='mock-reference-v1' and c['mode']=='mock':
            refs=packet['instances']
            if len(refs)!=len(rows) or any(v['file']!=r['file'] for v,r in zip(refs,rows)):raise ValueError('Mock reference order mismatch')
        else:
            if packet.get('distance_protocol')!={'input':'unit-square-float64-euclidean','LKH_edge_type':'EXPLICIT','integer_rounding':'floor(scale*d+0.5)','reference_cost':'recomputed-original-distance-closed-tour'}:raise ValueError('unsupported LKH distance/reference mapping')
            if packet['kind']!='fixed-LKH-reference-v1' or not packet.get('lkh_identity') or not packet.get('parameters') or not packet.get('distance_protocol'):raise ValueError('frozen LKH identity/parameters/distance protocol required; NN fallback prohibited')
            refs=packet['instances']
            if len(refs)!=len(rows):raise ValueError('complete ordered LKH references required')
            from heuristic_design.problems.tsp.solver import distances,tour_length
            for row,ref in zip(rows,refs):
                if ref['file']!=row['file'] or ref['instance_sha256']!=row['sha256'] or ref['source']!='LKH':raise ValueError('LKH input identity mismatch')
                cost=tour_length(distances(row['value']['coordinates']),ref['tour'])
                if not math.isclose(cost,ref['reference'],rel_tol=1e-12,abs_tol=1e-12):raise ValueError('LKH tour/reference distance mismatch')
    hs=[]
    if c.get('h_file'):
        raw=read(c['h_file'])
        if c['mode']=='real' and isinstance(raw,dict) and raw.get('engineering_only'):raise ValueError('engineering H asset cannot enter real search')
        members=raw['members'] if isinstance(raw,dict) else raw
        hs=[r.get('candidate',r) for r in members]
        for row in hs:
            checked_h(problem,row)
            if problem=='obp':
                actual='obp-vector-h-v1' if tuple(a.arg for a in ast.parse(row['code']).body[0].args.args)==('item_size','remaining_capacities') else 'obp-two-scalar-h-v1'
                if actual!=c['obp_h_abi']:raise ValueError('frozen OBP H ABI differs from configured protocol')
        if len({r['key'] for r in hs})!=len(hs):raise ValueError('frozen H must be AST distinct')
    return rows,refs,hs


def solve_row(spec,members,candidate,c,reference):
    problem=c['problem'];hs=[compile_h(problem,h) for h in members]
    u=u_language.compile_candidate(u_language.checked(candidate,len(hs)),len(hs))
    if problem=='fjsp':
        from heuristic_design.problems.fjsp.routing import construct_state_a_v3
        result=construct_state_a_v3(fixtures.decode_instance(problem,spec),hs,u,trace=False)
        solution=asdict(result.schedule);raw=result.schedule.makespan;seq=list(result.member_sequence);calls=list(result.h_calls)
    elif problem=='tsp':
        from heuristic_design.problems.tsp.solver import distances
        from heuristic_design.problems.tsp.routing import construct
        from heuristic_design.core.constructive_state import GROUPS
        result=construct(distances(spec['value']['coordinates']),hs,u,state_schema=state.schema_id(problem),reference=reference,enabled_groups=GROUPS,trace=False)
        solution={'tour':list(result.tour),'length':result.length};raw=result.length;seq=list(result.member_sequence);calls=list(result.h_calls)
    else:
        solution,seq,calls=solve_obp(spec['value'],hs,u,c);raw=solution['bin_count']
    return dict(file=spec['file'],solution=solution,raw_cost=raw,reference=reference,score=state.score_final_cost(raw,reference),member_sequence=seq,h_calls=calls)
