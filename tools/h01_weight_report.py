"""Saved primary results only; no model calls, re-evaluation or state replay."""
from collections import Counter
import ast
import hashlib
import json
import re
from pathlib import Path
from statistics import fmean

from fjsp_usage.research.candidates import parse_response
from fjsp_usage.research.evolution import ranked
from fjsp_usage.research_real.assets import check_result
from fjsp_usage.research.protocol import digest
from tools import usage_mechanism_ablation as common
from tools.report_usage_ablation import costs, outcome, table


def recorded_costs(result):
    # Interrupted evaluation never fabricates elapsed time or a zero-cost run.
    return costs({**result,'primary_evaluation_seconds':result.get('primary_evaluation_seconds')})


def alpha_profile(result, constant=None):
    rows = []
    all_values = []
    all_dominants = []
    switches = 0
    for instance in result['instances']:
        values = instance.get('observed_alpha')
        if values is None and constant is not None:
            # Analytic constant, not an observed dynamic profile.
            values = [constant]
        if values is None:
            rows.append({'file':instance['file'],'alpha_min':None,'alpha_max':None,'unknown':True});continue
        dominants = ([d[3] for d in instance['decision_support_weights']]
                     if constant is None and 'decision_support_weights' in instance
                     else [0 if a >= .5 else 1 for a in values])
        changes = sum(a != b for a,b in zip(dominants,dominants[1:]))
        switches += changes; all_values += values; all_dominants += dominants
        rows.append({'file':instance['file'],'alpha_min':min(values),'alpha_max':max(values),
            'distinct_alpha':len(set(values)), 'dominant_switches':changes,
            'observed_steps':len(values) if constant is None else None,
            'basis':'primary solve' if constant is None else 'analytic constant'})
    return {'alpha_min':min(all_values) if all_values else None,'alpha_max':max(all_values) if all_values else None,
        'distinct_alpha':len(set(all_values)) if all_values else None,
        'dominants':sorted(set(all_dominants)), 'dominant_switches':switches,
        'training_alpha_varies':len(set(all_values))>1 if all_values else None,
        'any_within_instance_alpha_varies':any(r.get('distinct_alpha',0)>1 for r in rows),
        'per_instance':rows, 'scope':'complete trajectory' if result['valid'] else 'success prefix; failed portion unknown'}


