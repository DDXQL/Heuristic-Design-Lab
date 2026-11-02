"""Bounded single-H adaptation of the vendored LLM4AD EoH.

Native prompts, parent selection, score/code duplicate handling and survival
are used directly. Shared execution supplies the HTTP ledger and safe pause.
No H10 imports, manual seeds, account authorization or validation selection.
"""
from dataclasses import asdict
import copy
import math
import os
from pathlib import Path
import subprocess
import time

import numpy as np
from llm4ad.base import TextFunctionProgramConverter as Converter
from llm4ad.method.eoh.population import Population
from llm4ad.method.eoh.prompt import EoHPrompt
from llm4ad.method.eoh.sampler import EoHSampler

from heuristic_design.core import evolution_v1, execution
from heuristic_design.core.storage import read, write, sha, digest
from heuristic_design.core.terminal_ops import inputs
from heuristic_design.llm.legacy import ClientConfig, JsonCandidateTransport
from . import candidates, h_build

ROOT = Path(__file__).resolve().parents[4]
VERSION = 'tsp-eoh-single-native-http-v1'
OPERATORS = ('E1', 'E2', 'M1', 'M2')  # exactly the local EoH._iteratively_use_eoh_operator order
TEMPLATE = 'def priority('+', '.join(candidates.H_ARGS)+'):\n    return 0.0\n'
METRICS = {k:h_build.METRICS[k] for k in ('fitness','relative','wlt')}
METRICS.update(relative='100*(F_EoH-F_pipeline)/abs(F_pipeline); relative mean normalized-length reduction',
    wlt='EoH vs existing pipeline tour length; absolute tolerance 1e-12',
    selection='all complete valid train H, fitness descending / task ID ascending',
    population='native EoH score elitism; no CPM',
    duplicate='AST duplicates reuse evaluation; native source-string OR equal mean score penalized -inf in population',
    budget='HTTP reservations including failed, repeated and uncertain attempts; at most one attempt per slot',
    comparison='same maximum 260, actual 253 of the existing pipeline also reported; EoH at253 and final both exported')
DEFAULTS = dict(version=VERSION, api_mode='real', real_requests_authorized=False,
    candidate_cap=260, api_attempt_cap=260, per_candidate_attempt_cap=1,
    population_size=5, selection_num=2, initialization_request_cap=20,
    initialization_sample_cap=10, search_seed=501, solve_seed=501,
    window_seconds=43200, instance_timeout_seconds=30, data_manifest=None,
    provider=None, comparison_h_run=None, comparison_u_run=None, comparison_fixed_run=None,
    milestone_requests=[40,50,100,150,200,250,253,260], mock_faults={}, pause_after_tasks=None)


def task_description():
    # Same problem, source language and evaluator as the frozen H10 experiment.
    return h_build.prompt().replace(' independently.', '.').replace(
        'No parent, earlier code, fitness, score ranking, validation or test feedback is supplied.\n', '')


def sources():
    result = h_build.source_files()
    for folder in ('code/llm4ad/method/eoh', 'code/llm4ad/base'):
        for path in (ROOT/folder).glob('*.py'):
            result[str(path.relative_to(ROOT))] = sha(path)
    for name in ('experiments/common/run_tsp_eoh_single.py', 'experiments/common/summarize_tsp_eoh.py',
                 'tools/tsp_eoh_plot_results.py'):
        result[name] = sha(ROOT/name)
    return result


