"""Reports saved certified progress rules. Never starts an evaluation."""
import csv
from datetime import datetime
import json
from pathlib import Path
from statistics import fmean
import tarfile
from zoneinfo import ZoneInfo


def csv_save(path, rows):
    if not rows: return
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n'); w.writeheader()
        for row in rows:
            w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()})


def comparison(rows, reference):
    if not rows: return None
    changes=[a['makespan']-b['makespan'] for a,b in zip(rows,reference['instances'])]
    return {'W':sum(v<0 for v in changes),'L':sum(v>0 for v in changes),'T':sum(v==0 for v in changes),
            'delta_F':fmean(r['score'] for r in rows)-reference['fitness'],
            'sum_Cmax_delta':sum(changes)}


def report():
    from tools import h01_progress_baseline as b
    run,out=b.RUN,b.REPORT;out.mkdir(exist_ok=True)
    p=b.check();state=b.read(run/'checkpoint.json');b.ledger(state,p)
    specs=b.read(run/'Rules.json');equal=b.read(run/p['cache']['STATIC_a050']['result_path'])
    b2=b.read(run/'references/B2_champion.json')['result']
    ranking=[];instances=[];behavior=[];new_results=[];all_results={};raw=[]
    for spec in specs:
        id=spec['id'];entry=state['strategies'].get(id)
        r=b.read(run/entry['result_path']) if entry and entry['status']=='completed' else None
        valid=bool(r and r['valid']);all_results[id]=r
        row={k:spec[k] for k in ('id','tau','alpha_before','alpha_after','dynamic')}
        row.update(status=entry['status'] if entry else 'not_started',valid=valid,
            origin=entry.get('origin') if entry else None,fitness=r['fitness'] if valid else None,
            completed_instances=len(r['instances']) if r else 0,failed_instance=r.get('failed_instance') if r else None,
            error_type=r.get('error_type') if r else None,delta_equal=None,delta_B2=None,
            W_equal=None,L_equal=None,T_equal=None,W_B2=None,L_B2=None,T_B2=None,
            sum_Cmax=None,first_seconds=None,recheck_seconds=None,primary_seconds=None,
            result_source=p['cache'][id]['source'] if id in p['cache'] else str((run/entry['result_path']).relative_to(b.ROOT)) if r else None)
        if r:
            if entry['origin']=='new':new_results.append(r)
            if valid:
                a=comparison(r['instances'],equal);c=comparison(r['instances'],b2)
                row.update(delta_equal=a['delta_F'],delta_B2=c['delta_F'],W_equal=a['W'],L_equal=a['L'],T_equal=a['T'],
                    W_B2=c['W'],L_B2=c['L'],T_B2=c['T'],sum_Cmax=sum(x['makespan'] for x in r['instances']),
                    first_seconds=sum(x['single_solve_seconds'] for x in r['instances']),
                    recheck_seconds=sum(x['deterministic_recheck_seconds'] for x in r['instances']),
                    primary_seconds=r['primary_evaluation_seconds'])
            for actual,e,z in zip(r['instances'],equal['instances'],b2['instances']):
                instances.append({'id':id,'origin':entry['origin'],'file':actual['file'],'Cmax':actual['makespan'],
                    'LB':actual['lower_bound'],'score':actual['score'],'equal_Cmax':e['makespan'],'B2_Cmax':z['makespan'],
                    'raw_Cmax_delta_equal':actual['makespan']-e['makespan'],
                    'delta_F_contribution_equal':(e['makespan']-actual['makespan'])/(21*actual['lower_bound']),
                    'raw_Cmax_delta_B2':actual['makespan']-z['makespan'],
                    'delta_F_contribution_B2':(z['makespan']-actual['makespan'])/(21*actual['lower_bound']),
                    'physical_sha256':actual['physical_schedule_sha256'],
                    'physical_equal_equal':actual['physical_schedule_sha256']==e['physical_schedule_sha256'],
                    'physical_equal_B2':actual['physical_schedule_sha256']==z['physical_schedule_sha256'],
                    'first_seconds':actual['single_solve_seconds'],'recheck_seconds':actual['deterministic_recheck_seconds']})
                if 'observed_progress_H0_H1' in actual:
                    samples=actual['observed_progress_H0_H1'];n=len(samples)
                    if actual['progress_weights_sha256']!=b.digest(samples) or actual['recheck_progress_weights_sha256']!=b.digest(samples):raise ValueError('behavior recheck hash')
                    if spec['dynamic']:
                        if actual['before_steps']+actual['after_steps']!=n or min(actual['before_steps'],actual['after_steps'])<1 or actual['actual_weight_changes']!=1:
                            raise ValueError('threshold not reached/exact switch missing')
                    behavior.append({'id':id,'file':actual['file'],'operations':n,'min_progress':samples[0][0],
                        'max_progress':samples[-1][0],'before_steps':actual['before_steps'],'after_steps':actual['after_steps'],
                        'actual_weight_changes':actual['actual_weight_changes'],'weights_before':[samples[0][1],samples[0][2]],
                        'weights_after':[samples[-1][1],samples[-1][2]],'passive_same_two_solves':True})
        ranking.append(row)
    order={r['id']:i for i,r in enumerate(specs)}
    ranked=sorted(ranking,key=lambda r:(r['fitness'] is None,-r['fitness'] if r['fitness'] is not None else 0,order[r['id']]))
    csv_save(out/'All_rules.csv',ranking);csv_save(out/'Ranking.csv',ranked)
    csv_save(out/'Per_instance.csv',instances);csv_save(out/'Behavior.csv',behavior)
    dynamic=[r for r in ranked if r['dynamic'] and r['valid']];best=dynamic[0] if dynamic else None
    groups={}
    for id,r in all_results.items():
        if r and r['valid']:
            key=b.digest([x['physical_schedule_sha256'] for x in r['instances']]);groups.setdefault(key,[]).append(id)
    b.write(out/'Physical_equivalence.json',{'groups':groups,'scope':'same physical schedules on train21 only; not universal U equivalence'})
    phases=[b.read(f) for f in (run/'evidence').glob('*/*.progress.json')]
    started_first=sum(bool(r.get('first_started')) for r in phases);started_recheck=sum(bool(r.get('recheck_started')) for r in phases)
    clock=b.read(run/'Run_clock.json') if (run/'Run_clock.json').exists() else None
    end=b.read(run/'End_summary.json') if (run/'End_summary.json').exists() else None
    wall=end['end']['wall']-clock['start']['wall'] if end and clock else None
    summary={'phase':state['phase'],'family_27':27,'canonical_strategies':21,'dynamic_rules':18,
        'completed_strategies':sum(r['status']=='completed' for r in ranking),'valid':sum(r['valid'] for r in ranking),
        'cache_strategies':sum(r['origin']=='cache' for r in ranking),'new_evaluations':len(new_results),
        'reserved_program_instances':sum(r['reserved_instances'] for r in state['strategies'].values()),
        'reserved_solve_passes':sum(r['reserved_solves'] for r in state['strategies'].values()),
        'actual_first_starts':started_first,'actual_recheck_starts':started_recheck,'actual_solve_starts':started_first+started_recheck,
        'invalid_new_strategies':sum(not r['valid'] for r in new_results),'API':0,'holdout':0,
        'dynamic_exceed_equal':sum(r['delta_equal']>0 for r in dynamic),
        'dynamic_equal_equal':sum(r['delta_equal']==0 for r in dynamic),
        'dynamic_exceed_B2':sum(r['delta_B2']>0 for r in dynamic),'best_dynamic':best,
        'equal_fitness':equal['fitness'],'historical_B2_fitness':b2['fitness'],
        'new_successful_first_seconds':sum(x['single_solve_seconds'] for r in new_results for x in r['instances']),
        'new_successful_recheck_seconds':sum(x['deterministic_recheck_seconds'] for r in new_results for x in r['instances']),
        'new_primary_seconds':sum(r['primary_evaluation_seconds'] for r in new_results),'wall_seconds':wall,
        'protocol_sha256':b.sha(run/'Protocol.json'),'physical_groups':len(groups),
        'dynamic_instance_behavior_rows':sum(r['id'].startswith('T') for r in behavior)}
    b.write(out/'Summary.json',summary)
    lines=['# H0/H1简单动态权重：正式结果','','完整扫描预先限定的27参数组合、去重21策略（18动态＋3静态）。结果只评价训练内策略质量，不比较搜索效率。','',
        f"终态：{state['phase']}；认证有效{summary['valid']}/21；动态超过等权{summary['dynamic_exceed_equal']}/18、持平{summary['dynamic_equal_equal']}/18、超过历史B2 {summary['dynamic_exceed_B2']}/18。",'',
        '|策略|tau|H0前→后|Fitness|Δ等权|Δ历史B2|对等权胜/负/平|来源|','|---|---:|---|---:|---:|---:|---|---|']
    fmt=lambda x:'null' if x is None else f'{x:.12f}'
    for r in ranked:
        lines.append(f"|{r['id']}|{r['tau']}|{r['alpha_before']}→{r['alpha_after']}|{fmt(r['fitness'])}|{fmt(r['delta_equal'])}|{fmt(r['delta_B2'])}|{r['W_equal']}/{r['L_equal']}/{r['T_equal']}|{r['origin']}|")
    if best:
        lines+=['','## 最佳预定动态规则', '',f"{best['id']}：p<{best['tau']}时H0={best['alpha_before']}，否则H0={best['alpha_after']}；H1始终为1−H0。Fitness={best['fitness']:.12f}。",
                f"对等权ΔFitness={best['delta_equal']:+.12f}，{best['W_equal']}胜{best['L_equal']}负{best['T_equal']}平；对历史B2 {best['W_B2']}胜{best['L_B2']}负{best['T_B2']}平，ΔFitness={best['delta_B2']:+.12f}。",'',
                '逐实例贡献定义为(C_ref−C_rule)/(21×LB)，越大越好；原始Cmax增量正值为退化。两种度量不能互相替代。','',
                '|实例|规则Cmax|等权Cmax|原始ΔCmax|ΔFitness贡献|','|---|---:|---:|---:|---:|']
        selected=[r for r in instances if r['id']==best['id']]
        for x in sorted(selected,key=lambda r:r['delta_F_contribution_equal'],reverse=True):
            lines.append(f"|{x['file']}|{x['Cmax']}|{x['equal_Cmax']}|{x['raw_Cmax_delta_equal']:+d}|{x['delta_F_contribution_equal']:+.12f}|")
        positive=sum(x['delta_F_contribution_equal'] for x in selected if x['delta_F_contribution_equal']>0)
        top=sorted([x for x in selected if x['delta_F_contribution_equal']>0],key=lambda r:-r['delta_F_contribution_equal'])[:3]
        lines+=['',f"正向贡献总和{positive:.12f}；前三个正贡献实例占正向贡献{sum(x['delta_F_contribution_equal'] for x in top)/positive:.2%}。该比例以总正贡献为分母，不是净改善的比例。" if positive else '没有正向实例贡献。']
    lines+=['','## 身份、行为与成本','',
        'H、train21及内核与历史B2源码pins一致；进度为已调度工序数／总数。七输入、LB未取整、合法动作、归一化、同分与Fitness定义保持一致；N5是历史种群规模，本批固定策略评价无种群选择。',
        '每个动态策略的21实例，使用原首解／复检中的实际U调用被动记录progress和权重；Behavior.csv复核阈值前后均访问、每实例恰好一次权重变化。没有额外诊断求解。',
        'H0和等权复用现代T30源身份、双解与正常退出证据；H1历史原生复检缺同级终态回执，独立新评，历史记录未改。',
        '历史B2为T15包装，本批T30完整接收＋全结果后2秒正常退出；B2科学内核与数据一致，但缺同等级现代生命周期回执，不称同期认证／成本公平对照。B2仅作保存完整成绩的历史质量参照。',
        f"新增{summary['new_evaluations']}策略，预留{summary['reserved_program_instances']}项／{summary['reserved_solve_passes']}遍；实际启动首解{started_first}、复检{started_recheck}。缓存2策略不重复求解；API=0，留出=0。",
        f"成功实例首解{summary['new_successful_first_seconds']:.3f}秒、复检{summary['new_successful_recheck_seconds']:.3f}秒；新策略父进程评价区间合计{summary['new_primary_seconds']:.3f}秒；campaign墙钟{wall if wall is not None else '尚未结束'}秒。父进程区间已含求解、IPC和退出等待，不再重复相加。",
        f"无效新增策略{summary['invalid_new_strategies']}；实际行为记录{summary['dynamic_instance_behavior_rows']}条动态策略—实例；完整物理排程分组{summary['physical_groups']}。未完成或隔离结果不计算完整Fitness。",'',
        '## 证据边界与文件','',
        '本族由已知强H0/H1与限定阈值/权重构成，并从train21扫描选优，包含先验与选择成本，不是零成本人工策略、不代表动态空间最优，也不支持泛化或搜索效率结论。无论成绩如何，不追加规则。',
        'All_rules.csv与Ranking.csv包含全部策略和来源；Per_instance.csv包含完整Cmax、LB和贡献；Behavior.csv包含跨阈值统计；Physical_equivalence.json只描述已观察train21物理排程。',
        f"冻结协议SHA：{summary['protocol_sha256']}。运行配置、Authorization、Rules、Aliases、checkpoint、End_summary及逐策略身份／终态／原始结果在runs/{b.NAME}/；原始归档与SHA索引保存到本报告目录。",'',
        '复现入口见docs/H01_PROGRESS_STEP_PROTOCOL_V1.md。report只整理已有证据；不要重新prepare、launch或重跑已完成策略。']
    (out/'REPORT_ZH.md').write_text('\n'.join(lines)+'\n')
    # End summary is durable before this report; archive only settled run evidence.
    if end:
        files=[f for f in sorted(run.rglob('*')) if f.is_file()]
        manifest={str(f.relative_to(b.ROOT)):{'sha256':b.sha(f),'bytes':f.stat().st_size} for f in files}
        archive=out/'Raw_execution_evidence.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            for f in files:tar.add(f,arcname=str(f.relative_to(b.ROOT)),recursive=False)
        import hashlib
        with tarfile.open(archive,'r:gz') as tar:
            for entry in tar.getmembers():
                data=tar.extractfile(entry).read()
                if hashlib.sha256(data).hexdigest()!=manifest[entry.name]['sha256']:raise ValueError('archive roundtrip mismatch')
        b.write(out/'Raw_evidence_manifest.json',{'archive':archive.name,'archive_sha256':b.sha(archive),'files':manifest})
    return summary
