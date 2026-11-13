"""Versioned FJSP EoH problem adapter; reuse native EoH and frozen execution.

Public code stays byte-identical to 923781f. Physical rows are J (minimize);
only the unchanged native maximizing Population receives -J.
"""
from dataclasses import asdict
from pathlib import Path
import copy
import csv
import math
import os
import time

from heuristic_design.problems.fjsp import eoh_single as old
from heuristic_design.core import execution, evolution_v1, routing_state_a_v3, state_a_v3
from heuristic_design.core.storage import read, write, sha, digest
from heuristic_design.core.terminal_ops import inputs
from heuristic_design.core.routing_evaluation import evaluate_task, semantic_row
from heuristic_design.problems.routing_fixtures import precheck_instances, decode_instance
from heuristic_design.llm.legacy import ClientConfig
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport, POLICY, STOP_POLICY
from fjsp_usage.research_real.real_transport import WIRE_VERSION
from fjsp_usage.offline_v2 import lower_bound_v5

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
VERSION='fjsp-eoh-single-J-min-v1'
METRICS={'objective':'J=mean((Cmax-LB_v5)/LB_v5)', 'direction':'min',
 'internal_native_score':'-J; implementation bridge only, NOT historical negative Fitness',
 'legacy_identity':'fjsp-eoh-single-native-http-v2; mean(-Cmax/LB_v5), maximize; immutable',
 'final_selection':'all complete valid train candidates, J ascending then stable task ID ascending',
 'population_ties':'native stable elitism; equal internal score OR canonical source duplicate penalized -inf; final selection uses unpenalized J'}
REQUIRED=('candidate_cap','api_attempt_cap','initialization_request_cap','evolution_request_cap',
 'population_size','initialization_sample_cap','search_seed','window_seconds','budget_basis')


def task_description():
    return old.task_description().replace('ascending job then machine order','ascending job order and original eligible-machine enumeration order').replace(
      'Complete train21 Fitness is mean(-Cmax/LB), maximized;',
      'Complete train21 objective J is mean((Cmax-LB)/LB), minimized; the native rank machinery uses -J internally;')


def sources():
    result=old.sources()
    for p in HERE.iterdir():
        if p.is_file() and p.suffix in ('.py','.sbatch'):
            result[str(p.relative_to(ROOT))]=sha(p)
    for name in ('experiments/common/run_fjsp_eoh_gap.py','deploy/eoh-baseline/unified-inputs.json'):
        result[name]=sha(ROOT/name)
    return result


def missing(c):
    out=[k for k in REQUIRED if c.get(k) is None]
    if c['freeze_status']!='frozen' and c['api_mode']=='real':out.append('freeze_status=frozen (future explicit approval)')
    if c['api_mode']=='real':
        out += ['resources.'+k for k in ('partition','cpus','memory_mib','walltime_seconds') if c['resources'].get(k) is None]
        for k in ('account_exclusion','credential_file'):
            if not c.get(k):out.append(k)
    return out


