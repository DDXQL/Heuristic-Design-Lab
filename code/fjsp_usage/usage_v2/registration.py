"""Serial v2.2 registration. Historical copies are evidence, not new sends.

The declared history counts the 79 ancestral slots once. The peer's new ledger
is appended only after a terminal, settled batch. Inventory hashes detect
foreign changes; summing all historical ledger copies would double-count
continuation snapshots and is deliberately not used as a lifetime counter.
"""
import hashlib
import json
from pathlib import Path
import subprocess

from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_seal
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.conditional_research import history_summary, dispatch_check
from fjsp_usage.research_real.quota_guard import QuotaGuardedTransport
from fjsp_usage.research_real.real_transport import JsonCandidateTransport
from .workflow import UsageWorkflow
from .billing import InvoiceTransport, certified_reconciliation, match_invoice

VERSION = 'registered-v22-serial-train-20261013'


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def worktree_roots(root):
    data = subprocess.check_output(['git', '-C', str(root), 'worktree', 'list', '--porcelain'], text=True)
    return [Path(line[9:]) for line in data.splitlines() if line.startswith('worktree ')]


def inventory(roots, exclude=None):
    exclude = Path(exclude).resolve() if exclude else None
    found = {}
    for root in roots:
        for lock in (Path(root) / 'runs').rglob('.writer.lock'):
            if lock.parent.resolve() != exclude:
                raise BudgetStop('another worktree run has a writer lock: ' + str(lock))
        for path in sorted((Path(root) / 'runs').glob('*/budget.json')):
            if path.parent.resolve() == exclude:
                continue
            body = json.loads(path.read_text())
            if body.get('mode') != 'real' or not body.get('records'):
                continue
            identity, sha = body['identity'], file_hash(path)
            if identity in found and found[identity] != sha:
                raise BudgetStop('divergent copies of one ledger identity')
            found[identity] = sha
    return found


def peer_terminal_audit(peer_root, *, model=None):
    """No lock or interrupted chat is evidence of completion by itself."""
    peer_root = Path(peer_root)
    locks = list((peer_root / 'runs').rglob('.writer.lock'))
    if locks:
        raise BudgetStop('WAIT_PEER_WRITER_LOCK')
    runs = []
    for path in (peer_root / 'runs').glob('*/protocol.json'):
        body = json.loads(path.read_text()); config = body.get('config', {})
        if (config.get('real_requests_authorized') is True and config.get('seeds') == [201]
                and config.get('total_request_cap') in ((60, 61) if model else (60,))
                and config.get('purpose') == 'research'
                and (model is None or config.get('provider', {}).get('model') == model)):
            runs.append((path.parent, body))
    if len(runs) != 1:
        raise BudgetStop('WAIT_SINGLE_PEER_REGISTERED_TERMINAL_BATCH: expected exactly one authorized seed201/cap60 batch')
    directory, protocol = runs[0]
    context = digest(protocol)
    gate_path = directory / ('Search_complete_resumed.json' if (directory / 'Final_budget_handoff.json').exists()
                              else 'Search_complete.json')
    init_path = directory / 'r201/Initialization_status.json'
    if gate_path.exists():
        gate = check_seal(json.loads(gate_path.read_text()), kind='Search_complete', mode='real', context=context)
        entries = gate.get('entries', [])
        if ([(r['seed'], r['arm']) for r in entries] != [(201, a) for a in ('B0', 'B1', 'B2', 'P')]
                or any(r['status'] not in ('completed', 'initialization_failed', 'initialization_budget_stopped', 'budget_stopped') for r in entries)):
            raise BudgetStop('peer terminal group evidence incomplete')
        terminal = {r['arm']: r['status'] for r in entries}
    elif init_path.exists():
        status = check_seal(json.loads(init_path.read_text()), kind='Initialization_status', mode='real', context=context)
        if status.get('status') not in ('initialization_failed', 'initialization_budget_stopped'):
            raise BudgetStop('WAIT_PEER_TERMINAL_OR_EXPLICIT_STOP')
        terminal = {'INIT': status['status']}
    else:
        raise BudgetStop('WAIT_PEER_TERMINAL_OR_EXPLICIT_STOP')
    budget_path = directory / 'budget.json'; budget = json.loads(budget_path.read_text())
    identity = digest({'config': protocol['config'], 'context': context})
    if budget.get('identity') != identity or budget.get('halted'):
        raise BudgetStop('peer ledger identity/overrun gate unresolved')
    if any(r['status'] not in ('completed', 'failed', 'interrupted') for r in budget['records'].values()):
        raise BudgetStop('peer reservation remains pending')
    quota_path = directory / 'platform_quota.json'
    quota = json.loads(quota_path.read_text()) if quota_path.exists() else {'records': {}}
    if budget['records'] and (quota.get('identity') != identity or quota.get('halted')):
        raise BudgetStop('peer account settlement halt unresolved: ' + str(quota.get('stop_reason', 'identity mismatch')))
    final_costs = audit_final_handoff(directory, budget, quota, model) if (directory / 'Final_budget_handoff.json').exists() else None
    for key, record in (() if final_costs is not None else budget['records'].items()):
        q = quota['records'].get(key)
        if record.get('send_confirmed') and (not q or q.get('status') != 'settled'):
            raise BudgetStop('peer sent request has unresolved usage/account settlement')
        if record.get('send_confirmed') and record.get('usage') is None:
            proofs = {directory.name + '/billing/' + p.name: json.loads(p.read_text())
                for p in (directory / 'billing').glob('*.json')}
            if not certified_reconciliation(key, q, quota.get('invoice_reconciliations', []), proofs,
                    directory.name, protocol['config']['provider']['model']):
                raise BudgetStop('peer sent request has unresolved usage/account settlement')
    pins = {str(p.relative_to(peer_root / 'runs')): file_hash(p)
        for p in directory.rglob('*') if p.is_file()}
    result = {'run_name': directory.name, 'root': str(peer_root.resolve()), 'context': context,
        'ledger_identity': identity, 'request_slots': len(budget['records']),
        'confirmed_sends': sum(r.get('send_confirmed', False) for r in budget['records'].values()),
        'observed_used': quota.get('observed_used', 0), 'terminal': terminal, 'files_sha256': pins}
    if final_costs is not None: result['final_costs'] = final_costs
    return result


