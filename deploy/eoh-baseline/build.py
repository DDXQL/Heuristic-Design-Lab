#!/usr/bin/env python3
"""Standalone sanitized release, using existing 923781f public bytes, no run imports."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'deploy/eoh-baseline'),str(ROOT/'code'),str(ROOT)]
import eoh_gap as e
BASE=Path('/Users/DDXQL/Developer/transfer-outbox/fjsp-cluster-noapi-923781f-20261113-r1.zip')
BASE_SHA='b7941d16b82caa9929c644afd8d75500dddba260a5f0141cef96d010f2a92b7d'
OUTPUT=Path('/Users/DDXQL/Developer/transfer-outbox/fjsp-eoh-J-prepared-923781f-20261113-r1.zip')
PUBLIC='923781f05686f1899c24fd7899fb3bc6b1df1562'


def sha(b):return hashlib.sha256(b).hexdigest()

def main():
    if sha(BASE.read_bytes())!=BASE_SHA:raise ValueError('admitted base ZIP changed')
    if OUTPUT.exists():raise FileExistsError('preserve existing frozen release; choose a new explicit revision')
    payload={}
    with zipfile.ZipFile(BASE) as z:
        release=json.loads(z.read('release.json'))
        for n,h in release['files'].items():
            if n.startswith('code/') or n in ('requirements.txt','LICENSE','THIRD_PARTY_NOTICES.md') or n.startswith('LICENSES/'):
                raw=z.read(n)
                if sha(raw)!=h:raise ValueError('base member changed: '+n)
                payload[n]=raw
    additions=set(e.sources())
    additions.update(str(p.relative_to(ROOT)) for p in (ROOT/'deploy/eoh-baseline').glob('*') if p.is_file() and p.suffix in ('.json','.md','.py','.sbatch'))
    additions.update(str(p.relative_to(ROOT)) for p in (ROOT/'preparations/eoh-gap').rglob('*') if p.is_file())
    additions.update(('experiments/common/_single_run.py','deploy/cluster-mock/control.py','deploy/cluster-mock/inspect_remote.py'))
    for n in additions:
        raw=(ROOT/n).read_bytes()
        if n.startswith(('code/','tools/')) or n in ('experiments/common/_single_run.py','experiments/common/manage.py','experiments/common/run_frozen.py') or n.startswith('experiments/common/run_tsp') or n in ('experiments/common/run_fjsp_eoh_single.py','experiments/common/summarize_tsp_eoh.py','experiments/common/summarize_tsp.py'):
            frozen=subprocess.check_output(['git','show',PUBLIC+':'+n],cwd=ROOT)
            if sha(raw)!=sha(frozen):raise ValueError('public/native source changed: '+n)
        if n in payload and payload[n]!=raw:raise ValueError('would replace public code: '+n)
        payload[n]=raw
    forbidden=('runs','account-gate','.venv','.ssh','logs','reports','__pycache__')
    for n in payload:
        if any(part in forbidden or part.endswith(('.key','.lock','.pyc','.env')) for part in Path(n).parts):raise ValueError('forbidden deploy member: '+n)
        if (ROOT/n).is_symlink():raise ValueError('symlink excluded: '+n)
    manifest=dict(version='fjsp-eoh-J-prepared-release-v1',commit=PUBLIC,
      engineering_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),base_zip_sha256=BASE_SHA,
      formal_search_authorized=False,protocol_status='pending',old_runs_included=False,
      files={n:sha(raw) for n,raw in sorted(payload.items())})
    payload['release.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    with zipfile.ZipFile(OUTPUT,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for n,raw in sorted(payload.items()):z.writestr(n,raw)
    with zipfile.ZipFile(OUTPUT) as z:
        if z.testzip():raise ValueError('CRC check failed')
        if any(sha(z.read(n))!=v for n,v in manifest['files'].items()):raise ValueError('manifest check failed')
    digest=sha(OUTPUT.read_bytes());OUTPUT.with_suffix('.zip.sha256').write_text(digest+'  '+OUTPUT.name+'\n')
    audit=dict(zip=str(OUTPUT),sha256=digest,bytes=OUTPUT.stat().st_size,files=len(payload),public_commit=PUBLIC,
      engineering_commit=manifest['engineering_commit'],public_code_files_unchanged=sum(n.startswith('code/') for n in payload),
      API_requests=0,actual_solves=0,credentials_included=False,Mac_checkpoints_included=False,uploaded=False,compute_node_verified=False)
    OUTPUT.with_suffix('.audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(audit,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
