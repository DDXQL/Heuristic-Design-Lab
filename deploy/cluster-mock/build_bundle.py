#!/usr/bin/env python3
"""Sanitize the existing frozen ZIP; public execution bytes are unchanged."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
ROOT=Path(__file__).resolve().parents[2]
SOURCE=Path('/Users/DDXQL/Developer/transfer-outbox/fjsp-u1000-v3-engineering-923781f-20261113.zip')
OUTPUT=Path('/Users/DDXQL/Developer/transfer-outbox/fjsp-cluster-noapi-923781f-20261113-r1.zip')
SOURCE_SHA='57e03373455b54731e3add2039dc222646e324f9cedcd814fdc422edb04d0747'


def digest(raw):return hashlib.sha256(raw).hexdigest()


def build(output=None):
    global OUTPUT
    if output is not None:OUTPUT=Path(output)
    if digest(SOURCE.read_bytes())!=SOURCE_SHA:raise ValueError('original frozen ZIP changed')
    if OUTPUT.exists():raise FileExistsError('preserve existing package; choose a new explicit revision')
    payload={};excluded=[]
    with zipfile.ZipFile(SOURCE) as archive:
        source_release=json.loads(archive.read('release.json'))
        for name,expected in source_release['files'].items():
            raw=archive.read(name)
            if digest(raw)!=expected:raise ValueError('source manifest mismatch: '+name)
            keep=(name.startswith(('code/','preparations/fjsp-long/','.agents/','LICENSES/','docs/state-a-'))
                  or name in ('experiments/common/manage.py','experiments/common/run_frozen.py',
                              'experiments/fjsp_long/mock.json','experiments/fjsp_long/research.pending.json',
                              'requirements.txt','LICENSE','THIRD_PARTY_NOTICES.md','AGENTS.md','docs/中文科研写作规范.md'))
            if keep:payload[name]=raw
            else:excluded.append(name)
    for p in (ROOT/'deploy/cluster-mock').glob('*'):
        if p.is_file() and p.suffix in ('.py','.sbatch','.md'):payload[str(p.relative_to(ROOT))]=p.read_bytes()
    if any(any(part in ('runs','account-gate','.venv','.ssh','logs','reports') or part.endswith(('.key','.lock')) for part in Path(n).parts) for n in payload):
        raise ValueError('credentials, local authority, locks or old result paths reached sanitized package')
    if any(n.startswith('reports/') for n in payload):raise AssertionError('old evidence included')
    preserved={n:digest(raw) for n,raw in payload.items() if n in source_release['files']}
    assert all(v==source_release['files'][n] for n,v in preserved.items())
    release={'version':'frozen-source-with-noapi-deployment-overlay-v1','commit':source_release['commit'],
             'branch':source_release['branch'],'source_archive_sha256':SOURCE_SHA,
             'deployment_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
             'files':{n:digest(raw) for n,raw in payload.items()},'excluded_source_paths':excluded,
             'frozen_files_preserved':preserved,'formal_search_authorized':False,'old_results_included':False}
    payload['release.json']=(json.dumps(release,ensure_ascii=False,indent=2)+'\n').encode()
    with zipfile.ZipFile(OUTPUT,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for n,raw in sorted(payload.items()):z.writestr(n,raw)
    with zipfile.ZipFile(OUTPUT) as z:
        if z.testzip() is not None:raise ValueError('ZIP CRC failed')
    sha=digest(OUTPUT.read_bytes());OUTPUT.with_suffix('.zip.sha256').write_text(sha+'  '+OUTPUT.name+'\n')
    record={'zip':str(OUTPUT),'sha256':sha,'bytes':OUTPUT.stat().st_size,'files':len(payload),
            'base_commit':release['commit'],'deployment_commit':release['deployment_commit'],
            'original_frozen_files_preserved':len(preserved),'old_results_removed':True,
            'uploaded':False,'compute_node_verified':False,'model_requests':0,'formal_solves':0}
    OUTPUT.with_suffix('.audit.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(record,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    build(parser.parse_args().output)
