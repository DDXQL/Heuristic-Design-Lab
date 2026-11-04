"""FJSP problem hooks for the existing durable native-EoH adapter.

No new search loop, transport, population or solver implementation.
"""
from dataclasses import asdict
from pathlib import Path
import ast, copy, csv, math, os, subprocess, time
from heuristic_design.core import routing
from heuristic_design.core.storage import read, write, sha, digest
from heuristic_design.core.terminal_ops import inputs
from heuristic_design.problems.routing_fixtures import precheck_instances,decode_instance
from heuristic_design.problems.tsp import eoh_single as native
from heuristic_design.llm.legacy import ClientConfig,JsonCandidateTransport
from fjsp_usage.research.candidates import H_ARGS,CandidateError,parse_response,validate_code
from fjsp_usage.offline_v2 import lower_bound_v5
from llm4ad.base import TextFunctionProgramConverter as Converter
from llm4ad.method.eoh.prompt import EoHPrompt
from llm4ad.method.eoh.sampler import EoHSampler
from llm4ad.task.optimization.fjsp_set.scheduler import Schedule,ScheduledOperation,validate_schedule

ROOT=Path(__file__).resolve().parents[4]
VERSION='fjsp-eoh-single-native-http-v1'
DEFAULTS=dict(version=VERSION,api_mode='real',evaluation_mode='solve',real_requests_authorized=False,
 candidate_cap=1050,api_attempt_cap=1050,per_candidate_attempt_cap=1,
 population_size=5,selection_num=2,initialization_request_cap=50,initialization_sample_cap=10,
 search_seed=501,solve_seed=501,window_seconds=172800,instance_timeout_seconds=30,
 data_manifest=None,comparison_a_run=None,comparison_b_run=None,
 expected_model='gpt-6.1-sol',provider=None,transport_binding=None,
 milestone_requests=[50,100,200,400,600,800,1000,1023,1050],mock_faults={},pause_after_tasks=None)
TEMPLATE='def priority('+', '.join(H_ARGS)+'):\n    return 0.0\n'

def task_description():
    return ('Design ONE FJSP ready-operation/machine action scoring heuristic. Minimize makespan. '
      'Use the exact seven-argument Python function '+TEMPLATE.splitlines()[0]+'. '
      'processing_time is the candidate operation duration; remaining_work is the sum of '
      'minimum alternative durations from this operation to the job end; remaining_operations includes '
      'the candidate operation. job_ready_time and machine_ready_time are current ready times; '
      'earliest_start=max(job_ready_time,machine_ready_time), earliest_finish=earliest_start+processing_time. '
      'Arguments are unnormalized physical values. Largest finite real priority wins; ties retain the '
      'first legal action in ascending job then machine order. The unchanged append-only constructor '
      'commits this action, with no local search or postprocessing. Complete train21 Fitness is '
      'mean(-Cmax/LB), maximized; LB=max(max_j sum_over_job_ops min_duration, sum_all_ops min_duration/M), '
      'not rounded. Do not access data, files, networks or globals. Closed H language: one function, '
      'finite scalar arithmetic, comparisons, conditionals; only abs/min/max/int/float/round/range '
      'builtins, no imports, external calls or fractional powers. Use the native boxed description '
      'and one complete fenced python function. Validation/test are never supplied.')

def sources():
    result=native.sources()
    for name in ('code/heuristic_design/problems/fjsp/eoh_single.py','experiments/common/run_fjsp_eoh_single.py'):
        result[name]=sha(ROOT/name)
    return result

