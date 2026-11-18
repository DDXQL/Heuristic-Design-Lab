#!/usr/bin/env python3
"""Build an independent source/data packet from frozen R13; no deployment."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
ROOT=Path(__file__).resolve().parents[2]
OUT=Path('/Users/DDXQL/Developer/transfer-outbox')
BASE=OUT/'triad-tsp-lkh-candidate-20261117-r13.zip'
TARGET=OUT/'triad-explore-runtime-20261118-r14.zip'


def build():
    assert not TARGET.exists(),'preserve frozen packet; choose an explicit new revision'
    assert hashlib.sha256(BASE.read_bytes()).hexdigest()==BASE.with_suffix('.zip.sha256').read_text().split()[0]
    with zipfile.ZipFile(BASE) as z:
        old=json.loads(z.read('release.json'))
        payload={n:z.read(n) for n in old['files'] if not n.startswith('preparations/operations/lkh-candidate-3.0.13/')}
    for name in ('AGENTS.md','README.md','docs/R13旧TSP501-Mac独立菜单-20261118.md','docs/R14公共轻量流程-离线交付-20261118.md','docs/成功返回1000口径-只读差异评估-20261118.md',
                 'experiments/triad/shared_admission.py','experiments/triad/entry.py','experiments/triad/parallel.py','experiments/triad/six_ops.py',
                 'experiments/triad/explore_tests.py','experiments/triad/explore_build.py','experiments/triad/explore_mac.py','experiments/triad/r13_tsp_mac.py','experiments/triad/r13_bridge_tests.py'):
        payload[name]=(ROOT/name).read_bytes()
    assert not any(n.startswith(('runs/','logs/','.venv/')) or Path(n).name in ('generation.lock','API_attempts.json','checkpoint.json','STOP.json') or Path(n).suffix=='.key' for n in payload)
    release={'version':'triad-explore-runtime-20261118-r14','engineering_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
      'parent_commit':'963499d6943bdd8bdac3f1805f8186f4561fba9e','public_commit':'923781f05686f1899c24fd7899fb3bc6b1df1562',
      'files':{n:hashlib.sha256(v).hexdigest() for n,v in payload.items()},'entry':'docs/R14公共轻量流程-离线交付-20261118.md',
      'runtime_policy':'explore-light-v1','real_execution_authorized':False,'actual_TSP_reference_included':False,
      'reuse_validated_R13_reference_without_resolving':True,'existing_runs_included':False}
    with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for n,raw in payload.items():z.writestr(n,raw)
        z.writestr('release.json',json.dumps(release,ensure_ascii=False,indent=2))
    h=hashlib.sha256(TARGET.read_bytes()).hexdigest()
    with TARGET.with_suffix('.zip.sha256').open('x') as f:f.write(h+'  '+TARGET.name+'\n')
    with zipfile.ZipFile(TARGET) as z:assert all(hashlib.sha256(z.read(n)).hexdigest()==v for n,v in release['files'].items())
    report={'prepared':True,'uploaded':False,'compute_node_verified':False,'path':str(TARGET),'bytes':TARGET.stat().st_size,'sha256':h,'files':len(payload),'source_commit':release['engineering_commit'],'API_requests':0,'actual_solves':0,'Slurm_submitted':False,'actual_reference_binding_pending':True}
    with TARGET.with_suffix('.zip.audit.json').open('x') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':build()
