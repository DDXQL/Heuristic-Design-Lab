#!/usr/bin/env python3
"""Manual partial states/history arithmetic only; no H, U or full solve."""
import copy
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core import state_a_v3 as public
from heuristic_design.core.storage import write,sha
from experiments.triad import obp_state_preset as adapter


def main():
    h=public.History(5,2);p,a=adapter.extract(3,[0]*5,10,h)
    assert a==(0,1,2,3,4) and p['legal_action_count']==5 and p['action_delta_mean']==1 and p['action_delta_std']==0
    assert p['resource_commitment_mean'] is None and not p['availability']['resource_commitment_mean']
    assert p['recent_delta_mean'] is None and p['h_usage_count']==(0,0) and all(p['availability']['h_usage_count'])
    h.commit(0,1);h.commit(0,1);before=copy.deepcopy(h.__dict__)
    p,a=adapter.extract(3,[8,4,0,0,0],10,h)
    assert a==(1,2,3,4) and p['legal_action_count']==4
    assert math.isclose(p['action_delta_mean'],.75) and math.isclose(p['action_delta_std'],math.sqrt(3)/4)
    assert math.isclose(p['resource_commitment_mean'],.6) and math.isclose(p['resource_commitment_std'],.2)
    assert p['construction_progress']==.4 and h.__dict__==before # observation never commits
    h.commit(1,1);p,a=adapter.extract(1,[8,4,3,0,0],10,h)
    assert p['h_usage_count']==(2,1) and p['h_recent_usage_count']==(2,1)
    assert p['h_last_use_gap_fraction']==(.2,0) and p['h_recent_delta_mean']==(1,1)
    assert p['recent_delta_mean']==1 and p['recent_delta_std']==0
    # Full opened bins are included in resource statistics, but excluded from actions.
    f=public.History(3,1);f.commit(0,1);p,a=adapter.extract(1,[10,0,0],10,f)
    assert a==(1,2) and p['resource_commitment_mean']==1 and p['resource_commitment_std']==0
    # Actual zero history increments stay available; no per-H/global zero padding.
    z=public.History(15,2)
    for i in range(12):z.commit(i%2,1 if i<2 else 0)
    p,a=adapter.extract(1,[8,4]+[0]*13,10,z)
    assert p['recent_delta_mean']==0 and p['availability']['recent_delta_mean'] and p['h_recent_usage_count']==(5,5) and p['h_recent_delta_mean']==(0,0)
    rejected=0
    for loads,cap in (([0,0],10),([8,4,0,0,-1],10),([8,4,0,0,0],0)):
        try:adapter.extract(3,loads,cap,h)
        except ValueError:rejected+=1
        else:raise AssertionError('malformed state accepted')
    done=public.History(1,1);done.commit(0,1)
    try:adapter.extract(1,[1],10,done)
    except ValueError:rejected+=1
    else:raise AssertionError('terminal observation accepted')
    result={'passed':True,'adapter_id':adapter.ADAPTER_ID,'action_policy':adapter.ACTION_POLICY,'adapter_file_sha256':sha(Path(adapter.__file__)),
      'public_schema':'common-state-a-v3-obp','public_spec_sha256':public.SPEC_SHA256,'public_modules_modified':False,
      'scope':'manual partial state and synthetic successful-history commits only; no H/U execution or full construction',
      'checks':['first N actions and missing opened resource','k+m and m/(k+m), sqrt(k*m)/(k+m)','opened-only resource including full bins','per-H/global history/window/zero availability','no mutation by observe','invalid/terminal state rejection'],
      'rejected_cases':rejected,'API_requests':0,'actual_solves':0,'H_executions':0,'U_executions':0,'research_adopted':False}
    write(ROOT/'reports/triad-package-20261113/OBP_PRESET_STATE_ACCEPTANCE.json',result)
    print(__import__('json').dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
