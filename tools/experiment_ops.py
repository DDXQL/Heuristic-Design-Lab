"""Thin configurable operations adapter over existing H/U/API/T30 components.

Not a replacement for frozen campaign controllers or Tier1 workflows.
"""
import argparse
from dataclasses import asdict
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys

from tools import cross_feedback_ab_execute as certified
from tools import h01_weight_search as h01
from tools import h01_progress_baseline as rules
from fjsp_usage.research.events import atomic_json as write
from fjsp_usage.research.protocol import digest
from fjsp_usage.research.candidates import U_ARGS,validate_code
from fjsp_usage.research_real.assets import check_seal,checked_candidate
from fjsp_usage.research_real.config import ProviderConfig
from fjsp_usage.usage_v2 import VERSION as INTERFACE

ROOT=Path(__file__).resolve().parents[1]
VERSION='experiment-operations-v1'
TYPES={'fixed':'固定U/静态策略；h01或10H', 'rules':'既有H01进度规则族的参数子集',
       'pair':'两份固定U配对；h01或10H', 'ind':'独立I1；h01或10H',
       'evo':'既定P0→CROSS/MUTATE→代末保留；h01或10H',
       'cross_ab':'历史自由P0的双父代CROSS成绩反馈A/B；仅10H、原train21'}
API_TYPES={'ind','evo','cross_ab'}
read=certified.read;sha=certified.sha


def local_path(value):
    p=Path(value);p=(p if p.is_absolute() else ROOT/p).resolve()
    if not p.is_relative_to(ROOT):raise ValueError('configuration inputs must be inside this worktree')
    return p


def integer(value,label,minimum=1):
    if type(value) is not int or value<minimum:raise ValueError(label+' must be an integer >= '+str(minimum))
    return value


def candidate(spec,space):
    if 'code_file' in spec:
        code=local_path(spec['code_file']).read_text()
    elif 'alpha' in spec:
        a=spec['alpha']
        if type(a) not in (int,float) or not math.isfinite(a) or not 0<=a<=1:raise ValueError('alpha in [0,1]')
        code='def use_heuristics('+', '.join(U_ARGS)+'):\n    return (1, ('+', '.join(map(repr,[float(a),1-float(a)]+[0.]*8))+'))\n'
    elif 'member' in spec:
        i=integer(spec['member'],'member',0)
        if i>9:raise ValueError('member 0..9')
        code='def use_heuristics('+', '.join(U_ARGS)+'):\n    return (0, ('+', '.join('1' if j==i else '0' for j in range(10))+'))\n'
    else:raise ValueError('strategy requires code_file, alpha, or member')
    c=validate_code(code,description=spec.get('id','configured strategy'),kind='U',interface_version=INTERFACE,member_count=10)
    if space=='h01':c=h01.validate(c.code,c.description)
    return asdict(c)