def audit_final_handoff(directory, budget, quota, model):
    """Count each raw request and verify its evidence, never trust a fee total."""
    directory = Path(directory); run = directory.name
    docs = {run + '/' + str(p.relative_to(directory)): json.loads(p.read_text())
            for p in directory.rglob('*.json')}
    hashes = {run + '/' + str(p.relative_to(directory)): file_hash(p)
              for p in directory.rglob('*.json')}
    handoff = docs[run + '/Final_budget_handoff.json']
    if (handoff.get('real_caller_active') is not False or handoff.get('budget_identity') != budget['identity']
            or handoff.get('budget_sha256') != file_hash(directory / 'budget.json')
            or handoff.get('quota_halted') is not False or quota.get('halted')
            or handoff.get('registered_generation_phases_complete') is not True):
        raise BudgetStop('final peer handoff not released/bound/complete')
    journals = {row['global_key']: row for body in docs.values() if isinstance(body, dict)
                and isinstance(body.get('requests'), dict) for row in body['requests'].values()
                if isinstance(row, dict) and 'global_key' in row}
    rows = []; suppliers = set()
    for key, record in budget['records'].items():
        name = hashlib.sha256(key.encode()).hexdigest()
        bill = docs.get(run + '/billing/' + name + '.json', {})
        q = quota['records'].get(key)
        if not record.get('send_confirmed'):
            journal = journals.get(key, {})
            if (record.get('status') != 'failed' or q is not None or bill.get('status') != 'before_dispatch'
                    or bill.get('before', {}).get('success') is True
                    or journal.get('error') != 'cannot inspect supplier billing before dispatch'
                    or run + '/wire_responses/' + name + '.json' in docs):
                raise BudgetStop('unconfirmed peer send is not proved unsent')
            rows.append({'key': key, 'state': 'proved_unsent', 'points': None}); continue
        if not q:
            raise BudgetStop('sent peer request missing original account record')
        amendments = quota.get('invoice_reconciliations', [])
        if any(r.get('global_key') == key for r in amendments):
            invoice = certified_reconciliation(key, q, amendments, docs, run, model, hashes)
        else:
            if (bill.get('status') != 'invoice_account_matched' or q.get('status') != 'settled'
                    or bill.get('original_quota_record') != q or bill.get('wire_usage') != record.get('usage')):
                raise BudgetStop('peer request settlement not independently certified: ' + key)
            invoice = match_invoice(bill['before'], bill['after'], q, model,
                failed=bill.get('transport_status') == 'failed',
                response_id=bill.get('response_metadata', {}).get('gateway_request_id'))
            if bill.get('invoice') != invoice or bill.get('actual_platform_units') != invoice['quota']:
                raise BudgetStop('peer original invoice differs')
        if not invoice or invoice['request_id'] in suppliers or invoice['quota'] > q['reserved']:
            raise BudgetStop('peer invoice missing/reused/above reservation')
        suppliers.add(invoice['request_id'])
        rows.append({'key': key, 'state': 'sent_settled', 'points': invoice['quota'],
                     'wire_usage_unknown': record.get('usage') is None})
    amount = sum(r['points'] for r in rows if r['points'] is not None)
    sent = sum(r['state'] == 'sent_settled' for r in rows)
    if (handoff.get('known_new_points') != amount or handoff.get('unknown_new_fee_keys') != []
            or handoff.get('unknown_new_fee_holds') != 0
            or handoff.get('latest_verified_used_points') != quota.get('observed_used')
            or handoff.get('old_account_hold') != 24000000
            or handoff.get('summary', {}).get('request_slots') != len(rows)
            or handoff.get('summary', {}).get('confirmed_sends') != sent):
        raise BudgetStop('final handoff summary differs from verified request evidence')
    return {'actual_points': amount, 'confirmed_sends': sent, 'proved_unsent': len(rows)-sent,
            'request_slots': len(rows), 'old_hold_preserved': 24000000, 'rows': rows}


