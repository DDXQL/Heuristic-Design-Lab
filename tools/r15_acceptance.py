#!/usr/bin/env python3
"""Bounded R15 API and TSP training acceptance on an allocated compute node."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import multiprocessing
import os
from pathlib import Path
import re
from threading import Barrier
import time

import experiment
from experiment import ROOT

from experiments.triad import entry, evaluation, problems, runtime, six_ops
from experiments.triad.concurrency_probe import claim
from fjsp_usage.research_real.budget import validate_usage
from heuristic_design.core.execution_contract import send_state
from heuristic_design.core.storage import digest, read, sha, write
from heuristic_design.llm.legacy import ClientConfig
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport


need = experiment.require
WIDTHS = (2, 4, 8)
PROMPT = "Reply with exactly the word OK."


def setup_tsp(config):
    need(config is not None, "TSP requires --config pointing to a D06-bound workbench JSON")
    doc, _ = experiment.load_document(config)
    rows, preview = experiment.prepare(doc)
    need(preview['ready_for_submission_checks'] and doc['execution']['mode']=='real'
         and [(c['group']) for c,_ in rows]==['tsp-u','tsp-eoh'], 'require exactly TSP U and EoH in that order with ready D06 assets')
    planned=[]
    for c,_ in rows:
        data, refs, hs = problems.load_inputs(c)
        assets=ROOT/'preparations/triad/tsp'
        need(len(data)==20 and sha(Path(c['data_manifest']))==sha(assets/'train20.manifest.json')
             and (c['method']=='eoh' or sha(Path(c['h_file']))==sha(assets/'H_frozen.json')),
             'TSP pilot requires the released train20 and frozen U 10H')
        v={'run_kind':c['method'],'config':c,'members':hs,'instances':data,'references':refs,
           'source_files':runtime.sources()}
        adapter=runtime.Adapter();adapter.p=v
        task={'id':'INIT-0000','operator':'INIT' if c['method']=='u' else 'I1','stage':'initialization'}
        prompt=adapter.build_prompt(c,task,[],hs)
        planned.append((v,prompt))
    return planned


def client(c, *, short):
    frozen=read(ROOT/'deploy/eoh-baseline/unified-inputs.json')['client_binding']
    need(c['client_binding']==frozen and c['provider']==frozen['provider'], 'provider or V5 binding differs from release')
    for name, expected in frozen['files'].items():
        actual=sha(ROOT/name)
        need(actual==expected or name=='code/fjsp_usage/research_real/real_transport.py'
             and actual=='65c3b290091981f45758c9e4369cccd08a061e621522467103f53ab8d44d59cc', 'V5 source changed')
    provider=dict(c['provider'])
    if short:provider.update(max_output_tokens=128)
    return ClientConfig({'config':{'provider':provider,'api_mode':'real','real_requests_authorized':True,
                                    'api_attempt_cap':1,'per_candidate_attempt_cap':1},'budgets':{'logical_generation':1}})


def summarize(folder):
    rows=[read(p) for p in sorted(folder.glob('request-*.json'))]
    ends=[r['ended_at'] for r in rows if 'ended_at' in r]
    starts=[r['sent_at'] for r in rows if 'sent_at' in r]
    events=sorted([e for r in rows if 'sent_at' in r for e in
                   [(r['sent_at'],1), *([(r['ended_at'],-1)] if 'ended_at' in r else [])]])
    active=peak=0
    for _, delta in events:
        active+=delta;peak=max(peak,active)
    duration=max(ends)-min(starts) if starts and ends and max(ends)>min(starts) else None
    successes=sum(r['state']=='returned' for r in rows)
    return {'requests_reserved':len(rows),'confirmed_sends':len(starts),'peak_confirmed_in_flight':peak,
            'successful_responses':successes,'elapsed_seconds':duration,
            'throughput_responses_per_second':successes/duration if duration else None,
            'known_tokens':{key:sum((r.get('usage') or {}).get(key,0) for r in rows)
                            for key in ('input_tokens','output_tokens')},
            'usage_unknown':sum(r.get('usage') is None and r.get('send_status')!='not_sent' for r in rows),
            'errors':[r for r in rows if r['state']=='failed'],
            'result_files':[str(p) for p in sorted(folder.glob('request-*.json'))]}


def dispatch(folder, number, transport, prompt, kind, *, barrier=None):
    path=folder/f'request-{number:02d}.json'
    row={'number':number,'kind':kind,'state':'reserved','started_at':time.time()}
    claim(path,row)
    if barrier is not None:barrier.wait(timeout=15)

    def on_sent():
        row.update(sent_at=time.time(),send_status='confirmed')
        write(path,row)

    try:
        reply=transport.dispatch(f'{folder.parent.name}/{folder.name}/{number}',prompt,kind=kind,on_sent=on_sent)
    except Exception as error:
        meta=getattr(error,'metadata',{}) or {}
        reply=None
        status=send_state({'sent':'sent_at' in row,'metadata':meta})
        if status=='not_sent' and meta.get('send_status')!='not_sent' and (
                meta.get('deadline_kind')=='total' or 'finished_seconds' not in (meta.get('wire_timing') or {})):
            status='unknown'
        row.update(state='failed',error_type=type(error).__name__,error=transport.redact(str(error))[:300],
                   send_status=status,
                   usage=validate_usage(getattr(error,'usage',None)))
    else:
        meta=reply.get('metadata') or {}
        row.update(state='returned',usage=validate_usage(reply.get('usage')))
    row.update(ended_at=time.time(), **{k:meta[k] for k in ('http_status','retry_after','failure_stage',
               'gateway_request_id','upstream_http_status') if k in meta})
    row['latency_seconds']=row['ended_at']-row.get('sent_at',row['started_at'])
    write(path,row)
    return row,reply


def probe(folder, width, factory, wait=time.sleep):
    waves=[]
    for wave in range(2):
        barrier=Barrier(width)
        transports=[factory() for _ in range(width)]
        with ThreadPoolExecutor(max_workers=width) as pool:
            futures=[pool.submit(dispatch,folder,wave*width+i+1,t,PROMPT,'acceptance',barrier=barrier)
                     for i,t in enumerate(transports)]
            rows=[f.result()[0] for f in futures]
        duration=max(r['ended_at'] for r in rows)-min(r['started_at'] for r in rows)
        waves.append({'elapsed_seconds':duration,'responses_per_second':sum(r['state']=='returned' for r in rows)/duration
                      if duration>0 else None})
        if any(r['state']!='returned' or r.get('usage') is None or r.get('send_status')!='confirmed' for r in rows):
            break
        if wave==0:wait(61)
    report=summarize(folder)
    report['passed']=report['successful_responses']==2*width and report['peak_confirmed_in_flight']==width
    return {**report,'requested_width':width,'waves':waves,'actual_solves':0}


def tsp(folder, planned, factory, evaluate=evaluation.evaluate):
    results=[]
    for number,(p,prompt) in enumerate(planned,1):
        adapter=runtime.Adapter();adapter.p=p;adapter._engineering_mode=False
        is_u=p['run_kind']=='u'
        record,reply=dispatch(folder,number,factory(p['config']),prompt,'U' if is_u else 'H')
        output=folder/f'{p["run_kind"]}-result.json'
        result={'method':p['run_kind'],'candidate_valid':False,'evaluation_complete':False,'actual_solves':0,
                'prompt_sha256':digest(prompt),'source_files':p['source_files']}
        evaluation_failed=False
        if reply is not None:
            try:candidate=adapter.parse_candidate(reply['text'],p['config'])
            except adapter.CandidateError as error:result['candidate_error']=str(error)
            else:
                selector=candidate if is_u else problems.u_language.validate('def use_heuristics(state):\n    return 0\n','singleton H host',1)
                members=p['members'] if is_u else [asdict(candidate)]
                task_id=f'tsp-{p["run_kind"]}-init-0000'
                evaluation_started=time.monotonic()
                result.update(candidate_valid=True,candidate=asdict(candidate))
                try:
                    evaluated=evaluate({'id':task_id,'candidate':asdict(selector)},
                                       {**p,'members':members,'run_directory':str(folder)})
                    adapter.validate_result(evaluated,p['instances'])
                except (OSError, RuntimeError, ValueError) as error:
                    result['evaluation_error']={'type':type(error).__name__,'detail':str(error)[:300]}
                    evaluation_failed=True
                else:
                    result.update(evaluation_complete=evaluated['valid'],evaluation_result=evaluated,
                                  J=-evaluated['fitness'] if evaluated['valid'] else None)
                result['evaluation_seconds']=time.monotonic()-evaluation_started
                events=folder/'worker-receipts'/task_id/'physical-solves.jsonl'
                result['actual_solves']=sum(json.loads(line)['event']=='started' for line in events.read_text().splitlines()) if events.is_file() else 0
        write(output,result)
        results.append({'path':str(output),**{k:v for k,v in result.items()
                                             if k not in ('candidate','evaluation_result','source_files')}})
        # Authentication/quota/ambiguous sending is a shared-account boundary.
        if evaluation_failed or record.get('send_status')=='unknown' or any(record.get(k) in (401,402,403,429)
                for k in ('http_status','upstream_http_status')):break
    report=summarize(folder)
    return {**report,'results':results,'actual_solves':sum(r['actual_solves'] for r in results),
            'passed':len(results)==2 and all(r['evaluation_complete'] and r['actual_solves']==40 for r in results)}


def execute(args, folder, planned, cap):
    max_solves=80 if args.kind=='tsp' else 0
    need(args.approve_requests==cap and args.approve_solves==max_solves and args.confirm_exclusive_account,
         'exact request/solve caps and explicit sole-account confirmation required')
    job=os.environ.get('SLURM_JOB_ID','')
    width=args.width if args.kind=='api' else 1
    deadline=entry.allocation_deadline()
    need(job.isdigit() and os.environ.get('SLURM_STEP_ID','')!='' and int(os.environ.get('SLURM_CPUS_PER_TASK','0'))>=width+1
         and deadline-time.monotonic() > (2100 if args.kind=='tsp' else 700), 'use srun on a sufficiently sized Slurm compute allocation')
    c=planned[0][0]['config'] if planned else six_ops.config('tsp-eoh')
    if args.kind=='api':
        need(args.rpm is not None and args.tpm is not None and args.rpm>=width and args.tpm>=512*width,
             'explicit provider-confirmed RPM and TPM must cover the planned burst')
        if width!=WIDTHS[0]:
            previous=folder.parent/f'api-{WIDTHS[WIDTHS.index(width)-1]}'/'result.json'
            need(previous.is_file() and read(previous).get('passed') is True, 'preceding concurrency stage has not passed')
    config=client(c,short=args.kind=='api')
    lease=Path(c['account_gate'])/'generation.lock'
    need(not lease.exists() and not folder.exists(), 'account occupied or this acceptance stage already reserved')
    folder.mkdir(parents=True,exist_ok=False)
    owner={'protocol':'R15-ACCEPTANCE:'+digest({'release':str(ROOT),'stage':str(folder),'job':job}),
           'batch':str(folder),'job_id':job}
    claim(lease,owner)
    claim(folder/'authorization.json',{**owner,'request_cap':cap,'solve_cap':max_solves,'model':config.provider.model,
                                       'required_rpm':args.rpm,'required_tpm':args.tpm})
    started=time.monotonic()
    try:
        entry.key(c)
        if args.kind=='api':result=probe(folder,width,lambda:StrictNonstreamTransport(config))
        else:result=tsp(folder,planned,lambda member:StrictNonstreamTransport(client(member,short=False)))
        need(result['requests_reserved']<=cap and result['actual_solves']<=max_solves,'acceptance budget exceeded')
        result.update(total_wall_seconds=time.monotonic()-started,job_id=job,report_file=str(folder/'result.json'))
        write(folder/'result.json',result)
        return result
    finally:
        rows=[read(p) for p in folder.glob('request-*.json')]
        if (not multiprocessing.active_children() and lease.is_file() and read(lease)==owner
                and all(r['state']!='reserved' and r.get('send_status') in ('confirmed','not_sent') for r in rows)):
            lease.unlink()


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('kind',choices=('api','tsp'));cli.add_argument('action',choices=('plan','run','status'))
    cli.add_argument('--name',required=True);cli.add_argument('--width',type=int,choices=WIDTHS)
    cli.add_argument('--config',type=Path);cli.add_argument('--rpm',type=int);cli.add_argument('--tpm',type=int)
    cli.add_argument('--approve-requests',type=int);cli.add_argument('--approve-solves',type=int)
    cli.add_argument('--confirm-exclusive-account',action='store_true')
    args=cli.parse_args()
    need(bool(re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}',args.name)), 'invalid acceptance name')
    need((args.width is not None)==(args.kind=='api'), '--width applies only to the API probe')
    need(args.action=='run' or not any((args.approve_requests,args.approve_solves,args.confirm_exclusive_account)),
         'approvals are only accepted for run')
    cap=2*args.width if args.width else 2
    folder=ROOT/'reports'/('acceptance-'+args.name)/(f'api-{args.width}' if args.width else 'tsp')
    if args.action=='status':
        result=read(folder/'result.json') if (folder/'result.json').is_file() else summarize(folder)
    else:
        planned=setup_tsp(args.config) if args.kind=='tsp' else []
        result=execute(args,folder,planned,cap) if args.action=='run' else {
            'output':str(folder),'request_cap':cap,'solve_cap':80 if planned else 0,'ready_for_user_approval':True,
            'real_requests_by_plan':0,'actual_solves_by_plan':0}
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