def load_config(path):
    raw=read(local_path(path));c=dict(raw)
    fields={'schema','question','type','space','H_source','dataset','strategies','rule_filter','p0',
        'candidates','population_size','generations','cross_per_generation','mutate_per_generation','cross_parents',
        'search_seed','solve_seed','instance_timeout','window_seconds','api_mode','real_requests_authorized',
        'provider','api_attempt_cap','per_candidate_attempt_cap','prompt_overrides','parent_pairs','repeats','mock_delay_seconds'}
    if set(c)-fields:raise ValueError('unknown configuration fields: '+str(sorted(set(c)-fields)))
    if c.get('schema')!=VERSION or c.get('type') not in TYPES or c.get('space') not in ('h01','ten_h'):
        raise ValueError('unsupported schema/type/space')
    defaults={'question':'工程运行','search_seed':17,'solve_seed':501,'instance_timeout':30,'window_seconds':3600,
        'api_mode':'disabled','real_requests_authorized':False,'population_size':5,'generations':1,
        'cross_per_generation':1,'mutate_per_generation':1,'cross_parents':5,'candidates':2,'p0':[],
        'per_candidate_attempt_cap':2,'api_attempt_cap':3,'prompt_overrides':{},'repeats':1,'mock_delay_seconds':0}
    c={**defaults,**c}
    if c['instance_timeout']!=30 or c['solve_seed']!=501:raise ValueError('adapter preserves certified T30/seed501; new scientific protocol required to change')
    integer(c['window_seconds'],'window_seconds')
    if c['window_seconds']>43200:raise ValueError('window maximum is 12 hours')
    integer(c['search_seed'],'search_seed',0)
    if c['api_mode'] not in ('disabled','mock','real'):raise ValueError('api_mode: disabled/mock/real')
    if type(c['real_requests_authorized']) is not bool:raise ValueError('real_requests_authorized must be boolean')
    if c['type'] in API_TYPES:
        if c['api_mode']=='disabled':raise ValueError('generation type requires mock or real api_mode')
        c['provider']=asdict(ProviderConfig(**c['provider']))
        integer(c['api_attempt_cap'],'api_attempt_cap');integer(c['per_candidate_attempt_cap'],'retry cap')
        if c['per_candidate_attempt_cap']>2:raise ValueError('at most two attempts per logical candidate')
    elif c['api_mode']!='disabled':raise ValueError('local evaluation has no API mode')
    if c['mock_delay_seconds'] and (c['api_mode']!='mock' or not 0<c['mock_delay_seconds']<=2):raise ValueError('bounded delay is mock-only')
    if set(c['prompt_overrides'])-{'I1','CROSS','MUTATE'}:raise ValueError('unknown prompt override operation')
    for op,path in c['prompt_overrides'].items():c['prompt_overrides'][op]=str(local_path(path))
    if c['type']=='cross_ab' and (c['space']!='ten_h' or c['prompt_overrides']):raise ValueError('CROSS A/B uses unchanged 10H templates; no overrides')
    if c['type']=='evo':
        for k in ('population_size','generations','cross_per_generation','mutate_per_generation','cross_parents'):integer(c[k],k)
        if not 2<=c['cross_parents']<=min(c['population_size'],5):raise ValueError('2 <= CROSS parents <= min(N,5)')
        if c['space']=='h01' and (c['population_size']!=5 or c['cross_parents']!=5):raise ValueError('original H01 CROSS requires N=5 and five parents')
    return c


