"""Frozen progress-policy analysis; no new schedules, H calls or API requests."""
from collections import Counter,defaultdict
import csv
import gzip
import itertools
import json
from pathlib import Path
from statistics import fmean

from fjsp_usage.fusion_v3.execution import fuse_rank
from fjsp_usage.fusion_v4.policies import specs
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from tools import fusion_v3_experiment as v3


def first_difference(a,b):
    return next((i for i,(x,y) in enumerate(zip(a,b)) if x!=y),None)


def report(directory):
    from tools import fusion_v4_experiment as batch
    v2=batch.v2;p=batch.check(directory);checkpoint=v2.read(directory/'checkpoint.json')
    out=batch.ROOT/'reports'/directory.name;out.mkdir(exist_ok=True);(out/'raw').mkdir(exist_ok=True)
    baselines={};baseline_seq={};all_results={};artifact_sources=[]
    for role,binding in p['fixed_baselines'].items():
        path=batch.ROOT/binding['path']
        if v2.sha(path)!=binding['sha256']:raise ValueError('baseline changed')
        result=v2.read(path);v2.check_result(result,[r['file'] for r in p['instances']])
        if not result['valid']:raise ValueError('invalid baseline')
        baselines[role]=result;all_results['FIXED_'+role]=result
        for row in result['instances']:
            trace_path=path.parents[2]/row['trace_path']
            if v2.sha(trace_path)!=row['trace_sha256']:raise ValueError('baseline trajectory changed')
            artifact_sources.append({'role':role,'file':row['file'],'path':str(trace_path),'sha256':row['trace_sha256']})
            with gzip.open(trace_path,'rt',encoding='utf-8') as handle:
                baseline_seq[(role,row['file'])]=[r['chosen'] for r in map(json.loads,handle)]
    base_rows={role:{r['file']:r for r in result['instances']} for role,result in baselines.items()}
    rankings=[{'strategy':'FIXED_'+role,'status':'historical_certified','fitness':r['fitness'],
        'delta_F_vs_WS':r['fitness']-baselines['WS']['fitness'],
        'delta_F_vs_BORDA':r['fitness']-baselines['BORDA']['fitness']} for role,r in baselines.items()]
    instance_rows=[];comparisons=[];switch_rows=[];mechanism=[];cost_rows=[];boundary_rows=[];artifacts={}
    with gzip.open(out/'State_decisions.csv.gz','wt',encoding='utf-8') as stream:
        fields=['strategy','file','step','progress','operator','chosen','WS_action','BORDA_action',
                'WS_top_ties','BORDA_top_ties','changed_from_WS','changed_from_BORDA']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for spec in specs():
            record=checkpoint['strategies'].get(spec['id']);folder=directory/'evidence'/spec['id'];result=None
            if record and record['status']=='completed':
                path=directory/record['result_path']
                if v2.sha(path)!=record['result_sha256']:raise ValueError('result changed')
                result=v2.read(path);v2.validate_rows(result['instances'],p)
                v2.check_result(result,[r['file'] for r in p['instances']])
                all_results[spec['id']]=result
            rank={'strategy':spec['id'],'status':'valid' if result and result['valid'] else 'invalid_or_not_completed',
                  'fitness':result['fitness'] if result else None,
                  'delta_F_vs_WS':result['fitness']-baselines['WS']['fitness'] if result and result['valid'] else None,
                  'delta_F_vs_BORDA':result['fitness']-baselines['BORDA']['fitness'] if result and result['valid'] else None}
            rankings.append(rank);by_name={r['file']:r for r in result['instances']} if result else {};stats=Counter()
            for expected in p['instances']:
                name=expected['file'];row=by_name.get(name)
                instance_rows.append({'strategy':spec['id'],'file':name,'valid_complete_candidate':bool(result and result['valid']),
                    'Cmax':row['makespan'] if row else None,'LB':expected['LB'],'score':row['score'] if row else None,
                    'fixed_WS_Cmax':base_rows['WS'][name]['makespan'],'fixed_BORDA_Cmax':base_rows['BORDA'][name]['makespan'],
                    'delta_Cmax_vs_WS':row['makespan']-base_rows['WS'][name]['makespan'] if row else None,
                    'delta_Cmax_vs_BORDA':row['makespan']-base_rows['BORDA'][name]['makespan'] if row else None,
                    'delta_F_vs_WS':row['score']-base_rows['WS'][name]['score'] if row else None,
                    'delta_F_vs_BORDA':row['score']-base_rows['BORDA'][name]['score'] if row else None,
                    'single_seconds':row['single_solve_seconds'] if row else None,
                    'recheck_seconds':row['deterministic_recheck_seconds'] if row else None,
                    'physical_schedule_sha256':row['physical_schedule_sha256'] if row else None,
                    'error_type':result.get('error_type') if result and not row else None})
                if not row:continue
                cost_rows.append({'strategy':spec['id'],'file':name,'CPU_seconds':row['instance_CPU_seconds'],
                    'first_H_seconds':row['first_costs']['h_scoring_seconds'],'first_fusion_seconds':row['first_costs']['fusion_seconds'],
                    'recheck_H_seconds':row['recheck_costs']['h_scoring_seconds'],'recheck_fusion_seconds':row['recheck_costs']['fusion_seconds'],
                    'trace_write_seconds':row['trace_write_seconds'],'peak_RSS_native_units':row['peak_RSS_native_units'],
                    'H_calls_two_passes':sum(row['single_h_calls'])+sum(row['recheck_h_calls'])})
                trace_path=directory/row['trace_path']
                if v2.sha(trace_path)!=row['trace_sha256']:raise ValueError('dynamic trajectory changed')
                sequence=[];operators=[];counts=Counter();boundary_changed=None;switch_step=None;last_op=None
                with gzip.open(trace_path,'rt',encoding='utf-8') as handle:
                    for trace in map(json.loads,handle):
                        if digest(trace['physical_state'])!=trace['state_sha256']:raise ValueError('state identity differs')
                        expected_op=spec['first'] if trace['state']['progress']<spec['threshold'] else spec['late']
                        if trace['operator']!=expected_op:raise ValueError('operator policy replay mismatch')
                        raw={int(i):tuple(c) for i,c in trace['columns'].items()};support=tuple(trace['support'])
                        choices={};ties={};actual_scores=None
                        for op in ('WEIGHTED_SUM','BORDA'):
                            scores,_=fuse_rank(raw,trace['weights'],support,op)
                            chosen=max(range(len(scores)),key=scores.__getitem__);choices[op]=chosen
                            ties[op]=sum(x==scores[chosen] for x in scores)
                            if op==expected_op:actual_scores=scores
                        if choices[expected_op]!=trace['winner'] or tuple(actual_scores)!=tuple(trace['scores']):raise ValueError('same-state decision mismatch')
                        if last_op is not None and last_op!=expected_op:
                            if switch_step is not None:raise ValueError('more than one actual switch')
                            switch_step=trace['step'];boundary_changed=choices['WEIGHTED_SUM']!=choices['BORDA']
                        sequence.append(trace['chosen']);operators.append(expected_op);counts[expected_op]+=1;last_op=expected_op
                        stats['states']+=1;stats['changed_vs_WS']+=choices[expected_op]!=choices['WEIGHTED_SUM']
                        stats['changed_vs_BORDA']+=choices[expected_op]!=choices['BORDA']
                        writer.writerow({'strategy':spec['id'],'file':name,'step':trace['step'],
                            'progress':trace['state']['progress'],'operator':expected_op,'chosen':trace['winner'],
                            'WS_action':choices['WEIGHTED_SUM'],'BORDA_action':choices['BORDA'],
                            'WS_top_ties':ties['WEIGHTED_SUM'],'BORDA_top_ties':ties['BORDA'],
                            'changed_from_WS':choices[expected_op]!=choices['WEIGHTED_SUM'],
                            'changed_from_BORDA':choices[expected_op]!=choices['BORDA']})
                if counts!=Counter(row['operator_counts']) or switch_step is None or row['operator_switches']!=1:
                    raise ValueError('operator counts/switch not independently verified')
                first_vs_ws=first_difference(sequence,baseline_seq[('WS',name)])
                first_vs_borda=first_difference(sequence,baseline_seq[('BORDA',name)])
                shared=first_vs_ws if spec['first']=='WEIGHTED_SUM' else first_vs_borda
                if shared is not None and shared<switch_step:raise ValueError('initial fixed policy shared-prefix failed')
                switch_rows.append({'strategy':spec['id'],'file':name,'operations':len(sequence),
                    'WS_steps':counts['WEIGHTED_SUM'],'BORDA_steps':counts['BORDA'],
                    'operator_switches':1,'switch_step_zero_based':switch_step,'switch_progress':switch_step/len(sequence),
                    'boundary_changes_action':boundary_changed,'first_action_diff_vs_WS_step':first_vs_ws,
                    'first_action_diff_vs_BORDA_step':first_vs_borda,
                    'initial_policy_prefix_verified':True,
                    'same_physical_WS':row['physical_schedule_sha256']==base_rows['WS'][name]['physical_schedule_sha256'],
                    'same_physical_BORDA':row['physical_schedule_sha256']==base_rows['BORDA'][name]['physical_schedule_sha256']})
                stats['WS_steps']+=counts['WEIGHTED_SUM'];stats['BORDA_steps']+=counts['BORDA']
                stats['switches']+=1;stats['adjacent_decision_pairs']+=len(sequence)-1
                stats['boundary_action_changes']+=bool(boundary_changed)
            mechanism.append({'strategy':spec['id'],**dict(stats),
                'switch_rate_per_adjacent_decisions':stats['switches']/stats['adjacent_decision_pairs'] if stats['adjacent_decision_pairs'] else None})
            if result and result['valid']:
                for role in baselines:
                    differences=[r['score']-base_rows[role][r['file']]['score'] for r in result['instances']]
                    comparisons.append({'strategy':spec['id'],'baseline':role,'delta_F':fmean(differences),
                        'wins':sum(x>0 for x in differences),'losses':sum(x<0 for x in differences),'ties':sum(x==0 for x in differences),
                        'same_physical_instances':sum(r['physical_schedule_sha256']==base_rows[role][r['file']]['physical_schedule_sha256'] for r in result['instances']),
                        'Cmax_sum':sum(r['makespan'] for r in result['instances'])})
            if folder.exists():
                life=v2.read(folder/'lifecycle.json');boundary=v2.read(folder/'boundary.json')
                boundary_rows.append({'strategy':spec['id'],'decision':boundary['decision'],'exitcode':life['exitcode'],
                    'alive':life['alive'],'exit_grace_used':life['exit_grace_used'],
                    'exit_wait_seconds':life['exit_wait_observed_seconds'],'trigger':life['trigger']})
                for path in folder.glob('*'):
                    artifacts[str(path.relative_to(directory))]={'sha256':v2.sha(path),'bytes':path.stat().st_size}
                    if path.name in ('result.json','raw_result.json','before.json','after.json','lifecycle.json','boundary.json','network_guard.json'):
                        (out/'raw'/(spec['id']+'__'+path.name)).write_bytes(path.read_bytes())
    if len(instance_rows)!=126:raise ValueError('all126 rows including failures required')
    progress=[v2.read(path) for path in (directory/'evidence').glob('*/*.progress.json')]
    passes=sum(r['first_started']+r['recheck_started'] for r in progress)
    if passes>252 or len(progress)>126:raise ValueError('observed budget exceeded')
    valid_dynamic=[r for r in rankings if r['status']=='valid'];improved=[r for r in valid_dynamic if r['delta_F_vs_WS']>0]
    best=max(valid_dynamic,key=lambda r:r['fitness']) if valid_dynamic else None
    physical_groups=defaultdict(list);physical_pairwise=[]
    for identifier,result in all_results.items():
        if result['valid']:physical_groups[digest([r['physical_schedule_sha256'] for r in result['instances']])].append(identifier)
    for a,b in itertools.combinations(all_results,2):
        if all_results[a]['valid'] and all_results[b]['valid']:
            physical_pairwise.append({'strategy_a':a,'strategy_b':b,'same_physical_instances':sum(
                x['physical_schedule_sha256']==y['physical_schedule_sha256'] for x,y in zip(all_results[a]['instances'],all_results[b]['instances']))})
    contribution_rows=[]
    if best:
        for row in all_results[best['strategy']]['instances']:
            delta=row['score']-base_rows['WS'][row['file']]['score']
            contribution_rows.append({'strategy':best['strategy'],'file':row['file'],'delta_F_instance':delta,
                'contribution_to_full_delta_F':delta/21,'delta_Cmax':row['makespan']-base_rows['WS'][row['file']]['makespan']})
        contribution_rows.sort(key=lambda r:r['contribution_to_full_delta_F'],reverse=True)
    costs={'reserved_evaluations':sum(r['reserved_evaluations'] for r in checkpoint['strategies'].values()),
        'first_solves_started':sum(r['first_started'] for r in progress),'rechecks_started':sum(r['recheck_started'] for r in progress),
        'completed_pairs':sum(r['completed'] for r in progress),'API_requests':0,'additional_H_calls':0,'additional_diagnostic_solves':0,
        'primary_wall_seconds':sum(r['primary_evaluation_seconds'] for k,r in all_results.items() if not k.startswith('FIXED_')),
        'recorded_CPU_seconds':sum(r['CPU_seconds'] for r in cost_rows),'recorded_H_calls':sum(r['H_calls_two_passes'] for r in cost_rows),
        'post_result_exit_wait_seconds':sum(r['exit_wait_seconds'] for r in boundary_rows),
        'raw_matrix_bytes':sum(path.stat().st_size for path in (directory/'evidence').glob('*/*.trace.jsonl.gz')),
        'timing_scope':'first pass records states, recheck does not; grace only after final complete row; historical times nonconcurrent'}
    summary={'phase':checkpoint['phase'],'protocol_sha256':v2.sha(directory/'Protocol.json'),'rankings':rankings,
        'comparisons':comparisons,'operator_mechanism':mechanism,'best_dynamic':best,
        'dynamic_strategies_better_than_WS':len(improved),'valid_dynamic_strategies':len(valid_dynamic),
        'physical_groups':list(physical_groups.values()),'costs':costs,
        'scientific_scope':'six predeclared progress-only schedules, single fixed H and train21; no independent generalization or LLM efficacy claim'}
    atomic_json(out/'Summary.json',summary);atomic_json(out/'Artifact_index.json',{'run_directory':str(directory),'files':artifacts})
    atomic_json(out/'Baseline_sources.json',{'baselines':p['fixed_baselines'],'traces':artifact_sources,'new_baseline_solves':0})
    for name in ('Protocol.json','Protocol.sha256','checkpoint.json','Expected_loaded_identity.json','H_frozen.json'):
        (out/name).write_bytes((directory/name).read_bytes())
    if (directory/'Stop.json').exists():(out/'Stop.json').write_bytes((directory/'Stop.json').read_bytes())
    v2.csv_write(out/'Ranking.csv',rankings);v2.csv_write(out/'All_instances_126.csv',instance_rows)
    v2.csv_write(out/'Comparisons.csv',comparisons);v2.csv_write(out/'Switch_instances.csv',switch_rows)
    v2.csv_write(out/'Mechanism_summary.csv',mechanism);v2.csv_write(out/'Cost_breakdown.csv',cost_rows)
    v2.csv_write(out/'Lifecycle_results.csv',boundary_rows);v2.csv_write(out/'Physical_pairwise.csv',physical_pairwise)
    v2.csv_write(out/'Best_contributions.csv',contribution_rows)
    fmt=lambda value:f'{value:.12f}' if value is not None else 'null'
    lines=['# Fusion V4：进度相关WS/Borda切换最小实验', '',
        '## 生命周期修复与边界', '',
        'V3旧异常已回传全部结果、before/after一致、没有poll超时；join(0.05)后仍存活，被terminate为−15。具体退出延迟来源未知，不能追认旧结果。',
        '新收集器保持每实例poll(15)不变；只有全部期望结果收齐后，才单独join最多2秒等待正常退出。该阶段不再接收成绩，不延长任何尚未完成结果的15秒期限。',
        '超时/错误仍用原0.05秒清理等待及terminate/kill；正常结果必须exit0、进程确认不存活、前后加载身份与完整文件边界匹配。2秒后仍存活或退出异常均停止。',
        '真实spawn Mock在回传后固定延迟0.25秒：旧收集器退出−15，新收集器正常exit0。另测试poll15、超时无宽限、异常退出、缺身份、未知终态、持久化失败和预算未知预留。详见Lifecycle_acceptance.json及Offline_tests.json。',
        '旧源码、V3 Stop/checkpoint及H0/H5隔离证据均绑定哈希、保持不变；没有重评或追认。', '',
        '## 冻结科学方案', '',
        '只用H0/H1，0.5/0.5；原WS和原始分数并列平均秩Borda不变，原七状态/动作合法性/同分/LB/Fitness不变。',
        '两方向WS→Borda与Borda→WS，各阈值0.25、0.50、0.75，共6策略；progress<threshold用前算子，等于或超过用后算子。',
        '这是预先指定的进度阶段日程，不是已学习的工作负载响应规则；不新增状态、算子、阈值、LLM请求或U演化。固定基线引用已认证旧WS及H01 Borda，零基线重评。', '',
        '## 完整训练结果', '', '| 策略 | Fitness | 相对固定WS | 相对固定Borda |', '|---|---:|---:|---:|']
    for r in sorted(rankings,key=lambda r:r['fitness'] if r['fitness'] is not None else -float('inf'),reverse=True):
        lines.append(f"| {r['strategy']} | {fmt(r['fitness'])} | {fmt(r['delta_F_vs_WS'])} | {fmt(r['delta_F_vs_BORDA'])} |")
    lines+=['',f"有效动态策略{len(valid_dynamic)}/6，超过固定WS的策略数为{len(improved)}。全部126行逐实例结果/失败null见All_instances_126.csv。", '',
        '| 策略 | 对固定WS胜/负/平 | 同物理排程实例 |', '|---|---|---:|']
    for r in comparisons:
        if r['baseline']=='WS':lines.append(f"| {r['strategy']} | {r['wins']}/{r['losses']}/{r['ties']} | {r['same_physical_instances']} |")
    lines+=['', '## 实际算子访问及动作变化', '', '| 策略 | WS步数 | Borda步数 | 实际切换 | 边界动作改变实例 | 相同状态下相对WS不同动作 |', '|---|---:|---:|---:|---:|---:|']
    for r in mechanism:lines.append(f"| {r['strategy']} | {r.get('WS_steps',0)} | {r.get('BORDA_steps',0)} | {r.get('switches',0)} | {r.get('boundary_action_changes',0)} | {r.get('changed_vs_WS',0)} |")
    lines+=['', '每步从完整同一物理状态/同一评分矩阵重组WS与Borda，核对已执行算子的分数和动作逐步一致。切换次数不含每个实例首步初始化；频率以实例内相邻决策对为分母。',
        'Switch_instances.csv包含每实例首次算子切换、边界是否改变动作、与两固定策略首次动作分歧；前段与其固定算子完整提交序列共享前缀已核验。',
        '这些事实能定位策略介入的时间和哪些实例贡献均值变化，不能把某一步局部动作差异直接归因为最终makespan收益；未进行额外受控续排。',
        f"包含固定基线的完整训练物理行为组数：{len(physical_groups)}；逐对一致数见Physical_pairwise.csv。", '',
        '## 收益来源与下一阶段', '']
    if best:
        lines += [f"训练内最佳动态策略为{best['strategy']}，ΔF相对WS为{fmt(best['delta_F_vs_WS'])}；这是6个预定策略比较后的训练最优，不是独立验证冠军。",
                  'Best_contributions.csv逐实例列出归一化增益对总ΔF的贡献，保留改善与退化实例；不是重定义Fitness或筛选实例。']
    if improved:
        lines += ['存在训练内改善，值得进入预先冻结的后续等预算A/B小试；本轮不自动调用LLM。',
            '建议A为WS-only程序空间（允许相同状态相关权重），B为同一WS空间加Borda算子选择；固定H与初始强WS基线，模型/上下文信息、生成尝试和FJSP评价上限、选择规则相同。',
            '比较超过共同初始冠军的增量、失败/重复/完整有效数、API与评价成本；预先固定搜索重复种子和选择规则。两臂都允许常量，不能强制B必须切换以制造结构差异。',
            '在新的未参与开发数据上另做冻结验证；已有test28不再充当全新确认集。搜索收益不能由本轮进度规则代替证明。']
    else:
        lines += ['六个简单策略没有建立超过固定WS的证据，暂缓LLM动态算子演化；不增加阈值、条件或新算子追分。',
                  '若后续仍研究该空间，应先形成新的机制假设与预先冻结的等预算对照，本轮不追加任何评价。']
    lines+=['', '## 成本、异常与证据边界', '',f'`{costs}`',
        '原始矩阵保存独立runs，Artifact_index.json给出哈希；报告raw保存原始结果、源码身份与进程回执。耗时包括首解留证，历史基线非同期；不把生命周期修复当算法质量创新。',
        'train21已参与开发；单H集合、单seed、6个预先指定策略的结果不证明普遍优势、动态切换必需或LLM搜索有效。所有门禁及预算维持；未知状态不得自动补评。', '',
        '## 复现', '', '详见Commands.md；先accept与离线验收，再prepare/check/run/report。新协议不能覆盖旧目录，已完成或未知预留不能重评。']
    (out/'REPORT_ZH.md').write_text('\n'.join(lines)+'\n');batch.check(directory)
    return {'phase':checkpoint['phase'],'valid_dynamic':len(valid_dynamic),'better_than_WS':len(improved),'best':best,'costs':costs}
