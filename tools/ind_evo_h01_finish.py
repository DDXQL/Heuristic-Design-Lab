"""Final scientific summary of existing records only; no generation or solves."""
import csv
from datetime import datetime
import json
from statistics import fmean
from zoneinfo import ZoneInfo
from tools import ind_evo_h01 as x
from tools.ind_evo_h01_report import csv_save


def main():
    summary=x.read(x.REPORT/'Summary.json');s=x.read(x.RUN/'checkpoint.json');plans=x.read(x.RUN/'Tasks.json')
    p0=x.read(x.RUN/'P0.json');equal=next(r for r in p0 if r['id'].endswith('alpha_050'))
    ref_equal=x.read(x.RUN/s['evaluations'][equal['candidate']['key']]['result_path'])
    b2=x.read(x.RUN/'External_quality_references.json')['B2']['result']
    with (x.REPORT/'Search_curves.csv').open() as f:curves=list(csv.DictReader(f))
    common=[]
    for repeat in (1,2,3):
        a=next(r for r in curves if r['repeat']==str(repeat) and r['arm']=='IND' and r['logical_query']=='18')
        b=next(r for r in curves if r['repeat']==str(repeat) and r['arm']=='EVO' and r['logical_query']=='18')
        common.append({'repeat':repeat,'logical_query':18,'IND_best':float(a['best_fitness']),
            'EVO_best':float(b['best_fitness']),'EVO_minus_IND':float(b['best_fitness'])-float(a['best_fitness']),
            'status':'post-hoc common-prefix descriptive endpoint; not planned20 completion'})
    csv_save(x.REPORT/'Common_prefix18_POSTHOC.csv',common)
    comparisons=[];champion_summaries=[]
    for tid in ('r1_EVO_s07','r2_EVO_s16'):
        t=s['tasks'][tid];result=x.read(x.RUN/s['evaluations'][t['evaluation_key']]['result_path'])
        for label,reference in [('P0_equal',ref_equal),('historical_B2',b2)]:
            rs=[]
            for a,b in zip(result['instances'],reference['instances']):
                dc=a['makespan']-b['makespan']
                row={'task_id':tid,'reference':label,'file':a['file'],'Cmax':a['makespan'],
                     'reference_Cmax':b['makespan'],'LB':a['lower_bound'],'delta_Cmax':dc,
                     'delta_F_contribution':-dc/(21*a['lower_bound'])}
                rs.append(row);comparisons.append(row)
            assert abs(sum(r['delta_F_contribution'] for r in rs)-(result['fitness']-reference['fitness']))<1e-14
            champion_summaries.append({'task_id':tid,'reference':label,'fitness':result['fitness'],
                'delta_F':result['fitness']-reference['fitness'],'W':sum(r['delta_Cmax']<0 for r in rs),
                'L':sum(r['delta_Cmax']>0 for r in rs),'T':sum(r['delta_Cmax']==0 for r in rs),
                'sum_Cmax_delta':sum(r['delta_Cmax'] for r in rs),
                'top_positive':sorted(rs,key=lambda r:-r['delta_F_contribution'])[:3],
                'top_negative':sorted(rs,key=lambda r:r['delta_F_contribution'])[:3]})
    csv_save(x.REPORT/'Champions_vs_references.csv',comparisons)
    x.write(x.REPORT/'Champion_comparisons.json',champion_summaries)
    attempts=[]
    for f in (x.RUN/'journals').glob('*.json'):
        j=x.read(f)
        attempts.extend([{'unit':f.stem,**a} for a in j['api_attempts'].values()])
    failures=[]
    for a in attempts:
        if a['status']=='failed':failures.append({'attempt_id':a['id'],'task_id':a['logical_id'],
            'http_status':a.get('metadata',{}).get('http_status'),'error_type':a.get('error_type'),
            'retry_reason':a.get('retry_reason'),'elapsed_seconds':a.get('elapsed_seconds'),
            'usage_known':a.get('usage') is not None})
    csv_save(x.REPORT/'API_failure_evidence.csv',failures)
    c=x.RUN/'continuation-v1';r=c/'recovery-v1'
    clocks={'initial':x.read(x.RUN/'Run_clock.json'),'renewal':x.read(c/'Run_clock.json')}
    times={}
    def fmt(v):return datetime.fromtimestamp(v,ZoneInfo('Asia/Manila')).isoformat()
    for key,clock in clocks.items():times[key]={'start':fmt(clock['start']['wall']),'deadline':fmt(clock['deadline'])}
    times['initial_partial_end']=fmt(x.read(x.RUN/'End_summary.json')['end']['wall'])
    times['renewal_end']=fmt(x.read(c/'End_summary.json')['end']['wall'])
    times['recovery_end']=fmt(x.read(r/'End_summary.json')['end']['wall'])
    active=sum(t['finished']['wall']-t['started']['wall'] for t in s['tasks'].values())
    for t in s['tasks'].values():
        deadline=clocks['initial']['deadline'] if t['position']<=109 else clocks['renewal']['deadline']
        assert t['started']['wall']<deadline
        assert abs((t['finished']['wall']-t['started']['wall'])-(t['finished']['monotonic']-t['started']['monotonic']))<=2
    timedata={'windows':times,'candidate_active_intervals_sum_seconds':active,
        'known_API_seconds':sum(a.get('elapsed_seconds') or 0 for a in attempts),
        'notice':'Power loss/sleep confirmed by user. Whole wall span includes suspension and human/engineering wait; not computational cost. No new launch after its applicable deadline.',
        'original_clock_and_end_preserved':True,'renewal_clock_not_extended_for_recovery':True}
    x.write(x.REPORT/'Execution_windows_and_cost.json',timedata)
    for base,names,prefix in [(x.RUN,['Protocol.json','Protocol.sha256','Tasks.json','P0.json','P0_sources.json','Authorization.json','Run_clock.json','End_summary.json','checkpoint.json'],'Frozen_'),
            (c,['Authorization.json','Binding.json','Binding.sha256','Run_clock.json','End_summary.json','Stop.json'],'Continuation_'),
            (r,['Authorization.json','Binding.json','Binding.sha256','End_summary.json','Stop.json'],'Recovery_')]:
        for name in names:(x.REPORT/(prefix+name)).write_bytes((base/name).read_bytes())
    verification=x.read(x.REPORT/'Final_verification.json');verification.update({
        'planned_experiment_complete':False,'planned_logical_candidates':120,'unstarted_candidates':120-len(s['tasks']),
        'verification_scope':'Saved-result certification and replay pass; full intended experiment remains partial'})
    x.write(x.REPORT/'Final_verification.json',verification)
    units=summary['units'];lines=['# 最终科研报告：IND与EVO（明确为partial）','',
        '**目前有支持继续研究演化流程的探索性信号，但本轮没有完成原定3组完整20候选对照。** 在所有六条路径共同完成的前18个逻辑候选处，IND没有超过共同P0，EVO有两条路径超过；第三条EVO路径没有改善。',
        '计划120，实际启动113，尚未启动7；API尝试117（108完整返回、8次HTTP503、1次HTTP524），重试均计预算。有效质量记录107；1个新程序因Behnke57的认证T30超时而Fitness=null。没有以成功前缀替代完整成绩。',
        '最初断电／休眠造成109槽位后停止；用户另授权最长2小时仅续原11个。续跑三槽位各两次503触发保护，用户授权再排查后，下一原槽位两次仍503。失败槽位未重生，未改模型、未充值；只读余额97130870原始点、模型列表仍列gpt-6.1-sol，不能归因为该令牌总余额耗尽；具体上游原因未知。','',
        '## 已确认事实','',
        '|重复|IND逻辑槽位|EVO逻辑槽位|IND档案冠军|EVO档案冠军|EVO首次严格超过P0|','|---|---:|---:|---:|---:|---:|']
    for i in (1,2,3):
        a=next(u for u in units if u['repeat']==i and u['arm']=='IND');b=next(u for u in units if u['repeat']==i and u['arm']=='EVO')
        lines.append(f"|{i}|{a['committed']}/20|{b['committed']}/20|{a['champion_Fitness']:.12f}|{b['champion_Fitness']:.12f}|{b['first_exceed_query'] or '未超过'}|")
    lines += ['', '只有重复1两组达到20逻辑槽位；它包括服务故障造成的失败，不能称20个有效生成。重复2、3保持partial，不计算或宣传三次完整20预算的最终分布。',
        '共同P0最优为−1.983144294915；五个P0的历史105项／210遍逻辑评价投入单列，本轮未新增P0求解。每次20“新增”并非从零20查询。',
        '共同前18是事后选取的最大共同完成前缀，取自预先保存的0～20曲线；只作辅助等逻辑预算描述，不替代原定20主端点。重复1和2的正向结果都在断电／白天503之前形成，未因成绩选择续跑或停止。','',
        '### 仅新增候选质量与成功率','',
        '|重复|组|认证质量数|新增均值|中位数|新增最佳|','|---|---|---:|---:|---:|']
    for u in units:
        lines.append(f"|{u['repeat']}|{u['arm']}|{u['certified_candidates']}|{u['new_quality_mean']:.12f}|{u['new_quality_median']:.12f}|{u['champion_new_Fitness']:.12f}|")
    lines += ['', '源码准入：108份完整响应均通过H01代码约束；IND 54/54认证、EVO 53/54认证，EVO另外1份是求解超时。按全部已启动逻辑槽位，IND 54/57、EVO 53/56；HTTP故障不当作代码无效或奖励值。AST在每个搜索内重复均为0；存在1次跨搜索精确AST评价缓存复用。',
        'EVO的新增均值只在重复1领先，重复2、3均不及IND；因此两次较好的冠军不等于新增质量分布一致领先。重复2的EVO含一次HTTP524缺失，条件样本均值也有不确定性。',
        'P1分别保留4、4、3个本轮第一代子代，这些子代均实际成为第二代父代。重复1已完成P2，重复2、3尚未完成P2更新。数据流和原代末elitist更新已逐步重放，未发现未传递子代的工程错误。',
        'r1_EVO_s07由共同等权P0经过一次MUTATE得到，计算alpha=clip(0.5+remaining_work_std−machine_ready_std)。r2_EVO_s16由第一代CROSS子代B/g0000/000004经MUTATE得到，使用工作／机器状态、进度、候选比例和前一成员计算alpha。两个源码都使用状态，不据此单独证明状态依赖的因果贡献；也不能据两名冠军均为MUTATE就归因变异有效。',
        '第二个冠军是已认证并进入“已见最好档案”的子代，但当前第二代尚未代末更新。当前真实种群冠军与档案冠军在Search_champions_verified.csv分列，未把缓冲区孩子误称已进入P2。','',
        '### 与强参照的逐实例比较','',
        '|子代|参照|ΔFitness|胜/负/平|原始Cmax总和差|','|---|---|---:|---|---:|']
    for row in champion_summaries:lines.append(f"|{row['task_id']}|{row['reference']}|{row['delta_F']:+.12f}|{row['W']}/{row['L']}/{row['T']}|{row['sum_Cmax_delta']:+d}|")
    lines += ['', '逐实例差与归一化贡献完整见Champions_vs_references.csv。Fitness贡献=(C_ref−C_child)/(21×LB)，不能用总Cmax替代排序。历史B2和简单进度规则仅外部质量参考，不混入本轮搜索重复。',
        '完整train21物理排程指纹汇总为103组（包含已知P0物理记录）；原生P0两个端点物理指纹缺失单列未知。相同物理排程不等于全状态程序等价；AST无重复也不代表每个程序行为都不同。','',
        '## 有支持但尚未证实的解释','',
        '演化流程在两条新的搜索路径中找到了超过强P0的U，说明该路线值得继续验证，并非只出现一次发现。不过第三条无改善，新增质量均值也不一致占优，不能宣称EVO稳定更好。',
        '本批未改善不能主要归因于大量AST重复（均为0）或种群没有更新（已重放传递）。强P0、生成方向、有限预算与选择／遗传信息利用都可能影响结果。这里比较整个演化流程，父代信息、CROSS、MUTATE和选择的单独效应没有被分离。','',
        '## 未知与边界','',
        '3个20预算重复尚未全部完成；服务故障时段影响两组可用响应数。前18辅助结果不能替代完整主实验。没有留出验证、没有显著性宣称，不把本批视为泛化或各算子创新的证明。',
        '模型seed未发送，同编号不是严格随机配对；共享确定性评价缓存让搜索路径不成为独立物理计时重复。历史B2的T15包装与本批T30不同，不追认为同期资源公平对照。',
        '只读余额工具沿用旧requested_model标签gpt-5.6-sol，不代表本轮实际生成模型：真实请求配置和108份完整返回的model均核对为gpt-6.1-sol。HTTP503的具体上游原因仍未知。','',
        '## 成本、证据与后续','']
    for arm,a in summary['arms'].items():lines.append(f"{arm}：API尝试{a['API_attempts']}，已知输入/输出Token {a['known_input_tokens']}/{a['known_output_tokens']}，usage未知尝试{a['unknown_usage_attempts']}；可关联扣点{a['associated_points']}，未关联费用尝试{a['unknown_invoice_attempts']}。CNY未知，不作换算。")
    lines += [f"新增物理评价107，预留2247项／4494遍，实际启动4494遍。父进程评价区间合计{sum(a['physical_primary_seconds'] for a in summary['arms'].values()):.3f}秒；成功前缀首解／复检构造已知合计{sum(a['known_first_seconds']+a['known_recheck_seconds'] for a in summary['arms'].values()):.3f}秒，失败活动阶段额外构造时间不伪造为0。候选处理区间累计{active:.3f}秒；包含API、评价和准入。跨断电／等待总墙钟不当作计算成本。",
        '时间窗口原始记录和明确续跑授权均保留在Execution_windows_and_cost.json及冻结副本；恢复探测沿用同一2小时截止，没有再次加时。保留503 Stop和已认证的保护锁证据，不自动清理或重复失败候选。',
        '**建议：待原模型接口恢复，优先完成原计划7个未启动槽位并确认这轮对照，而不是立刻扩样或同时改变演化机制。** 届时须遵守有效时间授权；已失败的槽位仍占预算，不补成有效程序。当前没有自动启动后续实验。',
        '核心文件：Search_summary.csv／Search_curves.csv（含共同P0与新增）；Candidates.csv；EVO_lineage.csv／Population_snapshots.json；Per_instance.csv；API_costs.csv／API_failure_evidence.csv；Final_verification.json。原始主记录以Raw_primary_evidence.tar.gz与逐文件SHA归档；本机原始单实例重复副本不删除。',
        f"原始科学协议SHA：{summary['protocol_sha256']}。本地提交只包括本轮新增文件，不推送、不覆盖旧实验。"]
    (x.REPORT/'FINAL_REPORT_ZH.md').write_text('\n'.join(lines)+'\n')
    print({'final_report':str(x.REPORT/'FINAL_REPORT_ZH.md'),'status':s['phase'],'unstarted':120-len(s['tasks'])})


if __name__=='__main__':main()
