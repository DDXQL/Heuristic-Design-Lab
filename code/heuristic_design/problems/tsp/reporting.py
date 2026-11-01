"""Offline committed evidence tables and predeclared figures; never runs a solver."""
import ast
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from heuristic_design.core.storage import read,write,sha,digest
from .h_build import VERSION,METRICS,protocol_state as h_state,committed as h_committed

ROOT=Path(__file__).resolve().parents[4]
U_REQUEST_NODES=(50,100,150,200,220)


def table(path,rows,fields=None):
    fields=fields or list(dict.fromkeys(k for r in rows for k in r)) or ['status']
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n',extrasaction='ignore');w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()})


def session_start(directory,operation):
    token=uuid4().hex;now=time.time()
    write(directory/'sessions'/f'{token}.json',{'operation':operation,'started_at':now,
          'started_monotonic':time.monotonic(),'status':'running'})
    return token


def session_end(directory,token):
    path=directory/'sessions'/f'{token}.json';v=read(path)
    v.update(ended_at=time.time(),active_seconds=time.monotonic()-v['started_monotonic'],status='ended')
    write(path,v)


def initialize_u_analysis(directory,*,request_nodes=U_REQUEST_NODES):
    path=directory/'Analysis_protocol.json'
    if list(request_nodes)!=sorted(set(request_nodes)) or any(type(x) is not int or x<1 for x in request_nodes):
        raise ValueError('positive ordered unique analysis budget nodes required')
    value={'metrics':METRICS,'request_nodes':list(request_nodes),'protocol_sha256':sha(directory/'Protocol.json')}
    value['git_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    value['git_diff_sha256']=digest(subprocess.check_output(['git','diff','HEAD'],cwd=ROOT,text=True))
    if path.exists() and read(path)!=value:raise ValueError('analysis protocol already differs')
    write(path,value);write(directory/'Analysis_protocol.receipt.json',{'sha256':sha(path)})


def u_snapshot(directory,s,p):
    count=s['initialization_requests']+s['generation_requests']
    analysis=directory/'Analysis_protocol.json'
    nodes=read(analysis)['request_nodes'] if analysis.exists() else U_REQUEST_NODES
    for node in nodes:
        cap=p['config'].get('api_attempt_cap')
        if node>count or (cap is not None and node>cap):continue
        path=directory/f'budget-nodes/Q{node:04d}.json'
        if not path.exists():
            write(path,{'target_requests':node,'observed_reserved_requests':count,'generation':s['generation'],
                'as_of':time.time(),'protocol_sha256':s['identity'],'population':s['population'],
                'completed_tasks':s['completed_tasks'],'note':'first drained batch boundary at/after target; overshoot explicitly recorded'})


def load(directory):
    p=read(directory/'Protocol.json')
    if p.get('version')==VERSION:
        p,s=h_state(directory);tasks=h_committed(directory,p,s);kind='H'
    else:
        from experiments.common._search_reports import protocol_state
        p,s=protocol_state(directory)
        if p['config']['problem']!='tsp':raise ValueError('only TSP evidence supported')
        ids=[]
        for path in sorted((directory/'batch-receipts').glob('*.json')):
            if int(path.stem)>s['completed_tasks']:continue
            ids.extend(read(path)['semantics_commit_order'])
        tasks=[s['tasks'][tid] for tid in ids if s['tasks'][tid]['status']=='completed'];kind='U'
    evaluations={}
    for t in tasks:
        key=t.get('candidate',{}).get('key');ev=s['evaluations'].get(key)
        if not ev or ev.get('status','completed')!='completed' or key in evaluations:continue
        path=directory/ev['path']
        if sha(path)!=ev['sha256']:raise ValueError('committed evaluation receipt changed')
        evaluations[key]=read(path)
    return p,s,tasks,evaluations,kind


def compatibility(p,b):
    reasons=[]
    for key in ('problem','solve_seed','instance_timeout_seconds','window','enabled_groups'):
        if p['config'].get(key)!=b['config'].get(key):reasons.append('config.'+key)
    if p['config'].get('evaluation_mode')!='solve' or b['config'].get('evaluation_mode')!='solve':
        reasons.append('evaluation must be real solve, not a Mock score')
    for key in ('instances','references','members'):
        a=p.get(key);bb=b.get(key)
        if key=='instances':
            a=[(r['file'],r['sha256']) for r in a];bb=[(r['file'],r['sha256']) for r in bb]
        elif key=='members':a=[r['key'] for r in a];bb=[r['key'] for r in bb]
        if a!=bb:reasons.append(key)
    for name in ('code/heuristic_design/problems/tsp/routing.py','code/heuristic_design/problems/tsp/solver.py',
                 'code/heuristic_design/problems/tsp/common_state.py','code/heuristic_design/core/routing.py',
                 'code/heuristic_design/core/routing_evaluation.py','code/heuristic_design/core/constructive_state.py',
                 'code/heuristic_design/problems/routing_fixtures.py'):
        if not p.get('source_files',{}).get(name) or p['source_files'].get(name)!=b.get('source_files',{}).get(name):reasons.append(name)
    return reasons


def baseline_comparison(directory,p,tasks,evs,baseline):
    if not baseline:return {'status':'missing_baseline','notice':'尚未提供兼容基线；保留占位'},[]
    b,bs,bt,be,bkind=load(Path(baseline))
    reasons=compatibility(p,b) if bkind=='U' else ['baseline is not a constant-U evaluation']
    if bs['phase']!='completed':reasons.append('baseline incomplete')
    singles=[]
    for t in bt:
        if not t.get('valid'):continue
        tree=ast.parse(t['candidate']['code']);f=tree.body[0]
        if len(f.body)==1 and isinstance(f.body[0],ast.Return) and isinstance(f.body[0].value,ast.Constant) and type(f.body[0].value.value) is int:
            singles.append(t)
    if {ast.parse(t['candidate']['code']).body[0].body[0].value.value for t in singles}!=set(range(len(p['members']))):reasons.append('not all constant H members evaluated')
    if reasons:return {'status':'incompatible_baseline','reasons':reasons,'notice':'不计算混合口径差值'},[]
    valid=[t for t in tasks if t.get('valid') and t['candidate']['key'] in evs]
    if not valid:return {'status':'no_valid_U'},[]
    champion=sorted(valid,key=lambda t:(-t['fitness'],t['id']))[0]
    best=sorted(singles,key=lambda t:(-t['fitness'],t['id']))[0]
    a=evs[champion['candidate']['key']]['instances'];bb=be[best['candidate']['key']]['instances'];rows=[]
    for x,y in zip(a,bb):
        la=x['solution']['length'];lb=y['solution']['length']
        rows.append({'file':x['file'],'U_length':la,'baseline_length':lb,'delta_fitness':x['score']-y['score'],
                     'relative_length_reduction_percent':100*(lb-la)/lb,
                     'result':'胜' if la<lb-1e-12 else '负' if la>lb+1e-12 else '平'})
    return {'status':'compatible','champion_id':champion['id'],'baseline_id':best['id'],
            'U_fitness':champion['fitness'],'baseline_fitness':best['fitness'],
            'delta_fitness':champion['fitness']-best['fitness'],
            'relative_normalized_improvement_percent':100*(champion['fitness']-best['fitness'])/abs(best['fitness']),
            'wins':sum(r['result']=='胜' for r in rows),'losses':sum(r['result']=='负' for r in rows),
            'ties':sum(r['result']=='平' for r in rows),'selection':'both complete train champions, fixed ID ties; descriptive training comparison'},rows


def report(directory,*,baseline=None,output=None,plots=True):
    directory=Path(directory).resolve();p,s,tasks,evs,kind=load(directory)
    output=Path(output).resolve() if output else directory/'analysis'
    protected=('evaluations','worker-receipts','wire_responses','responses','inputs','next','populations','milestones','plans','sessions','control')
    if output==directory or any(output.is_relative_to(directory/name) for name in protected):
        raise ValueError('separate analysis output required; raw evidence and handoff are protected')
    output.mkdir(parents=True,exist_ok=True)
    now=time.time();mode=p['config']['api_mode'];engineering=mode=='mock'
    analysis_protocol=None
    if (directory/'Analysis_protocol.receipt.json').exists():
        if sha(directory/'Analysis_protocol.json')!=read(directory/'Analysis_protocol.receipt.json')['sha256']:
            raise ValueError('frozen analysis protocol changed')
        analysis_protocol=read(directory/'Analysis_protocol.json')
        if analysis_protocol['protocol_sha256']!=s['identity']:raise ValueError('foreign analysis protocol')
    if kind=='U' and p['config'].get('h_file'):
        hpath=Path(p['config']['h_file'])
        if hpath.exists():engineering|=read(hpath).get('engineering_only',False) if isinstance(read(hpath),dict) else False
    sessions=[read(x) for x in (directory/'sessions').glob('*.json')]
    at=datetime.fromtimestamp(now,ZoneInfo('Asia/Manila')).isoformat(timespec='seconds')
    requests=[]
    if kind=='H':
        journal=read(directory/'API_attempts.json') if (directory/'API_attempts.json').exists() else {'requests':{},'api_attempts':{}}
        attempts=list(journal['api_attempts'].values());committed_ids={t['id'] for t in tasks}
        for a in attempts:
            usage=a.get('usage');requests.append({'id':a['logical_id'],'reserved_attempt':a['number'],
                'committed':a['logical_id'] in committed_ids,'status':a['status'],'sent':a.get('send_confirmed',False),
                'started_at':a.get('started_at'),'finished_at':a.get('finished_at'),
                'usage_known':usage is not None,'input_tokens':usage.get('input_tokens') if usage else None,
                'output_tokens':usage.get('output_tokens') if usage else None})
        reserved=len(attempts);cap=p['config']['api_attempt_cap']
    else:
        all_tasks=list(s['tasks'].values());reserved=s['initialization_requests']+s['generation_requests'];cap=p['config'].get('api_attempt_cap')
        for t in all_tasks:
            if 'request_key' not in t:continue
            value=read(directory/t['response_path']) if t.get('response_path') else {}
            reply=value.get('value',{}) if value.get('ok') else {};usage=reply.get('usage') if isinstance(reply,dict) else None
            requests.append({'id':t['id'],'committed':t in tasks,'status':t['status'],'sent':t.get('sent_confirmed',False),
                'usage_known':usage is not None,'input_tokens':usage.get('input_tokens') if usage else None,
                'output_tokens':usage.get('output_tokens') if usage else None})
    curve=[];best=None;taskrows=[];lineage=[];unique=set();per=[]
    request_order={r['id']:i+1 for i,r in enumerate(requests)}
    for i,t in enumerate(tasks):
        key=t.get('candidate',{}).get('key');duplicate=t.get('AST_duplicate',False) or bool(t.get('duplicate_of'))
        if t.get('valid'):best=max(best,t['fitness']) if best is not None else t['fitness']
        if key and t.get('valid'):unique.add(key)
        x=request_order.get(t['id'],0)
        taskrows.append({'id':t['id'],'generation':t.get('generation'),'operator':t.get('operator'),
            'valid':t.get('valid',False),'duplicate':duplicate,'failure':t.get('failure'),
            'fitness':t.get('fitness'),'candidate_key':key,'cumulative_reserved_requests':x})
        curve.append({'requests':x,'task_index':i+1,'best_fitness':best,'valid_unique_so_far':len(unique)})
        lineage.append({'id':t['id'],'parents':t.get('parents',[]),'operator':t.get('operator'),
                        'candidate_key':key,'generation':t.get('generation'),'prompt_path':t.get('prompt_path',f'prompts/{i:05d}.json'),
                        'response_path':t.get('response_path',f'responses/{i:05d}.json')})
    for key,value in evs.items():
        for r in value['instances']:
            solution=r.get('solution',{})
            per.append({'candidate_key':key,'complete_candidate_valid':value['valid'],'file':r['file'],
                'score':r['score'],'length':solution.get('length'),'tour':solution.get('tour'),
                'member_sequence':r.get('member_sequence'),'h_calls':r.get('h_calls'),'captured_solves':r.get('captured_solves'),
                'semantic_sha256':r.get('semantic_sha256'),'recheck_semantic_sha256':r.get('recheck_semantic_sha256')})
    table(output/'requests.csv',requests);table(output/'candidates.csv',taskrows);table(output/'best_fitness.csv',curve)
    table(output/'per_instance.csv',per);table(output/'lineage.csv',lineage)
    table(output/'generations.csv',s.get('generations',[]));table(output/'sessions.csv',sessions)
    populations=[]
    for path in sorted((directory/'populations').glob('P*.json')):
        for row in read(path):populations.append({'generation':int(path.stem[1:]),**row})
    first_plan=directory/'plans/G001.json'
    if first_plan.exists():
        populations=[{'generation':0,**row} for row in read(first_plan)['population']]+populations
    table(output/'populations.csv',populations)
    nodes=[]
    for folder in ('milestones','budget-nodes'):
        for path in sorted((directory/folder).glob('*.json')):
            if path.name.endswith('.receipt.json'):continue
            v=read(path);nodes.append({'path':str(path.relative_to(directory)),
                'target':v.get('target_requests',v.get('cursor',v.get('generation'))),
                'observed_requests':v.get('observed_reserved_requests',v.get('cursor')),
                'generation':v.get('generation'),'as_of':v.get('as_of')})
    table(output/'budget_nodes.csv',nodes)
    pauses=[]
    for path in sorted((directory/'control').glob('pause_*.json')):pauses.append(read(path))
    for name in ('Pause.json','Pause_request.json'):
        if (directory/name).exists():pauses.append(read(directory/name))
    pauses=list({r.get('sequence',digest(r)):r for r in pauses}.values())
    table(output/'pauses.csv',pauses)
    data={'kind':kind,'engineering':engineering,'phase':s['phase'],'as_of':at,'curve':curve,'generations':s.get('generations',[])}
    comparison={'status':'missing_baseline'};quality=[];selected=[];matrix=[];complement=[]
    if kind=='H':
        seen=set()
        for t in tasks:
            key=t.get('candidate',{}).get('key')
            if not t.get('valid') or key in seen:continue
            seen.add(key);r=evs[key]
            quality.append({'id':t['id'],'candidate_key':key,'fitness':r['fitness'],
                'tour_vector_sha256':digest([x['solution']['tour'] for x in r['instances']])})
        quality.sort(key=lambda r:(-r['fitness'],r['id']))
        if (directory/'H_frozen.json').exists():
            frozen=read(directory/'H_frozen.json');selected=frozen['lineage']
            display=[next(q for q in quality if q['candidate_key']==x['candidate_key']) for x in selected]
        else:display=quality[:10]  # provisional display, NEVER freeze or reselect
        for q in display:matrix.append({'id':q['id'],'scores':[r['score'] for r in evs[q['candidate_key']]['instances']]})
        if matrix:
            values=[r['scores'] for r in matrix];best_single=max(sum(x)/len(x) for x in values)
            envelope=[max(x[j] for x in values) for j in range(len(values[0]))]
            for i,row in enumerate(matrix):
                without=[max((x[j] for k,x in enumerate(values) if k!=i),default=envelope[j]) for j in range(len(envelope))]
                complement.append({'id':row['id'],'leave_one_out_envelope_loss':sum(a-b for a,b in zip(envelope,without))/len(envelope),
                    'envelope_fitness':sum(envelope)/len(envelope),'best_single_fitness':best_single,
                    'envelope_gain':sum(envelope)/len(envelope)-best_single})
        table(output/'H_quality.csv',quality);table(output/'H_frozen_list.csv',selected)
        table(output/'H_complementarity.csv',complement)
        table(output/'H_score_matrix.csv',[{'id':r['id'],**{p['instances'][j]['file']:x for j,x in enumerate(r['scores'])}} for r in matrix])
        data.update(quality=quality,matrix=matrix,complementarity=complement,selection_final=bool(selected))
    else:
        comparison,rows=baseline_comparison(directory,p,tasks,evs,baseline)
        table(output/'baseline_per_instance.csv',rows);table(output/'baseline_summary.csv',[comparison])
        data['comparison']=comparison
    valid=[t for t in tasks if t.get('valid')]
    if valid:
        champion=sorted(valid,key=lambda t:(-t['fitness'],t['id']))[0]
        write(output/'champion.json',champion);(output/'champion.py').write_text(champion['candidate']['code'])
    status='已完成' if s['phase']=='completed' else '进行中' if s['phase'] in ('prepared','launching','running','paused') else '已停止'
    outcome=read(directory/'H_build_outcome.json') if kind=='H' and (directory/'H_build_outcome.json').exists() else None
    if outcome and outcome['status']=='insufficient_valid_unique_H':status='已停止：有效H不足10个'
    summary={'kind':kind,'status':status,'phase':s['phase'],'as_of':at,'engineering_only':engineering,
        'generation_transport':mode,'evaluation_mode':p['config'].get('evaluation_mode','solve'),
        'protocol_sha256':s['identity'],'git_commit':p.get('git_commit',(analysis_protocol or {}).get('git_commit')),
        'analysis_preregistered':kind=='H' or analysis_protocol is not None,
        'committed_tasks':len(tasks),'reserved_attempts':reserved,'API_attempt_cap':cap,
        'real_API_attempts':reserved if mode=='real' else 0,'mock_attempts':reserved if mode=='mock' else 0,
        'confirmed_real_sends':sum(bool(r.get('sent')) for r in requests) if mode=='real' else 0,
        'failures':sum(bool(t.get('failure')) and not (t.get('AST_duplicate') or t.get('duplicate_of')) for t in tasks),
        'duplicates':sum(bool(t.get('AST_duplicate') or t.get('duplicate_of')) for t in tasks),
        'valid_unique_candidates':len(unique),'completed_generations':s.get('generation',0),
        'complete_candidate_instance_rows':sum(len(v['instances']) for v in evs.values() if v['valid']),
        'known_input_tokens':sum(r.get('input_tokens') or 0 for r in requests),
        'known_output_tokens':sum(r.get('output_tokens') or 0 for r in requests),
        'unknown_usage_attempts':sum(not r['usage_known'] for r in requests),
        'transport_failed_attempts':sum(r['status']=='failed' for r in requests),
        'uncommitted_reserved_attempts':sum(not r['committed'] for r in requests),
        'actual_cost':None,
        'started_at':min((x['started_at'] for x in sessions),default=None),
        'ended_at':max((x.get('ended_at',0) for x in sessions),default=None) if s['phase'] not in ('running','launching') else None,
        'active_seconds_completed_sessions':sum(x.get('active_seconds',0) for x in sessions),
        'active_seconds_running_estimate':sum(max(0,now-x['started_at']) for x in sessions if x['status']=='running'),
        'wall_span_seconds_including_pauses':max((x.get('ended_at',now) for x in sessions),default=now)-min((x['started_at'] for x in sessions),default=now),
        'pause_records':len(pauses),'freeze':outcome,'baseline':comparison,'plots_status':'not_requested'}
    write(output/'summary.json',summary);write(output/'plot-data.json',data)
    write(output/'Frozen_identities.json',{'config':p['config'],'source_files':p['source_files'],
        'instances':[{'file':r['file'],'sha256':r['sha256']} for r in p['instances']],
        'references':p['references'],'protocol_sha256':s['identity'],'metrics':p.get('metrics',METRICS)})
    text=[f'# TSP{kind}阶段汇总',f'截至：{at}；状态：{status}。',
        '【Mock工程验证，不是科研成绩】' if engineering else '生成方式：'+mode+'；评价：真实求解。',
        f'已提交任务 {len(tasks)}；预留尝试 {reserved}/{cap if cap is not None else "无真实请求预算"}；有效去重候选 {len(unique)}；完成代数 {s.get("generation",0)}。',
        f'失败 {summary["failures"]}，重复 {summary["duplicates"]}；已知输入/输出token {summary["known_input_tokens"]}/{summary["known_output_tokens"]}，usage未知尝试 {summary["unknown_usage_attempts"]}。',
        f'已结束执行段累计耗时 {summary["active_seconds_completed_sessions"]:.3f} 秒（不含暂停等待）；当前执行段约 {summary["active_seconds_running_estimate"]:.3f} 秒；暂停记录 {len(pauses)}。',
        'H筛选：独立I1池，完整训练评价后一次CPM互补筛选；无H演化、无人工补员、无人类行为审查声明。' if kind=='H' else '基线：'+json.dumps(comparison,ensure_ascii=False),
        '互补性包络是逐实例选择的诊断，不代表可执行动态路由的表现或上界。',
        '缺少的基线/验证数据保持占位；训练结果不等于泛化结果。离线汇总不调用API、不求解、不重选或冻结H。']
    (output/'REPORT_ZH.md').write_text('\n\n'.join(text)+'\n')
    if plots:
        import os
        candidates_=[os.environ.get('HDL_PLOT_PYTHON'),sys.executable,shutil.which('python3'),'/Applications/anaconda3/bin/python3']
        runtime=None
        for binary in dict.fromkeys(x for x in candidates_ if x):
            try:
                if subprocess.run([binary,'-c','import matplotlib'],capture_output=True,timeout=15).returncode==0:runtime=binary;break
            except (OSError,subprocess.TimeoutExpired):continue
        try:
            if not runtime:raise RuntimeError('no plotting Python with matplotlib; set HDL_PLOT_PYTHON')
            done=subprocess.run([runtime,str(ROOT/'tools/tsp_plot_results.py'),'--data',str(output/'plot-data.json'),'--output',str(output)],capture_output=True,text=True,timeout=60)
            if done.returncode:raise RuntimeError(done.stderr[-1500:])
            summary['plots_status']='completed';summary['plot_python']=runtime
        except Exception as exc:
            summary['plots_status']='failed';summary['plot_error']=str(exc)[:1500]
            (output/'PLOT_ERROR.txt').write_text(str(exc))
        write(output/'summary.json',summary)
    return {'output':str(output),'status':status,'plots_status':summary['plots_status'],'committed_tasks':len(tasks)}


def safe_report(directory):
    try:
        result=report(directory);print(json.dumps(result,ensure_ascii=False));return result['plots_status']!='failed'
    except Exception as exc:
        write(directory/'Report_error.json',{'error_type':type(exc).__name__,'error':str(exc)[:500],'raw_results_preserved':True})
        print('离线汇总未完成；原始结果已保留，可用summarize_tsp.py独立重试。',file=sys.stderr);return False
