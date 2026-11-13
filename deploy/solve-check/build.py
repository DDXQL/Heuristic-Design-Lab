#!/usr/bin/env python3
"""Small overlay only: reuse the admitted remote base, do not redeploy Mock."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
ROOT=Path(__file__).resolve().parents[2]
OUTPUT=Path('/Users/DDXQL/Developer/transfer-outbox/fjsp-real-solve-16-923781f-20261113-r1.zip')


def build(output):
    output=Path(output)
    if output.exists():raise FileExistsError('preserve existing overlay; explicit new revision required')
    payload={str(p.relative_to(ROOT)):p.read_bytes() for p in (ROOT/'deploy/solve-check').glob('*')
             if p.is_file() and p.suffix in ('.py','.json','.sbatch','.md')}
    release={'version':'bounded-real-solve-overlay-v1','commit':'923781f05686f1899c24fd7899fb3bc6b1df1562',
             'deployment_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
             'files':{k:hashlib.sha256(v).hexdigest() for k,v in payload.items()},'public_executor_included':False,
             'API_requests':0,'max_physical_solves':16,'actual_solves_performed':0}
    payload['release.json']=(json.dumps(release,ensure_ascii=False,indent=2)+'\n').encode()
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for k,v in payload.items():z.writestr(k,v)
    with zipfile.ZipFile(output) as z:
        if z.testzip() is not None:raise ValueError('CRC failed')
    sha=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(sha+'  '+output.name+'\n')
    print(json.dumps({'path':str(output),'sha256':sha,'bytes':output.stat().st_size,'files':len(payload),
                      'API_requests':0,'actual_solves':0,'uploaded':False,'submitted':False},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=OUTPUT)
    build(parser.parse_args().output)
