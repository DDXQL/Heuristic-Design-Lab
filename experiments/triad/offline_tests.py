#!/usr/bin/env python3
"""Small finite synthetic receipts for new six-group/batch wiring. No construction."""
from pathlib import Path
from dataclasses import asdict
import copy
import json
import os
import socket
import sys
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core import execution,evolution_v1
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport
from heuristic_design.problems import routing_fixtures
from experiments.triad import configuration,runtime,problems,evaluation,batch,slurm


def deny(*a,**k):raise AssertionError('OFFLINE: network, real API, LKH, real construction/evaluation prohibited')


def main():
    stamp=time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid());out=ROOT/'reports/triad-package-20261113'/('offline-'+stamp);out.mkdir(parents=True)
    data=out/'assets';data.mkdir();results={};configs={};dirs=[]
    for problem in ('fjsp','tsp','obp'):
        args=problems.h_args(problem,'obp-vector-feasible-h-v2' if problem=='obp' else None);hs=[asdict(problems.validate_h(problem,'def priority('+', '.join(args)+'):\n    return '+expr+'\n','HANDWRITTEN MOCK ONLY')) for expr in (('[-cap for cap in remaining_capacities]','[cap for cap in remaining_capacities]') if problem=='obp' else ('-'+args[0],args[1]))]
        write(data/(problem+'-H.json'),{'members':hs,'engineering_only':True})
    # Mock references are explicitly NOT LKH results.
    m=read(ROOT/'preparations/triad/tsp/train20.manifest.json');write(data/'tsp-mock-refs.json',{'kind':'mock-reference-v1','engineering_only':True,'instances':[{'file':r['file'],'reference':1.0} for r in m['instances']]})
    write(data/'obp-instance.json',{'N':3,'capacity':10,'items':[2,3,5]});write(data/'obp.manifest.json',{'problem':'obp','split':'train','instances':[{'file':'synthetic-arrivals','path':'obp-instance.json','sha256':sha(data/'obp-instance.json')}]})
    for group in configuration.GROUPS:
        c=read(ROOT/'experiments/triad/configs'/(group+'.json'));problem=c['problem']
        c.update(mode='mock',freeze_status='engineering_only',repeat_count=2,search_seeds=[7,8],search_seed=7,population_size=2,initialization_request_cap=4,evolution_request_cap=4,api_attempt_cap=8,
          initialization_policy='native_EoH' if c['method']=='eoh' else 'bounded_initialization_until_population',solve_seed=501,evaluation_concurrency=1,
          window_seconds=3600,budget_basis='SYNTHETIC_ENGINEERING_ONLY',protocol_receipt='MOCK_NOT_RESEARCH_APPROVAL',data_usage_receipt='SYNTHETIC_NO_HOLDOUT',
          h_file=str(data/(problem+'-H.json')) if c['method']=='u' else None,
          data_manifest=str(ROOT/'preparations/eoh-gap/train21.manifest.json') if problem=='fjsp' else str(ROOT/'preparations/triad/tsp/train20.manifest.json') if problem=='tsp' else str(data/'obp.manifest.json'),
          reference_file=str(data/'tsp-mock-refs.json') if problem=='tsp' else None,instance_count=21 if problem=='fjsp' else 20 if problem=='tsp' else 1,
          resources=dict(cpus=2,memory_mib=512,segment_seconds=1800,drain_seconds=1000,numeric_threads=1,partition='OFFLINE',account=None,qos=None))
        if problem=='obp':
            file=ROOT/'experiments/triad/obp_state_preset.py';c.update(obp_actions='preallocated_empty_bins',obp_h_abi='obp-vector-feasible-h-v2',obp_bound={'version':'obp-R-code-int64-float64-v1','rule':'int(float64(sum_int64(items))/float64(C)+0.5)'},state_delivery={'file':str(file),'sha256':sha(file),'module':'experiments.triad.obp_state_preset','action_policy':'preallocated_empty_bins','engineering_only':True})
        path=out/(group+'.json');write(path,c);configs[group]=path
    def run(group,label,**changes):
        c=read(configs[group]);c.update(changes);path=out/(group+'-'+label+'.json');write(path,c);d=ROOT/'runs'/('triad-OFFLINE-'+stamp+'-'+group+'-'+label);dirs.append(str(d))
        runtime.prepare(d,path,engineering=True);a=runtime.Adapter();value=execution.start(d,adapter=a);runtime.export(d);return d,value
    with patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny),patch.object(StrictNonstreamTransport,'__init__',deny),patch.object(routing_fixtures,'solve',deny),patch.object(problems,'solve_row',deny),patch.object(problems,'solve_obp',deny),patch.object(evaluation,'evaluate',deny):
        for group in configuration.GROUPS:
            d,value=run(group,'normal');assert value['phase']=='completed',(group,value,read(d/'Stop.json') if (d/'Stop.json').exists() else None)
            p,s=runtime.protocol_state(d);summary=runtime.Adapter().summary(d)
            assert summary['evolution_attempts']==4 and summary['initialization_attempts']==2 and summary['request_reservations']==6
            assert summary['confirmed_sends']==0 and summary['automatic_retries']==0
            paused,value=run(group,'pause',pause_after_tasks=3);assert value['phase']=='paused'
            clock=read(paused/'Run_clock.json');value=execution.start(paused,adapter=runtime.Adapter(),resume=True);runtime.export(paused)
            assert value['phase']=='completed' and read(paused/'Run_clock.json')==clock
            _,ss=runtime.protocol_state(paused)
            def semantics(st):return [{k:t.get(k) for k in ('semantic_id','operator','parents','parent_keys','candidate','J','failure','AST_duplicate','native_population_duplicate')} for t in st['tasks'].values()]
            assert semantics(s)==semantics(ss) and s['population']==ss['population'] and s['u_rng']==ss['u_rng']
            second,value=run(group,'seed8',search_seed=8);assert value['phase']=='completed'
            assert (d/'Protocol.sha256').read_text()!=(second/'Protocol.sha256').read_text()
            results[group]=dict(passed=True,summary=summary,source=dirs[-3:])
        d,value=run('obp-eoh','faults',mock_faults={'2':'failure','3':'invalid','4':'duplicate','5':'invalid_evaluation'})
        assert value['phase']=='completed';summary=runtime.Adapter().summary(d);assert summary['failures']>=3 and summary['duplicates']>=1 and summary['request_reservations']==6
        failed,value=run('tsp-eoh','transport-streak',mock_faults={'2':'failure','3':'failure','4':'failure'})
        assert value['phase']=='paused' and value['cursor']==5
        strict,value=run('obp-eoh','strict-N',initialization_policy='native_N_finite_or_fail',mock_faults={'1':'duplicate'})
        assert value['phase']=='initialization_incomplete' and value['cursor']==2
        # Unknown reservations are never replayed; keep the evidence lock.
        unknown=ROOT/'runs'/('triad-OFFLINE-'+stamp+'-unknown');runtime.prepare(unknown,configs['obp-eoh'],engineering=True);dirs.append(str(unknown));(unknown/'.execution.lock').write_text('{"state":"unknown"}')
        try:execution.start(unknown,adapter=runtime.Adapter())
        except ValueError:pass
        else:raise AssertionError('unknown lock ignored')
        assert (unknown/'.execution.lock').exists()
        # Stable semantic settlement despite reverse completion; no model/solver.
        tasks=[{'id':str(i)} for i in range(4)]
        def delayed(t):time.sleep((3-int(t['id']))*.01);return int(t['id'])
        reversed_results=evolution_v1._batch(delayed,tasks,2)
        assert [reversed_results[t['id']]['value'] for t in tasks]==[0,1,2,3]
        # Both OBP vector and scalar interfaces are explicit engineering options;
        # no state definition or real action-domain decision is changed here.
        from experiments.triad import obp_h
        vector=obp_h.validate('def priority(item_size, remaining_capacities):\n    return [-cap for cap in remaining_capacities]\n','MOCK vector H')
        obp_h.compile_candidate(vector) # compilation only; never call H / construct
        vc=read(configs['obp-eoh']);vc['obp_h_abi']='obp-vector-feasible-h-v2'
        vd,vv=run('obp-eoh','vector-ABI',obp_h_abi='obp-vector-feasible-h-v2');assert vv['phase']=='completed'
        problems.validate_obp_solution({'capacity':10,'items':[2,3,5]},{'placements':[2,0,2],'used':[3,0,7],'bin_count':2},'preallocated_empty_bins')
        # Exact arithmetic / pure legality validators, without constructing a solution.
        assert problems.obp_lower_bound({'capacity':10,'items':[2,3,5]},'volume_ceiling')==1
        problems.validate_obp_solution({'capacity':10,'items':[2,3,5]},{'placements':[0,0,0],'used':[10],'bin_count':1},'fit_only_else_new')
        for code in ('def priority(item_size, remaining_capacity):\n    return mean_remaining_distance\n','def priority(item_size, remaining_capacity):\n    import os\n    return 0\n'):
            try:problems.validate_h('obp',code,'bad')
            except Exception:pass
            else:raise AssertionError('unsafe OBP H admitted')
        campaign={'version':'triad-serial-batch-v1','campaign_id':'MOCK-'+stamp,'repeat_count':2,'search_seeds':[7,8],'global_generation_tasks':1,'run_root':str(ROOT/'runs'/('batch-OFFLINE-'+stamp)),
          'groups':[{'group':g,'config':str(path)} for g,path in configs.items()]}
        cp=out/'campaign.json';write(cp,campaign);frozen=batch.materialize(cp,out/'batch',engineering=True);assert len(frozen['rows'])==12
        # Attach one complete, one failed and the remaining unstarted rows; retain ALL in summary.
        frozen['rows'][0]['run_dir']=results['fjsp-u']['source'][0];frozen['rows'][1]['run_dir']=str(unknown)
        view=batch.summarize(frozen);assert len(view['all_runs'])==12 and any(r['phase']=='not_started' for r in view['all_runs']) and any(r.get('writer_lock') for r in view['all_runs'])
        c=read(configs['obp-eoh']);row={'config':str(configs['obp-eoh']),'run_id':'MOCK-seed-7','child_config_sha256':sha(configs['obp-eoh']),'run_dir':str(ROOT/'runs/MOCK-seed-7')}
        with patch.object(configuration,'load',lambda p:c):cmd=slurm.command(row,'run',sys.executable)
        assert '--cpus-per-task=2' in cmd and '--no-requeue' in cmd and 'cluster.sbatch' in ' '.join(cmd)
        # A separate bounded H-construction stage and freeze, with no EoH-S claim.
        hc=read(configs['obp-eoh']);hc['h_build']={'request_cap':3,'target_count':2,'selection':'complete train J ascending / ID ascending','source_cost':None}
        hp=out/'H-build.json';write(hp,hc);hd=ROOT/'runs'/('triad-OFFLINE-'+stamp+'-Hbuild');dirs.append(str(hd))
        runtime.prepare(hd,hp,engineering=True,run_kind='h-build');hv=execution.start(hd,adapter=runtime.Adapter());assert hv['phase']=='completed'
        from experiments.triad import assets,entry
        frozen_h=out/'H-fixture-frozen.json';receipt=assets.freeze_h(hd,frozen_h);assert receipt['H_count']==2 and read(frozen_h)['engineering_only']
        # Actual CLI dispatch in this guarded interpreter, no subprocess/network.
        import io
        from contextlib import redirect_stdout
        cli=ROOT/'runs'/('triad-OFFLINE-'+stamp+'-CLI');dirs.append(str(cli))
        with patch.object(sys,'argv',['entry','run','--config',str(configs['obp-eoh']),'--run-dir',str(cli),'--engineering']),redirect_stdout(io.StringIO()):assert entry.main()==0
        # Synthetic sbatch accepted-but-unreadable receipt: second attempt cannot resend.
        ud=ROOT/'runs'/('triad-OFFLINE-'+stamp+'-unknown-submit');runtime.prepare(ud,configs['obp-eoh'],engineering=True);dirs.append(str(ud))
        ur={'group':'obp-eoh','seed':7,'run_id':ud.name,'config':str(configs['obp-eoh']),'child_config_sha256':sha(configs['obp-eoh']),'run_dir':str(ud)}
        ub=out/'unknown-submission-batch';write(ub/'Batch.json',{'rows':[ur]})
        calls=[]
        def fake_sbatch(cmd,**kw):
            assert cmd[0]=='sbatch';calls.append(cmd)
            return __import__('subprocess').CompletedProcess(cmd,0,stdout='MOCK_UNREADABLE_JOB_RECEIPT',stderr='')
        argv=['slurm','run','--batch',str(ub),'--experiment','obp-eoh','--seed','7','--submit','--allow-api','--allow-solves','--approve-budget','8']
        with patch.object(configuration,'load',lambda p,**kw:hc),patch.object(slurm.subprocess,'run',fake_sbatch),patch.object(sys,'argv',argv):
            for _ in range(2):
                try:slurm.main()
                except ValueError:pass
                else:raise AssertionError('unknown submit did not stop')
        assert len(calls)==1 and batch.state(ur)['phase']=='unknown_submission'
        # All real group configs still reject, independently, without stopping the plan.
        live=batch.plan(ROOT/'experiments/triad/campaign.pending.json');assert len(live['rows'])==6 and all(r['pending'] for r in live['rows']) and live['all_declared_request_cap'] is None
    result=dict(passed=True,kind='SYNTHETIC_RECEIPTS_ONLY',API_requests=0,actual_solves=0,LKH_runs=0,credential_reads=0,
      groups=results,checks=['six interfaces and J-min','independent seeds','no borrowed initialization','separate init/evolution caps','failure/duplicate accounting','safe pause/resume original deadline','unknown lock no replay','reverse-return stable settlement','full failure/unstarted summary','Slurm command generation','OBP scalar/vector closed H and action-domain pure legality','bounded H-build and freeze','guarded CLI run','unknown submission no resend','pending research refusal'],evidence_directories=dirs)
    write(out/'result.json',result);write(ROOT/'reports/triad-package-20261113/latest-offline.json',result)
    print(json.dumps({'passed':True,'evidence':str(out/'result.json'),'API_requests':0,'actual_solves':0,'LKH_runs':0},indent=2))


if __name__=='__main__':main()
