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
from .billing import InvoiceTransport, certified_reconciliation

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


def peer_terminal_audit(peer_root):
    """No lock or interrupted chat is evidence of completion by itself."""
    peer_root = Path(peer_root)
    locks = list((peer_root / 'runs').rglob('.writer.lock'))
    if locks:
        raise BudgetStop('WAIT_PEER_WRITER_LOCK')
    runs = []
    for path in (peer_root / 'runs').glob('*/protocol.json'):
        body = json.loads(path.read_text()); config = body.get('config', {})
        if (config.get('real_requests_authorized') is True and config.get('seeds') == [201]
                and config.get('total_request_cap') == 60 and config.get('purpose') == 'research'):
            runs.append((path.parent, body))
    if len(runs) != 1:
        raise BudgetStop('WAIT_SINGLE_PEER_REGISTERED_TERMINAL_BATCH: expected exactly one authorized seed201/cap60 batch')
    directory, protocol = runs[0]
    context = digest(protocol)
    gate_path = directory / 'Search_complete.json'
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
    for key, record in budget['records'].items():
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
    return {'run_name': directory.name, 'root': str(peer_root.resolve()), 'context': context,
        'ledger_identity': identity, 'request_slots': len(budget['records']),
        'confirmed_sends': sum(r.get('send_confirmed', False) for r in budget['records'].values()),
        'observed_used': quota.get('observed_used', 0), 'terminal': terminal, 'files_sha256': pins}


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
        if b['version'] != VERSION or b['context'] != f.context:
            raise BudgetStop('v2.2 registration binding mismatch')
        f.assert_current()
        for group in b['source_groups']:
            verify_source_group(f.project_root, group['root'], group['files_sha256'])
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
            quota = QuotaGuardedTransport(inner, self.directory / 'platform_quota.json', self.context,
                retained_extra=history['retained_account_hold'],
                settlement_min_used=max(history['latest_saved_account_used'], binding['peer']['observed_used']))
            self._client = SerialTransport(InvoiceTransport(quota, self.directory / 'billing'), guard)
        return self._client
