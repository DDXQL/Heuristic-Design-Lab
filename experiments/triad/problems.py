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


def h_args(problem,abi=None):return ('item_size','remaining_capacities') if problem=='obp' and abi=='obp-vector-feasible-h-v2' else fjsp_h.H_ARGS if problem=='fjsp' else tsp_h.H_ARGS if problem=='tsp' else OBP_ARGS


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
    if set(value) not in ({'capacity','items'},{'capacity','items','N'}) or type(value['capacity']) not in (int,float) or not math.isfinite(value['capacity']) or value['capacity']<=0:raise ValueError('OBP instance requires capacity and ordered items')
    if 'N' in value and (type(value['N']) is not int or value['N']<=0 or value['N']!=len(value['items'])):raise ValueError('public N and actual arrival count differ')
    if not value['items'] or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<x<=value['capacity'] for x in value['items']):raise ValueError('OBP arrivals must be finite in (0,capacity]')


OBP_CONTRACT_VERSION='obp-feasible-permanent-actions-v2'


def obp_reference_spec(policy):
    # Legacy string is retained ONLY for explicitly labelled engineering fixtures.
    if policy=='volume_ceiling':return {'version':'obp-volume-ceiling-v1','rule':'ceil(S/C)'}
    choices={'obp-volume-ceiling-v1':'ceil(S/C)','obp-R-code-int64-float64-v1':'int(float64(sum_int64(items))/float64(C)+0.5)'}
    if not isinstance(policy,dict) or set(policy)!={'version','rule'} or choices.get(policy['version'])!=policy['rule']:
        raise ValueError('explicit versioned OBP reference required; rounding rules are not interchangeable')
    return policy


def obp_reference_details(value,policy):
    import numpy as np
    validate_obp_instance(value);spec=obp_reference_spec(policy)
    if spec['version']=='obp-R-code-int64-float64-v1':
        limit=int(np.iinfo(np.int64).max)
        if type(value['capacity']) is not int or value['capacity']>limit or any(type(x) is not int or x>limit for x in value['items']):raise ValueError('R_code formal domain requires positive integer sizes/capacity within int64, not general float inputs')
        exact=sum(value['items'])
        if exact>limit:raise ValueError('int64 full-sequence sum overflow; no wrapped reference')
        total=np.sum(np.asarray(value['items'],dtype=np.int64),dtype=np.int64)
        if int(total)!=exact:raise ValueError('int64 sum differs from overflow check')
        scaled=np.float64(total)/np.float64(value['capacity'])+np.float64(0.5)
        if not np.isfinite(scaled):raise ValueError('nonfinite float64 R_code calculation')
        reference=int(scaled)
        detail={'S':int(total),'C':value['capacity'],'reference':reference,'sum_dtype':str(total.dtype),'calculation_dtype':str(scaled.dtype),'cast':'Python int, positive truncation','numpy_version':np.__version__}
    else:
        ratio=sum((Fraction(str(x)) for x in value['items']),Fraction(0))/Fraction(str(value['capacity']))
        reference=(ratio.numerator+ratio.denominator-1)//ratio.denominator
        detail={'S':str(sum((Fraction(str(x)) for x in value['items']),Fraction(0))),'C':value['capacity'],'reference':reference,'arithmetic':'exact rational ceiling; separate reference identity'}
    if reference<=0:raise ValueError('OBP reference is zero; J denominator invalid; never clamp or substitute ceiling')
    return {**detail,'reference_identity':spec}


def obp_lower_bound(value,policy):return obp_reference_details(value,policy)['reference']


