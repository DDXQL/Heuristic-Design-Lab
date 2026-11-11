"""Common Mac/cluster bounded validation; extends the prior reliability entry.

Only run/resume with explicit --allow-api --approve-total 4 can dispatch.
All other commands use local files, never solve or read credential values.
"""
import argparse,csv,fcntl,hashlib,io,json,os,platform,signal,socket,stat,sys,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.llm.legacy import ClientConfig
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport,admit
from fjsp_usage.research_real.real_transport import WIRE_VERSION,failure_category,request_payload,request_audit
from fjsp_usage.research.candidates import parse_response
from heuristic_design.core.routing import parse as parse_u
PLAN=ROOT/'deploy/api-common/plan.json'
OUTBOX=Path('/Users/DDXQL/Developer/transfer-outbox')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
    tmp.replace(path)
def verify():
    p=read(PLAN)
    if sha(PLAN)!=(PLAN.with_suffix('.sha256')).read_text().split()[0]:raise ValueError('frozen plan changed')
    if (p['version']!='mac-cluster-api-v5-20261111' or p['new_total_cap']!=4
            or p['stage_cap']!=2 or p['api_concurrency']!=1 or p['automatic_retry'] is not False
            or p['real_requests_authorized'] is not False or WIRE_VERSION!=p['wire_version']
            or [t['id'] for t in p['tasks']]!=['fjsp_h','tsp_u']):
        raise ValueError('unreviewed plan/cap/client identity')
    for name,h in p['files'].items():
        path=ROOT/name
        if not path.resolve().is_relative_to(ROOT) or sha(path)!=h:raise ValueError('frozen file changed: '+name)
    import fjsp_usage.research_real.real_transport as module
    if Path(module.__file__).resolve()!=ROOT/'code/fjsp_usage/research_real/real_transport.py':
        raise ValueError('imported transport is outside frozen release')
    if platform.python_version()!=p['python_version']:raise ValueError('frozen Python version required: '+p['python_version'])
    return p

def directory(site):
    # Fixed per-site claim under the user's home: copying releases cannot reset it.
    return Path.home()/'hdl-api-validation/mac-cluster-api-v5-20261111'/site

def parse_candidate(text,kind):
    result={'extracted':False,'static_legal':None,'solved':False}
    import re
    match=re.fullmatch(r'\s*(.*?)\s*```python\s*\n(.*?)\n```\s*',text or '',re.S)
    if not match or (text or '').count('```')!=2 or not match[1].strip():
        result['failure_layer']='candidate_extraction';return result
    result['extracted']=True
    try:
        c=parse_response(text,kind='h') if kind=='fjsp_h' else parse_u(text,10)
        result.update(static_legal=True,key=c.key)
    except ValueError as error:result.update(static_legal=False,failure_layer='code_constraint',error=str(error)[:300])
    return result

def stage_export(site):
    d=directory(site);ledger=read(d/'ledger.json')
    value={'version':'api-v5-stage-export-v1','site':site,'plan_sha256':sha(PLAN),
           'ledger_sha256':sha(d/'ledger.json'),'ledger':ledger,
           'reservations':{p.name:read(p) for p in sorted((d/'reservations').glob('*.json'))},
           'responses':{p.name:read(p) for p in sorted((d/'responses').glob('*.json'))},
           'caller_rejections':{p.name:read(p) for p in sorted((d/'caller_rejections').glob('*.json'))}}
    save(d/'export.json',value);return d/'export.json'

