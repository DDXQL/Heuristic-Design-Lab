#!/usr/bin/env python3
"""Materialize adopted study inputs, not execution permission; no model/solver."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from experiments.triad import configuration,runtime
HERE=ROOT/'experiments/triad/adopted-20261115'
DEFAULT=ROOT/'configurations/triad-adopted-20261115'
GATE='/public2/home/qiuqian/hdl-account-gates/leafapi-gpt61sol-serial-v1'


def materialize(output=DEFAULT,reference=None,h_file=None,tsp_profile=False):
    output=Path(output).resolve()
    if output.exists():raise FileExistsError('new adopted-config revision required; no overwrite/rebind')
    rows=[]
    for group in configuration.GROUPS:
        source=ROOT/'experiments/triad/configs'/(group+'.json');c=configuration.load(source);problem=c['problem'];method=c['method']
        c.update(repeat_count=3,search_seeds=[501,502,503],search_seed=None,solve_seed=501,window_seconds=172800,account_gate=GATE,credential_file='/public2/home/qiuqian/.config/hdl/leafapi.key',account_exclusion=None,real_requests_authorized=False)
        c['resources'].update(cpus=3 if group=='fjsp-u' else 2,memory_mib=2048,segment_seconds=43200,drain_seconds=4000 if problem=='obp' else 1980 if group=='fjsp-u' else 1620,partition='128C_02',account='wz',qos='normal')
        c['freeze_status']='frozen';c['protocol_receipt']={'source':'explicit user decisions recorded2026-11-14/15','execution_authorized':False,'new_prompt_version':runtime.h_contract.VERSION}
        if problem in ('fjsp','obp'):
            c.update(population_size=5 if method=='u' else 10,initialization_request_cap=20,api_attempt_cap=1020,initialization_policy='bounded_initialization_until_population' if method=='u' else 'native_N_finite_or_fail',evaluation_concurrency=2 if group=='fjsp-u' else 1)
            c['budget_basis']='Adopted N5 U/N10 EoH,init<=20/evolution1000/cap1020; H build separate; no end-to-end equal-cost claim'
        if problem=='obp':
            state=ROOT/'experiments/triad/obp_state_preset.py'
            c.update(instance_count=96,data_manifest=str(ROOT/'preparations/triad/obp-official-20261115/train.manifest.json'),h_file=str(h_file) if method=='u' and h_file else None,obp_actions='preallocated_empty_bins',obp_h_abi='obp-vector-feasible-h-v2',obp_bound={'version':'obp-R-code-int64-float64-v1','rule':'int(float64(sum_int64(items))/float64(C)+0.5)'},state_delivery={'file':str(state),'sha256':sha(state),'module':'experiments.triad.obp_state_preset','action_policy':'preallocated_empty_bins','adoption':'adopted'},data_usage_receipt={'adopted':True,'train':'official instance0..95','validation':'official instance96..127','test':'30Weibull after frozen champions only; not opened here'})
            c['h_build']={'request_cap':40,'target_count':10,'selection':'greedy-envelope-J-v1','source_cost':{'budget':'independent cap40; shared once by3 U runs'},'search_seed':401,'window_seconds':172800}
        if problem=='tsp':
            c['reference_file']=str(reference) if reference else None;c['data_usage_receipt']={'adopted':True,'scope':'historical10H +train20; frozen D06 LKH reference; no NN fallback'}
            # Original pending values stay pending: the data/LKH adoption is not
            # evidence of adoption of additional search N/init/cap parameters.
            if c['population_size'] is None or c['api_attempt_cap'] is None:c['freeze_status']='pending'
            if tsp_profile:
                c.update(population_size=5 if method=='u' else 10,initialization_request_cap=20,api_attempt_cap=1020,initialization_policy='bounded_initialization_until_population' if method=='u' else 'native_N_finite_or_fail',evaluation_concurrency=1,freeze_status='frozen',budget_basis='operator explicitly adopted TSP U5/EoH10/init20/evolution1000/cap1020 via --adopt-tsp-search-profile')
        target=output/'configs'/(group+'.json')
        for k in ('data_manifest','h_file','reference_file','frozen_u_template','compatible_fixed_results'):
            if c.get(k):c[k]=os.path.relpath(Path(c[k]).resolve(),target.parent)
        if isinstance(c.get('state_delivery'),dict):c['state_delivery']['file']=os.path.relpath(c['state_delivery']['file'],target.parent)
        write(target,c);cc=configuration.load(target)
        for seed in (501,502,503):
            done=group=='fjsp-u' and seed in (501,502);name={'fjsp':'FJSP','tsp':'TSP','obp':'在线装箱'}[problem]+('双层方法' if method=='u' else '单规则EoH')+'：第'+str(seed-500)+'次独立搜索'
            rows.append({'中文名称':name,'group':group,'search_seed':seed,'solve_seed':c['solve_seed'],'config':str(target),'state':'completed_read_only' if done else 'not_started','job_id':'617156' if done and seed==502 else None,'existing_completed_run_id':'fjsp-u1000-20261112-mac-seed-501' if done and seed==501 else 'fjsp-u-repeat-20261115-fjsp-u-seed-502' if done else None,'data_manifest':cc['data_manifest'],'H_file':cc['h_file'],'reference_file':cc['reference_file'],'budget':configuration.budget(c),'run_id':'triad-v2-'+group+'-seed-'+str(seed) if not done else None,'planned_output':str(ROOT/'runs'/('triad-v2-'+group+'-seed-'+str(seed))) if not done else 'existing read-only receipt','pending':[] if done else configuration.gaps(cc)})
    pairs=[('first-eoh-501-502',[('fjsp-eoh',501),('fjsp-eoh',502)]),('fjsp-remaining503',[('fjsp-u',503),('fjsp-eoh',503)])]
    pairs += [(p+'-seed'+str(seed),[(p+'-u',seed),(p+'-eoh',seed)]) for p in ('tsp','obp') for seed in (501,502,503)]
    for name,items in pairs:
        batch_id=name+'-prompt-v2-20261115'
        spec={'batch_id':batch_id,'mode':'real','min_request_interval_seconds':1,'queue_wait_seconds':360,'account_gate':GATE,'members':[{'group':g,'seed':seed,'config':'../configs/'+g+'.json'} for g,seed in items]}
        write(output/'pairs'/(name+'.json'),spec)
        for row in rows:
            if (row['group'],row['search_seed']) in items:
                run_id=batch_id+'-'+row['group']+'-seed-'+str(row['search_seed']);row.update(pair=name,run_id=run_id,planned_output=str(ROOT/'runs'/batch_id/run_id),planned_child_config=str(ROOT/'plans'/name/'configs'/(run_id+'.json')))
    write(output/'RUNS18.json',{'runs':rows,'completed_read_only':2,'remaining':16,'API_requests':0,'actual_solves':0,'execution_authorized':False})
    write(output/'campaign.json',{'version':'triad-serial-batch-v1','campaign_id':'triad-v2-20261115','repeat_count':3,'search_seeds':[501,502,503],'global_generation_tasks':1,'run_root':str(ROOT/'runs/triad-v2-20261115'),'groups':[{'group':g,'config':'configs/'+g+'.json'} for g in configuration.GROUPS]})
    return {'directory':str(output),'runs':18,'completed_read_only':2,'remaining':16,'API_requests':0,'actual_solves':0}


def h_plan(hours,confirmed):
    if not confirmed or hours is None or not 48<=hours<=168:raise PermissionError('explicit other-generators-stopped account exclusion required for H401 original48h window')
    source=DEFAULT/'configs/obp-eoh.json';c=configuration.load(source);folder=ROOT/'plans/obp-H401';target=folder/'config.json'
    if folder.exists():raise FileExistsError('H401 already planned; preserve original config/budget')
    c['account_exclusion']={'scope':'all_devices_sharing_account','valid_until':time.time()+hours*3600,'confirmation':'operator confirms only this H construction may request this account'}
    for k in ('data_manifest','h_file','reference_file'):
        if c.get(k):c[k]=os.path.relpath(c[k],target.parent)
    c['state_delivery']['file']=os.path.relpath(c['state_delivery']['file'],target.parent)
    write(target,c)
    return {'config':str(target),'run_dir':str(ROOT/'runs/obp-H401'),'requests_max':40,'native_solves_max_including_recheck':40*96*2,'H_count_required':10,'automatic_retry':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['materialize','check-only','h-plan']);ap.add_argument('--output',type=Path,default=DEFAULT);ap.add_argument('--reference',type=Path);ap.add_argument('--h-file',type=Path);ap.add_argument('--exclusive-hours',type=float);ap.add_argument('--confirm-exclusive-account',action='store_true');ap.add_argument('--adopt-tsp-search-profile',action='store_true');a=ap.parse_args()
    if a.action=='materialize':value=materialize(a.output,a.reference,a.h_file,a.adopt_tsp_search_profile)
    elif a.action=='h-plan':value=h_plan(a.exclusive_hours,a.confirm_exclusive_account)
    else:
        runs=read(a.output/'RUNS18.json');value={'completed_read_only':2,'remaining':16,'groups':[],'API_requests':0,'actual_solves':0}
        for group in configuration.GROUPS:
            c=configuration.load(a.output/'configs'/(group+'.json'));value['groups'].append({'group':group,'pending':configuration.gaps(c),'data_exists':bool(c['data_manifest'] and Path(c['data_manifest']).exists()),'H_exists':bool(c['h_file'] and Path(c['h_file']).exists()),'reference_exists':bool(c['reference_file'] and Path(c['reference_file']).exists()),'budget':configuration.budget(c)})
    print(json.dumps(value,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