def obp_contract(c):
    return {'version':OBP_CONTRACT_VERSION,'actions':c['obp_actions'],'H_ABI':c['obp_h_abi'],
      'feasibility':'(capacity-used_load)-item >= 0 without epsilon; no infeasible bin enters H',
      'capacity_representation':'used loads updated by +item; residual derived capacity-used; this is an explicit project adapter, not bitwise NumPy-run equivalence',
      'vector_input':'immutable tuple of ALL feasible bin capacities; permanent IDs ascending; preserve every feasible empty bin',
      'vector_output':'list/tuple of finite built-in real scores, exact legal-action length; local argmax maps to permanent ID',
      'tie':'smallest feasible permanent bin ID','H_calls':('one selected vector H call per arrival; no nonselected H call' if c['obp_h_abi']=='obp-vector-feasible-h-v2' else 'selected scalar H per feasible action; no nonselected H call'),
      'reference':obp_reference_spec(c['obp_bound']),
      'public_state_spec':state.SPEC_SHA256,'state_delivery_sha256':(c.get('state_delivery') or {}).get('sha256'),
      'language':'closed Python arithmetic and one bounded current-bin comprehension; no imports, numpy or future stream; NOT native NumPy candidate compatibility'}


def legal_obp_actions(item,used,capacity,policy):
    if type(item) not in (int,float) or not math.isfinite(item) or not 0<item<=capacity:raise ValueError('invalid current arrival')
    if any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=capacity for x in used):raise ValueError('invalid bin loads')
    fitting=tuple(i for i,x in enumerate(used) if capacity-x-item>=0)
    if policy=='preallocated_empty_bins':return fitting
    if policy=='fit_and_one_virtual_new':return fitting+(len(used),)
    if policy=='fit_only_else_new':return fitting or (len(used),)
    raise ValueError('unapproved / unsupported OBP action domain')


def obp_choose_action(item,used,capacity,actions,selected_callback,abi,policy):
    actions=tuple(actions);expected=legal_obp_actions(item,used,capacity,policy)
    if actions!=expected or not actions:raise ValueError('all feasible actions in permanent-ID order required before H')
    capacities=tuple(capacity-used[b] if b<len(used) else capacity for b in actions)
    return _score_obp_actions(item, actions, capacities, selected_callback, abi)


def _score_obp_actions(item, actions, capacities, selected_callback, abi):
    """Score the host's ordered feasible actions using the unchanged H ABI."""
    if not actions:
        raise ValueError('all feasible actions in permanent-ID order required before H')
    if abi=='obp-vector-feasible-h-v2':
        scores=selected_callback(item,capacities);calls=1
        if not isinstance(scores,(tuple,list)) or len(scores)!=len(actions):raise ValueError('vector H output must match feasible input length')
        scores=tuple(scores)
    elif abi=='obp-two-scalar-h-v1':
        scores=tuple(selected_callback(item,x) for x in capacities);calls=len(actions)
    else:raise ValueError('retired or unsupported OBP H ABI; explicit migration required')
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in scores):raise ValueError('finite built-in real H scores required')
    local=max(range(len(actions)),key=lambda i:scores[i])
    return {'bin_index':actions[local],'local_index':local,'actions':actions,'capacities':capacities,'scores':scores,'H_calls':calls}


def validate_obp_solution(instance,solution,action_policy):
    validate_obp_instance(instance);items=instance['items'];cap=instance['capacity'];used=[0]*len(items) if action_policy=='preallocated_empty_bins' else []
    if set(solution)!={'placements','used','bin_count'} or len(solution['placements'])!=len(items):raise ValueError('one OBP placement per arrival required')
    for item,b in zip(items,solution['placements']):
        if type(b) is not int or not 0<=b<=(len(used)-1 if action_policy=='preallocated_empty_bins' else len(used)):raise ValueError('invalid / noncanonical OBP bin')
        if b==len(used):
            if action_policy=='fit_only_else_new' and any(cap-x-item>=0 for x in used):raise ValueError('new bin forbidden while an old bin fits')
            used.append(item)
        else:
            if cap-used[b]-item<0:raise ValueError('capacity violation')
            used[b]+=item
    if used!=solution['used'] or sum(x>0 for x in used)!=solution['bin_count']:raise ValueError('bin count/load mismatch')


