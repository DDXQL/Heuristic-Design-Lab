"""Fixed 50-task/75-attempt TSP campaign, train-only search and frozen holdout."""
from dataclasses import asdict
import csv
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from heuristic_design.core import execution
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.core.search import ranked
from . import candidates,data,prompts
from .solver import distances,nearest_neighbor
from .operations import Adapter,ROOT

VERSION='tsp-fixed-pilot-v1-20261026'
DEFAULT=ROOT/'runs/tsp-pilot-20261026-v1'


def sources():
    paths=set((ROOT/'code/heuristic_design').rglob('*.py'))
    for folder in ['research','research_real']:
        paths.update((ROOT/'code/fjsp_usage'/folder).glob('*.py'))
    paths.update([ROOT/'code/fjsp_usage/usage_v2/access.py',ROOT/'experiments/tsp/manage.py'])
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}


def freeze(directory,name,value):
    target=directory/name
    if target.exists():raise ValueError('frozen artifact already exists')
    write(target,value)
    write(directory/'Frozen_artifacts'/(name+'.receipt.json'),{'file':name,'sha256':sha(target),'protocol':sha(directory/'Protocol.json')})


def load_config(path):
    c=read(path)
    if set(c)!={'schema','api_mode','real_requests_authorized','provider','window_seconds','api_attempt_cap','per_candidate_attempt_cap','mock_delay_seconds'}:raise ValueError('exact campaign config fields required')
    if c['schema']!=VERSION or c['api_mode'] not in ('real','mock') or type(c['real_requests_authorized']) is not bool:raise ValueError('campaign schema/mode')
    if c['window_seconds']!=43200 or c['api_attempt_cap']!=75 or c['per_candidate_attempt_cap']!=2 or c['mock_delay_seconds']!=0:raise ValueError('fixed window and budgets')
    from heuristic_design.llm.legacy import ClientConfig
    ClientConfig({'config':c,'budgets':{'logical_generation':50}})
    return c


