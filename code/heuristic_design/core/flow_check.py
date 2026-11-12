"""FJSP engineering flow adapter over the established executor and T30 collector.

No search, selection, holdout, hidden refill or run on import. Mac has two new
requests; cluster imports the exact Mac responses and makes no model request.
"""
from collections import Counter
from dataclasses import asdict, dataclass
import csv
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import platform
import socket
import time

from . import execution, lifecycle, routing_state_a as u, state_a
from .state_contracts import make_binding
from .storage import digest, read, sha, write
from heuristic_design.llm.legacy import ClientConfig, WireRecorder, DeadlineTransport
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport, StopAwareJournal, admit
from fjsp_usage.research.candidates import validate_code, parse_response, compile_candidate, CandidateError
from fjsp_usage.research_real.real_transport import WIRE_VERSION, failure_category

ROOT = Path(__file__).resolve().parents[3]
PLAN = ROOT/'deploy/flow-check/plan.json'
VERSION = 'fjsp-state-a-flow-20261112'
ROLES = ('fixed_H0', 'single_H_sample', 'state_A_U')


def directory(site):
    return (Path.home()/'hdl-flow-validation'/VERSION/site).resolve()


def preflight():
    p = read(PLAN)
    if sha(PLAN) != PLAN.with_suffix('.sha256').read_text().split()[0]:
        raise ValueError('flow plan changed')
    if (p['version'] != VERSION or p['new_api_cap'] != 2 or p['total_solve_cap'] != 12
            or p['state_spec'] != state_a.SPEC_SHA256 or p['state_abi'] != u.ABI
            or p['wire_version'] != WIRE_VERSION or p['automatic_retry'] is not False):
        raise ValueError('flow identity, state or budget differs')
    for name,value in {'endpoint':'https://leafapi.cc/v1/chat/completions','model':'gpt-6.1-sol',
        'expected_response_model':'gpt-6.1-sol','stream_response':False,
        'connect_timeout':10,'read_timeout':240,'total_timeout':300,'max_output_tokens':8192}.items():
        if p['provider'].get(name)!=value:raise ValueError('admitted provider setting differs: '+name)
    if platform.python_version() != '3.12.10':
        raise ValueError('Python3.12.10 required')
    for name, expected in p['files'].items():
        path = (ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or sha(path) != expected:
            raise ValueError('frozen flow file changed: '+name)
    import fjsp_usage.research_real.real_transport as wire
    if Path(wire.__file__).resolve() != ROOT/'code/fjsp_usage/research_real/real_transport.py':
        raise ValueError('wrong wire import')
    # These are the byte-identical admitted common client and strict caller.
    for name, expected in p['admitted_client'].items():
        if sha(ROOT/name) != expected:
            raise ValueError('admitted client differs')
    members = read(ROOT/p['members'])
    for row in members:
        if validate_code(row['code'], description=row['description'], kind='h').key != row['key']:
            raise ValueError('fixture H identity changed')
    from heuristic_design.problems.routing_fixtures import precheck_instances
    value = read(ROOT/p['instance'])
    instances = [{'file':'synthetic-fjsp-flow-development','split':'synthetic-development',
                  'value':value,'sha256':digest(value)}]
    refs = precheck_instances('fjsp', instances)  # structure + arithmetic LB only
    return p, members, instances, refs


@dataclass(frozen=True)
class Candidate:
    description: str
    code: str
    kind: str
    role: str
    code_key: str
    key: str


def candidate(row, role, p):
    kind = 'U' if role == 'state_A_U' else 'h'
    raw = (u.validate(row['code'], row['description'], len(p['members'])) if kind == 'U'
           else validate_code(row['code'], description=row['description'], kind='h'))
    hs = [raw.key] if role == 'single_H_sample' else [r['key'] for r in p['members']]
    bind = make_binding(problem_id='fjsp',state_schema=state_a.schema_id('fjsp'),
        policy_sha256=raw.key,h_order=hs,data_order=[r['sha256'] for r in p['instances']],
        reference_sha256=digest(p['references']),solve_seed=501,u_interface=u.ABI,
        action_schema='append-only-original-H-inputs',objective='relative-gap-min',
        normalization=state_a.SPEC_SHA256,tie_rule='first-original-action-max',
        evaluator_sha256=p['source_files']['code/heuristic_design/core/flow_check.py'])
    return Candidate(raw.description, raw.code, kind, role, raw.key,
                     digest({'role':role,'scientific_binding':bind}))


def prompt(role, members):
    if role == 'single_H_sample':
        return (ROOT/'deploy/api-common/prompts/fjsp_h.txt').read_text()
    return u.build_prompt('fjsp', {'operator':'INIT'}, [], members)


def _worker(pipe, payload, members, instances, names, allowed_modes):
    """Only a user-authorized run calls this function in an isolated child."""
    os.environ.pop('LEAFAPI_API_KEY', None)
    def deny(*args, **kwargs):
        raise PermissionError('evaluation worker networking forbidden')
    socket.socket.connect = deny
    socket.create_connection = deny
    try:
        from heuristic_design.problems.routing_fixtures import decode_instance
        from heuristic_design.problems.fjsp.routing import construct_state_a
        expected = payload['source_files']
        before = {n:sha(ROOT/n) for n in expected}
        if before != expected:
            raise RuntimeError('evaluation source mismatch')
        c = payload['candidate']
        if c['kind'] == 'U':
            parsed = u.validate(c['code'], c['description'], len(members))
        else:
            parsed = validate_code(c['code'],description=c['description'],kind='h')
        if parsed.key != c['code_key']:
            raise RuntimeError('candidate identity changed')
        hs = ([compile_candidate(parsed)] if c['role']=='single_H_sample' else
              [compile_candidate(validate_code(r['code'],description=r['description'],kind='h')) for r in members])
        for spec, name in zip(instances, names):
            obj = decode_instance('fjsp', spec)
            outputs = []
            reads = Counter()
            for pass_number in (1, 2):
                route = u.compile_candidate(parsed, len(hs), reads=reads) if c['kind']=='U' else lambda packet:0
                def checked_route(packet):
                    state_a.validate_packet(packet,len(hs))
                    return route(packet)
                result = construct_state_a(obj, hs, checked_route, trace=True)
                outputs.append({'raw_cost':result.schedule.makespan,'reference':result.reference,
                    'score':result.score,'score_direction':result.score_direction,
                    'solution':asdict(result.schedule),'trace':list(result.trace),
                    'member_sequence':list(result.member_sequence),'h_calls':list(result.h_calls)})
            if outputs[0] != outputs[1]:
                raise ValueError('full solve/recheck mismatch')
            after = {n:sha(ROOT/n) for n in expected}
            if after != before:
                raise RuntimeError('source changed during evaluation')
            pipe.send({'file':name,**outputs[0],'feasible':True,'captured_solves':2,
                'semantic_sha256':digest(outputs[0]),'recheck_semantic_sha256':digest(outputs[1]),
                'state_reads_both_passes':dict(reads),'source_before':digest(before),'source_after':digest(after)})
    except BaseException as error:
        pipe.send({'error_type':type(error).__name__,'error':str(error)[:500]})
    finally:
        pipe.close()


def validate_result(value, instances):
    if not value['valid']:
        if value['fitness'] is not None:
            raise ValueError('failed evaluation must not get fitness')
        return
    rows = value['instances']
    if [r['file'] for r in rows] != [i['file'] for i in instances]:
        raise ValueError('incomplete instance evaluation')
    for row,spec in zip(rows,instances):
        if (not row['feasible'] or row['captured_solves']!=2 or row['score_direction']!='min'
                or row['score']!=state_a.score_final_cost(row['raw_cost'],row['reference'])
                or row['semantic_sha256']!=row['recheck_semantic_sha256']
                or row['source_before']!=row['source_after']):
            raise ValueError('result, source or deterministic recheck differs')
        semantic={k:row[k] for k in ('raw_cost','reference','score','score_direction','solution','trace','member_sequence','h_calls')}
        if digest(semantic)!=row['semantic_sha256']:raise ValueError('semantic result hash changed')
        if len(row['trace'])!=sum(len(job) for job in spec['value']['jobs']):
            raise ValueError('incomplete construction trace')
        for record in row['trace']:
            state_a.validate_packet(record['state'],len(row['h_calls']))
        if row['member_sequence'] != [r['member_id'] for r in row['trace']]:
            raise ValueError('selected member trace missing')
    if value['fitness'] != -sum(r['score'] for r in rows)/len(rows):
        raise ValueError('explicit engineering utility must equal negative relative gap')


def evaluate(directory, state, p, c):
    if c.key in state['evaluations']:
        return read(directory/state['evaluations'][c.key]['path']), True
    if len(state['evaluations']) >= 3:
        raise ValueError('three evaluation reservations exhausted; no refill')
    folder = directory/'evaluations'/c.key
    folder.mkdir(parents=True,exist_ok=False)
    state['evaluations'][c.key]={'status':'reserved','role':c.role,'maximum_solve_passes':2}
    write(directory/'checkpoint.json',state)
    rows,failure,life = lifecycle.collect(mp.get_context('spawn'),_worker,
        {'candidate':asdict(c),'source_files':p['source_files']},p['members'],p['instances'],
        [r['file'] for r in p['instances']],30,(0,),lambda r:write(folder/'lifecycle.json',r))
    if life['alive'] or not life['receiver_thread_stopped']:
        raise RuntimeError('unknown worker termination; preserve reservation')
    if failure and failure.get('error_type') in ('RuntimeError','WorkerExit'):
        raise RuntimeError('evaluation infrastructure/source failure; preserve reservation: '+str(failure))
    if not failure and (life['exitcode']!=0 or life['cleanup']!=['join_exit_grace_2.0']):
        raise RuntimeError('worker normal exit uncertified')
    value={'valid':failure is None,'fitness':None if failure else -sum(r['score'] for r in rows)/len(rows),
           'instances':rows,'failure':failure,'lifecycle':life,'score_direction':'min',
           'failure_layer':None if not failure else 'evaluation_deadline' if failure.get('error_type')=='Timeout' else 'candidate_runtime',
           'utility_note':'fitness=-J only for established executor storage; no selection/search'}
    validate_result(value,p['instances'])
    write(folder/'result.json',value)
    state['evaluations'][c.key]={'status':'completed','path':str((folder/'result.json').relative_to(directory)),
                               'sha256':sha(folder/'result.json'),'maximum_solve_passes':2,'role':c.role}
    write(directory/'checkpoint.json',state)
    return value, False


class Journal(StopAwareJournal):
    def request(self,key,text,*,kind='U'):
        return super().request(key,text,kind='U' if key=='state_A_U' else 'h')


class Adapter:
    ROOT=ROOT
    entrypoint='tools/flow_check.py'
    CandidateError=CandidateError
    settle_known_api_stop=True
    read=staticmethod(read);write=staticmethod(write);sha=staticmethod(sha)
    validate_result=staticmethod(validate_result)
    evaluate=staticmethod(evaluate)

    def check_run(self,directory):
        plan,members,instances,refs=preflight()
        p=read(directory/'Protocol.json')
        if p['version']!=VERSION or p['flow_plan_sha256']!=sha(PLAN):
            raise ValueError('foreign flow protocol')
        if sha(directory/'Tasks.json')!=p['tasks_sha256']:
            raise ValueError('task plan changed')
        logical=2 if p['site']=='mac' else 0
        if (p['site'] not in ('mac','cluster') or p['members']!=members or p['instances']!=instances
                or p['references']!=refs or p['budgets']!={'logical_generation':logical,'max_program_instances':3}
                or p['config']['api_attempt_cap']!=logical or p['config']['per_candidate_attempt_cap']!=1
                or p['config']['window_seconds']!=3600 or p['config']['type']!='engineering_flow'
                or p['config']['provider']!=plan['provider']
                or p['config']['api_mode']!=('real' if logical else 'fixed')
                or p['config']['real_requests_authorized']!=(p['site']=='mac')):
            raise ValueError('frozen flow inputs or bounds differ')
        if p['site']=='cluster' and sha(directory/'Mac_export.json')!=p['Mac_export_sha256']:
            raise ValueError('original Mac export changed')
        if [r['id'] for r in read(directory/'Tasks.json')]!=list(ROLES):
            raise ValueError('flow task order differs')
        expected={**plan['files'],'deploy/flow-check/plan.json':sha(PLAN),
                  'deploy/flow-check/plan.sha256':sha(PLAN.with_suffix('.sha256'))}
        if p['source_files']!=expected:raise ValueError('source binding is incomplete or foreign')
        for name,h in p['source_files'].items():
            if sha(ROOT/name)!=h:raise ValueError('runtime changed: '+name)
        return p

    def members(self,directory):
        return self.check_run(directory)['members']

    def task_context(self,directory,state,p,task,index):
        if index==1 and not state.get('planned_pause_done'):
            if getattr(self,'resume_cursor',0)>=1:
                state.update(planned_pause_done=True,pause_exercise='explicit_resume_after_settled_baseline')
                state.setdefault('resume_checks',[]).append({'cursor':index,'clock_sha256':state['clock_sha256'],
                    'at':time.time(),'reason':'explicit user resume of known baseline prefix; no extra planned stop'})
            else:
                state.update(phase='paused',pause_reason='preplanned_baseline_boundary',planned_pause_done=True,
                             pause_exercise='preplanned_after_baseline')
                return None,None
        self.role=task['id'];self.protocol=p
        return task,[]

    def checked_candidate(self,row):
        c=candidate(row,row['role'],self.protocol)
        if asdict(c)!=row:raise ValueError('imported candidate/binding changed')
        return c

    def parse_candidate(self,text,config):
        raw=(u.parse(text,len(self.protocol['members'])) if self.role=='state_A_U'
             else parse_response(text,kind='h'))
        return candidate(asdict(raw),self.role,self.protocol)

    def build_prompt(self,config,task,parents,members):
        return prompt(task['id'],members)

    def client_config(self,p):
        return ClientConfig(p)

    def journal(self,directory,state,p,deadline):
        inner=StrictNonstreamTransport(self.client_config(p));inner.rejection_directory=directory/'caller_rejections'
        wire=WireRecorder(inner,directory/'wire_responses',verify=lambda:self.check_run(directory))
        return Journal(directory/'API_attempts.json',config=self.client_config(p),context=state['identity'],
                       phase='flow/'+state['identity'],transport=DeadlineTransport(wire,deadline))

    def commit_candidate(self,directory,state,p,record,c,result):
        if not record['valid']:
            write(directory/'Known_failure.json',{'task':record['id'],'failure':record.get('failure'),
                  'failure_layer':result.get('failure_layer') if result else record.get('failure'),
                  'details':result.get('failure') if result else None,
                  'cursor':state['cursor'],'settled':True,'automatic_retry':False})
            raise ValueError('flow failed at '+record['id']+'; no retry/refill/automatic continuation')

    def summary(self,directory,write_files=False):
        p=read(directory/'Protocol.json');s=read(directory/'checkpoint.json')
        j=read(directory/'API_attempts.json') if (directory/'API_attempts.json').exists() else {'api_attempts':{}}
        attempts=list(j['api_attempts'].values())
        out={'version':VERSION,'site':p['site'],'phase':s['phase'],'cursor':s['cursor'],
             'tasks':len(s['tasks']),'valid_tasks':sum(r.get('valid',False) for r in s['tasks'].values()),
             'api_reserved':len(attempts),'api_confirmed':sum(r.get('send_confirmed',False) or r.get('metadata',{}).get('send_status')=='confirmed' for r in attempts),
             'usage_unknown':sum(r.get('usage') is None for r in attempts),
             'known_input_tokens':sum((r.get('usage') or {}).get('input_tokens',0) for r in attempts),
             'known_output_tokens':sum((r.get('usage') or {}).get('output_tokens',0) for r in attempts),
             'evaluation_reserved':len(s['evaluations']),
             'maximum_reserved_solve_passes':2*len(s['evaluations']),
             'planned_pause_exercised':s.get('pause_exercise')=='preplanned_after_baseline',
             'checkpoint_pause_kind':s.get('pause_exercise'),
             'resume_receipts':len(s.get('resume_checks',[])),'actual_money_cost':None,
             'API_cap_this_site':2 if p['site']=='mac' else 0,'solve_cap_this_site':6}
        results=[read(directory/r['path']) for r in s['evaluations'].values() if r['status']=='completed']
        out['known_solve_passes']=sum(row['captured_solves'] for value in results for row in value['instances'])
        out['unknown_solve_usage_reservations']=sum(r['status']!='completed' for r in s['evaluations'].values())+sum(not r['valid'] for r in results)
        out['api_send_unknown']=sum(not r.get('send_confirmed',False) and r.get('metadata',{}).get('send_status') not in ('confirmed','not_started') for r in attempts)
        failures=Counter(failure_category(r.get('error',''),r.get('metadata',{})) for r in attempts if r['status']=='failed')
        for task in s['tasks'].values():
            if task.get('failure')=='parse_or_constraint_error':failures['candidate_parse_or_constraint']+=1
        for value in results:
            if not value['valid']:failures[value.get('failure_layer','evaluation_invalid')]+=1
        if out['unknown_solve_usage_reservations']:failures['unknown_or_incomplete_evaluation']=out['unknown_solve_usage_reservations']
        if any(r['status']=='pending' for r in attempts):failures['unknown_API_reservation']=sum(r['status']=='pending' for r in attempts)
        out['failure_counts_by_layer']=dict(failures)
        if write_files:write(directory/'Summary.json',out)
        return out


def accept_mac_export(path):
    value=read(path);p=value['protocol'];s=value['checkpoint']
    if (value['flow_plan_sha256']!=sha(PLAN) or p['site']!='mac' or s['phase']!='completed'
            or value['summary']['api_reserved']!=2 or value['summary']['api_confirmed']!=2
            or value['summary']['valid_tasks']!=3 or value['summary']['usage_unknown']!=0):
        raise ValueError('complete, fully accounted Mac flow export required')
    if value['protocol_sha256']!=digest(p) or value['checkpoint_sha256']!=digest(s):
        raise ValueError('Mac export protocol/checkpoint changed')
    if s['identity']!=sha_bytes(p) or s.get('clock_sha256')!=sha_bytes(value['run_clock']):
        raise ValueError('Mac original protocol/clock binding changed')
    if value['run_clock']['deadline']!=value['run_clock']['start']+3600:
        raise ValueError('Mac clock window changed')
    attempts=value['api_journal']['api_attempts']
    if len(attempts)!=2 or any(r['status']!='completed' for r in attempts.values()):
        raise ValueError('Mac has unknown or failed requests')
    requests=value['api_journal']['requests']
    if set(requests)!={'single_H_sample','state_A_U'}:raise ValueError('wrong Mac logical requests')
    for role,row in requests.items():
        if row['status']!='completed' or len(row['attempt_ids'])!=1:
            raise ValueError('non-single physical request')
        normalized={'text':row['text'],'usage':row['usage'],'metadata':row['response_metadata']}
        admit(normalized,p['config']['provider']['expected_response_model'])
        physical=attempts[row['attempt_ids'][0]]
        if physical.get('reply')!=normalized or physical.get('usage')!=row['usage'] or not physical.get('send_confirmed'):
            raise ValueError('Mac physical response/usage differs from logical receipt')
        parsed=u.parse(row['text'],len(p['members'])) if role=='state_A_U' else parse_response(row['text'],kind='h')
        if parsed.key!=s['tasks'][role]['candidate']['code_key']:
            raise ValueError('Mac candidate does not match actual response')
    for name,item in value['evaluations'].items():
        if sha_bytes(item)!=s['evaluations'][name]['sha256']:
            raise ValueError('Mac evaluation export changed')
        validate_result(item,p['instances'])
    if [s['tasks'][role]['id'] for role in ROLES]!=list(ROLES):
        raise ValueError('Mac tasks missing')
    for role in ROLES:
        c=s['tasks'][role]['candidate']
        if asdict(candidate(c,role,p))!=c:
            raise ValueError('Mac candidate changed')
    return value


def sha_bytes(value):
    import hashlib
    return hashlib.sha256((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()).hexdigest()


def prepare(site,*,allow_api=False,approve_api=None,allow_evaluation=False,approve_solves=None,mac_export=None):
    plan,members,instances,refs=preflight()
    if not allow_evaluation or approve_solves!=12:
        raise PermissionError('requires --allow-evaluation --approve-solves 12 (new total, both sites)')
    if site=='mac':
        if not allow_api or approve_api!=2:
            raise PermissionError('requires explicit NEW --allow-api --approve-api 2; old budget closed')
        secret=os.environ.get('LEAFAPI_API_KEY')
        if not secret or any(c.isspace() for c in secret):
            raise ValueError('credential missing; no flow claim or request reserved')
        if sys_platform()!='darwin':raise ValueError('Mac run requires Mac')
        previous=None
    else:
        if allow_api or approve_api is not None:raise PermissionError('cluster flow is replay, API flags forbidden')
        if not os.environ.get('SLURM_JOB_ID') or socket.gethostname()=='master':
            raise PermissionError('cluster evaluation requires a compute-node allocation')
        previous=accept_mac_export(mac_export)
    d=directory(site)
    if d.exists():raise FileExistsError('flow stage already exists; status/resume only, never reset')
    sources={**plan['files'],'deploy/flow-check/plan.json':sha(PLAN),
             'deploy/flow-check/plan.sha256':sha(PLAN.with_suffix('.sha256'))}
    config={'problem':'fjsp','type':'engineering_flow','api_mode':'real' if site=='mac' else 'fixed',
        'real_requests_authorized':site=='mac','provider':plan['provider'],'api_attempt_cap':2 if site=='mac' else 0,
        'per_candidate_attempt_cap':1,'candidate_kind':'h','window_seconds':3600,'search_seed':501,
        'solve_seed':501,'instance_timeout_seconds':30,'population_size':1}
    p={'version':VERSION,'site':site,'flow_plan_sha256':sha(PLAN),'config':config,
       'members':members,'instances':instances,'references':refs,'source_files':sources,
       'runtime':{'python':platform.python_version(),'platform':sys_platform(),'hostname':socket.gethostname(),
                  'slurm_job_id':os.environ.get('SLURM_JOB_ID'),'wire':WIRE_VERSION,
                  'transport_file':str(ROOT/'code/fjsp_usage/research_real/real_transport.py'),
                  'monotonic_implementation':time.get_clock_info('monotonic').implementation},
       'budgets':{'logical_generation':2 if site=='mac' else 0,'max_program_instances':3},
       'scope':'synthetic engineering, no search/quality claim; score J min; internal utility=-J',
       'Mac_export_sha256':sha(mac_export) if previous else None}
    tasks=[]
    for role in ROLES:
        if previous:
            row=previous['checkpoint']['tasks'][role]['candidate'];c=candidate(row,role,p)
        elif role=='fixed_H0':c=candidate(members[0],role,p)
        else:c=None
        tasks.append({'id':role,'stage':'import' if c else 'new',
                      'operator':'fixed_import' if role=='fixed_H0' else 'frozen_H_prompt_new_engineering_request' if role=='single_H_sample' else 'INIT_state_A',
                      'generation':None,
                      **({'candidate':asdict(c)} if c else {})})
    d.mkdir(parents=True,exist_ok=False)
    write(d/'Tasks.json',tasks);p['tasks_sha256']=sha(d/'Tasks.json');write(d/'Protocol.json',p)
    state={'identity':sha(d/'Protocol.json'),'phase':'prepared','cursor':0,'tasks':{},'evaluations':{},
           'seen':{},'population':[],'children':[],'generation':0,'pause_ack':0}
    write(d/'checkpoint.json',state)
    write(d/'Budget_approval.json',{'new_API_cumulative_cap':2,'new_solve_cumulative_cap':12,
          'explicit_allow_API':allow_api,'explicit_allow_evaluation':allow_evaluation,
          'old_diagnostic_budget_inherited':False,'site':site,'at':time.time()})
    if previous:write(d/'Mac_export.json',previous)
    return d


def sys_platform():
    import sys
    return sys.platform


def run(site,*,resume=False,allow_api=False,approve_api=None,allow_evaluation=False,approve_solves=None,mac_export=None):
    if site=='cluster' and (not os.environ.get('SLURM_JOB_ID') or socket.gethostname()=='master'):
        raise PermissionError('cluster run/resume requires compute-node allocation')
    if resume:
        preflight();d=directory(site);p=Adapter().check_run(d)
        if not allow_evaluation or approve_solves!=12:raise PermissionError('resume acknowledges ORIGINAL solve cap12')
        if site=='mac' and (not allow_api or approve_api!=2):raise PermissionError('resume acknowledges ORIGINAL API cap2')
        if site=='cluster' and (allow_api or approve_api is not None):raise PermissionError('replay never requests API')
        # Existing coordinator validates settled prefixes/clock/Stop/locks; no refill.
    else:
        d=prepare(site,allow_api=allow_api,approve_api=approve_api,
          allow_evaluation=allow_evaluation,approve_solves=approve_solves,mac_export=mac_export)
    adapter=Adapter()
    if resume:adapter.resume_cursor=read(d/'checkpoint.json')['cursor']
    result=execution.start(d,adapter=adapter,resume=resume,allow_api=allow_api)
    s=read(d/'checkpoint.json')
    if (result['phase']=='paused' and s.get('pause_reason')=='preplanned_baseline_boundary' and not s.get('resume_checks')
            and s['cursor']==1 and s['tasks']['fixed_H0']['valid'] and not (d/'Clock_quarantine.json').exists()
            and not (d/'Stop.json').exists() and execution.pause_sequence(d,adapter=adapter)==s['pause_ack']):
        p=adapter.check_run(d);execution.ledger(d,s,p,adapter=adapter)
        s.setdefault('resume_checks',[]).append({'cursor':1,'clock_sha256':s['clock_sha256'],
            'remaining_API_slots':2 if site=='mac' else 0,'at':time.time(),
            'reason':'explicit plan: one settled baseline pause/resume, never retry failure'})
        s['pause_reason']=None;write(d/'checkpoint.json',s)
        result=execution.start(d,adapter=adapter,resume=True,allow_api=allow_api)
    export(site)
    return result


def export(site):
    d=directory(site);p=read(d/'Protocol.json');s=read(d/'checkpoint.json')
    evaluations={key:read(d/row['path']) for key,row in s['evaluations'].items() if row['status']=='completed'}
    value={'flow_plan_sha256':sha(PLAN),'protocol':p,'protocol_sha256':digest(p),
       'checkpoint':s,'checkpoint_sha256':digest(s),'summary':Adapter().summary(d),
       'evaluations':evaluations,'api_journal':read(d/'API_attempts.json') if (d/'API_attempts.json').exists() else {'api_attempts':{}},
       'solves_are_engineering_not_formal_evaluation':True,'actual_money_cost':None}
    value['run_clock']=read(d/'Run_clock.json') if (d/'Run_clock.json').exists() else None
    value['wire_responses']={f.name:read(f) for f in (d/'wire_responses').glob('*.json')}
    value['worker_receipts']={str(f.relative_to(d)):read(f) for f in (d/'evaluations').glob('*/lifecycle.json')}
    if site=='cluster':
        previous=read(d/'Mac_export.json')
        value['cross_platform']={}
        for role in ROLES:
            left=previous['checkpoint']['tasks'].get(role,{});right=s['tasks'].get(role,{})
            le=previous['evaluations'].get(left.get('evaluation_key'));re=evaluations.get(right.get('evaluation_key'))
            value['cross_platform'][role]=bool(le and re and le['valid'] and re['valid'] and
                [r['semantic_sha256'] for r in le['instances']]==[r['semantic_sha256'] for r in re['instances']])
        value['cross_platform_passed']=all(value['cross_platform'].values())
    write(d/'export.json',value)
    with (d/'results.csv').open('w') as f:
        writer=csv.writer(f);writer.writerow(['role','valid','raw_cost','reference_LB','J_min','captured_solves'])
        for role,row in s['tasks'].items():
            result=evaluations.get(row.get('evaluation_key'))
            if result and result['valid']:
                r=result['instances'][0];writer.writerow([role,True,r['raw_cost'],r['reference'],r['score'],r['captured_solves']])
            else:writer.writerow([role,False,None,None,None,None])
    return d/'export.json'