def verify_source_group(local_root, source_root, pins):
    for name, sha in pins.items():
        for root in (Path(local_root), Path(source_root)):
            path = root / 'runs' / name
            if not path.is_file() or file_hash(path) != sha:
                raise BudgetStop('source copy changed/missing: ' + str(path))


class SerialGuard:
    def __init__(self, flow, binding):
        self.flow, self.binding = flow, binding

    def check(self):
        f, b = self.flow, self.binding
        from .model_migration import MIGRATION_VERSION, audit_common_evidence
        if b['version'] not in (VERSION, MIGRATION_VERSION) or b['context'] != f.context:
            raise BudgetStop('v2.2 registration binding mismatch')
        f.assert_current()
        for group in b['source_groups']:
            verify_source_group(f.project_root, group['root'], group['files_sha256'])
        if b['version'] == MIGRATION_VERSION:
            common = audit_common_evidence(b['peer']['root'], b['common_evidence'])
            if common != b['common_audit']:
                raise BudgetStop('common model access/pricing/risk evidence changed after registration')
            if f.config.payload()['provider'] != common['provider']:
                raise BudgetStop('paired model generation parameters changed')
            if f.config.platform_quota_reservation != common['reservation']:
                raise BudgetStop('new model reservation differs from reviewed common basis')
            peer = common['peer']
        else:
            peer = peer_terminal_audit(b['peer']['root'])
        if peer != b['peer']:
            raise BudgetStop('peer final ledger/settlement changed after registration')
        if inventory(worktree_roots(f.project_root), exclude=f.directory) != b['inventory']:
            raise BudgetStop('foreign ledger changed; cumulative reconciliation required')
        history = history_summary(f.project_root, f.config)
        if history['historical_request_slots'] != b['historical_slots']:
            raise BudgetStop('unique ancestral and peer counters changed')
        if history['historical_request_slots'] + len(f.ledger.data['records']) > 300:
            raise BudgetStop('cumulative 300-slot limit exceeded')
        return history


class SerialTransport:
    def __init__(self, inner, guard):
        self.inner, self.guard, self.identity = inner, guard, inner.identity

    def preflight(self, prompt):
        self.guard.check()
        return self.inner.preflight(prompt)

    def dispatch(self, *args, **kwargs):
        self.guard.check()
        return self.inner.dispatch(*args, **kwargs)

    def redact(self, value):
        return self.inner.redact(value)


class RegisteredUsageWorkflow(UsageWorkflow):
    def client(self):
        if self._client is None:
            binding = self.read('V22_binding.json', 'V22_binding')
            guard = SerialGuard(self, binding); guard.check()
            history = dispatch_check(self)
            inner = JsonCandidateTransport(self.config)
            from .model_migration import MIGRATION_VERSION, Gpt61UsageQuota
            from .model_migration import check_live_tariff
            from .access import WireRecorder, MetadataPacer, InvoicePacer
            from .billing import query_invoices
            from fjsp_usage.research_real.leafapi import query_status
            pacer = MetadataPacer(self.directory / 'Metadata_pacing.json')
            inner = WireRecorder(inner, self.directory / 'wire_responses')
            quota_class = Gpt61UsageQuota if binding['version'] == MIGRATION_VERSION else QuotaGuardedTransport
            kwargs = {'tariff_query': lambda secret: check_live_tariff(secret, pacer)} if binding['version'] == MIGRATION_VERSION else {}
            quota = quota_class(inner, self.directory / 'platform_quota.json', self.context,
                query=lambda: pacer.call('/api/usage/token/', lambda: query_status(inner.secret,
                    quota_path='/api/usage/token/', include_models=False)), **kwargs,
                retained_extra=history['retained_account_hold'],
                settlement_min_used=max(history['latest_saved_account_used'], binding['peer']['observed_used']))
            invoice_query = InvoicePacer(lambda: query_invoices(inner.secret), self.directory / 'Invoice_pacing.json', pacer)
            self._client = SerialTransport(InvoiceTransport(quota, self.directory / 'billing', query=invoice_query), guard)
        return self._client
