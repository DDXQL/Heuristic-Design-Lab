"""Run from snapshot with the original venv. Hash/provenance/imports only.

A real file + main guard is necessary for existing spawned H review samples.
No dataset.load, API dispatch, account lookup or FJSP solve is allowed here.
"""
import json
from pathlib import Path
from unittest.mock import patch

from tools import b1_ns_recovery as recovery


def main():
    run = recovery.ROOT.parent
    p = recovery.read(run/'Protocol.json')
    out = Path(__file__).resolve().parent
    previous = recovery.read(out.parent/'b1-ns-recovery-scope-check-20261022/Read_only_checks.json')
    with patch('socket.socket.connect',side_effect=AssertionError('NO NETWORK')), \
            patch('fjsp_usage.research_real.staged_evaluation.StagedDataset.load',side_effect=AssertionError('NO INSTANCE LOAD')), \
            patch('fjsp_usage.research_real.leafapi.load_local_key',side_effect=AssertionError('NO KEY READ')):
        recovery.check(run)
        config = recovery.ns.Config.from_dict(p['config'])
        dataset, H, members = recovery.ns.b1.b2.data_and_h(config,run)
        assert dataset.metadata == p['dataset'] and [m.key for m in members] == p['H_order']
        first,second = recovery.source_attestation(p),recovery.source_attestation(p)
        assert first['identity'] == second['identity']
        for stage in ('revalidate','continue'):
            try: recovery.require_execution(run,stage)
            except recovery.BudgetStop: pass
            else: raise AssertionError('unapproved execution passed')
        origin = Path(p['origin_directory'])
        assert all(recovery.sha(origin/name)==row['sha256'] and (origin/name).stat().st_mtime_ns==row['mtime_ns']
                   for name,row in previous['original_files_unchanged'].items())
        data = recovery.read(recovery.ROOT/'data/fjsp_manifest.json')
        assert {f.name for f in (recovery.ROOT/data['portable_root']).iterdir()} == set(p['train_names'])
        result = {'protocol_sha256':recovery.sha(run/'Protocol.json'),
            'snapshot_files':len(p['snapshot_files']), 'retained_original_pins':len(p['original_pins']),
            'wrapper_still_frozen':'tools/usage_mechanism_ablation.py' in p['original_pins'],
            'same_original_H_and_order':True,'provenance_and_existing_H_review_samples_checked':True,
            'instance_loading_blocked':True,'train21_hashes_match':True,
            'validation_test_instance_bodies_in_snapshot':False,
            'worker_source_before_after_pure_import':{'before':first,'after':second},
            'loaded_module_count':len(first['modules']),
            'loaded_function_and_method_count':sum(len(v['loaded_functions']) for v in first['modules'].values()),
            'original_47_files_SHA_and_mtime_unchanged':True,
            'new_real_API_attempts':0,'formal_evaluations':0,'live_authorizations':[],
            'both_execution_gates_refused_without_approval':True}
        (out/'Isolated_import_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print({k:v for k,v in result.items() if k!='worker_source_before_after_pure_import'})


if __name__ == '__main__':main()