def report(run, out=None):
    import reportlab  # Fail before creating outputs; use the bundled artifact Python.
    from tools.h01_weight_search import pins_check, validate, VERSION
    plan = pins_check(run)
    out = Path(out) if out is not None else common.ROOT/'reports'/run.name
    out.mkdir(exist_ok=False)
    (out/'sources').mkdir()
    references, summaries, instances, comparison = {}, [], [], []
    for version in plan['versions']:
        path = run/'results'/f'{version["id"]}.json'
        if not path.exists():
            summaries.append({'id':version['id'],'kind':'fixed_grid','alpha':version['alpha'],
                'valid':None,'fitness':None,'status':'not_evaluated'});continue
        result = common.read(path); check_result(result,plan['names'])
        references[version['id']] = result
        summaries.append({'id':version['id'],'kind':'fixed_grid','alpha':version['alpha'],
            'reused':version['reused'],**recorded_costs(result)})
    complete_grid = len(references)==21
    valid_grid = [k for k,v in references.items() if v['valid']]
    best_grid = max(valid_grid,key=lambda k:references[k]['fitness']) if valid_grid else None
    equal = references.get('alpha_050')
    initial = common.read(run/'Initial_population.json')
    initial_champion = ranked(initial)[0]
    results = dict(references)
    checkpoint = run/'r501/B/checkpoint.json'
    generation_rows = [{'generation':0,'best_fitness':initial_champion['fitness'],
        'mean_fitness':fmean(r['fitness'] for r in initial),'population_ids':';'.join(r['id'] for r in ranked(initial))}]
    lineage, profiles, new_ids, request_rows = [], {}, [], []
    state = common.read(checkpoint) if checkpoint.exists() else None
    if state:
        from fjsp_usage.usage_v2 import VERSION as INTERFACE
        journal = common.read(run/'r501/B/budgeted_evolution_requests.json')['requests']
        for attempt in state['attempts']:
            record = journal[attempt['id']]
            usage = record.get('usage')
            bill_path = run/'billing'/(hashlib.sha256(record['global_key'].encode()).hexdigest()+'.json')
            bill = common.read(bill_path) if bill_path.exists() else {}
            request_rows.append({'id':attempt['id'],'global_key':record['global_key'],'status':attempt['status'],
                'input_tokens':usage['input_tokens'] if usage is not None else None,
                'output_tokens':usage['output_tokens'] if usage is not None else None,
                'request_seconds':record.get('elapsed_seconds'),
                'actual_platform_points':bill.get('actual_platform_units') if bill.get('status')=='invoice_account_matched' else None,
                'billing_status':bill.get('status','not_recorded')})
            lineage.append({**{k:v for k,v in attempt.items() if k != 'parents'},
                'parents':';'.join(attempt['parents']),'prompt_key':record['prompt_key']})
            if record['status'] != 'completed':continue
            envelope = re.fullmatch(r'\s*\{([^{}]+)\}\s*```python\s*\n(.*?)\n```\s*',record['text'],flags=re.DOTALL)
            if envelope:
                (out/'sources'/(attempt['id'].replace('/','_')+'_proposed.py')).write_text(envelope.group(2)+'\n')
            try:
                parsed = parse_response(record['text'],interface_version=INTERFACE,member_count=10)
                candidate = validate(parsed.code,parsed.description)
            except ValueError:continue
            source = out/'sources'/(attempt['id'].replace('/','_')+'.py')
            source.write_text(candidate.code)
            result = state['evaluations'].get(attempt['id'],{}).get('result')
            if result is None:continue
            check_result(result,plan['names']); results[attempt['id']] = result; new_ids.append(attempt['id'])
            profile = alpha_profile(result); profiles[attempt['id']] = profile
            from fjsp_usage.research.candidates import U_ARGS
            profile['state_inputs_read'] = sorted({n.id for n in ast.walk(ast.parse(candidate.code)) if isinstance(n,ast.Name) and n.id in U_ARGS})
            profile['provably_input_independent'] = not profile['state_inputs_read']
            summaries.append({'id':attempt['id'],'kind':'LLM_new','alpha':None,**recorded_costs(result),
                'alpha_min':profile['alpha_min'],'alpha_max':profile['alpha_max'],
                'training_alpha_varies':profile['training_alpha_varies'],
                'fitness_minus_equal':result['fitness']-equal['fitness'] if result['valid'] and equal else None,
                'fitness_minus_grid_best':result['fitness']-references[best_grid]['fitness'] if result['valid'] and complete_grid and best_grid else None,
                'fitness_minus_initial_champion':result['fitness']-initial_champion['fitness'] if result['valid'] else None})
        # Reconstruct only from already evaluated rows and the unchanged stable
        # survival rule. No new evaluator invocation or outcome-dependent search.
        population = list(initial)
        for gen in (0,1):
            outcomes = [a for a in state['attempts'] if f'/g{gen:04d}/' in a['id']]
            if len(outcomes) != 10:break
            children = []
            for a in outcomes:
                if a['status'] != 'valid':continue
                c = parse_response(journal[a['id']]['text'],interface_version=INTERFACE,member_count=10)
                r = results[a['id']]
                children.append({'id':a['id'],'candidate':{'key':c.key},'fitness':r['fitness']})
            population = ranked(population+children)[:5]
            generation_rows.append({'generation':gen+1,'best_fitness':population[0]['fitness'],
                'mean_fitness':fmean(r['fitness'] for r in population),
                'population_ids':';'.join(r['id'] for r in population)})
    for key,result in results.items():
        indexed = {r['file']:r for r in result['instances']}
        for name in plan['names']:
            row = indexed.get(name)
            status = 'complete' if row else 'failed' if name==result.get('failed_instance') else 'not_reached_or_unknown'
            instances.append({'id':key,'file':name,'candidate_complete_valid':result['valid'],'status':status,
                'makespan':row['makespan'] if row else None,'score':row['score'] if row else None,
                'physical_schedule_sha256':row.get('physical_schedule_sha256') if row else None})
            for ref in dict.fromkeys(['alpha_050',best_grid]):
                if ref is None or ref not in references:continue
                other = next((r for r in references[ref]['instances'] if r['file']==name),None)
                comparison.append({'id':key,'reference':ref,'file':name,'candidate_complete_valid':result['valid'],
                    'Cmax_delta':row['makespan']-other['makespan'] if row and other else None,
                    'score_delta':row['score']-other['score'] if row and other else None,
                    'outcome':outcome(row['makespan'],other['makespan']) if row and other else None,
                    'same_physical_schedule':row['physical_schedule_sha256']==other['physical_schedule_sha256']
                        if row and other and row.get('physical_schedule_sha256') and other.get('physical_schedule_sha256') else None})
    counts = []
    for key,ref in dict.fromkeys((r['id'],r['reference']) for r in comparison):
        rows=[r for r in comparison if r['id']==key and r['reference']==ref]
        counts.append({'id':key,'reference':ref,'candidate_complete_valid':results[key]['valid'],
            **{label:sum(r['outcome']==label for r in rows) for label in ('win','loss','tie')},
            'unknown':sum(r['outcome'] is None for r in rows),
            'notice':'complete train21' if results[key]['valid'] else 'success prefix only; complete fitness null'})
    for name,rows in [('Candidates.csv',summaries),('Instances.csv',instances),('Comparisons.csv',comparison),
                       ('Win_loss_tie.csv',counts),('Generations.csv',generation_rows),('Lineage.csv',lineage),('Requests.csv',request_rows)]:
        if rows:
            fields = list(dict.fromkeys(k for row in rows for k in row))
            table(name,[{k:row.get(k) for k in fields} for row in rows],out=out)
    budget = common.read(run/'Budget_summary.json') if (run/'Budget_summary.json').exists() else None
    actual_points = 0; unknown = []
    for path in (run/'billing').glob('*.json'):
        bill = common.read(path)
        if bill.get('status')=='invoice_account_matched':actual_points += bill['actual_platform_units']
        else:unknown.append(bill.get('global_key'))
    best_new = max((k for k in new_ids if results[k]['valid']),key=lambda k:results[k]['fitness'],default=None)
    attempts = state['attempts'] if state else []
    legal = sum(a['status'] in ('valid','invalid','duplicate') for a in attempts)
    duplicates = sum(a['status']=='duplicate' for a in attempts)
    evidence = {'version':VERSION,'run':str(run),'fixed_grid_complete':complete_grid,'best_grid':best_grid,
        'best_grid_alpha':next(v['alpha'] for v in plan['versions'] if v['id']==best_grid) if best_grid else None,
        'initial_champion':initial_champion['id'],'best_new':best_new,
        'best_new_profile':profiles.get(best_new),'generation_rows':generation_rows,
        'attempt_status_counts':dict(Counter(a['status'] for a in state['attempts'])) if state else {},
        'request_slot_denominator':len(attempts),'legal_candidates':legal,
        'legal_rate':legal/len(attempts) if attempts else None,
        'duplicate_rate':duplicates/len(attempts) if attempts else None,
        'known_actual_platform_points':actual_points,'unknown_billing_keys':unknown,
        'budget':budget,'alpha_profiles':profiles,'source_pins':plan['pins'],
        'new_evaluations_completed':sum(not v['reused'] and v['id'] in references for v in plan['versions'])+len(new_ids),
        'new_single_solve_seconds_certified':sum(recorded_costs(results[k])['single_solve_seconds'] for k in new_ids),
        'new_recheck_seconds_certified':sum(recorded_costs(results[k])['recheck_seconds'] for k in new_ids),
        'cost_totals_notice':'certified successful solve/recheck pairs only; incomplete failed costs remain unknown',
        'training_exploration_only':True,'independent_validation':False,'no_extra_replays':True}
    atomic = common.write
    atomic(out/'Evidence.json',evidence)
    lines = ['# H0/H1权重搜索：训练探索', '',
        f'固定网格完成：{complete_grid}；最佳alpha：{evidence["best_grid_alpha"]}；新模型候选最佳：{best_new}。',
        f'初始池冠军：{initial_champion["fitness"]:.12f}。继承初始池的成绩不计为模型收益。',
        f'已核对实际费用：{actual_points}平台点；未解决账单：{len(unknown)}；金额不换算为人民币。',
        '常量或轨迹中不变权重归为常量/观测不变权重；仅权重变化不能证明收益。',
        '比较使用完整21train平均-Cmax/LB，任一失败则fitness为空；前缀不代替完整成绩。',
        '端点采用单成员语义复用，旧计时不包含新alpha检查开销；精确速度差异不可据此归因。',
        '超过有限细网格也不能证明超过所有固定权重；独立验证和重复实验另行安排。']
    if best_new:
        score=results[best_new]['fitness']; profile=profiles[best_new]
        classification=('输入无关的常量权重优化' if profile['provably_input_independent'] else
            '训练轨迹中权重发生变化' if profile['training_alpha_varies'] else '训练轨迹权重不变，其他状态未知')
        lines += [f'最佳新候选fitness={score:.12f}；分类：{classification}。',
            f'相对等权差值={score-equal["fitness"]:.12f}；相对初始冠军差值={score-initial_champion["fitness"]:.12f}。',
            f'alpha范围=[{profile["alpha_min"]},{profile["alpha_max"]}]，实际主导切换={profile["dominant_switches"]}。']
        if complete_grid and best_grid:
            lines += [f'相对有限细网格冠军差值={score-references[best_grid]["fitness"]:.12f}。']
            if score<=references[best_grid]['fitness']:lines += ['本批未观察到新候选超过有限固定权重参照，不能宣称动态性有收益。']
    (out/'Report.md').write_text('\n'.join(lines)+'\n')
    plot(out,summaries,comparison,best_new,best_grid)
    print(json.dumps({k:evidence[k] for k in ('fixed_grid_complete','best_grid_alpha','best_new','known_actual_platform_points')},ensure_ascii=False))


