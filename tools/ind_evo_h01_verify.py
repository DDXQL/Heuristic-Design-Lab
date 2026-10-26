"""Read-only scientific replay of search state and durable receipts; no solves/API."""
from collections import Counter,defaultdict
import json
from pathlib import Path
import random
from statistics import fmean,median

from tools import ind_evo_h01 as x
from tools.ind_evo_h01_report import csv_save,quality


def main():
    p=x.check();s=x.read(x.RUN/'checkpoint.json');x.ledger(s,p)
    historical=x.read(x.B2/'Plan.json');engine_pins={}
    for name in ('code/fjsp_usage/research/evolution.py','code/fjsp_usage/research/sets.py',
                 'code/fjsp_usage/research_real/prompts.py','code/fjsp_usage/usage_v2/prompts.py'):
        assert x.sha(x.ROOT/name)==historical['pins'][name]
        engine_pins[name]=historical['pins'][name]
    summary=x.read(x.REPORT/'Summary.json');plans=x.read(x.RUN/'Tasks.json')
    p0=x.read(x.RUN/'P0.json');members=[x.checked_candidate(r['candidate'],'h') for r in x.read(x.RUN/'H_frozen.json')['members']]
    journals={f.stem:x.read(f) for f in (x.RUN/'journals').glob('*.json')}
    all_attempts=[a for j in journals.values() for a in j['api_attempts'].values()]
    assert len(all_attempts)<=180 and all(len(j['requests'])<=20 and len(j['api_attempts'])<=30 for j in journals.values())
    assert all(len(r['attempt_ids'])<=2 for j in journals.values() for r in j['requests'].values())
    assert all(a['status'] not in ('pending','interrupted_unknown') for a in all_attempts)
    start=x.ranked(p0)[0];stats=[];champions=[];trace=[];response_count=0;parsed_count=0
    for repeat,seed in enumerate(x.SEEDS,1):
        for arm in ('IND','EVO'):
            uid=f'r{repeat}_{arm}';unit=s['units'][uid];j=journals.get(uid,{'requests':{},'api_attempts':{}})
            pool=x.ranked(p0);children=[];rng=random.Random(seed);seen={r['candidate']['key']:r['id'] for r in p0}
            definitions={r['id']:r for r in p0};eligible=[];allquality=[];novelquality=[]
            best=start;first=None;max_new=None
            ids=unit['attempts']
            for slot,tid in enumerate(ids):
                t=s['tasks'][tid];assert t['slot']==slot and t['status']=='completed'
                request=j['requests'][tid];prompt=(x.RUN/'prompts'/(tid+'.txt')).read_text()
                assert request['prompt']==prompt
                if arm=='IND':
                    assert not t['parents'];assert not t['parent_pool']
                    assert prompt==x.independent_prompt(members)==(x.RUN/'templates/IND.txt').read_text()
                else:
                    op='CROSS' if slot%10<5 else 'MUTATE'
                    parents=x.select_parents(pool,5 if op=='CROSS' else 1,rng)
                    assert [r['id'] for r in parents]==t['parents']
                    assert [r['id'] for r in pool]==t['parent_pool']
                    assert prompt==x.legacy.build_prompt('B',op,parents,members)
                if request['status']=='completed':
                    response_count+=1
                    saved=x.read(x.RUN/'responses'/(tid+'.json'));assert saved==request
                    assert request['response_metadata']['model']==p['provider']['model']
                    try:
                        c=x.parse_response(request['text'],kind='U',interface_version=x.INTERFACE,member_count=10)
                        c=x.legacy.validate(c.code,c.description)
                    except x.CandidateError:assert t['outcome']=='parse_or_constraint_error'
                    else:
                        parsed_count+=1;assert c.key==t['candidate']['key']
                        assert t['duplicate']==(c.key in seen)
                        if c.key not in seen:seen[c.key]=t['source_id']
                child=None
                if t.get('certified_valid'):
                    e=s['evaluations'][t['evaluation_key']];r=x.read(x.RUN/e['result_path'])
                    assert e['status']=='completed' and r['valid'] and r['fitness']==t['fitness']
                    assert len(r['instances'])==21
                    if max_new is None or t['fitness']>max_new['fitness']:max_new={'id':tid,'fitness':t['fitness']}
                    allquality.append(t['fitness'])
                    if t['fitness']>best['fitness']:
                        best={'id':tid,'fitness':t['fitness'],'candidate':t['candidate']}
                        if first is None:first=slot+1
                    if t['admitted']:
                        assert not t['duplicate'];novelquality.append(t['fitness'])
                        child={'id':t['source_id'],'candidate':t['candidate'],'fitness':t['fitness'],
                               'scores':[a['score'] for a in r['instances']]}
                        definitions[child['id']]=child
                else:assert not t['admitted']
                if arm=='EVO':
                    if child is not None:children.append(child)
                    if slot%10==9:
                        before=[r['id'] for r in pool];pool=x.ranked(pool+children)[:5];children=[]
                        assert [r['id'] for r in pool]==unit['snapshots']['P'+str(slot//10+1)]
                        trace.append({'repeat':repeat,'after_generation':slot//10+1,
                            'population_ids':[r['id'] for r in pool],
                            'new_entries':[r['id'] for r in pool if r['id'] not in before],
                            'champion_fitness':pool[0]['fitness'],'delta_P0':pool[0]['fitness']-start['fitness']})
            if arm=='EVO':
                assert [r['id'] for r in pool]==[r['id'] for r in unit['population']]
                assert max(r['fitness'] for r in pool+children)==best['fitness']
            champions.append({'repeat':repeat,'arm':arm,'complete20':len(ids)==20,
                'archive_best_id_earliest_strict_improvement':best['id'],'archive_best_fitness':best['fitness'],
                'actual_final_population_best_id':pool[0]['id'] if arm=='EVO' else None,
                'actual_population_best_fitness':pool[0]['fitness'] if arm=='EVO' else None,
                'delta_P0':best['fitness']-start['fitness'],'first_exceed_query':first,
                'new_best_id':max_new['id'] if max_new else None,'new_best_fitness':max_new['fitness'] if max_new else None,
                'new_quality':quality(allquality),'novel_only_quality':quality(novelquality)})
            stats.append({'repeat':repeat,'arm':arm,'started':len(j['requests']),'committed':len(ids),
                'complete_responses':sum(r['status']=='completed' for r in j['requests'].values()),
                'API_attempts':len(j['api_attempts']),'certified_quality':len(allquality),'novel_valid':len(novelquality),
                'within_search_duplicates':sum(s['tasks'][tid].get('duplicate',False) for tid in ids)})
    expected={**p['source_files'],**p['protected_files']};normal=invalid=0;cert_rows=0
    for key,e in s['evaluations'].items():
        if e['origin']=='P0_legacy':continue
        folder=(x.RUN/e['result_path']).parent;r=x.read(folder/'result.json');life=x.read(folder/'lifecycle.json')
        kwargs=dict(before=x.read(folder/'before.json'),after=x.read(folder/'after.json') if (folder/'after.json').exists() else None,
            lifecycle=life,expected_identity=x.read(x.RUN/'Solver_expected_identity.json')['identity'],
            expected_files=expected,start_files=expected,end_files=expected,worker_failure=(folder/'worker_failure.json').exists())
        assert x.certified.certify(r,kwargs)==r['boundary']
        if r['valid']:normal+=1;assert life['exitcode']==0
        else:invalid+=1
        cert_rows+=len(r['instances'])
    assert not list(x.RUN.glob('**/*quarantine*.json'))
    if s['phase']=='completed':
        assert len(all_attempts)>=120 and sum(len(j['requests']) for j in journals.values())==120
        assert len(s['tasks'])==120 and all(len(u['attempts'])==20 for u in s['units'].values())
    csv_save(x.REPORT/'Search_champions_verified.csv',champions)
    csv_save(x.REPORT/'Per_search_verification.csv',stats);csv_save(x.REPORT/'Generational_flow_verified.csv',trace)
    x.write(x.REPORT/'Final_verification.json',{'passed':True,'phase':s['phase'],'logical_started':sum(r['started'] for r in stats),
        'complete_responses':response_count,'parsed_admissible':parsed_count,'API_attempts':len(all_attempts),
        'new_normal_certifications':normal,'new_invalid_certifications':invalid,'certified_success_rows':cert_rows,
        'parent_sampling_and_generational_survival_replayed':True,'every_saved_prompt_reconstructed_exactly':True,
        'original_B2_engine_and_prompt_pins_match':engine_pins,
        'unknown_requests':0,'unknown_evaluations':0,'new_API_during_verification':0,'new_solves_during_verification':0,
        'protected_source_and_history_unchanged':True,'protocol_sha256':x.sha(x.RUN/'Protocol.json')})
    # Distinguish archive tie retention from the original ranked population tie rule.
    lines=['# IND/EVO结果解释：事实、假设与未知','',
        '共同P0最优为H0/H1等权。曲线中的档案冠军遇到同分保留原先来源；EVO真实种群仍严格按原Fitness/ID规则排序。因此同分新子代可能替换P0进入种群，而外部曲线仍显示P0。两个ID在Search_champions_verified.csv分别列出，不混淆。','',
        '## 已确认事实','', '|重复|IND最终ΔP0|EVO最终ΔP0|EVO−IND最终Fitness|IND仅新增最佳|EVO仅新增最佳|','|---|---:|---:|---:|---:|---:|']
    diff=[]
    for r in (1,2,3):
        a=next(c for c in champions if c['repeat']==r and c['arm']=='IND');b=next(c for c in champions if c['repeat']==r and c['arm']=='EVO')
        d=b['archive_best_fitness']-a['archive_best_fitness'];diff.append(d)
        show=lambda z:'null' if z is None else f'{z:.12f}'
        lines.append(f"|{r}|{a['delta_P0']:+.12f}|{b['delta_P0']:+.12f}|{d:+.12f}|{show(a['new_best_fitness'])}|{show(b['new_best_fitness'])}|")
    counts={arm:sum(c['delta_P0']>0 for c in champions if c['arm']==arm) for arm in ('IND','EVO')}
    lines += ['',f"本批观察：改善共同初始冠军IND {counts['IND']}/3，EVO {counts['EVO']}/3。按相同重复编号并列，EVO最终成绩领先{sum(d>0 for d in diff)}次、落后{sum(d<0 for d in diff)}次、同分{sum(d==0 for d in diff)}次。这是任务级描述，不是严格随机配对检验。",'',
        '各重复完成状态在Search_champions_verified.csv的complete20列；若为partial，只能解释其实际已启动预算，不能当20查询完整重复比较。代中暂停时，已认证孩子可改善外部档案，但父代群体按冻结机制要到代末才更新。',
        'Per_search_verification.csv分别列完整响应、准入代码、认证质量、新颖有效数及重复；Search_champions_verified.csv同时给含重复的新增质量与novel-only质量，避免“复制P0”混同改进。',
        '父代抽样已从相同P0和冻结seed逐步重放，整代冻结、代末ranked保留和P0/P1/P2一致；每份真实提示词均重构一致，IND没有父代或历史。没有发现子代未按既定代码传递的工程错位。','',
        '## 有证据支持但尚未证实的解释','']
    if counts['EVO']>counts['IND']:
        lines += ['本批EVO改善共同P0的重复数较多，支持继续研究完整演化流程，但三次重复不能估计稳定成功概率。父代信息、rank选择、CROSS、MUTATE与生存共同改变，不能拆分归因。']
    elif counts['EVO']==counts['IND']==0:
        lines += ['两组本批均未突破强P0。若EVO新增候选更接近P0，这可以体现利用已有高质量父代，而不能等同探索出更好程序；应结合重复率、新颖质量与种群替换看，不能把平坦曲线直接诊断成群体更新失灵。',
            '已重放的代际传递排除了这套实现未更新群体的简单解释，但不能证明原演化机制有效或最优。3次无改善与随机生成波动、强起点、权重策略空间和提示约束等多种解释相容。']
    else:
        lines += ['本批没有显示EVO比IND更稳定改善P0；具体改善是否来自单次发现应看三行结果，不能把全campaign最优当20查询的典型结果。']
    lines += ['', '## 当前无法判断','',
        '3次训练内重复不足以证明普遍优劣或显著性；也没有拆分选择、交叉、变异的独立贡献。新U即使引用状态，整体成绩也不能证明动态控制的因果增益。没有访问留出，不声称泛化。',
        '模型默认采样、内部路由及独立请求的实际随机性不能由客户端完整认证；没有发送模型seed。共享确定性评价缓存减少物理成本，但各搜索路径不是独立物理计时重复。',
        '原生P0端点没有同级物理指纹，已将该缺口与新策略完整排程分组分开；不补造全状态行为等价。扣点的Token／时间关联不是精确request-ID认证，未知费用不作为质量结论的门禁。','',
        '## 后续判断（仅建议，不执行）','']
    if counts['EVO']>counts['IND']:
        lines += ['可保留现有EVO流程并在独立批次复核这一模式，先确认是否跨更多搜索重复稳定，不直接追加复杂反思或宣称单算子贡献。']
    else:
        lines += ['本批不足以支持扩大演化规模。优先依据已有重复、有效性和代际流转证据选择一个具体搜索瓶颈，再设计单因素改进；避免仅因最终冠军没有提升就同时改多个环节。没有自动执行下一项实验。']
    (x.REPORT/'INTERPRETATION_ZH.md').write_text('\n'.join(lines)+'\n')
    # Presentation-only repair of blank lines between Markdown table rows.
    report_path=x.REPORT/'REPORT_ZH.md';original=report_path.read_text().splitlines();formatted=[]
    for i,line in enumerate(original):
        if not line.strip() and formatted and formatted[-1].startswith('|'):
            next_line=next((r for r in original[i+1:] if r.strip()),'')
            if next_line.startswith('|'):continue
        formatted.append(line)
    report_path.write_text('\n'.join(formatted)+'\n')
    # Plot saved curves only. An unavailable plotting library leaves CSV intact.
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import csv
        with (x.REPORT/'Search_curves.csv').open() as f:curves=list(csv.DictReader(f))
        fig,axs=plt.subplots(1,3,figsize=(12,3.6),sharey=True)
        for repeat,ax in enumerate(axs,1):
            for arm,color in [('IND','#3178b6'),('EVO','#d25a38')]:
                rows=[r for r in curves if int(r['repeat'])==repeat and r['arm']==arm]
                ax.step([int(r['logical_query']) for r in rows],[float(r['best_fitness']) for r in rows],where='post',label=arm,color=color)
            ax.axhline(start['fitness'],color='gray',ls='--',lw=.7,label='P0 best')
            counts={arm:sum(int(c['repeat'])==repeat and c['arm']==arm for c in curves)-1 for arm in ('IND','EVO')}
            ax.set(title=f'Search repeat {repeat}\nIND {counts["IND"]}/20, EVO {counts["EVO"]}/20',xlabel='Additional logical candidates',xlim=(0,20));ax.grid(alpha=.2)
        axs[0].set_ylabel('Best train21 mean(-Cmax/LB)');axs[-1].legend();fig.tight_layout()
        fig.savefig(x.REPORT/'Search_curves.png',dpi=180);fig.savefig(x.REPORT/'Search_curves.svg');plt.close(fig)
    except ImportError as e:x.write(x.REPORT/'Plot_unavailable.json',{'error_type':type(e).__name__,'CSV_available':True})
    print({'verified':True,'phase':s['phase'],'improved_repeats':counts,'API_attempts':len(all_attempts)})


if __name__=='__main__':main()
