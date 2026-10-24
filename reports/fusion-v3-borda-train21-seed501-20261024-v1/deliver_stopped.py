"""Read-only experiment finalization after strict process-exit stop.

Never changes the run checkpoint/protocol/source/ledger. Only completed,
boundary-accepted results enter official quality tables. Quarantine raw rows of
the stopped strategy without adopting their mean or spending remaining budget.
"""
from collections import Counter,defaultdict
import csv
import gzip
import json
import math
from pathlib import Path
import random
from statistics import fmean

from fjsp_usage.fusion_v3.ranking import borda_scores,borda_twice,ws_certificate
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from tools import fusion_v3_experiment as batch


def order_metrics(raw,support):
    points,_=borda_scores(raw,support)
    weights=tuple(.5 if i in support else 0. for i in range(max(support)+1))
    ws,_=batch.v2.fuse_scores(raw,weights,support,'WEIGHTED_SUM')
    r=borda_twice(points);s=borda_twice(ws);mr=fmean(r);ms=fmean(s)
    vr=sum((x-mr)**2 for x in r);vs=sum((y-ms)**2 for y in s)
    rho=sum((x-mr)*(y-ms) for x,y in zip(r,s))/math.sqrt(vr*vs) if vr and vs else None
    return {'weak_order_equal':r==s,'spearman':rho,
        'mean_absolute_percentile_rank_diff':fmean(abs(x-y) for x,y in zip(r,s))/(2*max(1,len(r)-1)),
        'Borda_unique_top':sum(x==max(points) for x in points)==1}