def settings(path):
    path = Path(path).resolve(); raw = read(path)
    if set(raw)-set(DEFAULTS): raise ValueError('unknown EoH configuration fields')
    c = {**DEFAULTS, **raw}
    if c['version'] != VERSION or c['api_mode'] not in ('real','mock') or c['real_requests_authorized'] is not False:
        raise ValueError('saved EoH config must default to real requests OFF')
    for key in ('candidate_cap','api_attempt_cap','population_size','selection_num','initialization_request_cap','initialization_sample_cap'):
        if type(c[key]) is not int or c[key] < 1: raise ValueError('positive integer required: '+key)
    if not 2 <= c['population_size'] or c['selection_num'] != 2:
        raise ValueError('native EoH crossover selection_num=2 and N>=2 required')
    if not c['candidate_cap'] == c['api_attempt_cap'] <= 260 or c['per_candidate_attempt_cap'] != 1:
        raise ValueError('one HTTP attempt per slot, cap <=260, no retries/refill')
    if c['initialization_sample_cap'] != 2*c['population_size']:
        raise ValueError('native initialization evaluated-sample ceiling must be 2N')
    if not c['population_size'] <= c['initialization_request_cap'] <= c['candidate_cap']:
        raise ValueError('bounded initialization HTTP cap required')
    if c['instance_timeout_seconds'] != 30 or c['window_seconds'] != 43200:
        raise ValueError('same T30, persistent 12h wall window required')
    if any(type(c[k]) is not int or c[k] < 0 for k in ('search_seed','solve_seed')): raise ValueError('integer seeds required')
    if c['milestone_requests'] != sorted(set(c['milestone_requests'])) or any(type(n) is not int or not 1<=n<=c['candidate_cap'] for n in c['milestone_requests']):
        raise ValueError('ordered in-budget milestones required')
    if c['api_mode']=='real' and (c['mock_faults'] or c['pause_after_tasks'] is not None):
        raise ValueError('engineering faults forbidden in real runs')
    if any(v not in ('failure','invalid','duplicate','invalid_evaluation') for v in c['mock_faults'].values()):
        raise ValueError('unsupported Mock fault')
    for key in ('data_manifest','comparison_h_run','comparison_u_run','comparison_fixed_run'):
        if not c[key]: raise ValueError('explicit path required: '+key)
        c[key] = str((path.parent/c[key]).resolve())
    ClientConfig({'config':c,'budgets':{'logical_generation':c['candidate_cap']}})
    return c


def comparison_identity(c, data, refs, new_sources):
    """Read existing evidence only. Never solve, regenerate, or mutate it."""
    hdir,udir,fdir = [Path(c[k]) for k in ('comparison_h_run','comparison_u_run','comparison_fixed_run')]
    hp,hs = h_build.protocol_state(hdir)
    from experiments.common._search_reports import protocol_state as previous_state
    up,us = previous_state(udir)
    fp,fs = previous_state(fdir)
    h_build.check_frozen(hdir/'H_frozen.json',real=True)
    if any(s['phase']!='completed' for s in (hs,us,fs)): raise ValueError('comparison requires completed H/U/fixed evidence')
    if hp['config']['api_mode']!='real' or up['config']['api_mode']!='real' or fp['config']['api_mode']!='fixed':
        raise ValueError('Mock/foreign comparison evidence forbidden')
    if [r['sha256'] for r in data] != [r['sha256'] for r in up['instances']] or [r['file'] for r in data] != [r['file'] for r in up['instances']]:
        raise ValueError('ordered train instance content differs')
    for other in (hp,fp,up):
        if [r['sha256'] for r in other['instances']] != [r['sha256'] for r in data] or other['references'] != refs:
            raise ValueError('training data / NN references differ')
        for key in ('solve_seed','instance_timeout_seconds'):
            if other['config'][key] != c[key]: raise ValueError('evaluation condition differs: '+key)
    if hp['config']['provider'] != c['provider'] or up['config']['provider'] != c['provider']:
        raise ValueError('same frozen model, endpoint and request settings required')
    # Execution/search/reporting intentionally change; physical evaluator may not.
    physical = ['code/heuristic_design/core/routing_evaluation.py',
        'code/heuristic_design/core/constructive_state.py', 'code/heuristic_design/core/routing.py',
        'code/heuristic_design/problems/routing_fixtures.py']
    physical += [n for n in up['source_files'] if n.startswith('code/heuristic_design/problems/tsp/')
                 and not n.endswith(('h_build.py','reporting.py','eoh_single.py','eoh_reporting.py'))]
    for n in physical:
        if any(other['source_files'].get(n) != new_sources.get(n) for other in (hp,fp,up)):
            raise ValueError('physical solve/H-language source differs: '+n)
    if hp['config']['api_attempt_cap']+up['config']['api_attempt_cap'] != 260:
        raise ValueError('comparison ceiling is not the declared 40+220')
    files = [d/n for d in (hdir,udir,fdir) for n in ('Protocol.json','checkpoint.json')]
    files += [hdir/'H_frozen.json',hdir/'H_frozen.receipt.json',hdir/'API_attempts.json']
    files += sorted((udir/'responses').glob('*.json'))
    # The bound result files allow an independent report after launch; no inference from chats.
    for d,s in ((hdir,hs),(udir,us),(fdir,fs)):
        files += [d/v['path'] for v in s['evaluations'].values()]
    return dict(status='compatible_train_physics_and_model', ceiling=260,
        existing_H_slots=hs['cursor'], existing_U_slots=us['initialization_requests']+us['generation_requests'],
        actual_existing_slots=hs['cursor']+us['initialization_requests']+us['generation_requests'],
        h_protocol_sha256=hs['identity'], u_protocol_sha256=us['identity'], fixed_protocol_sha256=fs['identity'],
        files={str(p):sha(p) for p in files},
        physical_source_files=physical, native_request_concurrency=1, previous_U_request_concurrency=up['config']['api_concurrency'],
        notice='Same maximum budget, not guaranteed equal realized calls/tokens/CPU. Single train run; no generalization claim.')


