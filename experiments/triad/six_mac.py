#!/usr/bin/env python3
"""Mac transfer only; reuse admitted SSH, installer and hash-checked result fetch."""
import argparse
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import write
from experiments.triad import cluster,launch_concurrent
REMOTE='/public2/home/qiuqian/hdl-deploy/triad-tsp-lkh-candidate-20261117-r13'
BUNDLE=Path('/Users/DDXQL/Developer/transfer-outbox/triad-tsp-lkh-candidate-20261117-r13.zip')
R11='/public2/home/qiuqian/hdl-deploy/triad-fjsp-stop-recovery-20261116-r11'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['stage','inspect','fetch','fetch-r11','fetch-h','fetch-lkh'])
    ap.add_argument('--batch',choices=['fjsp503','tsp501','tsp502','tsp503','obp501','obp502','obp503'])
    a=ap.parse_args();report=ROOT/'reports/six-groups-20261116'/(a.action+'-'+str(time.time_ns()));report.mkdir(parents=True)
    with cluster.shared.Connection() as c:
        if a.action=='stage':
            cluster.REMOTE=REMOTE;cluster.BUNDLE=BUNDLE
            value=cluster.stage_release(c,report)
            checked=c.run([cluster.shared.PY,'-s','-B',REMOTE+'/experiments/triad/six_ops.py','check-only'])
            (report/'check-only.json').write_text(checked.stdout)
        elif a.action=='inspect':
            r=c.run([cluster.shared.PY,'-s','-B','-',REMOTE],(ROOT/'experiments/triad/cluster-fjsp/inspect_remote.py').read_text());value=json.loads(r.stdout)
        elif a.action in ('fetch-h','fetch-lkh'):
            from experiments.triad.six_ops import need
            relative='runs/obp-H401' if a.action=='fetch-h' else 'preparations/operations/tsp-LKH'
            # Existing asset receipts are checked on cluster before immutable packaging.
            script='''import pathlib,json,sys,zipfile,hashlib,time
r=pathlib.Path(sys.argv[1]);d=r/sys.argv[2]
receipt=json.loads((d/'latest-asset-submission.json').read_text());j=receipt['job_id']
import subprocess
q=subprocess.run(['squeue','-h','-u','qiuqian','-o','%i'],check=True,text=True,capture_output=True).stdout
if j in q.split():raise SystemExit('asset job active; no snapshot')
a=subprocess.run(['sacct','-n','-P','-j',j,'--format=JobIDRaw,State,ExitCode'],check=True,text=True,capture_output=True).stdout
exact=[l.split('|') for l in a.splitlines() if l.split('|')[0]==j]
if len(exact)!=1 or exact[0][1].split()[0] not in {'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL'}:raise SystemExit('terminal asset accounting missing')
payload={str(p.relative_to(r)):p.read_bytes() for p in d.rglob('*') if p.is_file() and not p.is_symlink()}
for p in (r/'logs').glob('asset-*'+d.name+'-'+j+'.out'):payload[str(p.relative_to(r))]=p.read_bytes()
out=r/'exports'/('asset-'+j+'-'+str(time.time_ns())+'.zip');out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
 for n,raw in payload.items():z.writestr(n,raw)
 z.writestr('retrieval-manifest.json',json.dumps({'files':{n:hashlib.sha256(v).hexdigest() for n,v in payload.items()},'job_id':j}))
print(json.dumps({'path':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest()}))
'''
            receipt=json.loads(c.run([cluster.shared.PY,'-s','-B','-c',script,REMOTE,relative]).stdout)
            archive=report/'asset.zip';c.copy(cluster.shared.HOST+':'+receipt['path'],str(archive))
            import zipfile,hashlib
            need(hashlib.sha256(archive.read_bytes()).hexdigest()==receipt['sha256'],'ZIP mismatch')
            with zipfile.ZipFile(archive) as z:
                for n,h in json.loads(z.read('retrieval-manifest.json'))['files'].items():
                    need(not Path(n).is_absolute() and '..' not in Path(n).parts and hashlib.sha256(z.read(n)).hexdigest()==h,'unsafe/mismatched member')
                z.extractall(report/'result')
            value={'retrieved':True,'hashes_verified':True,'ZIP_sha256':receipt['sha256']}
        else:
            if a.action=='fetch' and a.batch is None:raise ValueError('explicit --batch required')
            launch_concurrent.REMOTE=R11 if a.action=='fetch-r11' else REMOTE
            value=launch_concurrent.fetch(c,'stop-recovery-501-502' if a.action=='fetch-r11' else 'six-'+a.batch,report)
    value.update(local_evidence=str(report),local_API_requests=0,local_solves=0,Slurm_submitted=False)
    write(report/'status.json',value);print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False},ensure_ascii=False),file=sys.stderr)
        raise SystemExit(2)
