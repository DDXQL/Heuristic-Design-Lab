#!/usr/bin/env python3
"""Read-only evidence audit and derived export. Never generate or solve tours."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'code')]
import argparse,csv,json,math,tarfile
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.problems.tsp.campaign import check,summary,ROOT as WORKSPACE
from heuristic_design.problems.tsp.operations import Adapter


def audit(directory,out):
    p=check(directory);facts=summary(directory);s=facts['state'];out.mkdir(parents=True,exist_ok=True)
    origin=Path(p.get('request_origin',{}).get('directory',str(directory)))
    j=read(origin/'API_attempts.json') if (origin/'API_attempts.json').exists() else {'requests':{},'api_attempts':{}}
    assert len(j['requests'])<=50 and len(j['api_attempts'])<=75
    assert all(len(r['attempt_ids'])<=2 for r in j['requests'].values())
    if s['phase']=='completed':
        assert len(j['requests'])==50
        assert [g['used_new'] for g in facts['groups'] if g['planned_new']]==[10]*5
        assert not any(a['status'] not in ('completed','failed') for a in j['api_attempts'].values())
    outputs=[];physical=0;passes=0;solve_seconds=0.;valid_unique=0;stage_paths=[];nn_vectors={};raw_lengths=0
    for run in sorted((ROOT/'runs').glob(directory.name+'--*')):
        stage_paths.append(run);q=Adapter().check_run(run);state=read(run/'checkpoint.json')
        if s['phase']=='completed':assert state['phase']=='completed' and not (run/'.execution.lock').exists()
        split=q['instances'][0]['file'].split('_')[0]
        vector=[(r['file'],r['sha256'],r['NN_length']) for r in q['instances']]
        if split in nn_vectors:assert vector==nn_vectors[split]
        nn_vectors[split]=vector
        for item in state['evaluations'].values():
            if item['status']!='completed':continue
            path=run/item['path'];assert sha(path)==item['sha256'];result=read(path)
            Adapter().validate_result(result,q['instances']);physical+=len(q['instances']);valid_unique+=int(result['valid'])
            for row,spec in zip(result['instances'],q['instances']):
                coordinates=read(spec['source'])['coordinates'];tour=row['tour'];n=len(coordinates)
                assert len(tour)==n+1 and tour[0]==tour[-1]==0 and sorted(tour[:-1])==list(range(n))
                value=math.fsum(math.hypot(coordinates[a][0]-coordinates[b][0],coordinates[a][1]-coordinates[b][1]) for a,b in zip(tour,tour[1:]))
                assert math.isclose(value,row['length'],rel_tol=1e-14,abs_tol=1e-12)
                raw_lengths+=1;passes+=row['captured_solves'];solve_seconds+=row['single_solve_seconds']+row['deterministic_recheck_seconds']
        for task in state['tasks'].values():
            c=task.get('candidate')
            if c:
                name=run.name+'__'+task['id'].replace('/','__')
                target=out/'Candidates'/(name+'.py');target.parent.mkdir(exist_ok=True);target.write_text(c['code'])
                outputs.append({'stage':run.name.removeprefix(directory.name+'--'),'id':task['id'],'kind':c['kind'],'key':c['key'],'file':str(target.relative_to(out)),
                    'valid':task['valid'],'fitness':task['fitness'],'duplicate':task.get('AST_duplicate'),'cache_hit':task.get('cache_hit')})
    for split,vector in nn_vectors.items():
        nn=read(directory/'NN'/f'{split}.json')['instances'];assert [(r['file'],r['sha256'],r['NN_length']) for r in nn]==vector
        assert all(math.isfinite(r['NN_length']) and r['NN_length']>0 for r in nn)
    if (directory/'H_frozen.json').exists():
        h=read(directory/'H_frozen.json');assert 2<=len(h['members'])<=5
        expected=[];seen=set()
        for name in ['manual-H','H']:
            f=Adapter().summary(ROOT/'runs'/(directory.name+'--'+name))
            for row in f['records']:
                if row['valid'] and row['candidate']['key'] not in seen:seen.add(row['candidate']['key']);expected.append(row)
        expected=sorted(expected,key=lambda r:(-r['fitness'],r['id']))[:5]
        assert h['selected_ids']==[r['id'] for r in expected]
        assert h['members']==[r['candidate'] for r in expected]
        dispositions=[]
        for r in h['dispositions']:
            reason='selected' if r['id'] in h['selected_ids'] else 'below_quality_cutoff' if r['reason']=='eligible' else r['reason']
            dispositions.append({**r,'final_disposition':reason})
        write(out/'H_selection.json',{'ordered_members':h['selected_ids'],'dispositions':dispositions})
    if (directory/'P0.json').exists():
        pop=read(directory/'P0.json');ref=pop['static_reference'];static=Adapter().summary(ROOT/'runs'/(directory.name+'--static'))
        rows=sorted([r for r in static['records'] if r['valid']],key=lambda r:(-r['fitness'],r['id']))
        assert ref==rows[0];assert pop['members'][0]['candidate']['key']==ref['candidate']['key']
    if s['phase']=='completed':
        selected=read(directory/'Validation_candidates.json');final=read(directory/'Final_frozen.json')
        assert selected['frozen_at']<read(ROOT/'runs'/(directory.name+'--validation')/'Run_clock.json')['start']
        assert len(selected['candidates'])<=5
        for split in ['confirmation','transfer']:
            assert final['frozen_at']<read(ROOT/'runs'/(directory.name+'--'+split)/'Run_clock.json')['start']
            assert facts['comparisons'][split]['instances']==len(p['data'][split])
        validation=Adapter().summary(ROOT/'runs'/(directory.name+'--validation'))
        best=sorted([r for r in validation['records'] if r['valid']],key=lambda r:(-r['fitness'],r['id']))[0]
        assert final['final']==best
    write(out/'Candidate_index.json',outputs)
    if outputs:
        with (out/'Candidate_index.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(outputs[0]));w.writeheader();w.writerows(outputs)
    result={'campaign':str(directory),'phase':s['phase'],'protocol_sha256':sha(directory/'Protocol.json'),'git_commit':p['git_commit'],
        'budgets':facts['used'],'dataset_unique_sets':60,'all_stage_sources_matched':True,'all_stage_NN_vectors_match':True,
        'H_quality_selection_reproduced':(directory/'H_frozen.json').exists(),'all_candidate_tours_checked_independently':raw_lengths,
        'physical_program_instances_reserved':physical,'captured_solve_passes':passes,'valid_unique_evaluations':valid_unique,
        'recorded_solve_recheck_seconds':solve_seconds,'candidate_exports':len(outputs),'currency_cost':facts['usage']['verified_currency_cost']}
    write(out/'Delivery_verification.json',result)
    write(out/'Summary.json',facts)
    # Archive original runs and exact source, keeping paths and raw responses intact.
    files=sorted({x for folder in list(dict.fromkeys([directory,origin,*stage_paths])) for x in folder.rglob('*') if x.is_file()})
    files+=sorted(ROOT/name for name in p['source_files'])
    archive=out/'Raw_evidence.tar.gz'
    manifest={str(x.relative_to(ROOT)):{'sha256':sha(x),'bytes':x.stat().st_size} for x in files}
    with tarfile.open(archive,'w:gz') as t:
        for x in files:t.add(x,arcname=str(x.relative_to(ROOT)),recursive=False)
    with tarfile.open(archive,'r:gz') as t:
        for member in t:
            import hashlib
            assert hashlib.sha256(t.extractfile(member).read()).hexdigest()==manifest[member.name]['sha256']
    write(out/'Raw_manifest.json',{'archive':archive.name,'archive_sha256':sha(archive),'roundtrip_verified':True,'files':manifest})
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    audit(Path(a.directory).resolve(),Path(a.out).resolve())
