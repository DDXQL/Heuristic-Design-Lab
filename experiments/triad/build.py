#!/usr/bin/env python3
"""Sanitized standalone prepared source; admitted public code is unchanged."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from experiments.triad import runtime
BASE=Path('/Users/DDXQL/Developer/transfer-outbox/fjsp-cluster-noapi-923781f-20261113-r1.zip')
BASE_SHA='b7941d16b82caa9929c644afd8d75500dddba260a5f0141cef96d010f2a92b7d'
OUTPUT=Path('/Users/DDXQL/Developer/transfer-outbox/triad-six-groups-prepared-20261113-r3.zip')
PUBLIC='923781f05686f1899c24fd7899fb3bc6b1df1562'


def digest(b):return hashlib.sha256(b).hexdigest()

def main():
    if OUTPUT.exists():raise FileExistsError('frozen archive exists; preserve and choose a new revision')
    if digest(BASE.read_bytes())!=BASE_SHA:raise ValueError('admitted base archive changed')
    payload={}
    with zipfile.ZipFile(BASE) as z:
        release=json.loads(z.read('release.json'))
        for n,h in release['files'].items():
            if n.startswith(('code/','LICENSES/','.agents/')) or n in ('requirements.txt','LICENSE','THIRD_PARTY_NOTICES.md'):
                b=z.read(n)
                if digest(b)!=h:raise ValueError('base member mismatch')
                payload[n]=b
    names=set(runtime.sources())
    for folder in ('experiments/triad','deploy/eoh-baseline','preparations/eoh-gap','preparations/triad'):
        names.update(str(p.relative_to(ROOT)) for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.json','.md','.fjsp','.sbatch','.sh'))
    names.update(('experiments/common/_single_run.py','deploy/cluster-mock/control.py','deploy/cluster-mock/inspect_remote.py','AGENTS.md','docs/中文科研写作规范.md','README.md','docs/三问题实验运行入门.md'))
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    for n in sorted(names):
        p=ROOT/n
        if p.is_symlink():raise ValueError('symlink excluded: '+n)
        b=p.read_bytes()
        if b!=subprocess.check_output(['git','show',commit+':'+n],cwd=ROOT):raise ValueError('source not frozen in current commit: '+n)
        if n.startswith('code/') or n.startswith('tools/') or n.startswith('experiments/common/') and n!='experiments/common/run_fjsp_eoh_gap.py':
            if b!=subprocess.check_output(['git','show',PUBLIC+':'+n],cwd=ROOT):raise ValueError('frozen public source changed: '+n)
        if n in payload and payload[n]!=b:raise ValueError('public executor replacement prohibited')
        payload[n]=b
    for name in ('DELIVERY.json','FINAL_DELIVERY_CHECKS.json','OBP_PRESET_STATE_ACCEPTANCE.json','OBP_V2_INTERFACE_ACCEPTANCE.json','latest-offline.json'):
        payload['delivery/'+name]=(ROOT/'reports/triad-package-20261113'/name).read_bytes()
    forbidden=('runs','reports','logs','account-gate','.venv','.ssh','__pycache__','wire_responses','responses')
    for n in payload:
        if any(part in forbidden or part.endswith(('.lock','.key','.env','.pyc')) for part in Path(n).parts):raise ValueError('forbidden deployment member '+n)
    release=dict(version='triad-six-groups-prepared-r3',commit=PUBLIC,branch='codex/fjsp-execution-20261112',engineering_commit=commit,base_zip_sha256=BASE_SHA,code_ready=True,run_ready=False,formal_search_authorized=False,protocol_status='pending',supersedes_OBP_packages=['r1','r2'],files={n:digest(b) for n,b in sorted(payload.items())})
    payload['release.json']=(json.dumps(release,ensure_ascii=False,indent=2)+'\n').encode()
    with zipfile.ZipFile(OUTPUT,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for n,b in sorted(payload.items()):z.writestr(n,b)
    with zipfile.ZipFile(OUTPUT) as z:
        if z.testzip() or any(digest(z.read(n))!=h for n,h in release['files'].items()):raise ValueError('ZIP/member verification failed')
    value=dict(zip=str(OUTPUT),sha256=digest(OUTPUT.read_bytes()),bytes=OUTPUT.stat().st_size,files=len(payload),engineering_commit=commit,public_commit=PUBLIC,
      public_code_files_unchanged=sum(n.startswith('code/') for n in payload),old_runs_included=False,credentials_included=False,account_authority_included=False,
      uploaded=False,compute_node_verified=False,API_requests=0,actual_solves=0,LKH_runs=0)
    OUTPUT.with_suffix('.zip.sha256').write_text(value['sha256']+'  '+OUTPUT.name+'\n');OUTPUT.with_suffix('.audit.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
