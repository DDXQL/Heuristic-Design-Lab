#!/usr/bin/env python3
"""Independent one-step selection audits on archived pools, never a new search.
Every generation uses ITS ORIGINAL parents and children; changed choices are NOT
propagated to later generations. No U execution, evaluator, API or solver import.
"""
import argparse,csv,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
from heuristic_design.core.search import survive,survive_behavior_first
from heuristic_design.core.storage import read,sha,write


def replay(source,output):
    source=Path(source).resolve();output=Path(output).resolve()
    if output.exists():raise FileExistsError('new offline output directory required')
    p=read(source/'Protocol.json');s=read(source/'checkpoint.json')
    if s['phase']!='completed' or s['identity']!=sha(source/'Protocol.json') or read(source/'Protocol.receipt.json')['sha256']!=sha(source/'Protocol.json'):
        raise ValueError('Completed source with intact protocol required')
    if read(source/'checkpoint.receipt.json')!={'identity':s['identity'],'sha256':sha(source/'checkpoint.json')}:
        raise ValueError('Checkpoint receipt mismatch')
    rows=[];samples=[]
    for g in range(1,s['generation']+1):
        record=s['plans'][str(g)];path=source/record['path']
        if sha(path)!=record['sha256']:raise ValueError('Parent plan changed')
        plan=read(path);parents=plan['population'];children=[]
        for task in plan['tasks']:
            t=s['tasks'][task['id']]
            if t['valid']:
                ev=s['evaluations'][t['candidate']['key']]
                children.append({'id':t['id'],'fitness':t['fitness'],'behavior_sha256':ev['behavior_sha256']})
        n=p['config']['population_size'];a=survive(parents,children,n);b=survive_behavior_first(parents,children,n)
        original=read(source/f'populations/P{g:03d}.json')
        assert [r['id'] for r in a]==[r['id'] for r in original]
        assert a[0]['id']==b[0]['id'] and a[0]['fitness']==b[0]['fitness']
        row={'generation':g,'pool_size':len(parents)+len(children),
          'A_groups':len({r['behavior_sha256'] for r in a}),'B_groups':len({r['behavior_sha256'] for r in b}),
          'A_best':a[0]['fitness'],'B_best':b[0]['fitness'],
          'A_mean':sum(r['fitness'] for r in a)/n,'B_mean':sum(r['fitness'] for r in b)/n,
          'different_selected_IDs':len({r['id'] for r in b}-{r['id'] for r in a})}
        rows.append(row)
        if g in (1,14,22,30,50):samples.append({'generation':g,'A':a,'B':b})
    output.mkdir(parents=True)
    with (output/'selection_audit.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    # Do not duplicate candidate code in the compact audit.
    write(output/'sample_selections.json',[{'generation':r['generation'],**{a:[{k:x[k] for k in ('id','fitness','behavior_sha256')} for x in r[a]] for a in ('A','B')}} for r in samples])
    result={'original_source':str(source),'protocol_sha256':sha(source/'Protocol.json'),'checkpoint_sha256':sha(source/'checkpoint.json'),
      'generations_audited':len(rows),'A_matches_archived_selection':True,'global_elite_unchanged_for_each_original_pool':True,
      'generations_with_different_selection':sum(r['different_selected_IDs']>0 for r in rows),
      'generations_with_more_retained_groups':sum(r['B_groups']>r['A_groups'] for r in rows),
      'examples':[r for r in rows if r['generation'] in (14,22,30,50)],
      'limitation':'Independent one-step pool audits only. B choices are not propagated; cannot infer B future offspring, full trajectory or final superiority. Greater group coverage can reduce current population mean Fitness.',
      'API_requests':0,'solves':0}
    write(output/'summary.json',result);return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();print(json.dumps(replay(args.source,args.output),ensure_ascii=False,indent=2))