def settings(path):
    path=Path(path).resolve();raw=read(path)
    if set(raw)-set(DEFAULTS):raise ValueError('unknown FJSP EoH fields: '+str(set(raw)-set(DEFAULTS)))
    c={**DEFAULTS,**raw}
    if c['version']!=VERSION or c['api_mode'] not in ('real','mock') or c['real_requests_authorized'] is not False:
        raise ValueError('new saved configuration must have real requests OFF')
    if c['evaluation_mode'] not in ('mock','solve') or (c['api_mode']=='real' and c['evaluation_mode']!='solve'):
        raise ValueError('real research requires solve; Mock engineering scores must be explicit')
    for k in ('candidate_cap','api_attempt_cap','population_size','selection_num','initialization_request_cap','initialization_sample_cap','window_seconds'):
        if type(c[k]) is not int or c[k]<1:raise ValueError('positive integer required: '+k)
    if not c['candidate_cap']==c['api_attempt_cap']<=1050 or type(c['per_candidate_attempt_cap']) is not int or c['per_candidate_attempt_cap']!=1:
        raise ValueError('total cap <=1050, initialization included, exactly one attempt per slot')
    if c['population_size']<2 or c['selection_num']!=2 or c['initialization_sample_cap']!=2*c['population_size']:
        raise ValueError('native N>=2, selection_num=2, evaluated initialization cap=2N')
    if not c['population_size']<=c['initialization_request_cap']<=min(50,c['candidate_cap']):
        raise ValueError('initialization HTTP subcap <=50 and within total cap')
    if c['instance_timeout_seconds']!=30:raise ValueError('shared first/recheck T30 required')
    for k in ('search_seed','solve_seed'):
        if type(c[k]) is not int or c[k]<0:raise ValueError('nonnegative integer seed required')
    ms=c['milestone_requests']
    if ms!=sorted(set(ms)) or any(type(n) is not int or not 1<=n<=c['candidate_cap'] for n in ms):raise ValueError('in-budget ordered milestones required')
    if c['pause_after_tasks'] is not None and (type(c['pause_after_tasks']) is not int or not 1<=c['pause_after_tasks']<=c['candidate_cap']):raise ValueError('invalid Mock pause cursor')
    if any(v not in ('failure','invalid','duplicate','invalid_evaluation') for v in c['mock_faults'].values()):raise ValueError('unsupported Mock fault')
    if c['api_mode']=='real' and (c['mock_faults'] or c['pause_after_tasks'] is not None):raise ValueError('Mock faults forbidden in real configuration')
    for k in ('data_manifest','comparison_a_run','comparison_b_run'):
        if not c[k]:raise ValueError('explicit input required: '+k)
        c[k]=str((path.parent/c[k]).resolve())
    if c['api_mode']=='mock':
        if c['transport_binding'] is not None:raise ValueError('Mock cannot claim accepted online transport')
        ClientConfig({'config':c,'budgets':{'logical_generation':c['candidate_cap']}})
    return c

def transport_status(c):
    if c['provider'] is None or c['transport_binding'] is None:return 'pending_external_API_reliability_conclusion'
    # A future minimal integration binds the external page's immutable technical evidence.
    b=c['transport_binding']
    if set(b)!={'evidence_file','sha256'} or sha(Path(b['evidence_file']))!=b['sha256']:raise ValueError('transport evidence missing/changed')
    if c['provider']['model']!=c['expected_model'] or c['provider']['expected_response_model']!=c['expected_model']:raise ValueError('model identity differs')
    ClientConfig({'config':c,'budgets':{'logical_generation':c['candidate_cap']}})
    return 'bound_evidence_requires_integration_review'

def comparison_identity(c,data,refs):
    runs=[Path(c[k]) for k in ('comparison_a_run','comparison_b_run')];items=[]
    for d in runs:
        p=read(d/'Protocol.json');s=read(d/'checkpoint.json')
        if sha(d/'Protocol.json')!=read(d/'Protocol.receipt.json')['sha256'] or s['identity']!=sha(d/'Protocol.json'):raise ValueError('historical identity mismatch')
        if (s['phase']!='completed' or p['config']['problem']!='fjsp'
            or p['config']['api_mode']!='real' or p['config']['evaluation_mode']!='solve'):
            raise ValueError('completed real-generation/real-solve FJSP reference required')
        if c['expected_model']!=p['config']['provider']['model']:raise ValueError('expected model differs from historical comparator')
        if p['instances']!=data or p['references']!=refs:raise ValueError('train21 ordered instance/NN-LB reference mismatch')
        for key in ('solve_seed','instance_timeout_seconds'):
            if c[key]!=p['config'][key]:raise ValueError('external evaluation mismatch: '+key)
        physical=[n for n in p['source_files'] if n.startswith('code/heuristic_design/problems/fjsp/') or n in (
         'code/heuristic_design/core/routing_evaluation.py','code/heuristic_design/core/lifecycle.py',
         'code/heuristic_design/core/constructive_state.py','code/fjsp_usage/offline_v2.py',
         'code/llm4ad/task/optimization/fjsp_set/scheduler.py','code/llm4ad/task/optimization/fjsp_set/instances.py')]
        if any(sha(ROOT/n)!=p['source_files'][n] for n in physical):raise ValueError('physical evaluator differs')
        # Existing TSP-only prompt extension is outside the constant-U evaluation path.
        old=subprocess.check_output(['git','show','0ce75da:code/heuristic_design/core/routing.py'],cwd=ROOT)
        if __import__('hashlib').sha256(old).hexdigest()!=p['source_files']['code/heuristic_design/core/routing.py']:raise ValueError('unreviewed original routing source')
        def without_prompt(v):return ast.dump(ast.Module(body=[n for n in ast.parse(v).body if getattr(n,'name','')!='build_prompt'],type_ignores=[]),include_attributes=False)
        if without_prompt(old)!=without_prompt((ROOT/'code/heuristic_design/core/routing.py').read_text()):raise ValueError('runtime routing changed beyond prompt')
        items.append(dict(directory=str(d),protocol_sha256=s['identity'],checkpoint_sha256=sha(d/'checkpoint.json'),
         initialization_requests=s['initialization_requests'],evolution_requests=s['generation_requests'],physical_files=physical))
    return dict(scope='historical exploratory; not end-to-end equal cost',runs=items,
     H_build_cost='separate historical upstream cost; not included or assumed zero',
     routing_bridge='TSP-only prompt extension; all non-build_prompt AST identical; constant-U host does not invoke it')

