#!/usr/bin/env python3
"""Changed-path offline checks; synthetic receipts only, no H/solver or network."""
import copy
import json
import socket
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from heuristic_design.core import execution
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport
from heuristic_design.problems import routing_fixtures
from experiments.triad import runtime,evaluation,problems,configuration,six_ops,slurm


def deny(*a,**kw):raise AssertionError('OFFLINE: real network/client/solver/submission prohibited')


def main():
    stamp=str(time.time_ns());out=ROOT/'reports/six-groups-20261116'/('offline-'+stamp);out.mkdir(parents=True)
    fixtures=out/'fixtures';fixtures.mkdir();results={};run_root=ROOT/'runs'/('OFFLINE-six-'+stamp);run_root.mkdir(parents=True)
    m=read(ROOT/'preparations/triad/tsp/train20.manifest.json')
    write(fixtures/'tsp-reference.json',{'kind':'mock-reference-v1','engineering_only':True,'instances':[{'file':r['file'],'reference':1.0} for r in m['instances']]})
    write(fixtures/'obp.json',{'N':3,'capacity':10,'items':[2,3,5]})
    write(fixtures/'obp-manifest.json',{'problem':'obp','split':'train','instances':[{'file':'synthetic-only','path':'obp.json','sha256':sha(fixtures/'obp.json')}]})
    with patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny),patch.object(StrictNonstreamTransport,'__init__',deny),patch.object(routing_fixtures,'solve',deny),patch.object(problems,'solve_row',deny),patch.object(problems,'solve_obp',deny),patch.object(evaluation,'evaluate',deny):
        for group in configuration.GROUPS:
            base=six_ops.config(group);c=copy.deepcopy(base)
            c.update(mode='mock',freeze_status='engineering_only',population_size=2,initialization_request_cap=4,evolution_request_cap=2,api_attempt_cap=6,evaluation_concurrency=1,window_seconds=3600,account_exclusion=None,credential_file=None,account_gate=None,
                     initialization_policy='native_EoH' if c['method']=='eoh' else 'bounded_initialization_until_population',budget_basis='SYNTHETIC OFFLINE ONLY',mock_faults={},pause_after_tasks=None)
            c['resources'].update(cpus=2,memory_mib=512,segment_seconds=1800,drain_seconds=1000)
            if c['problem']=='tsp':c['reference_file']=str(fixtures/'tsp-reference.json')
            if c['problem']=='obp':
                c.update(data_manifest=str(fixtures/'obp-manifest.json'),instance_count=1)
                if c['method']=='u':
                    from dataclasses import asdict
                    from experiments.triad import obp_h
                    hs=[asdict(obp_h.validate('def priority(item_size, remaining_capacities):\n    return '+v+'\n','HANDWRITTEN MOCK')) for v in ('remaining_capacities','[-c for c in remaining_capacities]')]
                    hp=fixtures/'obp-H.json';write(hp,{'members':hs,'engineering_only':True});c['h_file']=str(hp)
            identities=[];traces=[]
            for seed in (501,502,503):
                cp=fixtures/(group+'-'+str(seed)+'.json');v={**c,'search_seed':seed};write(cp,v)
                d=run_root/(group+'-'+str(seed));runtime.prepare(d,cp,engineering=True)
                before=read(d/'checkpoint.json');assert before['population']==[] and before['eoh']['population']==[] and before['tasks']=={}
                result=execution.start(d,adapter=runtime.Adapter());assert result['phase']=='completed',(group,result)
                runtime.export(d);p,s=runtime.protocol_state(d);summary=runtime.Adapter().summary(d)
                assert summary['initialization_attempts']==2 and summary['evolution_attempts']==2 and summary['request_reservations']==4
                assert summary['automatic_retries']==0 and summary['confirmed_sends']==0
                identities.append(s['identity']);traces.append(s)
                row={'group':group,'seed':seed,'run_id':d.name,'run_dir':str(d),'config':str(cp),'child_config_sha256':sha(cp),'request_cap':6}
                # Only command rendering gets a complete synthetic declaration;
                # production Slurm renderer intentionally rejects tiny Mock profiles.
                rendered={**v,'mode':'real','freeze_status':'frozen','budget_basis':'SYNTHETIC COMMAND ONLY','account_gate':'SYNTHETIC','credential_file':'SYNTHETIC',
                    'account_exclusion':{'scope':'SYNTHETIC'},'h_file':v.get('h_file') or 'SYNTHETIC' if v['method']=='u' else None}
                with patch.object(slurm.configuration,'load',return_value=rendered):
                    cmd=slurm.command(row,'run','/public2/home/qiuqian/hdl-envs/portable-v2/bin/python')
                assert '--no-requeue' in cmd and '--cpus-per-task=2' in cmd
            assert len(set(identities))==3
            cp=fixtures/(group+'-pause.json');write(cp,{**c,'search_seed':501,'pause_after_tasks':3})
            d=run_root/(group+'-pause');runtime.prepare(d,cp,engineering=True);result=execution.start(d,adapter=runtime.Adapter());assert result['phase']=='paused'
            clock=sha(d/'Run_clock.json');result=execution.start(d,adapter=runtime.Adapter(),resume=True);assert result['phase']=='completed' and sha(d/'Run_clock.json')==clock
            _,s=runtime.protocol_state(d)
            semantic=lambda st:[{k:t.get(k) for k in ('semantic_id','operator','parent_keys','parents','candidate','J','failure','native_population_duplicate')} for t in st['tasks'].values()]
            assert semantic(s)==semantic(traces[0]) and s['u_rng']==traces[0]['u_rng'] and s['population']==traces[0]['population']
            results[group]={'three_fresh_initializations':True,'seed_directory_protocol_isolation':True,'budget4_not6_actual':True,'pause_resume_same_rng_trace_and_deadline':True,'Slurm_args_passed':True,'real_config_evolution_target':base['evolution_request_cap']}
        # Regress the adopted FJSP gate with10 native records and fewer finite parents.
        c=six_ops.config('fjsp-eoh');c.update(mode='mock',freeze_status='engineering_only',search_seed=503,population_size=10,initialization_request_cap=20,evolution_request_cap=2,api_attempt_cap=22,window_seconds=3600,credential_file=None,account_gate=None,account_exclusion=None,mock_faults={'8':'duplicate','9':'duplicate'})
        c['resources'].update(segment_seconds=1800,drain_seconds=1000)
        cp=fixtures/'native-gate.json';write(cp,c);d=run_root/'native-gate';runtime.prepare(d,cp,engineering=True);r=execution.start(d,adapter=runtime.Adapter());assert r['phase']=='completed',r
        _,s=runtime.protocol_state(d);assert s['eoh']['initialization_requests']==10 and s['eoh']['operator_cursor']==2
        results['FJSP_native_gate']={'init_requests':10,'evolution_attempts':2,'duplicate_or_tie_penalties_preserved':sum(bool(t.get('native_population_duplicate')) for t in s['tasks'].values()),'no_refill':True}
    need=six_ops.need
    try:six_ops.continue_batch('fjsp503',2040,False,True,True)
    except (PermissionError,FileNotFoundError):pass
    else:raise AssertionError('missing approval accepted')
    # Execution stays unapproved. R12 has pending TSP choices; R13 has adopted bindings.
    check=six_ops.check_only();assert len(check['runs'])==18 and not check['all_runs_ready']
    adopted=(ROOT/'preparations/operations/TSP-adoption.json').exists()
    assert all(('population_size' not in x['pending']) if adopted else ('population_size' in x['pending']) for x in check['runs'] if x['group'].startswith('tsp'))
    assert six_ops.config('obp-eoh')['initialization_policy']=='native_N_finite_or_fail'
    assert not __import__('subprocess').check_output(['git','diff','923781f','--','code/','experiments/common/run_frozen.py'],cwd=ROOT)
    value={'passed':True,'scope':'18 tiny synthetic runs +6 pause/resume +FJSP gate regression; existing admission/failure evidence reused','results':results,
        'public_923781f_unchanged':True,'credential_values_read':0,'API_requests':0,'actual_solves':0,'LKH_runs':0,'Slurm_submitted':False,'current_R11_modified':False,
        'reused_evidence':['R11 finite recovery622833/622834 user supplied passed certificate','Mock614258 and real evaluator614474 closed','R10 three process Mock only, no new pressure test']}
    write(out/'OFFLINE.json',value);write(ROOT/'reports/six-groups-20261116/latest-offline.json',{'evidence':str(out/'OFFLINE.json'),**value})
    print(json.dumps({'passed':True,'evidence':str(out/'OFFLINE.json'),'API_requests':0,'actual_solves':0,'Slurm_submitted':False},ensure_ascii=False))


if __name__=='__main__':main()
