"""Read saved evidence only: no solver, candidate execution, transport or training.
Derived tables go to this new report directory; original runs are never written.
"""
from collections import Counter,defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import ast,csv,hashlib,json,subprocess

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
RUN=ROOT/'runs/b1-v6-b1-20261030-155904-688532-7ced645e'
TOL=1e-12

def read(p):return json.loads(p.read_text())
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
 return h.hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def write(name,v):(OUT/name).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def table(name,rows):
 if not rows:return
 fields=list(dict.fromkeys(k for r in rows for k in r))
 with (OUT/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def git_bytes(ref,path):return subprocess.check_output(['git','show',ref+':'+path],cwd=ROOT)

def main():
 p=read(RUN/'Protocol.json');s=read(RUN/'checkpoint.json');summary=read(RUN/'exports/summary.json')
 assert s['phase']=='completed' and s['generation']==50 and not (RUN/'.coordinator.lock').exists()
 identity=sha(RUN/'Protocol.json');assert read(RUN/'Protocol.receipt.json')['sha256']==identity==s['identity']
 assert read(RUN/'checkpoint.receipt.json')=={'identity':identity,'sha256':sha(RUN/'checkpoint.json')}
 original_commit='0ce75da0ddd4a6aa67e0e37f7aaa31c8aaeed48c'
 available=subprocess.run(['git','cat-file','-e',original_commit+'^{commit}'],cwd=ROOT,capture_output=True).returncode==0
 source_ref=original_commit if available else 'HEAD'
 src=[]
 for name,value in p['source_files'].items():
  a=sha(ROOT/name);b=hashlib.sha256(git_bytes(source_ref,name)).hexdigest()
  src.append({'path':name,'frozen_sha256':value,'working_matches':a==value,'commit_matches':b==value})
 assert all(r['working_matches'] and r['commit_matches'] for r in src)
 launch=[]
 for f in sorted((RUN/'launch').glob('*.py')):
  name='experiments/common/'+f.name
  launch.append({'path':name,'frozen_sha256':sha(f),'commit_matches':hashlib.sha256(git_bytes(source_ref,name)).hexdigest()==sha(f),
                 'working_matches':sha(ROOT/name)==sha(f)})
 assert all(r['commit_matches'] for r in launch)
 current_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 diff=subprocess.check_output(['git','diff','--','experiments/common/run_b1_v6.py'],cwd=ROOT,text=True)
 assert ast.dump(ast.parse((ROOT/'experiments/common/run_b1_v6.py').read_text()))==ast.dump(ast.parse((RUN/'launch/run_b1_v6.py').read_text()))
 write('version_mapping.json',{'run_directory':str(RUN),'protocol_sha256':identity,'config_sha256':digest(p['config']),
  'frozen_parameter_file_sha256':sha(RUN/'launch/parameters.json'),'checkpoint_sha256':sha(RUN/'checkpoint.json'),
  'code_commit_matching_frozen_files':subprocess.check_output(['git','rev-parse',source_ref],cwd=ROOT,text=True).strip(),'original_matching_commit_recorded_in_initial_audit':original_commit,'git_HEAD_at_diagnosis':current_head,
  'identity_limit':'Protocol does not record a Git commit. Matching 81 frozen source hashes and three launcher snapshots establishes byte equivalence to these files in 0ce75da, not identity of the entire historical worktree.',
  'source_files':src,'launch_files':launch,'working_launcher_difference':diff,
  'working_launcher_AST_matches_frozen':True,'champion_id':summary['champion']['id'],
  'champion_source_sha256':sha(RUN/'exports/frozen_training_champion.py'),'input_provenance':p['input_provenance'],
  'publication_note':'Publish a curated snapshot based on existing remote aa83cac, without introducing local authorization/claim artifacts. Original local history/worktree remain intact.'})
 write('frozen_config.json',p['config'])
 tasks=list(s['tasks'].values());byid=s['tasks'];valid={t['id']:t for t in tasks if t['valid']}
 def behavior(t):return s['evaluations'][t['candidate']['key']]['behavior_sha256']
 for t in tasks:
  assert t['status']=='completed'
  for k in ('prompt','response'):
   if t.get(k+'_path'):assert sha(RUN/t[k+'_path'])==t[k+'_sha256']
 for rec in s['plans'].values():assert sha(RUN/rec['path'])==rec['sha256']
 for key,ev in s['evaluations'].items():
  assert sha(RUN/ev['path'])==ev['sha256']
  assert ev['binding']==digest({'protocol':identity,'candidate':key})
 populations={g:read(RUN/f'populations/P{g:03d}.json') for g in range(51)}
 for pop in populations.values():
  assert len(pop)==10 and len({r['id'] for r in pop})==10
  assert all(r['id'] in valid for r in pop)
 rows={}
 with (RUN/'exports/per_instance.csv').open() as f:
  for r in csv.DictReader(f):
   if r['complete_candidate_valid']!='True':continue
   assert r['feasible']=='True' and int(r['captured_solves'])==2 and r['semantic_sha256']==r['recheck_semantic_sha256']
   row={'file':r['file'],'Cmax':float(r['Cmax']),'LB':float(r['LB']),'score':float(r['score'])}
   assert abs(row['score']+row['Cmax']/row['LB'])<TOL
   rows.setdefault(r['candidate'],{})[r['file']]=row
 files=[r['file'] for r in p['instances']]
 assert set(rows)==set(valid)
 for tid,rr in rows.items():
  assert set(rr)==set(files) and len(rr)==21
  assert abs(sum(rr[f]['score'] for f in files)/21-valid[tid]['fitness'])<TOL
 champion=summary['champion'];cid=champion['id'];chash=behavior(valid[cid]);finalids={r['id'] for r in populations[50]}
 assert sorted(populations[50],key=lambda r:(-r['fitness'],r['id']))[0]['id']==cid
 assert (RUN/'exports/frozen_training_champion.py').read_text()==champion['candidate']['code']
 (OUT/'champion.py').write_text(champion['candidate']['code'])
 winner_result=read(RUN/s['evaluations'][champion['candidate']['key']]['path'])
 count=Counter();usage=[]
 for r in winner_result['instances']:
  seq=r['member_sequence'];count.update(seq)
  usage.append({'file':r['file'],'decisions':len(seq),'H1':seq.count(1),'H9':seq.count(9),
                'switches':sum(a!=b for a,b in zip(seq,seq[1:]))})
 assert set(count)<={1,9}
 assert digest(winner_result['behavior'])==chash
 table('champion_member_usage.csv',usage)
 tree=ast.parse(champion['candidate']['code']);fields=Counter()
 for node in ast.walk(tree):
  if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Name) and node.value.id=='state' and isinstance(node.slice,ast.Constant):fields[str(node.slice.value)]+=1
 seen={behavior(t) for t in tasks if t['stage']=='initialization' and t['valid']};timeline=[];dropped=[]
 for g in range(1,51):
  before=populations[g-1];after=populations[g];children=[t for t in tasks if t['stage']=='evolution' and t['generation']==g and t['valid']]
  child_hash={behavior(t) for t in children};novel=child_hash-seen;after_hash={r['behavior_sha256'] for r in after};selected={r['id'] for r in after};leader=after[0]['id']
  for t in children:
   if t['id'] in selected:continue
   wins=[f for f in files if rows[t['id']][f]['Cmax']<rows[leader][f]['Cmax']]
   dropped.append({'generation':g,'id':t['id'],'operator':t['operator'],'fitness':t['fitness'],
    'behavior_sha256':behavior(t),'behavior_missing_from_survivors':behavior(t) not in after_hash,
    'globally_novel_behavior_this_generation':behavior(t) in novel,'better_instances_than_generation_champion':len(wins),
    'winning_files':','.join(wins)})
  timeline.append({'generation':g,'population_behavior_groups':len(after_hash),'valid_children':len(children),'child_behavior_groups':len(child_hash),
    'globally_new_behavior_groups':len(novel),'globally_new_groups_selected':len(novel&after_hash),
    'child_groups_absent_from_parent_population':len(child_hash-{r['behavior_sha256'] for r in before}),
    'children_selected':sum(t['id'] in selected for t in children),'new_behavior_children_selected':sum(t['id'] in selected and behavior(t) in novel for t in children),
    'best_fitness':after[0]['fitness'],'population_mean':sum(r['fitness'] for r in after)/10,
    'behavior_keys':','.join(sorted(after_hash))})
  seen|=child_hash
 table('behavior_timeline.csv',timeline);table('discarded_children.csv',dropped)
 operators=[]
 for op in ('CROSS','MUTATE'):
  tt=[t for t in tasks if t['operator']==op];vv=[t for t in tt if t['valid']];improved=tied=worse=0;selected=0;novel_parent=0
  for t in vv:
   pf=max(r['fitness'] for r in t['parent_records']);delta=t['fitness']-pf
   improved+=delta>TOL;tied+=abs(delta)<=TOL;worse+=delta<-TOL
   selected+=t['id'] in {r['id'] for r in populations[t['generation']]}
   novel_parent+=behavior(t) not in {r['behavior_sha256'] for r in t['parent_records']}
  operators.append({'operator':op,'logical_attempts':len(tt),'complete_valid':len(vv),'valid_rate':len(vv)/len(tt),
    'better_than_best_parent':improved,'better_rate_among_valid':improved/len(vv),
    'better_rate_among_all_attempts':improved/len(tt),'tied_best_parent':tied,'worse_than_best_parent':worse,
    'selected_at_generation_end':selected,'different_behavior_from_all_parents':novel_parent,
    **{'failure_'+str(k):v for k,v in Counter(t.get('failure') for t in tt if not t['valid']).items()}})
 table('operators.csv',operators)
 eliminated=[]
 for tid,t in valid.items():
  if tid in finalids or behavior(t)==chash:continue
  ww=[f for f in files if rows[tid][f]['Cmax']<rows[cid][f]['Cmax']];ll=[f for f in files if rows[tid][f]['Cmax']>rows[cid][f]['Cmax']]
  eliminated.append({'id':tid,'generation':t['generation'],'fitness':t['fitness'],'behavior_sha256':behavior(t),
    'wins_vs_frozen_champion':len(ww),'losses_vs_frozen_champion':len(ll),'ties_vs_frozen_champion':21-len(ww)-len(ll),
    'winning_files':','.join(ww)})
 eliminated.sort(key=lambda r:(-r['wins_vs_frozen_champion'],-r['fitness'],r['id']))
 table('eliminated_vs_champion.csv',eliminated)
 representatives=[];represented=set()
 for r in eliminated:
  if r['behavior_sha256'] not in represented:
   representatives.append(r);represented.add(r['behavior_sha256'])
 examples=[]
 for r in [r for r in representatives if r['wins_vs_frozen_champion']>0][:5]:
  for f in r['winning_files'].split(','):
   examples.append({'candidate':r['id'],'candidate_fitness':r['fitness'],'file':f,'LB':rows[cid][f]['LB'],
     'candidate_Cmax':rows[r['id']][f]['Cmax'],'champion_Cmax':rows[cid][f]['Cmax']})
 table('partial_advantage_examples.csv',examples)
 grouptrans=[{'generation':0,'groups':len({r['behavior_sha256'] for r in populations[0]})}]
 for r in timeline:
  if r['population_behavior_groups']!=grouptrans[-1]['groups']:grouptrans.append({'generation':r['generation'],'groups':r['population_behavior_groups']})
 late=[r for r in timeline if r['generation']>=15];drop_late=[r for r in dropped if r['generation']>=15]
 result={'run_directory':str(RUN),'seed':p['config']['search_seed'],'N':10,'G':50,'champion_id':cid,'fitness':champion['fitness'],
  'final_mean':sum(r['fitness'] for r in populations[50])/10,'champion_member_counts':dict(count),'champion_decisions':sum(count.values()),
  'syntactic_state_fields':dict(fields),'behavior_group_transitions':grouptrans,
  'total_distinct_valid_train_behavior_groups':len(seen),'first_single_group_generation':next((r['generation'] for r in timeline if r['population_behavior_groups']==1),None),
  'late_G15_G50_new_groups':sum(r['globally_new_behavior_groups'] for r in late),'late_G15_G50_new_groups_selected':sum(r['globally_new_groups_selected'] for r in late),
  'late_discarded_valid_children':len(drop_late),'late_discarded_absent_behavior_with_partial_advantage':sum(r['behavior_missing_from_survivors'] and r['better_instances_than_generation_champion']>0 for r in drop_late),
  'eliminated_different_behavior_candidates':len(eliminated),'eliminated_with_partial_instance_advantage':sum(r['wins_vs_frozen_champion']>0 for r in eliminated),
  'eliminated_partial_advantage_unique_behaviors':len({r['behavior_sha256'] for r in eliminated if r['wins_vs_frozen_champion']>0}),
  'top_partial_advantage_examples':representatives[:5],'operators':operators,
  'failures':dict(Counter(t.get('failure') for t in tasks if not t['valid'])),
  'complete_valid':len(valid),'logical_attempts':len(tasks),'evaluation_receipts_verified':len(s['evaluations']),
  'task_prompt_response_receipts_verified':True,'generation_plan_receipts_verified':50,'per_instance_rows_verified':len(valid)*21,
  'scope':'Saved train21 complete candidates only. Behavior is ordered selected-H sequences, not global program equivalence or a physical-schedule grouping. No strategy execution, solve, model request, validation or test access.',
  'missing_evidence':'Compact recording omits per-step state/action tables: cannot recover each numeric trigger input, causal alternative-H action effects or unobserved states without separately authorized evaluation.',
  'API_requests':0,'solves':0}
 write('diagnosis.json',result)
 for name in ('train21_comparison.csv','train21_comparison.md','train21_comparison.json','generations.csv'):
  (OUT/name).write_bytes((RUN/'exports'/name).read_bytes())
 write('result_summary.json',{k:summary[k] for k in ('phase','generation','real_API_calls','api_attempts_reserved','initialization_requests','generation_requests','valid_unique_evaluations','failed_or_duplicate_tasks')})
 write('input_artifact_receipts.json',{'Protocol.json':identity,'checkpoint.json':sha(RUN/'checkpoint.json'),
    **{'exports/'+name:sha(RUN/'exports'/name) for name in ('summary.json','per_instance.csv','candidates.csv','generations.csv','acceptance.json','frozen_training_champion.json','frozen_training_champion.py','train21_comparison.json')}})
 print(json.dumps({k:v for k,v in result.items() if k not in ('missing_evidence','scope')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
