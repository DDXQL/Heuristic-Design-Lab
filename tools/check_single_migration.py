#!/usr/bin/env python3
"""Offline post-run provenance/result verification; no client or holdout loading."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
sys.path.insert(0,str(ROOT/'experiments/tier2/research_real_v1'))
from run_single_model_migration import MigrationWorkflow
from fjsp_usage.research_real.config import ExperimentConfig
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.research_real.single_experiments import Guard
from fjsp_usage.research.events import atomic_json


def check(p):
    c=ExperimentConfig.from_dict(json.loads((p/'config.migration.authorized.json').read_text()))
    ds=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
    flow=MigrationWorkflow(p,config=c,dataset=ds,project_root=ROOT)
    flow.assert_current();Guard(flow,flow.read('Worktree_binding.json','Worktree_binding')).check()
    H,members=flow.h_asset();initial=flow.read('r201/Shared_initial.json','Shared_initial')
    assert len(initial['population'])==5
    assert all(r['receipt']['model']=='gpt-6.1-sol' for r in initial['population'])
    a=json.loads((p/'Reconciled_training_results.json').read_text())
    valid=[r for r in a['requests'] if (r.get('attempt') or {}).get('category')=='valid']
    result=json.loads((p/'Single_results.json').read_text());by_id={r['id']:r for r in result['candidates']}
    for r in valid:
        e=by_id[r['id']]['evaluation']
        assert e['valid'] and e['total_instances']==21 and [x['file'] for x in e['instances']]==list(ds.names['train'])
        assert all(x['feasible'] and all(k in x for k in ('makespan','score','single_solve_seconds',
            'deterministic_recheck_seconds','deterministic_schedule_sha256')) for x in e['instances'])
    for arm in ('B0','B1','B2','P'):
        f=flow.read('r201/'+arm+'/Final_population.json','Final_population')
        assert len(f['population'])==5 and f['shared_initial_hash']==initial['artifact_sha256'] and f['H_hash']==H['artifact_sha256']
        assert json.loads((p/'r201'/arm/'checkpoint.json').read_text())['phase']=='completed'
    for name,sha in c.conditional_research['source_files_sha256'].items():
        assert hashlib.sha256((ROOT/'runs'/name).read_bytes()).hexdigest()==sha
    assert not any((p/name).exists() for name in ('Validation_selection.json','Experiment_frozen.json','Test_complete.json'))
    checks={'frozen_protocol_unchanged':True,'same_shared_initial_for_all_four':True,'all_final_populations_N5':True,
        'H_code_order_reviews_unchanged':True,'native_slots':len(flow.ledger.data['records']),
        'confirmed_sends':sum(r['send_confirmed'] for r in flow.ledger.data['records'].values()),
        'valid_candidates_full_train21':len(valid),'source_files_unchanged':len(c.conditional_research['source_files_sha256']),
        'validation_test_executed':False,'unknown_native_fee_keys':a['unknown_cost_requests']}
    atomic_json(p/'Final_integrity_checks.json',checks)
    print(json.dumps(checks,ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args();check(args.run_dir.resolve())


if __name__=='__main__':main()
