#!/usr/bin/env python3
"""H/reference asset lifecycle. Checks and plans never call a solver or model."""
import argparse
import copy
from dataclasses import asdict
import json
import math
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha,digest
from experiments.triad import configuration,problems,runtime,evaluation


def identity(c,data,refs):
    # Search seed and optimizer are irrelevant to compatibility of fixed raw costs.
    return dict(obp_contract_sha256=digest(problems.obp_contract(c)) if c['problem']=='obp' else None,problem=c['problem'],instances=[{'file':r['file'],'sha256':r['sha256']} for r in data],references=refs,
      solve_seed=c['solve_seed'],instance_timeout_seconds=c['instance_timeout_seconds'],state_schema=problems.state.schema_id(c['problem']),
      public_state_spec=problems.state.SPEC_SHA256,obp_actions=c['obp_actions'],obp_h_abi=c['obp_h_abi'],obp_bound=c['obp_bound'],
      physical_sources={n:h for n,h in runtime.sources().items() if n in ('experiments/triad/problems.py','experiments/triad/evaluation.py') or n.startswith(('code/heuristic_design/problems/'+c['problem']+'/',))})


def fixed_plan(c):
    data,refs,hs=problems.load_inputs(c);binding=identity(c,data,refs)
    if not hs:raise ValueError('declared frozen H pool needed')
    reused=None
    if c.get('compatible_fixed_results'):
        previous=read(c['compatible_fixed_results'])
        if previous['identity']!=binding or previous['H_keys']!=[r['key'] for r in hs]:raise ValueError('fixed-result compatibility differs; preserved, not reevaluated')
        costs=previous['costs']
        if len(costs)!=len(hs) or any(len(v)!=len(data) for v in costs):raise ValueError('complete H×train cost table required')
        js=[sum(problems.state.score_final_cost(x,r['reference']) for x,r in zip(row,refs))/len(refs) for row in costs]
        champion=min(range(len(hs)),key=lambda i:(js[i],i));reused={'H_index':champion,'J':js[champion],'costs':costs,'new_solves':0}
    return dict(identity=binding,H_keys=[r['key'] for r in hs],max_native_solves=2*len(hs)*len(data),compatible_reuse=reused,API_requests=0,actual_solves=0)


def import_fixed(c,source,review,output):
    data,refs,hs=problems.load_inputs(c);proof=read(review);raw=read(source)
    expected={'H_keys':[r['key'] for r in hs],'instance_hashes':[r['sha256'] for r in data],
       'solve_seed':c['solve_seed'],'instance_timeout_seconds':c['instance_timeout_seconds']}
    if proof.get('status')!='compatible_raw_cost_reuse' or proof.get('source_sha256')!=sha(source) or any(proof.get(k)!=v for k,v in expected.items()) or proof.get('complete_and_valid') is not True:raise ValueError('existing compatibility audit does not certify this cost source')
    costs=raw['costs']
    if len(costs)!=len(hs) or any(len(row)!=len(data) or any(type(x) not in (int,float) or not math.isfinite(x) or x<0 for x in row) for row in costs):raise ValueError('complete finite H×instance raw costs required')
    if Path(output).exists():raise FileExistsError('new imported compatibility packet required; preserve source')
    write(output,{'identity':identity(c,data,refs),'H_keys':expected['H_keys'],'costs':costs,'source_sha256':sha(source),'compatibility_audit_sha256':sha(review),'new_solves':0,'historical_fitness_overwritten':False})
    return {'output':str(output),'sha256':sha(output),'new_solves':0,'API_requests':0}


