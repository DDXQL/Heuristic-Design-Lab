"""Research-oriented offline exports, separate from recovery bookkeeping."""
import csv
from pathlib import Path
from .storage import read, write
from .evolution_v1 import check
from .search import ranked


def export(directory,output=None):
    directory=Path(directory)
    p,s=check(directory)
    output=Path(output) if output else directory/'exports'
    output.mkdir(parents=True,exist_ok=True)
    records=[];best=None;valid_count=0
    for t in s['tasks'].values():
        if t['valid']:
            valid_count+=1
            best=max(best,t['fitness']) if best is not None else t['fitness']
        records.append({'id':t['id'],'stage':t['stage'],'generation':t['generation'],
            'operator':t['operator'],'parents':','.join(t['parents']),
            'subject':t.get('subject'),'status':t['status'],'valid':t['valid'],
            'fitness':t['fitness'],'best_so_far':best,'valid_unique_evaluations_so_far':valid_count,
            'failure':t.get('failure'),'duplicate_of':t.get('duplicate_of'),
            'api_batch_seconds':t.get('api_batch_seconds'),'evaluation_batch_seconds':t.get('evaluation_batch_seconds')})
    columns=list(records[0]) if records else ['id','status']
    with (output/'candidates.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(records)
    with (output/'generations.csv').open('w',newline='') as f:
        columns=['generation','planned_candidates','generation_requests','valid_unique_children','best_fitness',
                 'population_mean','behavior_groups','children_selected','population_ids','mock']
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(s['generations'])
    lineage=[{'child':t['id'],'generation':t['generation'],'operator':t['operator'],
              'subject':t.get('subject'),'parents':t['parents'],'parent_keys':t['parent_keys'],
              'candidate_key':t.get('candidate',{}).get('key'),'valid':t['valid'],
              'prompt_path':t.get('prompt_path'),'response_path':t.get('response_path')}
             for t in s['tasks'].values() if t['stage']=='evolution']
    write(output/'lineage.json',lineage)
    result={'version':p['version'],'protocol_sha256':s['identity'],'phase':s['phase'],
        'evaluation_mode':p['config']['evaluation_mode'],
        'generation_transport':'MOCK_OFFLINE_NOT_LLM' if p['config']['api_mode']=='mock' else p['config']['api_mode'],
        'quality_claim':False,'real_API_calls':sum(t.get('sent_confirmed',False) for t in s['tasks'].values()),
        'api_attempts_reserved':(s['initialization_requests']+s['generation_requests']) if p['config']['api_mode']=='real' else 0,
        'generation':s['generation'],
        'initialization_requests':s['initialization_requests'],'generation_requests':s['generation_requests'],
        'planned_evolution_candidates':2*p['config']['population_size']*p['config']['generations'],
        'valid_unique_evaluations':sum(r['valid'] for r in s['evaluations'].values()),
        'failed_or_duplicate_tasks':sum(t['status']=='completed' and not t['valid'] for t in s['tasks'].values()),
        'generations':s['generations'],'champion':ranked(s['population'])[0] if s['population'] else None,
        'H_order_source':p['H_order_source'],
        'timing_note':'per-task batch times are shared; do not sum them as wall time',
        'behavior_note':'mock: five artificial progress probes; solve: selected-H sequences on declared synthetic instances'}
    write(output/'summary.json',result)
    return result
