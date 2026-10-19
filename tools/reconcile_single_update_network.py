#!/usr/bin/env python3
"""Bounded metadata-only proof for missing post-account snapshots in update v1.

No parser/search/prompt changes; never retries model requests. Genuine observed
account/invoice mismatches remain blocked. Original invoices/records stay intact.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.single_billing import match_invoice
from fjsp_usage.research_real.single_fair import read,file_sha
from fjsp_usage.research_real.single_update import VERSION
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.leafapi import KEY_ENV,load_local_key

REASON='supplier invoice/account debit mismatch; preserve reservation'
WIRE_ERROR='duplicate or premature stream usage'

def eligible(config,native,quota,key,bill,wire):
    old=bill.get('original_quota_record',{})
    if (config.conditional_research.get('version')!=VERSION or not config.real_requests_authorized
        or config.total_request_cap!=60 or config.seeds!=(201,)
        or not key.startswith(('r201/A/A/','r201/B/B/')) or len(native['records'])>60
        or not quota['halted'] or quota.get('stop_reason')!=REASON
        or bill.get('status')!='settlement_not_certified' or bill.get('settlement_error')!=REASON
        or bill.get('transport_status')!='failed' or bill.get('wire_usage') is not None
        or not old.get('send_confirmed') or old.get('status')!='settlement_unknown'
        or 'after_used' in old or 'observed_account_delta' in old
        or quota['records'].get(key)!=old or native['records'][key].get('status')!='failed'
        or not native['records'][key].get('send_confirmed') or native['records'][key].get('usage') is not None
        or wire.get('error')!=WIRE_ERROR or wire.get('status')!='wire_failed'
        or wire.get('global_key')!=key or not wire.get('send_confirmed')
        or not bill.get('response_metadata',{}).get('gateway_request_id')
        or any(r['status']=='pending' for r in quota['records'].values())):
        raise BudgetStop('not the bounded missing-post-account case; original protections remain')
    return old

def prove(config,native,quota,key,bill,wire,fresh,after,*,retained,now=None):
    old=eligible(config,native,quota,key,bill,wire);now=time.time() if now is None else now
    q=fresh['quota'];at=fresh['observed_at']
    if (not fresh.get('success') or not 0<=now-at<=180 or not q.get('available')
        or q.get('unlimited_quota') is not False or q.get('allowed_by_explicit_token_limit') is False
        or any(type(q.get(k)) is not int or q[k]<0 for k in ('total_used','total_available','total_granted'))
        or q['total_used']+q['total_available']!=q['total_granted']
        or type(q.get('expires_at')) is not int or (q['expires_at'] and q['expires_at']<=now)
        or retained!=config.conditional_research['history_binding']['retained_account_hold']
        or retained!=24000000 or q['total_used']<quota.get('observed_used',0)
        or q['total_used']+retained>config.platform_quota_ceiling):
        raise BudgetStop('fresh account/history/ceiling evidence rejected')
    account={**old,'status':'settled','after_used':q['total_used'],
        'observed_account_delta':q['total_used']-old['before_used'],
        'finished_at':max(at,old['finished_at'])}
    invoice=match_invoice(bill['before'],after,account,config.provider.model,failed=True,
        response_id=bill['response_metadata']['gateway_request_id'])
    if (invoice.get('group')!=config.conditional_research['risk_policy']['group']
        or not 0<invoice['quota']<=old['reserved']):
        raise BudgetStop('positive exact fee/group/risk evidence required')
    return account,invoice

def load_flow(directory):
    spec=importlib.util.spec_from_file_location('update_entry',ROOT/'experiments/tier2/research_real_v1/run_single_update.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module,module.load_flow(directory)

def one_case(flow,quota):
    resolved={r['global_key'] for r in quota.data.get('invoice_reconciliations',[])}
    rows=[]
    for path in (flow.directory/'billing').glob('*.json'):
        bill=read(path)
        if bill.get('status')=='settlement_not_certified' and bill['global_key'] not in resolved:rows.append((path,bill))
    if len(rows)!=1:raise BudgetStop('one unresolved native invoice required')
    path,bill=rows[0];key=bill['global_key'];wirepath=flow.directory/'wire_responses'/path.name
    wire=read(wirepath);eligible(flow.config,flow.ledger.data,quota.data,key,bill,wire)
    return path,bill,key,wirepath,wire

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('stage',choices=['inspect','apply'])
    ap.add_argument('--run-dir',type=Path,required=True);ap.add_argument('--env-file',type=Path)
    ap.add_argument('--evidence',type=Path);args=ap.parse_args();p=args.run_dir.resolve()
    if p!=ROOT/'runs/single-ID-update-frequency-seed201-v1-20261018':ap.error('current registered update trial only')
    with RunLock(p):
        module,flow=load_flow(p);flow.check()
        if args.stage=='inspect':
            if not args.env_file:ap.error('--env-file needed for paced metadata only')
            os.environ[KEY_ENV]=load_local_key(args.env_file)
        if args.stage=='inspect':quota=flow.client().inner.quota
        else:
            from fjsp_usage.research_real.quota_guard import QuotaGuardedTransport
            h=flow.config.conditional_research['history_binding']
            quota=QuotaGuardedTransport(SimpleNamespace(config=flow.config,identity='OFFLINE_PROOF_ONLY',redact=str),
                p/'platform_quota.json',flow.context,retained_extra=h['retained_account_hold'],
                settlement_min_used=h['latest_saved_account_used'])
        path,bill,key,wirepath,wire=one_case(flow,quota)
        if args.stage=='inspect':
            quota.balance();after=quota.invoice_query()
            prefix='Network_settlement.'+str(time.time_ns())
            qp=p/(prefix+'.quota.json');ip=p/(prefix+'.invoices.json');ep=p/(prefix+'.evidence.json')
            fresh={'success':True,'observed_at':quota.data['observed_at'],'quota':quota.data['latest_quota'],'inference_requests':0}
            atomic_json(qp,fresh);atomic_json(ip,after)
            account,invoice=prove(flow.config,flow.ledger.data,quota.data,key,bill,wire,fresh,after,retained=quota.check_retained())
            atomic_json(ep,{'version':'update-network-snapshot-proof-v1','global_key':key,
                'protocol_sha256':file_sha(p/'protocol.json'),'adapter_sha256':file_sha(Path(__file__)),'bill_sha256':file_sha(path),
                'wire_sha256':file_sha(wirepath),'evidence_files_sha256':{f.name:file_sha(f) for f in (qp,ip)},
                'quota_file':qp.name,'invoice_file':ip.name,'invoice':invoice,'reconciled_account':account,
                'no_model_requests':True,'gate_still_halted':quota.data['halted']})
            print('exact read-only settlement proof: '+str(ep),flush=True);return
        ep=args.evidence.resolve() if args.evidence else None
        if ep is None or ep.parent!=p:ap.error('--evidence must be this run direct child')
        e=read(ep)
        if (e['global_key']!=key or e['protocol_sha256']!=file_sha(p/'protocol.json')
            or e['adapter_sha256']!=file_sha(Path(__file__))
            or e['bill_sha256']!=file_sha(path) or e['wire_sha256']!=file_sha(wirepath)):
            raise BudgetStop('proof identity changed')
        for n,h in e['evidence_files_sha256'].items():
            if Path(n).name!=n or file_sha(p/n)!=h:raise BudgetStop('evidence changed or escaped')
        account,invoice=prove(flow.config,flow.ledger.data,quota.data,key,bill,wire,read(p/e['quota_file']),read(p/e['invoice_file']),retained=quota.check_retained())
        if account!=e['reconciled_account'] or invoice!=e['invoice']:raise BudgetStop('proof recomputation differs')
        proof={'version':'update-network-snapshot-proof-v1','global_key':key,
            'supplier_request_id':bill['response_metadata']['gateway_request_id'],
            'original_quota_record':deepcopy(bill['original_quota_record']),'original_billing_sha256':file_sha(path),
            'invoice':invoice,'reconciled_account':account,'actual_platform_units':invoice['quota'],
            'evidence_files_sha256':e['evidence_files_sha256'],'wire_usage':None,
            'slot_remains_failed':True,'no_candidate_replay_or_reconstruction':True,
            'historical_24million_hold_unchanged':True,'new_unknown_cost_reservation_released_by_invoice_only':account['reserved'],
            'adapter_sha256':file_sha(Path(__file__)),'limited_recovery':'missing post-account snapshot only; observed debit mismatches and old runs rejected'}
        target=p/'billing_reconciliations'/path.name
        if target.exists():raise BudgetStop('proof already exists; no overwrite')
        atomic_json(target,proof);quota.data.setdefault('invoice_reconciliations',[]).append(proof)
        quota.data.update(halted=False,stop_reason=None);quota.save();module.report(flow)
        print('exact fee '+str(invoice['quota'])+'; failed slot/unknown wire/old holds retained; no inference',flush=True)

if __name__=='__main__':main()
