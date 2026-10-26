"""Offline fixed-confirmation analysis; no API or scheduling entry points."""
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random
from statistics import fmean
import tarfile
from zoneinfo import ZoneInfo

from tools import h01_external_confirm as c


def csv_save(name,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with (c.REPORT/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys,lineterminator='\n');w.writeheader();w.writerows(rows)


def quantile(values,p):
    q=(len(values)-1)*p;lo=int(q);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(q-lo)


def bootstrap(rows):
    rng=random.Random(2026102618);layers=[[r['ratio_gain'] for r in rows if r['stratum']==layer] for layer in range(3)]
    samples=sorted(sum(sum(rng.choice(layer) for _ in layer) for layer in layers if layer)/len(rows) for _ in range(20000))
    return [quantile(samples,.025),quantile(samples,.975)]


def report():
    p=c.check();s=c.read(c.RUN/'checkpoint.json');c.ledger(s,p);c.REPORT.mkdir(exist_ok=True)
    plan=c.read(c.RUN/'Tasks.json');data=c.read(c.RUN/'Data_manifest.json');n=len(p['instances'])
    table=[];details=[];received={};firsts=rechecks=0;elapsed=0.
    for task in plan:
        t=s['tasks'].get(task['task_id']);spec=p['instances'][task['instance_index']]
        row={**task,'jobs':spec['jobs'],'machines':spec['machines'],'operations':spec['operations'],'LB':spec['LB'],
             'stratum':spec['stratum'],'status':'unstarted','valid':False,'Cmax':None,'score':None}
        if t:
            row['status']=t['status']
            folder=c.RUN/'evaluations'/task['task_id']
            for phase in folder.glob('*.progress.json'):
                progress=c.read(phase);firsts+=bool(progress.get('first_started'));rechecks+=bool(progress.get('recheck_started'))
            if t['status']=='completed':
                result=c.read(c.RUN/t['result_path']);life=c.read(folder/'lifecycle.json')
                expected={**p['source_files'],**p['protected_files']}
                boundary=c.old.certified.certify(result,dict(before=c.read(folder/'before.json'),
                    after=c.read(folder/'after.json') if (folder/'after.json').exists() else None,lifecycle=life,
                    expected_identity=c.read(c.RUN/'Expected_solver_identity.json')['identity'],expected_files=expected,
                    start_files=expected,end_files=expected,worker_failure=(folder/'worker_failure.json').exists()))
                assert boundary==result['boundary']==c.read(folder/'boundary.json')
                elapsed+=result['primary_evaluation_seconds'];row.update(valid=result['valid'],error_type=result.get('error_type'),
                    boundary=boundary['reason'],primary_seconds=result['primary_evaluation_seconds'],exitcode=life['exitcode'],
                    first_recheck_count=sum(a['captured_solves'] for a in result['instances']))
                if result['valid']:
                    r=result['instances'][0];received[(task['file'],task['policy'])]=r
                    row.update(Cmax=r['makespan'],score=r['score'],first_seconds=r['single_solve_seconds'],
                        recheck_seconds=r['deterministic_recheck_seconds'],physical_schedule_sha256=r['physical_schedule_sha256'],
                        H0_dominant_steps=r['member_usage']['dominant_counts'][0],H1_dominant_steps=r['member_usage']['dominant_counts'][1],
                        first_recheck_match=r['physical_schedule_sha256']==r['recheck_physical_schedule_sha256'])
        table.append(row)
    assert firsts+rechecks<=80 and len(s['tasks'])<=40
    fits={}
    for policy in ('dynamic','equal'):
        own=[r for r in table if r['policy']==policy]
        fits[policy]=fmean(r['score'] for r in own) if len(own)==n and all(r['valid'] for r in own) else None
    full=all(v is not None for v in fits.values())
    for spec in p['instances']:
        a=received.get((spec['file'],'dynamic'));b=received.get((spec['file'],'equal'))
        row={'file':spec['file'],'stratum':spec['stratum'],'jobs':spec['jobs'],'machines':spec['machines'],
             'operations':spec['operations'],'LB':spec['LB'],'both_valid':a is not None and b is not None}
        if a is not None and b is not None:
            gain=(b['makespan']-a['makespan'])/spec['LB']
            row.update(dynamic_Cmax=a['makespan'],equal_Cmax=b['makespan'],delta_Cmax=a['makespan']-b['makespan'],
                ratio_gain=gain,delta_F_contribution=gain/n,physical_same=a['physical_schedule_sha256']==b['physical_schedule_sha256'],
                winner='dynamic' if gain>0 else 'equal' if gain<0 else 'tie')
        details.append(row)
    summary={'phase':s['phase'],'selected_instances':n,'planned_program_instances':2*n,'consumed_program_instances':len(s['tasks']),
        'first_starts':firsts,'recheck_starts':rechecks,'total_solve_starts':firsts+rechecks,
        'complete_fitness':fits,'full_confirmation_valid':full,'API_calls':0,'tokens':0,'API_cost':0,
        'evaluation_parent_seconds':elapsed,'protocol_sha256':c.sha(c.RUN/'Protocol.json'),
        'source_commit':data['source_commit'],'distribution':data['distribution'],'selection_seed':data['selection_seed']}
    summary['known_first_construct_seconds']=sum(r.get('first_seconds',0) for r in table)
    summary['known_recheck_construct_seconds']=sum(r.get('recheck_seconds',0) for r in table)
    if (c.RUN/'Run_clock.json').exists() and (c.RUN/'End_summary.json').exists():
        clock=c.read(c.RUN/'Run_clock.json');end=c.read(c.RUN/'End_summary.json')
        summary['campaign_wall_seconds']=end['end']['wall']-clock['start']['wall']
    if full:
        delta=fits['dynamic']-fits['equal'];assert abs(delta-fmean(r['ratio_gain'] for r in details))<1e-13
        positive=sorted((r for r in details if r['ratio_gain']>0),key=lambda r:-r['ratio_gain'])
        negative=sorted((r for r in details if r['ratio_gain']<0),key=lambda r:r['ratio_gain'])
        gross=sum(r['delta_F_contribution'] for r in positive)
        gross_loss=-sum(r['delta_F_contribution'] for r in negative)
        summary.update(delta_F=delta,relative_mean_Cmax_LB_improvement_percent=delta/(-fits['equal'])*100,
            wins=sum(r['ratio_gain']>0 for r in details),losses=sum(r['ratio_gain']<0 for r in details),ties=sum(r['ratio_gain']==0 for r in details),
            dynamic_Cmax_sum=sum(r['dynamic_Cmax'] for r in details),equal_Cmax_sum=sum(r['equal_Cmax'] for r in details),
            gross_positive_F=gross,gross_negative_F=sum(r['delta_F_contribution'] for r in details if r['ratio_gain']<0),
            top1_share_of_gross_positive=positive[0]['delta_F_contribution']/gross if gross else None,
            top3_share_of_gross_positive=sum(r['delta_F_contribution'] for r in positive[:3])/gross if gross else None,
            top1_share_of_gross_negative=-negative[0]['delta_F_contribution']/gross_loss if gross_loss else None,
            top3_share_of_gross_negative=-sum(r['delta_F_contribution'] for r in negative[:3])/gross_loss if gross_loss else None,
            largest_normalized_gain=max(details,key=lambda r:r['ratio_gain']),largest_normalized_loss=min(details,key=lambda r:r['ratio_gain']),
            largest_raw_gain=min(details,key=lambda r:r['delta_Cmax']),largest_raw_loss=max(details,key=lambda r:r['delta_Cmax']),
            same_physical_count=sum(r['physical_same'] for r in details),stratified_bootstrap_95=bootstrap(details))
    csv_save('All_task_results.csv',table);csv_save('Paired_instance_results.csv',details)
    csv_save('Frozen_selected_instances.csv',data['instances']);c.write(c.REPORT/'Summary.json',summary)
    for name in ('Protocol.json','Protocol.sha256','Authorization.json','Policies.json','H_frozen.json','Data_manifest.json',
                 'Data_history.json','Tasks.json','Expected_solver_identity.json','Expected_controller_identity.json',
                 'checkpoint.json','Run_clock.json','Run_identity.json','Launch_identity.json','End_summary.json','Stop.json'):
        if (c.RUN/name).exists():(c.REPORT/name).write_bytes((c.RUN/name).read_bytes())
    proof=c.REPORT/'Frozen_U';proof.mkdir(exist_ok=True)
    policies=c.read(c.RUN/'Policies.json')
    for name,value in policies.items():(proof/(name+'.py')).write_text(value['code'])
    write_report(summary,table,details)
    files=[f for f in sorted(c.RUN.rglob('*')) if f.is_file()]
    manifest={str(f.relative_to(c.ROOT)):{'sha256':c.sha(f),'bytes':f.stat().st_size} for f in files}
    archive=c.REPORT/'Raw_evidence.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for f in files:tar.add(f,arcname=str(f.relative_to(c.ROOT)),recursive=False)
    with tarfile.open(archive,'r:gz') as tar:
        for entry in tar:
            assert hashlib.sha256(tar.extractfile(entry).read()).hexdigest()==manifest[entry.name]['sha256']
    assert all(c.sha(c.ROOT/name)==row['sha256'] for name,row in manifest.items())
    c.write(c.REPORT/'Raw_manifest.json',{'files':manifest,'archive_sha256':c.sha(archive),
        'archive_roundtrip_verified':True,'inputs_unchanged_during_pack':True})
    print({'phase':summary['phase'],'full':full,'fitness':fits,'delta_F':summary.get('delta_F'),'solves':firsts+rechecks})


def write_report(s,tasks,rows):
    lines=['# 冻结新冠军：训练外固定质量验证','',
        (f"**固定确认已完成：动态U相对等权ΔFitness={s['delta_F']:+.12f}，{s['wins']}胜、{s['losses']}负、{s['ties']}平。**" if s['full_confirmation_valid'] else '**固定确认未获得完整有效对照，不使用成功前缀替代。**'),'',
        '本轮只评价r2_EVO_s16与原H0/H1等权P0，没有生成API、策略修改、开发选优或旧campaign续跑。所有抽样、主指标及失败规则先冻结，结果不用于重新选择冠军。','',
        '## 数据与身份','',
        f"来源为SchedulingLab/fjsp-instances提交`{s['source_commit']}`的Hurink rdata LA01–LA40，MIT许可。40例均通过txt/json逐操作交叉核对、格式无损转换、独立LB复算及内容去重；固定seed{s['selection_seed']}，50–100/101–200/201–300工序三层配额7/7/6，冻结选中{s['selected_instances']}例。清单见Frozen_selected_instances.csv。",
        '全部为标准FJSP。机器5–15，训练Behnke机器20/40/60；加工时间结构和基准生成机制也不同。因此这是跨基准族及尺寸迁移，不能单独归因为尺度影响，也不能称同分布验证。',
        '旧train21/validation11/test28全部排除；原Behnke60只读取用于内容去重，没有旧留出求解或成绩选样。在命名H/B2/IND/EVO协议及本地实例库存中未发现本池曾用于当前开发/选择。此为可审计的项目记录范围，不保证未登记人工/项目外使用或LLM预训练无暴露。源仓库提醒应参照原文；本轮认证的是所固定公开版本的数学一致性，不声称重新认证原作者全部数据。',
        '冠军源码SHA256为09feca48812d404116b018cf26832490a20fc9d622f2e01a9870016c0bff1b06，AST键f5992550e506d4708c21b06595ecaa451095f5bf0d83ff9220cd9a88dc4bf215。等权采用原P0源码，不重写为不同程序。H冻结文件、七维接口、未取整V5 LB、归一化与同分规则均保持；两者旧train21认证不重算。',
        '复用同一T30 worker/collector/分类器；本轮每程序—实例独立worker以保存全部配对记录，首解+复检+完整回传共享30秒，正常退出另等2秒。相对原21例共worker改变进程粒度，编译/启动开销进入各项期限，调度算法及种子501未变。10项离线检查含2个独立toy认证worker及与直接构造器的回归；toy不是正式结果。','',
        '## 完整集结果','',
        f"共消耗{s['consumed_program_instances']}/{s['planned_program_instances']}项，实际启动{s['first_starts']}次首解及{s['recheck_starts']}次复检。完整Fitness：dynamic={s['complete_fitness']['dynamic']}，equal={s['complete_fitness']['equal']}。"]
    if s['full_confirmation_valid']:
        delta=s['delta_F'];result='更好' if delta>0 else '更差' if delta<0 else '持平'
        lines += [f"冻结冠军在这批确认实例上{result}：ΔFitness={delta:+.12f}，相对平均Cmax/LB改善={s['relative_mean_Cmax_LB_improvement_percent']:+.4f}%；胜/负/平={s['wins']}/{s['losses']}/{s['ties']}。原始Cmax合计dynamic={s['dynamic_Cmax_sum']}、equal={s['equal_Cmax_sum']}，仅作补充，不替代归一化主指标。",
            f"预定分层配对bootstrap95%区间为{s['stratified_bootstrap_95']}。它条件于这三个层和当前公开来源，实例相关性/小样本限制仍在，不能证明普遍泛化。",
            '逐实例如下，ΔCmax=dynamic−equal，ΔF贡献=(equal−dynamic)/(LB×总实例数)：','',
            '|实例|工序数|机器数|dynamic Cmax|equal Cmax|ΔCmax|ΔF贡献|','|---|---:|---:|---:|---:|---:|---:|']
        for r in rows:lines.append(f"|{r['file']}|{r['operations']}|{r['machines']}|{r['dynamic_Cmax']}|{r['equal_Cmax']}|{r['delta_Cmax']:+d}|{r['delta_F_contribution']:+.9f}|")
        hi=s['largest_normalized_gain'];lo=s['largest_normalized_loss']
        lines += ['',f"归一化最大改善为{hi['file']}（Cmax差{hi['delta_Cmax']:+d}，ΔF贡献{hi['delta_F_contribution']:+.9f}）；最大退化为{lo['file']}（{lo['delta_Cmax']:+d}，{lo['delta_F_contribution']:+.9f}）。这两个名称是极值方向，即使全体同向也不伪造正/负收益。",
            f"全部正贡献合计{s['gross_positive_F']:+.9f}，负贡献合计{s['gross_negative_F']:+.9f}。正贡献top1/top3占比为{s['top1_share_of_gross_positive']}/{s['top3_share_of_gross_positive']}；分母为全部正贡献，净值可能有正负抵消。",
            f"负贡献top1/top3占全部负贡献绝对值比例为{s['top1_share_of_gross_negative']}/{s['top3_share_of_gross_negative']}。这批18例退化并非仅一条异常差记录；仍不因此改变正式清单或主指标。",
            f"完整物理排程相同{s['same_physical_count']}/{s['selected_instances']}例；不代表两个程序在全部可能状态下等价。现有member_usage只提供主导成员步数，未新增第三遍轨迹诊断。"]
        if delta>0:
            lines += ['本轮支持该冻结U在这批项目未用于开发/选择的公开迁移实例上具有平均质量收益；适用范围仅为已固定来源/规模，不证明所有动态策略有效、动态状态项的单独因果作用或EVO整体稳定优于IND。']
        else:
            lines += ['本轮没有证明该冻结动态U的训练外平均优势；训练内改善不能直接迁移到这批公开实例。分布/规模改变与有限确认样本是解释边界，不能仅凭退化断言动态策略空间无价值。保留原冻结策略与全部负面/持平结果，不在本确认集继续调参。']
    else:
        lines += ['至少一方法未获得全部认证，完整集对照不成立。完整Fitness为null的一侧不得使用成功前缀或共同成功子集代替。已保存逐实例结果只作明细，不声称本轮确认成功。']
    failures=[r for r in tasks if not r['valid']]
    lines += ['', '## 成本、失败与边界','',
        f"失败/未完成项{len(failures)}。所有项、错误、生命周期和两次求解证据见All_task_results.csv及原始归档；普通超时不重试、不补实例。评价父进程区间累计{s['evaluation_parent_seconds']:.3f}秒；不是严格CPU时间。",
        f"完整campaign墙钟{s.get('campaign_wall_seconds')}秒；已知首解构造{s['known_first_construct_seconds']:.3f}秒、复检构造{s['known_recheck_construct_seconds']:.3f}秒，分别与进程/归档开销区分。正式启动及12小时截止、终态和PID清理见Run_clock.json、End_summary.json和Final_verification.json。",
        '生成API调用0、Token0、生成费用0；公开数据下载不属于生成请求。临时caffeinate绑定本runner，End_summary保存清理凭证，不改全局电源设置。严格执行进程终态、源码/数据身份、复检和时钟门禁；未知状态不清锁或重跑。',
        '原train冠军在断电前的质量认证已核查；其旧worker未独立保存带U SHA的输入签章，绑定依据为冻结控制器/响应/任务/评价键。本轮额外保存逐项Input_receipt.json，但不倒改旧证据。确认结果不回流修改U，也不用于EVO/IND方法比较。',
        f"协议SHA256：`{s['protocol_sha256']}`。原始公开数据、候选池/去重清单、已抽样清单、源码身份、请求为0的授权、任务及完整结果均保留。",
        '来源：[SchedulingLab数据与格式](https://github.com/SchedulingLab/fjsp-instances)、[许可](https://github.com/SchedulingLab/fjsp-instances/blob/ac4c3402312bfbeafcf4472d78be567d4e6b46ab/LICENSE)。本轮结束，不提出或启动新的搜索、调参或替代实验。','',
        '离线复核报告：`PYTHONPATH=code:. .venv/bin/python -B -m tools.h01_external_report`。历史正式命令顺序为数据准备→离线验收→freeze→check→launch；不得把这些有副作用命令当只读复核或重新运行同一确认。']
    formatted=[]
    for line in lines:
        if line and formatted and formatted[-1] and not (line.startswith('|') and formatted[-1].startswith('|')):
            formatted.append('')
        formatted.append(line)
    (c.REPORT/'REPORT_ZH.md').write_text('\n'.join(formatted)+'\n')


if __name__=='__main__':report()
