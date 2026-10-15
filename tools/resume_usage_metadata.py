#!/usr/bin/env python3
"""Same registered batch, read-only metadata recovery; never retry a sent key.

This execution amendment is outside the frozen algorithm fingerprint. It only
restores a proved before-dispatch metadata pause and continues the existing
search checkpoint. Original terminal status and request evidence stay intact.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'code')]
from experiments.tier2.usage_v2.run_registered_gpt61_v22 import (
    ORIGIN, MigratedUsageConfig, RegisteredUsageWorkflow, SerialGuard,
    StagedDataset, RunLock)
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.usage_v2.billing import match_invoice, certified_reconciliation
from fjsp_usage.usage_v2 import VERSION

REASON = 'before-dispatch supplier invoice metadata unavailable; no inference sent'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_existing(directory, ledger, quota, model):
    """All prior sends must have independently matched, unchanged receipts."""
    records = ledger['records']
    if ledger['halted'] or set(records) != set(quota['records']):
        raise BudgetStop('unresolved/mismatched original request ledger')
    proofs, ids = {}, set()
    for key, row in records.items():
        account = quota['records'][key]
        path = directory / 'billing' / (hashlib.sha256(key.encode()).hexdigest() + '.json')
        bill = json.loads(path.read_text())
        if (row.get('send_confirmed') is not True or account.get('send_confirmed') is not True
                or row.get('status') not in ('completed', 'failed')
                or bill.get('global_key') != key
                or bill.get('original_quota_record') != account
                or bill.get('wire_usage') != row.get('usage')):
            raise BudgetStop('prior request not fully certified; metadata recovery forbidden')
        if bill.get('status') == 'settlement_not_certified':
            amendments=[x for x in quota.get('invoice_reconciliations',[]) if x.get('global_key')==key]
            if len(amendments)!=1 or row['status']!='failed':
                raise BudgetStop('prior unresolved failed settlement')
            proof=amendments[0];proof_path=directory/'billing_reconciliations'/path.name
            if json.loads(proof_path.read_text())!=proof:raise BudgetStop('saved supplemental proof differs')
            files=[path,proof_path]
            for name in proof.get('evidence_files_sha256',{}):
                if Path(name).name!=name:raise BudgetStop('supplemental evidence path differs')
                files.append(directory/name)
            docs={directory.name+'/'+str(p.relative_to(directory)):json.loads(p.read_text()) for p in files}
            hashes={directory.name+'/'+str(p.relative_to(directory)):sha(p) for p in files}
            invoice=certified_reconciliation(key,account,amendments,docs,directory.name,model,hashes)
            if invoice is None or invoice['request_id'] in ids:raise BudgetStop('unproved/duplicate supplier receipt')
            ids.add(invoice['request_id']);proofs.update({str(p.relative_to(directory)):sha(p) for p in files})
            continue
        if account.get('status')!='settled' or bill.get('status')!='invoice_account_matched':
            raise BudgetStop('prior request not settled')
        invoice = match_invoice(bill['before'], bill['after'], account, model,
            failed=bill['transport_status'] == 'failed',
            response_id=bill.get('response_metadata', {}).get('gateway_request_id'))
        if (invoice != bill.get('invoice') or invoice['quota'] != bill.get('actual_platform_units')
                or invoice['quota'] > account['reserved'] or invoice['request_id'] in ids):
            raise BudgetStop('prior invoice amount, identity or reservation differs')
        ids.add(invoice['request_id']); proofs[str(path.relative_to(directory))] = sha(path)
    return proofs


def restore_metadata(flow, client, guard, *, driver_sha):
    quota = client.inner.inner
    if not quota.data['halted']:
        return None
    if quota.data.get('stop_reason') != REASON:
        raise BudgetStop('only proved before-dispatch invoice metadata pause can resume here')
    guard.check()
    proofs = verify_existing(flow.directory, flow.ledger.data, quota.data, flow.config.provider.model)
    original = deepcopy(quota.data)
    # Persist successful and failed health probes; no inference is made here.
    path = flow.directory / ('Metadata_health_restored.' + str(time.time_ns()) + '.json')
    audit = {'version': 'usage-v22-metadata-recovery-v1', 'inference_requests': 0,
        'driver_sha256': driver_sha, 'previous_quota': original,
        'ledger_sha256': sha(flow.directory / 'budget.json'), 'receipt_files_sha256': proofs,
        'historical_hold_unchanged': quota.check_retained(), 'status': 'checking'}
    atomic_json(path, audit)
    try:
        audit['tariff'] = quota.tariff_query(quota.transport.secret)
        audit['account'] = quota.balance()
        audit['invoices'] = client.inner.query()
        if audit['invoices'].get('success') is not True:
            raise BudgetStop('read-only invoice health still unavailable; no inference sent')
        guard.check()
        if sha(flow.directory / 'budget.json') != audit['ledger_sha256']:
            raise BudgetStop('request ledger changed during read-only recovery')
        if (quota.data['records'] != original['records']
                or quota.data.get('invoice_reconciliations') != original.get('invoice_reconciliations')
                or quota.check_retained() != audit['historical_hold_unchanged']):
            raise BudgetStop('historical request/reservation changed during recovery')
        # The original preflight enforces available quota + retained hold +
        # next-request reservation before any ledger slot can be reserved.
        audit['status'] = 'metadata_restored_no_inference'
        atomic_json(path, audit)
        quota.data.update(halted=False, stop_reason=None, latest_tariff_check=audit['tariff'])
        quota.data.setdefault('metadata_recovery_proofs', []).append(path.name)
        quota._tariff_at = quota.clock(); quota.save()
    except Exception as exc:
        audit.update(status='still_blocked_no_inference', error_type=type(exc).__name__)
        atomic_json(path, audit)
        raise
    return path


def initialize_existing(flow):
    seed = 301; name = 'r301/Shared_initial.json'
    if (flow.directory / name).exists():
        return flow.initialize_u(seed)
    old = flow.read('r301/Initialization_status.json', 'Initialization_status')
    if old['status'] != 'initialization_budget_stopped':
        raise BudgetStop('ordinary initialization failure is terminal; no refill')
    H, members = flow.h_asset()
    if old['H_hash'] != H['artifact_sha256'] or old['seed'] != seed:
        raise BudgetStop('original initialization binding changed')
    checkpoint = json.loads((flow.directory / 'r301/INIT/checkpoint.json').read_text())
    if checkpoint['phase'] != 'initialization':
        raise BudgetStop('only an interrupted initialization can continue')
    engine = flow.search_engine('r301/INIT', 'INIT', members, flow.config.u_search(seed), 'r301/init', 'r301/A')
    valid = engine.initialize()  # Existing cursor, inflight prompt, RNG and caps.
    if not valid:
        flow.write('r301/Initialization_resumed_status.json', 'Initialization_status',
            seed=seed, status='initialization_failed', H_hash=H['artifact_sha256'], search_report=engine.report())
        return {'status': 'initialization_failed', 'asset': None}
    rows = engine.export_rows()
    if any(x['member_usage']['MIX_steps'] for row in rows for x in row['training_result']['instances']):
        raise BudgetStop('shared initialization must remain SELECT only')
    asset = flow.write(name, 'Shared_initial', seed=seed, H_hash=H['artifact_sha256'],
        training_files=list(flow.dataset.names['train']), population=rows,
        u_interface_version=VERSION, allowed_modes=[0])
    flow.progress('USAGE_SHARED_SELECT_INITIALIZED', seed=seed)
    return {'status': 'initialized', 'asset': asset}


def run(directory):
    driver_sha = sha(__file__)
    config = MigratedUsageConfig.from_dict(json.loads((directory / 'config.gpt61.authorized.json').read_text()))
    dataset = StagedDataset(ROOT / 'data/fjsp_manifest.json', project_root=ROOT, mode='real')
    with RunLock(directory):
        flow = RegisteredUsageWorkflow(directory, config=config, dataset=dataset, project_root=ROOT)
        guard = SerialGuard(flow, flow.read('V22_binding.json', 'V22_binding')); guard.check()
        if not os.environ.get(config.provider.api_key_env):
            from fjsp_usage.research_real.leafapi import load_local_key
            os.environ[config.provider.api_key_env] = load_local_key(ORIGIN / '.env.leafapi.local')
        client = flow.client()
        # Observed account/log HTTP429 after the original 15/75 second pacing.
        # Engineering throttle only; inference parameters and caps stay frozen.
        client.inner.query.metadata.interval = 30
        client.inner.query.interval = 150
        original_check = client.guard.check
        def check():
            if sha(__file__) != driver_sha: raise BudgetStop('recovery driver changed while active')
            return original_check()
        client.guard.check = check
        pins = {n: sha(directory / n) for n in ('protocol.json', 'config.gpt61.authorized.json',
            'budget.json', 'r301/Initialization_status.json', 'r301/INIT/checkpoint.json')}
        atomic_json(directory / ('Execution_resume.' + str(time.time_ns()) + '.json'), {
            'driver_sha256': driver_sha, 'original_files_sha256': pins,
            'purpose': 'same checkpoint after before-dispatch metadata recovery; no algorithm or protocol changes',
            'request_slots_before': len(flow.ledger.data['records']), 'inference_retries': 0,
            'metadata_interval_seconds': 30, 'invoice_interval_seconds': 150})
        try:
            restore_metadata(flow, client, guard, driver_sha=driver_sha)
            if initialize_existing(flow)['status'] == 'initialized':
                statuses = []
                for arm in ('A', 'B'):
                    statuses.append(flow.search_arm(301, arm)['status'])
                    if statuses[-1] != 'completed': break
                if statuses == ['completed', 'completed']: flow.search_all()
        except BudgetStop as exc:
            flow.progress('RESUMED_USAGE_BUDGET_STOP', reason=str(exc))
        flow.training_report()
        from fjsp_usage.usage_v2.training_export import export_results
        report = export_results(flow)
        return {k: report[k] for k in ('status', 'request_slots', 'known_input_tokens', 'known_output_tokens')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args(); directory = args.directory.resolve()
    if directory.parent != ROOT / 'runs': raise SystemExit('registered own runs directory only')
    print(json.dumps(run(directory), ensure_ascii=False), flush=True)
