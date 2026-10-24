"""Verify design delivery only. No sampler, evaluator, H or raw data imports."""
import csv
import hashlib
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]


def read(path):return json.loads(path.read_text())


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest=read(OUT/'Source_manifest.json')
    assert manifest['new_solves']==manifest['new_API']==manifest['A4_samples']==0
    assert not any(manifest['guard'].values()) and manifest['unchanged_at_end']
    for row in manifest['inputs']:
        path=ROOT/row['path'];assert path.suffix!='.fjsp'
        assert sha(path)==row['sha256'],'historical source changed: '+row['path']
    assert sha(ROOT/'tools/a4_static_audit.py')==manifest['audit_script_sha256']
    tests=read(OUT/'Synthetic_acceptance.json');assert tests['passed'] and tests['tests_run']==10
    assert tests['formal_A4_plans_drawn']==tests['formal_train_solves']==tests['real_API_calls']==0
    for n,h in tests['files'].items():assert sha(ROOT/n)==h,'acceptance source changed: '+n
    assert read(OUT/'Authorization_TEMPLATE_NOT_APPROVED.json')['approved'] is False
    assert not (ROOT/'runs/a4-static-rs60x5-train21-seed501-v1').exists()
    with (OUT/'H01_grid_21.csv').open() as f:grid=list(csv.DictReader(f))
    assert len(grid)==21 and all(r['valid']=='True' and r['complete_instances']=='21' for r in grid)
    assert max(grid,key=lambda r:float(r['fitness']))['H0_weight']=='0.5'
    with (OUT/'H01_grid_instances_441.csv').open() as f:assert len(list(csv.DictReader(f)))==441
    a=read(OUT/'A1_A3_verified.json');assert (a['single_count'],a['pair_count'])==(10,45)
    assert len(read(OUT/'Verified_quality_cache_index.json')['entries'])==73
    old=ROOT/'reports/baseline-a-supplemental-T30-seed501-20261024-v1'
    old_manifest=read(old/'Report_files_manifest.json')
    assert sha(old/'NEXT_STATIC_SEARCH_PROTOCOL_ZH.md')==old_manifest['files']['NEXT_STATIC_SEARCH_PROTOCOL_ZH.md']['sha256']
    if (OUT/'Design_manifest.json').exists():
        for n,h in read(OUT/'Design_manifest.json')['files'].items():assert sha(ROOT/n)==h
    print(json.dumps({'status':'PASS','grid_points':21,'grid_rows':441,'A1_singles':10,'A2_pairs':45,
        'toy_tests':10,'formal_A4_plans':0,'new_real_solves':0,'new_API':0,'old_55_protocol_unchanged':True},ensure_ascii=False))


if __name__=='__main__':main()
