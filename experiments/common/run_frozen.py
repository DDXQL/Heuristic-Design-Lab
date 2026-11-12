#!/usr/bin/env python3
"""Frozen single-run entry. Default check-only never requests, solves or writes."""
import os
for _name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS'):
    os.environ[_name]='1'
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core import evolution_v1 as engine
from heuristic_design.core.storage import read, sha, digest, write
from heuristic_design.core.execution_contract import resources


def missing(value,prefix=''):
    rows=[]
    if isinstance(value,dict):
        for k,v in value.items():
            if v is None and k not in ('temperature','reasoning_effort','p0_file','actual_cost'):
                rows.append(prefix+k)
            elif isinstance(v,(list,dict)):rows+=missing(v,prefix+k+'.')
    elif isinstance(value,list):
        for i,v in enumerate(value):
            if v is None:rows.append(prefix+str(i))
            elif isinstance(v,(dict,list)):rows+=missing(v,prefix+str(i)+'.')
    return rows


def configuration(path,index=None):
    path=Path(path).resolve();document=read(path)
    if set(document)!={'version','freeze_status','campaign_id','seeds','run_root','settings'} or document['version']!='fjsp-single-launch-v1':
        raise ValueError('explicit launch schema required')
    pending=[] if document['freeze_status']=='mock_frozen' else missing(document)
    if document['freeze_status'] not in ('mock_frozen','research_frozen'):pending.append('freeze_status')
    if pending:return document,None,None,pending
    seeds=document['seeds']
    if not seeds or any(type(s) is not int or s<0 for s in seeds) or len(set(seeds))!=len(seeds):
        raise ValueError('explicit unique independent search seeds required')
    if index is None:
        if len(seeds)!=1:raise ValueError('multiple seeds require explicit --index; no implicit array/expansion')
        index=0
    if type(index) is not int or not 0<=index<len(seeds):raise ValueError('seed index outside frozen declaration')
    settings=document['settings']
    required=set(engine.DEFAULTS)-{'mock_delay_seconds','mock_reverse_delay','mock_faults'}
    if set(settings)-set(engine.DEFAULTS) or required-set(settings):
        raise ValueError('every non-Mock engine field must be explicit; defaults cannot freeze research parameters')
    c=json.loads(json.dumps(settings));c['search_seed']=seeds[index]
    x=c['execution_contract'];x['run_id']=document['campaign_id']+'-seed-'+str(seeds[index])
    for k in ('h_file','data_manifest','p0_file'):
        if c.get(k):c[k]=str((path.parent/c[k]).resolve())
    if x.get('account_gate'):x['account_gate']=str((path.parent/x['account_gate']).resolve())
    if document['freeze_status']=='mock_frozen':
        if c['api_mode']!='mock' or c['evaluation_mode']!='mock' or c['real_requests_authorized']:
            raise ValueError('Mock launch must use synthetic receipts exclusively')
    elif len(seeds)!=1:
        raise ValueError('this first research release permits one seed only; support is not authorization')
    c=engine.config(c)
    directory=(path.parent/document['run_root']/x['run_id']).resolve()
    return document,c,directory,[]


def check_only(path,index=None):
    document,c,directory,pending=configuration(path,index)
    result={'offline':True,'model_requests':0,'solves':0,'writes':0,'configuration_sha256':sha(path),
            'freeze_status':document['freeze_status'],'pending':pending,'ready':False}
    if c is None:return result
    from heuristic_design.core.terminal_ops import inputs
    from heuristic_design.problems.routing_fixtures import compile_members, precheck_instances
    members,instances,provenance=inputs(c)
    if members is not None:compile_members(c['problem'],members)
    if instances is not None:precheck_instances(c['problem'],instances)
    from heuristic_design.core.execution_contract import drain_bound
    result.update(ready=True,run_dir=str(directory),seed=c['search_seed'],group=c['execution_contract']['group'],
        resources=resources(c),input_provenance=provenance,
        initialization_max_attempts=c['initialization_request_cap'],
        initialization_policy=c['execution_contract']['initialization_policy'],
        evolution_attempts=c['generation_request_cap'],total_request_cap=c['api_attempt_cap'],
        declared_seed_count=len(document['seeds']),all_declared_runs_request_cap=len(document['seeds'])*c['api_attempt_cap'],
        drain_bound_seconds=drain_bound(c,len(instances) if instances else 2),
        authorization_for_real_requests=c['real_requests_authorized'],
        note='ready denotes offline structural validity, not API/solver/cluster acceptance or launch authorization')
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',nargs='?',default='check-only',choices=['check-only','prepare','run','resume','pause','status','export'])
    parser.add_argument('--config',type=Path,required=True);parser.add_argument('--index',type=int)
    parser.add_argument('--allow-api',action='store_true');parser.add_argument('--allow-evaluation',action='store_true')
    parser.add_argument('--credential-file',type=Path,help='existing owner-only cluster credential; read only in explicit real run/resume')
    parser.add_argument('--max-tasks',type=int,help='Mock boundary pause for offline acceptance only')
    args=parser.parse_args(argv)
    try:
        if args.action=='check-only':
            result=check_only(args.config,args.index)
        else:
            document,c,directory,pending=configuration(args.config,args.index)
            if pending:raise ValueError('unfrozen inputs: '+', '.join(pending))
            if args.action=='prepare':
                if args.allow_api or args.allow_evaluation:raise ValueError('prepare is offline; do not supply execution flags')
                result=engine.prepare(directory,c)
                write(directory/'Launch_configuration.json',{'sha256':sha(args.config),'document':document,'index':args.index})
            else:
                binding=read(directory/'Launch_configuration.json')
                if binding['sha256']!=sha(args.config):raise ValueError('launch configuration changed; never reset budget by editing it')
                if args.action=='pause':result=engine.request_pause(directory)
                elif args.action=='status':
                    from heuristic_design.core.terminal_ops import snapshot
                    result=snapshot(directory)
                elif args.action=='export':
                    from heuristic_design.core.execution_export import export
                    p,s=engine.check(directory);result=export(directory,p,s)
                else:
                    p,s=engine.check(directory)
                    if s['phase']!=('paused' if args.action=='resume' else 'prepared'):
                        raise ValueError('run requires prepared; resume requires safely paused original checkpoint')
                    if c['evaluation_mode']=='solve' and not args.allow_evaluation:raise PermissionError('explicit --allow-evaluation required')
                    if c['api_mode']=='real' and args.credential_file is not None:
                        if not args.allow_api or not c['real_requests_authorized']:raise PermissionError('explicit real launch authorization required before credential access')
                        import stat
                        fd=os.open(args.credential_file,os.O_RDONLY|os.O_NOFOLLOW)
                        with os.fdopen(fd) as keyfile:
                            info=os.fstat(keyfile.fileno())
                            if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600 or not stat.S_ISREG(info.st_mode):
                                raise ValueError('credential must be personally owned regular nonsymlink mode600 file')
                            secret=keyfile.read(4096).strip()
                        if not secret or '\n' in secret or '\r' in secret:raise ValueError('credential absent or malformed')
                        os.environ[c['provider']['api_key_env']]=secret
                    if args.max_tasks is not None and document['freeze_status']!='mock_frozen':raise ValueError('Mock control only')
                    result=engine.run(directory,allow_api=args.allow_api,max_tasks=args.max_tasks)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if result.get('pending') or result.get('phase') in ('blocked','initialization_incomplete'):return 2
        return 0
    except Exception as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