def settings(path):
    path=Path(path).resolve();c=read(path);allowed=set(read(HERE/'research.pending.json'))
    if set(c)!=allowed:raise ValueError('configuration fields differ: '+str(set(c)^allowed))
    if c['version']!=VERSION or c['real_requests_authorized'] is not False:raise ValueError('new saved config identity / requests OFF required')
    if (c['api_mode'],c['evaluation_mode']) not in (('real','solve'),('mock','mock')):raise ValueError('Mock transport and evaluation must both be isolated')
    if c['freeze_status'] not in ('pending','frozen','engineering_only'):raise ValueError('invalid freeze status')
    if c['api_mode']=='mock' and c['freeze_status']!='engineering_only':raise ValueError('Mock cannot claim a research freeze')
    for k in REQUIRED:
        if c[k] is not None and k!='budget_basis' and (type(c[k]) is not int or c[k] < (0 if k=='search_seed' else 1)):
            raise ValueError('invalid positive integer / seed: '+k)
    if c['per_candidate_attempt_cap']!=1 or c['selection_num']!=2 or c['api_concurrency']!=1 or c['evaluation_concurrency']!=1:
        raise ValueError('native EoH: two-parent crossover, API1/evaluation1, exactly one attempt; no retry')
    if c['budget_basis'] is not None and (not isinstance(c['budget_basis'],str) or not c['budget_basis'].strip()):raise ValueError('explicit budget comparison basis required')
    n=c['population_size']
    if n is not None:
        if n<2:raise ValueError('native N>=2')
        if c['initialization_sample_cap'] is not None and c['initialization_sample_cap']!=2*n:raise ValueError('native evaluated-sample init ceiling is 2N')
        if c['initialization_request_cap'] is not None and c['initialization_request_cap']<n:raise ValueError('initialization request cap cannot be below N')
    caps=[c[k] for k in ('candidate_cap','api_attempt_cap','initialization_request_cap','evolution_request_cap')]
    if None not in caps and not caps[0]==caps[1]==caps[2]+caps[3]:raise ValueError('total cap = initialization maximum + evolution maximum; no borrowing')
    if c['mock_faults'] and c['api_mode']!='mock' or c['pause_after_tasks'] is not None and c['api_mode']!='mock':raise ValueError('Mock controls forbidden in real config')
    if any(v not in ('failure','invalid','duplicate','invalid_evaluation') for v in c['mock_faults'].values()):raise ValueError('unknown Mock fault')
    if c['pause_after_tasks'] is not None and (type(c['pause_after_tasks']) is not int or not 1<=c['pause_after_tasks']<=c['candidate_cap']):raise ValueError('invalid pause cursor')
    ms=c['milestone_requests']
    if ms!=sorted(set(ms)) or any(type(x) is not int or x<1 or c['candidate_cap'] is None or x>c['candidate_cap'] for x in ms):raise ValueError('invalid milestones')
    r=c['resources']
    if set(r)!={'partition','account','qos','cpus','memory_mib','walltime_seconds','numeric_threads'}:raise ValueError('resource fields differ')
    for k in ('cpus','memory_mib','walltime_seconds'):
        if r[k] is not None and (type(r[k]) is not int or r[k]<1):raise ValueError('invalid resource: '+k)
    if r['numeric_threads']!=1 or r['cpus'] is not None and r['cpus']<2:raise ValueError('one controller plus one evaluator CPU; numeric threads=1')
    for k in ('partition','account','qos'):
        if r[k] is not None and (not isinstance(r[k],str) or not r[k] or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for ch in r[k])):raise ValueError('invalid Slurm '+k)
    c['data_manifest']=str((path.parent/c['data_manifest']).resolve())
    return c


def preflight(path):
    c=settings(path);binding=read(HERE/'unified-inputs.json')
    if c['provider']!=binding['provider']:raise ValueError('provider differs from frozen current U identity')
    if c['instance_timeout_seconds']!=30 or c['solve_seed']!=binding['solve_seed']:raise ValueError('shared T30/solve seed differs')
    client=binding['client_binding']
    if client['wire_version']!=WIRE_VERSION or client['caller_policy']!=POLICY:raise ValueError('V5 caller/wire differs')
    for n,h in client['files'].items():
        if sha(ROOT/n)!=h:raise ValueError('admitted client bytes differ: '+n)
    _,data,origin=inputs({'problem':'fjsp','data_manifest':c['data_manifest']})
    if len(data)!=21 or any(v['split']!='train' for v in data):raise ValueError('complete train21 only')
    if [{'file':r['file'],'source_sha256':r['source_sha256']} for r in data]!=binding['train21_order']:raise ValueError('ordered train21 differs')
    refs=precheck_instances('fjsp',data)  # parser / LB arithmetic only, never a construction
    todo=missing(c)
    if not todo:
        ClientConfig({'config':c,'budgets':{'logical_generation':c['candidate_cap']}})
        reserve=30*len(data)+c['provider']['total_timeout']+7+120
        if min(c['window_seconds'],c['resources']['walltime_seconds'])<=reserve:raise ValueError('window/Slurm time must fit a complete T30 evaluation+request and drain margin')
    return c,data,refs,origin,todo


def check(path):
    c,data,refs,_,todo=preflight(path)
    return dict(version=VERSION,environment_check='passed',protocol_check='unfrozen_expected_rejection' if todo else 'ready',
        missing_protocol_decisions=todo,API_requests=0,actual_solves=0,credential_reads=0,instances=len(data),
        provider=c['provider'],metrics=METRICS,resources=c['resources'],
        budgets={k:c[k] for k in ('initialization_request_cap','initialization_sample_cap','evolution_request_cap','candidate_cap','api_attempt_cap','per_candidate_attempt_cap')},
        max_native_solve_passes=None if c['candidate_cap'] is None else 2*len(data)*c['candidate_cap'],
        api_concurrency=1,evaluation_concurrency=1,native_operators=['I1',*old.native.OPERATORS],references=refs)


