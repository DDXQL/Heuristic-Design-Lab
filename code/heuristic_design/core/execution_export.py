"""Deterministic exports from settled receipts; never evaluates a candidate."""
import csv
from pathlib import Path
from xml.sax.saxutils import escape
from .storage import read, write


def table(path,rows,columns):
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore')
        writer.writeheader();writer.writerows(rows)


def export(directory,p,s):
    from .execution_contract import champion
    out=Path(directory)/'exports';out.mkdir(exist_ok=True)
    tasks=[t for t in s['tasks'].values() if t['status']=='completed']
    known_usage={'input_tokens':0,'output_tokens':0};unknown_usage=0
    records=[];per_instance=[];best=None;valid=0;attempt=0;evo=0
    for t in tasks:
        if 'request_key' in t:attempt+=1
        if t['stage']=='evolution':evo+=1
        if t.get('valid'):
            valid+=1
            best=min(best,-t['fitness']) if best is not None else -t['fitness']
        usage=t.get('usage')
        if p['config']['api_mode']=='real' and 'request_key' in t:
            if usage is None:unknown_usage+=1
            else:
                for k in known_usage:known_usage[k]+=usage[k]
        records.append({'id':t['id'],'stage':t['stage'],'generation':t['generation'],
            'operator':t['operator'],'parents':','.join(t['parents']),
            'attempt':attempt,'evolution_attempt':evo,'status':t['status'],'valid':t['valid'],
            'J':-t['fitness'] if t.get('valid') else None,'best_J':best,
            'valid_unique_evaluations':valid,'failure':t.get('failure'),
            'api_outcome':t.get('api_outcome'),'send_state':t.get('send_state'),
            'http_status':t.get('http_status'),'failure_stage':t.get('failure_stage'),
            'input_tokens':usage.get('input_tokens') if usage else None,
            'output_tokens':usage.get('output_tokens') if usage else None,
            'actual_cost':None,'source_H_attempts':p.get('source_cost',{}).get('H_attempts'),
            'attempts_including_H':attempt+p['source_cost']['H_attempts'] if p.get('source_cost',{}).get('H_attempts') is not None else None})
    for key,ev in s['evaluations'].items():
        result=read(Path(directory)/ev['path'])
        for row in result.get('instances',[]):
            solution=row.get('solution',{})
            per_instance.append({'candidate_key':key,'file':row['file'],'valid':result['valid'],
                'raw_cost':row.get('raw_cost',solution.get('makespan')),'reference':row.get('reference'),
                'J':row['score'] if result['valid'] else None,'partial_observed_J':row['score'],
                'member_sequence':row.get('member_sequence'),'h_calls':row.get('h_calls'),
                'solve_seconds':row.get('solve_seconds'),'recheck_seconds':row.get('recheck_solve_seconds'),
                'worker_peak_rss_bytes':row.get('worker_peak_rss_bytes'),
                'semantic_sha256':row.get('semantic_sha256'),'recheck_semantic_sha256':row.get('recheck_semantic_sha256')})
    table(out/'candidates.csv',records,list(records[0]) if records else ['id','J'])
    table(out/'per_instance.csv',per_instance,['candidate_key','file','valid','raw_cost','reference','J',
          'partial_observed_J','member_sequence','h_calls','solve_seconds','recheck_seconds',
          'worker_peak_rss_bytes','semantic_sha256','recheck_semantic_sha256'])
    table(out/'generations.csv',s['generations'],list(s['generations'][0]) if s['generations'] else ['generation'])
    # Initializations have their own denominator; unknown sends are excluded.
    api=[]
    for stage in ('initialization','evolution'):
        selected=[t for t in tasks if t['stage']==stage and t.get('api_outcome') in ('accepted','transport_failed','response_rejected')]
        blocks=sorted({(i//100)*100 for i in range(len(selected))}) or [0]
        for start in blocks:
            group=selected[start:start+100]
            failures=sum(t['api_outcome'] in ('transport_failed','response_rejected') for t in group)
            api.append({'stage':stage,'settled_start':start+1,'settled_end':start+len(group),
                'settled_API_attempts':len(group),'API_failures':failures,
                'failure_fraction':failures/len(group) if group else None})
    table(out/'api_intervals.csv',api,['stage','settled_start','settled_end','settled_API_attempts','API_failures','failure_fraction'])
    c=champion(s)
    if c:
        write(out/'champion.json',{'id':c['id'],'candidate':c['candidate'],'J':-c['fitness'],
             'protocol_sha256':s['identity'],'selection_scope':'ALL complete valid settled prefix candidates'})
        (out/'champion.py').write_text(c['candidate']['code'])
    summary={'label':'MOCK_ENGINEERING_ONLY' if p['config']['evaluation_mode']=='mock' else 'TRAINING_SEARCH',
        'run_id':p['run_id'],'phase':s['phase'],'protocol_sha256':s['identity'],
        'initialization_attempts':s['initialization_requests'],'evolution_attempts':s['generation_requests'],
        'request_reservations':s['initialization_requests']+s['generation_requests'],
        'confirmed_sends':sum(t.get('sent_confirmed') or t.get('send_state')=='confirmed' for t in s['tasks'].values()),
        'unknown_sends':sum('request_key' in t and not t.get('sent_confirmed') and t.get('send_state') not in ('confirmed','not_sent') for t in s['tasks'].values()) if p['config']['api_mode']=='real' else 0,
        'valid_unique_evaluations':valid,'evaluation_reservations':sum(t.get('evaluation_timing') is not None or t['status']=='evaluation_reserved' for t in s['tasks'].values()),
        'candidate_failures':sum(t.get('failure') in ('parse_or_constraint','evaluation_invalid') for t in tasks),
        'duplicates':sum(t.get('failure')=='AST_duplicate' for t in tasks),
        'cancelled_before_dispatch':sum(t.get('failure')=='cancelled_before_dispatch' for t in tasks),
        'known_usage_subtotal':known_usage if p['config']['api_mode']=='real' else None,
        'unknown_usage_attempts':sum('request_key' in t and t.get('usage') is None for t in s['tasks'].values()) if p['config']['api_mode']=='real' else 0,
        'actual_cost':None,'currency_hard_cap_verified':False,
        'automatic_retries':0,'source_H_cost':p['source_cost'],'best_J':-c['fitness'] if c else None,
        'champion_id':c['id'] if c else None,'calendar_clock':read(Path(directory)/'Run_clock.json') if (Path(directory)/'Run_clock.json').exists() else None,
        'timing_scope':'task timings are per function; batch durations are shared, never summed as wall time',
        'real_requests':0 if p['config']['api_mode']=='mock' else 'see confirmed/unknown sends',
        'real_solves':0 if p['config']['evaluation_mode']=='mock' else 'see lifecycle receipts'}
    write(out/'summary.json',summary)
    curve=[r for r in records if r['best_J'] is not None]
    plot(out/'best-J-by-attempt.svg',curve,'attempt',summary['label'])
    plot(out/'best-J-by-evaluation.svg',curve,'valid_unique_evaluations',summary['label'])
    return summary


def plot(path,rows,key,label):
    if not rows:return
    xs=[r[key] for r in rows];ys=[r['best_J'] for r in rows]
    lo=min(ys);hi=max(ys);span=hi-lo or 1
    points=' '.join(f'{55+650*x/max(xs or [1]):.2f},{310-250*(y-lo)/span:.2f}' for x,y in zip(xs,ys))
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="760" height="370" viewBox="0 0 760 370">'
        f'<rect width="760" height="370" fill="white"/><text x="55" y="24" font-family="sans-serif" font-size="16">{escape(label)} — best training J</text>'
        f'<path d="M55 45V310H710" fill="none" stroke="black"/><polyline points="{points}" fill="none" stroke="#176b9a" stroke-width="2"/>'
        f'<text x="55" y="345" font-family="sans-serif">{key}; J range {lo:.6g}–{hi:.6g}; lower is better</text></svg>\n')
