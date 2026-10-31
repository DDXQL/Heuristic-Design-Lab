"""Read-only live status and explicitly declared train inputs for the CLI."""
from pathlib import Path
from .storage import read, sha, digest
from .search import ranked


def settings(path):
    from .evolution_v1 import config
    path=Path(path).resolve()
    value=read(path)
    for key in ('data_manifest','h_file','p0_file'):
        if value.get(key):value[key]=str((path.parent/value[key]).resolve())
    return config(value)


def inputs(c):
    """Snapshot source content at prepare; no network or held-out split routing."""
    hs=data=None;provenance={}
    if c.get('h_file'):
        path=Path(c['h_file']);hs=read(path)
        if isinstance(hs,dict):hs=hs['members']
        hs=[r.get('candidate',r) for r in hs]
        provenance['H']={'path':str(path),'sha256':sha(path),'order':'file order, no reranking'}
    if c.get('data_manifest'):
        path=Path(c['data_manifest']);manifest=read(path)
        if manifest.get('problem')!=c['problem'] or manifest.get('split') not in ('train','synthetic-development'):
            raise ValueError('explicit matching problem and train/development manifest required; no holdout tuning')
        data=[]
        for row in manifest['instances']:
            source=(path.parent/row['path']).resolve()
            if row.get('sha256')!=sha(source):raise ValueError('instance source hash missing/changed')
            if c['problem']=='fjsp' and source.suffix=='.fjsp':
                from llm4ad.task.optimization.fjsp_set.instances import load_instance
                obj=load_instance(source)
                value={'machines':obj.machine_count,'jobs':[[[list(a) for a in op.alternatives] for op in job] for job in obj.jobs]}
            else:value=read(source)
            data.append({'file':row.get('file',source.name),'split':manifest['split'],
                         'value':value,'sha256':digest(value),'source_sha256':row['sha256']})
        if not data:raise ValueError('empty dataset manifest')
        provenance['data']={'path':str(path),'sha256':sha(path),'split':manifest['split']}
    return hs,data,provenance


def snapshot(directory, *, problem=None):
    """A live snapshot is not a crash-recovery certification; never edits files."""
    from .evolution_v1 import VERSION
    directory=Path(directory).resolve()
    p=read(directory/'Protocol.json');s=read(directory/'checkpoint.json')
    identity=sha(directory/'Protocol.json')
    if (p.get('version')!=VERSION or read(directory/'Protocol.receipt.json')['sha256']!=identity
            or s.get('identity')!=identity or problem and p['config']['problem']!=problem):
        raise ValueError('status protocol/problem identity mismatch')
    return progress(s,p,writer_lock=(directory/'.coordinator.lock').exists())


def progress(s,p,**extra):
    c=p['config'];valid=[t for t in s['tasks'].values() if t.get('valid')]
    inflight=[t['id'] for t in s['tasks'].values() if t['status'] in ('request_reserved','evaluation_reserved')]
    return {'phase':s['phase'],'problem':c['problem'],'generation_transport':c['api_mode'],
        'evaluation_mode':c['evaluation_mode'],'data_split':sorted({r['split'] for r in p['instances']}),
        'generation':s['generation'],'target_generations':c['generations'],
        'completed_candidates':s['completed_tasks'],'best_evaluated_fitness':max(t['fitness'] for t in valid) if valid else None,
        'score_is_mock':c['evaluation_mode']=='mock','initialization_requests':s['initialization_requests'],
        'initialization_request_cap':c['initialization_request_cap'],
        'generation_requests':s['generation_requests'],'generation_request_cap':c['generation_request_cap'],
        'api_attempts_reserved':(s['initialization_requests']+s['generation_requests']) if c['api_mode']=='real' else 0,
        'api_attempt_cap':c.get('api_attempt_cap'),'inflight':inflight,**extra}