def freeze_h(directory,output):
    p,s=runtime.protocol_state(directory)
    if p['run_kind']!='h-build' or s['phase']!='completed':raise ValueError('completed independent H-build required; old post-hoc candidates are not EoH-S')
    adapter=runtime.Adapter();adapter.check_run(directory)
    from heuristic_design.core import execution
    execution.ledger(Path(directory),s,p,adapter=adapter)
    count=p['config']['h_build']['target_count'];valid=[t for t in s['tasks'].values() if t['valid']]
    vectors={t['id']:[r['score'] for r in read(Path(directory)/s['evaluations'][t['evaluation_key']]['path'])['instances']] for t in valid}
    from experiments.triad import h_selection
    selected,selection_trace=h_selection.select(valid,vectors,count,p['config']['h_build']['selection'])
    output=Path(output)
    if output.exists():raise FileExistsError('frozen H output already exists; no overwrite')
    packet=dict(kind='H_frozen',engineering_only=p['config']['api_mode']=='mock',problem=p['config']['problem'],identity='bounded independent H construction + complete train J selection; NOT EoH-S',
      members=[{'id':t.get('semantic_id',t['id']),'candidate':t['candidate'],'train_J':t['J']} for t in selected[:count]],
      selection_policy=p['config']['h_build']['selection'],selection_trace=selection_trace,source_protocol_sha256=s['identity'],data=p['instances'],references=p['references'],budget=p['budgets'],API_summary=runtime.Adapter().summary(directory))
    if p['config']['problem']=='obp':packet.update(obp_contract=p['obp_execution_contract'],obp_contract_sha256=p['obp_contract_sha256'],H_language=p['config']['obp_h_abi'])
    write(output,packet);write(output.with_suffix('.receipt.json'),{'sha256':sha(output),'source_protocol':s['identity']});return {'output':str(output),'sha256':sha(output),'H_count':count,'new_solves':0,'API_requests':0}


def lkh_prepare(config,output,spec):
    c=configuration.load(config);manifest=read(c['data_manifest'])
    if c['problem']!='tsp' or manifest['split']!='train':raise ValueError('explicit TSP train manifest required')
    s=read(spec)
    required=('lkh_binary','lkh_binary_sha256','version','integer_scale','runs','max_trials','seed','distance_protocol','timeout_seconds','additional_parameters')
    if s.get('approved') is not True:raise PermissionError('PROTOCOL_PENDING: LKH specification not adopted')
    if not s.get('lkh_binary') or not s.get('lkh_binary_sha256'):raise PermissionError('ASSET_MISSING: adopted D06 still needs official source/compiled binary identity; run lkh-source and lkh-bind')
    if any(s.get(k) is None for k in required):raise ValueError('incomplete adopted LKH specification')
    reserved={'PROBLEM_FILE','OUTPUT_TOUR_FILE','RUNS','MAX_TRIALS','SEED'}
    if s.get('additional_parameters') is not None and any(k in reserved or not str(k).replace('_','').isalpha() or '\n' in str(v) or '\r' in str(v) for k,v in s['additional_parameters'].items()):raise ValueError('duplicate/unsafe LKH parameters')
    if sha(s['lkh_binary'])!=s['lkh_binary_sha256']:raise ValueError('fixed LKH executable identity differs')
    if s['distance_protocol']!={'input':'unit-square-float64-euclidean','LKH_edge_type':'EXPLICIT','integer_rounding':'floor(scale*d+0.5)','reference_cost':'recomputed-original-distance-closed-tour'}:raise ValueError('unsupported distance protocol; no silent conversion')
    if any(type(s[k]) is not int or s[k]<1 for k in ('integer_scale','runs','max_trials')) or type(s['seed']) is not int:raise ValueError('explicit positive LKH controls required')
    if type(s['timeout_seconds']) not in (int,float) or s['timeout_seconds']<=0 or not isinstance(s['additional_parameters'],dict):raise ValueError('bounded LKH timeout and explicit additional parameter map required')
    if s.get('cpu_seconds')!=120 or s['timeout_seconds']!=150 or s['additional_parameters'].get('TIME_LIMIT')!=10:raise PermissionError('adopted D06 CPU120/wall150/TIME_LIMIT10 must be explicit')
    out=Path(output)
    if out.exists():raise FileExistsError('new reference preparation directory required')
    out.mkdir(parents=True);commands=[]
    from heuristic_design.problems.tsp.solver import distances
    for row in manifest['instances']:
        source=(Path(c['data_manifest']).parent/row['path']).resolve()
        if sha(source)!=row['sha256']:raise ValueError('TSP training asset changed')
        value=read(source);matrix=distances(value['coordinates']);n=len(matrix);name=Path(row.get('file',source.name)).stem
        task=out/name;task.mkdir();tsp=task/'problem.tsp';par=task/'parameters.par'
        body=['NAME: '+name,'TYPE: TSP','DIMENSION: '+str(n),'EDGE_WEIGHT_TYPE: EXPLICIT','EDGE_WEIGHT_FORMAT: FULL_MATRIX','EDGE_WEIGHT_SECTION']
        body+=[' '.join(str(int(math.floor(float(x)*s['integer_scale']+0.5))) for x in line) for line in matrix];body+=['EOF'];tsp.write_text('\n'.join(body)+'\n')
        par.write_text('\n'.join(['PROBLEM_FILE = '+str(tsp.resolve()),'OUTPUT_TOUR_FILE = '+str((task/'result.tour').resolve()),'RUNS = '+str(s['runs']),'MAX_TRIALS = '+str(s['max_trials']),'SEED = '+str(s['seed'])]+[str(k)+' = '+str(v) for k,v in sorted(s['additional_parameters'].items())])+'\n')
        commands.append({'file':row.get('file',source.name),'instance_sha256':digest(value),'input':str(source),'command':[s['lkh_binary'],str(par.resolve())],'tour':str((task/'result.tour').resolve()),'parameter_file':str(par.resolve()),'parameter_sha256':sha(par),'problem_sha256':sha(tsp)})
    write(out/'reference-plan.json',{'spec':s,'commands':commands,'LKH_executed':False});return {'prepared':str(out),'commands':commands,'LKH_executed':False}


