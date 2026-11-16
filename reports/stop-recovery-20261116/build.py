"""Freeze R11 over the exact R9 bundle; no checkpoint, result, key or lease upload."""
import hashlib,json,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];BOX=Path('/Users/DDXQL/Developer/transfer-outbox');BASE=BOX/'triad-fjsp-native-continuation-20261115-r9.zip';OUT=BOX/'triad-fjsp-stop-recovery-20261116-r11.zip'
sha=lambda b:hashlib.sha256(b).hexdigest()
assert sha(BASE.read_bytes())=='9361b94d8b3812cdef8a49f79876f9fba765cf60b2cc740307fe8bfaa0512a2f'
if OUT.exists():raise FileExistsError('frozen package exists; do not overwrite')
check=json.loads((ROOT/'reports/stop-recovery-20261116/OFFLINE_CHECKS.json').read_text());assert check['passed']
assert not subprocess.check_output(['git','diff','923781f','--','code/','experiments/common/run_frozen.py'],cwd=ROOT)
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
with zipfile.ZipFile(BASE) as z:
 old=json.loads(z.read('release.json'));payload={n:z.read(n) for n in old['files']};assert all(sha(raw)==old['files'][n] for n,raw in payload.items())
paths=[p for folder in ['experiments/triad','deploy/stop-recovery','preparations/stop-recovery-20261116'] for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.json','.md','.sbatch','.sh')]
paths += [ROOT/'AGENTS.md',ROOT/'docs/R11已知失败审计恢复.md']
for p in paths:
 n=str(p.relative_to(ROOT));raw=p.read_bytes();assert not p.is_symlink() and raw==subprocess.check_output(['git','show',commit+':'+n],cwd=ROOT);payload[n]=raw
payload['delivery/STOP_RECOVERY_OFFLINE.json']=(ROOT/'reports/stop-recovery-20261116/OFFLINE_CHECKS.json').read_bytes()
for n in payload:assert not any(x in ('runs','logs','reports','.venv','.ssh','__pycache__','account-gate','responses','wire_responses') or x.endswith(('.lock','.key','.pyc','.env')) for x in Path(n).parts),n
release={'version':'triad-audited-R9-stop-recovery-r11','engineering_commit':commit,'commit':'923781f05686f1899c24fd7899fb3bc6b1df1562','base_zip_sha256':sha(BASE.read_bytes()),'CODE_READY':True,'RUN_READY':False,'uploaded':False,'actual_compute_recovery_verified':False,'old_source_evidence_uploaded':False,'scope':'audited one522/five known-not-sent;1167 charges retained; current RNG/partial population/original window; finite2 requests<=84 inclusive solves before full continuation; no automatic recovery or requests','files':{n:sha(raw) for n,raw in sorted(payload.items())}}
with zipfile.ZipFile(OUT,'x',compression=zipfile.ZIP_DEFLATED) as z:
 for n,raw in sorted(payload.items()):z.writestr(n,raw)
 z.writestr('release.json',json.dumps(release,ensure_ascii=False,indent=2)+'\n')
with zipfile.ZipFile(OUT) as z:assert not z.testzip() and all(sha(z.read(n))==h for n,h in release['files'].items())
record={'zip':str(OUT),'sha256':sha(OUT.read_bytes()),'bytes':OUT.stat().st_size,'files':len(payload)+1,'engineering_commit':commit,'prepared':True,'uploaded':False,'remote_account_handoff_performed':False,'Slurm_submitted':False,'API_requests':0,'actual_solves':0,'compute_node_verified':False,'credentials_or_old_runs_included':False,'source_request_charges':1167,'finite_max_new_requests':2,'finite_max_new_solves_including_recheck':84,'original_deadline_plus08':'2026-11-17 18:59:15 (original fractional seconds retained)'}
OUT.with_suffix('.zip.sha256').write_text(record['sha256']+'  '+OUT.name+'\n');OUT.with_suffix('.audit.json').write_text(json.dumps(record,indent=2)+'\n');(ROOT/'reports/stop-recovery-20261116/DELIVERY.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
