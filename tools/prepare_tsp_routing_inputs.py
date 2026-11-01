"""Recover only 20 historical training coordinate files, never a whole run/tree."""
import hashlib
from pathlib import Path
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read, write, sha


def prepare():
    report=ROOT/'reports/tsp-pilot-20261028-complete'
    receipt=read(report/'Raw_manifest.json')
    archive=report/'Raw_evidence.tar.gz'
    if sha(archive)!=receipt['archive_sha256']:raise ValueError('historical archive SHA changed')
    target=ROOT/'experiments/common/fixtures/tsp-routing-train20'
    rows=[]
    prefix='runs/tsp-pilot-20261026-v2/data/train/'
    with tarfile.open(archive) as tf:
        for i in range(20):
            name=f'train_{i:03d}.json';member=prefix+name
            info=tf.getmember(member)
            if not info.isfile() or info.size>100000:raise ValueError('unexpected training data member')
            content=tf.extractfile(info).read()
            expected=receipt['files'][member]['sha256']
            if hashlib.sha256(content).hexdigest()!=expected:raise ValueError('training archive member changed')
            path=target/name
            if path.exists() and path.read_bytes()!=content:raise ValueError('existing training asset differs')
            path.parent.mkdir(parents=True,exist_ok=True)
            if not path.exists():path.write_bytes(content)
            rows.append({'file':name,'path':f'tsp-routing-train20/{name}','sha256':expected})
    base=target.parent
    provenance={'archive_sha256':receipt['archive_sha256'],'source_prefix':prefix,
        'source_manifest_sha256':sha(report/'Raw_manifest.json'),
        'H_source':'reports/tsp-pilot-20261028-complete/H_frozen.json',
        'H_sha256':sha(report/'H_frozen.json'),
        'notice':'Historical train only, not a new holdout; five selected H are all handwritten.'}
    for name,selected in [('tsp-routing-train20.manifest.json',rows),('tsp-routing-smoke2.manifest.json',rows[:2])]:
        value={'problem':'tsp','split':'train','instances':selected,'provenance':provenance}
        path=base/name
        if path.exists() and read(path)!=value:raise ValueError('existing manifest differs')
        if not path.exists():write(path,value)
    return {'training_instances':20,'smoke_instances':2,'cities':50,'API_requests':0,'solves':0}


if __name__=='__main__':
    import json
    print(json.dumps(prepare(),indent=2))
