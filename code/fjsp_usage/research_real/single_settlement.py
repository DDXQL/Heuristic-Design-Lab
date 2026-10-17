"""Exact metadata-stop recovery; no model calls and no failed-slot replay."""
import hashlib
import json
from pathlib import Path
import time
from fjsp_usage.research.events import atomic_json
from .budget import BudgetStop
from .single_billing import match_invoice, query_invoices
from .single_io import VERSION


def reconcile(flow,quota,*,query_fallback=query_invoices):
    """Reconcile only a specifically proved metadata-429 stop; never blanket clear."""
    if not quota.data['halted']:return None
    directory=flow.directory
    resolved={r['global_key'] for r in quota.data.get('invoice_reconciliations',[])}
    candidates=[]
    for path in (directory/'billing').glob('*.json'):
        audit=json.loads(path.read_text())
        if audit.get('status')=='settlement_not_certified' and audit['global_key'] not in resolved:
            candidates.append((path,audit))
    if not candidates and quota.data.get('stop_reason') in (
            'new-model pricing/list metadata unavailable',
            'before-dispatch supplier invoice metadata unavailable; no inference sent',
            'account quota unavailable/inconsistent; no retry'):
        tariff=quota.tariff_query(quota.transport.secret)
        quota.balance()
        after=quota.invoice_query()
        if after.get('success') is not True:raise BudgetStop('invoice endpoint still unavailable; no send')
        audit={'version':VERSION,'inference_requests':0,'previous_stop_reason':quota.data['stop_reason'],
            'tariff':tariff,'quota':quota.data['latest_quota'],'invoice_metadata':after,
            'unresolved_confirmed_sent_invoices':0,'historical_hold_unchanged':quota.check_retained()}
        path=directory/('Metadata_health_restored.'+str(int(time.time()*1000))+'.json')
        atomic_json(path,audit)
        quota.data.update(halted=False,stop_reason=None,latest_tariff_check=tariff)
        quota._tariff_at=quota.clock();quota.save()
        return audit
    if len(candidates)!=1:raise BudgetStop('exactly one unresolved native invoice required for metadata-stop recovery')
    invoice_path,original=candidates[0];key=original['global_key'];old=original['original_quota_record']
    reason=quota.data.get('stop_reason')
    permitted=('supplier billing metadata unavailable; no settlement inferred',
        'account quota unavailable/inconsistent; no retry','supplier invoice/account debit mismatch; preserve reservation')
    if (reason not in permitted or not old or not old.get('send_confirmed')
            or quota.data['records'].get(key)!=old or flow.ledger.data['halted']
            or any(r['status']=='pending' for r in quota.data['records'].values())
            or not (original.get('after',{}).get('http_status')==429 or
                quota.data.get('last_metadata_result',{}).get('http_status')==429)):
        raise BudgetStop('only proved metadata-429 failures may resume; protect all other gates')
    supplier_id=original.get('response_metadata',{}).get('gateway_request_id')
    if not supplier_id:raise BudgetStop('supplier request ID missing; cannot attribute settlement')
    quota.balance()  # fresh validated supplier GET, never cached historical balance
    after=getattr(quota,'invoice_query',lambda:query_fallback(quota.transport.secret))()
    name=hashlib.sha256(key.encode()).hexdigest()
    qpath=directory/('Settlement.'+name+'.quota.json');ipath=directory/('Settlement.'+name+'.invoices.json')
    if qpath.exists() or ipath.exists():raise BudgetStop('use a fresh evidence identity for repeated read-only investigation')
    q={'success':True,'inference_requests':0,'observed_at':quota.data['observed_at'],'quota':quota.data['latest_quota']}
    atomic_json(qpath,q);atomic_json(ipath,after)
    account={**old,'status':'settled','after_used':q['quota']['total_used'],
        'observed_account_delta':q['quota']['total_used']-old['before_used'],
        'finished_at':max(q['observed_at'],old['finished_at'])}
    invoice=match_invoice(original['before'],after,account,flow.config.provider.model,
        failed=True,response_id=supplier_id)
    usage=original['wire_usage']
    if (invoice.get('group')!='codex-deafult' or invoice['quota']>old['reserved']
            or (usage is not None and (invoice.get('prompt_tokens')!=usage['input_tokens'] or
                invoice.get('completion_tokens')!=usage['output_tokens']))
            or account['after_used']+quota.check_retained()>flow.config.platform_quota_ceiling):
        raise BudgetStop('restored invoice differs from wire/group or exceeds risk reserve/ceiling')
    folder=directory/'billing_reconciliations';folder.mkdir(exist_ok=True)
    target=folder/(name+'.json')
    proof={'version':VERSION,'global_key':key,'supplier_request_id':supplier_id,
        'original_quota_record':old,'original_billing_sha256':hashlib.sha256(invoice_path.read_bytes()).hexdigest(),
        'invoice':invoice,'reconciled_account':account,'actual_platform_units':invoice['quota'],
        'evidence_files_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (qpath,ipath)},
        'wire_usage':usage,'slot_remains_failed':True,'no_candidate_replay_or_reconstruction':True,
        'historical_24million_hold_unchanged':True,
        'new_unknown_cost_reservation_released_by_invoice_only':old['reserved']}
    if target.exists():raise BudgetStop('reconciliation proof identity already exists')
    atomic_json(target,proof)
    quota.data.setdefault('invoice_reconciliations',[]).append(proof)
    quota.data.update(halted=False,stop_reason=None);quota.save()
    print('精确结算恢复 '+key+'；actual_points='+str(invoice['quota'])+'；原失败槽位保留',flush=True)
    return proof
