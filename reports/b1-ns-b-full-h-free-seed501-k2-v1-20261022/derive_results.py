"""Read-only persisted B1-NS-B analysis; no API, U execution or data loading."""
from collections import Counter
from pathlib import Path
import csv,gzip,hashlib,json,shutil

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'runs/b1-ns-full-h-free-seed501-k2-v1-20261022'
OUT=Path(__file__).resolve().parent

def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,x):
 (OUT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def table(name,rows):
 if not rows:return
 with (OUT/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
def total(x):return sum(x) if isinstance(x,list) else x

def main():
 p=read(RUN/'Protocol.json');c=read(RUN/'r501/B/checkpoint.json');j=read(RUN/'r501/B/batch_requests.json')
 h=read(RUN/'H_source_binding.json')['members'];names=p['train_names'];h0={r['file']:r for r in h[0]['training_result']['instances']}
 assert len(j['requests'])==len(j['api_attempts'])==6 and c['inflight'] is None
 assert len(c['evaluations'])==3 and c['generation']==0 and len(c['population'])==3
 rows=[];instance_rows=[];behaviors={};candidate_results=[]
 byid={a['id']:a for a in c['attempts']};accepted={r['id']:r for r in c['population']}
 for ident,rec in j['requests'].items():
  a=byid[ident];attempts=[j['api_attempts'][key] for key in rec['attempt_ids']];m=attempts[-1]['reply']['metadata']
  label=ident.replace('/','_');response_dir=OUT/'responses';response_dir.mkdir(exist_ok=True)
  (response_dir/(label+'.txt')).write_text(rec['text'])
  result=c['evaluations'].get(ident,{}).get('result');fit=result.get('fitness') if result else None
  rows.append({'id':ident,'operator':a['operator'],'status':a['status'],'category':a.get('category'),
   'error':a.get('error'),'API_attempts':len(attempts),'HTTP_status':m.get('http_status'),'model':m.get('model'),
   'finish_reason':m.get('finish_reason'),'input_tokens':sum(x['usage']['input_tokens'] for x in attempts),
   'output_tokens':sum(x['usage']['output_tokens'] for x in attempts),'API_elapsed_seconds':sum(x['elapsed_seconds'] for x in attempts),
   'static_contract_pass':ident in accepted,'complete_train_valid':result.get('valid') if result else None,
   'fitness':fit,'initial_pool_at_stop':ident in accepted,'full_P0_formed':False,'identity_exception_in_run':True})
  if result is None:continue
  assert result['valid'] is True and [r['file'] for r in result['instances']]==names
  candidate=accepted[ident]['candidate'];source=OUT/'U_sources';source.mkdir(exist_ok=True)
  (source/(label+'.py')).write_text(candidate['code'])
  modes=Counter();supports=Counter();dominants=Counter();vectors=set();switches=0;firstsec=0;reviewsec=0;calls=0;reviewcalls=0
  wins=losses=ties=0;mass=[0.0]*10;participation=[0]*10
  for r in result['instances']:
   base=h0[r['file']];assert abs(r['lower_bound']-base['lower_bound'])<1e-9
   delta=(base['makespan']-r['makespan'])/r['lower_bound'];wins+=delta>0;losses+=delta<0;ties+=delta==0
   u=r['member_usage'];switches+=u['dominant_switches']
   firstsec+=r['single_solve_seconds'];reviewsec+=r['deterministic_recheck_seconds']
   firstcalls=total(r['single_h_calls']);secondcalls=total(r['deterministic_recheck_h_calls']);calls+=firstcalls;reviewcalls+=secondcalls
   for i in range(10):mass[i]+=u['weight_mass'][i];participation[i]+=u['participation_counts'][i]
   for mode,vector,support,weights,dominant in r['usage_decisions']:
    modes[mode]+=1;supports[tuple(support)]+=1;dominants[dominant]+=1;vectors.add(tuple(vector))
   instance_rows.append({'candidate_id':ident,'file':r['file'],'Cmax':r['makespan'],'LB':r['lower_bound'],'score':r['score'],
    'H0_Cmax':base['makespan'],'delta_Cmax_U_minus_H0':r['makespan']-base['makespan'],'delta_F_U_minus_H0':delta,
    'single_solve_seconds':r['single_solve_seconds'],'recheck_seconds':r['deterministic_recheck_seconds'],
    'single_h_calls':firstcalls,'recheck_h_calls':secondcalls,'SELECT_steps':u['SELECT_steps'],'MIX_steps':u['MIX_steps'],
    'dual_member_steps':u['dual_member_steps'],'physical_recheck_equal':r['physical_schedule_sha256']==r['recheck_physical_schedule_sha256'],
    'run_identity_exception':True})
  b={'SELECT_steps':modes[0],'MIX_steps':modes[1],'supports':{','.join(map(str,k)):v for k,v in supports.items()},
     'dominant_counts':dict(dominants),'dominant_switches':switches,'observed_distinct_raw_vectors':len(vectors),
     'participation_counts':participation,'weight_mass':mass,'active_members':[i for i,n in enumerate(participation) if n],
     'dual_member_steps':sum(v for k,v in supports.items() if len(k)==2),'no_causal_gain_claim':True}
  behaviors[ident]=b
  candidate_results.append({'candidate_id':ident,'cached_complete_valid':True,'fitness':fit,
    'sum_Cmax_not_objective':sum(r['makespan'] for r in result['instances']),'delta_F_vs_H0':fit-h[0]['fitness'],
    'wins_vs_H0':wins,'losses_vs_H0':losses,'ties_vs_H0':ties,'primary_eval_wall_seconds':result['primary_evaluation_seconds'],
    'single_solve_seconds':firstsec,'recheck_seconds':reviewsec,'single_h_calls':calls,'recheck_h_calls':reviewcalls,
    'recheck_pairs':21,'run_identity_exception':True})
 fixed=[]
 for i,x in enumerate(h):
  assert [r['file'] for r in x['training_result']['instances']]==names
  fixed.append({'member':i,'code_key':x['candidate']['key'],'cached_fitness':x['fitness'],
   'sum_Cmax_not_objective':sum(r['makespan'] for r in x['training_result']['instances']),
   'source':'new run frozen H_source_binding.json; historical cached evaluation, not rerun'})
 summary={'batch_status':'stopped_frozen_input_identity_violation','engine_phase':c['phase'],'P0_members_at_stop':3,'full_P0':False,
  'generations_completed':0,'CROSS_tasks':0,'MUTATE_tasks':0,'CROSS_valid_rate':None,'MUTATE_valid_rate':None,
  'logical_tasks':6,'API_attempts':6,'confirmed_sends':6,'retries':0,'pending_attempts':0,'complete_HTTP_outputs':6,
  'format_and_static_pass':3,'format_fail':3,'AST_duplicates_recorded':0,'complete_train_valid':3,'FJSP_failures':0,
  'complete_train_instances':63,'first_plus_recheck_solves':126,'valid_rate_of_sent_logical_tasks':0.5,
  'input_tokens':sum(a['usage']['input_tokens'] for a in j['api_attempts'].values()),
  'output_tokens':sum(a['usage']['output_tokens'] for a in j['api_attempts'].values()),
  'cached_tokens_subset_of_input':sum(a['reply']['metadata'].get('cached_tokens',0) for a in j['api_attempts'].values()),
  'actual_cost':None,'API_elapsed_seconds_sum':sum(a['elapsed_seconds'] for a in j['api_attempts'].values()),
  'primary_evaluation_wall_seconds_sum':sum(r['primary_eval_wall_seconds'] for r in candidate_results),
  'single_solve_seconds_sum':sum(r['single_solve_seconds'] for r in candidate_results),'recheck_seconds_sum':sum(r['recheck_seconds'] for r in candidate_results),
  'certified_h_calls_first':sum(r['single_h_calls'] for r in candidate_results),'certified_h_calls_recheck':sum(r['recheck_h_calls'] for r in candidate_results),
  'SELECT_steps':sum(b['SELECT_steps'] for b in behaviors.values()),'MIX_steps':sum(b['MIX_steps'] for b in behaviors.values()),
  'dual_member_steps':sum(b['dual_member_steps'] for b in behaviors.values()),'active_members':sorted({i for b in behaviors.values() for i in b['active_members']}),
  'fixed_H_best':fixed[0],'best_observed_candidate':max(candidate_results,key=lambda r:r['fitness']),
  'new_evaluation_or_replay_in_analysis':False,'timing_limit':'Historical fixed-H timers and current U timers have different interface/time contexts; no exact speed claim.',
  'identity_caveat':'Native results retain valid=true; execution stopped on a frozen-code read mismatch. Current bytes match again, intermediate content and continuous worker source identity are not proven.'}
 save('Summary.json',summary);save('Candidate_index.json',rows);table('Candidate_index.csv',rows)
 save('Candidate_results.json',candidate_results);table('Candidate_results.csv',candidate_results);table('All_instance_results.csv',instance_rows)
 save('Behavior_profiles.json',behaviors);save('Fixed_H_cached_reference.json',fixed)
 save('Population_and_lineage.json',{'full_P0_formed':False,'partial_initial_pool':c['population'],
      'P0':None,'P1':None,'P2':None,'attempts':c['attempts'],'no_evolution_occurred':True})
 old=read(ROOT/'reports/b1-ns-a-engineering-v1-20261022/Historical_immutability.json');changed=[]
 for name,prior in old['before'].items():
  f=ROOT/name
  if not f.exists() or {'sha256':sha(f),'mtime_ns':f.stat().st_mtime_ns}!=prior:changed.append(name)
 current={str(f.relative_to(ROOT)) for name in old['directories'] for f in (ROOT/'runs'/name).rglob('*') if f.is_file()}
 save('Historical_protection_check.json',{'reference':'reports/b1-ns-a-engineering-v1-20261022/Historical_immutability.json',
      'files_checked':len(old['before']),'changed':changed,'added':sorted(current-set(old['before'])),'deleted':sorted(set(old['before'])-current)})
 prepared=ROOT/'reports/b1-ns-a-engineering-v1-20261022/prepared'
 assert all(f.read_bytes()==(RUN/f.relative_to(prepared)).read_bytes() for f in prepared.rglob('*') if f.is_file())
 manifest={}
 for f in sorted(RUN.rglob('*')):
  if not f.is_file():continue
  name=str(f.relative_to(RUN));target=OUT/'evidence'/name;target.parent.mkdir(parents=True,exist_ok=True)
  if f.stat().st_size>2000000:
   target=target.with_suffix(target.suffix+'.gz')
   with target.open('wb') as raw:
    with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as z:z.write(f.read_bytes())
   assert hashlib.sha256(gzip.decompress(target.read_bytes())).hexdigest()==sha(f)
   compression='gzip'
  else:shutil.copyfile(f,target);compression=None
  manifest[name]={'sha256':sha(f),'archived_as':str(target.relative_to(OUT)),'compression':compression,'source_bytes':f.stat().st_size}
 save('Evidence_manifest.json',{'source_run':str(RUN),'protocol_sha256':sha(RUN/'Protocol.json'),'files':manifest,
     'credentials_copied':False,'large_checkpoint_is_exact_decompressible_copy':True})
 print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
