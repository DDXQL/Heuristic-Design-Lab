#!/usr/bin/env python3
"""Freeze the native-admission overlay over the exact R8 bundle, without runs or credentials."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[2]
OUTBOX=Path('/Users/DDXQL/Developer/transfer-outbox')
BASE=OUTBOX/'triad-concurrent-prompt-v2-20261115-r8.zip'
BASE_SHA='6cfed839eac4042934fac275b1dd40a59acd94c72dd61e6f4560edeb6e0b93ec'
OUTPUT=OUTBOX/'triad-fjsp-native-continuation-20261115-r9.zip'
PUBLIC='923781f05686f1899c24fd7899fb3bc6b1df1562'

def digest(raw):return hashlib.sha256(raw).hexdigest()

def main():
    if OUTPUT.exists():raise FileExistsError('frozen archive exists; do not overwrite')
    if digest(BASE.read_bytes())!=BASE_SHA:raise ValueError('R8 base differs')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    if subprocess.check_output(['git','diff',PUBLIC,'--','code/','experiments/common/run_frozen.py'],cwd=ROOT):raise ValueError('public executor changed')
    with zipfile.ZipFile(BASE) as z:
        original=json.loads(z.read('release.json'));payload={n:z.read(n) for n in original['files']}
        if any(digest(b)!=original['files'][n] for n,b in payload.items()):raise ValueError('R8 member differs')
    names=[p for folder in ['experiments/triad','configurations/triad-adopted-20261115','preparations/native-continuation-20261115'] for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.json','.md','.sh','.sbatch')]
    names+=[ROOT/'AGENTS.md',ROOT/'docs/FJSP原生门槛承接.md']
    for p in names:
        n=str(p.relative_to(ROOT));raw=p.read_bytes()
        if p.is_symlink() or subprocess.check_output(['git','show',commit+':'+n],cwd=ROOT)!=raw:raise ValueError('not committed: '+n)
        payload[n]=raw
    checks=ROOT/'reports/native-continuation-20261115/OFFLINE_CHECKS.json'
    if not json.loads(checks.read_text())['passed']:raise ValueError('offline checks incomplete')
    payload['delivery/NATIVE_CONTINUATION_OFFLINE.json']=checks.read_bytes()
    for n,raw in payload.items():
        if any(x in ('runs','logs','reports','__pycache__','.venv','.ssh','account-gate','wire_responses','responses') or x.endswith(('.lock','.key','.pyc','.env')) for x in Path(n).parts):raise ValueError('forbidden package member '+n)
        if n.startswith('code/') or n=='experiments/common/run_frozen.py':
            if raw!=subprocess.check_output(['git','show',PUBLIC+':'+n],cwd=ROOT):raise ValueError('public source differs')
    release={'version':'triad-fjsp-native-continuation-r9','engineering_commit':commit,'engineering_branch':'codex/fjsp-native-continuation-20261115','commit':PUBLIC,'base_zip_sha256':BASE_SHA,
        'code_ready':True,'run_ready':False,'uploaded':False,'new_compute_verification':False,'formal_search_authorized':False,
        'scope':'user-adopted native admission for FJSP EoH501/502/503; explicit settled501/502 continuation; original clocks/caps and spent requests imported; no automatic execution',
        'evidence':'delivery/NATIVE_CONTINUATION_OFFLINE.json; other delivery evidence retains historical scope',
        'files':{n:digest(raw) for n,raw in sorted(payload.items())}}
    payload['release.json']=(json.dumps(release,ensure_ascii=False,indent=2)+'\n').encode()
    with zipfile.ZipFile(OUTPUT,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for n,raw in sorted(payload.items()):z.writestr(n,raw)
    with zipfile.ZipFile(OUTPUT) as z:
        if z.testzip() or any(digest(z.read(n))!=h for n,h in release['files'].items()):raise ValueError('ZIP verification failed')
    value={'zip':str(OUTPUT),'sha256':digest(OUTPUT.read_bytes()),'bytes':OUTPUT.stat().st_size,'files':len(payload),'engineering_commit':commit,'public_commit':PUBLIC,'old_runs_included':False,'credentials_included':False,'account_lease_included':False,'uploaded':False,'new_compute_verification':False,'API_requests':0,'actual_solves':0}
    OUTPUT.with_suffix('.zip.sha256').write_text(value['sha256']+'  '+OUTPUT.name+'\n')
    OUTPUT.with_suffix('.audit.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');print(json.dumps(value,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