def preflight(path):
    c=settings(path);_,data,origin=inputs({'problem':'fjsp','data_manifest':c['data_manifest']})
    refs=precheck_instances('fjsp',data)  # arithmetic LB and structural checks only, no policy solve
    if c['api_mode']=='real' and (len(data)!=21 or any(r['split']!='train' for r in data)):raise ValueError('complete declared train21 required')
    binding=comparison_identity(c,data,refs) if c['api_mode']=='real' else {'scope':'Mock engineering only'}
    return c,data,refs,origin,binding

def prepare(directory,path,*,approve_budget=None,allow_api=False):
    c,data,refs,origin,binding=preflight(path)
    if c['api_mode']=='real':
        # This phase deliberately cannot launch merely by filling provider fields.
        raise PermissionError('transport integration pending; no real EoH authorization or requests created')
    if allow_api or approve_budget is not None:raise PermissionError('Mock must not carry paid approval')
    directory=Path(directory).resolve()
    if directory.exists() or not directory.is_relative_to(ROOT/'runs'):raise ValueError('new independent runs directory required')
    directory.mkdir(parents=True)
    write(directory/'Tasks.json',[dict(id=f'H-{i:04d}',stage='new',generation=None,operator='adaptive_EoH_slot') for i in range(c['candidate_cap'])])
    runtime={**c,'type':'native_eoh','candidate_kind':'h','problem':'fjsp',
             'recording_mode':'compact','window':10,'enabled_groups':list(native.evolution_v1.GROUPS),'cross_parents':2}
    p=dict(version=VERSION,config=runtime,instances=data,references=refs,input_provenance=origin,source_files=sources(),
      tasks_sha256=sha(directory/'Tasks.json'),prompt_sha256=digest(task_description()),comparison=binding,
      algorithm=dict(implementation='local LLM4AD EoH revision 2025/02/16; inherited TSP durable native adapter at 52cfc1d',
        operators=['I1',*native.OPERATORS],population_size=c['population_size'],selection_num=2,
        native_parent_selection='inverse rank with replacement',native_survival='register_function auto every N, stable score elitism; equal score/source penalized -inf',
        initialization='native auto-survival + explicit post-init survival; 2N sample ceiling and <=50 HTTP subcap',
        stopping='HTTP total cap includes initialization; no fixed generation target or retries',
        final_selection='all full valid train21 Fitness descending, fixed task ID ascending',local_search=False),
      git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
      budgets=dict(logical_generation=c['candidate_cap'],API_attempts=c['api_attempt_cap'],
        max_program_instances=c['candidate_cap']*len(data),max_solve_passes=2*c['candidate_cap']*len(data)),created_at=time.time())
    write(directory/'Protocol.json',p);(directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    write(directory/'checkpoint.json',dict(identity=sha(directory/'Protocol.json'),phase='prepared',cursor=0,tasks={},evaluations={},population=[],children=[],seen={},generation=0,pause_ack=0,
      eoh=dict(stage='initialization',native_generation=0,population=[],next_population=[],evaluated_samples=0,initialization_samples=0,initialization_requests=0,operator_cursor=0,evolution_survivals=0,np_rng=None)))
    return p

def protocol_state(directory):
    directory=Path(directory);p=read(directory/'Protocol.json');s=read(directory/'checkpoint.json')
    if p['version']!=VERSION or sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip() or s['identity']!=sha(directory/'Protocol.json'):raise ValueError('FJSP EoH identity mismatch')
    return p,s

class MockTransport:
    def __init__(self,c,faults):self.config=c;self.faults=faults;self.identity=digest({'FJSP_Mock':1,'config':c.payload(),'faults':faults});self.secret=''
    def redact(self,s):return s
    def preflight(self,s):
        if len(s.encode())>self.config.provider.max_prompt_bytes:raise ValueError('Mock prompt size')
    def dispatch(self,key,prompt,*,kind,on_sent):
        on_sent();i=int(key.split('/H-')[-1].split('/')[0]);fault=self.faults.get(f'H-{i:04d}')
        if fault=='failure':raise TimeoutError('MOCK no network')
        if fault=='invalid':return dict(text='MOCK invalid',usage=None,metadata={'mock':True})
        n=0 if fault=='duplicate' else i
        expr='1/0' if fault=='invalid_evaluation' else f'-processing_time + {n/100!r} * remaining_work'
        return dict(text='{MOCK fixed engineering fixture, not LLM output.}\n```python\n'+TEMPLATE.replace('0.0',expr)+'```',usage=dict(input_tokens=0,output_tokens=0),metadata={'mock':True})

class Adapter(native.Adapter):
    ROOT=ROOT;entrypoint='experiments/common/run_fjsp_eoh_single.py';CandidateError=CandidateError
    def read_state(self,directory):return protocol_state(directory)
    def check_run(self,directory):
        p,s=protocol_state(directory)
        if sha(Path(directory)/'Tasks.json')!=p['tasks_sha256'] or digest(task_description())!=p['prompt_sha256']:raise ValueError('FJSP tasks/prompt changed')
        if any(sha(ROOT/n)!=v for n,v in p['source_files'].items()):raise ValueError('frozen FJSP EoH source changed')
        self._engineering_mode=p['config']['evaluation_mode']=='mock'
        return p
    def summary(self,directory,write_files=False):
        result=super().summary(directory,write_files=False);p,s=protocol_state(directory)
        result.update(evaluation_mode=p['config']['evaluation_mode'],engineering_only=p['config']['evaluation_mode']=='mock')
        if write_files:write(Path(directory)/'results/Summary.json',result)
        return result
    def checked_candidate(self,row):
        c=validate_code(row['code'],description=row['description'],kind='h')
        if c.key!=row['key']:raise ValueError('H identity changed')
        return c
    def parse_candidate(self,text,config):
        if EoHSampler.trim_thought_from_response(text) is None:raise CandidateError('native boxed description required')
        return parse_response(text,kind='h')
    def build_prompt(self,config,task,parents,members):
        template=Converter.text_to_function(TEMPLATE);funcs=[native.make_function(r['candidate'],r['id'],r['fitness']) for r in parents]
        fn=getattr(EoHPrompt,'get_prompt_'+task['operator'].lower())
        if task['operator']=='I1':text=fn(task_description(),template)
        elif task['operator'] in ('E1','E2'):text=fn(task_description(),funcs,template)
        else:text=fn(task_description(),funcs[0],template)
        return text+'\nSerialization requirement: one boxed {description}, then exactly one fenced python block containing the complete function. No other text.\n'
    def transport(self,p):
        if p['config']['api_mode']!='mock':raise PermissionError('real transport binding pending external page')
        return MockTransport(self.client_config(p),p['config']['mock_faults'])
    def evaluate(self,directory,state,p,candidate):
        if p['config']['evaluation_mode']!='mock':return super().evaluate(directory,state,p,candidate)
        key=candidate.key
        if key in state['evaluations']:return read(Path(directory)/state['evaluations'][key]['path']),True
        score=-(1+int(key[:6],16)%1000/10000)
        invalid='1 / 0' in candidate.code or '1/0' in candidate.code
        result=dict(mock=True,engineering_only=True,valid=not invalid,fitness=None if invalid else score,
          instances=[] if invalid else [dict(file=r['file'],score=score) for r in p['instances']])
        path=Path(directory)/'evaluations'/key/'result.json';write(path,result)
        state['evaluations'][key]=dict(status='completed',path=str(path.relative_to(directory)),sha256=sha(path))
        write(Path(directory)/'checkpoint.json',state);return result,False
    def validate_result(self,result,instances):
        if type(result.get('valid')) is not bool:raise ValueError('explicit validity required')
        rows=result['instances']
        if len(rows)>len(instances) or [r['file'] for r in rows]!=[r['file'] for r in instances[:len(rows)]]:raise ValueError('ordered instance prefix required')
        if result['valid']:
            if len(rows)!=len(instances) or [r['file'] for r in rows]!=[r['file'] for r in instances] or result['fitness']!=sum(r['score'] for r in rows)/len(rows):raise ValueError('complete finite mean train vector required')
        elif result['fitness'] is not None:raise ValueError('invalid candidate fitness must be null')
        if result.get('mock'):
            if not getattr(self,'_engineering_mode',False):raise ValueError('Mock scores cannot enter physical result validation')
            if any(not math.isfinite(r['score']) for r in rows):raise ValueError('finite Mock scores required')
            return
        for row,spec in zip(rows,instances):
            from heuristic_design.core.routing_evaluation import semantic_row
            instance=decode_instance('fjsp',spec);schedule=Schedule(tuple(ScheduledOperation(**r) for r in row['solution']['operations']),row['solution']['makespan'])
            validate_schedule(instance,schedule)
            if (row['file']!=spec['file'] or row['captured_solves']!=2 or not row['feasible']
                or row['semantic_sha256']!=row['recheck_semantic_sha256']
                or digest(semantic_row(row,compact='member_sequence' in row))!=row['semantic_sha256']
                or row['source_before_sha256']!=row['source_after_sha256']
                or row['score']!=-schedule.makespan/lower_bound_v5(instance)):
                raise ValueError('FJSP physical/LB/recheck result invalid')
        if any(not math.isfinite(r['score']) for r in rows):raise ValueError('finite instance score required')

def export(directory):
    directory=Path(directory);p,s=protocol_state(directory);out=directory/'analysis';out.mkdir(exist_ok=True)
    values=list(s['tasks'].values())[:s['cursor']];rows=[dict(id=t['id'],operator=t['operator'],valid=t['valid'],fitness=t['fitness'],failure=t.get('failure'),AST_duplicate=t.get('AST_duplicate'),native_population_duplicate=t.get('native_population_duplicate'),parents=str(t['parents'])) for t in values]
    if rows:
        with (out/'candidates.csv').open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    journal=read(directory/'API_attempts.json') if (directory/'API_attempts.json').exists() else {'api_attempts':{}}
    request_rows=[dict(attempt_id=a['id'],logical_id=a['logical_id'],status=a['status'],send_confirmed=a.get('send_confirmed',False),
        input_tokens=(a.get('usage') or {}).get('input_tokens'),output_tokens=(a.get('usage') or {}).get('output_tokens'),
        started_at=a.get('started_at'),elapsed_seconds=a.get('elapsed_seconds')) for a in journal['api_attempts'].values()]
    per_instance=[]
    for t in values:
        if not t.get('evaluation_key'):continue
        result=read(directory/s['evaluations'][t['evaluation_key']]['path'])
        for row in result['instances']:
            per_instance.append(dict(candidate_id=t['id'],complete_candidate_valid=t['valid'],mock=result.get('mock',False),
                file=row['file'],score=row['score'],Cmax=(row.get('solution') or {}).get('makespan'),
                LB=next(r['reference'] for r in p['references'] if r['file']==row['file']),
                captured_solves=row.get('captured_solves'),semantic_sha256=row.get('semantic_sha256'),recheck_semantic_sha256=row.get('recheck_semantic_sha256')))
    for name,table in [('requests.csv',request_rows),('per_instance.csv',per_instance)]:
        if table:
            with (out/name).open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
    summary=Adapter().summary(directory);summary.update(training_only=p['config']['evaluation_mode']=='solve',actual_billed_cost=None,validation_status='not_run',quality_claim=False,
        known_input_tokens=sum(r['input_tokens'] or 0 for r in request_rows),known_output_tokens=sum(r['output_tokens'] or 0 for r in request_rows),
        usage_unknown_attempts=sum(r['input_tokens'] is None or r['output_tokens'] is None for r in request_rows))
    valid=[t for t in values if t['valid']]
    if valid:
        best=min(valid,key=lambda t:(-t['fitness'],t['id']));summary['champion_id']=best['id']
        if s['phase']=='completed':
            frozen=dict(selection='complete train21 Fitness descending, fixed task ID ascending',champion=best,config=p['config'],instances=p['instances'],references=p['references'],source_files=p['source_files'],protocol_sha256=s['identity'],validation_status='not_run')
            path=out/('frozen_engineering_candidate.json' if p['config']['evaluation_mode']=='mock' else 'frozen_training_champion.json')
            if path.exists() and read(path)!=frozen:raise ValueError('frozen champion cannot be overwritten')
            write(path,frozen);(out/'champion.py').write_text(best['candidate']['code'])
    write(out/'Summary.json',summary);return summary
