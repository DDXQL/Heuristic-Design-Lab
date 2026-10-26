"""Stable local facts, never model-generated interpretation or legacy mutation."""
import csv
from datetime import datetime
import json
import os
from pathlib import Path
from statistics import fmean
import time
from zoneinfo import ZoneInfo
from tools import experiment_ops as o


def status(directory):
    s=o.read(directory/'checkpoint.json')
    paths=[directory/'API_attempts.json'] if (directory/'API_attempts.json').exists() else sorted((directory/'journals').glob('*.json'))
    journals=[o.read(path) for path in paths]
    protocol=o.read(directory/'Protocol.json')
    if journals and all('api_attempts' in j for j in journals):
        unknown=sum(a['status'] not in ('completed','failed') for j in journals for a in j['api_attempts'].values())
    elif protocol.get('budgets',{}).get('logical_generation')==0 or (protocol.get('version')==o.VERSION and s['phase']=='prepared'):
        unknown=0
    else:unknown=None  # An unrecognised legacy journal is not proof of zero.
    stop_paths=[directory/'Stop.json',directory/'continuation-v1/Stop.json',directory/'continuation-v1/recovery-v1/Stop.json']
    owner=o.read(directory/'.execution.lock') if (directory/'.execution.lock').exists() else None
    pid=owner.get('pid') if isinstance(owner,dict) else owner if type(owner) is int else None
    exists=None
    if pid:
        try:os.kill(pid,0);exists=True
        except ProcessLookupError:exists=False
        except PermissionError:exists=True
    closeout=o.ROOT/'reports'/directory.relative_to(o.ROOT/'runs')/'closeout-v1/Closeout_status.json'
    clock=o.read(directory/'Run_clock.json') if (directory/'Run_clock.json').exists() else None
    epoch=clock.get('deadline',clock.get('deadline_utc_epoch')) if clock else None
    plan=o.read(directory/'Tasks.json') if (directory/'Tasks.json').exists() else None
    total=len(plan) if isinstance(plan,list) else len(plan['tasks']) if isinstance(plan,dict) and isinstance(plan.get('tasks'),list) else None
    return {'run_dir':str(directory),'phase':s.get('phase'),'cursor':s.get('cursor'),
        'writer_lock_present':any((directory/n).exists() for n in ('.execution.lock','.writer.lock')),
        'persistent_Stop':any(p.exists() for p in stop_paths),
        'tasks_total':total,
        'known_Stop_records':[str(p) for p in stop_paths if p.exists()],
        'writer_owner':owner,'writer_pid_exists':exists,
        'separate_closeout_record':o.read(closeout) if closeout.exists() else None,
        'unknown_API_attempts':unknown,
        'unknown_evaluations':sum(e['status'] not in ('completed',) for e in s.get('evaluations',{}).values()),
        'deadline':clock,
        'deadline_manila':datetime.fromtimestamp(epoch,ZoneInfo('Asia/Manila')).isoformat() if epoch else None,
        'remaining_window_seconds':max(0,epoch-time.time()) if epoch else None,
        'pause_request':o.read(directory/'Pause_request.json') if (directory/'Pause_request.json').exists() else None,
        'read_only':True}


