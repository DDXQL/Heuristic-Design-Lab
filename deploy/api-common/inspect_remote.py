"""Read-only remote inventory. No project imports, keys, model calls or solving."""
import argparse,collections,hashlib,json,re,subprocess,time
from pathlib import Path

def scrub(text):return re.sub(r'(?i)(bearer\s+\S+|sk-[A-Za-z0-9_-]+)','[REDACTED]',text)
def load(path):return json.loads(path.read_text())
def query(cmd):
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=25)
        return {'returncode':p.returncode,'stdout':scrub(p.stdout[-12000:]),'stderr':scrub(p.stderr[-2000:])}
    except Exception as error:return {'error_type':type(error).__name__}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--require-idle',action='store_true');args=ap.parse_args()
    base=Path('/public2/home/qiuqian/hdl-deploy');suite=base/'tsp-state-ab-bb21b69-cluster-20261104'
    items=[('old585019',base/'tsp-search-n10g50-20261103/runs/tsp-u-n10g50-seed501-20261103-01')]
    if (suite/'experiments/tsp_state_ab/Suite.json').exists():
        items.extend((a['id'],suite/a['output']) for a in load(suite/'experiments/tsp_state_ab/Suite.json')['arms'])
    queue=query(['squeue','-u','qiuqian','-h','-o','%i %j %T %R'])
    out={'at_unix':time.time(),'model_requests':0,'solves':0,'queue':queue,
         'accounting':query(['sacct','-X','-S','2026-11-02','-u','qiuqian','--format=JobID,JobName%24,State,ExitCode,Elapsed,NodeList']),
         'runs':[],'suite_lock':(suite/'runs/tsp-state-ab-v1/.suite.lock').exists()}
    ids=['585019','585597']+[line.split()[0] for line in queue.get('stdout','').splitlines() if line.split() and line.split()[0].isdigit()]
    out['job_details']={job:query(['scontrol','show','job',job]) for job in dict.fromkeys(ids[:8])}
    for name,d in items:
        row={'name':name,'path':str(d),'checkpoint_exists':(d/'checkpoint.json').exists()}
        if row['checkpoint_exists']:
            s=load(d/'checkpoint.json');row.update(phase=s.get('phase'),generation=s.get('generation'),initialization_requests=s.get('initialization_requests'),generation_requests=s.get('generation_requests'),
                locks=[f for f in ('.coordinator.lock','.execution.lock') if (d/f).exists()],
                inflight=[t['id'] for t in s.get('tasks',{}).values() if t.get('status') in ('request_reserved','evaluation_reserved','reserved')],
                failure_counts=dict(collections.Counter(t.get('failure','valid') for t in s.get('tasks',{}).values())),checkpoint_sha256=hashlib.sha256((d/'checkpoint.json').read_bytes()).hexdigest())
            if (d/'Protocol.json').exists():
                p=load(d/'Protocol.json');row['transport_source_sha256']=p.get('source_files',{}).get('code/fjsp_usage/research_real/real_transport.py');row['provider']=p.get('config',{}).get('provider')
            # Only inspect failure receipts already identified by checkpoint, not all results.
            row['recent_failure_receipts']=[]
            failures=[t for t in s.get('tasks',{}).values() if t.get('failure') and t.get('response_path')][-4:]
            for t in failures:
                f=d/t['response_path']
                if f.exists():
                    v=load(f);v=v.get('value',v);m=v.get('metadata',{})
                    row['recent_failure_receipts'].append({'task':t['id'],'error':scrub(str(v.get('error')))[:400],'usage':v.get('usage'),'sent':v.get('sent'),'metadata':m})
        out['runs'].append(row)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    # Do not overlap this diagnostic with any owned active/queued work or unknown query state.
    return 3 if args.require_idle and (queue.get('returncode')!=0 or queue.get('stdout','').strip()) else 0
if __name__=='__main__':raise SystemExit(main())