def preflight(path):
    c = settings(path)
    _,data,origin = inputs({'problem':'tsp','data_manifest':c['data_manifest']})
    if c['api_mode']=='real' and (len(data)!=20 or any(r['split']!='train' or len(r['value']['coordinates'])!=50 for r in data)):
        raise ValueError('complete ordered train20 with 50 cities required')
    from heuristic_design.problems.routing_fixtures import precheck_instances
    refs = precheck_instances('tsp',data)
    binding = comparison_identity(c,data,refs,sources()) if c['api_mode']=='real' else {'status':'Mock engineering, no scientific comparison'}
    return c,data,refs,origin,binding


def make_function(candidate, task_id, score, vector=None):
    f = Converter.text_to_function(candidate['code'])
    if f is None: raise ValueError('native EoH converter rejected admitted H')
    f.algorithm=candidate['description']; f.score=score; f.score_list=vector
    f.eoh_id=task_id; f.eoh_candidate=copy.deepcopy(candidate)
    return f


def pack(f):
    return dict(id=f.eoh_id, candidate=f.eoh_candidate, algorithm=f.algorithm,
        score=f.score if f.score is not None and math.isfinite(f.score) else None,
        negative_infinity=f.score is not None and math.isinf(f.score), score_list=f.score_list)


def unpack(v):
    return make_function(v['candidate'],v['id'],float('-inf') if v['negative_infinity'] else v['score'],v['score_list'])


def population(state, c):
    value=state['eoh']; p=Population(c['population_size'],generation=value['native_generation'])
    p._population=[unpack(v) for v in value['population']]
    p._next_gen_pop=[unpack(v) for v in value['next_population']]
    return p


def save_population(state, p):
    state['eoh']['population']=[pack(f) for f in p._population]
    state['eoh']['next_population']=[pack(f) for f in p._next_gen_pop]
    state['eoh']['native_generation']=p.generation
    state['population']=[dict(id=f.eoh_id,candidate=f.eoh_candidate,fitness=f.score) for f in p._population if math.isfinite(f.score)]


