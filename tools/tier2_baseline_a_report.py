"""Baseline-A analysis, from persisted results only; no solves or H calls."""
from collections import Counter
import math
from statistics import fmean
from fjsp_usage.baseline_a.policies import specs
from fjsp_usage.baseline_a.validation import validate_result,validate_ledger
from fjsp_usage.research.events import atomic_json


def single_oracle(results,instances):
    if set(results)!={f'H{i}' for i in range(10)} or not all(r['valid'] for r in results.values()):
        raise ValueError('Oracle requires all ten complete single H results')
    rows=[]
    for position,expected in enumerate(instances):
        values={i:results[f'H{i}']['instances'][position] for i in range(10)}
        if any(r['file']!=expected['file'] or r['lower_bound']!=expected['LB'] for r in values.values()):
            raise ValueError('Oracle instance/LB mismatch')
        best=min(r['makespan'] for r in values.values());winners=[i for i,r in values.items() if r['makespan']==best]
        score=-best/expected['LB']
        if score!=max(r['score'] for r in values.values()):raise ValueError('Oracle Cmax/score selection mismatch')
        rows.append({'file':expected['file'],'LB':expected['LB'],'Oracle_Cmax':best,'Oracle_score':score,
            'display_member':winners[0],'all_tied_best_members':','.join(map(str,winners)),
            **{f'H{i}_Cmax':values[i]['makespan'] for i in range(10)}})
    return {'fitness':fmean(r['Oracle_score'] for r in rows),'instances':rows,
        'posthoc_diagnostic':True,'online_policy':False,'global_dynamic_upper_bound':False}


