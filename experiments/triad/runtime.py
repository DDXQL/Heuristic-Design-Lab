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
from heuristic_design.core import execution,evolution_v1,routing_state_a_v3 as language,state_a_v3
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.core.search import ranked,survive,_tuple_tree
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport
from . import problems,evaluation
from .configuration import load,gaps
VERSION='triad-shared-native-adapter-v1'


def sources():
    values=old.sources()
    for p in (ROOT/'experiments/triad').glob('*.py'):values[str(p.relative_to(ROOT))]=sha(p)
    return values


def protocol_state(directory):
    directory=Path(directory);p=read(directory/'Protocol.json');s=read(directory/'checkpoint.json')
    if p['version']!=VERSION or sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip() or s['identity']!=sha(directory/'Protocol.json'):raise ValueError('triad identity mismatch; no legacy reinterpretation')
    return p,s


def preflight(path,engineering=False):
    c=load(path,engineering=engineering);todo=gaps(c)
    if c.get('search_seed') is None:todo.append('select_independent_seed')
    elif c['search_seeds'] is None or c['search_seed'] not in c['search_seeds']:raise ValueError('search seed outside frozen declaration')
    if todo:return c,None,None,None,todo
    data,refs,hs=problems.load_inputs(c)
    if c['method']=='u' and not hs:raise ValueError('U needs a frozen H asset')
    for n,h in c['client_binding']['files'].items():
        if sha(ROOT/n)!=h:raise ValueError('admitted V5 client changed')
    if c['provider']!=c['client_binding']['provider'] or c['client_binding']!=read(ROOT/'deploy/eoh-baseline/unified-inputs.json')['client_binding']:raise ValueError('provider/V5 binding differs from unified current U identity')
    if c['problem']=='fjsp':
        expected=read(ROOT/'deploy/eoh-baseline/unified-inputs.json')['train21_order']
        if [{'file':r['file'],'source_sha256':r['source_sha256']} for r in data]!=expected:raise ValueError('frozen train21 order/content differs')
    r=c['resources'];width=max(c['api_concurrency'],c['evaluation_concurrency'])
    drain=math.ceil(width/c['api_concurrency'])*c['provider']['total_timeout']+len(data)*30+width+7
    if r['drain_seconds']<drain or min(r['segment_seconds'],c['window_seconds'])<=r['drain_seconds']:raise ValueError('resource window/drain cannot cover bounded staged wave')
    if not (c['problem']=='fjsp' and c['method']=='u' and c['mode']=='real') and c['evaluation_concurrency']!=1:raise ValueError('native EoH preserves serial evaluation/feedback')
    return c,data,refs,hs,[]


