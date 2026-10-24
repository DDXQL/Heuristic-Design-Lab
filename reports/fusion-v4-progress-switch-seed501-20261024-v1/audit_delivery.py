"""Post-evaluation read-only audit of accepted records and derived tables."""
import csv
import gzip
from statistics import fmean
from tools import fusion_v4_experiment as b
from fjsp_usage.research.events import atomic_json

p=b.check(b.DEFAULT);out=b.REPORT;s=b.v2.read(out/'Summary.json')
state=b.v2.read(b.DEFAULT/'checkpoint.json');assert state['phase']=='completed'
expected=b.v2.read(b.DEFAULT/'Expected_loaded_identity.json')['identity']
for record in state['strategies'].values():
    assert record['valid'] and record['status']=='completed'
    result=b.v2.read(b.DEFAULT/record['result_path'])
    assert len(result['instances'])==21
    assert result['fitness']==fmean(-r['makespan']/r['lower_bound'] for r in result['instances'])
    folder=(b.DEFAULT/record['result_path']).parent
    life=b.v2.read(folder/'lifecycle.json')
    assert life['exitcode']==0 and life['alive'] is False and life['trigger'] is None
    assert life['cleanup']==['join_exit_grace_2.0'] and life['rows_received']==21
    assert b.v2.read(folder/'before.json')['identity']==b.v2.read(folder/'after.json')['identity']==expected

with (out/'All_instances_126.csv').open() as f:rows=list(csv.DictReader(f))
assert len(rows)==126 and all(r['valid_complete_candidate']=='True' for r in rows)
with (out/'Switch_instances.csv').open() as f:switches=list(csv.DictReader(f))
assert len(switches)==126
assert all(int(r['WS_steps'])>0 and int(r['BORDA_steps'])>0 and int(r['operator_switches'])==1
           and r['initial_policy_prefix_verified']=='True' for r in switches)
with gzip.open(out/'State_decisions.csv.gz','rt') as f:
    decisions=list(csv.DictReader(f))
assert len(decisions)==22800
assert sum(int(r['WS_steps']) for r in switches)==11400
assert sum(int(r['BORDA_steps']) for r in switches)==11400
assert s['valid_dynamic_strategies']==6 and s['dynamic_strategies_better_than_WS']==0
assert s['costs']['completed_pairs']==126 and s['costs']['first_solves_started']==s['costs']['rechecks_started']==126
assert s['costs']['API_requests']==0 and s['costs']['additional_diagnostic_solves']==0
contrib=list(csv.DictReader((out/'Best_contributions.csv').open()))
positive=sum(float(r['contribution_to_full_delta_F']) for r in contrib if float(r['delta_F_instance'])>0)
negative=sum(float(r['contribution_to_full_delta_F']) for r in contrib if float(r['delta_F_instance'])<0)
assert abs(positive+negative-s['best_dynamic']['delta_F_vs_WS'])<1e-14
audit={'passed':True,'complete_strategies':6,'complete_evaluations':126,'solve_passes':252,
       'same_state_decisions_verified':len(decisions),'actual_switches':126,
       'WS_steps':11400,'BORDA_steps':11400,
       'changed_vs_WS_on_dynamic_states':sum(r['changed_from_WS']=='True' for r in decisions),
       'different_physical_vs_WS':sum(r['same_physical_WS']=='False' for r in switches),
       'boundary_action_changed_instances':sum(r['boundary_changes_action']=='True' for r in switches),
       'best_positive_contribution':positive,'best_negative_contribution':negative,
       'protocol_sha256':b.v2.sha(b.DEFAULT/'Protocol.json'),
       'protected_old_records_rechecked':True,'source_identity_and_normal_exit0_all_verified':True,
       'claim_scope':'full train21 descriptive; no generalization/LLM-search efficacy claim'}
atomic_json(out/'Final_audit.json',audit);print(audit)
