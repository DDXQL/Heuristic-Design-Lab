#!/usr/bin/env python3
"""Create a small source/data launch ZIP, no credentials, environments or runs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def sha(value):return hashlib.sha256(value).hexdigest()


def build(source,output):
    output=Path(output).resolve();source=Path(source).resolve()
    if output.exists() or output.with_suffix('.zip.sha256').exists():raise FileExistsError('new package name required')
    names=subprocess.check_output(['git','ls-files','-z','--','code','experiments/common','experiments/fjsp_long',
        'deploy/fjsp-long','tools/fjsp_fixed_h_reuse.py','tools/build_fjsp_launch.py',
        'tools/verify_frozen_execution.py','tools/check_state_a.py','tools/check_state_a_v3.py',
        'tests/test_frozen_execution_offline.py','tests/test_state_a_offline.py','tests/test_state_a_v3_offline.py',
        'requirements.txt','LICENSE','LICENSES','THIRD_PARTY_NOTICES.md','AGENTS.md','.agents',
        'docs/中文科研写作规范.md','docs/state-a-v2','docs/state-a-v3',
        'reports/fjsp-execution-20261112'],cwd=ROOT).decode().rstrip('\0').split('\0')
    # zip paths are explicit relative names, with no symlinks or ambient files.
    payload={}
    for name in names:
        path=ROOT/name
        if path.is_symlink() or any(part in ('.venv','runs','__pycache__') for part in path.parts):raise ValueError('unsafe package source')
        if path.is_file():payload[name]=path.read_bytes()
    prep=source/'preparations/b1-v6-20261029'
    manifest=json.loads((prep/'train21.manifest.json').read_text())
    payload['preparations/fjsp-long/H_frozen.json']=(prep/'H_frozen.json').read_bytes()
    payload['preparations/fjsp-long/train21.manifest.json']=(prep/'train21.manifest.json').read_bytes()
    for row in manifest['instances']:
        path=(prep/row['path']).resolve()
        if not path.is_relative_to(prep.resolve()) or path.is_symlink():raise ValueError('unsafe dataset source')
        raw=path.read_bytes()
        if sha(raw)!=row['sha256']:raise ValueError('declared training instance changed')
        payload['preparations/fjsp-long/'+row['path']]=raw
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    release={'version':'fjsp-launch-release-v1','commit':commit,'branch':branch,
             'files':{k:sha(v) for k,v in payload.items()},
             'scope':'source and declared train21 only; research.pending is deliberately blocked until separately frozen',
             'credentials_included':False,'submitted':False,'transferred':False}
    payload['release.json']=(json.dumps(release,ensure_ascii=False,indent=2)+'\n').encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for k,v in sorted(payload.items()):archive.writestr(k,v)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:raise ValueError('ZIP CRC failed')
        for k,v in release['files'].items():
            if sha(archive.read(k))!=v:raise ValueError('package hash mismatch')
    digest=sha(output.read_bytes())
    output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n')
    return {'path':str(output),'bytes':output.stat().st_size,'sha256':digest,'commit':commit,
            'files':len(payload),'packed':True,'transferred':False,'verified_on_cluster':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.source_root,a.output),indent=2))
