#!/usr/bin/env python3
"""Finish one user-paused, durably complete wire reply; never generate/replay.

Only pending lifecycle records can be completed. Original files are retained
in a pinned recovery snapshot before native billing/ledger/journal completion.
Failed or interrupted terminal requests cannot be promoted by this tool.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'code')]
from tools.resume_usage_metadata import (sha, verify_existing, ORIGIN, MigratedUsageConfig,
    RegisteredUsageWorkflow, StagedDataset, SerialGuard, RunLock)
from tools.reconcile_usage_429 import query_receipts
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.budget import BudgetStop, validate_usage
from fjsp_usage.usage_v2.billing import match_invoice


def pending_binding(directory, pause_path):
    pause=json.loads(pause_path.read_text());key=pause['last_key'];name=hashlib.sha256(key.encode()).hexdigest()+'.json'
    if pause.get('status')!='PAUSED_BY_USER' or pause.get('last_wire_status')!='wire_completed_before_settlement':
        raise BudgetStop('not a saved complete response at a user pause')
    for relative,value in pause['immutable_snapshot_files_sha256'].items():
        p=directory/relative
        if p.resolve().is_relative_to(directory.resolve()) is False or sha(p)!=value:
            raise BudgetStop('paused checkpoint/ledger/wire changed')
    paths={'budget':directory/'budget.json','quota':directory/'platform_quota.json',
        'checkpoint':directory/'r301/B/checkpoint.json','journal':directory/'r301/B/budgeted_evolution_requests.json',
        'billing':directory/'billing'/name,'wire':directory/'wire_responses'/name}
    bodies={label:json.loads(p.read_text()) for label,p in paths.items()}
    b,q,state,j,bill,wire=(bodies[n] for n in ('budget','quota','checkpoint','journal','billing','wire'))
    pending=state.get('inflight') or {};identifier=pending.get('id');record=j['requests'].get(identifier,{})
    prompt_key=digest({'prompt':pending.get('prompt'),'kind':'U'})
    reply=wire.get('reply',{});usage=validate_usage(reply.get('usage'))
    if (key!='r301/B/'+str(identifier) or pending.get('initial') is not False
            or identifier in state.get('evaluations',{}) or any(x['id']==identifier for x in state['attempts'])
            or record.get('status')!='pending' or record.get('global_key')!=key
            or record.get('prompt')!=pending.get('prompt') or record.get('prompt_key')!=prompt_key
            or b['records'][key].get('status')!='reserved' or b['records'][key].get('send_confirmed') is not True
            or q['records'][key].get('status')!='pending' or q['records'][key].get('send_confirmed') is not True
            or bill.get('status')!='before_dispatch' or bill.get('global_key')!=key
            or wire.get('global_key')!=key or wire.get('prompt_key')!=prompt_key
            or wire.get('status')!='wire_completed_before_settlement' or wire.get('send_confirmed') is not True
            or not isinstance(reply.get('text'),str) or not reply['text'] or usage is None
            or not reply.get('metadata',{}).get('gateway_request_id')):
        raise BudgetStop('pending saved response/prompt/identity binding differs; no promotion')
    finished=paths['wire'].stat().st_mtime
    paused=datetime.fromisoformat(pause['observed_at_utc']).timestamp()
    if not q['records'][key]['started_at']<=finished<=paused:
        raise BudgetStop('saved wire completion outside original pause interval')
    return key,identifier,paths,bodies,finished


def closed_record(old,finished,balance,invoices,bill,reply,model):
    if reply['metadata'].get('model')!=model:raise BudgetStop('saved response model differs')
    account={**old,'status':'settled','finished_at':finished,
        'finished_at_basis':'persisted complete wire mtime, bounded by original pause snapshot',
        'settlement_observed_at':time.time(),'after_used':balance['total_used'],
        'observed_account_delta':balance['total_used']-old['before_used'],'transport_status':'completed'}
    invoice=match_invoice(bill['before'],invoices,account,model,failed=False,
        response_id=reply['metadata']['gateway_request_id'])
    usage=validate_usage(reply['usage'])
    if (invoice.get('group')!='codex-deafult' or invoice['quota']>old['reserved']
            or invoice.get('prompt_tokens')!=usage['input_tokens']
            or invoice.get('completion_tokens')!=usage['output_tokens']):
        raise BudgetStop('saved response usage/group/reservation differs from supplier receipt')
    return account,invoice


def run(directory,pause_path):
    config=MigratedUsageConfig.from_dict(json.loads((directory/'config.gpt61.authorized.json').read_text()))
    with RunLock(directory):
        key,identifier,paths,bodies,finished=pending_binding(directory,pause_path)
        original_hashes={label:sha(p) for label,p in paths.items()}
        snapshot=directory/'pause_recovery'/str(time.time_ns());snapshot.mkdir(parents=True)
        for label,body in bodies.items():atomic_json(snapshot/('original_'+label+'.json'),body)
        atomic_json(snapshot/'Recovery_intent.json',{'inference_requests':0,'driver_sha256':sha(__file__),
            'pause_file':pause_path.name,'pause_sha256':sha(pause_path),'original_sha256':original_hashes,
            'key':key,'purpose':'finish pending lifecycle from exact saved reply; no failed-slot promotion'})
        flow=RegisteredUsageWorkflow(directory,config=config,dataset=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real'),project_root=ROOT)
        guard=SerialGuard(flow,flow.read('V22_binding.json','V22_binding'));guard.check()
        # Verify the other 18 settled sends independently before any network GET.
        ledger=deepcopy(bodies['budget']);ledger['records'].pop(key)
        prior=deepcopy(bodies['quota']);prior['records'].pop(key)
        verify_existing(directory,ledger,prior,config.provider.model)
        from fjsp_usage.research_real.leafapi import load_local_key
        if not os.environ.get(config.provider.api_key_env):os.environ[config.provider.api_key_env]=load_local_key(ORIGIN/'.env.leafapi.local')
        client=flow.client();quota=client.inner.inner
        if quota.data.get('stop_reason')!='uncertain interrupted request; no automatic continuation':
            raise BudgetStop('unexpected interruption gate; no blanket recovery')
        pacer=client.inner.query.metadata;pacer.interval=30;client.inner.query.interval=150
        client.inner.query.query=lambda:query_receipts(quota.transport.secret)
        balance=quota.balance();atomic_json(snapshot/'Fresh_quota.json',{'inference_requests':0,'quota':balance})
        invoices=client.inner.query();atomic_json(snapshot/'Fresh_invoices.json',invoices)
        account,invoice=closed_record(bodies['quota']['records'][key],finished,balance,invoices,bodies['billing'],bodies['wire']['reply'],config.provider.model)
        hold=quota.check_retained()
        if balance['total_used']+hold>config.platform_quota_ceiling or balance['total_available']<hold:
            raise BudgetStop('historical hold/account boundary prevents completion')
        guard.check()
        for label in ('budget','checkpoint','journal','billing','wire'):
            if sha(paths[label])!=original_hashes[label]:raise BudgetStop('source changed during saved-response settlement')
        if quota.data['records']!=bodies['quota']['records']:
            raise BudgetStop('request quota records changed during saved-response settlement')
        reply=bodies['wire']['reply'];elapsed=time.time()-account['started_at']
        metadata={**reply['metadata'],'billing_file':str(paths['billing']),
            'actual_platform_units':invoice['quota'],'billing_certified':True,
            'completed_from_original_saved_wire':True,'pause_recovery':str(snapshot),
            'request_elapsed_includes_user_pause':True}
        completed_bill={**bodies['billing'],'after':invoices,'original_quota_record':account,
            'wire_usage':reply['usage'],'transport_status':'completed','response_metadata':metadata,
            'status':'invoice_account_matched','invoice':invoice,'actual_platform_units':invoice['quota']}
        atomic_json(snapshot/'Completion_proof.json',{'inference_requests':0,'key':key,
            'account':account,'invoice':invoice,'original_sha256':original_hashes,
            'saved_wire_unchanged':True,'request_count_unchanged':len(flow.ledger.data['records'])})
        # Finish only previously pending lifecycle files; originals stay above.
        quota.data['records'][key]=account;quota.data.update(halted=False,stop_reason=None);quota.save()
        atomic_json(paths['billing'],completed_bill)
        flow.ledger.settle(key,status='completed',usage=reply['usage'],elapsed_seconds=elapsed)
        if flow.ledger.data['halted']:raise BudgetStop('saved response token reservation overrun; no search')
        journal=bodies['journal'];journal['requests'][identifier].update(status='completed',
            text=reply['text'],usage=reply['usage'],response_metadata=metadata,elapsed_seconds=elapsed)
        atomic_json(paths['journal'],journal)
        verify_existing(directory,flow.ledger.data,quota.data,config.provider.model)
        return {'status':'SAVED_REPLY_SETTLED_NO_NEW_INFERENCE','key':key,'actual_platform_points':invoice['quota'],
            'request_slots':len(flow.ledger.data['records']),'recovery_snapshot':str(snapshot)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--pause-file',required=True);args=parser.parse_args();directory=args.directory.resolve()
    if directory.parent!=ROOT/'runs' or Path(args.pause_file).name!=args.pause_file:raise SystemExit('own registered run/pause filename only')
    try:print(json.dumps(run(directory,directory/args.pause_file),ensure_ascii=False),flush=True)
    except BudgetStop as exc:print(json.dumps({'status':'STILL_BLOCKED','inference_requests':0,'reason':str(exc)},ensure_ascii=False),flush=True)
