"""Read only the two explicitly fetched R9 runs. No client, H, solver or scheduler."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
BASE=Path('/Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-native-continuation-20261115/reports/native-continuation-20261115/fetch-1794797115597286000')
OUT=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
digest=lambda v:hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
rows=[];failed=[];gate_hashes=[];physical=0;source_before={};all_attempts={};source_map={};clock=[]
for member in read(BASE/'status.json')['members']:
 root=Path(member['result']);run=next((root/'runs').rglob('checkpoint.json')).parent;p=read(run/'Protocol.json');s=read(run/'checkpoint.json');j=read(run/'API_attempts.json');summary=read(run/'exports/summary.json')
 for n in ['Protocol.json','checkpoint.json','API_attempts.json','Run_clock.json']:source_before[str(run/n)]=sha(run/n)
 assert s['identity']==sha(run/'Protocol.json')==(run/'Protocol.sha256').read_text().strip()
 assert s['phase']=='paused' and len(s['tasks'])==s['cursor']==len(j['requests'])==len(j['api_attempts'])
 assert len([t for t in s['tasks'].values() if t['operator'] not in ['I1','INIT']])==s['eoh']['operator_cursor']
 assert all(t['status']=='completed' for t in s['tasks'].values()) and all(a['status'] in ['completed','failed'] and a['number']==1 for a in j['api_attempts'].values()) and j['halt_reason'] is None
 plan=read(run/'Tasks.json');assert list(s['tasks'])==[t['id'] for t in plan[:s['cursor']]]
 assert p['config']['api_attempt_cap']==1020 and p['config']['evolution_request_cap']==1000
 assert not any((run/n).exists() for n in ['.execution.lock','.coordinator.lock','Stop.json'])
 passes=0
 for value in s['evaluations'].values():
  assert value['status']=='completed' and sha(run/value['path'])==value['sha256'];result=read(run/value['path'])
  assert result['valid'] and not result['mock'] and len(result['instances'])==21 and not result['lifecycle']['alive'] and result['lifecycle']['exitcode']==0
  scores=[]
  for r,ref in zip(result['instances'],p['references']):
   assert r['reference']==ref['reference'] and r['captured_solves']==2 and r['feasible'] and r['semantic_sha256']==r['recheck_semantic_sha256'] and r['source_before_sha256']==r['source_after_sha256']
   score=(r['raw_cost']-r['reference'])/r['reference'];assert math.isclose(score,r['score'],abs_tol=1e-12);scores.append(score);passes+=2
  assert math.isclose(-sum(scores)/21,result['fitness'],abs_tol=1e-12)
 assert passes==sum(summary['physical_passes'][q]['completed'] for q in ['first','recheck']);physical+=passes
 for a in j['api_attempts'].values():
  key=digest({'member':p['run_id'],'key':a['id']});all_attempts[key]=(p['run_id'],a)
  if a['status']=='failed':
   m=a.get('metadata',{});failed.append({'seed':p['config']['search_seed'],'slot':a['logical_id'],'request_id':a['id'],'shared_uid':key,'confirmed_sent':a['send_confirmed'],'send_status':m.get('send_status'),'http_status':m.get('http_status'),'failure_stage':m.get('failure_stage'),'error':a['error'],'usage':a['usage'],'elapsed_seconds':a['elapsed_seconds'],'request_finished_at':a.get('finished_at'),'wire_finished_seconds':m.get('wire_timing',{}).get('finished_seconds')})
 gate=root/'plans/native-eoh-501-502/gate';g=read(gate/'ledger.json');gate_hashes.append(sha(gate/'ledger.json'));source_before[str(gate/'ledger.json')]=sha(gate/'ledger.json')
 champion=s['tasks'][summary['champion_id']];best=read(run/s['evaluations'][champion['evaluation_key']]['path']);assert math.isclose(-best['fitness'],summary['best_J'],abs_tol=1e-12)
 stamp=read(run/'Run_clock.json');clock.append(stamp)
 rows.append({'seed':p['config']['search_seed'],'job_id':member['job_id'],'source_run':str(run),'protocol_sha256':s['identity'],'checkpoint_sha256':sha(run/'checkpoint.json'),'journal_sha256':sha(run/'API_attempts.json'),'phase':s['phase'],'initialization':s['eoh']['initialization_requests'],'evolution_attempts':s['eoh']['operator_cursor'],'remaining_evolution':1000-s['eoh']['operator_cursor'],'original_request_cap':1020,'charged_attempts':len(j['api_attempts']),'remaining_request_cap':1020-len(j['api_attempts']),'confirmed_sends':summary['confirmed_sends'],'journal_failed_attempts':sum(a['status']=='failed' for a in j['api_attempts'].values()),'parse_failures':sum(t.get('failure')=='parse_or_constraint_error' for t in s['tasks'].values()),'AST_duplicates':summary['duplicates'],'unique_completed_evaluations':len(s['evaluations']),'physical_solves_including_recheck':passes,'best_training_J':summary['best_J'],'champion_id':summary['champion_id'],'native_population_records':len(s['eoh']['population']),'native_next_population_records':len(s['eoh']['next_population']),'native_generation':s['eoh']['native_generation'],'finite_parents':len(s['population']),'np_rng_sha256':digest(s['eoh']['np_rng']),'eoh_state_sha256':digest(s['eoh']),'original_clock':stamp,'original_deadline_plus08':datetime.fromtimestamp(stamp['deadline'],ZoneInfo('Asia/Manila')).isoformat(),'known_usage':summary['known_usage_subtotal']})
 assert all(sha(path)==h for path,h in source_before.items())
assert len(set(gate_hashes))==1 and len(failed)==6 and len(all_attempts)==1167
sent=[a for a in failed if a['confirmed_sent']];notsent=[a for a in failed if not a['confirmed_sent']]
assert len(sent)==1 and sent[0]['http_status']==522 and sent[0]['send_status']=='confirmed'
assert len(notsent)==5 and all(a['send_status']=='not_sent' and a['failure_stage']=='shared_admission' for a in notsent)
assert len(g['requests'])==1163 and sum(r['state']=='completed' for r in g['requests'].values())==1161
missing=[{'uid':key,'member':member,'request_id':a['id'],'status':a['status'],'send_confirmed':a['send_confirmed'],'send_status':a.get('metadata',{}).get('send_status')} for key,(member,a) in all_attempts.items() if key not in g['requests']]
assert len(missing)==4 and all(a['status']=='failed' and not a['send_confirmed'] and a['send_status']=='not_sent' for a in missing)
unknown=[a for member,a in all_attempts.values() if a['status'] not in ['completed','failed'] or not a['send_confirmed'] and a.get('metadata',{}).get('send_status') not in ['not_sent']]
assert not unknown and not any(e['status']!='completed' for row in rows for e in read(Path(row['source_run'])/'checkpoint.json')['evaluations'].values())
report={'verified':True,'source_fetch':str(BASE),'members':rows,'failure_sequence':failed,'root_journal_charged_attempts':1167,'successful_responses':1161,'confirmed_sends':1162,'confirmed_http522_failures':1,'known_not_sent_failed_slots':5,'unknown_client_send_outcomes':0,'unknown_provider_usage_for_522':True,'physical_solves_including_recheck':physical,'new_R9_physical_solves_excluding_798_imported':physical-798,'shared_ledger_records':1163,'root_journal_records_not_in_shared_ledger':missing,'shared_STOP_preserved':True,'all_original_bytes_unchanged':all(sha(n)==h for n,h in source_before.items()),'new_API_requests':0,'new_actual_solves':0,'RNG_rule':'inherit current checkpoint eoh/np_rng and partial next_population exactly; do NOT roll back to P000_initial; six failed opportunities remain consumed','recovery_status':'NOT_EXECUTABLE_WITH_CURRENT_resume: explicit audited settlement/migration must preserve old STOP/ledger/journals, retain all1167 charges, classify known failed terminal outcomes without declaring them successful, verify current remote job terminality/account lease ownership, then permit fresh future slots only','direct_resume_safe':False,'request_replay_allowed':False,'refund_allowed':False,'remaining_evolution_total':sum(r['remaining_evolution'] for r in rows),'maximum_new_solves_including_recheck':42*sum(r['remaining_evolution'] for r in rows),'U503':'619593 stopped before child execution; no automatic requeue or launch under original failed follow plan'}
(OUT/'AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ['members','failure_sequence','root_journal_records_not_in_shared_ledger']},ensure_ascii=False,indent=2))
