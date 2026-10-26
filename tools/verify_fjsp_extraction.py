"""Capture full FJSP semantic traces and certified CLI results in NEW runs."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'code')]
import argparse
import csv
from dataclasses import asdict
import subprocess
from tools import experiment_ops as o

REPORT=ROOT/'reports/generic-extraction-20261026-v1'

def capture(tag):
    target=REPORT/(tag+'.json')
    if target.exists():raise ValueError('never overwrite captured evidence')
    c=o.read(ROOT/'experiments/tier2/ops/configs/fixed-toy.json')
    c['question']='FJSP extraction regression: toy + certified Behnke1'
    c['dataset']['files'].append('runs/baseline-a-supplemental-T30-seed501-20261024-v1/inputs/train/Behnke1.fjsp')
    config=REPORT/(tag+'.config.json');o.write(config,c)
    d=o.describe(config)
    rules=tuple(o.certified.compile_candidate(o.checked_candidate(m['candidate'],'h')) for m in d['H']['members'])
    semantic={}
    for task in d['tasks']:
        fn=o.certified.compile_candidate(o.checked_candidate(task['candidate'],'U'))
        for row in d['instances']:
            instance=o.certified.s.v2.load_instance(row['source']);passes=[]
            for _ in range(2):
                trace=[];r=o.certified.construct_usage_schedule(instance,rules,fn,trace=trace.append,max_actions=10000)
                passes.append({'result':asdict(r),'trace':trace})
            assert passes[0]==passes[1]
            semantic[task['id']+'/'+row['file']]=passes
    run=ROOT/'runs'/('fjsp-extraction-'+tag+'-20261026-'+('v2' if tag=='after' else 'v1'))
    if not run.exists():o.prepare(config,run)
    if o.read(run/'checkpoint.json')['phase']!='completed':subprocess.run([sys.executable,'-B',str(ROOT/'experiments/tier2/manage.py'),'run','--run-dir',str(run)],check=True,stdout=subprocess.DEVNULL)
    s=o.read(run/'checkpoint.json');assert s['phase']=='completed'
    certified={}
    for tid,t in s['tasks'].items():
        result=o.read(run/s['evaluations'][t['evaluation_key']]['path'])
        assert result['valid']
        certified[tid]={'fitness':result['fitness'],'rows':[{k:r[k] for k in ('file','makespan','lower_bound','score','physical_schedule_sha256','recheck_physical_schedule_sha256','commit_sequence_sha256','single_h_calls','recheck_h_calls')} for r in result['instances']]}
    historical=list(csv.DictReader((ROOT/'reports/baseline-a-supplemental-T30-seed501-20261024-v1/All_instances_189.csv').open()))
    historical_match=[]
    for tid,old_id in [('H0_SELECT','H0'),('equal','H0_H1_WS')]:
        row=next(r for r in certified[tid]['rows'] if r['file']=='Behnke1.fjsp')
        # CSV field names are recorded explicitly alongside the comparison.
        candidates=[r for r in historical if r.get('strategy_id',r.get('strategy'))==old_id and r['file']=='Behnke1.fjsp']
        assert len(candidates)==1,(old_id,historical[0].keys())
        old=candidates[0]
        assert row['makespan']==int(old.get('Cmax',old.get('makespan')))
        assert row['physical_schedule_sha256']==old['physical_sha256']
        historical_match.append({'strategy':old_id,'file':row['file'],'makespan':row['makespan'],'physical_schedule_sha256':row['physical_schedule_sha256'],'matched':True})
    o.write(target,{'semantic':semantic,'certified':certified,'historical_match':historical_match,'run':str(run.relative_to(ROOT)),'API_calls':0})
    print(tag,'captured',len(semantic),'strategy-instance pairs, two semantic and two certified passes each')

def main():
    p=argparse.ArgumentParser();p.add_argument('tag',choices=['before','after','compare']);a=p.parse_args()
    if a.tag!='compare':capture(a.tag);return
    b=o.read(REPORT/'before.json');a=o.read(REPORT/'after.json')
    assert b['semantic']==a['semantic'];assert b['certified']==a['certified']
    result={'equal':True,'strategy_instance_pairs':len(a['semantic']),'compared':['full action traces','all U states','full schedule','decisions and weights','Fitness','first/recheck','certified hashes and H calls'],'historical_matches':a['historical_match'],'real_API':0}
    o.write(REPORT/'Comparison.json',result);print(result)

if __name__=='__main__':main()
