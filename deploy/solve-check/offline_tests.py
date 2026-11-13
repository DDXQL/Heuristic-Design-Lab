#!/usr/bin/env python3
"""Synthetic receipts only. Every actual construction/evaluator is disabled."""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

import accept as app


def tests(base,report):
    p=app.prepare(base)
    from heuristic_design.problems import routing_fixtures as fixtures
    from heuristic_design.problems.fjsp import routing as fjsp
    from heuristic_design.core import routing_evaluation
    outcomes={};calls=[]
    def fake(task,protocol):
        calls.append(task['id']);time.sleep(.02)
        rows=[]
        for row,reference in zip(protocol['instances'],protocol['references']):
            ref=reference['reference'];cost=ref+10
            rows.append({'file':row['file'],'raw_cost':cost,'reference':ref,'score':(cost-ref)/ref,
                         'semantic_sha256':'SYNTHETIC_'+task['U']+row['file'],'recheck_semantic_sha256':'SYNTHETIC_'+task['U']+row['file']})
        return {'valid':True,'mock':True,'instances':rows,'fixture_label':'SYNTHETIC_OFFLINE_RECEIPT'}
    def never(*args,**kwargs):raise AssertionError('NO REAL SOLVER IN OFFLINE CHECKS')
    with tempfile.TemporaryDirectory(prefix='hdl-solve16-offline-') as tmp, \
         patch.object(fixtures,'solve',side_effect=never), \
         patch.object(fjsp,'construct',side_effect=never), \
         patch.object(fjsp,'construct_state_a_v3',side_effect=never), \
         patch.object(routing_evaluation,'evaluate_task',side_effect=never):
        root=Path(tmp)
        result=app.coordinate(root/'complete',p,fake,synthetic=True)
        assert result['reserved_solves']==16 and result['physical_solves']['confirmed_started']==0
        assert len(calls)==4 and len(result['comparison'])==4
        outcomes['two_modes_two_U_two_instances_two_native_passes_cap_16']=True
        before=app.sha(root/'complete/checkpoint.json')
        try:app.coordinate(root/'complete',p,fake,synthetic=True);raise AssertionError('duplicate admitted')
        except ValueError:pass
        assert app.sha(root/'complete/checkpoint.json')==before
        outcomes['duplicate_identity_no_replay']=True
        count=len(calls);small=copy.deepcopy(p);small['max_physical_solves']=15
        try:app.coordinate(root/'small_cap',small,fake,synthetic=True);raise AssertionError('cap bypass')
        except ValueError:pass
        state=app.read(root/'small_cap/checkpoint.json')
        assert state['reserved_solves']==8 and len(calls)==count+2
        outcomes['parallel_wave_budget_checked_before_dispatch']=True
        failures=[]
        def failure(task,protocol):failures.append(task['id']);raise RuntimeError('synthetic infrastructure failure')
        try:app.coordinate(root/'failure',p,failure,synthetic=True);raise AssertionError('failure continued')
        except RuntimeError:pass
        state=app.read(root/'failure/checkpoint.json')
        assert len(failures)==1 and state['reserved_solves']==4 and (root/'failure/.solve-check.lock').exists()
        assert app.read(root/'failure/failure.json')['unknown_is_not_zero']
        outcomes['failure_stops_with_charged_unknown_reservation_and_retained_lock']=True
        # Exercise the pass meter with a fake native function, never a solver.
        import meter
        metered=root/'meter';metered.mkdir();(metered/'physical-solves').mkdir()
        app.save(metered/'Protocol.json',{**p,'test_label':'SYNTHETIC_OFFLINE_ONLY'})
        app.save(metered/'checkpoint.json',{'identity':app.sha(metered/'Protocol.json'),'reserved_solves':4,
                 'reservations':{'serial/constant_H0':{'status':'reserved'}}})
        meter_calls=[]
        def fake_native(*args,**kwargs):meter_calls.append(1);return {'raw_cost':1,'reference':1}
        os.environ['HDL_SOLVE_CHECK_MODE']='serial'
        with patch.object(fixtures,'solve',side_effect=fake_native):
            meter.install(metered)
            for instance in p['instances']:
                for _ in range(2):fixtures.solve('fjsp',instance,p['members'],p['U'][0]['candidate'])
            try:fixtures.solve('fjsp',p['instances'][0],p['members'],p['U'][0]['candidate']);raise AssertionError('extra solve admitted')
            except RuntimeError:pass
        os.environ.pop('HDL_SOLVE_CHECK_MODE',None)
        assert len(meter_calls)==4
        outcomes['meter_rejects_hidden_fifth_call_before_delegate']=True
    # Static source/identity checks, not construction or train evaluation.
    outcomes['selected_first_two_not_score_based']=[v['file'] for v in p['instances']]==['Behnke1.fjsp','Behnke2.fjsp']
    outcomes['fourteen_category_state_v3']=p['state_schema']=='common-state-a-v3-fjsp'
    outcomes['API_clients_absent']=not app.api_guard.check()['real_client_modules_loaded']
    assert all(outcomes.values())
    result={'label':'SYNTHETIC_OFFLINE_ONLY','passed':True,'actual_solves':0,'model_requests':0,
            'cases':outcomes,'selected_instances':[{'file':v['file'],'sha256':v['source_sha256']} for v in p['instances']],
            'LB':p['references'],'U':[{'id':v['id'],'key':v['candidate']['key']} for v in p['U']],
            'native_solves_per_instance':2,'declared_max_physical_solves':16}
    if report.exists():raise FileExistsError('preserve prior offline evidence')
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-root',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();tests(args.base_root,args.report)