def report(directory):
    from tools import tier2_baseline_a as b
    v2=b.v2;p=b.check(directory);state=v2.read(directory/'checkpoint.json')
    reserved=validate_ledger(state,p,v2.read,v2.sha,directory)
    out=b.ROOT/'reports'/directory.name;out.mkdir(exist_ok=True);(out/'certified_results').mkdir(exist_ok=True)
    (out/'process_evidence').mkdir(exist_ok=True)
    references=v2.read(directory/'Historical_references.json');results={};ranking=[];sources=[];instance_rows=[];processes=[];artifacts={}
    for spec in specs():
        identifier=spec['id'];record=state['strategies'].get(identifier);result=None
        if record and record['status']=='completed':
            path=directory/record['result_path'];result=v2.read(path)
            level=p['cache'][identifier]['level'] if identifier in p['cache'] else 'modern'
            validate_result(result,p['instances'],level);results[identifier]=result
            (out/'certified_results'/(identifier+'.json')).write_bytes(path.read_bytes())
            sources.append({'strategy':identifier,'origin':record['origin'],'evidence_level':level,
                'result_path':str(path),'result_sha256':v2.sha(path),'valid':result['valid'],
                'cache_source_file':p['cache'].get(identifier,{}).get('source_file'),
                'cache_source_sha256':p['cache'].get(identifier,{}).get('source_sha256'),
                'terminal_contract':p['cache'].get(identifier,{}).get('process_evidence','modern V4 terminal certificate')})
        valid=bool(result and result['valid'])
        ranking.append({'strategy':identifier,'category':spec['category'],'members':','.join(map(str,spec['members'])),
            'valid':valid,'fitness':result['fitness'] if valid else None,
            'origin':record['origin'] if record else 'not_started','completed_instances':len(result['instances']) if result else 0,
            'first_seconds':sum(r['single_solve_seconds'] for r in result['instances']) if result else None,
            'recheck_seconds':sum(r['deterministic_recheck_seconds'] for r in result['instances']) if result else None,
            'primary_wall_seconds':result.get('primary_evaluation_seconds') if result else None,
            'error_type':result.get('error_type') if result else None,'failed_instance':result.get('failed_instance') if result else None})
        indexed={r['file']:r for r in result['instances']} if result else {}
        for expected in p['instances']:
            row=indexed.get(expected['file']);status=('complete' if valid else 'success_prefix') if row else (
                'failed' if result and expected['file']==result.get('failed_instance') else 'not_reached')
            instance_rows.append({'strategy':identifier,'category':spec['category'],'origin':record['origin'] if record else None,
                'complete_strategy_valid':valid,'file':expected['file'],'status':status,
                'Cmax':row['makespan'] if row else None,'LB':expected['LB'],'Cmax_over_LB':-row['score'] if row else None,
                'score':row['score'] if row else None,'single_seconds':row['single_solve_seconds'] if row else None,
                'recheck_seconds':row['deterministic_recheck_seconds'] if row else None,
                'CPU_seconds':row.get('instance_CPU_seconds') if row else None,
                'physical_schedule_sha256':row.get('physical_schedule_sha256') if row else None,
                'native_recheck_sha256':row.get('deterministic_schedule_sha256') if row else None,
                'error_type':result.get('error_type') if result and status=='failed' else None})
        folder=directory/'evidence'/identifier
        if folder.exists():
            for path in folder.iterdir():
                if path.is_file():artifacts[str(path.relative_to(directory))]={'sha256':v2.sha(path),'bytes':path.stat().st_size}
            if (folder/'boundary.json').exists():
                boundary=v2.read(folder/'boundary.json');life=v2.read(folder/'lifecycle.json')
                processes.append({'strategy':identifier,'decision':boundary['decision'],'reason':boundary.get('reason'),
                    'exitcode':life['exitcode'],'alive':life['alive'],'trigger':life['trigger'],
                    'rows_received':life['rows_received'],'post_result_grace_used':life['exit_grace_used'],
                    'exit_wait_seconds':life['exit_wait_observed_seconds'],
                    'end_identity_present':(folder/'after.json').exists()})
            for name in ('before.json','after.json','boundary.json','lifecycle.json','worker_failure.json','network_guard.json'):
                if (folder/name).exists():(out/'process_evidence'/(identifier+'__'+name)).write_bytes((folder/name).read_bytes())
    if len(instance_rows)!=1155:raise ValueError('all55x21 rows including null failures required')
    singles=[r for r in ranking if r['category']=='A1'];pairs=[r for r in ranking if r['category']=='A2']
    valid_singles=[r for r in singles if r['valid']];valid_pairs=[r for r in pairs if r['valid']]
    for group in (singles,pairs):
        for row in group:row['rank_within_valid_category']=1+sum(x['valid'] and x['fitness']>row['fitness'] for x in group) if row['valid'] else None
        group.sort(key=lambda r:(not r['valid'],-r['fitness'] if r['valid'] else math.inf,r['strategy']))
    best_single=max(valid_singles,key=lambda r:r['fitness']) if valid_singles else None
    best_pair=max(valid_pairs,key=lambda r:r['fitness']) if valid_pairs else None
    oracle=single_oracle({f'H{i}':results[f'H{i}'] for i in range(10)},p['instances'])
    oracle_rows=[{'file':r['file'],'makespan':r['Oracle_Cmax'],'score':r['Oracle_score']} for r in oracle['instances']]
    base={'Best_Single':results[best_single['strategy']],'H0_H1_WS':results['H0_H1_WS'],
          'B2':references['B2'],'Single_H_Oracle':{'fitness':oracle['fitness'],'instances':oracle_rows}}
    comparisons=[];pair_diagnostics=[]
    for row in ranking:
        if not row['valid']:continue
        result=results[row['strategy']]
        for label,reference in base.items():
            differences=[a['score']-c['score'] for a,c in zip(result['instances'],reference['instances'])]
            comparisons.append({'strategy':row['strategy'],'baseline':label,'delta_F':fmean(differences),
                'wins':sum(x>0 for x in differences),'losses':sum(x<0 for x in differences),'ties':sum(x==0 for x in differences)})
        if row['category']=='A2':
            a,c=map(int,row['members'].split(','));component=max(results[f'H{a}']['fitness'],results[f'H{c}']['fitness'])
            envelope=fmean(max(x['score'],y['score']) for x,y in zip(results[f'H{a}']['instances'],results[f'H{c}']['instances']))
            pair_diagnostics.append({'strategy':row['strategy'],'fitness':row['fitness'],
                'delta_vs_best_component':row['fitness']-component,'two_single_posthoc_envelope':envelope,
                'delta_vs_two_single_envelope':row['fitness']-envelope,'delta_vs_all_single_Oracle':row['fitness']-oracle['fitness']})
    h01=next(r for r in pairs if r['strategy']=='H0_H1_WS')
    counts={'above_Best_Single':sum(r['fitness']>best_single['fitness'] for r in valid_pairs),
        'above_H0_H1_WS':sum(r['fitness']>results['H0_H1_WS']['fitness'] for r in valid_pairs),
        'above_B2':sum(r['fitness']>references['B2']['fitness'] for r in valid_pairs),
        'above_Single_H_Oracle':sum(r['fitness']>oracle['fitness'] for r in valid_pairs)}
    oracle_counts=Counter(r['display_member'] for r in oracle['instances']);all_best=Counter()
    for row in oracle['instances']:all_best.update(map(int,row['all_tied_best_members'].split(',')))
    oracle_complementarity=[{'member':i,'display_wins_first_tie':oracle_counts[i],'instances_among_tied_best':all_best[i]} for i in range(10)]
    starts=[v2.read(path) for path in (directory/'evidence').glob('*/*.progress.json')]
    current=[r for r in ranking if r['origin']=='new'];cached=[r for r in ranking if r['origin']=='cache']
    costs={'reserved_new_evaluations':reserved,'reserved_new_solve_passes':reserved*2,
        'recorded_instance_start_markers':len(starts),'recorded_first_start_markers':sum(r['first_started'] for r in starts),
        'recorded_recheck_start_markers':sum(r['recheck_started'] for r in starts),'certified_new_pairs':sum(r['completed'] for r in starts),
        'new_strategies':len(current),'cached_strategies':len(cached),'cached_evaluations_avoided':len(cached)*21,
        'cached_solve_passes_avoided':len(cached)*42,'new_API_requests':0,'new_evolution_runs':0,
        'new_primary_wall_seconds':sum(r['primary_wall_seconds'] or 0 for r in current),
        'new_certified_prefix_first_seconds':sum(r['first_seconds'] or 0 for r in current),
        'new_certified_prefix_recheck_seconds':sum(r['recheck_seconds'] or 0 for r in current),
        'cached_historical_first_seconds':sum(r['first_seconds'] or 0 for r in cached),
        'cached_historical_recheck_seconds':sum(r['recheck_seconds'] or 0 for r in cached),
        'new_confirmed_timeouts':sum(r['error_type']=='Timeout' for r in current),
        'failed_instance_internal_cost':'unknown when killed; not zero filled; included in parent wall time',
        'comparison_scope':'descriptive timing only; legacy caches and modern local evaluations nonconcurrent; no speed claim'}
    if (reserved>861 or costs['recorded_first_start_markers']+costs['recorded_recheck_start_markers']>1722
        or len(starts)>861):raise ValueError('observed/reserved budget exceeded')
    summary={'phase':state['phase'],'single_valid':len(valid_singles),'single_total':10,'pair_valid':len(valid_pairs),'pair_total':45,
        'pair_tasks_covered':sum(r['origin']!='not_started' for r in pairs),'best_single':best_single,'best_pair':best_pair,
        'H01_rank_among_valid_pairs':h01['rank_within_valid_category'],'counts':counts,'Oracle_fitness':oracle['fitness'],
        'Oracle_delta_vs_best_single':oracle['fitness']-best_single['fitness'],
        'Oracle_improved_instances_vs_best_single':sum(r['Oracle_Cmax']<c['makespan'] for r,c in zip(oracle['instances'],results[best_single['strategy']]['instances'])),
        'references':{k:{a:v for a,v in r.items() if a!='instances'} for k,r in references.items()},'costs':costs,
        'protocol_sha256':v2.sha(directory/'Protocol.json'),
        'claim_scope':'best among complete valid evaluated fixed policies only; null strategies unranked; not best over all weights or dynamic U; searched train21 not independent test'}
    ref_instances=[{'reference':label,**row} for label,result in references.items() for row in result['instances']]
    tables={'Single_ranking.csv':singles,'Pair_ranking_45.csv':pairs,'All_instances_1155.csv':instance_rows,
        'Comparisons.csv':comparisons,'Pair_complementarity.csv':pair_diagnostics,'Oracle_instances.csv':oracle['instances'],
        'Oracle_member_counts.csv':oracle_complementarity,'Sources.csv':sources,'Lifecycle.csv':processes,'Historical_reference_instances.csv':ref_instances}
    for name,rows in tables.items():v2.csv_write(out/name,rows)
    atomic_json(out/'Summary.json',summary);atomic_json(out/'Oracle.json',oracle)
    atomic_json(out/'Source_manifest.json',{'run_directory':str(directory),'sources':sources,'raw_new_artifacts':artifacts})
    atomic_json(out/'Costs.json',costs)
    for name in ('Protocol.json','Protocol.sha256','checkpoint.json','H_frozen.json','Historical_references.json','Expected_loaded_identity.json'):
        (out/name).write_bytes((directory/name).read_bytes())
    if (directory/'Stop.json').exists():(out/'Stop.json').write_bytes((directory/'Stop.json').read_bytes())
    fmt=lambda value:f'{value:.12f}' if value is not None else 'null'
    lines=['# Tier 2 Baseline-A 中文总报告','',
        f"完整有效单H {len(valid_singles)}/10；完整有效等权WS {len(valid_pairs)}/45；已登记/覆盖成员对 {summary['pair_tasks_covered']}/45。",
        f"Best Single：{best_single['strategy']}，{fmt(best_single['fitness'])}。Best有效等权对：{best_pair['strategy']}，{fmt(best_pair['fitness'])}。",
        f"H0/H1在有效对中排名{h01['rank_within_valid_category']}。实例级Single-H Oracle：{fmt(oracle['fitness'])}。",'',
        '## 协议与审计','',
        '固定当前H0–H9顺序、train21、seed501、原LB与mean(−Cmax/LB)。单成员SELECT沿用原始评分；双成员各自对全部合法动作min–max归一化，常量列零，再0.5/0.5加权；精确同分沿原动作顺序首最大值。',
        '共预先冻结10个单H、45个无序双H等权WS。没有新权重、状态、算子、Prompt、LLM请求或演化，也没有访问validation11/test28。',
        '审计复用10个单H和4个成员对，扣除294项/588遍。新批只评价其余41对，最多861项/1722遍；全部策略清单和缺失项在Protocol.json、Cache_audit.json。',
        '旧单H来自封存的原生两遍结果及相同数据/执行器源码；旧额外成员对来自四对网格，逐实例物理复检一致。H01另有V2正常终态认证，并与早期网格全部21实例Cmax/score/物理哈希一致。',
        '旧缓存没有全部保留现代PID/exit0回执，不追溯伪造。旧计划中的10个非评价链配置/工作流/传输模块已变化，核心排程、解释器、原生runtime和相关缓存工具未变；逐项差异及排除依据见Cache_audit.json。',
        '缓存静态H/常量U和排程器不含随机行为；旧生成seed不被冒充为新seed501运行。新进程明确seed501。缓存成本为历史测量，不含当前进程认证开销。',
        '新评价复用冻结V2内核、V4收集器：每实例两遍共享poll(15)，收齐全部结果后独立最多2秒正常退出宽限。完整成绩仍要求前后加载身份、全部文件边界、确认终态exit0。已确认普通超时整策略null并继续独立策略；未知身份/终态/账本即停止。',
        '本轮不保存完整动作评分矩阵，不进行额外轨迹求解；所有物理排程和成本从原两遍求解留证。此留证负担与旧V2不同，不能由跨批耗时差异断言算法加速。', '',
        '## A1：完整单H排序','', '|排名|单H|Fitness|来源|','|---:|---|---:|---|']
    for r in singles:lines.append(f"|{r['rank_within_valid_category']}|{r['strategy']}|{fmt(r['fitness'])}|{r['origin']}|")
    lines+=['','## A2：45对完整结果表','', '|有效排名|成员对|Fitness|来源|完整实例|异常|','|---:|---|---:|---|---:|---|']
    for r in pairs:lines.append(f"|{r['rank_within_valid_category'] or '—'}|{r['strategy']}|{fmt(r['fitness'])}|{r['origin']}|{r['completed_instances']}/21|{r['error_type'] or ''}|")
    lines+=['',f"超过Best Single的有效对{counts['above_Best_Single']}个；超过H0/H1的{counts['above_H0_H1_WS']}个；超过B2冠军的{counts['above_B2']}个；超过Single-H Oracle的{counts['above_Single_H_Oracle']}个。",'',
        '这里的最佳仅指完整有效、已评价固定策略中的最佳；超时对没有完整质量成绩，不参与排序。即使全部45项任务都覆盖，也不把含null的扫描称为全45对质量最优，更不是全部权重或动态U空间最优。', '',
        '## A3：单H实例级事后Oracle','',
        f"Oracle逐实例选10个认证单H中最小Cmax/LB；同实例LB相同，等价于最小Cmax。得到{fmt(oracle['fitness'])}，相对最佳固定单H差{fmt(summary['Oracle_delta_vs_best_single'])}，在{summary['Oracle_improved_instances_vs_best_single']}个实例严格改善。",
        'Oracle_instances.csv同时保留全部10H的Cmax、所有并列最佳成员及展示成员（并列取最小编号）。Oracle_member_counts.csv区分展示计数与并列参与计数，避免把同分偏好当成成员独占贡献。',
        '这是使用结果标签的事后诊断，不可部署为在线U，也不是整个动态策略空间的理论上界；融合动作可产生任一单H未产生的完整排程。Pair_complementarity.csv另列每对相对最佳分量、两单H事后包络及全单H Oracle差值。', '',
        '## 与已有LLM-U比较','', '|方法|Fitness|完成程度/搜索范围|','|---|---:|---|']
    for label,r in references.items():lines.append(f"|{label} {r['id']}|{fmt(r['fitness'])}|{r['generations_completed']}代；{r['logical_attempts']}逻辑任务；非等预算|")
    lines+=['', 'B1核实为Recovery-B的P1完成、P2未运行：19次历史API尝试、14个完整有效新候选，最后一个候选超时后原协议因缺结束身份停止。旧初始化目录另有未完成inflight，本轮未恢复或改写。',
        'B2为固定H01的两代动态权重搜索：20次历史API尝试，19个新且完整有效候选、1重复，另含16个新增静态权重点和人工初始种群。B1自由10H与B2固定H01的初始化、空间、父代和完成程度不同。',
        '本轮55项静态覆盖、14项历史复用与41项新评价，不能与这些LLM搜索预算直接等同。最终策略质量比较不证明枚举搜索比LLM演化更高效。逐实例参照、差值与胜负平保留在CSV；原冠军未经重新求解。', '',
        '## 成本、异常与完整性','',f'`{costs}`','',
        'All_instances_1155.csv保留所有55×21行：成功、无效策略成功前缀、失败和未到达分别标记；后两类Cmax/score为null，整策略Fitness始终null。失败实例内部首解/复检完成量及H调用可能未知，不填成0。',
        '所有缓存结果及新认证结果在certified_results/；新进程身份/生命周期在process_evidence/；Source_manifest.json给出本地原始证据路径和哈希。历史源及新源码身份均再次检查，旧冻结文件不改写。', '',
        '## 后续基线建议','',
        'Budget-matched Static Search：预先固定与LLM-U相同的候选尝试、完整FJSP评价和时间上限，从45对中按预定随机顺序或随机无放回采样，比较相同已消耗预算下的best-so-far；本次全扫描冠军只作较充分覆盖参照。缓存命中也要区分逻辑评价预算与新增计算成本。',
        'Random U：冻结合法程序生成分布、深度/长度、SELECT/MIX及支持集/权重分布，沿用同一语言、解释器、失败和重复规则；匹配尝试与FJSP预算并保留失败，不额外给一方强初始种群。',
        'GP-U：使用相同七状态、H集合、SELECT/WS语义及大小限制，冻结初始化、变异/交叉、选择、重复和超时规则；匹配评价预算，另报程序执行成本。不要把Borda等新算子只开放给某一臂。',
        '后续随机/搜索重复种子及评估口径需另行预注册；train21用于开发，当前排名和Oracle不是独立泛化验证。已有test28不充当新确认集。本轮没有执行这些后续搜索。', '',
        '## 文件与复现','', '排名：Single_ranking.csv / Pair_ranking_45.csv；完整逐实例：All_instances_1155.csv；认证来源：Sources.csv / Source_manifest.json；Oracle：Oracle.json / Oracle_instances.csv；协议：Protocol.json；命令：Commands.md。']
    (out/'REPORT_ZH.md').write_text('\n'.join(lines)+'\n');b.check(directory)
    return {k:summary[k] for k in ('phase','single_valid','pair_valid','pair_tasks_covered','best_single','best_pair','H01_rank_among_valid_pairs','Oracle_fitness','counts','costs')}
