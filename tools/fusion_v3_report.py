"""Derived report from frozen Borda and V2 records; never solves schedules."""
from collections import Counter,defaultdict
import gzip
import itertools
import json
from pathlib import Path

from fjsp_usage.fusion_v3.ranking import borda_scores,ws_certificate
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from tools import fusion_v2_experiment as v2


def report(directory):
    from tools import fusion_v3_experiment as batch
    p=batch.check(directory);checkpoint=v2.read(directory/'checkpoint.json')
    if checkpoint['phase']!='completed':raise ValueError('report requires all frozen strategies terminal')
    out=v2.ROOT/'reports'/directory.name;out.mkdir(exist_ok=True);(out/'raw').mkdir(exist_ok=True)
    ref=v2.read(directory/'References.json')
    h0={r['file']:r for r in ref['H0']['training_result']['instances']}
    h01={r['file']:r for r in ref['H01_equal']['training_result']['instances']}
    rankings=[];instance_rows=[];comparisons=[];behavior=[];cost_rows=[];artifacts={};all_physical={}
    new_certificates=[]
    with gzip.open(out/'New_state_actions.csv.gz','wt',encoding='utf-8') as stream:
        import csv
        fields=['strategy','file','step','state_sha256','BORDA_action','WS_action','MAX_action','MIN_action',
                'BORDA_top_ties','WS_top_ties','MAX_top_ties','MIN_top_ties']
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for spec in batch.specs():
            saved=checkpoint['strategies'][spec['id']];path=directory/saved['result_path']
            if v2.sha(path)!=saved['result_sha256']:raise ValueError('saved V3 result changed')
            result=v2.read(path);v2.validate_rows(result['instances'],p);v2.check_result(result,[r['file'] for r in p['instances']])
            pair=spec['pair'];base=f'H{pair[0]}_H{pair[1]}_';ws_binding=p['history'][base+'WEIGHTED_SUM']
            if v2.sha(v2.ROOT/ws_binding['path'])!=ws_binding['sha256']:raise ValueError('WS reference changed')
            ws=v2.read(v2.ROOT/ws_binding['path']);new={r['file']:r for r in result['instances']};old={r['file']:r for r in ws['instances']}
            rankings.append({'strategy':spec['id'],'pair':'/'.join(map(str,pair)),'valid':result['valid'],
                'fitness':result['fitness'],'completed_instances':len(new),'error_type':result.get('error_type'),
                'failed_instance':result.get('failed_instance'),'historical_WS_valid':ws['valid'],'historical_WS_fitness':ws['fitness'],
                'delta_F_vs_pair_WS':result['fitness']-ws['fitness'] if result['valid'] and ws['valid'] else None,
                'delta_F_vs_H0':result['fitness']-ref['H0']['fitness'] if result['valid'] else None,
                'delta_F_vs_H01_equal':result['fitness']-ref['H01_equal']['fitness'] if result['valid'] else None,
                'primary_wall_seconds':result['primary_evaluation_seconds']})
            common=[n for n in new if n in old];diffs=[new[n]['score']-old[n]['score'] for n in common]
            comparisons.append({'strategy':spec['id'],'comparison':'same-pair historical WS',
                'paired_instances':len(common),'both_complete21':result['valid'] and ws['valid'],
                'full_delta_F':result['fitness']-ws['fitness'] if result['valid'] and ws['valid'] else None,
                'wins':sum(d>0 for d in diffs),'losses':sum(d<0 for d in diffs),'ties':sum(d==0 for d in diffs),
                'same_physical_instances':sum(new[n]['physical_schedule_sha256']==old[n]['physical_schedule_sha256'] for n in common),
                'scope':'complete train21' if result['valid'] and ws['valid'] else 'successful common prefix only; no prefix mean'})
            stats=Counter();seen=set();reservoir=[];import random
            rng=random.Random(501);unique=0
            for expected in p['instances']:
                name=expected['file'];row=new.get(name);wsrow=old.get(name)
                instance_rows.append({'strategy':spec['id'],'file':name,'candidate_valid':result['valid'],
                    'instance_status':'complete_pair' if row else result.get('error_type','not_completed'),
                    'Cmax':row['makespan'] if row else None,'LB':expected['LB'],'score':row['score'] if row else None,
                    'WS_Cmax':wsrow['makespan'] if wsrow else None,'WS_candidate_valid':ws['valid'],
                    'delta_Cmax_vs_WS':row['makespan']-wsrow['makespan'] if row and wsrow else None,
                    'delta_F_vs_WS':row['score']-wsrow['score'] if row and wsrow else None,
                    'delta_F_vs_H0':row['score']-h0[name]['score'] if row else None,
                    'delta_F_vs_H01_equal':row['score']-h01[name]['score'] if row else None,
                    'single_seconds':row['single_solve_seconds'] if row else None,
                    'recheck_seconds':row['deterministic_recheck_seconds'] if row else None,
                    'error_type':None if row else result.get('error_type'),
                    'physical_schedule_sha256':row['physical_schedule_sha256'] if row else None})
                if not row:continue
                cost_rows.append({'strategy':spec['id'],'file':name,'CPU_seconds':row['instance_CPU_seconds'],
                    'first_H_seconds':row['first_costs']['h_scoring_seconds'],'first_fusion_seconds':row['first_costs']['fusion_seconds'],
                    'recheck_H_seconds':row['recheck_costs']['h_scoring_seconds'],'recheck_fusion_seconds':row['recheck_costs']['fusion_seconds'],
                    'peak_RSS_native_units':row['peak_RSS_native_units'],
                    'H_calls_two_passes':sum(row['single_h_calls'])+sum(row['recheck_h_calls'])})
                trace_path=directory/row['trace_path']
                if v2.sha(trace_path)!=row['trace_sha256']:raise ValueError('new trajectory changed')
                with gzip.open(trace_path,'rt',encoding='utf-8') as handle:
                    for trace in map(json.loads,handle):
                        if digest(trace['physical_state'])!=trace['state_sha256']:raise ValueError('new state digest mismatch')
                        raw={int(i):tuple(c) for i,c in trace['columns'].items()};support=tuple(trace['support'])
                        points,ranks=borda_scores(raw,support);chosen=max(range(len(points)),key=points.__getitem__)
                        if list(points)!=trace['scores'] or chosen!=trace['winner']:raise ValueError('Borda replay differs')
                        decisions={};ties={};norm=None
                        for op in v2.OPERATORS:
                            scores,info=v2.fuse_scores(raw,trace['weights'],support,op)
                            decisions[op]=max(range(len(scores)),key=scores.__getitem__)
                            ties[op]=sum(x==scores[decisions[op]] for x in scores);norm=info['normalized']
                        if (name,trace['state_sha256']) in seen:continue
                        seen.add((name,trace['state_sha256']));unique+=1
                        entry={'strategy':spec['id'],'file':name,'step':trace['step'],'state_sha256':trace['state_sha256'],
                            'raw':raw,'normalized':norm,'support':support,'target':chosen}
                        if len(reservoir)<64:reservoir.append(entry)
                        else:
                            k=rng.randrange(unique)
                            if k<64:reservoir[k]=entry
                        stats['states']+=1;stats['BORDA_tied_states']+=sum(x==points[chosen] for x in points)>1
                        for op in v2.OPERATORS:
                            stats['BORDA_diff_'+op]+=chosen!=decisions[op];stats[op+'_tied_states']+=ties[op]>1
                        writer.writerow({'strategy':spec['id'],'file':name,'step':trace['step'],'state_sha256':trace['state_sha256'],
                            'BORDA_action':chosen,'WS_action':decisions['WEIGHTED_SUM'],'MAX_action':decisions['MAX'],
                            'MIN_action':decisions['MIN'],'BORDA_top_ties':sum(x==points[chosen] for x in points),
                            'WS_top_ties':ties['WEIGHTED_SUM'],'MAX_top_ties':ties['MAX'],'MIN_top_ties':ties['MIN']})
            behavior.append({'strategy':spec['id'],**dict(stats)})
            for entry in reservoir:
                new_certificates.append(dict(entry,certificate=ws_certificate(entry['raw'],entry['normalized'],entry['support'],entry['target'])))
            if result['valid']:all_physical[spec['id']]=[r['physical_schedule_sha256'] for r in result['instances']]
            for name in ('result.json','before.json','after.json','lifecycle.json','boundary.json','network_guard.json'):
                source=path.parent/name
                if source.exists():(out/'raw'/(spec['id']+'__'+name)).write_bytes(source.read_bytes())
            for source in sorted(path.parent.glob('*')):
                artifacts[str(source.relative_to(directory))]={'sha256':v2.sha(source),'bytes':source.stat().st_size}
    if len(instance_rows)!=63:raise ValueError('expected exact63 rows including nulls')
    progress=[v2.read(f) for f in (directory/'evidence').glob('*/*.progress.json')]
    passes=sum(r.get('first_started',False)+r.get('recheck_started',False) for r in progress)
    if passes>126 or len(progress)>63:raise ValueError('observed budget exceeded')
    with gzip.open(out/'Exact_WS_new_samples.jsonl.gz','wt',encoding='utf-8') as handle:
        for entry in new_certificates:handle.write(json.dumps(entry,separators=(',',':'))+'\n')
    cert_counts={s['id']:dict(Counter(e['certificate']['status'] for e in new_certificates if e['strategy']==s['id'])) for s in batch.specs()}
    costs={'reserved_evaluations':sum(r['reserved_evaluations'] for r in checkpoint['strategies'].values()),
        'started_first_solves':sum(r['first_started'] for r in progress),'started_rechecks':sum(r['recheck_started'] for r in progress),
        'completed_pairs':sum(r['completed'] for r in progress),'API_requests':0,'additional_diagnostic_solves':0,
        'additional_diagnostic_H_calls':0,'primary_wall_seconds':sum(r['primary_wall_seconds'] for r in rankings),
        'certified_CPU_seconds':sum(r['CPU_seconds'] for r in cost_rows),
        'certified_H_calls':sum(r['H_calls_two_passes'] for r in cost_rows),
        'raw_trace_bytes':sum(f.stat().st_size for f in (directory/'evidence').glob('*/*.trace.jsonl.gz')),
        'failed_details':'uncertified CPU/H-call costs unknown; failed progress preserves whether first completed',
        'timing':'traced first solve, untraced recheck, same15s parent acceptance including serialization; historical nonconcurrent times descriptive only'}
    diagnosis=v2.read(batch.DIAGNOSIS/'Diagnosis.json')
    summary={'version':p['version'],'protocol_sha256':v2.sha(directory/'Protocol.json'),'phase':checkpoint['phase'],
        'rankings':rankings,'comparisons':comparisons,'new_state_behavior':behavior,'new_sample_WS_certificates':cert_counts,
        'costs':costs,'new_full_physical_groups':list({digest(v):[k for k,w in all_physical.items() if w==v] for v in all_physical.values()}.values()),
        'selection_diagnosis':'diagnosis/Diagnosis.json','boundary':'train21 feasibility; no LLM discovery, no generalization or mechanism-causal claim'}
    atomic_json(out/'Summary.json',summary);atomic_json(out/'Protocol.json',p)
    atomic_json(out/'Artifact_index.json',{'run_directory':str(directory),'files':artifacts})
    v2.csv_write(out/'Ranking.csv',rankings);v2.csv_write(out/'All_instances_63.csv',instance_rows)
    v2.csv_write(out/'Comparisons.csv',comparisons);v2.csv_write(out/'New_state_summary.csv',behavior);v2.csv_write(out/'Cost_breakdown.csv',cost_rows)
    (out/'H_frozen.json').write_bytes((directory/'H_frozen.json').read_bytes())
    lines=['# Tier 2 Fusion V3：等权并列平均秩 Borda 可行性', '',
        '## 决策与预先定义', '',
        '本轮只新增BORDA一种机制；Rank Sum/Borda仅方向或正比例记分不同，不作为两个算子。',
        '两列原始有限H评分分别按升序计算B(a)=严格更低分动作数+(同分动作数−1)/2；合计两成员的B点数，越大越好。',
        '实现用整数2B点数之和，等价于等权平均百分位秩；每列常量贡献共同偏移，单动作为0。原始分数精确相等才并列，不加epsilon。',
        '最终同分沿用原合法动作枚举首项。BORDA恰用两个等值正支持指示项，历史成员取小编号；没有不等秩权重、状态新增或破同分改动。',
        '冻结三成员对H0/H1、H0/H5、H5/H9，train21、seed501、LB/Fitness、15秒期限和复检规范不变。代码为独立fusion_v3，V1/V2及账本未修改。', '',
        '## 阶段A：已有矩阵诊断', '', '| 成员对 | 去重状态 | Borda≠等权WS | Borda顶端并列 | MAX顶端并列 |', '|---|---:|---:|---:|---:|']
    for r in diagnosis['summaries']:
        if r['source']=='UNION_DEDUPLICATED':lines.append(f"| {r['pair']} | {r['states']} | {r['BORDA_diff_WS']} | {r['BORDA_tied_states']} | {r['MAX_tied_states']} |")
    lines+=['',f"每对固定seed501抽样64状态的精确WS证书计数：`{diagnosis['sample_WS_certificate_counts']}`。",
        '精确证书用Fraction对保存的归一化浮点值作实数线性不等式检查，并考虑先出现动作的严格破同分条件；单成员端点按原始分数单独核对。',
        '存在实数不可表达动作不等于穷举所有IEEE执行；可表达者另用冻结WS实现核对具体alpha见证。样本不按质量或差异筛选，不能把抽样比例外推到所有状态。',
        'WS的min–max已消除正仿射尺度差；Borda改变的是分数间距敏感性，对保序变换在不引入新浮点并列时不变。',
        '原始秩与先min–max再求秩的首选在H01/H05/H59分别有11/2/0个去重状态不同，故本轮明确冻结先对原始分数求秩。',
        'MAX仍有大量顶端同分，V2两例归一化舍入反例保留；MIN有不同局部动作，但旧H01完整评价未显示收益。', '',
        '## 新固定策略完整结果', '', '| 策略 | 完整Fitness | 同对WS完整Fitness | ΔF | 完成实例 |', '|---|---:|---:|---:|---:|']
    fmt=lambda v:f'{v:.12f}' if v is not None else 'null'
    for r in rankings:lines.append(f"| {r['strategy']} | {fmt(r['fitness'])} | {fmt(r['historical_WS_fitness'])} | {fmt(r['delta_F_vs_pair_WS'])} | {r['completed_instances']}/21 |")
    lines+=['', 'All_instances_63.csv保留全部63行，含失败null；无效候选禁止前缀Fitness均值。', '',
        '| 策略 | 配对覆盖 | 胜/负/平 | 相同物理排程 | 证据范围 |','|---|---:|---|---:|---|']
    for r in comparisons:lines.append(f"| {r['strategy']} | {r['paired_instances']} | {r['wins']}/{r['losses']}/{r['ties']} | {r['same_physical_instances']} | {r['scope']} |")
    lines+=['', '历史WS未完成21的成员对，即使新Borda完整，也不能生成同对完整ΔFitness或称全21优越；共同成功前缀只作描述性逐实例比较。', '',
        '## 新轨迹的相同状态证据', '', '| 策略 | 状态 | Borda≠WS | Borda顶端并列 |','|---|---:|---:|---:|']
    for r in behavior:lines.append(f"| {r['strategy']} | {r['states']} | {r.get('BORDA_diff_WEIGHTED_SUM',0)} | {r.get('BORDA_tied_states',0)} |")
    valid=[r for r in rankings if r['valid']]
    strong_improvements=[r for r in valid if r['delta_F_vs_H01_equal']>0]
    if strong_improvements:
        recommendation='保留Borda作为可选研究算子：至少一个完整固定策略在当前train21超过已知H01等权基线；仍需同预算WS-only与WS+BORDA的U搜索对照，不能仅凭本轮称动态算子或LLM搜索有效。'
    elif valid:
        recommendation='暂缓将Borda加入主U搜索空间，保留独立研究实现：已有结构和动作差异证据，但完整候选没有超越已知H01等权强基线，单纯扩大空间尚无收益依据。'
    else:
        recommendation='暂缓加入主U搜索空间：完整策略均未认证，当前只能报告离线决策能力；先研究在固定评价期限内的可执行性，不能以部分结果选优。'
    summary['recommendation']=recommendation
    atomic_json(out/'Summary.json',summary)
    lines+=['',f'新轨迹固定抽样64状态/策略的证书：`{cert_counts}`。',
        '该诊断在完整物理状态、全部合法动作和相同原始评分矩阵上比较，而非比较不同轨迹的动作频率。局部动作不同及不可线性表达不等于完整排程收益。', '',
        '## 成本、异常、证据边界', '',f'`{costs}`',
        '每实例首解/复检各最多一次，超时不重评；缺少结束身份只有经独立分类证实起始身份、源文件前后不变、父等待触发与已终止退出码才记无效继续，未知情况停止。',
        '旧V2参考结果通过来源协议/结果SHA256绑定；新旧计时非同时且首解包含留证开销，不以此证明算法复杂度优势。',
        'train21是已暴露开发集。本轮无真实LLM请求、无U演化、不访问validation11/test28，不声称独立泛化、动态利用或LLM搜索有效。', '',
        '## 建议', '',recommendation,
        'MAX不因与等权动作不同就优先纳入；其大量顶端并列与浮点秩合并需要解释。MIN可保留机制支线，但旧完整H01结果不支持质量收益。本轮没有改变二者或新增第二种机制。', '',
        '## 复现', '', '```bash',
        'PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v3/run.py prepare --run-dir runs/新目录',
        'PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v3/run.py check --run-dir runs/新目录',
        'PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v3/run.py run --run-dir runs/新目录',
        'PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v3/run.py report --run-dir runs/新目录',
        '```', '原始矩阵在独立runs/evidence中；Artifact_index.json提供哈希。诊断原始列/精确证书样本和压缩逐状态表保留在reports。']
    (out/'REPORT_ZH.md').write_text('\n'.join(lines)+'\n')
    batch.check(directory)
    return {'phase':checkpoint['phase'],'rankings':rankings,'costs':costs}