def authorize(c,approve_budget,allow_api,original_deadline=None):
    if c['api_mode']=='mock':
        if allow_api or approve_budget is not None:raise PermissionError('Mock cannot carry API authorization')
        return
    if not allow_api or type(approve_budget) is not int or approve_budget!=c['api_attempt_cap']:raise PermissionError('explicit ORIGINAL cumulative request cap required')
    e=c['account_exclusion']
    if (not isinstance(e,dict) or e.get('scope')!='all_devices_sharing_account' or not e.get('confirmation')
        or type(e.get('valid_until')) not in (int,float) or e['valid_until']<(original_deadline or time.time()+c['window_seconds'])):raise PermissionError('future exclusive model-request interval must cover original run window; do not change Mac gate')


def prepare(directory,path,*,approve_budget=None,allow_api=False):
    c,data,refs,origin,todo=preflight(path)
    if todo:raise PermissionError('PROTOCOL_UNFROZEN: '+', '.join(todo))
    authorize(c,approve_budget,allow_api)
    if c['api_mode']=='real':
        c['real_requests_authorized']=True
    directory=Path(directory).resolve()
    if directory.exists() or not directory.is_relative_to(ROOT/'runs'):raise ValueError('new independent run under this release runs/ required')
    directory.mkdir(parents=True)
    write(directory/'Tasks.json',[dict(id=f'H-{i:04d}',stage='new',generation=None,operator='adaptive_EoH_slot') for i in range(c['candidate_cap'])])
    runtime={**c,'type':'native_eoh','candidate_kind':'h','problem':'fjsp','recording_mode':'compact','window':10,
      'enabled_groups':list(evolution_v1.GROUPS),'cross_parents':2,'execution_contract':{'version':VERSION,'allocated_cpus':c['resources']['cpus']}}
    p=dict(version=VERSION,config=runtime,instances=data,references=refs,input_provenance=origin,source_files=sources(),
       tasks_sha256=sha(directory/'Tasks.json'),prompt_sha256=digest(task_description()),metrics=METRICS,
       state_schema=state_a_v3.schema_id('fjsp'),u_abi=routing_state_a_v3.ABI,
       caller_acceptance_policy=POLICY,infrastructure_policy=STOP_POLICY,
       algorithm=dict(implementation='unchanged native LLM4AD EoH + existing durable adapter',
         operators=['I1',*old.native.OPERATORS],initialization='native auto survival and explicit post-init survival; <=2N evaluated samples and separate HTTP cap; no refill',
         selection='inverse rank with replacement; two for E1/E2, one for M1/M2',
         survival='native register every N; score=-J; stable sort; source/equal-score duplicate -> -inf',
         final_selection=METRICS['final_selection'],search_space='direct seven-argument H; not a selector over frozen H10',
         stopping='separate init/evolution attempt maxima, no spare-init borrowing, one HTTP attempt/slot, no automatic retry/restart',local_search=False),
       budgets=dict(logical_generation=c['candidate_cap'],API_attempts=c['api_attempt_cap'],
         initialization=c['initialization_request_cap'],evolution=c['evolution_request_cap'],
         max_program_instances=c['candidate_cap']*len(data),max_solve_passes=2*c['candidate_cap']*len(data)),created_at=time.time())
    write(directory/'Protocol.json',p);(directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    write(directory/'checkpoint.json',dict(identity=sha(directory/'Protocol.json'),phase='prepared',cursor=0,tasks={},evaluations={},population=[],children=[],seen={},generation=0,pause_ack=0,
      eoh=dict(stage='initialization',native_generation=0,population=[],next_population=[],evaluated_samples=0,initialization_samples=0,initialization_requests=0,operator_cursor=0,evolution_survivals=0,np_rng=None)))
    return p


def protocol_state(directory):
    directory=Path(directory);p=read(directory/'Protocol.json');s=read(directory/'checkpoint.json')
    if p['version']!=VERSION or sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip() or s['identity']!=sha(directory/'Protocol.json'):raise ValueError('new J protocol identity mismatch; legacy resume forbidden')
    return p,s


class Adapter(old.Adapter):
    ROOT=ROOT
    entrypoint='experiments/common/run_fjsp_eoh_gap.py'
    def read_state(self,directory):return protocol_state(directory)
    def check_run(self,directory):
        p,s=protocol_state(directory)
        if sha(Path(directory)/'Tasks.json')!=p['tasks_sha256'] or digest(task_description())!=p['prompt_sha256']:raise ValueError('frozen task plan/prompt changed')
        if any(sha(ROOT/n)!=h for n,h in p['source_files'].items()):raise ValueError('frozen source changed')
        if p['metrics']!=METRICS or p['caller_acceptance_policy']!=POLICY:raise ValueError('metric/client identity changed')
        if p['budgets']['API_attempts']!=p['budgets']['initialization']+p['budgets']['evolution']:raise ValueError('budget identity differs')
        self._engineering_mode=p['config']['api_mode']=='mock'
        return p
    def transport(self,p):
        if p['config']['api_mode']=='mock':return old.MockTransport(self.client_config(p),p['config']['mock_faults'])
        return StrictNonstreamTransport(self.client_config(p))
    def build_prompt(self,config,task,parents,members):
        template=old.Converter.text_to_function(old.TEMPLATE)
        funcs=[old.native.make_function(r['candidate'],r['id'],r['fitness']) for r in parents]
        fn=getattr(old.EoHPrompt,'get_prompt_'+task['operator'].lower())
        text=fn(task_description(),template) if task['operator']=='I1' else fn(task_description(),funcs if task['operator'] in ('E1','E2') else funcs[0],template)
        return text+'\nSerialization requirement: one boxed {description}, then exactly one fenced python block containing the complete function. No other text.\n'
    def task_context(self,directory,state,p,task,index):
        if state['eoh']['stage']=='evolution' and state['eoh']['operator_cursor']>=p['config']['evolution_request_cap']:
            state['phase']='completed';return None,[]
        segment=getattr(self,'segment_deadline',None)
        reserve=30*len(p['instances'])+p['config']['provider']['total_timeout']+7+120
        if segment is not None and time.monotonic()+reserve>segment:
            state['phase']='paused';state['pause_reason']='Slurm segment drain before reservation';return None,[]
        return super().task_context(directory,state,p,task,index)
    def evaluate(self,directory,state,p,candidate):
        key=candidate.key
        if key in state['evaluations']:return read(Path(directory)/state['evaluations'][key]['path']),True
        state['evaluations'][key]={'status':'reserved'};write(Path(directory)/'checkpoint.json',state)
        tid=next(k for k,t in state['tasks'].items() if t['status']=='reserved')
        if p['config']['evaluation_mode']=='mock':
            gap=(int(key[:6],16)%7)/100  # deliberate ties exercise native and final tie rules
            invalid='1 / 0' in candidate.code or '1/0' in candidate.code
            result=dict(mock=True,engineering_only=True,valid=not invalid,fitness=None if invalid else -sum(gap for _ in p['instances'])/len(p['instances']),
              instances=[] if invalid else [dict(file=r['file'],score=gap,raw_cost=None,reference=None) for r in p['instances']])
            path=Path(directory)/'evaluations'/key/'result.json';write(path,result)
        else:
            u=asdict(routing_state_a_v3.validate('def use_heuristics(state):\n    return 0\n','singleton H host; no evolved U',1))
            result=evaluate_task({'id':tid,'candidate':u},{**p,'run_directory':str(directory),'members':[asdict(candidate)]})
            path=Path(directory)/'worker-receipts'/tid/'result.json'
        self.validate_result(result,p['instances'])
        state['evaluations'][key]={'status':'completed','path':str(path.relative_to(directory)),'sha256':sha(path)}
        write(Path(directory)/'checkpoint.json',state);return result,False
    def validate_result(self,result,instances):
        rows=result['instances']
        if type(result.get('valid')) is not bool or len(rows)>len(instances) or [r['file'] for r in rows]!=[v['file'] for v in instances[:len(rows)]]:raise ValueError('validity / ordered prefix differs')
        if result['valid']:
            if len(rows)!=len(instances) or result['fitness']!=-sum(r['score'] for r in rows)/len(rows):raise ValueError('complete J mean / -J bridge differs')
        elif result['fitness'] is not None:raise ValueError('invalid candidate has no objective')
        if any(type(r['score']) not in (int,float) or not math.isfinite(r['score']) for r in rows):raise ValueError('nonfinite J')
        if result.get('mock'):
            if not getattr(self,'_engineering_mode',False):raise ValueError('Mock cannot enter real results')
            return
        for row,spec in zip(rows,instances):
            instance=decode_instance('fjsp',spec)
            schedule=old.Schedule(tuple(old.ScheduledOperation(**v) for v in row['solution']['operations']),row['solution']['makespan'])
            old.validate_schedule(instance,schedule)  # pure feasibility validation, no construction
            ref=lower_bound_v5(instance)
            if (row['raw_cost']!=schedule.makespan or row['reference']!=ref or row['score']!=state_a_v3.score_final_cost(schedule.makespan,ref)
                or row['captured_solves']!=2 or not row['feasible'] or row['semantic_sha256']!=row['recheck_semantic_sha256']
                or digest(semantic_row(row,compact=result.get('recording_mode')=='compact'))!=row['semantic_sha256']
                or row['source_before_sha256']!=row['source_after_sha256']):raise ValueError('physical J/LB/feasibility/recheck mismatch')
    def commit_candidate(self,directory,state,p,record,candidate,result):
        record['J']=(-result['fitness']) if result and result['valid'] else None
        record['objective_direction']='min';record['internal_native_score']=-record['J'] if record['J'] is not None else None
        bridge=copy.deepcopy(result)
        if bridge and bridge['valid']:
            for r in bridge['instances']:r['score']=-r['score']
        super().commit_candidate(directory,state,p,record,candidate,bridge)
    def summary(self,directory,write_files=False):
        p,s=protocol_state(directory);j=read(Path(directory)/'API_attempts.json') if (Path(directory)/'API_attempts.json').exists() else {'api_attempts':{}}
        attempts=list(j['api_attempts'].values());tasks=list(s['tasks'].values());values=tasks[:s['cursor']]
        valid=[t for t in values if t['valid']];best=min(valid,key=lambda t:(t['J'],t['id'])) if valid else None
        real=p['config']['api_mode']=='real'
        result=dict(version=VERSION,phase=s['phase'],cursor=s['cursor'],stage=s['eoh']['stage'],engineering_only=not real,
          objective=METRICS['objective'],direction='min',best_J=best['J'] if best else None,champion_id=best['id'] if best else None,
          initialization_attempts=s['eoh']['initialization_requests'],evolution_attempts=s['eoh']['operator_cursor'],
          request_reservations=len(attempts),actual_API_confirmed_sends=sum(a.get('send_confirmed',False) for a in attempts) if real else 0,
          uncertain_request_attempts=sum(a['status'] not in ('completed','failed') for a in attempts) if real else 0,
          completed_transport_attempts=sum(a['status']=='completed' for a in attempts),failed_transport_attempts=sum(a['status']=='failed' for a in attempts),
          scientific_failures=sum(bool(t.get('failure')) for t in values),AST_duplicates=sum(bool(t.get('AST_duplicate')) for t in values),
          native_population_duplicates=sum(bool(t.get('native_population_duplicate')) for t in values),cached_evaluations=sum(bool(t.get('cache_hit')) for t in values),
          unique_H_evaluation_reservations=len(s['evaluations']),valid_candidate_records=len(valid),automatic_retries=0,
          confirmed_native_solve_passes=sum(r.get('captured_solves',0) for v in s['evaluations'].values() if v['status']=='completed' for r in read(Path(directory)/v['path'])['instances']) if real else 0,
          native_solve_passes_upper_reserved=len(s['evaluations'])*len(p['instances'])*2 if real else 0,
          failed_or_inflight_solve_count_known=False if real else True,
          budgets=p['budgets'],remaining_cumulative_requests=p['budgets']['API_attempts']-len(attempts),
          known_input_tokens=sum((a.get('usage') or {}).get('input_tokens',0) for a in attempts),known_output_tokens=sum((a.get('usage') or {}).get('output_tokens',0) for a in attempts),
          usage_unknown_attempts=sum(a.get('usage') is None for a in attempts),actual_billed_cost=None,API_stop=j.get('halt_reason'),
          pause_reason=s.get('pause_reason'),writer_lock=(Path(directory)/'.execution.lock').exists(),training_only=real,validation_status='not_run',quality_claim=False)
        result['phase_breakdown']={stage:dict(committed_attempts=len(ts),valid_candidates=sum(t['valid'] for t in ts),failures=sum(bool(t.get('failure')) for t in ts),AST_duplicates=sum(bool(t.get('AST_duplicate')) for t in ts)) for stage,ts in ((stage,[t for t in values if (t['operator']=='I1')==(stage=='initialization')]) for stage in ('initialization','evolution'))}
        if write_files:write(Path(directory)/'results/Summary.json',result)
        return result


def export(directory):
    directory=Path(directory);p,s=protocol_state(directory);out=directory/'analysis';out.mkdir(exist_ok=True)
    tasks=list(s['tasks'].values())[:s['cursor']]
    journal=read(directory/'API_attempts.json') if (directory/'API_attempts.json').exists() else {'api_attempts':{}}
    rows=[{k:t.get(k) for k in ('id','operator','valid','J','failure','AST_duplicate','native_population_duplicate','cache_hit')} for t in tasks]
    requests=[dict(id=a['id'],logical_id=a['logical_id'],status=a['status'],send_confirmed=a.get('send_confirmed',False),usage=a.get('usage')) for a in journal['api_attempts'].values()]
    best=None;curve=[dict(attempt_reservations=0,initialization_attempts=0,evolution_attempts=0,best_J=None)]
    byid={t['id']:t for t in tasks};init=evo=0
    for i,a in enumerate(requests,1):
        t=byid.get(a['logical_id'])
        if t:
            if t['operator']=='I1':init+=1
            else:evo+=1
            if t['valid']:best=t['J'] if best is None else min(best,t['J'])
        curve.append(dict(attempt_reservations=i,initialization_attempts=init,evolution_attempts=evo,best_J=best,committed=t is not None))
    instance_rows=[]
    for t in tasks:
        if not t.get('evaluation_key'):continue
        for r in read(directory/s['evaluations'][t['evaluation_key']]['path'])['instances']:
            instance_rows.append(dict(candidate_id=t['id'],file=r['file'],complete_candidate_valid=t['valid'],J_i=r['score'],Cmax=r.get('raw_cost'),LB_v5=r.get('reference'),mock=p['config']['api_mode']=='mock'))
    for name,data in (('candidates',rows),('requests',requests),('instances',instance_rows),('J_curve',curve)):
        write(out/(name+'.json'),data)
        if data:
            fields=list(dict.fromkeys(k for r in data for k in r))
            with (out/(name+'.csv')).open('w',newline='',encoding='utf-8-sig') as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(data)
    # Standalone J curve; no legacy negative-Fitness plotter or optional dependency.
    points=[(r['attempt_reservations'],r['best_J']) for r in curve if r['best_J'] is not None]
    if points:
        low=min(y for x,y in points);high=max(y for x,y in points);span=high-low or 1.0
        coords=' '.join(f'{50+700*x/max(1,len(requests)):.3f},{330-260*(y-low)/span:.3f}' for x,y in points)
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400" viewBox="0 0 800 400"><rect width="800" height="400" fill="white"/><text x="50" y="30" font-family="sans-serif">Best complete train21 J (minimize)</text><path d="M50 60 V330 H760" fill="none" stroke="black"/><polyline points="{coords}" fill="none" stroke="#2166ac" stroke-width="2"/><text x="50" y="365" font-family="sans-serif">Cumulative attempt reservations (initialization included)</text><text x="50" y="390" font-family="sans-serif">J range: {low:.8g} to {high:.8g}; engineering fixture={p['config']['api_mode']=='mock'}</text></svg>'
        (out/'J_curve.svg').write_text(svg)
    summary=Adapter().summary(directory);write(out/'Summary.json',summary)
    valid=[t for t in tasks if t['valid']]
    if valid:
        champion=min(valid,key=lambda t:(t['J'],t['id']))
        write(out/'training_best_so_far.json',dict(champion=champion,selection=METRICS['final_selection'],protocol_sha256=s['identity'],final=s['phase']=='completed',engineering_only=p['config']['api_mode']=='mock'))
        if s['phase']=='completed':
            frozen=dict(champion=champion,metrics=METRICS,protocol_sha256=s['identity'],engineering_only=p['config']['api_mode']=='mock',validation_status='not_run')
            target=out/('frozen_engineering_candidate.json' if p['config']['api_mode']=='mock' else 'frozen_training_champion.json')
            if target.exists() and read(target)!=frozen:raise ValueError('frozen champion differs; preserved')
            write(target,frozen);(out/'champion.py').write_text(champion['candidate']['code'])
    return summary