def describe(config_path):
    c=load_config(config_path);hpath=local_path(c['H_source']);h=check_seal(read(hpath),kind='H_frozen',mode='real')
    members=[checked_candidate(r['candidate'],'h') for r in h['members']]
    if len(members)!=10 or [r['member_id'] for r in h['members']]!=list(range(10)):raise ValueError('ordered reviewed H0..H9 required')
    inputs={str(local_path(config_path)):sha(local_path(config_path)),str(hpath):sha(hpath)}
    ds=c['dataset']
    if set(ds)-{'files','protocol','role'} or ds.get('role') not in ('engineering','train','confirmation'):
        raise ValueError('dataset requires explicit role and files OR protocol')
    if c['type'] in API_TYPES and ds['role']=='confirmation':raise ValueError('confirmation data cannot guide generation/search')
    if ('files' in ds)==('protocol' in ds):raise ValueError('use dataset.files OR dataset.protocol')
    if 'protocol' in ds:
        origin=local_path(ds['protocol']);inputs[str(origin)]=sha(origin)
        specs=read(origin)['instances'];paths=[origin.parent/r['relative_path'] for r in specs]
    else:specs=None;paths=[local_path(p) for p in ds['files']]
    if not paths or len({p.name for p in paths})!=len(paths):raise ValueError('nonempty, unique instance filenames required')
    instances=[]
    for i,path in enumerate(paths):
        path=local_path(str(path));v=certified.s.v2.load_instance(path);lb=certified.s.v2.lower_bound_v5(v)
        if specs is not None and (sha(path)!=specs[i]['sha256'] or lb!=specs[i]['LB']):raise ValueError('dataset source identity/LB mismatch')
        inputs[str(path)]=sha(path)
        instances.append({'file':path.name,'source':str(path),'sha256':sha(path),'LB':lb,'operations':v.operation_count})
    manual=[];parents=[];plan=[]
    if c['type'] in ('fixed','pair'):
        for spec in c.get('strategies',[]):
            manual.append({'id':spec['id'],'candidate':candidate(spec,c['space'])})
            if 'code_file' in spec:inputs[str(local_path(spec['code_file']))]=sha(local_path(spec['code_file']))
        if not manual or c['type']=='pair' and len(manual)!=2:raise ValueError('fixed needs strategies; pair needs exactly two')
    elif c['type']=='rules':
        if c['space']!='h01':raise ValueError('existing rules are H01 only')
        filters=c.get('rule_filter',{})
        if set(filters)-{'tau','alpha_before','alpha_after'}:raise ValueError('unknown rule filter')
        allowed={'tau':[.25,.5,.75],'alpha_before':[0,.5,1],'alpha_after':[0,.5,1]}
        for k,v in filters.items():
            if not v or any(x not in allowed[k] for x in v):raise ValueError('only subsets of existing rule family: '+str(allowed))
        manual=[{'id':r['id'],'candidate':r['candidate']} for r in rules.rules()
                if all((r['tau'] is None and k=='tau') or r[k] in v for k,v in filters.items())]
    elif c['type']=='cross_ab':
        from tools.cross_feedback_ab import parents_audit
        parents,source_h,science,pins,_=parents_audit()
        if [m.key for m in members]!=science['H_order'] or len(instances)!=len(science['instances']):raise ValueError('parent H/full train21 context mismatch')
        for a,b in zip(instances,science['instances']):
            if (a['file'],a['sha256'],a['LB'])!=(b['file'],b['sha256'],b['LB']):raise ValueError('parent data/LB context mismatch; no parent re-evaluation')
        inputs.update({str(ROOT/k):v for k,v in pins.items()})
        byid={r['id']:r for r in parents}
        integer(c['repeats'],'repeats')
        for i,pair in enumerate(c['parent_pairs']):
            if len(pair)!=2 or len(set(pair))!=2 or any(k not in byid for k in pair):raise ValueError('invalid explicit parent pair')
            for repeat in range(c['repeats']):
                for condition in (('A','B') if repeat%2==0 else ('B','A')):
                    plan.append({'id':f'pair{i:02d}_{repeat:02d}_{condition}','stage':'new','operator':'CROSS','condition':condition,'pair_index':i,'repeat':repeat,'parents':pair})
    else:
        for spec in c['p0']:
            manual.append({'id':spec['id'],'candidate':candidate(spec,c['space'])})
            if 'code_file' in spec:inputs[str(local_path(spec['code_file']))]=sha(local_path(spec['code_file']))
    if len({r['id'] for r in manual})!=len(manual):raise ValueError('unique strategy/P0 ids required')
    if c['type']=='evo' and (len(manual)!=c['population_size'] or len({r['candidate']['key'] for r in manual})!=len(manual)):
        raise ValueError('EVO requires exactly N distinct configured P0 codes; no implicit new initialization')
    if c['type']!='cross_ab':
        plan=[{'id':r['id'],'stage':'p0' if c['type'] in API_TYPES else 'fixed','candidate':r['candidate']} for r in manual]
        if c['type']=='ind':
            integer(c['candidates'],'candidates')
            plan += [{'id':f'IND/{i:06d}','stage':'new','operator':'I1'} for i in range(c['candidates'])]
        if c['type']=='evo':
            for g in range(c['generations']):
                for op,count in [('CROSS',c['cross_per_generation']),('MUTATE',c['mutate_per_generation'])]:
                    for i in range(count):plan.append({'id':f'EVO/g{g:04d}/{op}/{i:04d}','stage':'new','operator':op,'generation':g})
    api=sum(r['stage']=='new' for r in plan)
    if c['type'] in API_TYPES and not api:raise ValueError('generation plan must contain candidates')
    if api and not api<=c['api_attempt_cap']<=api*c['per_candidate_attempt_cap']:raise ValueError('API cap must cover logical candidates and not exceed retry limit')
    if c['mock_delay_seconds'] and ds['role']!='engineering':raise ValueError('mock delay only on engineering data')
    for path in c['prompt_overrides'].values():inputs[path]=sha(path)
    return {'config':c,'instances':instances,'H':h,'parents':parents,'tasks':plan,'inputs':inputs,
            'budgets':{'logical_generation':api,'manual_or_P0_evaluations':len(manual),'API_attempts':c['api_attempt_cap'] if api else 0,
                       'max_program_instances':len(plan)*len(instances),'max_solve_passes':2*len(plan)*len(instances)}}


