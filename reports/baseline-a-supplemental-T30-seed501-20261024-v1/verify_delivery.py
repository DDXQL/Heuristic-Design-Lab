"""Offline delivery-integrity checks; no evaluator, heuristic or data imports."""
import csv
import hashlib
import json
from pathlib import Path
from statistics import fmean
import tarfile

OUT=Path(__file__).resolve().parent


def read(name):return json.loads((OUT/name).read_text())


def table(name):
    with (OUT/name).open() as f:return list(csv.DictReader(f))


def sha(data):return hashlib.sha256(data).hexdigest()


def main():
    p=read('Protocol.json');state=read('checkpoint.json');s=read('Summary.json');manifest=read('Source_manifest.json')
    h=sha((OUT/'Protocol.json').read_bytes())
    assert h==(OUT/'Protocol.sha256').read_text().strip()==state['protocol_sha256']==s['protocol_sha256']
    assert (p['evaluation_cap'],p['solve_pass_cap'],p['API_cap'])==(189,378,0)
    assert list(state['strategies'])==[x['id'] for x in p['strategies']] and len(state['strategies'])==9
    assert state['phase']=='completed'
    for entry in state['strategies'].values():assert (entry['reserved_evaluations'],entry['reserved_solve_passes'])==(21,42)
    for entry in manifest['new_results']:
        path=OUT/'certified_results'/(entry['strategy']+'.json');result=json.loads(path.read_text())
        assert sha(path.read_bytes())==entry['result_sha256']
        if result['valid']:
            assert len(result['instances'])==21 and result['fitness']==fmean(x['score'] for x in result['instances'])
        else:assert result['fitness'] is None
        for r,expected in zip(result['instances'],p['instances']):
            assert r['file']==expected['file'] and r['lower_bound']==expected['LB']
            assert r['score']==-r['makespan']/r['lower_bound']
            assert r['physical_schedule_sha256']==r['recheck_physical_schedule_sha256']
    with tarfile.open(OUT/'Raw_evidence.tar.gz','r:gz') as archive:
        found={}
        for member in archive.getmembers():
            assert member.isfile() and not member.name.startswith('/') and '..' not in Path(member.name).parts
            data=archive.extractfile(member).read()
            found[member.name]={'sha256':sha(data),'bytes':len(data)}
        assert found==manifest['raw_artifacts']
    instances=table('All_instances_189.csv');pairs=table('Composite_pairs_45.csv')
    assert len(instances)==189 and len(pairs)==45 and len(table('Composite_pair_instances_945.csv'))==945
    if (OUT/'Composite_static_instances_1155.csv').exists():assert len(table('Composite_static_instances_1155.csv'))==1155
    valid=[r for r in pairs if r['valid']=='True']
    assert len(valid)==s['composite_pair_valid'] and len({r['strategy'] for r in pairs})==45
    assert all(float(a['fitness'])>=float(b['fitness']) for a,b in zip(valid,valid[1:]))
    assert pairs[0]['strategy']==s['best_pair']['strategy']
    assert sum(r['source']=='Supplemental-T30' for r in pairs)==6
    comparisons=table('Old_new_comparison.csv');controls=[r for r in comparisons if r['control']=='True']
    assert len(controls)==63
    assert all(r['Cmax_equal']==r['score_equal']==r['commit_or_native_hash_equal']=='True' for r in controls)
    assert all(r['physical_hash_equal'] in ('','True') for r in comparisons)
    assert all(r['Cmax_equal']==r['score_equal']=='True' for r in comparisons)
    phases=table('Phases_189.csv')
    assert len(phases)<=189 and sum(r['first_started']=='True' for r in phases)+sum(r['recheck_started']=='True' for r in phases)<=378
    for r in phases:
        if r['parent_timely']=='True':assert float(r['parent_receive_end'])-float(r['parent_wait_start'])<=30
    processes=table('Lifecycle_9.csv');assert len(processes)==9
    assert all(r['alive']=='False' and r['reader_stopped']=='True' for r in processes)
    assert not any(read('Network_guard.json').values())
    print(json.dumps({'status':'PASS','protocol_sha256':h,'strategies':9,'instance_rows':len(instances),
        'composite_pairs':45,'control_rows':63,'raw_artifacts_verified':len(found),'new_solves':0,'API':0},ensure_ascii=False))


if __name__=='__main__':main()