def prepare(directory, config_path, *, approve_budget=None, allow_api=False):
    c,data,refs,origin,binding=preflight(config_path)
    if c['api_mode']=='real':
        if not allow_api or approve_budget != c['api_attempt_cap']: raise PermissionError('explicit --allow-api --approve-budget matching THIS EoH cap required')
        if not os.environ.get(c['provider']['api_key_env']): raise ValueError('credential environment variable absent; no secret printed')
        c['real_requests_authorized']=True
    elif allow_api or approve_budget is not None: raise PermissionError('Mock must not approve paid requests')
    directory=Path(directory).resolve()
    if directory.exists() or not directory.is_relative_to(ROOT/'runs'): raise ValueError('new directory under this worktree runs/ required')
    directory.mkdir(parents=True)
    tasks=[dict(id=f'H-{i:04d}',stage='new',generation=None,operator='adaptive_EoH_slot') for i in range(c['candidate_cap'])]
    write(directory/'Tasks.json',tasks)
    runtime={**c,'type':'native_eoh','candidate_kind':'h','problem':'tsp','evaluation_mode':'solve','recording_mode':'compact','window':10,
             'enabled_groups':list(evolution_v1.GROUPS),'cross_parents':2}
    protocol=dict(version=VERSION,config=runtime,instances=data,references=refs,input_provenance=origin,
        source_files=sources(),tasks_sha256=sha(directory/'Tasks.json'),prompt_sha256=digest(task_description()),
        metrics=METRICS,comparison=binding,
        algorithm=dict(implementation='vendored LLM4AD EoH, eoh.py revision 2025/02/16',
            operators=['I1',*OPERATORS],parent_selection='native Population.selection; inverse rank 1/(r+N), replacement allowed',
            survival='native register_function + survival every N registered functions; stable score descending',
            duplicates='native canonical function-string OR equal mean score => -inf population score; AST duplicates reuse solve only',
            native_sample_count='increments only on admitted function entering evaluator, not HTTP/parse failures',
            conversion='bound 260 serial HTTP reservations, one per slot; native evaluated count separately; no max_sample_nums=260 claim',
            initialization='native auto-survival / 2N evaluated-sample cap, plus 20 HTTP cap; native explicit post-init survival retained',
            final_selection='all complete valid train candidates, fitness descending / stable task ID ascending; validation never loaded',
            adaptation='closed common H language, bounded HTTP/initialization, durable scheduler, explicit JSON-to-fenced serialization',
            max_generations=None,concurrency=1,temporary_failure='3 consecutive => safe pause; no automatic resume'),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        git_diff_sha256=digest(subprocess.check_output(['git','diff','HEAD'],cwd=ROOT,text=True)),created_at=time.time(),
        budgets=dict(logical_generation=c['candidate_cap'],API_attempts=c['api_attempt_cap'],
            max_program_instances=c['candidate_cap']*len(data),max_solve_passes=2*c['candidate_cap']*len(data)))
    write(directory/'Protocol.json',protocol);(directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    write(directory/'checkpoint.json',dict(identity=sha(directory/'Protocol.json'),phase='prepared',cursor=0,tasks={},evaluations={},
        population=[],children=[],seen={},generation=0,pause_ack=0,
        eoh=dict(stage='initialization',native_generation=0,population=[],next_population=[],evaluated_samples=0,
            initialization_samples=0,initialization_requests=0,operator_cursor=0,evolution_survivals=0,np_rng=None)))
    return protocol


class Adapter(h_build.Adapter):
    ROOT=ROOT
    entrypoint='experiments/common/run_tsp_eoh_single.py'
    pause_on_transport_streak=True

    def check_run(self,directory):
        p,s=protocol_state(directory)
        if sha(Path(directory)/'Tasks.json')!=p['tasks_sha256'] or digest(task_description())!=p['prompt_sha256']:
            raise ValueError('EoH task plan/prompt changed')
        if any(sha(ROOT/n)!=v for n,v in p['source_files'].items()): raise ValueError('bound EoH source changed')
        return p

    def task_context(self,directory,state,p,task,index):
        c=p['config']; v=state['eoh']; native=population(state,c)
        if v['stage']=='initialization' and (native.generation>0 or v['initialization_samples']>=c['initialization_sample_cap'] or v['initialization_requests']>=c['initialization_request_cap']):
            native.survival()  # exactly the explicit post-init survival in native EoH.run
            save_population(state,native)
            if len(native)<c['selection_num'] or not any(math.isfinite(f.score) for f in native._population):
                state['phase']='initialization_incomplete';state['stop_reason']='native population smaller than selection_num or no finite parent; no manual refill'
                write(Path(directory)/'checkpoint.json',state);return None,[]
            v['stage']='evolution'
            write(Path(directory)/'populations/P000_initial.json',state['eoh'])
        seed_state=v['np_rng']
        old=np.random.get_state()
        try:
            if seed_state: np.random.set_state((seed_state[0],np.array(seed_state[1],dtype=np.uint32),seed_state[2],seed_state[3],seed_state[4]))
            else: np.random.seed(c['search_seed']%(2**32))
            op='I1' if v['stage']=='initialization' else OPERATORS[v['operator_cursor']%len(OPERATORS)]
            parents=[] if op=='I1' else [native.selection() for _ in range(2 if op in ('E1','E2') else 1)]
            rs=np.random.get_state();v['np_rng']=[rs[0],rs[1].tolist(),int(rs[2]),int(rs[3]),float(rs[4])]
        finally: np.random.set_state(old)
        return {**task,'operator':op,'eoh_generation':v['evolution_survivals'],'native_generation':native.generation},[
            dict(id=f.eoh_id,candidate=copy.deepcopy(f.eoh_candidate),fitness=f.score) for f in parents]

    def build_prompt(self,config,task,parents,members):
        template=Converter.text_to_function(TEMPLATE)
        funcs=[make_function(r['candidate'],r['id'],r['fitness']) for r in parents]
        fn=getattr(EoHPrompt,'get_prompt_'+task['operator'].lower())
        if task['operator']=='I1': prompt=fn(task_description(),template)
        elif task['operator'] in ('E1','E2'): prompt=fn(task_description(),funcs,template)
        else: prompt=fn(task_description(),funcs[0],template)
        return prompt+'\nSerialization requirement: one boxed {description}, then exactly one fenced python block containing the complete function. No other text.\n'

    def parse_candidate(self,text,config):
        if EoHSampler.trim_thought_from_response(text) is None: raise candidates.CandidateError('native EoH boxed description required')
        return candidates.parse(text,'h',1)

    def transport(self,p):
        if p['config']['api_mode']=='real': return JsonCandidateTransport(self.client_config(p))
        return MockTransport(self.client_config(p),p['config']['mock_faults'])

    def commit_candidate(self,directory,state,p,record,candidate,result):
        v=state['eoh']; native=population(state,p['config']); before=native.generation
        if record['operator']=='I1': v['initialization_requests']+=1
        else: v['operator_cursor']+=1  # errors consume their operator opportunity, never extra requests
        if candidate is not None:
            v['evaluated_samples']+=1
            if record['operator']=='I1': v['initialization_samples']+=1
            f=make_function(asdict(candidate),record['id'],result['fitness'] if result['valid'] else None,
                            [r['score'] for r in result['instances']] if result['valid'] else None)
            native.register_function(f)
            record['native_population_score']=f.score if f.score is not None and math.isfinite(f.score) else None
            record['native_population_duplicate']=bool(result['valid'] and math.isinf(f.score))
        if v['stage']=='evolution' and native.generation>before:
            v['evolution_survivals']+=native.generation-before
        save_population(state,native);state['generation']=v['evolution_survivals']

    def on_commit(self,directory,state,p):
        directory=Path(directory);v=state['eoh']
        if not v['next_population']:
            write(directory/f'populations/P{v["native_generation"]:03d}.json',v)
        progress=self.summary(directory)
        write(directory/'Progress.json',{**progress,'as_of':time.time()})
        print(__import__('json').dumps(progress,ensure_ascii=False),flush=True)
        if state['cursor'] in p['config']['milestone_requests']:
            write(directory/f'milestones/Q{state["cursor"]:04d}.json',dict(cursor=state['cursor'],as_of=time.time(),
                eoh=copy.deepcopy(v),tasks=list(state['tasks'].values()),protocol_sha256=state['identity']))
        if p['config']['pause_after_tasks']==state['cursor']: execution.stop(directory,adapter=self)

    def summary(self,directory,write_files=False):
        p,s=protocol_state(directory);jpath=Path(directory)/'API_attempts.json'
        attempts=read(jpath)['api_attempts'] if jpath.exists() else {}
        values=list(s['tasks'].values())[:s['cursor']]
        unique={t['candidate']['key'] for t in values if t['valid']}
        best=max((t['fitness'] for t in values if t['valid']),default=None)
        result=dict(phase=s['phase'],cursor=s['cursor'],planned=p['config']['candidate_cap'],
            request_slots=len(attempts),confirmed_sends=sum(a.get('send_confirmed',False) for a in attempts.values()),
            valid_unique_H=len(unique),best_fitness=best,evolution_survival_updates=s['generation'],
            native_generation=s['eoh']['native_generation'],evaluated_samples=s['eoh']['evaluated_samples'],
            stage=s['eoh']['stage'],generation_transport=p['config']['api_mode'],evaluation_mode='solve',
            API_attempt_cap=p['config']['api_attempt_cap'],writer_lock=(Path(directory)/'.execution.lock').exists())
        if write_files: write(Path(directory)/'results/Summary.json',result)
        return result


def protocol_state(directory):
    directory=Path(directory);p=read(directory/'Protocol.json');s=read(directory/'checkpoint.json')
    if p['version']!=VERSION or sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip() or s['identity']!=sha(directory/'Protocol.json'):
        raise ValueError('EoH protocol/checkpoint identity mismatch')
    return p,s


class MockTransport(h_build.MockTransport):
    def dispatch(self,key,text,*,kind,on_sent):
        on_sent();index=int(key.split('/H-')[-1].split('/')[0]);fault=self.faults.get(f'H-{index:04d}')
        if fault=='failure':raise TimeoutError('MOCK fixture, no network')
        if fault=='invalid':return dict(text='MOCK malformed response',usage=None,metadata={'mock':True})
        n=0 if fault=='duplicate' else index
        expression='1 / 0' if fault=='invalid_evaluation' else f'{1 if n%2 else -1} * distance_current + {n/100!r} * distance_start'
        code='def priority('+', '.join(candidates.H_ARGS)+'):\n    return '+expression+'\n'
        return dict(text='{MOCK engineering fixed candidate; NOT a real LLM.}\n```python\n'+code+'```',
                    usage=dict(input_tokens=0,output_tokens=0),metadata={'mock':True,'model':'MOCK_NOT_LLM'})