def sources():
    s=certified.s;b=s.b;v4=b.old;v3=v4.v3;v2=v3.v2
    names=set(v2.MODULES+v3.NEW_MODULES+v4.MODULES+b.MODULES+s.MODULES)
    names.update(['tools.cross_feedback_ab_execute','tools.h01_weight_search','tools.h01_progress_baseline','tools.ind_evo_h01',
        'tools.b1_usage_prompts','tools.experiment_ops','tools.experiment_ops_run','tools.experiment_ops_prompts',
        'fjsp_usage.cross_feedback_ab','tools.cross_feedback_ab','fjsp_usage.usage_v2',
        'fjsp_usage.research_real.config','fjsp_usage.research_real.prompts',
        'fjsp_usage.usage_v2.prompts','fjsp_usage.usage_v2.candidates','fjsp_usage.research.prompts',
        'fjsp_usage.research.evolution','fjsp_usage.research.sets','fjsp_usage.research_real.attempt_budget',
        'fjsp_usage.research_real.budget','fjsp_usage.research_real.real_transport','fjsp_usage.usage_v2.access',
        'heuristic_design.core.execution','heuristic_design.core.search',
        'heuristic_design.llm.legacy','heuristic_design.problems.fjsp.adapter'])
    return {str(Path(importlib.import_module(n).__file__).resolve().relative_to(ROOT)):sha(Path(importlib.import_module(n).__file__)) for n in sorted(names)}


