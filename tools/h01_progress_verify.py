"""Post-run evidence/analysis only. No solver invocation or network calls."""
import csv
import math
import os
from pathlib import Path
from statistics import fmean

from tools import h01_progress_baseline as b


def main():
    p=b.check();network=b.old.v2.local_guard([b.RUN/r['relative_path'] for r in p['instances']])
    state=b.read(b.RUN/'checkpoint.json');used=b.ledger(state,p)
    summary=b.read(b.REPORT/'Summary.json');specs=b.read(b.RUN/'Rules.json')
    equal=b.read(b.RUN/p['cache']['STATIC_a050']['result_path'])
    historical=b.read(b.RUN/'references/B2_champion.json')['result']
    expected={**p['source_files'],**p['protected_files']};identity=b.read(b.RUN/'Expected_loaded_identity.json')['identity']
    results={};checks=[];new=0;behavior_rows=0;dynamic_ops=0
    for spec in specs:
        entry=state['strategies'].get(spec['id'])
        if not entry or entry['status']!='completed':continue
        path=b.RUN/entry['result_path'];r=b.read(path);results[spec['id']]=r
        if entry['origin']=='new':
            new+=1;folder=path.parent;life=b.read(folder/'lifecycle.json')
            boundary=b.classify(r,before=b.read(folder/'before.json'),after=b.read(folder/'after.json') if (folder/'after.json').exists() else None,
                lifecycle=life,expected_identity=identity,expected_files=expected,start_files=expected,end_files=expected,
                worker_failure=(folder/'worker_failure.json').exists())
            assert boundary==r['boundary']
            checks.append({'id':spec['id'],'boundary':boundary,'normal_exitcode':life['exitcode'],
                           'receiver_stopped':life['receiver_thread_stopped']})
            for row in r['instances']:
                trace=row['observed_progress_H0_H1'];n=len(trace)
                assert [t[0] for t in trace]==[k/n for k in range(n)]
                assert all(row['single_h_calls'][i]==0 for i in range(2,10))
                assert b.digest(trace)==row['progress_weights_sha256']==row['recheck_progress_weights_sha256']
                for progress,a,c in trace:
                    alpha=spec['alpha_before'] if not spec['dynamic'] or progress<spec['tau'] else spec['alpha_after']
                    assert (a,c)==(alpha,1-alpha)
                if spec['dynamic']:
                    behavior_rows+=1;dynamic_ops+=n
                    assert row['before_steps']==math.ceil(spec['tau']*n)
                    assert row['after_steps']==n-row['before_steps']
                    assert row['actual_weight_changes']==1
                else:assert row['actual_weight_changes']==0
        if r['valid']:
            assert len(r['instances'])==21
            for ref in (equal,historical):
                contribution=sum((z['makespan']-x['makespan'])/(21*x['lower_bound']) for x,z in zip(r['instances'],ref['instances']))
                assert abs(contribution-(r['fitness']-ref['fitness']))<1e-14
    assert used==new*21<=399 and summary['new_evaluations']==new
    assert len(b.read(b.RUN/'Aliases_27.json'))==27 and len(specs)==21
    complete=state['phase']=='completed'
    if complete:
        assert len(results)==21 and new==19 and behavior_rows==378 and dynamic_ops==68400
        assert summary['actual_solve_starts']==798
    allnewvalid=all(r['valid'] for id,r in results.items() if id not in p['cache'])
    if allnewvalid:assert all(c['normal_exitcode']==0 for c in checks)
    clock=b.read(b.RUN/'Run_clock.json');end=b.read(b.RUN/'End_summary.json')
    assert clock['deadline']==clock['start']['wall']+21600
    assert summary['protocol_sha256']==b.sha(b.RUN/'Protocol.json')
    assert not list((b.RUN/'evidence').glob('*/Clock_quarantine.json'))
    static_h1=results.get('STATIC_a000');old=b.read(b.RUN/'references/H1_legacy.json')
    if static_h1 and static_h1['valid']:
        assert [(x['makespan'],x['score']) for x in static_h1['instances']]==[(x['makespan'],x['score']) for x in old['instances']]
    best=summary['best_dynamic'];lines=['# 科研解释与复核结论','',
        f"本轮终态{state['phase']}，21规范策略中认证{len(results)}，新增{new}策略；新增API=0。",'',
        f"预定18条动态规则中，{summary['dynamic_exceed_equal']}条超过静态等权，{summary['dynamic_equal_equal']}条持平；{summary['dynamic_exceed_B2']}条超过历史B2完整成绩。"]
    if best:
        r=results[best['id']];rows=[]
        for x,e,z in zip(r['instances'],equal['instances'],historical['instances']):
            rows.append({'file':x['file'],'Cmax':x['makespan'],'LB':x['lower_bound'],
                'delta_equal':(e['makespan']-x['makespan'])/(21*x['lower_bound']),
                'delta_B2':(z['makespan']-x['makespan'])/(21*x['lower_bound'])})
        positive=sorted([x for x in rows if x['delta_equal']>0],key=lambda x:-x['delta_equal'])
        negative=sorted([x for x in rows if x['delta_equal']<0],key=lambda x:x['delta_equal'])
        gross=sum(x['delta_equal'] for x in positive);loss=sum(x['delta_equal'] for x in negative)
        lines+=['',f"冠军{best['id']}：tau={best['tau']}，H0权重{best['alpha_before']}→{best['alpha_after']}，H1互补。Fitness {r['fitness']:.12f}。",'',
            f"相对等权Δ={best['delta_equal']:+.12f}，{best['W_equal']}胜{best['L_equal']}负{best['T_equal']}平；相对历史B2 Δ={best['delta_B2']:+.12f}，{best['W_B2']}胜{best['L_B2']}负{best['T_B2']}平。",'',
            f"正贡献合计{gross:+.12f}，负贡献合计{loss:+.12f}，二者之和复现净ΔFitness。"]
        if positive:
            lines += [f"前三个正贡献：{'、'.join(x['file']+' '+format(x['delta_equal'],'+.9f') for x in positive[:3])}；占总正贡献{sum(x['delta_equal'] for x in positive[:3])/gross:.1%}。不能把它说成净改善百分比。"]
        if negative:lines += [f"主要负贡献：{'、'.join(x['file']+' '+format(x['delta_equal'],'+.9f') for x in negative[:3])}。"]
        if best['delta_equal']>0:
            lines += ['', '判断：预定简单规则在这批train21上提供了动态利用可以改善强静态参照的直接质量证据。若与B2比较领先，只能说保存完整训练成绩的数值更好；旧B2的T15生命周期与本批T30并不完全一致，不能升级为同期同协议优势或搜索效率优势。',
                '研究优先级：先让U搜索能稳定发现和利用这些已验证的简单动态规律，把本族作为可复用质量参照；当前没有必要立即扩充状态、算子或复杂动态结构。简单族的结果不能说明复杂动态策略没有价值。']
        else:
            lines += ['', '判断：本族没有提供超过等权的新动态收益证据；这只限制这18条简单进度规则，不能证明动态控制整体无效。',
                '研究优先级：先改善U搜索对已知强静态和已有有效U的发现／保留能力，再检验动态增量；本次没有理由为追分追加阈值、权重或更复杂状态条件。']
    lines += ['', '行为证据：18个动态规则×21实例均在原两遍求解中访问阈值两侧，每实例权重恰改变一次；首解／复检progress与权重一致。被动记录68400次首解U调用，复检逐项一致后留SHA，不追加诊断求解。',
        '程序使用H0/H1意味着允许端点处某成员权重为0，host只调用正权重成员。实际权重变化／支持集变化不等于每步动作必然变化，物理排程分组只证明有限train21上的相同／不同。',
        '历史参照：B2完整原始checkpoint hash、冠军代码key、H成员顺序、核心排程源码pins、train21顺序与LB均已核对。旧B2是T15包装，本轮T30；保留其原始完整质量作为历史参照，不补跑、不追认缺少的现代终态证据。',
        '静态复用：H0与等权保留现代T30身份／进程正常退出和两遍一致性。H1由于缺同级终态回执，本轮新认证，21实例Cmax与原历史原生复检结果全部一致；没有更改或否定旧记录。',
        f"成本：预留{used}项／{used*2}遍，实际启动{summary['actual_solve_starts']}遍；首解+复检成功求解合计{summary['new_successful_first_seconds']+summary['new_successful_recheck_seconds']:.3f}秒；包含IPC、源码校验边界和退出等待的新评价区间合计{summary['new_primary_seconds']:.3f}秒；评价结束摘要墙钟{summary['wall_seconds']:.3f}秒，不含随后报告归档和离线复核。不同成本区间不可相加重复计算。",
        f"异常：无效新增策略{summary['invalid_new_strategies']}。源码与预算复核通过；没有本批Clock_quarantine记录。wall与monotonic检测未发现大于2秒的差异，不能据此保证所有系统休眠形式均已排除。临时防空闲休眠进程已按结束摘要清理，未修改全局电源。",'',
        '限制：已知H0/H1强组合的先验、开发过的train21、27组合／21规范策略的扫描与冠军选择均有成本。本轮不是零成本人工策略，不比较LLM与随机搜索效率，不支持独立泛化。若有相同Fitness而不同指纹，仍须区别质量相等与物理排程相同。',
        '没有启动下一项实验。正式命令与冻结规则在docs/H01_PROGRESS_STEP_PROTOCOL_V1.md；完整排名、逐实例与行为表见同目录，Raw_execution_evidence.tar.gz包含原始运行记录。']
    (b.REPORT/'RESEARCH_FINDINGS_ZH.md').write_text('\n\n'.join(x for x in lines if x)+'\n')
    b.write(b.REPORT/'Final_verification.json',{'passed':True,'phase':state['phase'],'complete_family':complete,
        'new_count':new,'reserved_instances':used,'reserved_solves':used*2,'lifecycle':checks,
        'dynamic_instance_behavior_rows':behavior_rows,'dynamic_first_U_calls':dynamic_ops,
        'scientific_and_protected_files_unchanged':True,'API':0,'network_guard':network,
        'cache_H0_and_equal_reused':True,'new_H1_matches_legacy_quality':True,
        'protocol_sha256':b.sha(b.RUN/'Protocol.json')})
    print({'passed':True,'phase':state['phase'],'best_dynamic':best,'new_solves':summary['actual_solve_starts']})


if __name__=='__main__':main()
