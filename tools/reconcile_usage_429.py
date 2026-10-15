#!/usr/bin/env python3
"""Read-only investigation of one saved HTTP429 settlement; no inference."""
import argparse
from copy import deepcopy
import http.client
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'code')]
from tools.resume_usage_metadata import (sha, verify_existing, ORIGIN,
    MigratedUsageConfig, RegisteredUsageWorkflow, StagedDataset, SerialGuard, RunLock)
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.usage_v2.billing import match_invoice, certified_amendment

# Reuse the already verified supplemental-receipt schema, whose historical
# version name is from the single-ID implementation. This is a usage-v2 run;
# schema compatibility does not change its research identity or original data.
SCHEMA = 'single-ID-nonsemantic-recording-settlement-amendment-v1-20261014'


def query_receipts(secret):
    result = {'success': False, 'inference_requests': 0, 'metadata_requests': 1,
        'records': [], 'observed_at': time.time(), 'path': '/api/log/token'}
    connection = http.client.HTTPSConnection('leafapi.cc', timeout=15)
    try:
        connection.request('GET', '/api/log/token', headers={'Authorization': 'Bearer '+secret, 'Accept': 'application/json'})
        response = connection.getresponse(); raw = response.read(524289)
        result.update(http_status=response.status, retry_after=response.getheader('Retry-After'))
        if response.status != 200 or len(raw)>524288: return result
        body=json.loads(raw); rows=body.get('data', [])
        if isinstance(rows,dict): rows=rows.get('items',rows.get('data',rows.get('logs',[])))
        if body.get('success',body.get('code')) is not True or not isinstance(rows,list): return result
        fields=('id','created_at','type','model_name','quota','prompt_tokens','completion_tokens','use_time','request_id','group')
        for row in rows:
            if not isinstance(row,dict): raise ValueError('invalid receipt')
            result['records'].append({k:(v.replace(secret,'[REDACTED]') if isinstance(v,str) else v)
                for k,v in row.items() if k in fields and type(v) in (str,int,float,bool)})
        result['success']=True
    except (ValueError,OSError) as exc: result['error_type']=type(exc).__name__
    finally: connection.close()
    return result


def build_proof(directory, original_path, original, account, invoices, quota_path, invoices_path, model):
    old=original['original_quota_record']; key=original['global_key']
    reconciled={**old,'status':'settled','after_used':account['quota']['total_used'],
        'observed_account_delta':account['quota']['total_used']-old['before_used'],
        'finished_at':max(account['observed_at'],old['finished_at'])}
    identifier=original.get('response_metadata',{}).get('gateway_request_id')
    if not identifier: raise BudgetStop('missing supplier identity; no settlement attribution')
    invoice=match_invoice(original['before'],invoices,reconciled,model,failed=True,response_id=identifier)
    proof={'version':SCHEMA,'research_run':directory.name,'global_key':key,'supplier_request_id':identifier,
        'original_quota_record':old,'original_billing_sha256':sha(original_path),'invoice':invoice,
        'reconciled_account':reconciled,'actual_platform_units':invoice['quota'],
        'wire_usage':original['wire_usage'],'slot_remains_failed':True,'no_candidate_replay_or_reconstruction':True,
        'historical_hold_unchanged':True,'driver_sha256':sha(__file__),
        'evidence_files_sha256':{p.name:sha(p) for p in (quota_path,invoices_path)}}
    target=directory/'billing_reconciliations'/(original_path.name)
    docs={directory.name+'/'+str(p.relative_to(directory)):body for p,body in
        ((original_path,original),(quota_path,account),(invoices_path,invoices),(target,proof))}
    hashes={directory.name+'/'+str(p.relative_to(directory)):sha(p) for p in (original_path,quota_path,invoices_path)}
    certified_amendment(key,old,proof,docs,directory.name,model,hashes)
    return target,proof


