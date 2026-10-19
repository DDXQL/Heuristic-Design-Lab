#!/usr/bin/env python3
"""Saved-record reports for the bounded update-frequency trial. No inference/replay."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from statistics import fmean
from report_single_fair import read,sha,csvfile,dump,check_evaluation,cost_row,backup,mdtable
ROOT=Path(__file__).resolve().parents[1]


def build(run,out,*,charts=True):
    if (run/'.writer.lock').exists():raise RuntimeError('active caller; wait before final reporting')
    out.mkdir(parents=True,exist_ok=True)
    protocol=read(run/'protocol.json');names=protocol['dataset']['split']['train']
    H=read(run/'H_frozen.json');shared=read(run/'r201/Shared_initial.json');p0=shared['population']
    init_ids={x['id'] for x in p0};initial_best=sorted(p0,key=lambda x:(-x['fitness'],x['id']))[0]
    old=read(run/'Frozen_historical_reference.json');oldfit=old['row']['fitness']
    ledger=read(run/'budget.json');requests=[];instances=[];lineage=[];milestones=[];states={};populations=[];exports=out/'candidates';exports.mkdir(exist_ok=True)
    evals={x['id']:x['training_result'] for x in p0};candidates={x['id']:x['candidate'] for x in p0}
    for arm in ('A','B'):
        folder=run/f'r201/{arm}';s=read(folder/'checkpoint.json',{});states[arm]=s
        journal=read(folder/'budgeted_evolution_requests.json',{}).get('requests',{})
        attempts={a['id']:a for a in s.get('attempts',[])}
        for ident,entry in s.get('evaluations',{}).items():
            e=entry.get('result');check_evaluation(e,names);evals[ident]=e
            if e:
                for x in e.get('instances',[]):
                    instances.append({'arm':arm,'id':ident,'valid_candidate':e['valid'],'fitness':e.get('fitness'),
                        **{k:x.get(k) for k in ['file','makespan','lower_bound','score','feasible','single_solve_seconds','deterministic_recheck_seconds','diagnostic_replay_seconds','member_usage']}})
        for ident,r in journal.items():
            a=attempts.get(ident,{});b=ledger['records'][r['global_key']];e=evals.get(ident)
            row={'arm':arm,'id':ident,'global_key':r['global_key'],'confirmed_sent':b.get('send_confirmed',False),
                'status':r['status'],'category':a.get('category'),'operator':a.get('operator'),'parents':a.get('parents'),
                'code_key':a.get('code_key'),'fitness':e.get('fitness') if e else None,
                'error_type':r.get('error_type') or a.get('error_type'),'error':r.get('error') or a.get('error'),**cost_row(run,r['global_key'],r)}
            requests.append(row)
            for parent in a.get('parents',[]):lineage.append({'arm':arm,'child':ident,'parent':parent,'parent_is_new':parent not in init_ids,'operator':a['operator']})
            if r.get('text'):
                import re
                stem=ident.replace('/','_');(exports/(stem+'.response.txt')).write_text(r['text'])
                m=re.search(r'```python\s*\n(.*?)\n```',r['text'],re.S)
                if m:(exports/(stem+'.py')).write_text(m.group(1).rstrip()+'\n')
        for x in s.get('population',[]):
            candidates[x['id']]=x['candidate'];populations.append({'arm':arm,'id':x['id'],'fitness':x['fitness'],'from_initial':x['id'] in init_ids})
        for boundary in (10,20,30):
            m=read(folder/f'Milestone_{boundary:02d}.json')
            if not m:continue
            incumbent=m['incumbent'];rs=[r for r in requests if r['arm']==arm][:boundary]
            categories=Counter(r['category'] or r['status'] for r in rs)
            evaluations=[evals[r['id']] for r in rs if evals.get(r['id'])]
            time_rows=[x for e in evaluations for x in e.get('instances',[])]
            milestones.append({'arm':arm,'planned_boundary':boundary,'actual_requests':sum(r['confirmed_sent'] for r in rs),
                'champion_id':incumbent['id'],'champion_fitness':incumbent['fitness'],'champion_is_new':incumbent['id'] not in init_ids,
                'above_initial_H0':incumbent['fitness']>initial_best['fitness'],
                'at_least_old_frozen':incumbent['fitness']>=oldfit,
                'actual_parent_pool_mean':fmean(x['fitness'] for x in m['actual_parent_pool']),
                'observed_top5_mean':fmean(x['fitness'] for x in m['observed_elites']),
                'survival_updates':m['actual_survival_updates'],
                'new_survivors_in_actual_pool':sum(x['id'] not in init_ids for x in m['actual_parent_pool']),
                'valid':categories['valid'],'code_duplicates':categories['code_duplicate'],
                'narrow_duplicates':categories['narrow_equivalence_duplicate'],'categories':dict(categories),
                'valid_per_sent':categories['valid']/sum(r['confirmed_sent'] for r in rs) if any(r['confirmed_sent'] for r in rs) else None,
                'known_platform_points':sum(r['actual_platform_points'] for r in rs if r['actual_platform_points'] is not None),
                'unknown_fee_requests':sum(r['confirmed_sent'] and r['actual_platform_points'] is None for r in rs),
                'known_input_tokens':sum(r['wire_input_tokens'] for r in rs if r['wire_input_tokens'] is not None),
                'known_output_tokens':sum(r['wire_output_tokens'] for r in rs if r['wire_output_tokens'] is not None),
                'known_invoice_input_tokens':sum(r['invoice_input_tokens'] for r in rs if r['invoice_input_tokens'] is not None),
                'known_invoice_output_tokens':sum(r['invoice_output_tokens'] for r in rs if r['invoice_output_tokens'] is not None),
                'unknown_wire_requests':sum(r['confirmed_sent'] and r['wire_input_tokens'] is None for r in rs),
                **{k:sum(x[k] for x in time_rows if x.get(k) is not None) for k in ('single_solve_seconds','deterministic_recheck_seconds','diagnostic_replay_seconds')},
                'primary_evaluation_seconds':sum(e.get('primary_evaluation_seconds',0) for e in evaluations),
                'known_provider_roundtrip_seconds':sum(r['provider_roundtrip_seconds'] for r in rs if r['provider_roundtrip_seconds'] is not None)})
    assert {r['global_key'] for r in requests}==set(ledger['records'])
    trajectory=[]
    for arm in ('A','B'):
        best_id,best_fit=initial_best['id'],initial_best['fitness'];sent=0
        trajectory.append({'arm':arm,'actual_requests':0,'champion_id':best_id,'fitness':best_fit})
        for r in (x for x in requests if x['arm']==arm):
            sent+=bool(r['confirmed_sent'])
            if r['category']=='valid' and (r['fitness']>best_fit or
                (r['fitness']==best_fit and r['id']<best_id)):
                best_id,best_fit=r['id'],r['fitness']
            trajectory.append({'arm':arm,'actual_requests':sent,'champion_id':best_id,'fitness':best_fit})
    csvfile(out/'trajectory.csv',trajectory,['arm','actual_requests','champion_id','fitness'])
    csvfile(out/'requests.csv',requests, list(requests[0]) if requests else ['arm','id','confirmed_sent'])
    csvfile(out/'milestones.csv',milestones,list(milestones[0]) if milestones else ['arm','planned_boundary','actual_requests','champion_fitness'])
    csvfile(out/'all_candidate_instances.csv',instances,list(instances[0]) if instances else ['arm','id','file','makespan'])
    csvfile(out/'lineage.csv',lineage,['arm','child','parent','parent_is_new','operator'])
    csvfile(out/'populations.csv',populations,['arm','id','fitness','from_initial'])
    champions={'H0':H['members'][0]['training_result'],'INITIAL':initial_best['training_result'],'OLD_FROZEN':old['row']['training_result']}
    champion_ids={'H0':'fixed-h0','INITIAL':initial_best['id'],'OLD_FROZEN':old['row']['id']}
    champion_keys={'H0':H['members'][0].get('candidate',{}).get('key'),
        'INITIAL':initial_best['candidate']['key'],'OLD_FROZEN':old['row']['candidate']['key']}
    champion_origins={'H0':H.get('source_run'),'INITIAL':shared.get('source_run'),
        'OLD_FROZEN':old.get('source',{}).get('run')}
    for arm in ('A','B'):
        if states[arm].get('phase')=='completed':
            best=sorted(states[arm]['population'],key=lambda x:(-x['fitness'],x['id']))[0]
            champions[arm]=best.get('training_result') or evals[best['id']];champion_ids[arm]=best['id']
            champion_keys[arm]=best['candidate']['key']
            champion_origins[arm]=shared.get('source_run') if best['id'] in init_ids else run.name
    pairs=[];diffs=[]
    for a,b in [('B','A'),('A','H0'),('B','H0'),('A','OLD_FROZEN'),('B','OLD_FROZEN')]:
        if a not in champions or b not in champions:continue
        aa,bb=champions[a],champions[b];check_evaluation(aa,names);check_evaluation(bb,names)
        rows=[]
        for x,y in zip(aa['instances'],bb['instances']):
            assert x['file']==y['file'];rows.append({'A':a,'B':b,'file':x['file'],'A_makespan':x['makespan'],'B_makespan':y['makespan'],'A_minus_B_makespan':x['makespan']-y['makespan'],'A_minus_B_score':x['score']-y['score']})
        diffs.extend(rows);pairs.append({'A':a,'B':b,'fitness_difference':aa['fitness']-bb['fitness'],
            'A_wins':sum(x['A_minus_B_makespan']<0 for x in rows),'ties':sum(x['A_minus_B_makespan']==0 for x in rows),'A_losses':sum(x['A_minus_B_makespan']>0 for x in rows)})
    csvfile(out/'paired_instances.csv',diffs,['A','B','file','A_makespan','B_makespan','A_minus_B_makespan','A_minus_B_score'])
    csvfile(out/'paired_summary.csv',pairs,['A','B','fitness_difference','A_wins','ties','A_losses'])
    csvfile(out/'champion_instances.csv',[{'label':g,'source_run':champion_origins[g],'id':champion_ids[g],'code_key':champion_keys[g],'fitness':e['fitness'],**{k:x.get(k) for k in ['file','makespan','lower_bound','score','feasible','single_solve_seconds','deterministic_recheck_seconds','diagnostic_replay_seconds']}} for g,e in champions.items() for x in e['instances']])
    chain=next((x for x in lineage if x['arm']=='B' and x['parent_is_new']),None)
    if chain:
        folder=run/'r201/B';journal=read(folder/'budgeted_evolution_requests.json')['requests']
        parent=chain['parent'];child=chain['child'];entry=next(a for a in states['B']['attempts'] if a['id']==parent)
        assert entry['category']=='valid' and evals[parent]['valid']
        survived_at=next(n for n in (10,20) if (folder/f'Milestone_{n:02d}.json').exists() and parent in {x['id'] for x in read(folder/f'Milestone_{n:02d}.json')['actual_parent_pool']})
        case=out/'lineage_case';case.mkdir(exist_ok=True)
        for role,ident in [('new_parent',parent),('descendant',child)]:
            (case/(role+'.prompt.txt')).write_text(journal[ident]['prompt']);(case/(role+'.response.txt')).write_text(journal[ident].get('text','NO_RESPONSE'))
        dump(case/'evidence.json',{'parent_candidate':parent,'parent_evaluation':evals[parent],
            'selected_at_slots':survived_at,'descendant_attempt':next(x for x in states['B']['attempts'] if x['id']==child),
            'descendant_evaluation':evals.get(child),'source_milestone_sha256':sha(folder/f'Milestone_{survived_at:02d}.json'),
            'source_journal_sha256':sha(folder/'budgeted_evolution_requests.json'),
            'note':'Actual parent selection from updated B pool, not an inferred code resemblance.'})
        (case/'说明.md').write_text('# 真实新子代再次成为父代\n\n'
            f'新候选`{parent}`完整21train有效，fitness={evals[parent]["fitness"]}；'
            f'在第{survived_at}槽位后的实际父代池存活，随后被实际请求`{child}`选作父代。'
            '提示与响应均直接导出自原journal；完整评价及源文件哈希见evidence.json。'
            '被选作父代本身不证明后代更强，须结合后代实际评价。\n')
    summary={'run':run.name,'complete':all(states[a].get('phase')=='completed' for a in ('A','B')),
        'milestones':milestones,'champions':{k:{'id':champion_ids[k],'source_run':champion_origins[k],
            'code_key':champion_keys[k],'fitness':v['fitness']} for k,v in champions.items()},
        'comparison':pairs,'actual_requests':sum(r['confirmed_sent'] for r in requests),
        'known_points':sum(r['actual_platform_points'] for r in requests if r['actual_platform_points'] is not None),
        'unknown_fee_ids':[r['id'] for r in requests if r['confirmed_sent'] and r['actual_platform_points'] is None],
        'wire_input_tokens_known':sum(r['wire_input_tokens'] for r in requests if r['wire_input_tokens'] is not None),
        'wire_output_tokens_known':sum(r['wire_output_tokens'] for r in requests if r['wire_output_tokens'] is not None),
        'unknown_wire_usage_ids':[r['id'] for r in requests if r['confirmed_sent'] and r['wire_input_tokens'] is None],
        'invoice_input_tokens_known':sum(r['invoice_input_tokens'] for r in requests if r['invoice_input_tokens'] is not None),
        'invoice_output_tokens_known':sum(r['invoice_output_tokens'] for r in requests if r['invoice_output_tokens'] is not None),
        'categories_by_arm':{a:dict(Counter(r['category'] or r['status'] for r in requests if r['arm']==a)) for a in ('A','B')},
        'api_or_interruption_failure_ids':[r['id'] for r in requests if r['category'] in ('api_failure','interrupted_request')],
        'lineage_chain':chain,'initial_code_keys':[x['candidate']['key'] for x in p0],
        'source_shared_initial_hash':shared['source_shared_hash'],'protocol_sha256':sha(run/'protocol.json'),
        'budget_sha256':sha(run/'budget.json'),'budget_handoff':read(run/'Final_budget_handoff.json'),
        'scope':'one paired exploration, fixed existing H/P0, scalar ID, train21 only; no generalization/stability inference'}
    # Production completion proof binds saved native artifacts, not a report's
    # optimistic status. Handwritten report fixtures deliberately lack seals.
    if summary['complete'] and protocol.get('version'):
        from fjsp_usage.research_real.assets import check_seal
        from fjsp_usage.research.protocol import digest
        context=digest(protocol);proof={}
        for name,kind in [('H_frozen.json','H_frozen'),('r201/Shared_initial.json','Shared_initial')]:
            check_seal(read(run/name),kind=kind,mode='real',context=context);proof[name]=sha(run/name)
        for arm in ('A','B'):
            s=states[arm];assert s['inflight'] is None and len(s['attempts'])==30
            assert [x['operator'] for x in s['attempts']]==(['CROSS']*5+['MUTATE']*5)*3
            for x in s['attempts']:
                assert len(set(x['parents']))==(5 if x['operator']=='CROSS' else 1)
                if arm=='A':assert set(x['parents'])<=init_ids
            final=read(run/f'r201/{arm}/Final_population.json')
            check_seal(final,kind='Final_population',mode='real',context=context)
            assert [x['id'] for x in final['population']]==[x['id'] for x in s['population']]
            assert final['shared_initial_hash']==shared['artifact_sha256']
            for name in ('checkpoint.json','budgeted_evolution_requests.json','Final_population.json',
                         'Milestone_10.json','Milestone_20.json','Milestone_30.json'):
                rel=f'r201/{arm}/'+name;proof[rel]=sha(run/rel)
        for r in requests:
            import hashlib
            if not r['confirmed_sent']:continue
            rel='wire_responses/'+hashlib.sha256(r['global_key'].encode()).hexdigest()+'.json'
            w=read(run/rel);assert w['send_confirmed'] and w['global_key']==r['global_key']
            proof[rel]=sha(run/rel)
            if w['status']=='wire_completed_before_settlement':
                journal=read(run/f'r201/{r["arm"]}/budgeted_evolution_requests.json')['requests'][r['id']]
                assert w['reply']['text']==journal['text'] and w['reply']['usage']==journal['usage']
        for name in ('protocol.json','budget.json','History_binding.json','Final_budget_handoff.json'):
            proof[name]=sha(run/name)
        dump(out/'completion_verification.json',{'complete':True,'source_files_sha256':proof,
            'actual_requests':summary['actual_requests'],'known_points':summary['known_points'],
            'unknown_fees':summary['unknown_fee_ids'],'no_new_requests_or_evaluations':True})
    dump(out/'summary.json',summary)
    lines=['# 等预算更新频率对照：真实结果','',summary['scope'],'',
        'A30次期间只用P₀作父代，第30次后选拔；B每10次选拔更新。两组均采用原P特化提示及同一全局(5交叉+5变异)×3，交叉5个不同父代、变异1父代。父代选择初始RNG相同，去重独立；执行顺序预登记为A10/B10/A20/B20/A30/B30。云模型结果不保证相同。','',
        f"状态：完整={summary['complete']}；真实请求{summary['actual_requests']}，已核实点数{summary['known_points']}，未知费用{summary['unknown_fee_ids']}。",'',
        f"接入失败/中断：{summary['api_or_interruption_failure_ids']}。数量相等不代表接口条件完全相同；存在接入失败时保留全部槽位，并将结果标为受接口故障影响的配对探索，不把有效率或冠军差异完全归因于更新时间。",'',
        mdtable(milestones,['arm','planned_boundary','actual_requests','champion_id','champion_fitness','champion_is_new','above_initial_H0','at_least_old_frozen','actual_parent_pool_mean','observed_top5_mean','survival_updates','new_survivors_in_actual_pool','valid','code_duplicates']), '',
        '**口径。** 冠军是截至此时已发现的最佳完整有效候选（包含尚未进入A父代池的子代）；A10/20的observed_top5_mean仅为观察值，不改变父代。actual_parent_pool_mean才是实际父代种群均值。mean(−Cmax/未取整LB)越大越好；任何实例失败使整个候选无效。请求横轴采用确认发送次数，失败/重复计入预算，不补发。','',
        mdtable(pairs,['A','B','fitness_difference','A_wins','ties','A_losses']), '',
        f"实际子代成为父代证据：{chain}。" if chain else '没有观察到真实新子代成为父代的证据，不补造谱系。', '',
        '逐请求真实费用、wire及账单token见requests.csv；完整候选实例、单次求解、确定性复检及独立诊断分别保存。元数据等待不当作求解时间；公开费率不冒充实际账单，人民币/美元未知。历史未知记录及2400万点预留继承；新批不借用旧初始化额度。', '',
        f"账单已知token：输入{summary['invoice_input_tokens_known']}，输出{summary['invoice_output_tokens_known']}；wire已知token：输入{summary['wire_input_tokens_known']}，输出{summary['wire_output_tokens_known']}。wire未知请求为{summary['unknown_wire_usage_ids']}，不以账单字段覆盖原始wire用量；有账单扣费不等于得到有效候选。",'',
        '主要目标是更强冠军；仅均值提高、继承初始冠军或更多切换不算突破。固定H0 −2.111804961、旧冻结冠军 −2.070427514仅作标记的训练参照；后者未入种群、未重评。全部失败/重复和两组负结果均保留。单次配对不支持稳定性、因果确定性或泛化结论。', '',
        '## 入口与恢复','',
        '以下execute为原批唯一启动/续接命令，会发送剩余已授权请求；必须先核对.writer.lock中的PID与真实进程，活跃时不得再启动。recover只查询结算元数据，不能重发请求或清除无证据门禁。report仅从保存记录生成材料。','',
        '```bash\n.venv/bin/python -B -u experiments/tier2/research_real_v1/run_single_update.py execute \\\n  --run-dir runs/'+run.name+' \\\n  --env-file ../FJSP-Heuristic-Research/.env.leafapi.local\n\n.venv/bin/python -B experiments/tier2/research_real_v1/run_single_update.py recover \\\n  --run-dir runs/'+run.name+' \\\n  --env-file ../FJSP-Heuristic-Research/.env.leafapi.local\n\npython3 tools/report_single_update.py --run-dir runs/'+run.name+' \\\n  --out-dir reports/'+out.name+'\n```','',
        '[里程碑CSV](milestones.csv) · [逐请求](requests.csv) · [谱系](lineage.csv) · [逐实例对照](paired_instances.csv) · [最终交接]('+str(run/'Final_budget_handoff.json')+')。原始提示/响应和检查点在运行目录，快照含代码/配置/训练数据；不读取validation/test。']
    (out/'报告.md').write_text('\n'.join(lines)+'\n')
    if charts:
        import matplotlib
        matplotlib.use('Agg')
        from matplotlib import pyplot as plt,font_manager
        available={f.name for f in font_manager.fontManager.ttflist};font=next((f for f in ['Arial Unicode MS','PingFang HK','Noto Sans CJK SC'] if f in available),'DejaVu Sans')
        plt.rcParams.update({'font.family':font,'axes.unicode_minus':False,'svg.fonttype':'path','svg.hashsalt':'update-frequency-v1'})
        fig,ax=plt.subplots(figsize=(12,6.75))
        for arm,col in [('A','#2864AE'),('B','#239477')]:
            rows=[x for x in trajectory if x['arm']==arm];ax.step([x['actual_requests'] for x in rows],[x['fitness'] for x in rows],where='post',label=arm+('：30次后选拔' if arm=='A' else '：每10次选拔'),color=col)
        ax.axhline(H['members'][0]['fitness'],ls='--',color='#A34435',label='固定H0 / 初始最佳')
        ax.axhline(oldfit,ls=':',color='#8560A5',label='旧冻结冠军（不入种群）')
        ax.set(xlabel='本组累计确认发送的模型请求（失败、重复计入）',ylabel='完整21train冠军fitness，越大越好',title='等预算更新频率对照 · seed201 · 仅训练');ax.legend();ax.grid(alpha=.15)
        fig.tight_layout()
        for ext in ('png','svg'):
            path=out/f'冠军轨迹.{ext}';fig.savefig(path,dpi=180,metadata={'Date':None} if ext=='svg' else {})
            if ext=='svg':path.write_text('\n'.join(x.rstrip() for x in path.read_text().splitlines())+'\n')
        plt.close(fig)
        plot_pairs=[(a,b) for a,b in [('B','A'),('A','H0'),('B','H0')] if a in champions and b in champions]
        if plot_pairs:
            fig,axes=plt.subplots(len(plot_pairs),1,figsize=(13,3.2*len(plot_pairs)),squeeze=False)
            for ax,(a,b) in zip(axes[:,0],plot_pairs):
                rr=[x for x in diffs if x['A']==a and x['B']==b]
                values=[x['A_minus_B_makespan'] for x in rr]
                ax.bar(range(21),values,color=['#239477' if v<0 else '#BC6353' for v in values])
                ax.axhline(0,color='black',lw=.6);ax.set_xticks(range(21),[x['file'] for x in rr],rotation=55,ha='right',fontsize=7)
                ax.set_title(a+' 对 '+b+'：负值表示前者makespan更小');ax.set_ylabel('makespan差值')
            fig.tight_layout()
            for ext in ('png','svg'):
                path=out/f'逐实例比较.{ext}';fig.savefig(path,dpi=180,metadata={'Date':None} if ext=='svg' else {})
                if ext=='svg':path.write_text('\n'.join(x.rstrip() for x in path.read_text().splitlines())+'\n')
            plt.close(fig)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--out-dir',type=Path,required=True);p.add_argument('--no-charts',action='store_true');p.add_argument('--backup-dir',type=Path);a=p.parse_args()
    run,out=a.run_dir.resolve(),a.out_dir.resolve();s=build(run,out,charts=not a.no_charts)
    if a.backup_dir:s['backup']=backup(run,out,a.backup_dir.resolve())
    print(json.dumps({k:s[k] for k in ['complete','actual_requests','known_points','unknown_fee_ids','lineage_chain']}|({'backup':s['backup']} if 'backup' in s else {}),ensure_ascii=False))
