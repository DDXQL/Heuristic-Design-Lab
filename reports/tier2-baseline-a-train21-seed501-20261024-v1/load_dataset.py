"""Portable read-only baseline loader; Python stdlib, no project/run dependency.

Imports no scheduler, model client or data loader. Returns invalid records with
fitness=None unless valid_only=True. Validity/evidence levels remain in manifest.
"""
import hashlib
import json
from pathlib import Path
from statistics import fmean


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def load(directory=None,*,valid_only=False):
    directory=Path(directory or Path(__file__).parent).resolve()
    manifest=json.loads((directory/'Dataset_manifest.json').read_text())
    protocol_path=directory/'Protocol.json'
    if sha(protocol_path)!=manifest['protocol_sha256'] or (directory/'Protocol.sha256').read_text().strip()!=manifest['protocol_sha256']:
        raise ValueError('dataset protocol hash mismatch')
    protocol=json.loads(protocol_path.read_text())
    if protocol['seed']!=501 or sha(directory/'H_frozen.json')!=protocol['H_sha256']:
        raise ValueError('dataset H/seed mismatch')
    if len(manifest['results'])!=55 or set(manifest['results'])!={s['id'] for s in protocol['strategies']}:
        raise ValueError('dataset strategy coverage mismatch')
    result={}
    for identifier,binding in manifest['results'].items():
        path=(directory/binding['path']).resolve()
        if not path.is_relative_to(directory) or sha(path)!=binding['sha256']:
            raise ValueError('dataset result hash mismatch: '+identifier)
        record=json.loads(path.read_text())
        if record['valid']!=binding['valid'] or record['fitness']!=binding['fitness']:
            raise ValueError('dataset result metadata mismatch')
        if record['valid']:
            rows=record['instances']
            if [r['file'] for r in rows]!=[r['file'] for r in protocol['instances']]:
                raise ValueError('dataset complete train21 required')
            for row,expected in zip(rows,protocol['instances']):
                if row['lower_bound']!=expected['LB'] or row['score']!=-row['makespan']/expected['LB']:
                    raise ValueError('dataset LB/score mismatch')
            if record['fitness']!=fmean(r['score'] for r in rows):raise ValueError('dataset Fitness mismatch')
        elif record['fitness'] is not None:raise ValueError('invalid dataset record cannot have complete Fitness')
        if not valid_only or record['valid']:result[identifier]=record
    return result


if __name__=='__main__':
    values=load();print({'strategies':len(values),'valid':sum(r['valid'] for r in values.values()),'scheduler_calls':0,'API_requests':0})
