"""Offline single-H EoH exports and frozen end-to-end comparison, no solving."""
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

from heuristic_design.core.storage import read, write, sha
from . import eoh_single as e
from .reporting import table, load as load_previous


def render(output, data):
    write(output/'plot-data.json',data)
    try:
        runtime=None
        for binary in dict.fromkeys([sys.executable,shutil.which('python3'),'/opt/homebrew/bin/python3','/opt/anaconda3/bin/python']):
            if binary and Path(binary).exists() and subprocess.run([binary,'-c','import matplotlib'],capture_output=True,timeout=15).returncode==0:
                runtime=binary;break
        if runtime is None: raise RuntimeError('matplotlib unavailable; CSV/report retained')
        done=subprocess.run([runtime,str(e.ROOT/'tools/tsp_eoh_plot_results.py'),'--data',str(output/'plot-data.json'),'--output',str(output)],capture_output=True,text=True,timeout=60)
        if done.returncode: raise RuntimeError(done.stderr[-1000:])
        return 'completed'
    except Exception as exc:
        write(output/'PLOT_ERROR.json',dict(error=str(exc),raw_results_preserved=True))
        return 'failed'


def paired_rows(first, second):
    if len(first)!=len(second): raise ValueError('paired instance count differs')
    result=[]
    for a,b in zip(first,second):
        if a['file']!=b['file']: raise ValueError('instance comparison order changed')
        la=a['solution']['length'];lb=b['solution']['length']
        result.append(dict(file=a['file'],EoH_length=la,pipeline_length=lb,
            delta_fitness=a['score']-b['score'],relative_length_reduction_percent=100*(lb-la)/lb,
            result='胜' if la<lb-1e-12 else '负' if la>lb+1e-12 else '平'))
    return result


def preview(config, output, plots=True):
    """Template populated ONLY with the already completed pipeline; EoH blank."""
    c,data,refs,origin,binding=e.preflight(config)
    if c['api_mode']!='real': raise ValueError('preview requires the blocked real config')
    output=Path(output).resolve()
    if not output.is_relative_to(e.ROOT/'reports'): raise ValueError('preview output must be in local reports/')
    output.mkdir(parents=True,exist_ok=True)
    p,s,tasks,evs,kind=load_previous(Path(c['comparison_u_run']))
    best=None;curve=[]
    for i,t in enumerate(tasks,1):
        if t['valid']:best=max(best,t['fitness']) if best is not None else t['fitness']
        curve.append(dict(requests=binding['existing_H_slots']+i,best_fitness=best))
    asof=datetime.now(ZoneInfo('Asia/Manila')).isoformat(timespec='seconds')
    comparison=[dict(method='10H构建+U搜索',fitness=best,request_slots=binding['actual_existing_slots'],request_cap=260),
                dict(method='EoH单H：未运行',fitness=None,request_slots=0,request_cap=c['api_attempt_cap'])]
    values=dict(as_of=asof,engineering=False,phase='protocol_ready_no_EoH_run',curve=[],previous_curve=curve,comparison=comparison,paired=[])
    table(output/'comparison_summary.csv',comparison)
    write(output/'preview.json',dict(**values,API_requests_this_preview=0,policy_solves_this_preview=0,comparison_binding=binding))
    status=render(output,values) if plots else 'not_requested'
    (output/'REPORT_ZH.md').write_text(f'# 比较报告开跑前模板\n\n截至{asof}。EoH真实训练尚未运行，成绩和配对保留空白。已有方案253/260槽，Fitness={best}。\n\n本操作API=0、求解=0，仅重读既有落盘证据。PNG/SVG为同口径输出模板；不把Mock或历史FJSP当作EoH新结果。正式结束/安全暂停将自动输出到新EoH运行目录analysis/。\n')
    return dict(output=str(output),plots_status=status,API_requests=0,policy_solves=0)