def prior_receipt(path,p):
    if not path:raise ValueError('cluster stage requires the finished Mac export')
    e=read(path)
    expected=hashlib.sha256((json.dumps(e['ledger'],ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()).hexdigest()
    if expected!=e['ledger_sha256']:raise ValueError('Mac export ledger hash mismatch')
    if e['site']!='mac' or e['plan_sha256']!=sha(PLAN) or e['ledger']['status'] not in ('completed','failed_closed'):
        raise ValueError('Mac must finish before cluster; paused/unknown stage is not admission')
    if e['ledger'].get('global_hard_stop'):raise ValueError('Mac explicit refusal/identity failure blocks cluster stage')
    rs=e['ledger']['records']
    if (e['ledger']['status']=='completed' and (len(rs)!=2 or any(r['status']!='passed' for r in rs))) or (e['ledger']['status']=='failed_closed' and (not rs or rs[-1]['status']!='failed')):
        raise ValueError('Mac terminal state/count mismatch')
    for r in rs:
        response=e['responses'].get(f"{r['slot']:02d}.json")
        encoded=(json.dumps(response,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
        if response is None or hashlib.sha256(encoded).hexdigest()!=r.get('response_sha256'):
            raise ValueError('Mac response export changed')
    if len(e.get('reservations',{}))!=len(rs):raise ValueError('Mac reservation receipts differ')
    if len(rs)>2 or any(r['status'] not in ('passed','failed') for r in rs):raise ValueError('ambiguous Mac request; no cluster dispatch')
    if len(rs)+p['stage_cap']>p['new_total_cap']:raise ValueError('cumulative cap exceeded')
    return e

def totals(ledger,reservation_count=None):
    rows=ledger['records'];orphan=max(0,(reservation_count or 0)-len(rows));return {'reserved':len(rows)+orphan,'confirmed_sends':sum(r['send_status']=='confirmed' for r in rows),
        'send_unknown':sum(r['send_status']=='unknown' for r in rows)+orphan,
        'response_passed':sum(r.get('response_pass') is True for r in rows),
        'static_passed':sum((r.get('candidate') or {}).get('static_legal') is True for r in rows),
        'failed':sum(r['status']=='failed' for r in rows),
        'known_input_tokens':sum((r.get('usage') or {}).get('input_tokens',0) for r in rows),
        'known_output_tokens':sum((r.get('usage') or {}).get('output_tokens',0) for r in rows),
        'usage_unknown':sum(r.get('usage') is None for r in rows)+orphan,
        'sent_usage_unknown':sum(r['send_status']=='confirmed' and r.get('usage') is None for r in rows)}

def run(site,*,allow_api=False,approve_total=None,resume=False,mac_export=None,credential_file=None):
    p=verify()
    if not allow_api or approve_total!=4:raise PermissionError('requires --allow-api --approve-total 4 for this new plan')
    if site=='mac' and sys.platform!='darwin':raise ValueError('Mac stage must run on Mac')
    if site=='cluster' and (not os.environ.get('SLURM_JOB_ID') or socket.gethostname()=='master'):
        raise ValueError('cluster online stage requires a compute-node Slurm allocation')
    previous=prior_receipt(mac_export,p) if site=='cluster' else None
    d=directory(site);d.mkdir(parents=True,exist_ok=True)
    owner=(d/'owner.lock').open('a+')
    try:fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:owner.close();raise ValueError('stage controller is active; no overlap')
    try:
        if resume:
            l=read(d/'ledger.json')
            if l['status']!='paused' or l['plan_sha256']!=sha(PLAN) or any(r['status']!='passed' for r in l['records']):
                raise ValueError('resume only a safely paused settled prefix; unknown/failed requests never replay')
            receipts={f.name:read(f) for f in (d/'reservations').glob('*.json')}
            if read(d/'claim.json')['plan_sha256']!=sha(PLAN) or len(receipts)!=len(l['records']) or len(l['records'])>2:
                raise ValueError('reservation ledger mismatch; never refill or reset')
            for i,row in enumerate(l['records']):
                receipt=receipts.get(f"{i+1:02d}.json",{})
                if row['slot']!=i+1 or row['task']!=p['tasks'][i]['id'] or receipt.get('request_sha256')!=row['request']['serialized_body_sha256'] or receipt.get('plan_sha256')!=sha(PLAN) or sha(d/'responses'/f"{i+1:02d}.json")!=row['response_sha256']:
                    raise ValueError('settled prefix/reservation response changed')
            if l['status']!='paused' or l['plan_sha256']!=sha(PLAN) or any(r['status']!='passed' for r in l['records']):
                raise ValueError('resume only a safely paused, fully settled successful prefix; never replay unknown/failed')
        elif (d/'claim.json').exists() or (d/'ledger.json').exists():raise FileExistsError('stage already claimed; no new run or refill')
        else:l=None
        # Credential value is read only inside explicit online run, never check/replay/status.
        name=p['provider']['api_key_env'];secret=os.environ.get(name)
        if not secret and credential_file:
            key=Path(credential_file).expanduser();info=key.stat()
            if key.is_symlink() or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600:
                raise ValueError('credential file must be personally owned, nonsymlink, mode600')
            secret=key.read_text().strip()
        if not secret or '\n' in secret or '\r' in secret:raise ValueError('credential absent or malformed; no request reserved')
        os.environ[name]=secret
        cfg={'api_mode':'real','real_requests_authorized':True,'provider':p['provider'],'api_attempt_cap':2,'per_candidate_attempt_cap':1}
        transport=StrictNonstreamTransport(ClientConfig({'config':cfg,'budgets':{'logical_generation':2}}))
        transport.rejection_directory=d/'caller_rejections'
        for task in p['tasks']:transport.preflight((ROOT/task['prompt']).read_text())
        if l is None:
            with (d/'claim.json').open('x') as f:
                json.dump({'plan_sha256':sha(PLAN),'site':site,'new_total_cap':4,'stage_cap':2,'at':time.time()},f);f.flush();os.fsync(f.fileno())
            l={'version':p['version'],'site':site,'plan_sha256':sha(PLAN),'status':'running','stage_cap':2,'new_total_cap':4,
               'prior_new_reserved':len(previous['ledger']['records']) if previous else 0,
               'records':[],'solves':0,'automatic_retry':False,'actual_money_cost':None,'global_hard_stop':False,
               'runtime':{'pid':os.getpid(),'platform':sys.platform,'monotonic_implementation':time.get_clock_info('monotonic').implementation,'python':platform.python_version(),'transport_file':str(Path(__import__('fjsp_usage.research_real.real_transport',fromlist=['x']).__file__).resolve()),
                          'wire_version':WIRE_VERSION,'slurm_job_id':os.environ.get('SLURM_JOB_ID'),'hostname':socket.gethostname()}}
        else:l['status']='running';l.setdefault('resume_events',[]).append({'at':time.time(),'old_records':len(l['records']),'pid':os.getpid(),'slurm_job_id':os.environ.get('SLURM_JOB_ID')})
        # Acknowledge control sequence, retaining all old control requests on disk.
        ack=read(d/'Stop_request.json').get('sequence',0) if (d/'Stop_request.json').exists() else 0
        interrupted=[False];old_signals={}
        def request_stop(*_):interrupted[0]=True
        for signum in (signal.SIGINT,signal.SIGTERM,getattr(signal,'SIGUSR1',signal.SIGINT)):
            try:old_signals[signum]=signal.signal(signum,request_stop)
            except ValueError:pass # tests may call run on a fixture thread
        save(d/'ledger.json',l)
        try:
            for task in p['tasks'][len(l['records']):]:
                seq=read(d/'Stop_request.json').get('sequence',0) if (d/'Stop_request.json').exists() else 0
                if interrupted[0] or seq>ack:l['status']='paused';break
                row={'slot':len(l['records'])+1,'task':task['id'],'kind':task['kind'],'status':'reserved',
                     'reserved_at_unix':time.time(),'send_status':'unknown','usage':None,'response_pass':False,
                     'candidate':{'extracted':None,'static_legal':None,'solved':False}}
                if len(l['records'])>=2:raise ValueError('physical stage cap exhausted')
                prompt=(ROOT/task['prompt']).read_text();payload=request_payload(transport.provider,site+'-'+task['id'],prompt)
                row['request']=request_audit(payload,json.dumps(payload).encode())
                (d/'reservations').mkdir(exist_ok=True)
                with (d/'reservations'/f"{row['slot']:02d}.json").open('x') as f:
                    json.dump({'slot':row['slot'],'task':task['id'],'plan_sha256':sha(PLAN),
                               'request_sha256':row['request']['serialized_body_sha256'],'at':row['reserved_at_unix']},f)
                    f.flush();os.fsync(f.fileno())
                l['records'].append(row);save(d/'ledger.json',l)
                def sent():row.update(send_status='confirmed',send_confirmed_at_unix=time.time());save(d/'ledger.json',l)
                row['dispatch_started_at_unix']=time.time();began=time.monotonic()
                try:
                    value=transport.dispatch(site+'-'+task['id'],prompt,kind='h' if task['kind']=='fjsp_h' else 'U',on_sent=sent)
                    admit(value,p['provider']['expected_response_model']);candidate=parse_candidate(value['text'],task['kind'])
                    row.update(status='passed' if candidate['static_legal'] else 'failed',response_pass=True,candidate=candidate,
                               metadata=value['metadata'],usage=value['usage'],send_status='confirmed')
                    if not candidate['static_legal']:row['failure_layer']=candidate['failure_layer']
                    save(d/'responses'/f"{row['slot']:02d}.json",value)
                except Exception as error:
                    meta=transport.redact_metadata(getattr(error,'metadata',{}));category=failure_category(str(error),meta)
                    row.update(status='failed',error=transport.redact(str(error))[:500],metadata=meta,
                               usage=getattr(error,'usage',None),send_status=meta.get('send_status',row['send_status']),failure_layer=category)
                    # Explicit denial or response identity rejection blocks the later platform stage.
                    l['global_hard_stop']=bool(meta.get('http_status') in (400,401,402,403,404,405,422) or meta.get('failure_class')=='permanent'
                        or meta.get('caller_hard_stop'))
                    save(d/'responses'/f"{row['slot']:02d}.json",row)
                row['response_sha256']=sha(d/'responses'/f"{row['slot']:02d}.json")
                finished=time.time();elapsed=time.monotonic()-began
                row.update(finished_at_unix=finished,elapsed_seconds=elapsed)
                gap=(finished-row['dispatch_started_at_unix'])-elapsed
                if abs(gap)>2:
                    row['local_clock_gap_seconds']=gap
                    l.setdefault('clock_events',[]).append({'slot':row['slot'],'wall_minus_monotonic_seconds':gap,
                        'settled':True,'cause':'local suspend/clock gap; provider cause not inferred'})
                save(d/'ledger.json',l)
                if row['status']=='failed':l['status']='failed_closed';break
                if abs(gap)>2:l['status']='paused';break
            else:l['status']='completed'
        except BaseException:
            l['status']='unknown_interruption';raise
        finally:
            l['totals']=totals(l,len(list((d/'reservations').glob('*.json'))));save(d/'ledger.json',l);stage_export(site)
            for signum,handler in old_signals.items():signal.signal(signum,handler)
        return l
    finally:fcntl.flock(owner,fcntl.LOCK_UN);owner.close()

def replay():
    p=verify();rows=[]
    for case in p['replay']:
        value=read(ROOT/case['file'])
        if case['type']=='normalized':
            try:admit(value,p['provider']['expected_response_model']);valid=True
            except Exception:valid=False
            candidate=parse_candidate(value.get('text'),case['kind']) if valid else None
            observed=bool(valid and candidate['static_legal'])
            if observed!=case['expected']:raise ValueError('saved response replay differs: '+case['file'])
            rows.append({'file':case['file'],'response_pass':valid,'candidate':candidate})
        else:
            if case['type']=='clock':
                observed='local_clock_gap' if abs(value['wall_minus_monotonic_seconds'])>2 else 'no_gap'
            else:observed=failure_category(value.get('error',''),value.get('metadata',{}))
            if observed!=case['expected']:raise ValueError('saved failure classification differs: '+case['file'])
            rows.append({'file':case['file'],'classification':observed})
    return {'offline':True,'model_requests':0,'solves':0,'cases':rows}

def bundle(mac_export):
    p=verify();prior_receipt(mac_export,p)
    if sys.platform!='darwin':raise ValueError('transfer bundle is created on Mac only')
    out=OUTBOX/'api-common-v5-20261111.zip'
    out.parent.mkdir(parents=True,exist_ok=True)
    names=list(p['files'])+['deploy/api-common/plan.json','deploy/api-common/plan.sha256']
    if out.exists():
        with zipfile.ZipFile(out) as z:
            if set(z.namelist())!=set(names+['deploy/api-common/mac-export.json']):raise ValueError('existing archive file set differs')
            if hashlib.sha256(z.read('deploy/api-common/plan.json')).hexdigest()!=sha(PLAN):raise ValueError('existing archive plan differs; preserve it')
            if z.read('deploy/api-common/mac-export.json')!=Path(mac_export).read_bytes():raise ValueError('existing archive Mac receipt differs; preserve it')
            for name,h in p['files'].items():
                if hashlib.sha256(z.read(name)).hexdigest()!=h:raise ValueError('existing archive source differs; preserve it')
        return out
    with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for name in names:z.write(ROOT/name,name)
        z.write(mac_export,'deploy/api-common/mac-export.json')
    (out.with_suffix('.zip.sha256')).write_text(sha(out)+'  '+out.name+'\n')
    return out

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['check-only','replay','run','resume','status','stop','export','bundle'])
    parser.add_argument('--site',choices=['mac','cluster'],default='mac');parser.add_argument('--allow-api',action='store_true');parser.add_argument('--approve-total',type=int)
    parser.add_argument('--mac-export',type=Path);parser.add_argument('--credential-file');args=parser.parse_args()
    try:
        p=verify();d=directory(args.site)
        if args.command=='check-only':value={'offline':True,'model_requests':0,'solves':0,'version':p['wire_version'],'plan_sha256':sha(PLAN),'new_cap':4,'stage_cap':2,'concurrency':1,'state_path':str(d),'tasks':[{k:t[k] for k in ('id','kind','bytes','sha256')} for t in p['tasks']]}
        elif args.command=='replay':value=replay()
        elif args.command in ('run','resume'):value=run(args.site,allow_api=args.allow_api,approve_total=args.approve_total,resume=args.command=='resume',mac_export=args.mac_export,credential_file=args.credential_file)
        elif args.command=='status':
            value=read(d/'ledger.json') if (d/'ledger.json').exists() else {'status':'not_started','no_request':True}
            value['reservation_receipt_count']=len(list((d/'reservations').glob('*.json')))
            if 'records' in value:value['totals']=totals(value,value['reservation_receipt_count'])
        elif args.command=='stop':
            previous=read(d/'Stop_request.json') if (d/'Stop_request.json').exists() else {'sequence':0}
            save(d/'Stop_request.json',{'sequence':previous['sequence']+1,'at':time.time(),'action':'drain_current_request_and_pause'});value={'stop_requested':True,'requests_added':0}
        elif args.command=='export':value={'export':str(stage_export(args.site)),'requests_added':0}
        else:value={'bundle':str(bundle(args.mac_export)),'requests_added':0}
        if args.command in ('run','resume'):
            print(json.dumps({'status':value['status'],'site':value['site'],'totals':value['totals'],'export':str(d/'export.json')},ensure_ascii=False,indent=2))
            return 0 if value['status'] in ('completed','paused') else 2
        print(json.dumps(value,ensure_ascii=False,indent=2));return 0
    except (ValueError,FileExistsError,FileNotFoundError,PermissionError) as error:print(str(error),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
