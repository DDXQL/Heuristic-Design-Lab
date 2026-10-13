"""Read-only cross-worktree checks for the original scalar-ID experiment.

This guard never settles an invoice or merges an unseen budget automatically.
Foreign changes require a new reviewed registration, rather than resetting cost.
"""
import hashlib
import json
from pathlib import Path
import subprocess
from .budget import BudgetStop

VERSION = 'single-ID-four-arm-worktree-v1-20261013'


def file_hashes(root):
    runs = Path(root) / 'runs'
    if list(runs.rglob('.writer.lock')):
        raise BudgetStop('source has a writer lock; do not snapshot an active run')
    return {str(p.relative_to(runs)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(runs.rglob('*')) if p.is_file()}


def declaration_pins(hashes):
    """Asset declarations name runs children; keep root notes in outer snapshot."""
    return {name: sha for name, sha in hashes.items() if len(Path(name).parts) >= 2}


def worktree_roots(root):
    text = subprocess.check_output(['git', '-C', str(root), 'worktree', 'list', '--porcelain'], text=True)
    return [Path(line.removeprefix('worktree ')) for line in text.splitlines()
            if line.startswith('worktree ')]


def budget_inventory(roots, *, exclude=None):
    """Deduplicate copied ledgers by identity; conflicting copies fail closed."""
    exclude = Path(exclude).resolve() if exclude is not None else None
    inventory = {}
    for root in roots:
        runs = Path(root) / 'runs'
        for lock in runs.rglob('.writer.lock'):
            if exclude is None or lock.parent.resolve() != exclude:
                raise BudgetStop('another run has a writer lock: ' + str(lock))
        for path in sorted(runs.glob('*/budget.json')):
            if exclude is not None and path.parent.resolve() == exclude:
                continue
            body = json.loads(path.read_text())
            if body.get('mode') != 'real' or not body.get('records'):
                continue
            identity = body['identity']
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if identity in inventory and inventory[identity] != sha:
                raise BudgetStop('same ledger identity has divergent worktree copies')
            inventory[identity] = sha
    return inventory


def ensure_no_new_paid_ledgers(origin_inventory, inventory):
    if set(inventory) - set(origin_inventory):
        raise BudgetStop('new paid ledger outside original history; cannot reuse first-stage authorization in a fresh batch')


def verify_sources(root, origin, expected):
    root, origin = Path(root), Path(origin)
    for name, sha in expected.items():
        for base in (root, origin):
            path = base / 'runs' / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise BudgetStop('read-only source changed or missing: ' + str(path))


class Guard:
    def __init__(self, flow, binding):
        self.flow, self.binding = flow, binding

    def check(self):
        b, flow = self.binding, self.flow
        if b['version'] != VERSION or b['context'] != flow.context:
            raise BudgetStop('single experiment registration/context mismatch')
        flow.assert_current()
        verify_sources(flow.project_root, b['origin_root'], b['source_files_sha256'])
        current = budget_inventory(worktree_roots(flow.project_root), exclude=flow.directory)
        if current != b['real_budget_inventory']:
            raise BudgetStop('another worktree budget changed; reconcile cumulative consumption and register a new batch')


class GuardedTransport:
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
