"""No evaluator imports, new jobs, formal samples or network: saved-file QA only."""
import csv
import hashlib
import json
from pathlib import Path
from statistics import fmean

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
RUN=ROOT/'runs/a4-static-rs60x5-train21-seed501-v1'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rows(n):return list(csv.DictReader((OUT/n).open()))

def main():
 s=read(OUT/'Certified_summary.json')
 assert (s['certified_completed_queries'],s['distinct_queried_strategies'],s['new_queries'],s['historical_cache_queries'],s['campaign_cache_queries'])==(93,91,81,10,2)
 assert s['first_starts']==s['recheck_starts']==1701 and s['invalid_queries']==0
 assert not s['unresolved_reservations'] and s['phase']=='wall_budget_stopped' and s['API']==0
 assert 'champion_distribution' not in s
 assert [x['consumed'] for x in s['repeats']]==[60,33,0,0,0]
 assert [x['budget_complete'] for x in s['repeats']]==[True,False,False,False,False]
 assert [x['champion_slot'] for x in s['repeats'][:2]]==[52,17]
 assert len(rows('Round1_best_so_far_60.csv'))==60 and len(rows('Round2_partial_best_so_far_33.csv'))==33
 q=rows('Certified_queries.csv');inst=rows('All_instances.csv');assert len(q)==93 and len(inst)==1953
 for v in q:
  rr=[x for x in inst if x['query']==v['query']];assert len(rr)==21
  assert all(float(x['score'])==-int(x['Cmax'])/float(x['LB']) for x in rr)
  assert fmean(float(x['score']) for x in rr)==float(v['fitness'])
 assert max(float(x['fitness']) for x in q)==-2.022083102801006
 assert s['repeats'][1]['fitness']==-2.0370501606594282
 old=ROOT/'reports/a4-static-rs60x5-train21-seed501-v1/Pause_snapshot'
 for n in ('Protocol.json','Plans.json','checkpoint.json','Run_clock.json'):
  assert sha(RUN/n)==sha(old/n)==sha(OUT/n),'original campaign changed: '+n
 assert not (RUN/'.writer.lock').exists() and not (RUN/'Stop.json').exists()
 t=read(OUT/'Timeline_summary.json');assert t['all_query_births_before_launch_cutoff']
 assert t['strict_suspend_inclusive_T30_unconfirmed_queries']==[88,89,90,92,93]
 assert all(x not in t['strict_suspend_inclusive_T30_unconfirmed_queries'] for x in (52,77))
 test=read(OUT/'Long_job_acceptance.json');assert test['passed'] and test['tests_run']==5
 for p,h in test['files'].items():assert sha(ROOT/p)==h
 src=read(OUT/'Certified_result_sources.json');assert src['analysis_script_sha256']==sha(ROOT/'tools/a4_static_campaign_analysis.py')
 if (OUT/'Delivery_manifest.json').exists():
  for p,h in read(OUT/'Delivery_manifest.json')['files'].items():assert sha(ROOT/p)==h,p
 print(json.dumps({'status':'PASS','complete60_repeats':1,'partial33_repeats':1,'not_started_repeats':3,'queries':93,'unique_policies':91,'new_formal_solves_this_turn':0,'API':0,'synthetic_tests':5,'original_campaign_unchanged':True,'five_repeat_distribution_computed':False},ensure_ascii=False))

if __name__=='__main__':main()
