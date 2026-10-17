#!/usr/bin/env python3
"""Close one failed-send fee from a unique invoice; no inference or token repair.

Financial unknown->known lifecycle only. Preserve the original billing/quota
snapshot, and leave the failed budget/journal/wire records byte-for-byte intact.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'code')]
from tools.resume_usage_metadata import (sha,verify_existing,MigratedUsageConfig,
    RegisteredUsageWorkflow,StagedDataset,SerialGuard,RunLock)
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.usage_v2.billing import match_invoice,certified_reconciliation


def close_fee(old,bill,wire,account,invoices,model):
    if (wire.get('status')!='wire_failed' or wire.get('error')!='TimeoutError'
            or wire.get('usage') is not None or bill.get('wire_usage') is not None
            or bill.get('transport_status')!='failed' or old.get('send_confirmed') is not True
            or old.get('status')!='settlement_unknown'):
        raise BudgetStop('not an unknown-wire, confirmed failed timeout')
    q=account['quota']; used=q['total_used']
    if (account.get('success') is not True or account.get('inference_requests')!=0
            or q['unlimited_quota'] is not False or q['total_used']+q['total_available']!=q['total_granted']):
        raise BudgetStop('fresh account proof invalid')
    closed={**old,'status':'settled','after_used':used,'observed_account_delta':used-old['before_used'],
        'settlement_verified_at':account['observed_at']}
    invoice=match_invoice(bill['before'],invoices,closed,model,failed=True,
        response_id=bill.get('response_metadata',{}).get('gateway_request_id'))
    duration=bill.get('response_metadata',{}).get('provider_roundtrip_seconds')
    if (type(duration) not in (int,float) or duration<=0 or invoice.get('group')!='codex-deafult'
            or invoice['quota']>old['reserved']
            or not old['started_at']-2<=invoice['created_at']<=old['started_at']+duration+30):
        raise BudgetStop('invoice exceeds original active request window/group/reservation')
    return closed,invoice


def run(directory,prefix,key):
    config=MigratedUsageConfig.from_dict(json.loads((directory/'config.gpt61.authorized.json').read_text()))
    with RunLock(directory):
        flow=RegisteredUsageWorkflow(directory,config=config,dataset=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real'),project_root=ROOT)
        guard=SerialGuard(flow,flow.read('V22_binding.json','V22_binding'));guard.check()
        quota_path=directory/'platform_quota.json';quota=json.loads(quota_path.read_text())
        name=hashlib.sha256(key.encode()).hexdigest()+'.json';bp=directory/'billing'/name;wp=directory/'wire_responses'/name
        bill=json.loads(bp.read_text());wire=json.loads(wp.read_text());row=flow.ledger.data['records'][key]
        jp=directory/'r301/B/budgeted_evolution_requests.json'
        health_paths=[directory/(prefix+'.'+n+'.json') for n in ('summary','account','invoices')]
        summary,account,invoices=[json.loads(p.read_text()) for p in health_paths]
        if (not quota['halted'] or quota.get('stop_reason')!='live new-model metadata unavailable; no fallback'
                or summary.get('status')!='READ_ONLY_HEALTH_CHECKED' or summary.get('inference_requests')!=0
                or summary.get('invoices_success') is not True or summary.get('tariff',{}).get('model')!=config.provider.model
                or quota.get('latest_quota')!=account['quota']
                or row['status']!='failed' or row.get('send_confirmed') is not True or row.get('usage') is not None
                or bill.get('status')!='settlement_not_certified' or bill.get('global_key')!=key
                or wire.get('global_key')!=key or bill.get('original_quota_record')!=quota['records'][key]
                or bill.get('after',{}).get('error_type')!='gaierror'):
            raise BudgetStop('specific DNS/timeout failure and live-health proof differ')
        original_quota=deepcopy(quota);original_bill=deepcopy(bill)
        prior=deepcopy(quota);prior['records'].pop(key)
        ledger=deepcopy(flow.ledger.data);ledger['records'].pop(key)
        verify_existing(directory,ledger,prior,config.provider.model)
        closed,invoice=close_fee(quota['records'][key],bill,wire,account,invoices,config.provider.model)
        history=guard.check()
        if account['quota']['total_used']+history['retained_account_hold']>config.platform_quota_ceiling:
            raise BudgetStop('account plus unchanged historical hold exceeds boundary')
        unchanged={str(p.relative_to(directory)):sha(p) for p in (directory/'budget.json',jp,wp)}
        snap=directory/'financial_recovery'/str(time.time_ns());snap.mkdir(parents=True)
        atomic_json(snap/'original_quota.json',original_quota);atomic_json(snap/'original_billing.json',original_bill)
        atomic_json(snap/'Completion_proof.json',{'inference_requests':0,'global_key':key,'driver_sha256':sha(__file__),
            'original_billing_sha256':sha(bp),'original_quota_sha256':sha(quota_path),
            'health_files_sha256':{p.name:sha(p) for p in health_paths},'unchanged_failed_files_sha256':unchanged,
            'closed_account_record':closed,'invoice':invoice,'historical_hold_unchanged':history['retained_account_hold'],
            'wire_usage_still_unknown':True,'failed_slot_unchanged':True})
        bill.update(status='invoice_account_matched',after=invoices,original_quota_record=closed,
            invoice=invoice,actual_platform_units=invoice['quota'],financial_recovery_snapshot=str(snap))
        reconciliation={'global_key':key,'original_quota_record':closed,'original_stop_reason':quota['stop_reason'],
            'invoice':invoice,'proof_file':bp.name,'wire_usage_still_unknown':True,'financial_recovery_snapshot':str(snap)}
        # Validate through the unchanged native certification path before writes.
        docs={directory.name+'/billing/'+bp.name:bill}
        certified_reconciliation(key,closed,[reconciliation],docs,directory.name,config.provider.model)
        quota['records'][key]=closed;quota.setdefault('invoice_reconciliations',[]).append(reconciliation)
        quota.update(halted=False,stop_reason=None,latest_tariff_check=summary['tariff'])
        atomic_json(bp,bill);atomic_json(quota_path,quota)
        for name,value in unchanged.items():
            if sha(directory/name)!=value:raise BudgetStop('failed request/journal/wire changed unexpectedly')
        verify_existing(directory,flow.ledger.data,quota,config.provider.model)
        return {'status':'UNIQUE_FAILED_SEND_FEE_CERTIFIED','inference_requests':0,'fee':invoice['quota'],
            'request_slots':len(flow.ledger.data['records']),'failed_slot_and_unknown_wire_usage_preserved':True,'snapshot':str(snap)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--health-prefix',required=True);p.add_argument('--key',required=True);a=p.parse_args();d=a.directory.resolve()
    if d.parent!=ROOT/'runs' or Path(a.health_prefix).name!=a.health_prefix:raise SystemExit('own run/health filename prefix only')
    try:print(json.dumps(run(d,a.health_prefix,a.key),ensure_ascii=False),flush=True)
    except BudgetStop as exc:print(json.dumps({'status':'STILL_BLOCKED','inference_requests':0,'reason':str(exc)},ensure_ascii=False),flush=True)