def plot(out,summaries,comparisons,best_new,best_grid):
    from tools.plot_usage_ablation import base, chart
    from reportlab.graphics import renderSVG
    from reportlab.graphics.shapes import String
    rows = sorted((r for r in summaries if r['kind']=='fixed_grid'),key=lambda r:r['alpha'])
    drawing = base('Fixed H0/H1 weight reference grid','Train21 fitness; higher is better. Gaps denote failed or not-evaluated references.')
    # Split the curve at missing/failed references, never interpolate over them.
    segments, points = [], []
    for row in rows:
        if row.get('valid'):points.append((row['alpha'],row['fitness']))
        elif points:segments.append(points);points=[]
    if points:segments.append(points)
    if segments:
        axis=chart(drawing,segments);axis.xValueAxis.valueMin=0;axis.xValueAxis.valueMax=1
    drawing.add(String(75,65,'alpha = H0 raw weight; H1 = 1-alpha',fontSize=11))
    drawing.add(String(75,40,'Missing/failed: '+(', '.join(str(r['alpha']) for r in rows if not r.get('valid')) or 'none'),fontSize=10))
    renderSVG.drawToFile(drawing,str(out/'Fixed_weight_curve.svg'))
    if best_new:
        for ref in dict.fromkeys(('alpha_050',best_grid)):
            rows=[r for r in comparisons if r['id']==best_new and r['reference']==ref]
            drawing=base(best_new+' versus '+str(ref),'Cmax delta by instance; below zero is an improvement; missing points are unknown.')
            data=[(i+1,r['Cmax_delta']) for i,r in enumerate(rows) if r['Cmax_delta'] is not None]
            if data:
                axis=chart(drawing,[data],joined=False)
                axis.xValueAxis.valueMin=1;axis.xValueAxis.valueMax=21
                axis.xValueAxis.valueSteps=list(range(1,22))
                axis.xValueAxis.labelTextFormat=lambda x:rows[int(round(x))-1]['file'].replace('Behnke','').replace('.fjsp','')
            renderSVG.drawToFile(drawing,str(out/f'Best_new_vs_{ref}.svg'))
