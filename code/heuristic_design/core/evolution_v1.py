"""Versioned parent-coverage search with a single durable coordinator.

Mock, fixed evaluation and gated real transports share the same coordinator.
Real dispatch requires frozen configuration authorization and an explicit CLI gate.
Unknown in-flight requests after a crash are never resent. Safe pause drains
one bounded batch. Old B1 and the generic legacy executor are unchanged.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import math
import os
from pathlib import Path
import random
import signal
import time

from .constructive_state import GROUPS, SPEC_SHA256, schema_id
from .routing import ABI, CandidateError, checked, parse, build_prompt, validate
from .search import ranked, survive, survive_behavior_first, _tuple_tree
from .storage import digest, read, write, sha

VERSION = 'parent-coverage-routing-v1'
ROOT = Path(__file__).resolve().parents[3]
DEFAULTS = dict(version=VERSION, api_mode='mock', real_requests_authorized=False,
    problem='fjsp', population_size=5, generations=20, search_seed=501, solve_seed=501,
    initialization='llm', initialization_candidate_cap=20, initialization_request_cap=20,
    generation_request_cap=200, api_concurrency=1, evaluation_concurrency=1,
    evaluation_mode='mock', window=10, enabled_groups=list(GROUPS),
    instance_timeout_seconds=30, mock_reverse_delay=False, mock_faults={},
    mock_delay_seconds=0.0, provider=None, api_attempt_cap=None,
    data_manifest=None, h_file=None, p0_file=None, state_schema=None,
    recording_mode='full', milestone_generations=[], survival_policy='fitness')


def config(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):
        raise ValueError('unknown configuration fields')
    c = {**DEFAULTS, **value}
    if c['survival_policy'] not in ('fitness','behavior_first'):
        raise ValueError('survival_policy must be fitness or behavior_first')
    if c['version'] != VERSION or c['api_mode'] not in ('mock','fixed','real') or type(c['real_requests_authorized']) is not bool:
        raise ValueError('invalid version/mode/authorization')
    if c['state_schema'] not in (None,schema_id(c['problem'])):raise ValueError('state schema/problem mismatch')
    if c['api_mode']!='real' and c['real_requests_authorized']:raise ValueError('offline modes cannot authorize requests')
    if c['api_mode']=='real':
        from fjsp_usage.research_real.config import ProviderConfig
        if not isinstance(c['provider'],dict):raise ValueError('real mode requires explicit provider')
        provider=ProviderConfig(**c['provider'])
        if not provider.api_key_env:raise ValueError('real mode requires environment credential name')
        if not c['data_manifest'] or not c['h_file'] or c['evaluation_mode']!='solve':
            raise ValueError('real search requires explicit dataset/H and real solve evaluation')
        expected=c['generation_request_cap']+(c['initialization_request_cap'] if c['initialization']=='llm' else 0)
        if type(c['api_attempt_cap']) is not int or c['api_attempt_cap']<expected:
            raise ValueError('explicit total attempt cap must cover initialization plus evolution')
    if c['api_mode']=='fixed' and (c['generations']!=0 or c['initialization']!='import' or c['evaluation_mode']!='solve'):
        raise ValueError('fixed evaluation requires G=0, imported policies and solve mode')
    if c['problem'] not in ('fjsp','tsp') or c['evaluation_mode'] not in ('mock','solve') or c['initialization'] not in ('llm','import'):
        raise ValueError('explicit problem, evaluation and initialization mode required')
    for k in ('population_size','generations','search_seed','solve_seed','initialization_candidate_cap',
              'initialization_request_cap','generation_request_cap','api_concurrency','evaluation_concurrency','window'):
        if type(c[k]) is not int or c[k] < (0 if k in ('search_seed','solve_seed','generation_request_cap','generations') else 1):
            raise ValueError('invalid nonnegative/positive integer: '+k)
    if c['population_size'] < 2:
        raise ValueError('N>=2 required; odd N supported')
    if c['generation_request_cap'] < 2*c['population_size']*c['generations']:
        raise ValueError('generation request cap cannot cover the frozen 2NG plan')
    if c['instance_timeout_seconds'] != 30:
        raise ValueError('v1 uses complete solve/recheck row T30 and separate 2s exit grace')
    if c['recording_mode'] not in ('full','compact') or (c['recording_mode']=='compact' and c['problem']!='fjsp'):
        raise ValueError('recording_mode must be full, or compact for FJSP')
    milestones=c['milestone_generations']
    if (not isinstance(milestones,list) or any(type(g) is not int or not 1<=g<=c['generations'] for g in milestones)
            or milestones!=sorted(set(milestones))):
        raise ValueError('milestone_generations must be ordered unique generations within G')
    if (not isinstance(c['enabled_groups'],list) or len(set(c['enabled_groups'])) != len(c['enabled_groups'])
            or not set(c['enabled_groups']) <= set(GROUPS) or 'construction' not in c['enabled_groups']):
        raise ValueError('invalid feature groups')
    if type(c['mock_reverse_delay']) is not bool or type(c['mock_delay_seconds']) not in (float,int) or not 0 <= c['mock_delay_seconds'] <= .2:
        raise ValueError('bounded Mock timing required')
    if not isinstance(c['mock_faults'],dict) or any(v not in ('duplicate','invalid','failure','invalid_evaluation') for v in c['mock_faults'].values()):
        raise ValueError('unknown offline fault fixture')
    return c


def source_identity():
    paths = set((ROOT/'code/heuristic_design/core').glob('*.py'))
    paths.update((ROOT/'code/heuristic_design/problems').rglob('*.py'))
    paths.update((ROOT/'code/heuristic_design/llm').glob('*.py'))
    paths.update((ROOT/'code/fjsp_usage/research_real').glob('*.py'))
    paths.add(ROOT/'experiments/common/manage.py')
    paths.update((ROOT/'code/llm4ad/task/optimization/fjsp_set').glob('*.py'))
    paths.update([ROOT/'code/fjsp_usage/offline_v2.py', ROOT/'code/fjsp_usage/research/candidates.py'])
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}


def select_survivors(population, children, c):
    policy = c.get('survival_policy','fitness')
    if policy not in ('fitness','behavior_first'):raise ValueError('unknown survival policy')
    selector = survive_behavior_first if policy == 'behavior_first' else survive
    return selector(population, children, c['population_size'])


def save(directory, state):
    write(directory/'checkpoint.json',state)
    write(directory/'checkpoint.receipt.json',{'sha256':sha(directory/'checkpoint.json'),'identity':state['identity']})


def store_evaluation(directory, task, key, result, mode):
    """Keep both receipt paths; compact files share bytes where supported."""
    path=directory/'evaluations'/key/'result.json'
    if path.exists():raise FileExistsError('evaluation evidence already exists: '+str(path))
    origin=directory/'worker-receipts'/task['id']/'result.json'
    if mode=='compact' and origin.exists() and read(origin)==result:
        path.parent.mkdir(parents=True,exist_ok=True)
        try:
            os.link(origin,path)
            return path,'hardlink'
        except FileExistsError:raise
        except OSError as exc:
            import errno
            if exc.errno not in (errno.EXDEV,errno.EPERM,errno.EACCES,errno.ENOTSUP,errno.ENOSYS):raise
    write(path,result)
    return path,'copy'


def save_milestone(directory, state, protocol):
    g=state['generation']
    if g not in protocol['config'].get('milestone_generations',[]):return
    value={'protocol_sha256':state['identity'],'generation':g,'summary':state['generations'][-1],
           'population':state['population'],'initialization_requests':state['initialization_requests'],
           'generation_requests':state['generation_requests'],
           'evaluations':{r['candidate']['key']:state['evaluations'][r['candidate']['key']] for r in state['population']},
           'notice':'Result snapshot only; resume uses the live checkpoint and original cumulative budget.'}
    path=directory/f'milestones/G{g:03d}.json'
    if path.exists() and read(path)!=value:raise FileExistsError('milestone evidence changed')
    write(path,value)
    write(path.with_suffix('.receipt.json'),{'sha256':sha(path),'protocol_sha256':state['identity']})


def prepare(directory, settings, *, imports=None, h_members=None, instances=None):
    from heuristic_design.problems import routing_fixtures as fixtures
    import platform
    c = config(settings)
    from .terminal_ops import inputs
    loaded_h,loaded_data,provenance=inputs(c)
    if h_members is None:h_members=loaded_h
    if instances is None:instances=loaded_data
    if imports is None and c['p0_file']:imports=read(c['p0_file'])
    directory = Path(directory).resolve()
    if directory.exists():
        raise ValueError('new run directory required; never overwrite evidence')
    hs = fixtures.members(c['problem']) if h_members is None else h_members
    data = fixtures.instances(c['problem'],seed=c['solve_seed']) if instances is None else instances
    if len(hs) < 2 or not data or any(r.get('split') not in ('synthetic-development','train') for r in data):
        raise ValueError('nonempty train/development set and >=2 frozen H required')
    fixtures.compile_members(c['problem'],hs)
    references = fixtures.precheck_instances(c['problem'],data)
    if c['initialization'] == 'import':
        if not isinstance(imports,list) or len(imports) != c['population_size']:
            raise ValueError('import mode requires exactly N declared sources')
        keys = []
        for row in imports:
            if not isinstance(row.get('source'),str) or not row['source']:
                raise ValueError('explicit P0 source provenance required')
            keys.append(checked(row['candidate'],len(hs)).key)
        if len(set(keys)) != len(keys):
            raise ValueError('import P0 must be AST distinct; no borrowing baseline')
    elif imports is not None:
        raise ValueError('LLM initialization cannot borrow imported P0')
    protocol = {'version':VERSION,'config':c,'state_schema':schema_id(c['problem']),
        'state_spec_sha256':SPEC_SHA256,'u_abi':ABI,'members':hs,'instances':data,'references':references,'imports':imports,
        'input_provenance':provenance,'source_files':source_identity(),'machine':{'system':platform.system(),'machine':platform.machine(),
            'python':platform.python_version(),'cpu_count':os.cpu_count()},
        'selection':('best behavior representatives, then ranked duplicate fill; fitness descending/id ascending; global elite retained'
                     if c['survival_policy']=='behavior_first' else 'fitness descending, id ascending; parent+valid unique child elitism at generation end'),
        'H_order_source':'explicit frozen declaration order; no implicit performance-rank prior',
        'initialization':'new-state complete reevaluation; old/imported Fitness is never reused',
        'objective':'MOCK_SYNTHETIC_NOT_QUALITY' if c['evaluation_mode']=='mock' else ('mean(-Cmax/LB_v5)' if c['problem']=='fjsp' else 'mean(-length/NN)'),
        'reference_rule':'LB_v5' if c['problem']=='fjsp' else 'NN fixed start 0/city-id ties/closed tour',
        'cost_scope':'T30 complete solve/recheck row including transport, then separate 2s exit grace',
        'recovery':'safe pause drains a bounded batch; ambiguous in-flight crash requires investigation, no automatic resend',
        'real_API_calls':0}
    directory.mkdir(parents=True)
    write(directory/'Protocol.json',protocol)
    write(directory/'Protocol.receipt.json',{'sha256':sha(directory/'Protocol.json')})
    st = {'version':VERSION,'identity':sha(directory/'Protocol.json'),'phase':'prepared',
          'generation':0,'population':[],'tasks':{},'plans':{},'seen':{},'evaluations':{},
          'initialization_candidates':0,'initialization_requests':0,'generation_requests':0,
          'rng':random.Random(c['search_seed']).getstate(),'generations':[],
          'initialization_complete':False,'pause_ack':0,'completed_tasks':0}
    save(directory,st)
    return {'directory':str(directory),'phase':st['phase'],'protocol':st['identity'],'real_API_calls':0}


def check(directory):
    p = read(directory/'Protocol.json')
    if p.get('version') != VERSION or sha(directory/'Protocol.json') != read(directory/'Protocol.receipt.json')['sha256']:
        raise ValueError('foreign/changed protocol; never reinterpret legacy checkpoint')
    config(p['config'])
    if p['state_schema'] != schema_id(p['config']['problem']) or p['state_spec_sha256'] != SPEC_SHA256 or p['u_abi'] != ABI:
        raise ValueError('state/ABI mismatch')
    for name,value in p['source_files'].items():
        if sha(ROOT/name) != value:
            raise ValueError('bound source changed: '+name)
    s = read(directory/'checkpoint.json')
    if (s.get('version') != VERSION or s.get('identity') != sha(directory/'Protocol.json')
            or read(directory/'checkpoint.receipt.json') != {'identity':s['identity'],'sha256':sha(directory/'checkpoint.json')}):
        raise ValueError('checkpoint identity/receipt mismatch')
    for task in s['tasks'].values():
        if task['status'] in ('request_reserved','evaluation_reserved'):
            raise ValueError('ambiguous in-flight task; never resend or auto-replay')
        for k in ('prompt','response'):
            if k+'_path' in task and sha(directory/task[k+'_path']) != task[k+'_sha256']:
                raise ValueError('durable '+k+' changed')
    for g, plan in s['plans'].items():
        if sha(directory/plan['path']) != plan['sha256']:
            raise ValueError('generation plan changed')
    for key,e in s['evaluations'].items():
        if sha(directory/e['path']) != e['sha256'] or e['binding'] != digest({'protocol':s['identity'],'candidate':key}):
            raise ValueError('evaluation cache identity changed')
    if s['generation_requests'] > p['config']['generation_request_cap'] or s['initialization_requests'] > p['config']['initialization_request_cap']:
        raise ValueError('request budget exceeded')
    return p,s


def plan_generation(population, generation, rng):
    """Every original parent: one CROSS subject and one independent MUTATE."""
    frozen = [dict(row) for row in population]
    if len(frozen) < 2 or len({r['id'] for r in frozen}) != len(frozen):
        raise ValueError('distinct frozen population N>=2 required')
    tasks = []
    for i,subject in enumerate(frozen):
        partner = rng.choice([j for j in range(len(frozen)) if j != i])
        for op, parents in [('CROSS',[subject,frozen[partner]]),('MUTATE',[subject])]:
            tasks.append({'id':f'G{generation:03d}-{i:03d}-{op}', 'stage':'evolution',
                          'generation':generation,'operator':op,'subject':subject['id'],
                          'parents':[r['id'] for r in parents], 'parent_keys':[r['candidate']['key'] for r in parents],
                          'parent_records':parents,'status':'planned','fitness':None,'valid':False})
    return tasks


def mock_generate(task, prompt, c, member_count):
    """Deterministic raw responses, with optional reverse completion and faults."""
    delay = c['mock_delay_seconds']
    if c['mock_reverse_delay']:
        delay += ((100-int(digest(task['id'])[:4],16)%100)/100)*.012
    if delay:
        time.sleep(delay)
    fault = c['mock_faults'].get(task['id'])
    if fault == 'failure':
        raise TimeoutError('MOCK transport failure fixture')
    if fault == 'invalid':
        return 'MOCK invalid response without code fence'
    n = int(digest(task['id'])[:7],16)
    if fault == 'duplicate':
        code = 'def use_heuristics(state):\n    return 0\n'
    else:
        a,b = n%member_count,(n+1)%member_count
        code = (f'def use_heuristics(state):\n    fixture_tag = {n}\n'
                f'    return {a} if state["construction_progress"] < {(n%89+5)/100!r} else {b}\n')
    return 'MOCK engineering response, not an LLM or quality claim.\n```python\n'+code+'```'


def mock_evaluate(task, p):
    """Artificial objective forces generational turnover for lineage testing."""
    from .routing import compile_candidate
    c = p['config']
    if c['mock_faults'].get(task['id']) == 'invalid_evaluation':
        return {'valid':False,'fitness':None,'instances':[],'mock':True,'error':'MOCK evaluation failure'}
    rank = int(digest(task['id'])[:6],16)/16**6
    score = task.get('generation',0) + rank
    u = compile_candidate(checked(task['candidate'],len(p['members'])),len(p['members']))
    from .constructive_state import FIELDS, freeze
    probes = []
    for x in (0.,.2,.5,.8,.99):
        values = {k:None for k in FIELDS}
        values.update(construction_progress=x,action_breadth_fraction=1-x,
                      committed_objective_fraction=x/2,has_history=False,
                      history_count=0,recent_history_count=0)
        probes.append(freeze({**values,'availability':{k:v is not None for k,v in values.items()}}))
    behavior = [u(packet) for packet in probes]
    return {'valid':True,'fitness':score,'mock':True,
            'instances':[{'file':r['file'],'score':score} for r in p['instances']],
            'behavior_sha256':digest(behavior),'behavior':behavior,
            'notice':'MOCK synthetic objective and five progress probes; no solver quality inference'}


def _batch(function, items, width, *args):
    """Workers return values only. Coordinator persists in stable task order."""
    def timed(item):
        started = time.time()
        monotonic = time.monotonic()
        try:
            result = {'ok':True,'value':function(item,*args)}
        except Exception as exc:
            result = {'ok':False,'error_type':type(exc).__name__,'error':str(exc)[:500]}
        return {**result,'timing':{'started_at_unix':started,'finished_at_unix':time.time(),
                'started_monotonic':monotonic,'finished_monotonic':time.monotonic(),
                'scope':'candidate function in bounded task pool; not provider-side execution'}}
    values = {}
    with ThreadPoolExecutor(max_workers=width) as pool:
        pending = {pool.submit(timed,item):item['id'] for item in items}
        for future in as_completed(pending):
            key = pending[future]
            values[key] = future.result()
    return values


def request_pause(directory):
    directory = Path(directory)
    path = directory/'Pause.json'
    sequence = read(path)['sequence']+1 if path.exists() else 1
    write(path,{'sequence':sequence,'action':'pause_after_draining_bounded_batch'})
    return {'requested':True,'sequence':sequence}


def run(directory, *, max_tasks=None, evaluate=None, allow_api=False, before_evolution=None):
    """Single writer; optional fail-closed gate after P0 and before any generation."""
    directory = Path(directory).resolve()
    p,s = check(directory)
    from heuristic_design.llm.routing_transport import preflight
    preflight(p['config'],allow_api)
    if s['phase'] in ('completed','initialization_incomplete'):
        return {'phase':s['phase'],'generation':s['generation']}
    lock = directory/'.coordinator.lock'
    fd = os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        f.write(str(os.getpid()))
    c = p['config']
    if evaluate is None:
        if c['evaluation_mode'] == 'mock':
            evaluate = mock_evaluate
        else:
            from .routing_evaluation import evaluate_task
            evaluate = evaluate_task
    stopped = [False]
    old_handlers = {}
    # Threads in tests may call the coordinator; signals belong to the main thread.
    import threading
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT,signal.SIGTERM):
            old_handlers[sig] = signal.signal(sig,lambda *a:stopped.__setitem__(0,True))
    started_count = s['completed_tasks']
    if (directory/'Pause.json').exists(): s['pause_ack'] = read(directory/'Pause.json')['sequence']
    normal = False
    try:
        s['phase']='running';save(directory,s);log_progress(directory,s,p)
        while True:
            if (stopped[0] or max_tasks is not None and s['completed_tasks']-started_count >= max_tasks
                    or (directory/'Pause.json').exists() and read(directory/'Pause.json')['sequence'] > s['pause_ack']):
                s['phase']='paused';break
            if not s['initialization_complete']:
                if len(s['population']) == c['population_size']:
                    s['population'] = ranked(s['population'])
                    s['initialization_complete'] = True
                    write(directory/'populations/P000.json',s['population'])
                    save(directory,s)
                    continue
                limit = c['population_size'] if c['initialization']=='import' else min(c['initialization_candidate_cap'],c['initialization_request_cap'])
                if s['initialization_candidates'] >= limit:
                    s['phase']='initialization_incomplete';break
                # Initialization may replace duplicates/invalid responses only
                # inside its separate, predeclared caps; never borrow baselines.
                n = min(max(c['api_concurrency'],c['evaluation_concurrency']),c['population_size']-len(s['population']),limit-s['initialization_candidates'])
                batch = []
                for _ in range(n):
                    i = s['initialization_candidates']
                    task = {'id':f'INIT-{i:04d}','stage':'initialization','generation':0,'operator':'INIT',
                            'parents':[],'parent_keys':[],'parent_records':[], 'status':'planned','fitness':None,'valid':False}
                    if c['initialization']=='import':
                        task.update(candidate=p['imports'][i]['candidate'],source=p['imports'][i]['source'],status='parsed')
                    s['tasks'][task['id']] = task
                    s['initialization_candidates'] += 1
                    batch.append(task)
                save(directory,s)
            else:
                # Also runs on resume. A rejected imported P0 must never reach
                # planning, request reservation, or generation transport.
                if before_evolution is not None:
                    if before_evolution(directory) is not True:
                        s['phase']='blocked';break
                    before_evolution = None
                if s['generation'] == c['generations']:
                    s['phase']='completed';break
                g = s['generation']+1
                if str(g) not in s['plans']:
                    rng = random.Random();rng.setstate(_tuple_tree(s['rng']))
                    before = rng.getstate()
                    tasks = plan_generation(s['population'],g,rng)
                    path = directory/f'plans/G{g:03d}.json'
                    write(path,{'generation':g,'population':s['population'],'tasks':tasks,
                                'rng_before':before,'rng_after':rng.getstate()})
                    s['plans'][str(g)]={'path':str(path.relative_to(directory)),'sha256':sha(path)}
                    s['rng']=rng.getstate()
                    for task in tasks:s['tasks'][task['id']]=task
                    save(directory,s)
                tasks = [s['tasks'][t['id']] for t in read(directory/s['plans'][str(g)]['path'])['tasks']]
                batch = [t for t in tasks if t['status']!='completed'][:max(c['api_concurrency'],c['evaluation_concurrency'])]
                if not batch:
                    children = [_individual(t,s) for t in tasks if t['valid']]
                    old = s['population']
                    s['population'] = select_survivors(old,children,c)
                    s['generation']=g
                    selected = {r['id'] for r in s['population']}
                    row = {'generation':g,'planned_candidates':len(tasks),'generation_requests':s['generation_requests'],
                           'valid_unique_children':len(children),'children_selected':[t['id'] for t in tasks if t['id'] in selected],
                           'best_fitness':s['population'][0]['fitness'],
                           'population_mean':sum(r['fitness'] for r in s['population'])/len(s['population']),
                           'behavior_groups':len({r['behavior_sha256'] for r in s['population']}),
                           'population_ids':[r['id'] for r in s['population']], 'mock':c['evaluation_mode']=='mock'}
                    s['generations'].append(row)
                    write(directory/f'populations/P{g:03d}.json',s['population'])
                    save_milestone(directory,s,p)
                    log_progress(directory,s,p)
                    save(directory,s)
                    continue
            _execute_batch(directory,s,p,batch,evaluate)
            if s['phase'] == 'blocked':break
        save(directory,s)
        log_progress(directory,s,p)
        normal=True
    except BaseException:
        # Leave lock and all reservations intact. Resuming must not replay an
        # ambiguous send. Safe pauses are the supported automatic recovery path.
        s['phase']='blocked';save(directory,s)
        raise
    finally:
        for sig,handler in old_handlers.items():signal.signal(sig,handler)
        if normal:lock.unlink()
    return {'phase':s['phase'],'generation':s['generation'],'completed_tasks':s['completed_tasks'],
            'initialization_requests':s['initialization_requests'],'generation_requests':s['generation_requests'],
            'api_attempts_reserved':s['initialization_requests']+s['generation_requests'] if c['api_mode']=='real' else 0}


def _individual(t,s):
    e = s['evaluations'][t['candidate']['key']]
    return {'id':t['id'],'candidate':t['candidate'],'fitness':t['fitness'],
            'behavior_sha256':e['behavior_sha256']}


def _execute_batch(directory,s,p,batch,evaluate):
    c = p['config']
    needed = [t for t in batch if t['status']=='planned']
    for task in needed:
        counter,cap = ('initialization_requests','initialization_request_cap') if task['stage']=='initialization' else ('generation_requests','generation_request_cap')
        if s[counter] >= c[cap]:raise ValueError('predeclared request cap exhausted')
        s[counter] += 1
        if c['api_mode']=='real' and s['initialization_requests']+s['generation_requests']>c['api_attempt_cap']:raise ValueError('total API attempt cap exhausted')
        task['request_key']=s['identity']+'/'+task['id']
        prompt = build_prompt(c['problem'],task,task['parent_records'],p['members'],window=c['window'],enabled_groups=c['enabled_groups'])
        path=directory/'prompts'/(task['id']+'.txt');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(prompt)
        task.update(status='request_reserved',prompt_path=str(path.relative_to(directory)),prompt_sha256=sha(path))
    save(directory,s)  # all sends reserved before dispatch; workers never touch ledger
    api_started = time.perf_counter()
    from heuristic_design.llm.routing_transport import generate as real_generate
    generator=real_generate if c['api_mode']=='real' else mock_generate
    responses = _batch(lambda task:generator(task,(directory/task['prompt_path']).read_text(),c,len(p['members'])),needed,c['api_concurrency']) if needed else {}
    api_seconds=time.perf_counter()-api_started
    for task in needed:
        reply=responses[task['id']]
        if c['api_mode']=='real':task['sent_confirmed']=bool(reply.get('ok') and reply['value'].get('sent'))
        path=directory/'responses'/(task['id']+'.json');write(path,{**reply,'mock':c['api_mode']=='mock'})
        task.update(response_path=str(path.relative_to(directory)),response_sha256=sha(path),
                    status='response_saved',api_batch_seconds=api_seconds,generation_timing=reply['timing'])
        if c['api_mode']=='real' and reply.get('ok'):
            task['wire_send_confirmed_at_unix']=reply['value'].get('wire_send_confirmed_at_unix')
        if reply['ok'] and (c['api_mode']!='real' or reply['value'].get('text') is not None):
            text=reply['value']['text'] if c['api_mode']=='real' else reply['value']
            try:task.update(candidate=asdict(parse(text,len(p['members']))),status='parsed')
            except CandidateError as exc:task.update(status='completed',failure='parse_or_constraint',error=str(exc))
        else:task.update(status='completed',failure='mock_transport' if c['api_mode']=='mock' else 'real_transport',error='request failed; see redacted response receipt')
    save(directory,s)
    evaluate_tasks=[]
    for task in batch:
        if task['status']!='parsed':continue
        key=task['candidate']['key']
        if key in s['seen']:
            task.update(status='completed',failure='AST_duplicate',duplicate_of=s['seen'][key])
            continue
        s['seen'][key]=task['id']
        task['status']='evaluation_reserved'
        evaluate_tasks.append(task)
    save(directory,s)
    eval_started=time.perf_counter()
    evaluations=_batch(evaluate,evaluate_tasks,c['evaluation_concurrency'],{**p,'run_directory':str(directory)})
    eval_seconds=time.perf_counter()-eval_started
    for task in evaluate_tasks:
        response=evaluations[task['id']]
        task['evaluation_timing']=response['timing']
        if response['ok']:
            result=response['value']
            _validate_result(result,p)
        else:
            # Infrastructure uncertainty is not a scientific invalid fitness.
            task.update(failure='evaluation_infrastructure',error=response['error'])
            s['phase']='blocked';save(directory,s)
            raise RuntimeError('evaluation infrastructure failure: '+response['error'])
        key=task['candidate']['key']
        path,storage=store_evaluation(directory,task,key,result,c.get('recording_mode','full'))
        task['result_storage']=storage
        s['evaluations'][key]={'path':str(path.relative_to(directory)),'sha256':sha(path),
            'binding':digest({'protocol':s['identity'],'candidate':key}),
            'behavior_sha256':result.get('behavior_sha256'),'valid':result['valid']}
        task.update(status='completed',valid=result['valid'],fitness=result['fitness'],evaluation_batch_seconds=eval_seconds,
                    evaluation_timing=response['timing'])
        if not result['valid']:task['failure']='evaluation_invalid'
        if task['stage']=='initialization' and task['valid']:s['population'].append(_individual(task,s))
    s['completed_tasks'] += len(batch)
    write(directory/'batch-receipts'/f'{s["completed_tasks"]:06d}.json',{
        'tasks':[t['id'] for t in batch],
        'api_concurrency':c['api_concurrency'],'evaluation_concurrency':c['evaluation_concurrency'],
        'response_completion_order':list(responses),'evaluation_completion_order':list(evaluations),
        'generation_task_timings':{k:r['timing'] for k,r in responses.items()},
        'evaluation_task_timings':{k:r['timing'] for k,r in evaluations.items()},
        'api_batch_seconds':api_seconds,'evaluation_batch_seconds':eval_seconds,
        'semantics_commit_order':[t['id'] for t in batch],
        'note':'generation and evaluation have independently bounded pools; bounded waves run in stages'})
    # Source changes while work is in flight block the run without accepting
    # another batch. This also rejects any cached result from another revision.
    if any(sha(ROOT/k)!=v for k,v in p['source_files'].items()):
        raise ValueError('source changed during batch')
    save(directory,s)
    log_progress(directory,s,p)


def log_progress(directory,s,p):
    import json
    from .terminal_ops import progress
    row={**progress(s,p),'at':time.time()}
    print(json.dumps(row,ensure_ascii=False),flush=True)
    with (directory/'Events.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')


def _validate_result(result,p):
    if type(result.get('valid')) is not bool or result.get('mock') != (p['config']['evaluation_mode']=='mock'):
        raise ValueError('explicit evaluator provenance and validity required')
    if not result['valid']:
        if result.get('fitness') is not None:raise ValueError('invalid candidate cannot have fitness')
        return
    if (type(result.get('fitness')) not in (int,float) or not math.isfinite(result['fitness'])
            or [r['file'] for r in result['instances']] != [r['file'] for r in p['instances']]
            or any(type(r['score']) not in (int,float) or not math.isfinite(r['score']) for r in result['instances'])
            or result['fitness'] != sum(r['score'] for r in result['instances'])/len(p['instances'])
            or not result.get('behavior_sha256')):
        raise ValueError('complete finite all-instance evaluation required')