def prepare(config,directory,continue_from=None,renew_window_seconds=None,window_authorization=None):
    directory=Path(directory).resolve()
    if directory.parent!=ROOT/'runs' or directory.exists():raise ValueError('new direct runs child required')
    c=load_config(config)
    if renew_window_seconds is not None:
        if continue_from is None or type(renew_window_seconds) is not int or not 1<=renew_window_seconds<=43200 or not window_authorization:
            raise ValueError('renewal requires continuation, explicit authorization and <=12 hours')
        authority=read(window_authorization)
        if authority.get('user_text')!='允许新窗口，预算不变' or authority.get('logical_cap')!=50 or authority.get('API_attempt_cap')!=75:
            raise ValueError('window authorization must preserve original total budget')
    directory.mkdir(parents=True)
    if continue_from is None:manifest=data.generate(directory/'data')
    else:
        import shutil
        origin=Path(continue_from).resolve();old=read(origin/'Protocol.json');journal=read(origin/'API_attempts.json')
        if sha(origin/'Protocol.json')!=(origin/'Protocol.sha256').read_text().strip():raise ValueError('origin protocol changed')
        if any(a['status'] not in ('completed','failed') for a in journal['api_attempts'].values()):raise ValueError('unknown request; no continuation replay')
        if (origin/'.campaign.lock').exists():raise ValueError('origin still has writer lock')
        for run in (ROOT/'runs').glob(origin.name+'--*'):
            if (run/'.execution.lock').exists():raise ValueError('origin stage lock present')
        if old['config']!=c:raise ValueError('continuation cannot alter provider, budget or parameters')
        shutil.copytree(origin/'data',directory/'data');manifest=old['data']
        if renew_window_seconds is None:(directory/'Run_clock.json').write_bytes((origin/'Run_clock.json').read_bytes())
        else:(directory/'Original_clock.json').write_bytes((origin/'Run_clock.json').read_bytes())
        write(directory/'Inherited_budget.json',{'origin':str(origin),'requests':journal['requests'],'api_attempts':journal['api_attempts'],'no_reset':True})
    p={'version':VERSION,'config':c,'source_files':sources(),'config_file':str(Path(config).resolve()),'config_sha256':sha(config),
        'data_manifest_sha256':sha(directory/'data/Manifest.json'),'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'data':manifest,'budgets':{'logical_cap':50,'API_attempt_cap':75,'per_candidate_attempt_cap':2,'H':10,'IND_701':10,'IND_702':10,'EVO_801':10,'EVO_802':10},
        'science_protocol_sha256':sha(ROOT/'docs/TSP_PILOT_PROTOCOL_V1.md'),
        'H_selection':'canonical AST first occurrence, manual before generated; valid train Fitness desc/id asc, top min(5, valid)',
        'P0':'all singles and all equal pairs; AST distinct; train Fitness desc/id asc, top min(5,valid)',
        'EVO':'one generation 5 CROSS +5 MUTATE; two rank-weighted parents/one mutation parent; frozen generation; top N at end',
        'seeds':{'IND':[701,702],'EVO':[801,802]},'score':'-mean(length/NN_length), complete declared set',
        'deadline':'30 seconds shared solve/recheck complete row, separate 2 second exit grace',
        'failure':'any failed instance => null complete Fitness; no refill; first complete response only',
        'validation':'dedup 4 path train champions plus train-static reference; Fitness desc/id asc; one pass',
        'confirmation_transfer':'only frozen final U and train-static reference; no return to tuning',
        'cost':'no fee gate; unknown usage/points/currency null; static and P0 costs separate',
        'resume':'one global journal, no count resets; unknown reservations stop; new source/config requires explicit evidence preservation'}
    if continue_from is not None:
        p['request_origin']={'directory':str(origin),'protocol_sha256':sha(origin/'Protocol.json'),'clock_sha256':sha(origin/'Run_clock.json')}
        p['execution_revision']={'version':'description-wrapper-compatible-v2','change':'accept plain or braced description; unchanged candidate code/AST/geometry/prompt/selection','inherited_logical':len(journal['requests']),'inherited_attempts':len(journal['api_attempts']),'no_extra_budget':True,'origin_H_selection_superseded_before_any_U':not any(k.startswith(('IND_','EVO_')) for k in journal['requests'])}
    if renew_window_seconds is not None:
        p['window_renewal']={'seconds':renew_window_seconds,'authorization':authority,'from':'first start of this continuation','original_clock_sha256':sha(directory/'Original_clock.json'),'budget_reset':False}
    write(directory/'Protocol.json',p);(directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    write(directory/'Campaign_state.json',{'phase':'prepared','current_stage':None,'completed_stages':[],'started_at':None})
    (directory/'wire_responses').mkdir()
    write(directory/'Authorization.json',{'source':'2026-10-26 current user full TSP protocol','real_API_authorized':c['real_requests_authorized'],'caps':p['budgets'],'no_push':True,'no_extra_budget':True})
    (directory/'prompts').mkdir()
    (directory/'prompts/H_I1.txt').write_text(prompts.build({'candidate_kind':'h'},{'operator':'I1'},[],[]))
    return {'directory':str(directory),'prepared':True,'API_calls':0,'solves':0,'budget':p['budgets']}


def check(directory):
    p=read(directory/'Protocol.json')
    if p['version']!=VERSION or sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip():raise ValueError('campaign identity changed')
    if sha(p['config_file'])!=p['config_sha256'] or sha(ROOT/'docs/TSP_PILOT_PROTOCOL_V1.md')!=p['science_protocol_sha256']:raise ValueError('bound config/science protocol changed')
    for name,value in p['source_files'].items():
        if sha(ROOT/name)!=value:raise ValueError('bound source changed: '+name)
    if sha(directory/'data/Manifest.json')!=p['data_manifest_sha256']:raise ValueError('data manifest changed')
    for rows in p['data'].values():
        for row in rows:
            if sha(directory/'data'/row['path'])!=row['sha256']:raise ValueError('data changed')
    if 'request_origin' in p:
        origin=Path(p['request_origin']['directory'])
        if sha(origin/'Protocol.json')!=p['request_origin']['protocol_sha256'] or sha(origin/'Run_clock.json')!=p['request_origin']['clock_sha256']:raise ValueError('origin identity/deadline changed')
        if 'window_renewal' in p:
            if sha(directory/'Original_clock.json')!=p['window_renewal']['original_clock_sha256']:raise ValueError('original clock copy changed')
            if (directory/'Run_clock.json').exists():
                clock=read(directory/'Run_clock.json');receipt=read(directory/'Window_renewal_receipt.json')
                if receipt['clock_sha256']!=sha(directory/'Run_clock.json') or receipt['protocol']!=sha(directory/'Protocol.json') or clock['deadline']!=clock['start']+p['window_renewal']['seconds']:raise ValueError('renewed clock changed')
        elif sha(directory/'Run_clock.json')!=p['request_origin']['clock_sha256']:raise ValueError('original deadline changed')
        inherited=read(directory/'Inherited_budget.json');current=read(origin/'API_attempts.json')
        if any(current['requests'].get(k)!=v for k,v in inherited['requests'].items()) or any(current['api_attempts'].get(k)!=v for k,v in inherited['api_attempts'].items()):raise ValueError('inherited request or attempt record changed')
    for name in ['H_frozen.json','P0.json','Validation_candidates.json','Final_frozen.json']:
        if (directory/name).exists():
            receipt=read(directory/'Frozen_artifacts'/(name+'.receipt.json'))
            if receipt['sha256']!=sha(directory/name) or receipt['protocol']!=sha(directory/'Protocol.json'):raise ValueError('frozen artifact changed: '+name)
    return p


def nn_instances(directory,split):
    p=check(directory);path=directory/'NN'/f'{split}.json'
    if path.exists():
        receipt=read(path)
        if receipt['protocol']!=sha(directory/'Protocol.json'):raise ValueError('NN context changed')
        for row in receipt['instances']:
            if not math.isfinite(row['NN_length']) or row['NN_length']<=0:raise ValueError('NN denominator')
        return receipt['instances']
    rows=[];beg=time.monotonic()
    for spec in p['data'][split]:
        source=directory/'data'/spec['path'];d=distances(read(source)['coordinates']);tour,length=nearest_neighbor(d)
        if not math.isfinite(length) or length<=0:raise ValueError('invalid NN denominator')
        rows.append({**spec,'source':str(source),'NN_length':length,'NN_tour':tour})
    write(path,{'protocol':sha(directory/'Protocol.json'),'instances':rows,'seconds':time.monotonic()-beg,'uses':split,'no_generated_candidate':True})
    return rows


def manual_pool():
    expressions=[('manual_NN','-distance_current'),('manual_return_bias','-distance_current - 0.25 * (1-progress) * distance_start'),
        ('manual_far_early','-distance_current + 0.25 * (1-progress) * distance_start'),
        ('manual_remaining_mean','-distance_current - 0.2 * mean_remaining_distance'),
        ('manual_spread','-distance_current + 0.15 * (mean_remaining_distance-nearest_remaining_distance)')]
    return [{'id':name,'candidate':asdict(candidates.validate('def priority('+', '.join(candidates.H_ARGS)+'):\n    return '+expr+'\n',
        'Human-designed '+name+': '+expr,kind='h')),'origin':'manual design for this pilot','formula':expr} for name,expr in expressions]


def static_candidate(support,k):
    values=tuple(1 if i in support else 0 for i in range(k));mode=0 if len(support)==1 else 1
    code='def use_heuristics('+', '.join(candidates.U_ARGS)+'):\n    return '+repr((mode,values))+'\n'
    return asdict(candidates.validate(code,'Static '+str(support),'U',k))


def stage(directory,label,*,kind,split,members=(),manual=(),method='fixed',seed=0,new=0,allow_api=False):
    p=check(directory);s=read(directory/'Campaign_state.json');run=ROOT/'runs'/(directory.name+'--'+label)
    if label not in s['completed_stages']:
        if (directory/'Pause_request.json').exists():raise Paused('campaign paused before stage '+label)
        s['current_stage']=label;write(directory/'Campaign_state.json',s)
    if not run.exists():
        instances=nn_instances(directory,split);run.mkdir()
        config={**p['config'],'type':method,'candidate_kind':kind,'member_count':len(members) if kind=='U' else 1,
            'space':'tsp','search_seed':seed,'population_size':len(manual) if method in ('ind','evo') else 5,'cross_parents':2,'instance_timeout':30}
        tasks=[{'id':r['id'],'candidate':r['candidate'],'stage':'p0' if method in ('ind','evo') else 'fixed'} for r in manual]
        for i in range(new):tasks.append({'id':label+'/'+str(i).zfill(3),'stage':'new','operator':'I1' if method=='ind' else 'CROSS' if i<5 else 'MUTATE',**({'generation':0} if method=='evo' else {})})
        write(run/'Tasks.json',tasks);write(run/'Members.json',list(members))
        protected={str(x.relative_to(ROOT)):sha(x) for x in [run/'Tasks.json',run/'Members.json']}
        for name in ['H_frozen.json','P0.json']:
            if (directory/name).exists():protected[str((directory/name).relative_to(ROOT))]=sha(directory/name)
        protocol={'version':VERSION,'campaign':str(directory),'config':config,'instances':instances,'members':list(members),'protected_files':protected,'source_files':p['source_files'],
            'budgets':{'logical_generation':new,'max_program_instances':len(tasks)*len(instances),'manual_or_P0_evaluations':len(manual)}}
        write(run/'Protocol.json',protocol);(run/'Protocol.sha256').write_text(sha(run/'Protocol.json')+'\n')
        write(run/'checkpoint.json',{'identity':sha(run/'Protocol.json'),'phase':'prepared','cursor':0,'tasks':{},'evaluations':{},'population':[],'children':[],'seen':{},'generation':0,'pause_ack':0})
    state=read(run/'checkpoint.json')
    if state['phase']!='completed':
        if state['phase'] not in ('prepared','paused'):raise RuntimeError('partial stage has Stop/unknown state: '+str(run))
        r=execution.start(run,adapter=Adapter(),resume=state['phase']=='paused',allow_api=allow_api)
        if r['phase']=='paused':raise Paused('stage paused at candidate boundary')
        if r['phase']!='completed':raise RuntimeError('stage '+label+' '+r['phase']+'; preserve its evidence')
    if label not in s['completed_stages']:
        s['completed_stages'].append(label);write(directory/'Campaign_state.json',s)
    return Adapter().summary(run),run


def best_rows(facts):return sorted([r for r in facts['records'] if r['valid']],key=lambda r:(-r['fitness'],r['id']))


class Paused(RuntimeError):pass


def run(directory,allow_api=False,resume=False):
    directory=Path(directory);p=check(directory);s=read(directory/'Campaign_state.json')
    if s['phase']=='completed':raise ValueError('campaign already complete; use summary')
    if p['config']['api_mode']=='real' and (not allow_api or not p['config']['real_requests_authorized']):raise PermissionError('explicit real run authorization required')
    if (directory/'.campaign.lock').exists():raise ValueError('campaign writer/unknown lock present')
    if s['phase']=='partial':raise ValueError('partial Stop requires evidence audit, not blind replay')
    if s['phase']=='paused' and not resume:raise ValueError('use resume for paused campaign')
    fd=os.open(directory/'.campaign.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'pid':os.getpid()},f)
    try:
        if resume and (directory/'Pause_request.json').exists():
            ack=directory/'control'/('pause_ack_'+str(time.time_ns())+'.json');ack.parent.mkdir(exist_ok=True);(directory/'Pause_request.json').replace(ack)
        if not (directory/'Run_clock.json').exists():
            t=time.time();write(directory/'Run_clock.json',{'start':t,'deadline':t+p.get('window_renewal',{}).get('seconds',43200)})
            if 'window_renewal' in p:write(directory/'Window_renewal_receipt.json',{'protocol':sha(directory/'Protocol.json'),'clock_sha256':sha(directory/'Run_clock.json'),'authorization':p['window_renewal']['authorization'],'original_clock_sha256':p['request_origin']['clock_sha256']})
        if time.time()>=read(directory/'Run_clock.json')['deadline']:raise RuntimeError('original campaign window expired')
        s.pop('reason',None);s['phase']='running';s['started_at']=s['started_at'] or time.time();write(directory/'Campaign_state.json',s)
        a,_=stage(directory,'manual-H',kind='h',split='train',manual=manual_pool(),allow_api=allow_api)
        b,_=stage(directory,'H',kind='h',split='train',method='ind',new=10,allow_api=allow_api)
        if not (directory/'H_frozen.json').exists():
            allrows=a['records']+b['records'];seen={};dispositions=[];valid=[]
            for r in allrows:
                key=(r.get('candidate') or {}).get('key');reason='invalid'
                if r['valid']:
                    if key in seen:reason='AST_duplicate_of_'+seen[key]
                    else:seen[key]=r['id'];valid.append(r);reason='eligible'
                dispositions.append({'id':r['id'],'key':key,'fitness':r['fitness'],'valid':r['valid'],'reason':reason,'origin':'manual' if r['id'].startswith('manual') else 'LLM generated pool' if p['config']['api_mode']=='real' else 'MOCK'})
            selected=sorted(valid,key=lambda r:(-r['fitness'],r['id']))[:5]
            if len(selected)<2:raise RuntimeError('fewer than two valid H; no fusion search')
            members=[r['candidate'] for r in selected];freeze(directory,'H_frozen.json',{'members':members,'selected_ids':[r['id'] for r in selected],'selection':p['H_selection'],'dispositions':dispositions,'train_only':True,'key':digest(members)})
        h=read(directory/'H_frozen.json');members=h['members'];k=len(members)
        defs=[{'id':'static_H'+str(i),'candidate':static_candidate((i,),k)} for i in range(k)]
        defs +=[{'id':f'static_H{i}_H{j}_equal','candidate':static_candidate((i,j),k)} for i in range(k) for j in range(i+1,k)]
        static,_=stage(directory,'static',kind='U',split='train',members=members,manual=defs,allow_api=allow_api)
        if not (directory/'P0.json').exists():
            rows=best_rows(static);unique={}
            for r in rows:unique.setdefault(r['candidate']['key'],r)
            pop=list(unique.values())[:5]
            if len(pop)<2:raise RuntimeError('P0 insufficient; no EVO')
            freeze(directory,'P0.json',{'members':[{'id':r['id'],'candidate':r['candidate'],'train_fitness':r['fitness']} for r in pop],
                'static_reference':rows[0],'source':'all frozen H singles/equal pairs train evaluation','static_costs_separate':True,'key':digest(pop)})
        p0=read(directory/'P0.json');pool=p0['members'];champions=[]
        for method,seed in [('IND',701),('IND',702),('EVO',801),('EVO',802)]:
            label=method+'_'+str(seed)
            facts,_=stage(directory,label,kind='U',split='train',members=members,manual=pool,method=method.lower(),seed=seed,new=10,allow_api=allow_api)
            champions.append({'source':label,**best_rows(facts)[0]})
        frozen=directory/'Validation_candidates.json'
        if not frozen.exists():
            unique={}
            for r in champions+[dict(p0['static_reference'],source='train_static_reference')]:
                key=r['candidate']['key']
                if key not in unique:unique[key]={'id':r['id'],'candidate':r['candidate'],'train_fitness':r['fitness'],'sources':[]}
                unique[key]['sources'].append(r['source'])
            freeze(directory,'Validation_candidates.json',{'candidates':list(unique.values()),'selection':'validation complete Fitness desc/id asc','search_closed':True,'H_sha256':sha(directory/'H_frozen.json'),'P0_sha256':sha(directory/'P0.json'),'frozen_at':time.time()})
        val,_=stage(directory,'validation',kind='U',split='validation',members=members,manual=read(frozen)['candidates'],allow_api=allow_api)
        if not (directory/'Final_frozen.json').exists():
            if not best_rows(val):raise RuntimeError('no valid validation candidate')
            winner=best_rows(val)[0]
            freeze(directory,'Final_frozen.json',{'final':winner,'static_reference':p0['static_reference'],'candidate_list_sha256':sha(frozen),'validation_stage_sha256':sha(ROOT/'runs'/(directory.name+'--validation')/'Protocol.json'),'frozen_at':time.time(),'no_more_generation':True})
        final=read(directory/'Final_frozen.json');pair=[{'id':name,'candidate':final[field]['candidate']} for name,field in [('final_U','final'),('train_static','static_reference')]]
        stage(directory,'confirmation',kind='U',split='confirmation',members=members,manual=pair,allow_api=allow_api)
        stage(directory,'transfer',kind='U',split='transfer',members=members,manual=pair,allow_api=allow_api)
        s=read(directory/'Campaign_state.json');s.update(phase='completed',finished_at=time.time());write(directory/'Campaign_state.json',s)
    except Paused as exc:
        s=read(directory/'Campaign_state.json');s.update(phase='paused',reason=str(exc));write(directory/'Campaign_state.json',s)
    except BaseException as exc:
        s=read(directory/'Campaign_state.json');s.update(phase='partial',reason=str(exc),error_type=type(exc).__name__);write(directory/'Campaign_state.json',s)
        write(directory/'Stop.json',{'error_type':type(exc).__name__,'error':str(exc),'at':time.time(),'automatic_retry':False})
    finally:
        (directory/'.campaign.lock').unlink()
        summary(directory,write_files=True)
    return read(directory/'Campaign_state.json')


def stop(directory):
    write(directory/'Pause_request.json',{'requested_at':time.time(),'candidate_boundary':True})
    s=read(directory/'Campaign_state.json');label=s.get('current_stage')
    if label:
        run=ROOT/'runs'/(directory.name+'--'+label)
        if run.exists() and read(run/'checkpoint.json')['phase'] not in ('completed','stopped','expired'):
            execution.stop(run,adapter=Adapter())
    return {'requested':True,'wait_for':'phase=paused, locks removed'}


def summary(directory,write_files=False):
    p=read(directory/'Protocol.json');s=read(directory/'Campaign_state.json');path=directory/'API_attempts.json'
    j=read(Path(p.get('request_origin',{}).get('directory',str(directory)))/'API_attempts.json') if (Path(p.get('request_origin',{}).get('directory',str(directory)))/'API_attempts.json').exists() else {'requests':{},'api_attempts':{}}
    attempts=list(j['api_attempts'].values());req=j['requests'];groups=[];stagefacts={};allrows=[]
    stages=['manual-H','H','static','IND_701','IND_702','EVO_801','EVO_802','validation','confirmation','transfer']
    for label in stages:
        run=ROOT/'runs'/(directory.name+'--'+label)
        if not run.exists():continue
        facts=Adapter().summary(run);stagefacts[label]=facts
        ids={r['id'] for r in facts['records'] if r['stage']=='new'};aa=[a for a in attempts if a['logical_id'] in ids]
        generated=[r for r in facts['records'] if r['stage']=='new'];valid=[r for r in generated if r['valid']]
        groups.append({'stage':label,'planned_new':10 if label in ('H','IND_701','IND_702','EVO_801','EVO_802') else 0,
            'used_new':sum(key in ids for key in req),'API_attempts':len(aa),'complete_responses':sum(key in ids and r['status']=='completed' for key,r in req.items()),
            'certified_new':len(valid),'failed_or_uncommitted_new':sum(r['status']!='not_started' and not r['valid'] for r in generated),'unknown_API_attempts':sum(a['status'] not in ('completed','failed') for a in aa),'duplicates':sum(bool(r.get('AST_duplicate')) for r in generated),'best_fitness':facts['best_so_far']['fitness'] if facts['best_so_far'] else None,
            'new_champion':max((r['fitness'] for r in valid),default=None),'phase':facts['phase'],'physical_evaluations':facts['physical_evaluations']})
        state=read(run/'checkpoint.json')
        for r in facts['records']:
            t=state['tasks'].get(r['id'],{});key=t.get('evaluation_key')
            if key in state['evaluations'] and state['evaluations'][key]['status']=='completed':
                result=read(run/state['evaluations'][key]['path'])
                for row in result['instances']:allrows.append({'stage':label,'id':r['id'],'candidate_complete_valid':result['valid'],**row})
    comparisons={}
    for split in ['confirmation','transfer']:
        rows=[r for r in allrows if r['stage']==split];a={r['file']:r for r in rows if r['id']=='final_U'};b={r['file']:r for r in rows if r['id']=='train_static'}
        if a and a.keys()==b.keys() and len(a)==len(p['data'][split]) and all(r['candidate_complete_valid'] for r in rows):
            delta=[a[k]['length']-b[k]['length'] for k in a];comparisons[split]={'instances':len(a),'final_total_length':math.fsum(r['length'] for r in a.values()),'static_total_length':math.fsum(r['length'] for r in b.values()),
                'final_fitness':-sum(r['ratio'] for r in a.values())/len(a),'static_fitness':-sum(r['ratio'] for r in b.values())/len(b),
                'wins':sum(x< -1e-12 for x in delta),'losses':sum(x>1e-12 for x in delta),'ties':sum(abs(x)<=1e-12 for x in delta),'deltas':dict(zip(a,delta))}
    usage={'known_input_tokens':sum((a.get('usage') or {}).get('input_tokens',0) for a in attempts),'known_output_tokens':sum((a.get('usage') or {}).get('output_tokens',0) for a in attempts),
        'unknown_usage_attempts':sum(a.get('usage') is None for a in attempts),'platform_points':None,'verified_currency_cost':0 if p['config']['api_mode']=='mock' else None}
    result={'mode':p['config']['api_mode'],'state':s,'planned':p['budgets'],'used':{'logical':len(req),'API_attempts':len(attempts),'complete_responses':sum(r['status']=='completed' for r in req.values()),
        'unknown_attempts':sum(a['status'] not in ('completed','failed') for a in attempts)},'groups':groups,'comparisons':comparisons,'usage':usage,'stage_facts':stagefacts,
        'limits':['2 repeats per method; migration pilot, not stable superiority evidence','static/P0 costs reported separately','NN-relative metric, not optimality gap','confirmation and transfer are separate evaluations']}
    if write_files:
        out=directory/'results';out.mkdir(exist_ok=True)
        write(out/'Summary.json',result)
        for name,rows in [('Stages.csv',groups),('Per_instance.csv',allrows)]:
            if rows:
                with (out/name).open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)));w.writeheader();w.writerows(rows)
        (out/'Summary.md').write_text('# TSP固定预算迁移小试\n\n状态：'+s['phase']+'；模式：'+p['config']['api_mode']+'\n\n预算：'+json.dumps(result['used'],ensure_ascii=False)+'\n\n逐阶段：\n\n'+json.dumps(groups,ensure_ascii=False,indent=2)+'\n\n冻结确认/迁移：\n\n'+json.dumps(comparisons,ensure_ascii=False,indent=2)+'\n\n成本：'+json.dumps(usage,ensure_ascii=False)+'\n\n限制：'+'；'.join(result['limits'])+'\n')
    return result
