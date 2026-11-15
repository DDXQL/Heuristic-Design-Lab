#!/usr/bin/env python3
"""Single independently budgeted experiment. Default check-only, no secret reads."""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from contextlib import nullcontext
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
for n in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS'):os.environ[n]='1'
from heuristic_design.core.storage import read,write,sha
from heuristic_design.core import execution
from experiments.triad import runtime,configuration


def key(c):
    fd=os.open(c['credential_file'],os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as f:
        s=os.fstat(f.fileno())
        if s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=0o600 or not stat.S_ISREG(s.st_mode):raise ValueError('credential must be personally owned nonsymlink mode600 regular file')
        value=f.read(4096).strip()
    if not value or '\n' in value or '\r' in value:raise ValueError('invalid runtime credential format')
    os.environ[c['provider']['api_key_env']]=value


def frozen_launch(c,d,authorize=False):
    from heuristic_design.core.evolution_v1 import source_identity
    manifest=read(ROOT/'preparations/triad/fjsp/public-runtime-923781f.json')
    if source_identity()!=manifest['files']:raise ValueError('same-version FJSP U public runtime differs from 923781f; no silent source upgrade')
    v=read(c['frozen_u_template']);s=v['settings'];x=s['execution_contract']
    # The approved 501 algorithm/actual Prompt/evaluation identity stays unchanged.
    fields=('population_size','initialization_request_cap','generation_request_cap','api_attempt_cap','solve_seed','api_concurrency','evaluation_concurrency','instance_timeout_seconds','provider')
    wanted={**c,'generation_request_cap':c['evolution_request_cap']}
    if any(s[k]!=wanted[k] for k in fields):raise ValueError('same-version FJSP U must retain actual 501 scientific settings; a changed profile needs separate identity')
    if sha(c['h_file'])!=read(ROOT/'preparations/triad/fjsp/provenance.json')['H_sha256']:raise ValueError('same-version frozen H asset differs')
    if c['initialization_policy']!=x['initialization_policy']:raise ValueError('501 initialization policy differs')
    v.update(campaign_id=d.name.rsplit('-seed-',1)[0],seeds=[c['search_seed']],run_root=str(d.parent),freeze_status='research_frozen' if c['mode']=='real' else 'mock_frozen')
    s.update(search_seed=c['search_seed'],h_file=c['h_file'],data_manifest=c['data_manifest'],real_requests_authorized=authorize,api_mode=c['mode'],evaluation_mode='solve' if c['mode']=='real' else 'mock')
    x.update(run_id=d.name,allocated_cpus=c['resources']['cpus'],window_seconds=c['window_seconds'],segment_seconds=c['resources']['segment_seconds'],drain_seconds=c['resources']['drain_seconds'],account_gate=c['account_gate'],account_exclusion={**(c['account_exclusion'] or {}),'run_id':d.name})
    return v


def approve(c,args,deadline=None):
    cap=c['h_build']['request_cap'] if getattr(args,'kind',None)=='h-build' else c['api_attempt_cap']
    if c['mode']=='mock':
        if args.allow_api or args.approve_budget is not None:raise PermissionError('no real approval in Mock')
        return
    if not args.allow_api or args.approve_budget!=cap:raise PermissionError('explicit original request cap required')
    if args.action in ('run','resume') and not args.allow_solves:raise PermissionError('explicit --allow-solves required')
    e=c['account_exclusion'];end=deadline or time.time()+c['window_seconds']
    if not e or e.get('scope')!='all_devices_sharing_account' or not e.get('confirmation') or e.get('valid_until',0)<end:raise PermissionError('all-device account exclusion must cover original run window')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['check-only','prepare','run','status','pause','resume','export'])
    ap.add_argument('--config',type=Path,required=True);ap.add_argument('--run-dir',type=Path)
    ap.add_argument('--kind',choices=['search','h-build'],default='search');ap.add_argument('--engineering',action='store_true');ap.add_argument('--allow-api',action='store_true');ap.add_argument('--allow-solves',action='store_true');ap.add_argument('--approve-budget',type=int)
    ap.add_argument('--pause-after-attempts',type=int,help='absolute cumulative settled-attempt prefix within original cap')
    ap.add_argument('--approve-segment-solves',type=int,help='inclusive first/recheck upper bound for this finite segment')
    ap.add_argument('--shared-manifest',type=Path,help='new-version two-search request admission; never use to take over an old run')
    args=ap.parse_args();c=configuration.load(args.config,engineering=args.engineering)
    if c.get('shared_manifest') and (args.shared_manifest is None or str(args.shared_manifest.resolve())!=c['shared_manifest']):raise PermissionError('this new-version shared child requires its original --shared-manifest')
    if args.kind=='h-build':c=runtime.h_build_config(c)
    if args.action=='check-only':
        if args.allow_api or args.allow_solves or args.approve_budget is not None:raise PermissionError('check-only carries no execution approval')
        c,data,refs,hs,todo=runtime.preflight(args.config,args.engineering,'h-build' if args.kind=='h-build' else None)
        print(json.dumps(dict(group=c['group'],pending=todo,ready=not todo,environment='not_fully_checked' if todo else 'passed',API_requests=0,actual_solves=0,credential_reads=0,budget=configuration.budget(c)),ensure_ascii=False,indent=2));return 0
    if args.run_dir is None:raise ValueError('explicit independent --run-dir required')
    d=args.run_dir.resolve()
    if not d.is_relative_to(ROOT/'runs'):raise ValueError('run must be inside this release runs/')
    if c.get('search_seed') is None:raise PermissionError('select a frozen independent seed before preparing')
    shared=None
    if args.shared_manifest:
        from experiments.triad import shared_admission
        shared=shared_admission.binding(args.shared_manifest,d,args.config)
    if args.kind!='h-build' and c['mode']=='real' and c['group']=='fjsp-u' and c['search_seed'] in (501,502) and args.action in ('prepare','run','resume'):raise PermissionError('completed frozen U501/U502 are protected read-only; never rerun/take over')
    if args.kind!='h-build' and c['problem']=='fjsp' and c['method']=='u' and (c['mode']=='real' or shared):
        launch=d.parent/(d.name+'.launch.json')
        if args.action in ('prepare','run') and not d.exists():
            if shared and c['mode']=='mock':todo=configuration.gaps(c)
            else:_,_,_,_,todo=runtime.preflight(args.config,args.engineering,'h-build' if args.kind=='h-build' else None)
            if todo:raise PermissionError('PROTOCOL_PENDING: '+', '.join(todo))
            approve(c,args);v=frozen_launch(c,d,authorize=c['mode']=='real')
            if launch.exists() and read(launch)!=v:raise ValueError('existing frozen child launch differs')
            write(launch,v)
            subprocess.run([sys.executable,'-B',str(ROOT/'experiments/common/run_frozen.py'),'prepare','--config',str(launch)],check=True,text=True,capture_output=True)
            write(d/'Triad_binding.json',{'config_sha256':sha(args.config),'launch_sha256':sha(launch),'public_execution_commit':'923781f05686f1899c24fd7899fb3bc6b1df1562'})
            if shared:shared_admission.attach(d,shared)
        if not launch.exists():raise ValueError('frozen per-seed launch missing')
        if read(d/'Triad_binding.json')!={'config_sha256':sha(args.config),'launch_sha256':sha(launch),'public_execution_commit':'923781f05686f1899c24fd7899fb3bc6b1df1562'}:raise ValueError('original per-seed config/launch binding changed')
        if shared:shared_admission.verify_attachment(d,shared)
        elif (d/'Shared_execution.json').exists():raise PermissionError('shared run requires its original --shared-manifest')
        cmd=[sys.executable,'-B',str(ROOT/'experiments/common/run_frozen.py'),args.action,'--config',str(launch)]
        if args.action=='prepare':print(json.dumps({'prepared':True,'API_requests':0,'actual_solves':0,'run_dir':str(d)}));return 0
        if args.action in ('run','resume'):
            approve(c,args,read(d/'Run_clock.json')['deadline'] if (d/'Run_clock.json').exists() else None)
            if c['mode']=='real':cmd += ['--allow-api','--allow-evaluation','--credential-file',c['credential_file']]
            if args.pause_after_attempts is not None:
                from heuristic_design.core.storage import read as read_json
                state=read_json(d/'checkpoint.json');used=state['initialization_requests']+state['generation_requests'];maximum=0 if shared and c['mode']=='mock' else 2*(args.pause_after_attempts-used)*c['instance_count']
                if shared and c['mode']=='real' and not state['initialization_complete']:
                    wave=min(max(c['api_concurrency'],c['evaluation_concurrency']),c['population_size']-len(state['population']),c['initialization_request_cap']-state['initialization_candidates'])
                    if args.pause_after_attempts!=used+wave:raise PermissionError('finite U initialization must stop after the NEXT WHOLE wave, never split or predict future successful initialization')
                if args.pause_after_attempts<=used or args.pause_after_attempts>c['api_attempt_cap'] or args.approve_segment_solves!=maximum:raise PermissionError('finite prefix and inclusive solve upper bound must match original remaining budget')
                cmd+=['--pause-after-attempts',str(args.pause_after_attempts)]
        if shared and args.action in ('run','resume'):
            from experiments.triad.shared_frozen import execute
            return execute(cmd[3:],shared,d)
        return subprocess.run(cmd).returncode
    adapter=shared_admission.adapter(shared) if shared else runtime.Adapter()
    if args.action in ('status','pause','export'):
        adapter.check_run(d)
        value=adapter.summary(d) if args.action=='status' else execution.stop(d,adapter=adapter) if args.action=='pause' else runtime.export(d)
    else:
        if not d.exists():
            _,_,_,_,todo=runtime.preflight(args.config,args.engineering,'h-build' if args.kind=='h-build' else None)
            if todo:raise PermissionError('PROTOCOL_PENDING: '+', '.join(todo))
            approve(c,args);runtime.prepare(d,args.config,engineering=args.engineering,allow_api=args.allow_api,approve_budget=args.approve_budget,run_kind='h-build' if args.kind=='h-build' else None)
            if shared:shared_admission.attach(d,shared)
        if not shared and (d/'Shared_execution.json').exists():raise PermissionError('shared run requires its original --shared-manifest')
        p=adapter.check_run(d);_,s=runtime.protocol_state(d)
        if sha(args.config)!=p['config_sha256']:raise ValueError('original config changed; no reset or rebind')
        if args.action=='prepare':value={'prepared':True,'API_requests':0,'actual_solves':0,'run_dir':str(d)}
        else:
            deadline=read(d/'Run_clock.json')['deadline'] if (d/'Run_clock.json').exists() else None
            approve(c,args,deadline);execution.ledger(d,s,p,adapter=adapter)
            prefix=args.pause_after_attempts
            expected_solves=0 if shared and c['mode']=='mock' else 2*(prefix-s['cursor'])*len(p['instances']) if prefix is not None else None
            if prefix is not None and (not s['cursor']<prefix<=c['api_attempt_cap'] or args.approve_segment_solves!=expected_solves):raise PermissionError('finite segment must declare exact inclusive first/recheck cap under original cumulative budget')
            seq=len(list((d/'manual-boundaries').glob('*.json')))+1
            control={'sequence':seq,'protocol':s['identity'],'settled_prefix':prefix,'original_request_cap':c['api_attempt_cap'],'remaining_segment_request_cap':None if prefix is None else prefix-s['cursor'],'inclusive_native_solve_cap':args.approve_segment_solves,'at':time.time()}
            write(d/'manual-boundaries'/f'{seq:04d}.json',control);write(d/'Current_manual_boundary.json',control)
            if p['config']['api_mode']=='real':
                if os.environ.get('SLURM_JOB_ID') and int(os.environ.get('SLURM_CPUS_PER_TASK','0'))<c['resources']['cpus']:raise ValueError('allocation below declared CPUs')
                key(c);gate=Path(c['account_gate']);gate.mkdir(parents=True,exist_ok=True)
                fd=os.open(gate/'generation.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                with os.fdopen(fd,'w') as f:json.dump({'run_id':d.name,'protocol':s['identity']},f);f.flush();os.fsync(f.fileno())
                adapter.segment_deadline=time.monotonic()+c['resources']['segment_seconds']
            with (d/'terminal.log').open('a') as log:
                from contextlib import redirect_stdout,redirect_stderr
                from experiments.common._single_run import _Tee
                with redirect_stdout(_Tee(sys.stdout,log)),redirect_stderr(_Tee(sys.stderr,log)):
                    with shared_admission.Admission(shared).session(d) if shared else nullcontext():
                        value=execution.start(d,adapter=adapter,resume=args.action=='resume',allow_api=args.allow_api)
            runtime.export(d)
            if p['config']['api_mode']=='real' and value['phase'] in ('completed','paused','initialization_incomplete','expired') and not (d/'Stop.json').exists() and not adapter.summary(d)['requires_investigation']:
                lock=Path(c['account_gate'])/'generation.lock'
                if read(lock)['protocol']==s['identity']:lock.unlink()
    print(json.dumps(value,ensure_ascii=False,indent=2));return 0 if value.get('phase') not in ('stopped','initialization_incomplete','expired') else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as x:print(json.dumps({'error_type':type(x).__name__,'error':str(x),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