def state_provider(c):
    delivery=c.get('state_delivery')
    if c['problem']!='obp':return None
    if not isinstance(delivery,dict):raise ValueError('OBP state delivery required; action-domain change cannot reuse old assumptions')
    if c['mode']=='real' and (delivery.get('status')!='delivered_code' or delivery.get('adoption')!='adopted' or c['obp_actions'] not in delivery.get('supported_actions',[])):raise ValueError('D08 conditional definition is not a delivered action-compatible state module')
    module=delivery['module'];path=Path(delivery['file'])
    if sha(path)!=delivery['sha256'] or delivery['action_policy']!=c['obp_actions']:raise ValueError('OBP action/state binding mismatch')
    import importlib
    provider=importlib.import_module(module)
    if Path(provider.__file__).resolve()!=path.resolve():raise ValueError('state module/file identity differs')
    if not callable(getattr(provider,'extract',None)):raise ValueError('state delivery must export extract(current_item, opened_used, capacity, history)')
    return provider


def solve_obp(instance, hs, u, c):
    """Place each arrival in order. A missing selector means a single fixed H."""
    validate_obp_instance(instance)
    provider = state_provider(c)
    items, capacity = instance['items'], instance['capacity']
    policy = c['obp_actions']
    preset = policy == 'preallocated_empty_bins'
    use_fixed_h = u is None
    if use_fixed_h and len(hs) != 1:
        raise ValueError('fixed OBP evaluation requires exactly one H')
    # Inside the int64 domain, both residual subtraction and feasible load
    # updates are exact. Other inputs retain Python arithmetic.
    provider_checks_actions = preset and provider.__name__ == f'{__package__}.obp_state_preset'
    integer_bins = (preset and type(capacity) is int and capacity <= 2**63 - 1
                    and all(type(item) is int for item in items))
    fast_u = integer_bins and provider_checks_actions and not use_fixed_h and capacity <= 1024
    if fast_u:
        from . import obp_fast_state
    vectorized = integer_bins and (use_fixed_h or fast_u)
    if vectorized:
        import numpy as np
        used = np.zeros(len(items), dtype=np.int64)
    else:
        used = [0] * len(items) if preset else []
    history = None if use_fixed_h else state.History(len(items), len(hs))
    placements, sequence, calls = [], [], [0] * len(hs)
    for item in items:
        if fast_u:
            packet, actions, capacities = obp_fast_state.extract(item, used, capacity, history)
        elif history is not None:
            packet, actions = provider.extract(item, tuple(used), capacity, history)
            actions = tuple(actions)
            # The bound D08 provider calls legal_obp_actions itself. Retain the
            # independent check for other delivered state providers.
            if not provider_checks_actions and actions != legal_obp_actions(item, used, capacity, policy):
                raise ValueError('delivered state/action domain differs from frozen protocol')
            capacities = tuple(capacity - used[b] if b < len(used) else capacity for b in actions)
        elif vectorized:
            remaining = capacity - used
            fitting = np.flatnonzero(remaining - item >= 0)
            actions = tuple(fitting.tolist())
            capacities = tuple(remaining[fitting].tolist())
        else:
            actions = legal_obp_actions(item, used, capacity, policy)
            capacities = tuple(capacity - used[b] if b < len(used) else capacity for b in actions)
        if history is None:
            member = 0
        else:
            state.validate_packet(packet, len(hs))
            member = u_language.language.route_token(u(packet), len(hs))
        selected = _score_obp_actions(item, actions, capacities, hs[member], c['obp_h_abi'])
        calls[member] += selected['H_calls']
        b = selected['bin_index']
        delta = int(b == len(used) or used[b] == 0)
        if b == len(used):
            used.append(item)
        else:
            used[b] += item
        placements.append(b)
        sequence.append(member)
        if history is not None:
            history.commit(member, delta)
    if vectorized:
        used = used.tolist()
    result = {'placements': placements, 'used': used, 'bin_count': sum(x > 0 for x in used)}
    validate_obp_solution(instance, result, policy)
    return result, sequence, calls


