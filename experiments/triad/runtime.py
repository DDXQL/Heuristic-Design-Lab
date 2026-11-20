"""Versioned adapters over core.execution; native EoH and parent-coverage planning reused."""
from dataclasses import asdict
import copy
import importlib.util
import math
import os
from pathlib import Path
import random
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'deploy/eoh-baseline'))
import eoh_gap as old
import prompt_contract as h_contract
from heuristic_design.core import execution,evolution_v1,routing_state_a_v3 as language,state_a_v3
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.core.search import ranked,survive,_tuple_tree
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport
from . import problems,evaluation,candidate_policy
from .configuration import candidate_drain,load,gaps
VERSION='triad-six-groups-operations-v5'


def sources():
    values=old.sources()
    for p in (ROOT/'experiments/triad').glob('*.py'):values[str(p.relative_to(ROOT))]=sha(p)
    wire='code/fjsp_usage/research_real/real_transport.py'
    values[wire]=sha(ROOT/wire)
    return values


def protocol_state(directory):
    directory=Path(directory);p=read(directory/'Protocol.json');s=read(directory/'checkpoint.json')
    if p['version']!=VERSION or sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip() or s['identity']!=sha(directory/'Protocol.json'):raise ValueError('triad identity mismatch; no legacy reinterpretation')
    return p,s


def h_build_config(c):
    c=copy.deepcopy(c);h=c['h_build'];engineering=c['mode']=='mock'
    c.update(search_seed=h.get('search_seed',c['search_seed'] if engineering else None),
      window_seconds=h.get('window_seconds',c['window_seconds'] if engineering else None),
      api_attempt_cap=h.get('request_cap'),initialization_request_cap=h.get('request_cap'),evolution_request_cap=0,
      h_file=None,evaluation_concurrency=1)
    return c


def preflight(path,engineering=False,run_kind=None):
    c=load(path,engineering=engineering)
    if run_kind=='h-build':
        if c.get('candidate_policy'):raise ValueError('H construction has its own frozen budget and runner')
        c=h_build_config(c);todo=gaps(c)
        ignored={'repeat_count','search_seeds','population_size','h_file','budget_basis','initialization_policy'}
        todo=[key for key in todo if key not in ignored]
        for key in ('request_cap','target_count','selection','search_seed','window_seconds'):
            if c['h_build'].get(key) is None and c['mode']!='mock':todo.append('h_build.'+key)
    else:
        todo=gaps(c)
        if c.get('search_seed') is None:todo.append('select_independent_seed')
        elif c['search_seeds'] is None or c['search_seed'] not in c['search_seeds']:raise ValueError('search seed outside frozen declaration')
    if todo:return c,None,None,None,todo
    data,refs,hs=problems.load_inputs(c)
    if run_kind!='h-build' and c['method']=='u' and not hs:raise ValueError('U needs a frozen H asset')
    for n,h in c['client_binding']['files'].items():
        actual=sha(ROOT/n)
        # R15 development release admits one reviewed V5 audit-only revision.
        # Existing released bindings and original R15p3 files are untouched.
        overlay=(n=='code/fjsp_usage/research_real/real_transport.py'
                 and h=='592e531494407644de13688101dcee224045ecdc5c155583dc75039966767618'
                 and actual=='65c3b290091981f45758c9e4369cccd08a061e621522467103f53ab8d44d59cc')
        if actual!=h and not overlay:raise ValueError('admitted V5 client changed')
    if c['provider']!=c['client_binding']['provider'] or c['client_binding']!=read(ROOT/'deploy/eoh-baseline/unified-inputs.json')['client_binding']:raise ValueError('provider/V5 binding differs from unified current U identity')
    if c['problem']=='fjsp':
        expected=read(ROOT/'deploy/eoh-baseline/unified-inputs.json')['train21_order']
        if [{'file':r['file'],'source_sha256':r['source_sha256']} for r in data]!=expected:raise ValueError('frozen train21 order/content differs')
    r=c['resources'];width=max(c['api_concurrency'],c['evaluation_concurrency'])
    drain=math.ceil(width/c['api_concurrency'])*c['provider']['total_timeout']+len(data)*30+width+7
    if c.get('candidate_policy'):
        drain=candidate_drain(c,r.get('request_queue_seconds',600))
    if r['drain_seconds']<drain or min(r['segment_seconds'],c['window_seconds'])<=r['drain_seconds']:raise ValueError('resource window/drain cannot cover bounded staged wave')
    if not (c['problem']=='fjsp' and c['method']=='u' and c['mode']=='real') and c['evaluation_concurrency']!=1:raise ValueError('native EoH preserves serial evaluation/feedback')
    return c,data,refs,hs,[]


