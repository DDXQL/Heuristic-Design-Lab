"""Persisted-evidence analysis only; no scheduling, API or new search."""
import csv
import math
import tarfile
from pathlib import Path
from statistics import fmean,median
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.baseline_a.policies import specs as all_specs
from fjsp_usage.baseline_supplemental import specs
from fjsp_usage.baseline_supplemental.validation import ledger,compare_historical


def csv_write(path,rows):
    if not rows:return
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)


def report(directory):
    from tools import baseline_a_supplemental as s
    p=s.check(directory);state=s.v2.read(directory/'checkpoint.json')
    reserved=ledger(state,p,s.v2.read,s.v2.sha,directory)
    out=s.ROOT/'reports'/directory.name;out.mkdir(exist_ok=True);(out/'certified_results').mkdir(exist_ok=True)
    old={id:s.v2.read(s.ROOT/row['path']) for id,row in p['historical_results'].items()}
    new={};sources=[];rows189=[];costs=[];processes=[];phases=[];comparison=[];summary9=[];artifacts={}
    references=s.v2.read(s.BASE/'Historical_references.json')
    for spec in specs():
        id=spec['id'];entry=state['strategies'].get(id);result=None
        if entry and entry['status']=='completed':
            path=directory/entry['result_path'];result=s.v2.read(path);new[id]=result
            compare_historical(id,result,old[id]);(out/'certified_results'/(id+'.json')).write_bytes(path.read_bytes())
            sources.append({'strategy':id,'source':'Supplemental-T30','result_path':str(path),
                'result_sha256':s.v2.sha(path),'valid':result['valid'],'protocol_sha256':s.v2.sha(directory/'Protocol.json')})
        valid=bool(result and result['valid']);indexed={r['file']:r for r in result['instances']} if result else {}
        summary9.append({'strategy':id,'valid':valid,'fitness':result['fitness'] if valid else None,
            'complete_instances':len(indexed),'failed_instance':result.get('failed_instance') if result else None,
            'primary_seconds':result.get('primary_evaluation_seconds') if result else None,
            'old_baseline_A_fitness':old[id]['fitness'],'old_baseline_A_valid':old[id]['valid']})
        for expected in p['instances']:
            row=indexed.get(expected['file']);historical=next((r for r in old[id]['instances'] if r['file']==expected['file']),None)
            status=('complete' if valid else 'success_prefix') if row else (
                'failed' if result and result.get('failed_instance')==expected['file'] else 'not_reached')
            rows189.append({'strategy':id,'source':'Supplemental-T30','strategy_valid':valid,'file':expected['file'],
                'status':status,'Cmax':row['makespan'] if row else None,'LB':expected['LB'],'score':row['score'] if row else None,
                'single_seconds':row['single_solve_seconds'] if row else None,
                'recheck_seconds':row['deterministic_recheck_seconds'] if row else None,
                'CPU_seconds':row['instance_CPU_seconds'] if row else None,
                'physical_sha256':row['physical_schedule_sha256'] if row else None,
                'commit_sha256':row['commit_sequence_sha256'] if row else None,
                'old_Cmax':historical['makespan'] if historical else None,
                'delta_Cmax_vs_old':row['makespan']-historical['makespan'] if row and historical else None,
                'delta_score_vs_H01':row['score']-old['H0_H1_WS']['instances'][p['instances'].index(expected)]['score'] if row else None,
                'delta_score_vs_B2':row['score']-references['B2']['instances'][p['instances'].index(expected)]['score'] if row else None})
            if row and historical:
                old_hash=historical.get('commit_sequence_sha256') if id!='H0' else historical['deterministic_schedule_sha256']
                comparison.append({'strategy':id,'file':expected['file'],'control':id in ('H0','H0_H1_WS','H0_H3_WS'),
                    'old_Cmax':historical['makespan'],'new_Cmax':row['makespan'],'Cmax_equal':row['makespan']==historical['makespan'],
                    'score_equal':row['score']==historical['score'],
                    'physical_hash_equal':row['physical_schedule_sha256']==historical['physical_schedule_sha256'] if 'physical_schedule_sha256' in historical else None,
                    'commit_or_native_hash_equal':row['commit_sequence_sha256']==old_hash if old_hash else None,
                    'old_single_seconds':historical['single_solve_seconds'],'new_single_seconds':row['single_solve_seconds'],
                    'old_recheck_seconds':historical['deterministic_recheck_seconds'],'new_recheck_seconds':row['deterministic_recheck_seconds']})
        folder=directory/'evidence'/id
        if not folder.exists():continue
        life=s.v2.read(folder/'lifecycle.json');boundary=s.v2.read(folder/'boundary.json')
        processes.append({'strategy':id,'decision':boundary['decision'],'exitcode':life['exitcode'],'alive':life['alive'],
            'reader_stopped':life['receiver_thread_stopped'],'trigger':life['trigger'],'rows_received':life['rows_received'],
            'normal_exit_wait_seconds':life['exit_wait_observed_seconds'],'end_identity_present':(folder/'after.json').exists()})
        for path in folder.iterdir():
            if path.is_file():artifacts[str(path.relative_to(directory))]={'sha256':s.v2.sha(path),'bytes':path.stat().st_size}
        for expected in p['instances']:
            path=folder/(Path(expected['file']).stem+'.progress.json')
            if path.exists():
                phase=s.v2.read(path);receive=next((x for x in life['instance_receives'] if x['file']==expected['file']),{})
                keys=('worker_started','first_start','first_end','recheck_start','recheck_end','consistency_and_physical_end',
                      'result_write_end','after_identity_start','after_identity_end','send_start','send_end')
                phases.append({'strategy':id,'file':expected['file'],**{k:phase.get(k) for k in keys},
                    'parent_wait_start':receive.get('started'),'parent_receive_end':receive.get('finished'),'parent_timely':receive.get('timely'),
                    'first_started':phase['first_started'],'recheck_started':phase['recheck_started'],'completed_marker':phase['completed']})
        if result:
            rows=result['instances'];times=[r['single_solve_seconds']+r['deterministic_recheck_seconds'] for r in rows]
            cpu=sum(r['instance_CPU_seconds'] for r in rows)
            costs.append({'strategy':id,'valid':valid,'successful_instances':len(rows),
                'first_seconds':sum(r['single_solve_seconds'] for r in rows),'recheck_seconds':sum(r['deterministic_recheck_seconds'] for r in rows),
                'two_solve_seconds':sum(times),'median_two_solve_seconds':median(times) if times else None,
                'max_two_solve_seconds':max(times) if times else None,'CPU_seconds':cpu,
                'h_scoring_seconds':sum(r[k]['h_scoring_seconds'] for r in rows for k in ('first_costs','recheck_costs')),
                'fusion_seconds':sum(r[k]['fusion_seconds'] for r in rows for k in ('first_costs','recheck_costs')),
                'primary_wall_seconds':result['primary_evaluation_seconds'],'post_all_results_exit_wait_seconds':life['exit_wait_observed_seconds'],
                'peak_RSS_bytes_macos':max((r['peak_RSS_bytes_macos'] for r in rows),default=None),
                'max_complete_receive_wait_seconds':max((x['finished']-x['started'] for x in life['instance_receives'] if x.get('timely')),default=None)})
    # Composite quality table: retain ALL original 39 valid pairs and use T30
    # only for the six originally invalid pairs. Never rewrite original nulls.
    composite=[];combined_instances=[];chosen={};source_rows=[]
    for spec in all_specs()[10:]:
        id=spec['id'];supplement=not old[id]['valid'];result=new.get(id) if supplement else old[id]
        source='Supplemental-T30' if supplement else 'Baseline-A-original'
        valid=bool(result and result['valid']);chosen[id]=result
        path=(directory/state['strategies'][id]['result_path']) if supplement and id in new else (s.ROOT/p['historical_results'][id]['path'])
        composite.append({'strategy':id,'valid':valid,'fitness':result['fitness'] if valid else None,
            'source':source,'original_Baseline_A_fitness':old[id]['fitness'],
            'original_Baseline_A_valid':old[id]['valid'],'result_path':str(path),'result_sha256':s.v2.sha(path),
            'delta_vs_H01':result['fitness']-old['H0_H1_WS']['fitness'] if valid else None,
            'delta_vs_B2':result['fitness']-references['B2']['fitness'] if valid else None})
        indexed={r['file']:r for r in result['instances']} if result else {}
        for expected in p['instances']:
            row=indexed.get(expected['file'])
            combined_instances.append({'strategy':id,'source':source,'strategy_valid':valid,'file':expected['file'],
                'Cmax':row['makespan'] if row else None,'LB':expected['LB'],'score':row['score'] if row else None,
                'row_status':('complete' if valid else 'success_prefix') if row else 'unavailable'})
    valid_pairs=[r for r in composite if r['valid']]
    for r in composite:r['rank']=1+sum(v['fitness']>r['fitness'] for v in valid_pairs) if r['valid'] else None
    composite.sort(key=lambda r:(not r['valid'],-r['fitness'] if r['valid'] else math.inf,r['strategy']))
    from tools.tier2_baseline_a_report import single_oracle
    oracle=single_oracle({f'H{i}':old[f'H{i}'] for i in range(10)},p['instances'])
    best_single=max((f'H{i}' for i in range(10)),key=lambda id:old[id]['fitness'])
    comparisons=[]
    for id,result in new.items():
        if not result['valid']:continue
        for ref,ref_result in {'H0':old['H0'],'H01':old['H0_H1_WS'],'B2':references['B2']}.items():
            d=[a['score']-b['score'] for a,b in zip(result['instances'],ref_result['instances'])]
            comparisons.append({'strategy':id,'reference':ref,'delta_F':fmean(d),'wins':sum(x>0 for x in d),
                                'losses':sum(x<0 for x in d),'ties':sum(x==0 for x in d)})
    control_rows=[r for r in comparison if r['control']]
    observations={'reserved_evaluations':reserved,'reserved_solve_passes':reserved*2,
        'instance_start_markers':len(phases),'first_start_markers':sum(r['first_started'] for r in phases),
        'recheck_start_markers':sum(r['recheck_started'] for r in phases),
        'completed_pair_markers':sum(r['completed_marker'] for r in phases),'API_requests':0,
        'new_evolution_runs':0,'cached_new_evaluations':0,'extra_diagnostic_solves':0,
        'primary_wall_seconds':sum(r['primary_wall_seconds'] for r in costs)}
    if observations['first_start_markers']+observations['recheck_start_markers']>378 or len(phases)>189:
        raise ValueError('observed budget exceeded')
    summary={'phase':state['phase'],'supplemental_complete_valid':sum(r['valid'] for r in summary9),
        'six_previously_invalid_complete':sum(id in new and new[id]['valid'] for id in old if not old[id]['valid']),
        'composite_pair_valid':len(valid_pairs),'composite_pair_total':45,
        'best_pair':composite[0],'best_single':{'strategy':best_single,'fitness':old[best_single]['fitness']},
        'single_H_Oracle_fitness':oracle['fitness'],'references':{k:{a:b for a,b in v.items() if a!='instances'} for k,v in references.items()},
        'control_instances_compared':len(control_rows),'control_scientific_and_hash_matches':all(r['Cmax_equal'] and r['score_equal'] and r['commit_or_native_hash_equal'] and r['physical_hash_equal'] is not False for r in control_rows),
        'old_prefix_instances_compared':len(comparison)-len(control_rows),
        'above_H01_pairs':sum(r['fitness']>old['H0_H1_WS']['fitness'] for r in valid_pairs),
        'above_B2_pairs':sum(r['fitness']>references['B2']['fitness'] for r in valid_pairs),
        'above_best_single_pairs':sum(r['fitness']>old[best_single]['fitness'] for r in valid_pairs),
        'costs':observations,'protocol_sha256':s.v2.sha(directory/'Protocol.json'),
        'scope':'train21 descriptive; composite mixed source quality ranking, not full45 concurrent T30; original T15 nulls unchanged; no independent generalization'}
    tables={'Strategies_9.csv':summary9,'All_instances_189.csv':rows189,'Old_new_comparison.csv':comparison,
        'Composite_pairs_45.csv':composite,'Composite_pair_instances_945.csv':combined_instances,
        'Costs_9.csv':costs,'Lifecycle_9.csv':processes,'Phases_189.csv':phases,
        'Comparisons.csv':comparisons,'Sources.csv':sources,'Oracle_instances.csv':oracle['instances']}
    for name,rows in tables.items():csv_write(out/name,rows)
    atomic_json(out/'Summary.json',summary);atomic_json(out/'Oracle.json',oracle)
    atomic_json(out/'Source_manifest.json',{'new_results':sources,'raw_artifacts':artifacts,
        'old_results':p['historical_results'],'protected_historical_files':p['protected_files']})
    with tarfile.open(out/'Raw_evidence.tar.gz','w:gz') as archive:
        for path in sorted((directory/'evidence').rglob('*')):
            if path.is_file():archive.add(path,arcname=str(path.relative_to(directory)),recursive=False)
    for name in ('Protocol.json','Protocol.sha256','checkpoint.json','H_frozen.json','Expected_loaded_identity.json','Network_guard.json'):
        if (directory/name).exists():(out/name).write_bytes((directory/name).read_bytes())
    fmt=lambda v:f'{v:.12f}' if v is not None else 'null'
    lines=['# Baseline-A Supplemental T30 与静态基线定稿','',
        f"九策略完整有效{summary['supplemental_complete_valid']}/9；六个原超时组合补齐{summary['six_previously_invalid_complete']}/6；综合有效等权对{len(valid_pairs)}/45。",
        f"协议SHA256：`{summary['protocol_sha256']}`。原Baseline-A六个null及全部旧记录保持不变。",'',
        '## 协议、验收与证据','',
        '依据df28b3d审计，冻结原九策略与顺序、H0–H9代码和排名编号、train21、seed501、未取整V5-LB和mean(−Cmax/LB)。仅SELECT及逐成员当前合法动作minmax后0.5/0.5 WS，原同分规则未变。',
        '独立T30版本使用接收线程，对完整消息接收及反序列化执行30秒期限；首解、复检、结果写入/发送及最后after身份证据共用期限。该机制比原poll(15)后可能阻塞recv更严格，因此不是只改变15→30一个工程变量。阶段计时也增加少量开销。',
        '接收完整21行后另等最多2秒正常退出，不接受迟到成绩；失败时按原0.05秒join、terminate/kill清理。必须PID与源身份对应、接收线程停止、明确终态；成功要求after匹配、exit0及完整复检一致，普通超时只认证无效。未知终态/身份/复检/历史输出/预算不一致立即Stop，不自动重试。',
        'Offline_acceptance.json记录合成进程/部分消息/迟到/退出/身份/预算恢复Mock、V1兼容toy以及既存3800状态矩阵重放；正式评价前冻结全部源文件与旧证据SHA。未运行Tier 1/2演化、真实LLM或holdout。',
        '新批九项全部从空排程完整重评，没有用旧成绩抵扣同期评价。所有完整成功及已认证超时都保留原始行、before/after（如存在）、lifecycle、boundary、进度和网络/数据守卫。已完成账本任务跳过，未知reservation或孤立证据停止，不重复消耗。','',
        '## 九策略结果','', '|策略|完整Fitness|原Baseline-A Fitness|完整实例|主评价墙钟秒|','|---|---:|---:|---:|---:|']
    for r in summary9:lines.append(f"|{r['strategy']}|{fmt(r['fitness'])}|{fmt(r['old_baseline_A_fitness'])}|{r['complete_instances']}/21|{r['primary_seconds']:.3f}|")
    lines+=['','## 同期参照与历史一致性','',
        f"对三个参照的{len(control_rows)}/63项进行了逐实例比较；Cmax、score与对应排程指纹一致性：{summary['control_scientific_and_hash_matches']}。另核对六对原成功前缀{summary['old_prefix_instances_compared']}项。所有共同历史行的结果和可比哈希在每个新策略结束后验证，不一致将停止后续正式评价。",
        'H0历史原生结果的deterministic_schedule_sha256对应新commit_sequence_sha256（同为原Schedule的asdict摘要）；不将FusionResult容器摘要或不同物理序列化哈希混比。H0/H1及H0/H3另比物理排程和commit哈希。H0/H3与H0旧值来自认证历史缓存，不能称三条基线均曾同期重新跑过T15现代执行器；本节为科学输出一致性，不能归因期限改变导致提速。',
        'Old_new_comparison.csv给出逐实例原新Cmax、哈希与两遍耗时；All_instances_189.csv包含对H0/H1、B2逐实例score差，Comparisons.csv列完整策略胜负平及delta_F。','',
        '## 45对综合质量排名','',
        '综合表保留原39个有效对，用本批结果补充六个原无效对；这是一张显式标注来源的质量表，不是全45对同期T30资源实验。原Baseline-A/T15新评价及历史缓存证据边界继续保留，新T30控制结果另表报告，不覆盖旧表。',
        '|有效排名|成员对|Fitness|来源|','|---:|---|---:|---|']
    for r in composite:lines.append(f"|{r['rank'] or '—'}|{r['strategy']}|{fmt(r['fitness'])}|{r['source']}|")
    lines+=['',f"Best Single：{best_single}，{fmt(old[best_single]['fitness'])}；Best Equal-Weight Pair：{composite[0]['strategy']}，{fmt(composite[0]['fitness'])}；Single-H Oracle：{fmt(oracle['fitness'])}。",
        f"综合有效对中超过H0/H1的{summary['above_H01_pairs']}个，超过历史B2的{summary['above_B2_pairs']}个，超过Best Single的{summary['above_best_single_pairs']}个。",
        f"历史B2：{fmt(references['B2']['fitness'])}，两代20次逻辑请求/19个完整有效候选；历史B1已知P1最佳：{fmt(references['B1']['fitness'])}，19次逻辑尝试/14个完整有效候选，P2未完成。来源为原封存Historical_references；不追认缺失现代进程回执、不声称预算或策略空间完全匹配。",
        '最佳仅限这10个固定单H与45个等权对，不是全部权重或动态U的最优。Oracle只用原10H逐实例事后最小Cmax，单H数据未变时Oracle不变；不可部署，也不是动态或融合空间理论上界。枚举最终质量不证明比LLM搜索更有效率。','',
        '## 成本与异常','', '|策略|两遍构造秒|主评价墙钟秒|最慢实例双解秒|退出等待秒|','|---|---:|---:|---:|---:|']
    for r in costs:lines.append(f"|{r['strategy']}|{r['two_solve_seconds']:.3f}|{r['primary_wall_seconds']:.3f}|{r['max_two_solve_seconds']:.3f}|{r['post_all_results_exit_wait_seconds']:.4f}|")
    lines += ['',f"预留{reserved}项／{reserved*2}遍；实际首解启动{observations['first_start_markers']}、复检启动{observations['recheck_start_markers']}；主评价合计{observations['primary_wall_seconds']:.3f}秒。额外诊断求解0、缓存抵扣0、API请求0、演化0。",
        'Costs_9.csv列CPU、评分、融合、RSS与主墙钟；Phases_189.csv区分首解、复检、检查、写盘、after、发送与父接收，Lifecycle_9.csv单列退出等待和终态。构造时间已包含排程器内部合法性检查，不能把CPU/墙钟重叠分项相加成总时间。未完成失败内部耗时不得填零；只认原始启动标记与父等待。',
        '九策略同期串行，描述其差异；跨历史批次的包装、监控和环境不同，不能把耗时变化全归于算子/H复杂度，也不对单次计时作显著性或普遍性能结论。','',
        '## 下一轮：只设计，不执行','',
        'Budget-matched Static Search最小协议、缓存与合法率计账、B1/B2公平性及独立编号置换敏感性方案见NEXT_STATIC_SEARCH_PROTOCOL_ZH.md。此处不启动搜索、不抽取任何新候选、不运行LLM演化。','',
        '## 复现','',
        '参见REPRODUCE.md。run目录保存原始证据，报告目录保存认证结果副本、逐实例表、来源清单与本报告。Protocol.sha256为正式评价前的冻结值；源码/旧记录受协议SHA清单保护。']
    (out/'REPORT_ZH.md').write_text('\n'.join(lines)+'\n')
    s.check(directory);print(summary)
