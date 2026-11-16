#!/usr/bin/env python3
"""Local allowlisted ZIP, no transport, credentials, run states or execution."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
ROOT=Path(__file__).resolve().parents[2]
OUTBOX=Path('/Users/DDXQL/Developer/transfer-outbox')
BASE=OUTBOX/'triad-fjsp-stop-recovery-20261116-r11.zip'
TARGET=OUTBOX/'triad-six-groups-20261116-r12.zip'


def build():
    expected=BASE.with_suffix('.zip.sha256').read_text().split()[0]
    assert hashlib.sha256(BASE.read_bytes()).hexdigest()==expected
    with zipfile.ZipFile(BASE) as z:names=set(z.namelist())-{'release.json'}
    # Reuse exact admitted runtime/input allowlist, replace sources from NEW tree.
    # Remove old delivery metadata, old source-pin and validation data from runtime packet.
    names={n for n in names if not n.startswith(('delivery/','preparations/stop-recovery-20261116/','configurations/triad-adopted-20261115/pairs/'))}
    names={n for n in names if 'validation' not in n and not any(p in Path(n).parts for p in ('runs','logs','operations','run-gates'))}
    for prefix in ('experiments/triad','configurations/six-groups-20261116'):
        for p in (ROOT/prefix).glob('*'):
            if p.is_file() and p.suffix in ('.py','.sbatch','.json'):names.add(str(p.relative_to(ROOT)))
    for n in ('README.md','docs/六组实验按序运行.md','docs/六组实验18份清单.md','AGENTS.md'):
        names.add(n)
    # Include exactly the train manifests and their local files; never current test data.
    for n in ('preparations/eoh-gap/train21.manifest.json','preparations/triad/tsp/train20.manifest.json','preparations/triad/obp-official-20261115/train.manifest.json'):
        names.add(n);p=ROOT/n
        for row in json.loads(p.read_text())['instances']:names.add(str((p.parent/row['path']).resolve().relative_to(ROOT)))
    names={n for n in names if (ROOT/n).is_file() and not (ROOT/n).is_symlink()}
    # Official OBP validation content is historical exposure metadata, not runtime input.
    allowed_obp={str((ROOT/'preparations/triad/obp-official-20261115'/r['path']).relative_to(ROOT)) for r in json.loads((ROOT/'preparations/triad/obp-official-20261115/train.manifest.json').read_text())['instances']}
    names={n for n in names if not n.startswith('preparations/triad/obp-official-20261115/instances/') or n in allowed_obp}
    forbidden=('generation.lock','.execution.lock','.coordinator.lock','API_attempts.json','checkpoint.json','.key','.env','STOP.json')
    assert not any(Path(n).name in forbidden or n.startswith(('runs/','logs/','.venv/')) for n in names)
    payload={n:(ROOT/n).read_bytes() for n in sorted(names)}
    release={'version':'triad-six-groups-20261116-r12','engineering_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'public_commit':'923781f05686f1899c24fd7899fb3bc6b1df1562','files':{n:hashlib.sha256(v).hexdigest() for n,v in payload.items()},
        'entry':'docs/六组实验按序运行.md','API_execution_authorized':False,'existing_R11_included':False}
    assert not TARGET.exists(),'preserve existing frozen package; choose explicit new revision instead'
    with zipfile.ZipFile(TARGET,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for n,v in payload.items():z.writestr(n,v)
        z.writestr('release.json',json.dumps(release,ensure_ascii=False,indent=2))
    h=hashlib.sha256(TARGET.read_bytes()).hexdigest();TARGET.with_suffix('.zip.sha256').write_text(h+'  '+TARGET.name+'\n')
    with zipfile.ZipFile(TARGET) as z:
        assert all(hashlib.sha256(z.read(n)).hexdigest()==v for n,v in release['files'].items())
    result={'prepared':True,'uploaded':False,'new_compute_verified':False,'path':str(TARGET),'bytes':TARGET.stat().st_size,'sha256':h,'files':len(payload),'source_commit':release['engineering_commit'],'API_requests':0,'solves':0}
    TARGET.with_suffix('.zip.audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':build()