def prepare(directory,path,*,engineering=False,allow_api=False,approve_budget=None,run_kind=None):
    c,data,refs,hs,todo=preflight(path,engineering,run_kind)
    if todo:raise PermissionError('PROTOCOL_PENDING: '+', '.join(todo))
    expected=c['h_build']['request_cap'] if run_kind=='h-build' else c['api_attempt_cap']
    if c['mode']=='real' and (not allow_api or approve_budget!=expected):raise PermissionError('manual original cumulative request cap approval required')
    if c['mode']=='mock' and (allow_api or approve_budget is not None):raise PermissionError('Mock cannot carry real approval')
    directory=Path(directory).resolve()
    if directory.exists() or not directory.is_relative_to(ROOT/'runs'):raise ValueError('new independent runs directory required')
    kind=run_kind or c['method'];cap=c['api_attempt_cap'];init=c['initialization_request_cap'];evo=c['evolution_request_cap']
    if kind=='h-build':
        cap=init=c['h_build']['request_cap'];evo=0
        if type(cap) is not int or cap<1 or type(c['h_build']['target_count']) is not int or c['h_build']['target_count']<1:raise ValueError('separate H-build budget and target required')
        if c['mode']=='real' and approve_budget!=cap:raise PermissionError('separate H-build request cap required')
    runtime={**c,'api_mode':c['mode'],'evaluation_mode':'mock' if c['mode']=='mock' else 'solve','real_requests_authorized':c['mode']=='real',
      'candidate_cap':cap,'api_attempt_cap':cap,'evolution_request_cap':evo,'initialization_request_cap':init,'initialization_sample_cap':2*c['population_size'] if c['population_size'] is not None else None,
      'selection_num':2,'type':'triad-native','candidate_kind':'U' if kind=='u' else 'h','recording_mode':'compact','window':10,'enabled_groups':list(evolution_v1.GROUPS),'cross_parents':2}
    directory.mkdir(parents=True)
    write(directory/'Tasks.json',[{'id':f'SLOT-{i:07d}','stage':'new','generation':None,'operator':'adaptive_slot'} for i in range(cap)])
    evaluation_cap=init+evo if c.get('candidate_policy') else cap
    p=dict(version=VERSION,run_kind=kind,config=runtime,members=hs if kind=='u' else [],instances=data,references=refs,source_files=sources(),
      state_schema=state_a_v3.schema_id(c['problem']),tasks_sha256=sha(directory/'Tasks.json'),config_sha256=sha(path),
      metrics={'objective':'J=mean((raw_cost-reference)/reference)','direction':'min','internal_score':'-J','final_selection':'all complete valid candidates; J ascending, semantic ID ascending'},
      run_id=directory.name,source_cost={'H_attempts':None},budgets=dict(logical_generation=cap,API_attempts=cap,initialization=init,evolution=evo,max_program_instances=evaluation_cap*len(data),max_solve_passes=2*evaluation_cap*len(data)))
    if c['problem']=='obp':p['obp_execution_contract']=problems.obp_contract(c);p['obp_contract_sha256']=digest(p['obp_execution_contract'])
    if c.get('candidate_policy') and kind=='u':
        source=read(Path(c['h_file']))
        h_summary=source.get('API_summary',{}) if isinstance(source,dict) else {}
        p['source_cost'].update(H_file_sha256=sha(Path(c['h_file'])),
                                H_attempts=h_summary.get('request_reservations'),
                                H_sends=h_summary.get('confirmed_sends'),
                                H_usage=h_summary.get('known_usage_subtotal'))
    if kind!='u':p['H_prompt_contract']=h_contract.identity(c['problem'],c.get('obp_h_abi'),problems.obp_contract(c) if c['problem']=='obp' else None)
    write(directory/'Protocol.json',p);(directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    write(directory/'checkpoint.json',dict(identity=sha(directory/'Protocol.json'),phase='prepared',cursor=0,tasks={},evaluations={},population=[],children=[],seen={},generation=0,pause_ack=0,
      generations=[],u_rng=random.Random(c['search_seed']).getstate(),u_plan=None,
      eoh=dict(stage='initialization',native_generation=0,population=[],next_population=[],evaluated_samples=0,initialization_samples=0,initialization_requests=0,operator_cursor=0,evolution_survivals=0,np_rng=None)))
    return p


def obp_u_prompt(c,task,parents,members):
    import json
    from heuristic_design.core.operators import CROSS,MUTATE
    from heuristic_design.core import state_a
    for row in parents:language.checked(row['candidate'],len(members))
    instruction={'INIT':'Design one new pure H selector.','CROSS':CROSS,'MUTATE':MUTATE}[task['operator']]
    return '\n'.join(['Problem obp; '+language.ABI+'; public state '+state_a_v3.SPEC_SHA256,
       instruction,'Return a description and one fenced Python def use_heuristics(state). Return one built-in int H index in 0..'+str(len(members)-1)+'.',
       'Read only literal scalar/per-H-array state paths and availability masks. No imports, loops, mutation, H calls, previews, lookahead or online model requests.',
       'Only current arrival, public total count and current bin state are visible. The frozen host action/H-input/reference contract is:',
       json.dumps(problems.obp_contract(c),sort_keys=True),
       'The 14 information items are the ten numerical definitions plus four committed-history H arrays; auxiliary fields do not count as information items.',
       json.dumps(state_a.DEFINITIONS,sort_keys=True),json.dumps(state_a_v3.H_DEFINITIONS,sort_keys=True),
       'Guard missing entries using the matching availability mask. Minimize complete train J; ties use stable candidate ID.',
       'Frozen H records in immutable order: '+json.dumps(members,sort_keys=True),
       'Original frozen parents: '+json.dumps([{'id':r['id'],'candidate':r['candidate']} for r in parents],sort_keys=True)])


class MockTransport:
    def __init__(self,c,p):self.config=c;self.p=p;self.identity=digest({'mock-triad':p['config'],'kind':p['run_kind']});self.secret=''
    def redact(self,s):return s
    def preflight(self,prompt):
        if len(prompt.encode())>self.config.provider.max_prompt_bytes:raise ValueError('prompt limit')
    def dispatch(self,key,prompt,*,kind,on_sent):
        on_sent();i=int(key.split('SLOT-')[-1].split('/')[0]);c=self.p['config'];fault=c['mock_faults'].get(str(i))
        if fault=='failure':raise TimeoutError('OFFLINE no-network fixture')
        if fault=='invalid':return {'text':'MOCK malformed','usage':None,'metadata':{'mock':True}}
        n=0 if fault=='duplicate' else i
        if kind=='U':code='def use_heuristics(state):\n    return '+str(n%len(self.p['members']))+'\n'
        else:
            args=problems.h_args(c['problem'],c.get('obp_h_abi'));expr='1/0' if fault=='invalid_evaluation' else '-'+args[0]+' + '+str(n/100)+' * '+args[1]
            if c.get('obp_h_abi')=='obp-vector-feasible-h-v2':expr='[(1/0) for cap in remaining_capacities]' if fault=='invalid_evaluation' else '[-item_size + '+str(n/100)+' * cap for cap in remaining_capacities]'
            code='def priority('+', '.join(args)+'):\n    return '+expr+'\n'
        return {'text':'{OFFLINE fixture; not model output}\n```python\n'+code+'```','usage':{'input_tokens':0,'output_tokens':0},'metadata':{'mock':True}}


class Adapter(old.Adapter):
    ROOT=ROOT
    entrypoint='experiments/triad/entry.py'
    def read_state(self,d):return protocol_state(d)
    def check_run(self,d):
        p,s=protocol_state(d)
        if sha(Path(d)/'Tasks.json')!=p['tasks_sha256'] or any(sha(ROOT/n)!=h for n,h in p['source_files'].items()):raise ValueError('frozen tasks/source changed')
        if p['run_kind']!='u' and p.get('H_prompt_contract')!=h_contract.identity(p['config']['problem'],p['config'].get('obp_h_abi'),problems.obp_contract(p['config']) if p['config']['problem']=='obp' else None):raise ValueError('new H prompt contract changed; old protocols cannot be reinterpreted')
        if p['config']['problem']=='obp' and (p.get('obp_execution_contract')!=problems.obp_contract(p['config']) or p.get('obp_contract_sha256')!=digest(problems.obp_contract(p['config']))):raise ValueError('OBP input/action/reference protocol changed; old cache/resume forbidden')
        if 'stop_recovery' in p:
            from .stop_recovery import verify
            verify(d,p)
        elif 'continuation' in p:
            from .native_continuation import verify
            verify(d,p)
        self.p=p;self._engineering_mode=p['config']['api_mode']=='mock';return p
    def members(self,d):return read(Path(d)/'Protocol.json')['members']
    def transport(self,p):
        c=p['config']
        if c['api_mode']=='mock':return MockTransport(self.client_config(p),p)
        if c.get('candidate_policy'):return candidate_policy.CandidateTransport(candidate_policy.client_config(p),c['candidate_policy'])
        return StrictNonstreamTransport(self.client_config(p))
    def journal(self,d,s,p,deadline):
        if p['config'].get('candidate_policy'):
            return candidate_policy.journal(self,Path(d),s,p,deadline)
        if 'stop_recovery' in p:
            from .stop_recovery import journal
            return journal(self,d,s,p,deadline)
        if 'continuation' in p:
            from .native_continuation import journal
            return journal(self,d,s,p,deadline)
        return super().journal(d,s,p,deadline)
    def parse_candidate(self,text,c):
        try:
            if self.p['run_kind']!='u' and old.old.EoHSampler.trim_thought_from_response(text) is None:raise ValueError('native boxed H description required')
            if self.p['run_kind']=='u':return language.parse(text,len(self.p['members']))
            candidate=problems.parse_h(c['problem'],text)
            if c['problem']=='obp':
                import ast
                actual=tuple(arg.arg for arg in ast.parse(candidate.code).body[0].args.args)
                if actual!=problems.h_args('obp',c['obp_h_abi']):raise ValueError('H signature differs from frozen OBP language')
            return candidate
        except Exception as x:raise self.CandidateError(str(x)) from x
    def build_prompt(self,c,task,parents,members):
        if self.p['run_kind']=='u':
            semantic={**task,'operator':task['operator']}
            if c['problem']=='obp':return obp_u_prompt(c,semantic,parents,members)
            return language.build_prompt(c['problem'],semantic,parents,members)
        args=problems.h_args(c['problem'],c.get('obp_h_abi'));template=old.old.Converter.text_to_function('def priority('+', '.join(args)+'):\n    return 0.0\n')
        description=h_contract.description(c['problem'],c.get('obp_h_abi'),problems.obp_contract(c) if c['problem']=='obp' else None)
        op=task['operator'];funcs=[old.old.native.make_function(r['candidate'],r['id'],r['fitness']) for r in parents]
        fn=getattr(old.old.EoHPrompt,'get_prompt_'+op.lower())
        text=fn(description,template) if op=='I1' else fn(description,funcs if op in ('E1','E2') else funcs[0],template)
        return text+'\nHere boxed {} means literal ASCII braces, NOT LaTeX. Return only {description} and one complete python fence as specified above.\n'
    def task_context(self,d,s,p,task,index):
        c=p['config'];v=s['eoh']
        boundary=Path(d)/'Current_manual_boundary.json'
        if boundary.exists():
            control=read(boundary)
            if control['protocol']!=s['identity'] or control['original_request_cap']!=c['api_attempt_cap']:raise ValueError('manual boundary belongs to another original budget')
            if control['settled_prefix'] is not None and s['cursor']>=control['settled_prefix']:
                s.update(phase='paused',pause_reason='manual finite settled-attempt boundary; original budget retained');return None,[]
        if getattr(self,'segment_deadline',None) and time.monotonic()+c['resources']['drain_seconds']>self.segment_deadline:
            reason=candidate_policy.TIME_PAUSE if c.get('candidate_policy') else 'segment drain before next reservation'
            s.update(phase='paused',pause_reason=reason);return None,[]
        if p['run_kind']=='h-build':return {**task,'operator':'I1','semantic_id':f'H-{index:05d}','phase':'initialization'},[]
        if p['run_kind']=='eoh':
            row,parents=super().task_context(d,s,p,task,index)
            if row is not None and c['initialization_policy']=='native_N_finite_or_fail' and s['eoh']['stage']=='evolution' and len(s['population'])!=c['population_size']:
                s.update(phase='initialization_incomplete',pause_reason='native initialization ended with fewer than N finite distinct parents; no refill');return None,[]
            return row,parents
        if v['stage']=='initialization':
            if len(s['population'])==c['population_size']:v['stage']='evolution';s['population']=ranked(s['population'])
            elif v['initialization_requests']>=min(c['initialization_request_cap'],c['population_size'] if c['initialization_policy']=='fixed_population_slots_no_refill' else c['initialization_request_cap']):
                s.update(phase='initialization_incomplete',pause_reason='bounded independent initialization exhausted; no imported parents');return None,[]
            else:return {**task,'operator':'INIT','semantic_id':f'INIT-{v["initialization_requests"]:04d}','phase':'initialization'},[]
        if not c.get('candidate_policy') and v['operator_cursor']>=c['evolution_request_cap']:s['phase']='completed';return None,[]
        if s['u_plan'] is None:
            rng=random.Random();rng.setstate(_tuple_tree(s['u_rng']));g=s['generation']+1
            rows=evolution_v1.plan_generation(s['population'],g,rng)
            if not c.get('candidate_policy'):rows=rows[:c['evolution_request_cap']-v['operator_cursor']]
            s['u_rng']=rng.getstate();s['u_plan']={'generation':g,'offset':0,'tasks':rows,'parents':copy.deepcopy(s['population'])}
            write(Path(d)/f'plans/G{g:04d}.json',s['u_plan'])
        row=s['u_plan']['tasks'][s['u_plan']['offset']]
        return {**task,'operator':row['operator'],'semantic_id':row['id'],'original_generation':row['generation'],'phase':'evolution'},row['parent_records']
    def evaluate(self,d,s,p,candidate):
        key=candidate.key
        if key in s['evaluations']:
            if p['run_kind']=='u':return dict(valid=False,fitness=None,instances=[],mock=p['config']['api_mode']=='mock',failure={'kind':'AST_duplicate'}),True
            return read(Path(d)/s['evaluations'][key]['path']),True
        s['evaluations'][key]={'status':'reserved'};write(Path(d)/'checkpoint.json',s)
        tid=next(k for k,t in s['tasks'].items() if t['status']=='reserved')
        if p['config']['evaluation_mode']=='mock':
            raw=int(key[:7],16)
            # Strict EoH penalizes equal fitness. Its Mock N10 must have
            # enough distinct scores to exercise the finite-parent gate.
            strict=p['run_kind']=='eoh' and p['config']['initialization_policy']=='native_N_finite_or_fail'
            j=raw/0xfffffff/100 if strict else (raw%5)/100
            rows=[dict(file=r['file'],score=j,raw_cost=None,reference=None) for r in p['instances']]
            valid=not ('1/0' in candidate.code or '1 / 0' in candidate.code)
            result=dict(valid=valid,fitness=-sum(r['score'] for r in rows)/len(rows) if valid else None,instances=rows if valid else [],mock=True,engineering_only=True)
            path=Path(d)/'evaluations'/key/'result.json';write(path,result)
        else:
            members=p['members'] if p['run_kind']=='u' else [asdict(candidate)]
            selector=asdict(candidate) if p['run_kind']=='u' else asdict(language.validate('def use_heuristics(state):\n    return 0\n','singleton H host',1))
            result=evaluation.evaluate({'id':tid,'candidate':selector},{**p,'run_directory':str(d),'members':members})
            path=Path(d)/'worker-receipts'/tid/'result.json'
        self.validate_result(result,p['instances']);s['evaluations'][key]={'status':'completed','path':str(path.relative_to(d)),'sha256':sha(path)};write(Path(d)/'checkpoint.json',s)
        return result,False
    def validate_result(self,r,instances):
        if r.get('mock') and not self._engineering_mode:raise ValueError('synthetic score in real result')
        evaluation.validate(r,instances,self.p['config']['problem'],self.p['config'].get('obp_actions'))
        if not r.get('mock'):
            for row,ref in zip(r['instances'],self.p['references']):
                if row['reference']!=ref['reference']:raise ValueError('frozen reference differs')
                if self.p['config']['problem']=='obp' and (row['B']!=row['raw_cost'] or row['S']!=ref['S'] or row['C']!=ref['C'] or row['R_code']!=ref['reference'] or row['reference_identity']!=ref['reference_identity']):raise ValueError('OBP B/S/C/R_code receipt differs from frozen reference')
    def commit_candidate(self,d,s,p,record,candidate,result):
        record['J']=-result['fitness'] if result and result['valid'] else None
        record['semantic_id']=record.get('semantic_id',record['id']);record['stage']=record.get('phase','initialization' if record['operator']=='I1' else 'evolution')
        record['generation']=None # custom adapters alone decide native survival boundaries
        j=read(Path(d)/'API_attempts.json');attempts=[a for a in j['api_attempts'].values() if a['logical_id']==record['id']]
        if attempts:
            a=attempts[-1];record.update(usage=a.get('usage'),sent_confirmed=a.get('send_confirmed',False) if p['config']['api_mode']=='real' else False,request_key=a['id'],send_state='confirmed' if a.get('send_confirmed') else 'unknown' if a['status'] not in ('completed','failed') else 'not_sent')
        v=s['eoh']
        if p['config'].get('candidate_policy') and record['stage']=='evolution':
            counted=record['generation_status']=='completed' and not record['excluded_response']
            record['successful_evolution_response']=counted
            s['successful_evolution_responses']=s.get('successful_evolution_responses',0)+int(counted)
        if p['run_kind']=='eoh':return super().commit_candidate(d,s,p,record,candidate,result)
        if record['stage']=='initialization':v['initialization_requests']+=1
        else:v['operator_cursor']+=1
        if candidate is not None:v['evaluated_samples']+=1
        if record.get('AST_duplicate') and p['run_kind']=='u':record['failure']='AST_duplicate'
        row={'id':record['semantic_id'],'candidate':asdict(candidate),'fitness':result['fitness']} if candidate and result['valid'] else None
        if p['run_kind']=='h-build':return
        if record['stage']=='initialization':
            if row:s['population'].append(row)
        else:
            if row and not record.get('AST_duplicate'):s['children'].append(row)
            s['u_plan']['offset']+=1
            if s['u_plan']['offset']==len(s['u_plan']['tasks']):
                s['population']=survive(s['population'],s['children'],p['config']['population_size']);s['children']=[];s['generation']+=1;s['u_plan']=None
                write(Path(d)/f'populations/P{s["generation"]:04d}.json',s['population'])
    def on_commit(self,d,s,p):
        write(Path(d)/'Progress.json',self.summary(d,live=bool(p['config'].get('candidate_policy'))))
        if p['config']['pause_after_tasks']==s['cursor']:execution.stop(d,adapter=self)
    def summary(self,d,write_files=False,*,live=False):
        p,s=protocol_state(d);values=list(s['tasks'].values())[:s['cursor']];j=read(Path(d)/'API_attempts.json') if (Path(d)/'API_attempts.json').exists() else {'api_attempts':{}}
        attempts=list(j['api_attempts'].values());valid=[t for t in values if t['valid']];best=min(valid,key=lambda t:(t['J'],t.get('semantic_id',t['id']))) if valid else None
        real=p['config']['api_mode']=='real'
        out=dict(run_id=p['run_id'],problem=p['config']['problem'],method=p['run_kind'],phase=s['phase'],cursor=s['cursor'],engineering_only=not real,
          initialization_attempts=s['eoh']['initialization_requests'],evolution_attempts=s['eoh']['operator_cursor'],request_reservations=len(attempts),
          confirmed_sends=sum(a.get('send_confirmed',False) for a in attempts) if real else 0,unknown_sends=sum(not a.get('send_confirmed',False) and (a['status'] not in ('completed','failed') or (a.get('metadata') or {}).get('send_status')=='unknown') for a in attempts) if real else 0,
          valid_candidates=len(valid),unique_evaluation_reservations=len(s['evaluations']),failures=sum(bool(t.get('failure')) for t in values),duplicates=sum(bool(t.get('AST_duplicate')) for t in values),
          automatic_retries=0,API_stop=j.get('halt_reason'),requires_investigation=bool(j.get('halt_reason')) or s['phase']=='stopped',budgets=p['budgets'],best_J=best['J'] if best else None,champion_id=best.get('semantic_id',best['id']) if best else None,
          actual_cost=None,known_usage_subtotal={k:sum((a.get('usage') or {}).get(k,0) for a in attempts) for k in ('input_tokens','output_tokens')},unknown_usage_attempts=sum(a.get('usage') is None for a in attempts),writer_lock=(Path(d)/'.execution.lock').exists(),pause_reason=s.get('pause_reason'))
        out['phase_request_reservations']={phase:sum((s['tasks'].get(a['logical_id'],{}).get('operator') in ('INIT','I1'))==(phase=='initialization') for a in attempts) for phase in ('initialization','evolution')}
        if not live:
            import json
            physical=[]
            for path in (Path(d)/'worker-receipts').rglob('physical-solves.jsonl'):
                physical.extend(json.loads(line) for line in path.read_text().splitlines())
            out['physical_passes']={phase:{event:sum(r.get('pass')==phase and r['event']==event for r in physical) for event in ('started','completed','failed')} for phase in ('first','recheck')}
            out['physical_passes_unsettled']=sum(r['event']=='started' for r in physical)-sum(r['event'] in ('completed','failed') for r in physical)
        out['native_solve_upper_reserved']=len(s['evaluations'])*len(p['instances'])*2 if real else 0
        if policy:=p['config'].get('candidate_policy'):
            costs=candidate_policy.costs(j)
            out.update(candidate_policy_version=policy['version'],successful_evolution_responses=s.get('successful_evolution_responses',0),
                       successful_evolution_target=p['config']['evolution_request_cap'],
                       automatic_retries=costs['retry_reservations'],**costs)
        out['resources']={'declared_model_concurrency':p['config']['api_concurrency'],'declared_evaluation_concurrency':p['config']['evaluation_concurrency'],'CPUs':p['config']['resources']['cpus'],'memory_mib':p['config']['resources']['memory_mib'],'numeric_threads':1,'generation_tasks_across_devices':1,'real_throughput_verified':False}
        if p['config'].get('shared_manifest'):
            out['resources'].update(generation_tasks_across_devices=2,global_API_width=1)
        if 'stop_recovery' in p:
            v=p['stop_recovery'];done=sum(out['physical_passes'][phase]['completed'] for phase in ('first','recheck'))
            out['stop_recovery']={'parent_protocol_sha256':v['parent_protocol_sha256'],'inherited_requests':v['inherited_requests'],'inherited_solves':v['inherited_solves'],'new_request_reservations':len(attempts)-v['inherited_requests'],'new_completed_physical_solves':done-v['inherited_solves'],'original_deadline':read(Path(d)/'Run_clock.json')['deadline'],'no_reinitialization':True}
        if 'continuation' in p:
            v=p['continuation'];done=sum(out['physical_passes'][phase]['completed'] for phase in ('first','recheck'))
            out['continuation']={'parent_protocol_sha256':v['parent_protocol_sha256'],'imported_requests':v['imported_requests'],'imported_solves':v['imported_solves'],
                'new_request_reservations':len(attempts)-v['imported_requests'],'new_completed_physical_solves':done-v['imported_solves'],
                'original_deadline':read(Path(d)/'Run_clock.json')['deadline'],'no_reinitialization':True}
        if write_files:write(Path(d)/'results/Summary.json',out)
        return out


def export(directory):
    from heuristic_design.core.execution_export import export as shared_export, plot, table
    d=Path(directory);p,s=protocol_state(d);q=copy.deepcopy(s)
    q.update(initialization_requests=s['eoh']['initialization_requests'],generation_requests=s['eoh']['operator_cursor'])
    for t in q['tasks'].values():
        t['generation']=t.get('original_generation',0);t['id']=t.get('semantic_id',t['id'])
    shared_export(d,p,q)
    out=Adapter().summary(d);write(d/'exports/summary.json',out)
    if p['config'].get('candidate_policy'):
        out['source_H_cost']=p['source_cost'] if p['run_kind']=='u' else None
        j=read(d/'API_attempts.json') if (d/'API_attempts.json').exists() else {}
        attempts=[]
        for a in j.get('api_attempts',{}).values():
            meta=a.get('metadata') or {};usage=a.get('usage') or {}
            attempts.append(dict(id=a['id'],stage=j['requests'][a['logical_id']]['stage'],attempt=a['number'],
                status=a['status'],send_confirmed=a['send_confirmed'],send_status=meta.get('send_status'),
                http_status=meta.get('http_status'),failure_stage=meta.get('failure_stage'),
                input_tokens=usage.get('input_tokens'),output_tokens=usage.get('output_tokens')))
        table(d/'exports/API-physical-attempts.csv',attempts,
              ['id','stage','attempt','status','send_confirmed','send_status','http_status','failure_stage','input_tokens','output_tokens'])
        count=0;curve=[];best=None
        for t in q['tasks'].values():
            if t.get('valid'):best=t['J'] if best is None else min(best,t['J'])
            if t.get('successful_evolution_response'):
                count+=1
                if best is not None:curve.append({'successful_evolution_responses':count,'best_J':best})
        table(d/'exports/successful-response-curve.csv',curve,['successful_evolution_responses','best_J'])
        plot(d/'exports/best-J-by-successful-response.svg',curve,'successful_evolution_responses',
             'MOCK_ENGINEERING_ONLY' if p['config']['api_mode']=='mock' else 'TRAINING_SEARCH')
        write(d/'exports/summary.json',out)
    if p['config']['problem']=='obp':
        import csv
        rows=[]
        for key,receipt in s['evaluations'].items():
            if receipt['status']!='completed':continue
            result=read(d/receipt['path'])
            for row in result['instances']:rows.append({'candidate_key':key,'file':row['file'],'valid':result['valid'],'engineering_only':result.get('mock',False),'B':row.get('B'),'S':row.get('S'),'C':row.get('C'),'R_code':row.get('R_code'),'J':row['score'],'reference_version':(row.get('reference_identity') or {}).get('version')})
        with (d/'exports/obp-instance-costs.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['candidate_key','file','valid','engineering_only','B','S','C','R_code','J','reference_version']);writer.writeheader();writer.writerows(rows)
    if s['phase']=='completed':
        valid=[t for t in q['tasks'].values() if t.get('valid')]
        if valid:
            champion=min(valid,key=lambda t:(t['J'],t['id']));target=d/'exports'/('frozen_engineering_candidate.json' if p['config']['api_mode']=='mock' else 'frozen_training_champion.json')
            frozen={'champion':champion,'protocol_sha256':s['identity'],'metrics':p['metrics'],'holdout':'not_run'}
            if target.exists() and read(target)!=frozen:raise ValueError('frozen champion changed')
            write(target,frozen)
    return out
