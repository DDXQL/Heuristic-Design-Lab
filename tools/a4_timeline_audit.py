"""Bounded offline timeline audit of the stopped A4 run, no solver imports."""
import csv
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/a4-static-rs60x5-train21-seed501-v1'
OUT=ROOT/'reports/a4-closeout-20261025-v1'
TZ=ZoneInfo('Asia/Manila')

def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def stamp(t):return datetime.fromtimestamp(t,timezone.utc).astimezone(TZ).isoformat()
def overlap(a,b,spans):return sum(max(0,min(b,y)-max(a,x)) for x,y in spans)

def main():
 s=read(RUN/'checkpoint.json');c=read(RUN/'Run_clock.json');events=[]
 for line in (OUT/'System_power_events.txt').read_text().splitlines():
  m=re.match(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d{4}) (Sleep|Wake|DarkWake)\s{2,}',line)
  if m:events.append((datetime.strptime(m[1],'%Y-%m-%d %H:%M:%S %z').timestamp(),m[2]))
 spans=[(a[0],b[0]) for a,b in zip(events,events[1:]) if a[1]=='Sleep' and b[1] in ('Wake','DarkWake')]
 rows=[];sources={};isolated=[]
 for i,q in enumerate(s['queries']):
  if q['origin']!='new':continue
  f=RUN/'queries'/f'q{i:04d}';e=f/'evidence';life=read(e/'lifecycle.json');raw=read(e/'raw_result.json')
  a=f.stat().st_birthtime;b=(f/'result.json').stat().st_mtime
  child_a=(e/'before.json').stat().st_mtime;child_b=(e/'after.json').stat().st_mtime
  ends=[(e/(Path(r['file']).stem+'.result.json')).stat().st_mtime for r in raw['instances']]
  endpoint_gaps=[y-x for x,y in zip([child_a]+ends[:-1],ends)]
  mono=life['finished_monotonic']-life['started_monotonic'];sleep=overlap(a,b,spans)
  resource_flag=(b-a)-raw['primary_evaluation_seconds']>2 and sleep>0
  strict_unknown=max(endpoint_gaps)>30 and overlap(child_a,child_b,spans)>0
  row={'query':i+1,'repeat':q['repeat']+1,'slot':q['slot']+1,'ticket':q['ticket'],
   'query_folder_birth':stamp(a),'child_before_write':stamp(child_a),'last_instance_result_write':stamp(ends[-1]),
   'child_after_write':stamp(child_b),'collector_terminal_write':stamp((e/'lifecycle.json').stat().st_mtime),
   'accepted_result_write':stamp(b),'query_wall_seconds':b-a,'child_evidence_wall_span_seconds':child_b-child_a,
   'collector_monotonic_seconds':mono,'primary_perf_seconds':raw['primary_evaluation_seconds'],
   'max_monotonic_instance_recv_seconds':max(x['finished']-x['started'] for x in life['instance_receives']),
   'max_instance_write_endpoint_gap_seconds':max(endpoint_gaps),'system_sleep_overlap_query_seconds':sleep,
   'resource_wall_not_comparable':resource_flag,'suspend_inclusive_T30_not_certifiable':strict_unknown,
   'original_valid_retained':raw['valid'],'exitcode':life['exitcode']}
  assert row['exitcode']==0 and row['original_valid_retained'] and row['max_monotonic_instance_recv_seconds']<=30
  rows.append(row)
  if resource_flag or strict_unknown:isolated.append(row)
  for path in [e/'lifecycle.json',e/'before.json',e/'after.json',e/'raw_result.json',f/'result.json']:
   sources[str(path.relative_to(ROOT))]=sha(path)
 def table(name,rs):
  with (OUT/name).open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rs)
 table('Query_timeline_81.csv',rows);table('Timing_isolation.csv',isolated)
 pause=read(ROOT/'reports/a4-static-rs60x5-train21-seed501-v1/Pause_audit.json')
 summary={'sleep_log_events':len(events),'sleep_intervals':len(spans),'source':'pmset -g log, filtered to task window and Sleep/Wake/DarkWake only; trailing whitespace normalized',
  'power_events_sha256':sha(OUT/'System_power_events.txt'),'queries':len(rows),
  'resource_timing_flag_queries':[r['query'] for r in rows if r['resource_wall_not_comparable']],
  'strict_suspend_inclusive_T30_unconfirmed_queries':[r['query'] for r in rows if r['suspend_inclusive_T30_not_certifiable']],
  'limits':'File writes are wall-time endpoints, not exact instance start/recv/OS-exit timestamps. Flags isolate resource-timing evidence, do not rewrite original accepted quality.',
  'clock_implementation':'Python monotonic/perf_counter uses mach_absolute_time() on this host, verified via time.get_clock_info; source lifecycle uses monotonic while campaign launch uses time.time.',
  'start':stamp(c['start_utc_epoch']),'deadline':stamp(c['deadline_utc_epoch']),
  'terminal_checkpoint_write':stamp((RUN/'checkpoint.json').stat().st_mtime),
  'last_query':rows[-1],
  'parent_actual_exit_time':'not recorded; after terminal checkpoint write, no later than first observed exit0',
  'parent_exit0_first_observed':'Prior conversation tool result at approximately2026-10-25 11:04 Asia/Manila; exact observation second not separately persisted.',
  'structured_exit0_observation_upper_bound':pause['audit_date_Asia_Manila'],
  'all_query_births_before_launch_cutoff':all((RUN/'queries'/f'q{i:04d}').stat().st_birthtime<c['deadline_utc_epoch']-650 for i in range(len(s['queries']))),
  'original_records_mutated':False,'new_solves':0,'sources':sources}
 (OUT/'Timeline_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in summary.items() if k not in ('sources','last_query')},ensure_ascii=False))

if __name__=='__main__':main()