def lkh_run(folder,allow_lkh,approve_lkh):
    import os,time,signal,resource
    folder=Path(folder);plan=read(folder/'reference-plan.json');spec=plan['spec']
    if not allow_lkh or approve_lkh!=len(plan['commands']):raise PermissionError('manual --allow-lkh --approve-lkh exact process count required')
    if sha(spec['lkh_binary'])!=spec['lkh_binary_sha256']:raise ValueError('fixed LKH binary changed')
    if spec.get('cpu_seconds')!=120 or spec['timeout_seconds']!=150:raise PermissionError('hard CPU120/wall150 required; no old unlimited runner')
    target=folder/'LKH-run-receipt.json'
    if target.exists():raise ValueError('prior LKH launch/reservation exists; no automatic retry or budget reset')
    receipt={'phase':'reserved','plan_sha256':sha(folder/'reference-plan.json'),'reserved_processes':len(plan['commands']),'completed_processes':0,'automatic_retry':False,'internal_RUNS':spec['runs'],'MAX_TRIALS':spec['max_trials'],'timeout_seconds_per_process':spec['timeout_seconds'],'CPU_hard_seconds_per_process':120,'attempts':[]}
    fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump(receipt,f);f.flush();os.fsync(f.fileno())
    for row in plan['commands']:
        if sha(row['parameter_file'])!=row['parameter_sha256'] or sha(Path(row['parameter_file']).parent/'problem.tsp')!=row['problem_sha256']:raise ValueError('frozen LKH input changed')
        event={'file':row['file'],'state':'reserved','started_at':time.time()};receipt['attempts'].append(event);write(target,receipt)
        try:
            log=Path(row['parameter_file']).parent/'LKH.log'
            before=resource.getrusage(resource.RUSAGE_CHILDREN);started=time.monotonic()
            # Fresh single-process official LKH, Python child sets the limit
            # before exec; no thread-unsafe preexec_fn in the parent.
            child='import os,resource,sys;resource.setrlimit(resource.RLIMIT_CPU,(120,120));os.execv(sys.argv[1],sys.argv[1:])'
            with log.open('x') as output:
                process=subprocess.Popen([sys.executable,'-s','-B','-c',child,*row['command']],stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    code=process.wait(timeout=150)
                    if code:raise subprocess.CalledProcessError(code,row['command'])
                except BaseException:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    process.wait(timeout=5);raise
            if not Path(row['tour']).exists():raise ValueError('LKH tour missing')
            after=resource.getrusage(resource.RUSAGE_CHILDREN)
            event.update(state='completed',tour_sha256=sha(row['tour']),exit_code=code,wall_seconds=time.monotonic()-started,child_CPU_seconds=(after.ru_utime+after.ru_stime)-(before.ru_utime+before.ru_stime));receipt['completed_processes']+=1;write(target,receipt)
        except BaseException as x:
            event.update(state='failed_or_unknown',error_type=type(x).__name__);receipt['phase']='stopped';write(target,receipt);raise
    receipt['phase']='completed';write(target,receipt);return receipt


def lkh_source(output,download=False,build=False,academic=False):
    """Operator-invoked official download/build only; never execute LKH."""
    import tarfile,urllib.request,hashlib
    out=Path(output).resolve();archive=out/'LKH-3.0.13.tgz';receipt=out/'source-receipt.json'
    url='https://webhotel4.ruc.dk/~keld/research/LKH-3/LKH-3.0.13.tgz'
    if not (download or build) or build and not academic:raise PermissionError('explicit download/build action required; compiling requires manual source-license acceptance')
    if download:
        if out.exists():raise FileExistsError('new LKH source folder required; no overwrite/retry')
        out.mkdir(parents=True);write(receipt,{'state':'download_reserved','official_URL':url,'automatic_retry':False})
        with urllib.request.urlopen(url,timeout=30) as response:raw=response.read(20*1024*1024+1)
        if len(raw)>20*1024*1024:raise ValueError('bounded official source download exceeded20MiB')
        archive.write_bytes(raw)
        with tarfile.open(archive,'r:gz') as tf:
            for member in tf.getmembers():
                p=Path(member.name)
                if p.is_absolute() or '..' in p.parts or p.parts[0]!='LKH-3.0.13' or not (member.isfile() or member.isdir()):raise ValueError('unexpected archive root, links or device entries')
            tf.extractall(out,filter='data')
        write(receipt,{'state':'downloaded','official_URL':url,'observed_archive_sha256':sha(archive),'independent_official_digest':'not available; observed official-origin bytes only','license_scope':'operator accepted academic/noncommercial; preserve source notices','version':'3.0.13','LKH_runs':0})
    if build:
        record=read(receipt)
        if record['state']!='downloaded' or sha(archive)!=record['observed_archive_sha256']:raise PermissionError('matching official source receipt required')
        claim=out/'build-reservation.json'
        if claim.exists():raise FileExistsError('prior build attempt retained; no automatic rebuild')
        write(claim,{'state':'reserved','automatic_retry':False})
        with (out/'build.log').open('x') as log:subprocess.run(['make'],cwd=out/'LKH-3.0.13',stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
        binary=out/'LKH-3.0.13/LKH';record.update(state='built',binary=str(binary),binary_sha256=sha(binary));write(receipt,record)
    return {**read(receipt),'LKH_executed':False}


def lkh_bind(source,output):
    record=read(Path(source)/'source-receipt.json');spec=read(ROOT/'experiments/triad/lkh.pending.json')
    if record['state']!='built' or sha(record['binary'])!=record['binary_sha256']:raise PermissionError('actual compiled official source identity required')
    spec.update(lkh_binary=record['binary'],lkh_binary_sha256=record['binary_sha256'])
    if Path(output).exists():raise FileExistsError('preserve prior bound LKH spec')
    write(output,spec);return {'bound_spec':str(output),'LKH_executed':False}


def job_submit(a):
    """One bounded asset job, not another model/search execution layer."""
    from experiments.triad.concurrency_probe import claim
    folder=a.run_dir.resolve();kind=a.asset
    if kind=='obp-H':
        c=configuration.load(a.config);cap=c['h_build']['request_cap']
        if c['problem']!='obp' or cap!=40 or not a.allow_api or not a.allow_solves or a.approve_budget!=40 or a.approve_solves!=7680:raise PermissionError('OBP H401 requires explicit40 requests/<=7680 first+recheck solves')
        if (Path(c['account_gate'])/'generation.lock').exists():raise PermissionError('shared account lease exists; do not overlap or clear it')
        action='resume' if a.resume else 'run';r=c['resources'];cpus=r['cpus'];memory=r['memory_mib'];seconds=r['segment_seconds']
        if not (folder/'Protocol.json').exists():
            if a.resume:raise PermissionError('cannot resume uninitialized H build')
            subprocess.run([sys.executable,'-s','-B',str(ROOT/'experiments/triad/entry.py'),'prepare','--kind','h-build','--config',str(a.config.resolve()),'--run-dir',str(folder),'--allow-api','--approve-budget','40'],check=True)
        cp=read(folder/'checkpoint.json')
        if cp['phase']!=('paused' if a.resume else 'prepared') or any((folder/n).exists() for n in ('.execution.lock','Stop.json')):raise PermissionError('H build requires prepared or safely paused original state')
        args=[kind,'/public2/home/qiuqian/hdl-envs/portable-v2/bin/python',action,str(a.config.resolve()),str(folder),'40'];stamp=sha(folder/'checkpoint.json')
    else:
        plan=read(folder/'reference-plan.json')
        if not a.allow_lkh or a.approve_lkh!=len(plan['commands']) or a.allow_api or a.allow_solves or a.resume:raise PermissionError('explicit exact LKH process count, no API, no automatic LKH resume/retry')
        if (folder/'LKH-run-receipt.json').exists():raise PermissionError('prior LKH execution exists; preserve budget/receipt')
        cpus=1;memory=1024;seconds=len(plan['commands'])*150+900;r={'partition':'128C_02','account':'wz','qos':'normal'}
        args=['lkh','/public2/home/qiuqian/hdl-envs/portable-v2/bin/python',str(folder),str(a.approve_lkh)];stamp=sha(folder/'reference-plan.json')
    h,left=divmod(seconds,3600);m,s=divmod(left,60);job_name='asset-'+kind+'-'+folder.name
    command=['sbatch','--parsable','--no-requeue','--nodes=1','--ntasks=1','--cpus-per-task='+str(cpus),'--mem='+str(memory)+'M','--time='+f'{h:02d}:{m:02d}:{s:02d}','--partition='+r['partition'],'--account='+r['account'],'--qos='+r['qos'],'--chdir='+str(ROOT),'--job-name='+job_name,'--output='+str(ROOT/'logs'/(job_name+'-%j.out')),str(ROOT/'experiments/triad/assets.sbatch'),*args]
    if kind=='obp-H':command.insert(command.index(str(ROOT/'experiments/triad/assets.sbatch')),'--signal=B:USR1@'+str(r['drain_seconds']))
    if not a.submit:return {'submitted':False,'command':command}
    for previous in (folder/'submissions').glob('asset-*.json'):
        record=read(previous)
        if record['state']!='submitted':raise PermissionError('unknown asset submission retained; do not retry')
        account=subprocess.run(['sacct','-n','-P','-j',record['job_id'],'--format=JobIDRaw,State'],check=True,text=True,capture_output=True)
        state=next((line.split('|')[1].split()[0] for line in account.stdout.splitlines() if line.split('|')[0]==record['job_id']),None)
        if state not in ('COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED'):raise PermissionError('previous asset job active/unknown')
    receipt=folder/'submissions'/('asset-'+stamp+'.json');record={'state':'submission_reserved','command':command,'asset':kind,'automatic_retry':False};claim(receipt,record);(ROOT/'logs').mkdir(exist_ok=True)
    result=subprocess.run(command,check=True,text=True,capture_output=True);job=result.stdout.strip().split(';')[0]
    if not job.isdigit():raise RuntimeError('unknown sbatch receipt; reserved asset claim retained')
    record.update(state='submitted',job_id=job);write(receipt,record);write(folder/'latest-asset-submission.json',record);return record


def lkh_import(folder,output):
    p=read(Path(folder)/'reference-plan.json');rows=[]
    receipt=read(Path(folder)/'LKH-run-receipt.json')
    if receipt['phase']!='completed' or receipt['plan_sha256']!=sha(Path(folder)/'reference-plan.json') or receipt['completed_processes']!=len(p['commands']):raise ValueError('complete bounded manual LKH execution receipt required')
    from heuristic_design.problems.tsp.solver import distances,tour_length
    for row in p['commands']:
        observed=next((r for r in receipt['attempts'] if r['file']==row['file']),None)
        if not observed or observed['state']!='completed' or observed['tour_sha256']!=sha(row['tour']):raise ValueError('LKH tour differs from bounded execution receipt')
        text=Path(row['tour']).read_text();part=text.split('TOUR_SECTION',1)[1].split('-1',1)[0];tour=[int(x)-1 for x in part.split()]
        if len(tour)!=len(set(tour)) or 0 not in tour:raise ValueError('invalid LKH tour')
        i=tour.index(0);tour=tour[i:]+tour[:i]+[0];cost=tour_length(distances(read(row['input'])['coordinates']),tour)
        rows.append({'file':row['file'],'instance_sha256':row['instance_sha256'],'reference':cost,'tour':tour,'source':'LKH','tour_file_sha256':sha(row['tour'])})
    if Path(output).exists():raise FileExistsError('reference output already frozen')
    s=p['spec'];write(output,{'kind':'fixed-LKH-reference-v1','lkh_identity':{'version':s['version'],'binary_sha256':s['lkh_binary_sha256']},'parameters':{k:s[k] for k in ('runs','max_trials','seed','integer_scale')},'distance_protocol':s['distance_protocol'],'execution_receipt_sha256':sha(Path(folder)/'LKH-run-receipt.json'),'instances':rows});return {'output':str(output),'sha256':sha(output),'LKH_executed':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['obp-import','check','fixed-plan','fixed-run','fixed-import','build-check','build-prepare','build-run','freeze','lkh-prepare','lkh-import','lkh-run','lkh-source','lkh-bind','job-submit'])
    ap.add_argument('--source',type=Path);ap.add_argument('--config',type=Path);ap.add_argument('--run-dir',type=Path);ap.add_argument('--output',type=Path);ap.add_argument('--spec',type=Path)
    ap.add_argument('--allow-lkh',action='store_true');ap.add_argument('--approve-lkh',type=int)
    ap.add_argument('--download',action='store_true');ap.add_argument('--build',action='store_true');ap.add_argument('--accept-academic-license',action='store_true')
    ap.add_argument('--asset',choices=['obp-H','lkh']);ap.add_argument('--submit',action='store_true');ap.add_argument('--resume',action='store_true')
    ap.add_argument('--allow-api',action='store_true');ap.add_argument('--allow-solves',action='store_true');ap.add_argument('--approve-budget',type=int);ap.add_argument('--approve-solves',type=int)
    a=ap.parse_args()
    if a.action=='job-submit':value=job_submit(a)
    elif a.action=='lkh-source':value=lkh_source(a.output,a.download,a.build,a.accept_academic_license)
    elif a.action=='lkh-bind':value=lkh_bind(a.source,a.output)
    elif a.action=='obp-import':
        from experiments.triad import obp_data
        value=obp_data.prepare(a.source,a.spec,a.output)
    elif a.action=='freeze':value=freeze_h(a.run_dir,a.output)
    elif a.action=='lkh-prepare':value=lkh_prepare(a.config,a.output,a.spec)
    elif a.action=='lkh-run':value=lkh_run(a.run_dir,a.allow_lkh,a.approve_lkh)
    elif a.action=='lkh-import':value=lkh_import(a.run_dir,a.output)
    else:
        if a.config is None:raise ValueError('explicit config required')
        c=configuration.load(a.config)
        if a.action=='fixed-import':value=import_fixed(c,a.source,a.spec,a.output)
        elif a.action=='check':
            hs=[]
            if c.get('h_file'):
                raw=read(c['h_file']);hs=[r.get('candidate',r) for r in (raw['members'] if isinstance(raw,dict) else raw)]
                for row in hs:problems.checked_h(c['problem'],row)
            value={'H_count':len(hs),'H_keys':[x['key'] for x in hs],'pending':configuration.gaps(c),'data_manifest_exists':bool(c.get('data_manifest') and Path(c['data_manifest']).exists()),'API_requests':0,'actual_solves':0}
        elif a.action=='build-check':value={'pending':[k for k,v in c['h_build'].items() if v is None],'H_budget_separate':c['h_build'],'API_requests':0,'actual_solves':0}
        elif a.action.startswith('build-'):
            action='prepare' if a.action=='build-prepare' else 'run';cmd=[sys.executable,'-B',str(ROOT/'experiments/triad/entry.py'),action,'--config',str(a.config),'--run-dir',str(a.run_dir),'--kind','h-build']
            if a.allow_api:cmd+=['--allow-api','--approve-budget',str(a.approve_budget)]
            if a.allow_solves:cmd+=['--allow-solves']
            return subprocess.run(cmd).returncode
        else:
            value=fixed_plan(c)
            if a.action=='fixed-run':
                if value['compatible_reuse'] is not None:print(json.dumps(value,ensure_ascii=False,indent=2));return 0
                if c['problem']=='fjsp' and c.get('compatible_fixed_results') is None:raise PermissionError('existing FJSP 10H×train21 baseline must be imported/reused; no automatic 420-pass reevaluation')
                if not a.allow_solves or a.approve_solves!=value['max_native_solves'] or a.allow_api:raise PermissionError('explicit inclusive solve cap and no API approval required')
                if a.run_dir is None or a.run_dir.exists():raise ValueError('new fixed-evaluation directory required')
                data,refs,hs=problems.load_inputs(c);a.run_dir.mkdir(parents=True);sources=runtime.sources();costs=[]
                lock=a.run_dir/'.fixed.lock';lock.touch(exist_ok=False)
                ledger={'reserved_native_solves':value['max_native_solves'],'completed_H':0,'phase':'running','automatic_retry':False};write(a.run_dir/'fixed-ledger.json',ledger)
                for i,h in enumerate(hs):
                    selector=asdict(problems.u_language.validate('def use_heuristics(state):\n    return 0\n','fixed H host',1))
                    result=evaluation.evaluate({'id':f'H-{i:03d}','candidate':selector},{'config':c,'members':[h],'instances':data,'references':refs,'source_files':sources,'run_directory':str(a.run_dir)})
                    write(a.run_dir/f'H-{i:03d}.json',result)
                    if not result['valid']:raise RuntimeError('fixed H invalid; bounded stop without refill')
                    costs.append([r['raw_cost'] for r in result['instances']]);ledger['completed_H']+=1;write(a.run_dir/'fixed-ledger.json',ledger)
                write(a.run_dir/'fixed-results.json',{'identity':value['identity'],'H_keys':value['H_keys'],'costs':costs});value['output']=str(a.run_dir/'fixed-results.json');ledger['phase']='completed';write(a.run_dir/'fixed-ledger.json',ledger);lock.unlink()
    print(json.dumps(value,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as x:print(json.dumps({'error_type':type(x).__name__,'error':str(x),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
