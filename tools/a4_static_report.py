"""Report persisted query results only. Template is also exercised on toy data."""
import csv
from pathlib import Path
from statistics import median
from fjsp_usage.a4_static.engine import Campaign,read,write


def report(directory,out):
    campaign=Campaign(directory);p,plans,state,flat=campaign.validate();out=Path(out);out.mkdir(exist_ok=True)
    queries=[];curves=[];repeats=[];instance_rows=[]
    actual={'first_starts':0,'recheck_starts':0,'complete_pair_markers':0,'primary_wall_seconds':0.,
            'successful_prefix_first_seconds':0.,'successful_prefix_recheck_seconds':0.,'h_scoring_seconds':0.,'fusion_seconds':0.}
    for repeat,seed in enumerate(p['search_seeds']):
        incumbent=None;incumbent_ticket=None;completed=0;valid=0
        for q in state['queries']:
            if q['repeat']!=repeat:continue
            result=read(Path(directory)/q['result_path']);completed+=1;valid+=result['valid']
            if result['valid'] and (incumbent is None or result['fitness']>incumbent):
                incumbent=result['fitness'];incumbent_ticket=q['ticket']
            curves.append({'repeat':repeat,'search_seed':seed,'slot':q['slot']+1,'ticket':q['ticket'],
                'valid':result['valid'],'fitness':result['fitness'],'best_so_far':incumbent,'incumbent_ticket':incumbent_ticket})
            queries.append({**q,'valid':result['valid'],'fitness':result['fitness']})
            indexed={r['file']:r for r in result['instances']}
            for expected in p['instances']:
                r=indexed.get(expected['file'])
                instance_rows.append({'repeat':repeat,'search_seed':seed,'slot':q['slot']+1,'ticket':q['ticket'],
                    'origin':q['origin'],'strategy_valid':result['valid'],'file':expected['file'],'LB':expected['LB'],
                    'Cmax':r['makespan'] if r else None,'score':r['score'] if r else None,
                    'status':('complete' if result['valid'] else 'success_prefix') if r else (
                        'failed' if expected['file']==result.get('failed_instance') else 'not_reached'),
                    'single_seconds':r.get('single_solve_seconds') if r else None,
                    'recheck_seconds':r.get('deterministic_recheck_seconds') if r else None})
            if q['origin']=='new':
                folder=(Path(directory)/q['result_path']).parent/'evidence'
                for path in folder.glob('*.progress.json'):
                    marker=read(path);actual['first_starts']+=marker['first_started'];actual['recheck_starts']+=marker['recheck_started']
                    actual['complete_pair_markers']+=marker['completed']
                actual['primary_wall_seconds']+=result.get('primary_evaluation_seconds',0.)
                actual['successful_prefix_first_seconds']+=sum(r.get('single_solve_seconds',0) for r in result['instances'])
                actual['successful_prefix_recheck_seconds']+=sum(r.get('deterministic_recheck_seconds',0) for r in result['instances'])
                for key in ('h_scoring_seconds','fusion_seconds'):
                    actual[key]+=sum(r.get(c,{}).get(key,0) for r in result['instances'] for c in ('first_costs','recheck_costs'))
        repeats.append({'repeat':repeat,'search_seed':seed,'consumed_queries':completed,
            'complete_at_declared_budget':completed==p['queries_per_repeat'],'valid_queries':valid,
            'final_fitness':incumbent,'best_ticket':incumbent_ticket,
            'status':'complete' if completed==p['queries_per_repeat'] else 'partial_or_not_started'})
    for name,rows in [('Queries.csv',queries),('Best_so_far.csv',curves),('Repeats.csv',repeats),('All_instances.csv',instance_rows)]:
        if rows:
            with (out/name).open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
    values=[r['final_fitness'] for r in repeats if r['complete_at_declared_budget'] and r['final_fitness'] is not None]
    ordered=sorted(values)
    def quantile(q):
        if not ordered:return None
        x=(len(ordered)-1)*q;i=int(x);j=min(i+1,len(ordered)-1)
        return ordered[i]+(ordered[j]-ordered[i])*(x-i)
    summary={'mode':p['mode'],'phase':state['phase'],'completed_repeats':sum(r['complete_at_declared_budget'] for r in repeats),
        'completed_repeats_with_no_valid_strategy':sum(r['complete_at_declared_budget'] and r['final_fitness'] is None for r in repeats),
        'queries_consumed':len(queries),'candidates_precommitted':sum(map(len,plans)),
        'logical_evaluations_reserved':sum(q['logical_evaluations'] for q in queries),
        'physical_evaluations_reserved':sum(q['physical_reserved_evaluations'] for q in queries),
        'physical_passes_reserved':sum(q['physical_reserved_passes'] for q in queries),
        'valid_queries':sum(q['valid'] for q in queries),'invalid_queries':sum(not q['valid'] for q in queries),
        'unique_tickets':len({q['ticket'] for q in queries}),
        'within_repeat_duplicate_queries':sum(len([q for q in queries if q['repeat']==r])-len({q['ticket'] for q in queries if q['repeat']==r}) for r in range(len(plans))),
        'historical_cache_hits':sum(q['origin']=='historical_cache' for q in queries),
        'campaign_cache_hits':sum(q['origin']=='campaign_cache' for q in queries),
        'complete_repeat_quality':{'n':len(values),'median':median(values) if values else None,
            'min':min(values) if values else None,'max':max(values) if values else None,'q25':quantile(.25),'q75':quantile(.75)},
        'actual_new_evaluation_markers_and_costs':actual,
        'invalid_rate':sum(not q['valid'] for q in queries)/len(queries) if queries else None,
        'construction_legal_rate':1. if queries else None,
        'failed_internal_solve_time':'unknown if terminated; parent wall included; no zero-filled failure cost',
        'LLM_API_requests':0,'note':'No valid-prefix fitness; partial repeats are not full-budget final estimates. Search seeds, not solver timing replicates.'}
    write(out/'Summary.json',summary)
    external=[{'repeat':r['repeat'],'search_seed':r['search_seed'],'complete_repeat':r['complete_at_declared_budget'],
        'reference':label,'reference_fitness':value,'delta_F':r['final_fitness']-value if r['final_fitness'] is not None else None}
        for r in repeats for label,value in p.get('external_reference_fitness',{}).items()]
    if external:
        with (out/'External_reference_comparison.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(external[0]),lineterminator='\n');w.writeheader();w.writerows(external)
    (out/'REPORT_ZH.md').write_text('# A4运行结果（从存档生成）\n\n'+
        ('本文件为合成验收输出，不能称为正式A4实验。\n\n' if p['mode']!='formal' else '')+
        f"完成重复 {summary['completed_repeats']}/{len(plans)}；查询 {len(queries)}；有效 {summary['valid_queries']}。\n\n"+
        '正式报告还须列逐实例Cmax、相对外部基线差、完整重复质量分布/IQR、合法率、重复和缓存率、实际求解启动及资源成本；原始证据由查询目录和provenance绑定。\n')
    return summary