def summary(directory,write_files=False):
    p=o.read(directory/'Protocol.json');s=o.read(directory/'checkpoint.json')
    if p.get('version')!=o.VERSION:
        # Existing published reports are evidence, not rewritten by this adapter.
        report=o.ROOT/'reports'/directory.relative_to(o.ROOT/'runs')
        path=report/'Summary.json'
        if not path.exists():raise ValueError('no recognized published Summary.json; use the original report CLI')
        old=o.read(path)
        closeout=report/'closeout-v1/Closeout_status.json'
        return {'historical_read_only':True,'source':str(path),'facts':old,
                'separate_closeout_record':o.read(closeout) if closeout.exists() else None,
                'limit':'Old campaign remains frozen. This command does not start/resume/recompute it.'}
    try:o.check_run(directory);identity='matched'
    except Exception as exc:identity='mismatch: '+str(exc)
    tasks=list(s['tasks'].values());j=o.read(directory/'API_attempts.json') if (directory/'API_attempts.json').exists() else {'requests':{},'api_attempts':{}}
    valid=[];per_instance=[];rows=[];initial=[];new=[];fixed=[];running=[];best=None
    for task in o.read(directory/'Tasks.json'):
        t=s['tasks'].get(task['id']);row={'id':task['id'],'stage':task['stage'],'condition':task.get('condition'),
            'status':t.get('status') if t else 'not_started','fitness':None,'valid':False,
            'repeat':task.get('repeat',0),'pair_index':task.get('pair_index')}
        if t:
            row.update(failure=t.get('failure'),AST_duplicate=t.get('AST_duplicate'),cache_hit=t.get('cache_hit'),parents=json.dumps(t.get('parents',[])))
            key=t.get('evaluation_key');e=s['evaluations'].get(key)
            if e and e['status']=='completed' and o.sha(directory/e['path'])==e['sha256']:
                result=o.read(directory/e['path'])
                o.certified.validate_result(result,p['instances'],'modern')
                row['error_type']=result.get('error_type');row['successful_rows']=len(result['instances'])
                if t.get('status')=='completed' and result['valid'] and t['fitness']==result['fitness']:
                    row.update(valid=True,fitness=result['fitness']);valid.append(row)
                    (initial if task['stage']=='p0' else new if task['stage']=='new' else fixed).append(row)
                    if best is None or row['fitness']>best['fitness']:best=dict(row)
                for r in result['instances']:per_instance.append({'id':task['id'],'complete_candidate_valid':bool(t.get('status')=='completed' and result['valid']),
                        'file':r['file'],'Cmax':r['makespan'],'LB':r['lower_bound'],
                        'score':r['score'],'physical_schedule_sha256':r['physical_schedule_sha256'],
                        'first_seconds':r['single_solve_seconds'],'recheck_seconds':r['deterministic_recheck_seconds']})
        if t and t['status']=='completed':running.append({'committed_task':len(running)+1,'id':task['id'],'stage':task['stage'],
            'best_fitness':best['fitness'] if best else None,'best_id':best['id'] if best else None})
        rows.append(row)
    attempts=list(j['api_attempts'].values());complete=sum(r['status']=='completed' for r in j['requests'].values())
    costs=[]
    for key,e in s['evaluations'].items():
        if e['status']!='completed':continue
        folder=(directory/e['path']).parent;result=o.read(directory/e['path'])
        phases=[o.read(q) for q in folder.glob('*.progress.json')]
        costs.append({'key':key,'valid':result['valid'],'parent_seconds':result['primary_evaluation_seconds'],
                      'first_starts':sum(bool(q.get('first_started')) for q in phases),
                      'recheck_starts':sum(bool(q.get('recheck_started')) for q in phases)})
    b0=max(initial,key=lambda r:r['fitness']) if initial else None;b1=max(new,key=lambda r:r['fitness']) if new else None
    comparison=None
    if p['config']['type']=='pair' and len(rows)==2 and all(r['valid'] for r in rows):
        left,right=rows
        l={r['file']:r for r in per_instance if r['id']==left['id']};rr={r['file']:r for r in per_instance if r['id']==right['id']}
        comparison={'direction':'second minus first Fitness; wins count second Cmax < first Cmax','first':left['id'],'second':right['id'],
            'delta_Fitness':right['fitness']-left['fitness'],'second_wins':sum(rr[k]['Cmax']<l[k]['Cmax'] for k in l),
            'second_losses':sum(rr[k]['Cmax']>l[k]['Cmax'] for k in l),'ties':sum(rr[k]['Cmax']==l[k]['Cmax'] for k in l)}
    facts={'schema':'operations-facts-v1','question':p['config']['question'],'config_identity':s['identity'],
        'type':p['config']['type'],'space':p['config']['space'],'search_seed':p['config']['search_seed'],'solve_seed':501,
        'api_mode':p['config']['api_mode'],'phase':s['phase'],'complete':s['phase']=='completed','identity_check':identity,
        'planned':p['budgets'],'used':{'committed_tasks':s['cursor'],'reserved_tasks':len(s['tasks']),
            'logical_generation':len(j['requests']),'API_attempts':len(attempts),'complete_responses':complete,
            'certified_strategies':len(valid),'certified_new_generation':sum(r['valid'] and r['stage']=='new' for r in rows),
            'failed_or_uncommitted_tasks':sum(r['status'] not in ('not_started',) and not r['valid'] for r in rows),
            'AST_duplicates':sum(bool(r.get('AST_duplicate')) for r in rows),'cache_hits':sum(bool(r.get('cache_hit')) for r in rows),
            'new_program_instances_reserved':len(s['evaluations'])*len(p['instances']),
            'first_starts':sum(r['first_starts'] for r in costs),'recheck_starts':sum(r['recheck_starts'] for r in costs)},
        'initial_champion':b0,'new_champion':b1,'best_so_far':best,
        'fixed_evaluation_champion':max(fixed,key=lambda r:r['fitness']) if fixed else None,
        'strategy_results':rows,'paired_comparison':comparison,
        'new_minus_initial_Fitness':b1['fitness']-b0['fitness'] if b1 and b0 else None,
        'API_usage':{'known_input_tokens':sum((a.get('usage') or {}).get('input_tokens',0) for a in attempts),
            'known_output_tokens':sum((a.get('usage') or {}).get('output_tokens',0) for a in attempts),
            'unknown_usage_attempts':sum(a.get('usage') is None for a in attempts),
            'verified_currency_cost':0 if p['config']['api_mode']!='real' else None,
            'platform_points':None,'note':'No fee gate or invoice/account queries; mock tokens are zero, not real generation.'},
        'evaluation_parent_seconds':sum(r['parent_seconds'] for r in costs),
        'limits':['Facts only; no generated scientific interpretation.','Complete Fitness requires all frozen instances; failures never get prefix mean.',
                  'P0 evaluations cost separately; cache hits still occupy logical slots.','This run is not automatically budget-fair with historical B1/B2.'],
        'files':{'candidates':str(directory/'results/Candidates.csv'),'per_instance':str(directory/'results/Per_instance.csv'),
                 'raw_responses':str(directory/'responses'),'checkpoint':str(directory/'checkpoint.json')}}
    groups=[]
    for condition in sorted({r['condition'] or p['config']['type'] for r in rows}):
        group=[r for r in rows if (r['condition'] or p['config']['type'])==condition]
        ids={r['id'] for r in group};scores=[r['fitness'] for r in group if r['valid'] and r['stage']=='new']
        groups.append({'method':condition,'search_seed':p['config']['search_seed'],
            'planned_new_slots':sum(r['stage']=='new' for r in group),
            'used_new_slots':sum(k in ids for k in j['requests']),
            'API_attempts':sum(a['logical_id'] in ids for a in attempts),
            'complete_responses':sum(k in ids and r['status']=='completed' for k,r in j['requests'].items()),
            'certified_new':len(scores),'mean_valid_new':fmean(scores) if scores else None})
    facts['method_groups']=groups
    if write_files:
        out=directory/'results';out.mkdir(exist_ok=True)
        for name,data in [('Candidates.csv',rows),('Per_instance.csv',per_instance),('Best_so_far.csv',running),('Evaluation_costs.csv',costs)]:
            if not data:continue
            fields=list(dict.fromkeys(k for r in data for k in r))
            with (out/name).open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(data)
        o.write(out/'Summary.json',facts)
        text=['# 实验事实摘要（可贴回讨论）','',f"问题：{facts['question']}",f"身份：{s['identity']}",
            f"类型/范围/seed：{facts['type']} / {facts['space']} / {facts['search_seed']}",
            f"状态：{s['phase']}；完整={facts['complete']}；身份={identity}",
            f"原定预算：{json.dumps(facts['planned'],ensure_ascii=False)}",f"已用预算：{json.dumps(facts['used'],ensure_ascii=False)}",
            f"初始冠军：{b0}",f"新增生成冠军：{b1}",f"已见最好：{best}",f"新增−初始Fitness：{facts['new_minus_initial_Fitness']}",
            f"逐方法预算/结果：{groups}",f"固定配对差值：{comparison}",
            f"API/用量：{facts['API_usage']}",f"评价区间秒：{facts['evaluation_parent_seconds']}",
            '限制：'+ '；'.join(facts['limits']),f"结果：{directory/'results'}",'事实不自动解释为方法有效或无效。']
        (out/'Summary.md').write_text('\n\n'.join(text)+'\n')
    return facts