def run(directory):
    config=MigratedUsageConfig.from_dict(json.loads((directory/'config.gpt61.authorized.json').read_text()))
    with RunLock(directory):
        flow=RegisteredUsageWorkflow(directory,config=config,dataset=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real'),project_root=ROOT)
        guard=SerialGuard(flow,flow.read('V22_binding.json','V22_binding'));guard.check()
        from fjsp_usage.research_real.leafapi import load_local_key
        if not os.environ.get(config.provider.api_key_env): os.environ[config.provider.api_key_env]=load_local_key(ORIGIN/'.env.leafapi.local')
        client=flow.client();quota=client.inner.inner
        resolved={x['global_key'] for x in quota.data.get('invoice_reconciliations',[])}
        pending=[(p,json.loads(p.read_text())) for p in (directory/'billing').glob('*.json')]
        pending=[(p,b) for p,b in pending if b.get('status')=='settlement_not_certified' and b['global_key'] not in resolved]
        reasons=('supplier billing metadata unavailable; no settlement inferred','account quota unavailable/inconsistent; no retry')
        if len(pending)!=1 or not quota.data['halted'] or quota.data.get('stop_reason') not in reasons:
            raise BudgetStop('not exactly one unresolved metadata-429 settlement')
        path,bill=pending[0];key=bill['global_key'];old=bill['original_quota_record']
        row=flow.ledger.data['records'][key]
        if (bill.get('after',{}).get('http_status')!=429 or old!=quota.data['records'][key]
                or old.get('send_confirmed') is not True or row['status']!='failed'
                or row.get('usage')!=bill['wire_usage'] or not row.get('send_confirmed')):
            raise BudgetStop('original sent failure/HTTP429 evidence differs')
        # Independently certify all OTHER requests as well.
        ledger=deepcopy(flow.ledger.data);ledger['records'].pop(key)
        q=deepcopy(quota.data);q['records'].pop(key)
        verify_existing(directory,ledger,q,config.provider.model)
        budget_sha=sha(directory/'budget.json');original_sha=sha(path);original_quota=deepcopy(quota.data['records'])
        hold=quota.check_retained();pacer=client.inner.query.metadata;pacer.interval=30
        client.inner.query.interval=150
        client.inner.query.query=lambda:query_receipts(quota.transport.secret)
        prefix='Settlement.'+str(time.time_ns());qp=directory/(prefix+'.quota.json');ip=directory/(prefix+'.invoices.json')
        balance=quota.balance()
        account={'success':True,'inference_requests':0,'observed_at':quota.data['observed_at'],'quota':balance}
        atomic_json(qp,account);invoices=client.inner.query();atomic_json(ip,invoices)
        target,proof=build_proof(directory,path,bill,account,invoices,qp,ip,config.provider.model)
        guard.check()
        if (sha(directory/'budget.json')!=budget_sha or sha(path)!=original_sha or quota.data['records']!=original_quota
                or quota.check_retained()!=hold or balance['total_used']+hold>config.platform_quota_ceiling):
            raise BudgetStop('original ledger, historical hold or account boundary changed')
        if target.exists():raise BudgetStop('supplemental proof already exists')
        atomic_json(target,proof)
        quota.data.setdefault('invoice_reconciliations',[]).append(proof)
        quota.data.update(halted=False,stop_reason=None);quota.save()
        return {'status':'EXACT_RECEIPT_CERTIFIED','inference_requests':0,'failed_slot_preserved':key,
            'actual_platform_points':proof['actual_platform_units'],'proof':str(target)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    directory=parser.parse_args().directory.resolve()
    if directory.parent!=ROOT/'runs':raise SystemExit('own registered run only')
    try: print(json.dumps(run(directory),ensure_ascii=False),flush=True)
    except BudgetStop as exc: print(json.dumps({'status':'STILL_BLOCKED','inference_requests':0,'reason':str(exc)},ensure_ascii=False),flush=True)