def load_inputs(c, *, allowed_splits=('train',), manifest=None):
    problem=c['problem'];manifest=read(c['data_manifest']) if manifest is None else manifest
    split=manifest['split']
    if manifest['problem']!=problem or split not in allowed_splits:raise ValueError('explicit allowed split manifest required')
    rows=[]
    for item in manifest['instances']:
        source=(Path(c['data_manifest']).parent/item['path']).resolve()
        if sha(source)!=item['sha256']:raise ValueError('instance content changed')
        if problem=='fjsp':
            from llm4ad.task.optimization.fjsp_set.instances import load_instance
            obj=load_instance(source);value={'machines':obj.machine_count,'jobs':[[[list(a) for a in op.alternatives] for op in job] for job in obj.jobs]}
        else:value=read(source)
        if problem=='obp':
            validate_obp_instance(value)
            if c['mode']=='real' and 'N' not in value:raise ValueError('formal OBP instance must bind explicit public N')
        rows.append({'file':item.get('file',source.name),'split':split,'value':value,'sha256':digest(value),'source_sha256':item['sha256']})
    if not rows or c['instance_count']!=len(rows):raise ValueError('declared instance count differs')
    if problem=='fjsp':
        if split=='train':
            refs=fixtures.precheck_instances(problem,rows)
        else:
            from heuristic_design.problems.fjsp.common_state import precheck
            from fjsp_usage.offline_v2 import lower_bound_v5
            refs=[]
            for row in rows:
                instance=decode_fjsp(row, split)
                precheck(instance)
                refs.append({'file':row['file'],'reference':lower_bound_v5(instance),'rule':'LB_v5'})
    elif problem=='obp':
        if c['mode']=='real' and not isinstance(c['obp_bound'],dict):raise ValueError('real OBP requires an explicitly versioned reference; old alias is engineering-only')
        refs=[{'file':r['file'],**obp_reference_details(r['value'],c['obp_bound'])} for r in rows];state_provider(c)
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
        if problem=='fjsp' and c['mode']=='real' and c.get('candidate_policy'):
            provenance=Path(__file__).resolve().parents[2]/'preparations/triad/fjsp/provenance.json'
            if sha(Path(c['h_file']))!=read(provenance)['H_sha256']:
                raise ValueError('FJSP U requires the original frozen 10H bytes and order')
        members=raw['members'] if isinstance(raw,dict) else raw
        hs=[r.get('candidate',r) for r in members]
        if problem=='obp' and c['mode']=='real' and (not isinstance(raw,dict) or raw.get('obp_contract_sha256')!=digest(obp_contract(c))):raise ValueError('OBP H asset lacks current feasible-input/action/reference identity; no silent reuse')
        for row in hs:
            checked_h(problem,row)
            if problem=='obp':
                actual='obp-vector-feasible-h-v2' if tuple(a.arg for a in ast.parse(row['code']).body[0].args.args)==('item_size','remaining_capacities') else 'obp-two-scalar-h-v1'
                if actual!=c['obp_h_abi']:raise ValueError('frozen OBP H ABI differs from configured protocol')
        if len({r['key'] for r in hs})!=len(hs):raise ValueError('frozen H must be AST distinct')
        if problem=='obp' and c['mode']=='real' and len(hs)!=10:
            raise ValueError('real OBP routing and fixed-H require the frozen H401 set of 10 rules')
    return rows,refs,hs


def decode_fjsp(row, holdout_split=None):
    if holdout_split is None:
        return fixtures.decode_instance('fjsp',row)
    if row['split']!=holdout_split or holdout_split not in ('validation','test','prospective-confirmation'):
        raise ValueError('FJSP evaluation requires the bound holdout split')
    # Adapt only the decoder's private argument. The evidence retains the original split.
    return fixtures.decode_instance('fjsp',{**row,'split':'train'})


def solve_row(spec,members,candidate,c,reference):
    problem=c['problem'];hs=[compile_h(problem,h) for h in members]
    if isinstance(candidate, dict) and candidate.get('kind') == 'evolutionary-prototype-router-v1':
        from experiments.prototype_hh.model import compile_selector
        u = compile_selector(candidate, len(hs))
    else:
        u = None if problem == 'obp' and candidate is None else u_language.compile_candidate(
            u_language.checked(candidate, len(hs)), len(hs))
    if problem=='fjsp':
        from heuristic_design.problems.fjsp.routing import construct_state_a_v3
        result=construct_state_a_v3(decode_fjsp(spec,c.get('holdout_split')),hs,u,trace=False)
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
