#!/usr/bin/env python3
"""One-arrival recording callbacks and reference arithmetic. No H/instance solve."""
import ast
from dataclasses import asdict
import copy
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import write,sha,digest
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport
from experiments.triad import problems,obp_h,evaluation,runtime,assets


def deny(*a,**k):raise AssertionError('OBP interface check prohibits real H execution, full construction, evaluation and network')


def main():
    with patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny),patch.object(StrictNonstreamTransport,'__init__',deny),patch.object(problems,'solve_obp',deny),patch.object(problems,'solve_row',deny),patch.object(evaluation,'evaluate',deny),patch.object(obp_h,'compile_candidate',deny):
        item=3;capacity=10;used=[8,4,0,0,0];actions=(1,2,3,4);seen=[]
        def recording_callback(current,capacities):
            seen.append({'item':current,'capacities':list(capacities),'type':type(capacities).__name__})
            assert isinstance(capacities,tuple)
            try:capacities[0]=999
            except TypeError:pass
            else:raise AssertionError('input mutable')
            mean=sum(capacities)/len(capacities)
            return tuple(-(cap-mean)**2 for cap in capacities)
        choice=problems.obp_choose_action(item,used,capacity,actions,recording_callback,obp_h.ABI,'preallocated_empty_bins')
        assert seen==[{'item':3,'capacities':[6,10,10,10],'type':'tuple'}]
        assert choice['local_index']==1 and choice['bin_index']==2 and choice['H_calls']==1 and used==[8,4,0,0,0]
        wrong_input=(2,6,10,10,10);wrong_mean=sum(wrong_input)/len(wrong_input);wrong_scores=[-(cap-wrong_mean)**2 for cap in wrong_input]
        wrong_bin=max(actions,key=lambda b:wrong_scores[b]);assert wrong_bin==1
        ties=problems.obp_choose_action(item,used,capacity,actions,lambda *_:(0,0,0,0),obp_h.ABI,'preallocated_empty_bins');assert ties['bin_index']==1
        opens=problems.obp_choose_action(item,used,capacity,actions,lambda *_:(0,7,7,7),obp_h.ABI,'preallocated_empty_bins');assert opens['bin_index']==2
        rejected=[]
        for label,callback in [('global_length',lambda *_:(0,0,0,0,0)),('short',lambda *_:(0,0)),('nonfinite',lambda *_:(0,float('inf'),0,0)),('boolean',lambda *_:(False,0,0,0))]:
            try:problems.obp_choose_action(item,used,capacity,actions,callback,obp_h.ABI,'preallocated_empty_bins')
            except ValueError:rejected.append(label)
            else:raise AssertionError(label+' admitted')
        for invalid in ((0,1,2,3,4),(4,3,2,1),(1,2)):
            try:problems.obp_choose_action(item,used,capacity,invalid,deny,obp_h.ABI,'preallocated_empty_bins')
            except ValueError:pass
            else:raise AssertionError('wrong feasible set/order admitted')
        ceil={'version':'obp-volume-ceiling-v1','rule':'ceil(S/C)'};code={'version':'obp-R-code-int64-float64-v1','rule':'int(float64(sum_int64(items))/float64(C)+0.5)'}
        refs=[]
        for items in ([5],[10,1],[10,4],[10,5],[10,10]):
            value={'capacity':10,'items':list(items)};a=problems.obp_lower_bound(value,ceil);b=problems.obp_lower_bound(value,code);refs.append({'items':list(items),'ceiling':a,'R_code':b})
        detail=problems.obp_reference_details({'capacity':10,'items':[10,1]},code)
        assert detail['S']==11 and detail['sum_dtype']=='int64' and detail['calculation_dtype']=='float64'
        for invalid in ({'capacity':10,'items':[1.0]},{'capacity':10,'items':[1],'N':2},{'capacity':2**63-1,'items':[2**63-1,1]}):
            try:problems.obp_reference_details(invalid,code)
            except ValueError:pass
            else:raise AssertionError('invalid dtype/N/overflow accepted')
        assert refs[1]['ceiling']==2 and refs[1]['R_code']==1
        assert problems.obp_lower_bound({'capacity':10,'items':[10,5]},code)==2 # exact half-up, not Python banker rounding
        try:problems.obp_lower_bound({'capacity':10,'items':[4]},code)
        except ValueError as x:assert 'zero' in str(x)
        else:raise AssertionError('zero reference silently repaired')
        c={'problem':'obp','obp_actions':'preallocated_empty_bins','obp_h_abi':obp_h.ABI,'obp_bound':code,'state_delivery':{'sha256':'D08_PENDING'},'solve_seed':501,'instance_timeout_seconds':30}
        contract=problems.obp_contract(c);fingerprint=digest(contract)
        for key,value in [('obp_actions','fit_and_one_virtual_new'),('obp_bound',ceil)]:
            changed={**c,key:value};assert digest(problems.obp_contract(changed))!=fingerprint
        candidate=obp_h.validate('def priority(item_size, remaining_capacities):\n    mean = sum(remaining_capacities) / len(remaining_capacities)\n    return [-(cap-mean)**2 for cap in remaining_capacities]\n','INTERFACE FIXTURE ONLY')
        tree=ast.parse(candidate.code)
        old_key=digest({'ABI':'obp-vector-h-v1','AST':ast.dump(tree,include_attributes=False)})
        assert candidate.key!=old_key
        # Construct prompts only, never run model or generated H.
        prompt=runtime.obp_u_prompt(c,{'operator':'INIT'},[],[asdict(candidate)])
        assert 'ALL feasible' in prompt and 'preallocated_empty_bins' in prompt and 'Only if none fits' not in prompt
        adapter=runtime.Adapter();adapter.p={'run_kind':'eoh'}
        hprompt=adapter.build_prompt(c,{'operator':'I1'},[],[])
        assert 'ALL feasible' in hprompt and code['version'] in hprompt and code['rule'] in hprompt
        from experiments.triad import h_selection
        records=[{'id':name,'candidate':{'key':name}} for name in ('A','B','C','D')]
        vectors={'A':[0,8],'B':[3,3],'C':[2.5,2.5],'D':[8,0]}
        selected,trace=h_selection.select(records,vectors,4,'greedy-envelope-J-v1')
        assert [r['id'] for r in selected]==['C','A','D','B']
        individual,_=h_selection.select(records,vectors,2,'individual-J-v1');assert [r['id'] for r in individual]==['C','B']
        assert trace[-1]['envelope_J']==trace[-2]['envelope_J']==0 # still fills K at no improvement
        # All three methods share the solver and the ordered scoring boundary.
        tree=ast.parse(Path(problems.__file__).read_text());row=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='solve_row')
        assert len([n for n in ast.walk(row) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='solve_obp'])==1
        for name in ('solve_obp','obp_choose_action'):
            function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            assert len([n for n in ast.walk(function) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_score_obp_actions'])==1
        result={'passed':True,'kind':'MANUAL_SINGLE_ARRIVAL_CALLBACK_AND_ARITHMETIC_ONLY','contract_version':problems.OBP_CONTRACT_VERSION,
          'H_ABI':obp_h.ABI,'actual_input_record':seen,'correct_selection':choice,'old_all_bins_counterexample':{'input':list(wrong_input),'mean':wrong_mean,'selected_permanent_bin':wrong_bin},
          'tie_selected_bin':ties['bin_index'],'active_open_selected_bin':opens['bin_index'],'rejected_output_cases':rejected,
          'reference_options_are_distinct':refs,'R_code_actual_type_receipt':detail,'zero_reference_rejected_without_substitution':True,'protocol_reference_action_fingerprints_change':True,'old_H_ABI_key_rejected':True,
          'shared_U_EoH_fixed_H_path':True,'H_selection_greedy_envelope_and_no_improvement_fill_checked':True,'research_state_adopted':False,'state_adapter_separate_evidence':'OBP_PRESET_STATE_ACCEPTANCE.json',
          'API_requests':0,'actual_solves':0,'LKH_runs':0,'generated_H_executions':0,'full_training_constructions':0,'recording_callback_invocations':1}
        write(ROOT/'reports/triad-package-20261113/OBP_V2_INTERFACE_ACCEPTANCE.json',result)
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