def report(directory, output=None, plots=True):
    directory=Path(directory).resolve(); p,s=e.protocol_state(directory)
    output=Path(output).resolve() if output else directory/'analysis'
    if output==directory or any(output.is_relative_to(directory/n) for n in ('evaluations','worker-receipts','wire_responses','responses','populations','milestones','sessions')):
        raise ValueError('separate analysis output required')
    output.mkdir(parents=True,exist_ok=True)
    tasks=list(s['tasks'].values())[:s['cursor']]
    if any(t['status']!='completed' for t in tasks): raise ValueError('uncommitted task in committed prefix')
    journal=read(directory/'API_attempts.json') if (directory/'API_attempts.json').exists() else {'api_attempts':{}}
    attempts=list(journal['api_attempts'].values()); request_order={a['logical_id']:i+1 for i,a in enumerate(attempts)}
    request_rows=[dict(id=a['logical_id'],slot=i+1,status=a['status'],sent=a.get('send_confirmed',False),
        input_tokens=(a.get('usage') or {}).get('input_tokens'),output_tokens=(a.get('usage') or {}).get('output_tokens'),
        usage_known=a.get('usage') is not None,started_at=a.get('started_at'),finished_at=a.get('finished_at'),
        http_status=a.get('metadata',{}).get('http_status'),error_type=a.get('error_type')) for i,a in enumerate(attempts)]
    evs={}; best=None; curve=[]; records=[]; seen=set()
    for t in tasks:
        key=t.get('candidate',{}).get('key')
        if key and key not in evs:
            v=s['evaluations'][key]
            if v['status']!='completed' or sha(directory/v['path'])!=v['sha256']: raise ValueError('committed evaluation changed')
            evs[key]=read(directory/v['path'])
        if t['valid']:
            best=max(best,t['fitness']) if best is not None else t['fitness'];seen.add(key)
        slot=request_order.get(t['id'])
        records.append(dict(id=t['id'],operator=t['operator'],native_generation=t['native_generation'],
            evolution_generation=t['eoh_generation'],parents=t['parents'],candidate_key=key,valid=t['valid'],
            AST_duplicate=t.get('AST_duplicate',False),native_population_duplicate=t.get('native_population_duplicate',False),
            failure=t.get('failure'),fitness=t['fitness'],slot=slot))
        curve.append(dict(requests=slot,best_fitness=best,valid_unique_so_far=len(seen)))
    per=[]
    for key,result in evs.items():
        for r in result['instances']:
            per.append(dict(candidate_key=key,file=r['file'],complete_candidate_valid=result['valid'],
                score=r['score'],length=r['solution']['length'],tour=r['solution']['tour'],
                captured_solves=r['captured_solves'],semantic_sha256=r['semantic_sha256'],
                recheck_semantic_sha256=r['recheck_semantic_sha256']))
    valid=sorted((t for t in tasks if t['valid']),key=lambda t:(-t['fitness'],t['id']))
    champion=valid[0] if valid else None
    if champion:
        write(output/'champion.json',champion);(output/'champion.py').write_text(champion['candidate']['code'])
    table(output/'requests.csv',request_rows);table(output/'candidates.csv',records)
    table(output/'lineage.csv',[{k:r[k] for k in ('id','operator','native_generation','evolution_generation','parents','candidate_key')} for r in records])
    table(output/'per_instance.csv',per);table(output/'best_fitness.csv',curve)
    populations=[]
    for path in sorted((directory/'populations').glob('*.json')):
        value=read(path)
        for category in ('population','next_population'):
            for v in value.get(category,[]):
                populations.append(dict(snapshot=path.stem,native_generation=value['native_generation'],
                    evolution_survivals=value['evolution_survivals'],category=category,id=v['id'],
                    score=v['score'],negative_infinity=v['negative_infinity'],candidate_key=v['candidate']['key']))
    table(output/'populations.csv',populations)
    table(output/'budget_nodes.csv',[dict(path=str(x.relative_to(directory)),cursor=read(x)['cursor'],as_of=read(x)['as_of']) for x in sorted((directory/'milestones').glob('Q*.json'))])
    sessions=[read(x) for x in (directory/'sessions').glob('*.json')]
    table(output/'sessions.csv',sessions)
    table(output/'pauses.csv',[read(x) for x in sorted((directory/'control').glob('pause_*.json'))])
    comparison=[];paired=[];previous_curve=[];mock=p['config']['api_mode']=='mock'
    if not mock:
        for path,expected in p['comparison']['files'].items():
            if sha(path)!=expected: raise ValueError('frozen comparison source changed: '+path)
        up,us,ut,ue,_=load_previous(Path(p['config']['comparison_u_run']))
        old=sorted((t for t in ut if t['valid']),key=lambda t:(-t['fitness'],t['id']))[0]
        old_best=None
        for i,t in enumerate(ut,1):
            if t['valid']: old_best=max(old_best,t['fitness']) if old_best is not None else t['fitness']
            previous_curve.append(dict(requests=p['comparison']['existing_H_slots']+i,best_fitness=old_best))
        previous_result=ue[old['candidate']['key']]
        def comparison_row(label,fitness,budget,confirmed,cap,input_tokens=None,output_tokens=None,unknown=None):
            return dict(method=label,fitness=fitness,request_slots=budget,confirmed_sends=confirmed,request_cap=cap,
                delta_vs_existing_pipeline=fitness-old['fitness'] if fitness is not None else None,
                relative_normalized_improvement_percent=100*(fitness-old['fitness'])/abs(old['fitness']) if fitness is not None else None,
                known_input_tokens=input_tokens,known_output_tokens=output_tokens,unknown_usage_attempts=unknown,
                split='train20',status=s['phase'] if label.startswith('EoH') else 'completed')
        hdir=Path(p['config']['comparison_h_run']); h_journal=read(hdir/'API_attempts.json')
        old_attempts=list(h_journal['api_attempts'].values())
        old_confirmed=sum(a.get('send_confirmed',False) for a in old_attempts)
        old_input=sum((a.get('usage') or {}).get('input_tokens',0) for a in old_attempts)
        old_output=sum((a.get('usage') or {}).get('output_tokens',0) for a in old_attempts)
        old_unknown=sum(a.get('usage') is None for a in old_attempts)
        udir=Path(p['config']['comparison_u_run'])
        for t in ut:
            value=read(udir/t['response_path']).get('value',{})
            usage=value.get('usage');old_confirmed+=bool(t.get('sent_confirmed'))
            old_input+=(usage or {}).get('input_tokens',0);old_output+=(usage or {}).get('output_tokens',0)
            old_unknown+=usage is None
        comparison.append(comparison_row('10H构建+U搜索',old['fitness'],p['comparison']['actual_existing_slots'],old_confirmed,260,old_input,old_output,old_unknown))
        comparison.append(comparison_row('EoH单H：当前/最终',champion['fitness'] if champion else None,len(attempts),
            sum(a.get('send_confirmed',False) for a in attempts),p['config']['api_attempt_cap'],
            sum((a.get('usage') or {}).get('input_tokens',0) for a in attempts),
            sum((a.get('usage') or {}).get('output_tokens',0) for a in attempts),sum(a.get('usage') is None for a in attempts)))
        at253=[r for r in curve if r['requests'] is not None and r['requests']<=253 and r['best_fitness'] is not None]
        if at253:
            label='EoH单H：截至共同实际预算253' if at253[-1]['requests']==253 else 'EoH单H：253节点未到（当前前缀）'
            row=comparison_row(label,at253[-1]['best_fitness'],at253[-1]['requests'],None,260)
            row['status']='253已到达' if at253[-1]['requests']==253 else '进行中：尚未到253';comparison.append(row)
        if champion:
            paired=paired_rows(evs[champion['candidate']['key']]['instances'],previous_result['instances'])
    table(output/'comparison_summary.csv',comparison);table(output/'comparison_per_instance.csv',paired)
    now=time.time();asof=datetime.fromtimestamp(now,ZoneInfo('Asia/Manila')).isoformat(timespec='seconds')
    summary={**e.Adapter().summary(directory),'as_of':asof,'engineering_only':mock,
        'failures':sum(bool(t.get('failure')) for t in tasks),'AST_duplicates':sum(bool(t.get('AST_duplicate')) for t in tasks),
        'native_population_duplicates':sum(bool(t.get('native_population_duplicate')) for t in tasks),
        'known_input_tokens':sum((a.get('usage') or {}).get('input_tokens',0) for a in attempts),
        'known_output_tokens':sum((a.get('usage') or {}).get('output_tokens',0) for a in attempts),
        'unknown_usage_attempts':sum(a.get('usage') is None for a in attempts),'actual_cost':None,
        'complete_candidate_instance_rows':sum(len(v['instances']) for v in evs.values() if v['valid']),
        'captured_solve_passes':sum(r['captured_solves'] for v in evs.values() for r in v['instances']),
        'active_seconds':sum(x.get('active_seconds',max(0,now-x['started_at'])) for x in sessions),
        'comparison':comparison,'plots_status':'not_requested'}
    data=dict(as_of=asof,engineering=mock,phase=s['phase'],curve=curve,previous_curve=previous_curve,comparison=comparison,paired=paired)
    write(output/'plot-data.json',data)
    write(output/'Frozen_identities.json',dict(protocol_sha256=s['identity'],git_commit=p['git_commit'],
        config=p['config'],source_files=p['source_files'],comparison=p['comparison'],metrics=p['metrics'],
        algorithm=p['algorithm'],instances=[dict(file=r['file'],sha256=r['sha256']) for r in p['instances']],references=p['references']))
    if plots: summary['plots_status']=render(output,data)
    write(output/'summary.json',summary)
    status='已完成' if s['phase']=='completed' else '进行中（安全暂停）' if s['phase']=='paused' else '进行中' if s['phase'] in ('prepared','launching','running') else '已停止/未完成'
    lines=['# TSP EoH单规则与双层方案比较',f'截至：{asof}；状态：{status}。',
        '【MOCK工程验证；固定候选真实求解；不是真实LLM科研成绩】' if mock else '真实LLM生成、完整train20真实求解。',
        f'预算：EoH上限{p["config"]["api_attempt_cap"]}次HTTP尝试，当前预留{len(attempts)}，确认发送{summary["confirmed_sends"]}；失败与重复消耗预算，每槽1次，无补发。',
        f'有效AST不同H {summary["valid_unique_H"]}；失败{summary["failures"]}；AST重复{summary["AST_duplicates"]}；原生种群源码/分数重复{summary["native_population_duplicates"]}（口径不同，不能直接相加）。',
        f'初始化请求{s["eoh"]["initialization_requests"]}；原生评价样本{s["eoh"]["evaluated_samples"]}；演化生存更新{s["generation"]}；native generation={s["eoh"]["native_generation"]}（含初始化记账，不能当成U的代数）。',
        f'冠军：{champion["id"] if champion else "尚无"}；Fitness={champion["fitness"] if champion else "缺失"}。完整train按Fitness降序/ID升序选优，不读留出集。',
        '既有方案：H上限40+U上限220=260，实际预留40+213=253；确认发送与已知token另列，不把未知usage当零费用。',
        '同上限比较不是相同实际费用比较。另报告EoH截至253槽的结果；260最终点多出的7槽明确保留。',
        '评价物理、训练实例、NN参考、H语言、模型与请求设置通过身份核对；EoH串行，原U并发2，墙钟不作为公平加速结论。',
        '指标：F=mean(-L/L_NN)，越大越好；ΔF=F_EoH-F_双层；相对变化100*ΔF/abs(F_双层)。逐实例长度胜负平容差1e-12。',
        '单轮训练比较；没有训练外/独立重复证据，不宣称泛化或统计显著性。没有EoH结果时保留占位，绝不借用历史FJSP或旧5H。',
        '表：comparison_summary.csv、comparison_per_instance.csv、requests.csv、candidates.csv、per_instance.csv、populations.csv、lineage.csv、budget_nodes.csv、sessions.csv。图：01_budget_fitness、02_final_comparison、03_instance_comparison（PNG及可编辑SVG）。']
    if comparison:
        lines += ['|方法|Fitness|实际槽位|上限|相对双层变化%|','|---|---:|---:|---:|---:|']
        for x in comparison:
            lines.append(f'|{x["method"]}|{x["fitness"]}|{x["request_slots"]}|{x["request_cap"]}|{x["relative_normalized_improvement_percent"]}|')
    (output/'REPORT_ZH.md').write_text('\n\n'.join(lines)+'\n')
    return dict(output=str(output),phase=s['phase'],plots_status=summary['plots_status'])


def safe_report(directory):
    try: return report(directory)
    except Exception as exc:
        write(Path(directory)/'Report_error.json',dict(error_type=type(exc).__name__,error=str(exc)[:500],raw_results_preserved=True))
        return {'error':type(exc).__name__,'raw_results_preserved':True}
