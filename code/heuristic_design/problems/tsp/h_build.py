"""Independent TSP H pool + existing complementary selection, over shared execution.

No H evolution, manual refill, old-response imports, or upstream EoH-S claim.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import time

from heuristic_design.core import evolution_v1, execution, routing
from heuristic_design.core.routing_evaluation import evaluate_task
from heuristic_design.core.storage import digest, read, sha, write
from heuristic_design.core.terminal_ops import inputs
from heuristic_design.llm.legacy import ClientConfig, JsonCandidateTransport
from fjsp_usage.research.sets import complementary_survival, ranked
from . import candidates

ROOT=Path(__file__).resolve().parents[4]
VERSION='tsp-h10-independent-pool-cpm-v1'
K=10
METRICS={'fitness':'mean(-length/NN_length), higher is better; entire declared train20',
 'selection':'CPM greedy instance-score envelope; first maximum mean; gain ties by mean descending / task ID ascending',
 'numbering':'selected members sorted by complete train fitness descending / task ID ascending',
 'duplicate':'canonical AST key, first occurrence only; score ties are NOT duplicates',
 'baseline':'same ordered instance content, NN references, H keys/order, solve_seed, T30 and objective; otherwise placeholder',
 'relative':'100*(F_U-F_baseline)/abs(F_baseline); mean normalized-length reduction, not mean per-instance percent',
 'wlt':'tour length: win if L_U < L_B - 1e-12; loss if > L_B + 1e-12; else tie',
 'diversity':'number of distinct full selected-H sequence vectors in each stored U population',
 'complementarity':'mean per-instance best selected single-H score minus best mean single-H; diagnostic only, not a routing upper bound',
 'plots':'only committed results; no interpolation before first valid result; Mock always labeled engineering'}
DEFAULTS={'version':VERSION,'api_mode':'real','real_requests_authorized':False,'member_count':10,
 'candidate_cap':40,'api_attempt_cap':40,'per_candidate_attempt_cap':1,'search_seed':501,
 'solve_seed':501,'window_seconds':43200,'instance_timeout_seconds':30,
 'data_manifest':None,'provider':None,'milestone_requests':[10,20,30,40],
 'mock_faults':{},'pause_after_tasks':None}


def settings(path):
    path=Path(path).resolve();v=read(path)
    if set(v)-set(DEFAULTS):raise ValueError('unknown H configuration fields')
    c={**DEFAULTS,**v}
    if c['version']!=VERSION or c['api_mode'] not in ('real','mock') or c['real_requests_authorized'] is not False:
        raise ValueError('saved H configuration must default to real requests OFF')
    if c['member_count']!=10 or type(c['candidate_cap']) is not int or c['candidate_cap']<10:
        raise ValueError('exactly ten final H; explicit pool budget >=10')
    if c['api_attempt_cap']!=c['candidate_cap'] or c['per_candidate_attempt_cap']!=1:
        raise ValueError('one attempt per logical slot, no retries or refill')
    if c['instance_timeout_seconds']!=30 or c['window_seconds']!=43200:
        raise ValueError('fixed T30 and persistent 12-hour window')
    if any(type(c[k]) is not int or c[k]<0 for k in ('search_seed','solve_seed')):raise ValueError('integer seeds required')
    nodes=c['milestone_requests']
    if not isinstance(nodes,list) or nodes!=sorted(set(nodes)) or any(type(x) is not int or not 1<=x<=c['candidate_cap'] for x in nodes):
        raise ValueError('ordered unique budget nodes required')
    if c['pause_after_tasks'] is not None and (type(c['pause_after_tasks']) is not int or c['pause_after_tasks']<1):
        raise ValueError('pause_after_tasks must be positive or null')
    if not isinstance(c['mock_faults'],dict) or any(x not in ('failure','invalid','duplicate','invalid_evaluation') for x in c['mock_faults'].values()):
        raise ValueError('unknown offline fixture fault')
    if c['api_mode']=='real' and (c['mock_faults'] or c['pause_after_tasks'] is not None):raise ValueError('engineering faults only in Mock')
    c['data_manifest']=str((path.parent/c['data_manifest']).resolve())
    ClientConfig({'config':c,'budgets':{'logical_generation':c['candidate_cap']}})
    return c


def prompt():
    return '''Design ONE constructive symmetric Euclidean TSP action-scoring heuristic independently.
Coordinates are float64 in [0,1]^2. Start city 0, visit all other cities exactly once, then close to 0.
No local search. Highest raw priority chooses the next city; exact ties use smallest city ID.
Signature: def priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress):
distance_current=current-to-candidate; distance_start=candidate-to-city-0. mean_remaining_distance and
nearest_remaining_distance summarize candidate-to-OTHER-unvisited-city edges, zero if none remain.
ALL FOUR distance inputs are divided by sqrt(2). progress=committed decisions/(n-1), before the action.
The closing edge counts in final length but does not call the heuristic. Return one finite real scalar.
Training fitness maximizes mean(-tour_length / deterministic_nearest_neighbor_length) on the ENTIRE
declared train20. NN starts at 0, smallest-city ties, closed tour. NN is not an optimum or lower bound.
No parent, earlier code, fitness, score ranking, validation or test feedback is supplied.
Use scalar assignments, if/else, arithmetic and abs/min/max/int/float/round. No imports, attributes,
subscripts, loops, recursion, collections, randomness, external calls, U or other H. Integer literal
power exponents 0..8 only. Numeric constants <=1e9; intermediates must be finite and <=1e100.
All paths return. Return a short description followed by exactly one fenced python function.
'''


def preflight(path):
    c=settings(path)
    _,data,origin=inputs({'problem':'tsp','data_manifest':c['data_manifest']})
    if c['api_mode']=='real' and (len(data)!=20 or any(r['split']!='train' or len(r['value']['coordinates'])!=50 for r in data)):
        raise ValueError('real H construction requires complete train20, 50 cities each')
    from heuristic_design.problems.routing_fixtures import precheck_instances
    refs=precheck_instances('tsp',data)
    return c,data,refs,origin


def source_files():
    values=evolution_v1.source_identity()
    for name in ('experiments/common/run_tsp_h10.py','experiments/common/run_tsp_routing.py',
                 'experiments/common/summarize_tsp.py','tools/tsp_plot_results.py',
                 'code/fjsp_usage/research/sets.py','code/fjsp_usage/research/operations.py',
                 'code/fjsp_usage/usage_v2/access.py'):
        if (ROOT/name).exists():values[name]=sha(ROOT/name)
    return values


def prepare(directory,config_path,*,approve_budget=None):
    c,data,refs,origin=preflight(config_path)
    if c['api_mode']=='real':
        if approve_budget!=c['api_attempt_cap']:raise PermissionError('explicit --approve-budget must match H API attempt cap')
        if not __import__('os').environ.get(c['provider']['api_key_env']):raise ValueError('credential environment variable absent; no secret printed')
        c['real_requests_authorized']=True  # only the user's future explicit terminal invocation
    elif approve_budget is not None:raise ValueError('Mock must not approve a paid budget')
    directory=Path(directory).resolve()
    if not directory.is_relative_to(ROOT/'runs') or directory.exists():raise ValueError('new run directory inside this worktree runs/ required')
    files=source_files()
    tasks=[{'id':f'H-{i:04d}','stage':'new','generation':None,'operator':'I1'} for i in range(c['candidate_cap'])]
    directory.mkdir(parents=True)
    write(directory/'Tasks.json',tasks)
    runtime={**c,'type':'ind','candidate_kind':'h','population_size':10,'cross_parents':2,
             'problem':'tsp','recording_mode':'compact','window':10,'enabled_groups':list(evolution_v1.GROUPS)}
    p={'version':VERSION,'config':runtime,'instances':data,'references':refs,'input_provenance':origin,
       'source_files':files,'tasks_sha256':sha(directory/'Tasks.json'),'prompt_sha256':digest(prompt()),
       'metrics':METRICS,'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
       'git_diff_sha256':digest(subprocess.check_output(['git','diff','HEAD'],cwd=ROOT,text=True)),
       'config_source_sha256':sha(config_path),'evaluation_method':'one H + constant pure U, real compact solve/recheck',
       'H_method':'independent I1 pool; no H evolution; existing CPM once after ALL slots complete',
       'human_reviewed':False,'created_at':time.time(),
       'budgets':{'logical_generation':c['candidate_cap'],'API_attempts':c['api_attempt_cap'],
                  'max_program_instances':c['candidate_cap']*len(data),'max_solve_passes':2*c['candidate_cap']*len(data)}}
    write(directory/'Protocol.json',p);(directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    write(directory/'checkpoint.json',{'identity':sha(directory/'Protocol.json'),'phase':'prepared','cursor':0,
        'tasks':{},'evaluations':{},'population':[],'children':[],'seen':{},'generation':0,'pause_ack':0})
    (directory/'Launcher_snapshot.py').write_bytes((ROOT/'experiments/common/run_tsp_h10.py').read_bytes())
    write(directory/'Analysis_protocol.json',METRICS)
    return p


def protocol_state(directory):
    directory=Path(directory);p=read(directory/'Protocol.json');s=read(directory/'checkpoint.json')
    if p.get('version')!=VERSION or sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip() or s['identity']!=sha(directory/'Protocol.json'):
        raise ValueError('H protocol/checkpoint identity mismatch')
    return p,s


def committed(directory,p,s):
    """A reserved last task is not a committed scientific result."""
    plan=read(directory/'Tasks.json');rows=[]
    for task in plan[:s['cursor']]:
        record=s['tasks'][task['id']]
        if record['status']!='completed':raise ValueError('committed task status differs')
        rows.append(record)
    return rows


def pool(directory,p,s):
    seen=set();valid=[]
    for t in committed(directory,p,s):
        key=t.get('candidate',{}).get('key')
        if not key or key in seen:continue
        seen.add(key)
        if not t['valid']:continue
        ev=s['evaluations'][key];path=directory/ev['path']
        if sha(path)!=ev['sha256']:raise ValueError('H result hash changed')
        r=read(path);Adapter.validate_result(r,p['instances'])
        valid.append({'id':t['id'],'candidate':t['candidate'],'fitness':r['fitness'],
                      'scores':[x['score'] for x in r['instances']],'evaluation_sha256':ev['sha256']})
    return valid


def freeze(directory):
    p,s=protocol_state(directory)
    if s['phase']!='completed' or s['cursor']!=p['config']['candidate_cap']:return {'status':'not_terminal_complete'}
    population=pool(directory,p,s)
    if len(population)<10:
        value={'status':'insufficient_valid_unique_H','required':10,'actual':len(population),
               'manual_refill':False,'extra_requests':0,'protocol_sha256':s['identity']}
        write(directory/'H_build_outcome.json',value);return value
    greedy=complementary_survival(population,10);selected=ranked(greedy)
    artifact={'kind':VERSION,'member_count':10,'origin_mode':p['config']['api_mode'],
        'engineering_only':p['config']['api_mode']!='real','human_reviewed':False,
        'protocol_sha256':s['identity'],'training_instances':[{'file':r['file'],'sha256':r['sha256'],
          'source_sha256':r.get('source_sha256')} for r in p['instances']],
        'references':p['references'],'source_files':p['source_files'],'git_commit':p['git_commit'],
        'members':[r['candidate'] for r in selected],
        'lineage':[{'member_id':i,'source_task':r['id'],'parents':[],'operator':'I1',
                    'fitness':r['fitness'],'scores':r['scores'],'candidate_key':r['candidate']['key'],
                    'code_sha256':hashlib.sha256(r['candidate']['code'].encode()).hexdigest(),'evaluation_sha256':r['evaluation_sha256']} for i,r in enumerate(selected)],
        'greedy_selection_order':[r['id'] for r in greedy],'selection':METRICS['selection'],
        'numbering':METRICS['numbering'],'training_only':True}
    artifact['artifact_sha256']=digest(artifact)
    path=directory/'H_frozen.json'
    if path.exists() and read(path)!=artifact:raise ValueError('frozen H cannot be replaced')
    if not path.exists():write(path,artifact)
    write(directory/'H_frozen.receipt.json',{'sha256':sha(path),'protocol_sha256':s['identity']})
    write(directory/'H_build_outcome.json',{'status':'frozen','member_count':10,'protocol_sha256':s['identity'],
                                         'H_sha256':sha(path),'origin_mode':artifact['origin_mode']})
    handoff(directory,p,artifact)
    return read(directory/'H_build_outcome.json')


def check_frozen(path,*,real=False):
    path=Path(path).resolve();h=read(path);payload={k:v for k,v in h.items() if k!='artifact_sha256'}
    if h.get('kind')!=VERSION or digest(payload)!=h['artifact_sha256'] or h['member_count']!=10 or len(h['members'])!=10:
        raise ValueError('invalid TSP H10 freeze')
    receipt=read(path.with_name('H_frozen.receipt.json'))
    if receipt!={'sha256':sha(path),'protocol_sha256':h['protocol_sha256']}:raise ValueError('H receipt changed')
    p,s=protocol_state(path.parent)
    if s['phase']!='completed' or h['protocol_sha256']!=s['identity']:raise ValueError('H parent not completed')
    if real and h['origin_mode']!='real':raise ValueError('Mock H cannot enter real U search')
    from heuristic_design.problems.routing_fixtures import compile_members
    compile_members('tsp',h['members'])
    return h


def handoff(directory,p,h):
    out=directory/'next';p0=[]
    for i in range(10):p0.append({'source':f'frozen-H10-constant-{i}',
        'candidate':asdict(routing.validate(f'def use_heuristics(state):\n    return {i}\n',f'Constant frozen H{i}',10))})
    write(out/'singles-p0.json',p0)
    # Recreate source files from the frozen input snapshot, never reread mutable old data.
    manifest={'problem':'tsp','split':p['instances'][0]['split'],'instances':[]}
    for i,r in enumerate(p['instances']):
        path=out/'data'/f'{i:03d}.json';write(path,r['value'])
        manifest['instances'].append({'file':r['file'],'path':f'data/{i:03d}.json','sha256':sha(path)})
    write(out/'train.manifest.json',manifest)
    base={'problem':'tsp','state_schema':'constructive-common-v1-tsp','api_mode':'fixed','evaluation_mode':'solve',
        'real_requests_authorized':False,'recording_mode':'compact','h_file':'../H_frozen.json',
        'data_manifest':'train.manifest.json','p0_file':'singles-p0.json','population_size':10,'generations':0,
        'generation_request_cap':0,'initialization':'import','search_seed':p['config']['search_seed'],
        'solve_seed':p['config']['solve_seed'],'instance_timeout_seconds':30,'evaluation_concurrency':1,
        'api_concurrency':1,'window':10}
    write(out/'singles.fixed.json',base)
    u={**base,'api_mode':'real','population_size':5,'generations':20,'generation_request_cap':200,
       'initialization':'llm','initialization_candidate_cap':20,'initialization_request_cap':20,
       'api_attempt_cap':220,'p0_file':None,'provider':p['config']['provider'],
       'api_concurrency':2,'evaluation_concurrency':2,'milestone_generations':[5,10,15,20]}
    write(out/'u-real.pending.json',u)
    write(out/'u-mock-solve.json',{**u,'api_mode':'mock','population_size':2,'generations':1,
       'generation_request_cap':4,'initialization_candidate_cap':4,'initialization_request_cap':4,
       'api_attempt_cap':None,'milestone_generations':[1]})


class MockTransport:
    def __init__(self,config,faults):
        self.config=config;self.faults=faults;self.identity=digest({'h10_mock':1,'config':config.payload(),'faults':faults});self.secret=''
    def redact(self,text):return text
    def preflight(self,text):
        if len(text.encode())>self.config.provider.max_prompt_bytes:raise ValueError('prompt bytes exceeded')
    def dispatch(self,key,text,*,kind,on_sent):
        on_sent();index=int(key.split('/H-')[-1].split('/')[0]);fault=self.faults.get(f'H-{index:04d}')
        if fault=='failure':raise TimeoutError('Mock transport timeout, no network')
        if fault=='invalid':return {'text':'Mock malformed response','usage':None,'metadata':{'mock':True}}
        n=0 if fault=='duplicate' else index
        code='def priority('+', '.join(candidates.H_ARGS)+'):\n    return '+('1 / 0' if fault=='invalid_evaluation' else
            f'-distance_current + {(n-5)/40!r} * (1-progress) * distance_start + {(n%3)/20!r} * nearest_remaining_distance')+'\n'
        return {'text':'MOCK engineering fixture, not a real LLM.\n```python\n'+code+'```',
                'usage':{'input_tokens':0,'output_tokens':0},'metadata':{'mock':True,'model':'MOCK_NOT_LLM'}}


class Adapter:
    ROOT=ROOT;entrypoint='experiments/common/run_tsp_h10.py'
    read=staticmethod(read);write=staticmethod(write);sha=staticmethod(sha);digest=staticmethod(digest)
    CandidateError=candidates.CandidateError
    def check_run(self,directory):
        directory=Path(directory);p,s=protocol_state(directory)
        if sha(directory/'Tasks.json')!=p['tasks_sha256'] or p['prompt_sha256']!=digest(prompt()):raise ValueError('H plan/prompt changed')
        if any(sha(ROOT/n)!=v for n,v in p['source_files'].items()):raise ValueError('bound H source changed')
        if p['config']['candidate_cap']!=p['budgets']['logical_generation']:raise ValueError('H budget changed')
        return p
    def members(self,directory):return []
    def checked_candidate(self,row):return candidates.checked(row,1)
    def parse_candidate(self,text,config):return candidates.parse(text,'h',1)
    def build_prompt(self,config,task,parents,members):
        if parents or members or task['operator']!='I1':raise ValueError('independent H generation only')
        return prompt()
    def client_config(self,p):return ClientConfig(p)
    def transport(self,p):
        c=self.client_config(p)
        return MockTransport(c,p['config']['mock_faults']) if p['config']['api_mode']=='mock' else JsonCandidateTransport(c)
    @staticmethod
    def validate_result(result,instances):
        if not isinstance(result.get('valid'),bool):raise ValueError('H validity missing')
        rows=result['instances']
        if result['valid']:
            if [r['file'] for r in rows]!=[r['file'] for r in instances] or result['fitness']!=sum(r['score'] for r in rows)/len(instances):
                raise ValueError('complete H training vector required')
        elif result['fitness'] is not None:raise ValueError('invalid H has no fitness')
        for row,spec in zip(rows,instances):
            from .solver import distances,tour_length,nearest_neighbor
            d=distances(spec['value']['coordinates']);length=tour_length(d,row['solution']['tour'])
            if (row['file']!=spec['file'] or row['captured_solves']!=2 or not row['feasible']
                or row['semantic_sha256']!=row['recheck_semantic_sha256'] or row['score']!=-length/nearest_neighbor(d)[1]
                or length!=row['solution']['length']):raise ValueError('H physical/recheck row invalid')
    def evaluate(self,directory,state,p,candidate):
        key=candidate.key
        if key in state['evaluations']:return read(directory/state['evaluations'][key]['path']),True
        state['evaluations'][key]={'status':'reserved'};write(directory/'checkpoint.json',state)
        taskid=next(k for k,t in state['tasks'].items() if t['status']=='reserved')
        u=asdict(routing.validate('def use_heuristics(state):\n    return 0\n','Host constant for H evaluation',1))
        result=evaluate_task({'id':taskid,'candidate':u},{**p,'run_directory':str(directory),'members':[asdict(candidate)]})
        self.validate_result(result,p['instances'])
        path=directory/'worker-receipts'/taskid/'result.json'
        state['evaluations'][key]={'status':'completed','path':str(path.relative_to(directory)),'sha256':sha(path)}
        write(directory/'checkpoint.json',state);return result,False
    def on_commit(self,directory,state,p):
        rows=committed(directory,p,state);valid=pool(directory,p,state)
        summary={'cursor':state['cursor'],'committed_candidates':len(rows),'valid_unique_H':len(valid),
                 'generation':0,'API_attempt_cap':p['config']['api_attempt_cap'],'as_of':time.time()}
        write(directory/'Progress.json',summary)
        print(json.dumps({**summary,'stage':'H_independent_pool','generation_transport':p['config']['api_mode'],
                          'evaluation_mode':'solve','real_requests':state['cursor'] if p['config']['api_mode']=='real' else 0}),flush=True)
        if state['cursor'] in p['config']['milestone_requests']:
            write(directory/f'milestones/Q{state["cursor"]:04d}.json',{
                **summary,'protocol_sha256':state['identity'],'tasks':rows,'pool':valid,
                'note':'intermediate candidate pool, not a final frozen H'})
        with (directory/'Population_snapshots.jsonl').open('a') as f:
            f.write(json.dumps({'cursor':state['cursor'],'pool_ids':[r['id'] for r in valid],'as_of':time.time()})+'\n')
        if p['config']['pause_after_tasks']==state['cursor']:
            execution.stop(directory,adapter=self)
    def summary(self,directory,write_files=False):
        p,s=protocol_state(directory);rows=committed(directory,p,s);valid=pool(directory,p,s)
        result={'phase':s['phase'],'cursor':s['cursor'],'planned':p['config']['candidate_cap'],
            'valid_unique_H':len(valid),'generation':0,'required_members':10,'origin_mode':p['config']['api_mode']}
        if write_files:
            write(directory/'results/Summary.json',result)
            if s['phase']=='completed':result['freeze']=freeze(directory)
        return result