def main():
    out=Path(__file__).resolve().parent;run=batch.ROOT/'runs'/out.name
    p=batch.check(run);v2=batch.v2;checkpoint=v2.read(run/'checkpoint.json');stop=v2.read(run/'Stop.json')
    assert stop['error']=='V3 boundary stop: unexpected_worker_exit'
    assert checkpoint['strategies']['H0_H5_BORDA']['status']=='reserved'
    assert 'H5_H9_BORDA' not in checkpoint['strategies']
    frozen_paths=[run/'Protocol.json',run/'Protocol.sha256',run/'checkpoint.json',run/'Stop.json']
    frozen_before={str(path):v2.sha(path) for path in frozen_paths}
    accepted={};raw_unaccepted={};status={}
    for spec in batch.specs():
        record=checkpoint['strategies'].get(spec['id']);folder=run/'evidence'/spec['id']
        if record and record['status']=='completed':
            path=run/record['result_path'];assert v2.sha(path)==record['result_sha256']
            result=v2.read(path);v2.validate_rows(result['instances'],p)
            v2.check_result(result,[r['file'] for r in p['instances']])
            assert result['valid'] and result['boundary']['decision']=='original_result_checks_required'
            life=v2.read(folder/'lifecycle.json');assert life['exitcode']==0 and life['alive'] is False
            assert v2.read(folder/'before.json')['identity']==v2.read(folder/'after.json')['identity']
            accepted[spec['id']]=result;status[spec['id']]='certified_complete21'
        elif record:
            boundary=v2.read(folder/'boundary.json');life=v2.read(folder/'lifecycle.json')
            assert boundary['decision']=='stop' and boundary['reason']=='unexpected_worker_exit'
            assert life['trigger'] is None and life['exitcode']==-15 and life['alive'] is False
            assert v2.read(folder/'before.json')['identity']==v2.read(folder/'after.json')['identity']
            raw_unaccepted[spec['id']]=v2.read(folder/'raw_result.json')
            status[spec['id']]='quarantined_unexpected_worker_exit'
        else:status[spec['id']]='not_started_after_stop'
    refs=v2.read(run/'References.json');base_h0={r['file']:r for r in refs['H0']['training_result']['instances']}
    base_equal={r['file']:r for r in refs['H01_equal']['training_result']['instances']}
    rankings=[];rows=[];quarantine=[];comparisons=[];cost_rows=[]
    for spec in batch.specs():
        identifier=spec['id'];result=accepted.get(identifier);pair=spec['pair']
        oldid=f'H{pair[0]}_H{pair[1]}_WEIGHTED_SUM'
        binding=p['history'][oldid];assert v2.sha(batch.ROOT/binding['path'])==binding['sha256']
        old=v2.read(batch.ROOT/binding['path']);oldrows={r['file']:r for r in old['instances']}
        newrows={r['file']:r for r in result['instances']} if result else {}
        rankings.append({'strategy':identifier,'status':status[identifier],
            'official_fitness':result['fitness'] if result else None,
            'same_pair_WS_fitness':old['fitness'] if old['valid'] else None,
            'official_delta_F_vs_WS':result['fitness']-old['fitness'] if result and old['valid'] else None,
            'official_delta_F_vs_H0':result['fitness']-refs['H0']['fitness'] if result else None,
            'official_delta_F_vs_H01_equal':result['fitness']-refs['H01_equal']['fitness'] if result else None})
        if result and old['valid']:
            diffs=[newrows[n]['score']-oldrows[n]['score'] for n in newrows]
            comparisons.append({'strategy':identifier,'comparison':oldid,'instances':len(diffs),
                'delta_F':result['fitness']-old['fitness'],'wins':sum(x>0 for x in diffs),
                'losses':sum(x<0 for x in diffs),'ties':sum(x==0 for x in diffs),
                'same_physical_instances':sum(newrows[n]['physical_schedule_sha256']==oldrows[n]['physical_schedule_sha256'] for n in newrows)})
        for expected in p['instances']:
            n=expected['file'];new=newrows.get(n);oldrow=oldrows.get(n)
            rows.append({'strategy':identifier,'file':n,'candidate_status':status[identifier],
                'Cmax':new['makespan'] if new else None,'LB':expected['LB'],'score':new['score'] if new else None,
                'historical_WS_Cmax':oldrow['makespan'] if oldrow else None,'historical_WS_complete':old['valid'],
                'delta_Cmax_vs_WS':new['makespan']-oldrow['makespan'] if new and oldrow else None,
                'delta_F_vs_WS':new['score']-oldrow['score'] if new and oldrow else None,
                'delta_F_vs_H0':new['score']-base_h0[n]['score'] if new else None,
                'delta_F_vs_H01_equal':new['score']-base_equal[n]['score'] if new else None,
                'physical_schedule_sha256':new['physical_schedule_sha256'] if new else None})
        raw=raw_unaccepted.get(identifier) or result
        if raw:
            for row in raw['instances']:
                cost_rows.append({'strategy':identifier,'file':row['file'],'officially_accepted':bool(result),
                    'first_seconds':row['single_solve_seconds'],'recheck_seconds':row['deterministic_recheck_seconds'],
                    'CPU_seconds':row['instance_CPU_seconds'],
                    'first_H_seconds':row['first_costs']['h_scoring_seconds'],
                    'first_fusion_seconds':row['first_costs']['fusion_seconds'],
                    'recheck_H_seconds':row['recheck_costs']['h_scoring_seconds'],
                    'recheck_fusion_seconds':row['recheck_costs']['fusion_seconds'],
                    'peak_RSS_native_units':row['peak_RSS_native_units'],
                    'H_calls_two_passes':sum(row['single_h_calls'])+sum(row['recheck_h_calls'])})
                if not result:quarantine.append({'strategy':identifier,'file':row['file'],
                    'raw_Cmax':row['makespan'],'raw_LB':row['lower_bound'],'raw_score':row['score'],
                    'officially_accepted':False,'reason':'unexpected_worker_exit; no official quality aggregation'})
    assert len(rows)==63 and sum(r['Cmax'] is not None for r in rows)==21
    v2.csv_write(out/'Ranking.csv',rankings);v2.csv_write(out/'All_instances_63.csv',rows)
    v2.csv_write(out/'Comparisons.csv',comparisons);v2.csv_write(out/'Quarantined_raw_instances.csv',quarantine)
    v2.csv_write(out/'Cost_breakdown.csv',cost_rows)
    behavior=[];new_samples=[]
    with gzip.open(out/'Accepted_state_actions.csv.gz','wt',encoding='utf-8') as stream:
        fields=['strategy','file','step','state_sha256','BORDA_action','WS_action','MAX_action','MIN_action','BORDA_top_ties','WS_top_ties','MAX_top_ties','MIN_top_ties']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for identifier,result in accepted.items():
            stats=Counter();reservoir=[];rng=random.Random(501)
            for row in result['instances']:
                path=run/row['trace_path'];assert v2.sha(path)==row['trace_sha256']
                with gzip.open(path,'rt',encoding='utf-8') as handle:
                    for trace in map(json.loads,handle):
                        assert digest(trace['physical_state'])==trace['state_sha256']
                        support=tuple(trace['support']);raw={int(i):tuple(c) for i,c in trace['columns'].items()}
                        points,_=borda_scores(raw,support);chosen=max(range(len(points)),key=points.__getitem__)
                        assert list(points)==trace['scores'] and chosen==trace['winner']
                        decisions={};ties={}
                        for op in v2.OPERATORS:
                            scores,info=v2.fuse_scores(raw,trace['weights'],support,op)
                            decisions[op]=max(range(len(scores)),key=scores.__getitem__);ties[op]=sum(x==scores[decisions[op]] for x in scores)
                            norm=info['normalized'];stats['BORDA_diff_'+op]+=chosen!=decisions[op]
                            stats[op+'_tied_states']+=ties[op]>1
                        stats['states']+=1;stats['BORDA_tied_states']+=sum(x==points[chosen] for x in points)>1
                        entry={'strategy':identifier,'file':row['file'],'step':trace['step'],
                            'state_sha256':trace['state_sha256'],'raw':raw,'normalized':norm,'support':support,'target':chosen}
                        if len(reservoir)<64:reservoir.append(entry)
                        else:
                            k=rng.randrange(stats['states'])
                            if k<64:reservoir[k]=entry
                        writer.writerow({'strategy':identifier,'file':row['file'],'step':trace['step'],'state_sha256':trace['state_sha256'],
                            'BORDA_action':chosen,'WS_action':decisions['WEIGHTED_SUM'],'MAX_action':decisions['MAX'],'MIN_action':decisions['MIN'],
                            'BORDA_top_ties':sum(x==points[chosen] for x in points),'WS_top_ties':ties['WEIGHTED_SUM'],
                            'MAX_top_ties':ties['MAX'],'MIN_top_ties':ties['MIN']})
            behavior.append({'strategy':identifier,**dict(stats)})
            for entry in reservoir:new_samples.append(dict(entry,certificate=ws_certificate(entry['raw'],entry['normalized'],entry['support'],entry['target'])))
    with gzip.open(out/'Exact_WS_accepted_samples.jsonl.gz','wt',encoding='utf-8') as handle:
        for entry in new_samples:handle.write(json.dumps(entry,separators=(',',':'))+'\n')
    v2.csv_write(out/'Accepted_state_summary.csv',behavior)
    samples=[]
    with gzip.open(batch.DIAGNOSIS/'Exact_WS_samples.jsonl.gz','rt') as handle:samples.extend(('V2_reference',json.loads(line)) for line in handle)
    samples.extend(('accepted_Borda',entry) for entry in new_samples)
    sample_rows=[]
    for phase,entry in samples:
        raw={int(i):tuple(c) for i,c in entry['raw'].items()};support=tuple(entry['support'])
        sample_rows.append({'phase':phase,'pair':'/'.join(map(str,support)),'file':entry['file'],'step':entry['step'],
            'state_sha256':entry['state_sha256'],'certificate':entry['certificate']['status'],**order_metrics(raw,support)})
    v2.csv_write(out/'Sample_order_analysis.csv',sample_rows)
    order_summary=[]
    for phase,pair in sorted({(r['phase'],r['pair']) for r in sample_rows}):
        group=[r for r in sample_rows if (r['phase'],r['pair'])==(phase,pair)];rho=[r['spearman'] for r in group if r['spearman'] is not None]
        order_summary.append({'phase':phase,'pair':pair,'sample_n':len(group),
            'equal_full_weak_order':sum(r['weak_order_equal'] for r in group),
            'mean_spearman':fmean(rho) if rho else None,'spearman_defined_n':len(rho),
            'outside_real_WS':sum(r['certificate']=='outside_real_linear_WS' for r in group),
            'outside_WS_unique_Borda_top':sum(r['certificate']=='outside_real_linear_WS' and r['Borda_unique_top'] for r in group)})
    v2.csv_write(out/'Sample_order_summary.csv',order_summary)
    progress=[v2.read(f) for f in (run/'evidence').glob('*/*.progress.json')]
    first=sum(r['first_started'] for r in progress);second=sum(r['recheck_started'] for r in progress)
    assert first==second==42 and first+second<=126
    costs={'reserved_evaluations':42,'reserved_passes':84,'started_first_solves':first,'started_rechecks':second,
        'result_pairs_recorded':sum(r['completed'] for r in progress),'certified_evaluations':21,
        'quarantined_evaluations':21,'unstarted_evaluations':21,'API_requests':0,'extra_diagnostic_solves':0,'extra_H_calls':0,
        'parent_primary_wall_seconds':sum(r['primary_evaluation_seconds'] for r in list(accepted.values())+list(raw_unaccepted.values())),
        'recorded_CPU_seconds':sum(r['CPU_seconds'] for r in cost_rows),
        'recorded_H_calls':sum(r['H_calls_two_passes'] for r in cost_rows),
        'raw_matrix_bytes':sum(f.stat().st_size for f in (run/'evidence').glob('*/*.trace.jsonl.gz')),
        'boundary':'recorded cost includes quarantined strategy; its quality is NOT certified; no additional budget spent after stop'}
    out_raw=out/'raw';out_raw.mkdir(exist_ok=True)
    artifacts={}
    for path in (run/'evidence').glob('*/*'):
        if path.is_file():
            artifacts[str(path.relative_to(run))]={'sha256':v2.sha(path),'bytes':path.stat().st_size}
            if path.name in ('result.json','raw_result.json','before.json','after.json','boundary.json','lifecycle.json','network_guard.json'):
                (out_raw/(path.parent.name+'__'+path.name)).write_bytes(path.read_bytes())
    for name in ('Protocol.json','Protocol.sha256','Stop.json','checkpoint.json','H_frozen.json','Expected_loaded_identity.json','References.json'):
        (out/name).write_bytes((run/name).read_bytes())
    audit={'protocol_sha256':v2.sha(run/'Protocol.json'),'analysis_sha256':v2.sha(__file__),
        'formal_phase':'stopped_by_boundary','new_solves_in_report':0,'new_API_requests':0,
        'official_rankings':rankings,'comparisons':comparisons,'accepted_state_behavior':behavior,
        'sample_order_summary':order_summary,'costs':costs,'stop':stop,
        'source_and_original_asset_check':'PASS','original_checkpoint_preserved':True,
        'recommendation':'暂缓纳入主U空间；保留Borda独立机制实现。局部表达能力不同，但唯一认证的H01固定策略不及强等权WS；MAX/MIN亦无新质量证据。'}
    atomic_json(out/'Final_audit.json',audit);atomic_json(out/'Artifact_index.json',{'run_directory':str(run),'files':artifacts})
    assert {str(path):v2.sha(path) for path in frozen_paths}==frozen_before
    batch.check(run)
    # Report is intentionally self-contained. Never call the normal completed-only reporter.
    lines=['# Tier 2 Fusion V3：Borda机制验证与安全停止报告', '',
        '**结论：Borda确实增加了相对分数加权和的局部决策能力，但当前证据不足以支持加入主U搜索空间，建议暂缓。** 唯一完整认证的H0/H1固定Borda不及强等权WS；第二策略异常终态触发停止，第三策略未运行。', '',
        '## 固定方案与定义', '',
        '唯一新增机制为两成员等权并列平均秩Borda。对原始有限H动作评分：`B(a)=严格更小分数的动作数+(同分动作数−1)/2`；最终取`2B0+2B1`最大动作。整数实现与等权平均百分位秩argmax等价，避免人为浮点秩并列。',
        '每列真实并列用平均秩，不按动作编号拆并列；最终同分保留原合法动作枚举首项。常量列为动作无关偏移，单动作计0。Rank Sum/Borda只是方向和仿射记分不同，不拆成两个算子。',
        '正式三策略在运行前固定为H0/H1、H0/H5、H5/H9；均不含阈值、可调秩权重、随机破同分或新状态。保留H、train21、seed501、未取整LB、mean(-Cmax/LB)、原同分规则和15秒期限。',
        '独立模块fusion_v3保留可信callable接口；旧算子在新模块中委托V2数学实现。原V1/V2源码及任何旧实验/账本未修改。本轮未扩LLM闭合AST、未演化U。', '',
        '## 阶段A：已有V2矩阵证据', '', '| 成员对 | 去重状态 | Borda≠等权WS | Borda顶端并列 | MAX顶端并列 |', '|---|---:|---:|---:|---:|',
        '| H0/H1 | 11346 | 6643 | 1273 | 11140 |', '| H0/H5 | 9571 | 3689 | 1080 | 8858 |', '| H5/H9 | 9328 | 3552 | 2085 | 8594 |', '',
        '所有31200个状态出现/30245个去重状态均由同一完整物理状态和全部动作评分重组，不是比较不同轨迹的动作频率。H5相关V2矩阵只覆盖成功的前20实例，用于行为而非完整质量。',
        '每对固定seed501 reservoir64的样本，Borda动作在保存归一化列上无法由任何非负实数线性WS首选的状态分别为27/16/8；其中Borda顶端唯一的分别为25/10/6，故差异不只是最终破并列。',
        '证书使用Fraction精确不等式，考虑稳定首项的严格同分约束；端点保留原始SELECT分数，内部可表达者还核对实际WS alpha见证。不可表达结论针对保存浮点值上的实数线性组合，不声称穷尽所有IEEE执行。',
        'WS已有min–max，因此正仿射评分尺度不是本轮待修复缺陷；Borda改变分数间距的影响，对不产生新并列的保序变换不变。把归一化分数平方会改变WS首选：三对分别3371/1034/575个去重状态。',
        '直接原始秩与先min–max后秩的Borda首选分别有11/2/0个状态不同，体现浮点归一化合并秩。因此预先固定对原始分数求秩。MAX仍大量顶端同分；V2两例浮点反例保留，MIN旧H01完整结果仍无收益。', '',
        '## 验收与正式质量结果', '',
        '64项测试/Mock/回归通过：数学和边界、V1/V2状态/动作/完整排程兼容、重复求解、真实子进程身份、严格超时分类、网络/非训练集保护、未知预留阻止启动。证据见Offline_acceptance.json。', '',
        '| 策略 | 正式train21 Fitness | 状态 |', '|---|---:|---|',
        '| H0/H1 BORDA | −2.066904716328 | 完整21实例认证 |',
        '| H0/H5 BORDA | null | 21实例原始结果隔离，异常进程终态未接受 |',
        '| H5/H9 BORDA | null | 停止后未启动 |', '',
        'H0/H1 Borda相对等权WS（−1.983144294915）：ΔF=−0.083760421413，1胜/18负/2平，21实例物理排程全部不同。相对H0为+0.044900244298；相对MAX约+0.006790767109，但这不能替代与强WS的比较。',
        'All_instances_63.csv保留全部63行，只有21行有认证Cmax/score。隔离策略的逐实例原始记录在Quarantined_raw_instances.csv，明确不接受为质量证据；不重算其均值或排行。', '',
        '## 安全门禁停止：不是算法超时', '',
        'H0/H5已回传21个实例，before/after加载身份匹配，父poll没有超时；但在既有join(0.05)后子进程仍存活，收集器执行terminate，最终exitcode=−15、alive=false。',
        '严格分类为unexpected_worker_exit，正式运行写Stop.json并停止；这是“正常结果必须exit0”的门禁，不可改记成功或确认超时。源码身份未失配，进程已确认终止。',
        '退出延迟可能来自求解后的清理，但日志没有足够证据认证具体原因。本轮不修改join期限、不放宽15秒、不重评、不解除预留、不启动第三策略。',
        '原checkpoint保留phase=running及第二策略reserved，Stop.json为终态解释；报告不把账本重写为completed。未来任何收集器改动须新协议、Mock验收及剩余预算审查，不能自动重置额度。', '',
        '## 已认证新轨迹的同状态行为与全排序', '', '| 策略 | 状态数 | Borda≠WS | Borda顶端并列 | WS顶端并列 |', '|---|---:|---:|---:|---:|']
    for r in behavior:lines.append(f"| {r['strategy']} | {r['states']} | {r['BORDA_diff_WEIGHTED_SUM']} | {r['BORDA_tied_states']} | {r['WEIGHTED_SUM_tied_states']} |")
    lines+=['', 'Sample_order_summary.csv在阶段A固定192状态与认证新轨迹固定64状态上比较完整弱序和并列平均秩Spearman；恒定排序相关系数记null，不补零。', '',
        '| 样本来源 | 成员对 | 样本数 | 完整弱序相同 | 平均Spearman | 不可实数WS表达 |', '|---|---|---:|---:|---:|---:|']
    for r in order_summary:lines.append(f"| {r['phase']} | {r['pair']} | {r['sample_n']} | {r['equal_full_weak_order']} | {r['mean_spearman']} | {r['outside_real_WS']} |")
    lines+=['', '这些样本不按收益挑选，也不代表全体状态分布。动作与完整排序不同只表示表达机制不同，不能推出完整排程收益或动态选择价值。', '',
        '## 成本与复现', '',f'`{costs}`',
        '共预留42项/84遍，实际首解42遍、复检42遍；21项认证、21项隔离、21项未启动。无真实API、无额外诊断求解/H调用，无超时重评。',
        'Cost_breakdown.csv明确区分认证与隔离资源记录；首解含状态/矩阵留证，复检无轨迹，历史耗时非同期，不据此证明复杂度优势。峰值RSS单位在macOS为字节。',
        '原始矩阵保留独立runs，Artifact_index.json给出哈希；Git报告保留原始结果/身份/生命周期、抽样评分与证书、逐状态决策表。', '',
        '## 最终建议及证据边界', '',
        '暂缓Borda纳入主U搜索空间，保留独立机制实现。它有超出分数线性融合的真实局部决策证据，且不是单纯更换H01权重；但唯一认证固定策略的训练质量劣于强WS，当前不能以扩大表达空间推断收益。',
        'MAX暂不优先：顶端同分大量依赖原枚举规则；MIN保留机制支线，但原H01完整质量亦不支持替换WS。未来若研究动态算子选择，须同预算WS-only对照，不能由固定策略或动作差异直接归因。',
        'H5相关新策略未获完整认证，跨成员对一致性未知。本轮train21仅为已暴露开发集，无独立泛化结论，无新LLM搜索或动态U有效性证据。', '',
        '本报告由deliver_stopped.py生成，只读冻结运行记录，无新增求解。原协议与停止门禁保持原样。详细复现及安全停止说明见Commands.md。']
    (out/'REPORT_ZH.md').write_text('\n'.join(lines)+'\n')
    print({'official_rankings':rankings,'behavior':behavior,'orders':order_summary,'costs':costs})


if __name__=='__main__':main()