def prepare(config_path,directory):
    directory=local_path(directory)
    if directory.parent!=ROOT/'runs' or directory.exists():raise ValueError('prepare requires a NEW direct runs child; never overwrite')
    d=describe(config_path);directory.mkdir();(directory/'inputs').mkdir();(directory/'templates').mkdir()
    for r in d['instances']:
        target=directory/'inputs'/r['file'];target.write_bytes(Path(r['source']).read_bytes());r['relative_path']=str(target.relative_to(directory))
    write(directory/'Resolved_config.json',d['config']);write(directory/'Tasks.json',d['tasks'])
    write(directory/'H_frozen.json',d['H']);write(directory/'Parents.json',d['parents'])
    from tools.experiment_ops_prompts import build
    members=[checked_candidate(r['candidate'],'h') for r in d['H']['members']]
    examples=[]
    if d['config']['type'] in API_TYPES:
        p0=d['parents'] or [r for r in d['tasks'] if r['stage']=='p0']
        for op in (('I1',) if d['config']['type']=='ind' else ('CROSS','MUTATE') if d['config']['type']=='evo' else ('CROSS',)):
            parents=[] if op=='I1' else p0[:1] if op=='MUTATE' else ([next(r for r in p0 if r['id']==pid) for pid in d['config']['parent_pairs'][0]] if d['config']['type']=='cross_ab' else p0[:d['config']['cross_parents']])
            # B preview must carry the original authenticated parent scores.
            for cond in (('A','B') if d['config']['type']=='cross_ab' else ('A',)):
                text=build(d['config'],{'operator':op,'condition':cond},parents,members)
                path=directory/'templates'/(op+'_'+cond+'.txt');path.write_text(text);examples.append(path)
    locked={**d['inputs'],**{str(p):sha(p) for p in directory.rglob('*') if p.is_file()}}
    p={'version':VERSION,'config':d['config'],'instances':d['instances'],'budgets':d['budgets'],
       'source_files':sources(),'protected_files':{str(Path(k).relative_to(ROOT)):v for k,v in locked.items()},
       'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
       'python':platform.python_version(),'interface':INTERFACE,'score':'complete mean(-Cmax/unrounded V5 LB)',
       'timeout':'T30 complete row receive; solve+recheck; separate 2s exit grace',
       'cache':'same canonical U key + frozen context, this run only; all logical slots count; P0 costs separate',
       'history_resume':'new adapter only; never reinterprets old campaigns; unknown reservations lock and Stop persist'}
    if d['budgets']['logical_generation']:
        from tools.experiment_ops_run import ClientConfig
        p['transport_config']=ClientConfig(p).payload()
    write(directory/'Protocol.json',p);(directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    write(directory/'Solver_identity.json',certified.witness(p))
    write(directory/'Controller_identity.json',certified.attest_module('tools.experiment_ops_run',p))
    write(directory/'checkpoint.json',{'identity':sha(directory/'Protocol.json'),'phase':'prepared','cursor':0,'tasks':{},'evaluations':{},
        'population':[],'children':[],'seen':{},'generation':0,'pause_ack':0})
    return {'run_dir':str(directory),'budgets':d['budgets'],'API_calls':0,'solves':0}


def check_run(directory):
    p=read(directory/'Protocol.json')
    if p.get('version')!=VERSION:raise ValueError('historical campaign: status/summary only; use its own controller')
    if sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip():raise ValueError('protocol identity mismatch')
    for k,v in {**p['source_files'],**p['protected_files']}.items():
        if sha(ROOT/k)!=v:raise ValueError('changed config/source/template/data; use a new run: '+k)
    if p['config']!=read(directory/'Resolved_config.json'):raise ValueError('resolved config changed')
    if certified.witness(p)['identity']!=read(directory/'Solver_identity.json')['identity']:raise ValueError('loaded solver identity mismatch')
    if certified.attest_module('tools.experiment_ops_run',p)!=read(directory/'Controller_identity.json'):raise ValueError('loaded controller identity mismatch')
    return p


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('doctor',help='local environment only; no network')
    commands.add_parser('types',help='list supported types and example configs')
    for name in ('check','plan','prepare'):
        q=commands.add_parser(name);q.add_argument('--config',required=True)
        if name=='prepare':q.add_argument('--run-dir',required=True)
    for name in ('run','resume','status','stop','summary','_work'):
        q=commands.add_parser(name);q.add_argument('--run-dir',required=True)
        if name in ('run','resume'):q.add_argument('--allow-api',action='store_true');q.add_argument('--background',action='store_true')
        if name=='summary':q.add_argument('--write',action='store_true',help='write new adapter results only; historical summaries always readonly')
    a=parser.parse_args()
    try:
        if a.command=='doctor':
            result={'python':platform.python_version(),'executable':sys.executable,'worktree':str(ROOT),
                'dependencies':{n:importlib.metadata.version(n) for n in ('numpy','pytz','tqdm')},
                'LEAFAPI_API_KEY_present':bool(os.environ.get('LEAFAPI_API_KEY')),'network_queries':0,'solves':0}
        elif a.command=='types':result={'types':TYPES,'examples':sorted(str(p.relative_to(ROOT)) for p in (ROOT/'experiments/tier2/ops/configs').glob('*.json'))}
        elif a.command in ('check','plan'):
            d=describe(a.config);result={'valid':True,'type':d['config']['type'],'space':d['config']['space'],
                'budgets':d['budgets'],'instances':[r['file'] for r in d['instances']],'API_calls':0,'solves':0}
            if a.command=='plan':result['tasks']=[{k:v for k,v in r.items() if k!='candidate'} for r in d['tasks']]
        elif a.command=='prepare':result=prepare(a.config,a.run_dir)
        else:
            directory=local_path(a.run_dir)
            if a.command in ('status','summary'):
                from tools.experiment_ops_report import status,summary
                result=status(directory) if a.command=='status' else summary(directory,write_files=a.write)
            else:
                from tools.experiment_ops_run import start,work,stop
                result=stop(directory) if a.command=='stop' else work(directory) if a.command=='_work' else start(directory,resume=a.command=='resume',allow_api=a.allow_api,background=a.background)
        if result is not None:
            print(json.dumps(result,ensure_ascii=False,indent=2))
            if a.command in ('run','resume','_work') and result.get('phase') in ('stopped','expired'):raise SystemExit(2)
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__,'error':str(exc),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