def prepare(directory,path,*,engineering=False,allow_api=False,approve_budget=None,run_kind=None):
    c,data,refs,hs,todo=preflight(path,engineering)
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
      'candidate_cap':cap,'api_attempt_cap':cap,'evolution_request_cap':evo,'initialization_request_cap':init,'initialization_sample_cap':2*c['population_size'],
      'selection_num':2,'type':'triad-native','candidate_kind':'U' if kind=='u' else 'h','recording_mode':'compact','window':10,'enabled_groups':list(evolution_v1.GROUPS),'cross_parents':2}
    directory.mkdir(parents=True)
    write(directory/'Tasks.json',[{'id':f'SLOT-{i:07d}','stage':'new','generation':None,'operator':'adaptive_slot'} for i in range(cap)])
    p=dict(version=VERSION,run_kind=kind,config=runtime,members=hs if kind=='u' else [],instances=data,references=refs,source_files=sources(),
      state_schema=state_a_v3.schema_id(c['problem']),tasks_sha256=sha(directory/'Tasks.json'),config_sha256=sha(path),
      metrics={'objective':'J=mean((raw_cost-reference)/reference)','direction':'min','internal_score':'-J','final_selection':'all complete valid candidates; J ascending, semantic ID ascending'},
      run_id=directory.name,source_cost={'H_attempts':None},budgets=dict(logical_generation=cap,API_attempts=cap,initialization=init,evolution=evo,max_program_instances=cap*len(data),max_solve_passes=2*cap*len(data)))
    write(directory/'Protocol.json',p);(directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    write(directory/'checkpoint.json',dict(identity=sha(directory/'Protocol.json'),phase='prepared',cursor=0,tasks={},evaluations={},population=[],children=[],seen={},generation=0,pause_ack=0,
      generations=[],u_rng=random.Random(c['search_seed']).getstate(),u_plan=None,
      eoh=dict(stage='initialization',native_generation=0,population=[],next_population=[],evaluated_samples=0,initialization_samples=0,initialization_requests=0,operator_cursor=0,evolution_survivals=0,np_rng=None)))
    return p


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
            if c.get('obp_h_abi')=='obp-vector-h-v1':expr='[(1/0) for cap in remaining_capacities]' if fault=='invalid_evaluation' else '[-item_size + '+str(n/100)+' * cap for cap in remaining_capacities]'
            code='def priority('+', '.join(args)+'):\n    return '+expr+'\n'
        return {'text':'{OFFLINE fixture; not model output}\n```python\n'+code+'```','usage':{'input_tokens':0,'output_tokens':0},'metadata':{'mock':True}}


class Adapter(old.Adapter):
    ROOT=ROOT
    entrypoint='experiments/triad/entry.py'
    def read_state(self,d):return protocol_state(d)
    def check_run(self,d):
        p,s=protocol_state(d)
        if sha(Path(d)/'Tasks.json')!=p['tasks_sha256'] or any(sha(ROOT/n)!=h for n,h in p['source_files'].items()):raise ValueError('frozen tasks/source changed')
        self.p=p;self._engineering_mode=p['config']['api_mode']=='mock';return p
    def members(self,d):return read(Path(d)/'Protocol.json')['members']
    def transport(self,p):return MockTransport(self.client_config(p),p) if p['config']['api_mode']=='mock' else StrictNonstreamTransport(self.client_config(p))
    def parse_candidate(self,text,c):
        try:
            if self.p['run_kind']!='u' and old.old.EoHSampler.trim_thought_from_response(text) is None:raise ValueError('native boxed H description required')
            return language.parse(text,len(self.p['members'])) if self.p['run_kind']=='u' else problems.parse_h(c['problem'],text)
        except Exception as x:raise self.CandidateError(str(x)) from x
    def build_prompt(self,c,task,parents,members):
        if self.p['run_kind']=='u':
            semantic={**task,'operator':task['operator']}
            return language.build_prompt(c['problem'],semantic,parents,members)
        args=problems.h_args(c['problem'],c.get('obp_h_abi'));template=old.old.Converter.text_to_function('def priority('+', '.join(args)+'):\n    return 0.0\n')
        description=('Design ONE '+c['problem']+' action-scoring H with exact scalar arguments '+str(args)+'. Highest finite priority wins, stable original action order breaks exact ties. '
          'Minimize complete train objective J=mean((raw cost-reference)/reference). No imports, network, files, globals or lookahead. '
          +('Reference is externally frozen LKH, never nearest-neighbor. ' if c['problem']=='tsp' else '')
          +('Return one list/tuple score per supplied bin, in the same order; use only one comprehension over remaining_capacities. ' if c.get('obp_h_abi')=='obp-vector-h-v1' else '')
          +('Only current arrival and current bin remaining capacity are visible. Future items are not available. ' if c['problem']=='obp' else '')
          +'Return one boxed {description} and one complete fenced python function.')
        op=task['operator'];funcs=[old.old.native.make_function(r['candidate'],r['id'],r['fitness']) for r in parents]
        fn=getattr(old.old.EoHPrompt,'get_prompt_'+op.lower())
        return fn(description,template) if op=='I1' else fn(description,funcs if op in ('E1','E2') else funcs[0],template)
    def task_context(self,d,s,p,task,index):
        c=p['config'];v=s['eoh']
        if getattr(self,'segment_deadline',None) and time.monotonic()+c['resources']['drain_seconds']>self.segment_deadline:
            s.update(phase='paused',pause_reason='segment drain before next reservation');return None,[]
        if p['run_kind']=='h-build':return {**task,'operator':'I1','semantic_id':f'H-{index:05d}','phase':'initialization'},[]
        if p['run_kind']=='eoh':return super().task_context(d,s,p,task,index)
        if v['stage']=='initialization':
            if len(s['population'])==c['population_size']:v['stage']='evolution';s['population']=ranked(s['population'])
            elif v['initialization_requests']>=min(c['initialization_request_cap'],c['population_size'] if c['initialization_policy']=='fixed_population_slots_no_refill' else c['initialization_request_cap']):
                s.update(phase='initialization_incomplete',pause_reason='bounded independent initialization exhausted; no imported parents');return None,[]
            else:return {**task,'operator':'INIT','semantic_id':f'INIT-{v["initialization_requests"]:04d}','phase':'initialization'},[]
        if v['operator_cursor']>=c['evolution_request_cap']:s['phase']='completed';return None,[]
        if s['u_plan'] is None:
            rng=random.Random();rng.setstate(_tuple_tree(s['u_rng']));g=s['generation']+1
            rows=evolution_v1.plan_generation(s['population'],g,rng)[:c['evolution_request_cap']-v['operator_cursor']]
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
            j=(int(key[:7],16)%5)/100;rows=[dict(file=r['file'],score=j,raw_cost=None,reference=None) for r in p['instances']]
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
    def commit_candidate(self,d,s,p,record,candidate,result):
        record['J']=-result['fitness'] if result and result['valid'] else None
        record['semantic_id']=record.get('semantic_id',record['id']);record['stage']=record.get('phase','initialization' if record['operator']=='I1' else 'evolution')
        record['generation']=None # custom adapters alone decide native survival boundaries
        j=read(Path(d)/'API_attempts.json');attempts=[a for a in j['api_attempts'].values() if a['logical_id']==record['id']]
        if attempts:
            a=attempts[-1];record.update(usage=a.get('usage'),sent_confirmed=a.get('send_confirmed',False) if p['config']['api_mode']=='real' else False,request_key=a['id'],send_state='confirmed' if a.get('send_confirmed') else 'unknown' if a['status'] not in ('completed','failed') else 'not_sent')
        v=s['eoh']
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
        write(Path(d)/'Progress.json',self.summary(d))
        if p['config']['pause_after_tasks']==s['cursor']:execution.stop(d,adapter=self)
    def summary(self,d,write_files=False):
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
        physical=[]
        import json
        for path in (Path(d)/'worker-receipts').rglob('physical-solves.jsonl'):
            physical.extend(json.loads(line) for line in path.read_text().splitlines())
        out['physical_passes']={phase:{event:sum(r.get('pass')==phase and r['event']==event for r in physical) for event in ('started','completed','failed')} for phase in ('first','recheck')}
        out['native_solve_upper_reserved']=len(s['evaluations'])*len(p['instances'])*2 if real else 0
        out['physical_passes_unsettled']=sum(r['event']=='started' for r in physical)-sum(r['event'] in ('completed','failed') for r in physical)
        out['resources']={'declared_model_concurrency':p['config']['api_concurrency'],'declared_evaluation_concurrency':p['config']['evaluation_concurrency'],'CPUs':p['config']['resources']['cpus'],'memory_mib':p['config']['resources']['memory_mib'],'numeric_threads':1,'generation_tasks_across_devices':1,'real_throughput_verified':False}
        if write_files:write(Path(d)/'results/Summary.json',out)
        return out


def export(directory):
    from heuristic_design.core.execution_export import export as shared_export
    d=Path(directory);p,s=protocol_state(d);q=copy.deepcopy(s)
    q.update(initialization_requests=s['eoh']['initialization_requests'],generation_requests=s['eoh']['operator_cursor'])
    for t in q['tasks'].values():
        t['generation']=t.get('original_generation',0);t['id']=t.get('semantic_id',t['id'])
    shared_export(d,p,q)
    out=Adapter().summary(d);write(d/'exports/summary.json',out)
    if s['phase']=='completed':
        valid=[t for t in q['tasks'].values() if t.get('valid')]
        if valid:
            champion=min(valid,key=lambda t:(t['J'],t['id']));target=d/'exports'/('frozen_engineering_candidate.json' if p['config']['api_mode']=='mock' else 'frozen_training_champion.json')
            frozen={'champion':champion,'protocol_sha256':s['identity'],'metrics':p['metrics'],'holdout':'not_run'}
            if target.exists() and read(target)!=frozen:raise ValueError('frozen champion changed')
            write(target,frozen)
    return out
