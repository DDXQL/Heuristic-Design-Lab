"""Bounded, train-only fair rerun. Cached H evidence; fresh U; no legacy upgrade.

Offline preparation deliberately has no ledger, authorization or provider client.
Registration requires a new human authorization and FINAL cross-worktree handoffs.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from fjsp_usage.research.candidates import Candidate
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from .assets import check_seal, validate_row
from .budget import BudgetStop
from .config import ExperimentConfig, fingerprint
from .model_migration import MigrationQuota, MODEL, risk_reservation
from .quota_guard import QuotaGuardedTransport
from .real_transport import JsonCandidateTransport
from .single_billing import InvoiceTransport
from .single_experiments import GuardedTransport, budget_inventory, worktree_roots
from .single_io import install_protections
from .workflow import Workflow, ARMS

VERSION = 'single-ID-fixed-H-fair-v2'
AUTH_SCOPE = 'fixed-existing-H-single-ID-four-arm-train-only'
# These changes affect registration and recording, never H/U/scheduling semantics.
REGISTRATION_FILES = {'code/fjsp_usage/research_real/conditional_research.py',
                      'code/fjsp_usage/research_real/single_billing.py'}
SOURCE_NAMES = ('protocol.json', 'config.migration.authorized.json', 'H_frozen.json',
    'Conditional_H_reassessment.json', 'Human_authorization.json', 'Shared_model_acceptance.json',
    'Final_budget_handoff.json', 'Migration_readiness.json', 'Worktree_binding.json',
    'budget.json', 'platform_quota.json', 'Metadata_global_pacing.json', 'Invoice_query_pacing.json')


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def validate_declaration(c):
    d = c.conditional_research
    fields = {'version', 'source_run', 'source_files_sha256', 'scope_approval', 'risk_policy',
              'lifetime_request_cap', 'history_binding', 'authorization'}
    if (set(d) != fields or d['version'] != VERSION or c.mode != 'real' or c.purpose != 'research'
            or c.seeds != (201,) or c.H_size != 10 or c.population_size != 5
            or c.cross_parents != 5 or c.mutation_parents != 1 or c.generations != 1
            or c.attempts_per_generation != 10 or c.initialization_cap != 20 or c.total_request_cap != 60
            or c.instance_timeout != 15 or not c.training_diagnostics
            or c.platform_quota_ceiling != 30000000 or d['lifetime_request_cap'] != 300
            or c.platform_quota_query_interval < 75 or c.platform_quota_reservation != 1000000
            or c.provider.model != MODEL or c.provider.expected_response_model != MODEL
            or c.development_h_source or c.development_continuation_source or c.development_acceptance):
        raise ValueError('fair v2 requires the registered scalar-ID seed201/N5/60-call train-only scale')
    name = Path(d['source_run'])
    if name.is_absolute() or len(name.parts) != 1 or name.name in ('.', '..'):
        raise ValueError('fair source must be one runs child')
    if set(d['source_files_sha256']) != set(SOURCE_NAMES):
        raise ValueError('bounded fair source bundle incomplete')
    if c.phase_request_caps is not None and c.phase_request_caps != c.default_phase_caps():
        raise ValueError('fair phase caps must match init20 and four arms x10')
    if any(not isinstance(h, str) or len(h) != 64 or any(x not in '0123456789abcdef' for x in h)
           for h in d['source_files_sha256'].values()):
        raise ValueError('source SHA256 required')
    if c.real_requests_authorized:
        a = d['authorization']
        if (not isinstance(a, dict) or a.get('approved') is not True or a.get('scope') != AUTH_SCOPE
                or a.get('max_new_requests') != 60 or not a.get('reviewer')
                or a.get('exclusive_caller_branch') != 'codex/u-single-experiments'
                or not d['history_binding']):
            raise ValueError('new authorization and final history binding required')
    elif d['authorization'] is not None:
        raise ValueError('pending fair config must not contain a fabricated authorization')


def source_bundle(root, config, dataset):
    """Read only thirteen pinned files; never enumerate historical responses."""
    d = config.conditional_research
    folder = Path(root)/'runs'/d['source_run']
    if (folder/'.writer.lock').exists():
        raise BudgetStop('fixed-H source still has a writer')
    docs = {}
    for name, expected in d['source_files_sha256'].items():
        path = folder/name
        if file_sha(path) != expected:
            raise ValueError('fair source changed: '+name)
        docs[name] = read(path)
    p, H = docs['protocol.json'], docs['H_frozen.json']
    check_seal(H, kind='H_frozen', mode='real', context=digest(p))
    if (p['dataset'] != dataset.metadata or H['training_files'] != list(dataset.names['train'])
            or p['config']['provider'] != config.payload()['provider']
            or p['config']['instance_timeout'] != config.instance_timeout
            or p['config']['review_timeout'] != config.review_timeout
            or d['risk_policy'] != p['config']['conditional_research']['model_migration']['risk_policy']
            or d['scope_approval'] != H['scope_approval']):
        raise ValueError('H/data/provider/evaluation/review/risk semantics differ from the source')
    implementation = fingerprint(root)
    if any(implementation[k] != p['implementation'].get(k)
           for k in ('version','python','platform','dependencies')):
        raise ValueError('cached H evaluation runtime/dependencies changed')
    current = implementation['files']
    for name, expected in p['implementation']['files'].items():
        if name.startswith('code/') and name not in REGISTRATION_FILES and current.get(name) != expected:
            raise ValueError('cached H evaluation cannot be reused after semantic change: '+name)
    if H['member_count'] != 10 or len(H['members']) != 10:
        raise ValueError('exact ten-member H required')
    approval = H['scope_approval']
    if (not approval.get('reviewer') or approval.get('scope') != 'conditional-fixed-H-research'
            or approval['member_code_keys'] != [x['candidate']['key'] for x in H['members']]):
        raise ValueError('original research scope/code-order binding invalid')
    members = []
    for i, row in enumerate(H['members']):
        candidate = validate_row(row, dataset.names['train'], 'real', 'h')
        review = row['review']
        if (row['member_id'] != i or review['reviewed_code_key'] != candidate.key
                or review['sample_sha256'] != digest(review['samples'])
                or any(not review.get(k) for k in ('description','reviewer','method','note'))
                or review['method'].startswith('synthetic')
                or not all(r.get('feasible') is True for r in row['training_result']['instances'])):
            raise ValueError('cached H review/result invalid')
        members.append(Candidate(review['description'], candidate.code, candidate.key, 'h'))
    if len({m.key for m in members}) != 10:
        raise ValueError('duplicate H code')
    return docs, tuple(members)


def pending_config(root, source_run):
    folder = Path(root)/'runs'/source_run
    old = read(folder/'config.migration.authorized.json')
    d = old['conditional_research']
    old.update(real_requests_authorized=False, total_request_cap=60, phase_request_caps=None)
    old['conditional_research'] = {'version': VERSION, 'source_run': source_run,
        'source_files_sha256': {n:file_sha(folder/n) for n in SOURCE_NAMES},
        'scope_approval': read(folder/'H_frozen.json')['scope_approval'],
        'risk_policy': d['model_migration']['risk_policy'], 'lifetime_request_cap':300,
        'history_binding':None, 'authorization':None}
    return ExperimentConfig.from_dict(old)


def history_summary(root, config):
    b = config.conditional_research['history_binding']
    if b is None:
        raise BudgetStop('waiting for FINAL peer handoff and new authorization; no network allowed')
    check_seal(b, kind='Fair_history_binding', mode='real')
    for name, expected in b['files_sha256'].items():
        if file_sha(name) != expected:
            raise BudgetStop('final historical handoff/ledger changed: '+name)
    if b['historical_request_slots']+config.total_request_cap > 300:
        raise BudgetStop('new batch plus inherited slots exceeds cumulative 300 cap')
    return b


def verify_final_receipts(folder, ledger, quota, files):
    """Pin exact invoice/debit evidence, not merely a handoff's 'unknown=0'."""
    from .single_billing import match_invoice
    total = 0
    for key, record in ledger['records'].items():
        stem = hashlib.sha256(key.encode()).hexdigest()
        path = folder/'billing'/(stem+'.json')
        bill = read(path); files[str(path)] = file_sha(path)
        if not record.get('send_confirmed'):
            if (bill.get('status') != 'before_dispatch' or bill['before'].get('success') is True
                    or key in quota['records']):
                raise BudgetStop('unconfirmed peer send cannot be declared free/settled')
            continue
        account = quota['records'].get(key)
        if not account or not account.get('send_confirmed') or account.get('status') != 'settled':
            raise BudgetStop('peer native quota settlement absent')
        after = bill.get('after',{}); metadata = bill.get('response_metadata',{})
        proof_path = folder/'billing_reconciliations'/(stem+'.json')
        if bill.get('status') != 'invoice_account_matched':
            if not proof_path.exists():raise BudgetStop('peer final invoice proof missing')
            proof = read(proof_path); files[str(proof_path)] = file_sha(proof_path)
            if proof['original_billing_sha256'] != file_sha(path):
                raise BudgetStop('peer reconciliation does not bind the original bill')
            for name, expected in proof['evidence_files_sha256'].items():
                evidence = (folder/name).resolve()
                if not evidence.is_relative_to(folder) or file_sha(evidence) != expected:
                    raise BudgetStop('peer settlement evidence changed/escaped')
                files[str(evidence)] = expected
                if 'invoices' in name:after = read(evidence)
            account = proof['reconciled_account']
            metadata = {'gateway_request_id':proof['supplier_request_id']}
        invoice = match_invoice(bill['before'],after,account,MODEL,
            failed=bill.get('transport_status')=='failed',response_id=metadata.get('gateway_request_id'))
        if invoice.get('group') != 'codex-deafult':
            raise BudgetStop('peer invoice group mismatch')
        total += invoice['quota']
    return total


def bind_history(root, config, dataset, additional, *, inventory=None):
    """Additional = explicit (run directory, final handoff file) pairs.

    The base aggregate was previously audited, including continuation dedup;
    its native 48 slots are NOT added a second time. New ledgers count once by
    identity. Final handoffs, raw ledgers and quota evidence are hash pinned.
    """
    docs, _ = source_bundle(root, config, dataset)
    source = Path(root)/'runs'/config.conditional_research['source_run']
    base = docs['Final_budget_handoff.json']; native = docs['budget.json']
    if (base['real_caller_active'] is not False or base['unknown_new_fee_keys']
            or base['budget_sha256'] != file_sha(source/'budget.json')
            or base['budget_identity'] != native['identity'] or base['unknown_new_fee_holds'] != 0
            or base['summary']['historical_request_slots'] != docs['Migration_readiness.json']['history']['historical_request_slots']
            or base['summary']['lifetime_request_slots'] != base['summary']['historical_request_slots']+len(native['records'])
            or base['summary']['lifetime_confirmed_sends'] != docs['Migration_readiness.json']['history']['historical_confirmed_sends']
                +sum(bool(r.get('send_confirmed')) for r in native['records'].values())
            or base['old_account_hold'] != docs['Migration_readiness.json']['history']['retained_account_hold']):
        raise BudgetStop('base final cumulative handoff inconsistent')
    files = {str(source/n):file_sha(source/n) for n in SOURCE_NAMES}
    expected = dict(docs['Worktree_binding.json']['real_budget_inventory'])
    expected[native['identity']] = file_sha(source/'budget.json')
    slots = base['summary']['lifetime_request_slots']
    sends = base['summary']['lifetime_confirmed_sends']
    charges = deepcopy(docs['Migration_readiness.json']['history']['historical_token_charges'])
    charges += [r['usage'] if r.get('usage') is not None else r['reservation'] for r in native['records'].values()]
    used, hold = base['latest_verified_used_points'], base['old_account_hold']
    metadata_floor = docs['Metadata_global_pacing.json']['last_finished_at']
    invoice_floor = docs['Invoice_query_pacing.json']['last_finished_at']
    seen = set(expected)
    for folder, handoff in additional:
        folder, handoff = Path(folder).resolve(), Path(handoff).resolve()
        if handoff.parent != folder or (folder/'.writer.lock').exists():
            raise BudgetStop('peer handoff must belong to a stopped run')
        h, ledger, quota = read(handoff), read(folder/'budget.json'), read(folder/'platform_quota.json')
        if (h.get('real_caller_active') is not False or h.get('quota_halted') is not False
                or h.get('unknown_new_fee_keys') != [] or h.get('unknown_new_fee_holds') != 0
                or h.get('old_account_hold') != hold or h.get('budget_identity') != ledger['identity']
                or h.get('budget_sha256') != file_sha(folder/'budget.json')
                or ledger['identity'] in seen or ledger.get('mode') != 'real'
                or any(r.get('status') in ('pending','reserved') for r in ledger['records'].values())
                or any(r.get('status') != 'settled' for r in quota['records'].values())
                or h['summary']['request_slots'] != len(ledger['records'])
                or h['summary']['confirmed_sends'] != sum(bool(r.get('send_confirmed')) for r in ledger['records'].values())):
            raise BudgetStop('peer handoff incomplete, unsettled, duplicated or inconsistent')
        points = verify_final_receipts(folder,ledger,quota,files)
        if h.get('known_new_points') != points:
            raise BudgetStop('peer handoff actual cost differs from invoice evidence')
        seen.add(ledger['identity']); expected[ledger['identity']] = file_sha(folder/'budget.json')
        slots += len(ledger['records']); sends += h['summary']['confirmed_sends']
        charges += [r['usage'] if r.get('usage') is not None else r['reservation'] for r in ledger['records'].values()]
        used = max(used, h['latest_verified_used_points'], quota.get('observed_used',0))
        for p in (handoff, folder/'budget.json', folder/'platform_quota.json',
                  folder/'Metadata_global_pacing.json', folder/'Invoice_query_pacing.json'):
            files[str(p)] = file_sha(p)
        metadata_floor = max(metadata_floor, read(folder/'Metadata_global_pacing.json')['last_finished_at'])
        invoice_floor = max(invoice_floor, read(folder/'Invoice_query_pacing.json')['last_finished_at'])
    current = inventory() if inventory else budget_inventory(worktree_roots(root))
    if current != expected:
        raise BudgetStop('unregistered/changed cross-worktree consumption; final handoffs required')
    if slots+config.total_request_cap > 300:
        raise BudgetStop('not enough cumulative slots for the registered new batch')
    from .assets import seal
    return seal({'kind':'Fair_history_binding','mode':'real', 'files_sha256':files,
        'real_budget_inventory':expected,'historical_request_slots':slots,
        'historical_confirmed_sends':sends,'historical_token_charges':charges,
        'retained_account_hold':hold,'latest_saved_account_used':used,'lifetime_request_cap':300,
        'metadata_floor':metadata_floor,'invoice_floor':invoice_floor,
        'notice':'Old unknown usage/reservations retained; no monetary conversion; no allowance reset.'})


def budget_check(ledger, key, phase):
    b = history_summary(ledger.path.parent.parent.parent, ledger.config)
    if phase.startswith('H/') or phase not in ledger.config.phase_caps():
        raise BudgetStop('fair batch permits declared scalar-ID U phases only')
    if b['historical_request_slots']+len(ledger.data['records']) >= 300:
        raise BudgetStop('cumulative slot cap exhausted')
    return b


class FairQuota(MigrationQuota):
    def preflight(self, prompt):
        if self.data['halted']:
            raise BudgetStop(self.data.get('stop_reason','fair quota halted'))
        return super().preflight(prompt)

    def reservation_for(self, prompt):
        return risk_reservation(prompt, self.config.conditional_research['risk_policy'])['points']

    def dispatch(self, key, prompt, *, kind='U', on_sent=lambda:None):
        if '/'.join(key.split('/')[:2]) not in self.config.phase_caps() or '/H/' in key:
            raise BudgetStop('undeclared fair dispatch phase')
        def sent():
            self.data['records'][key]['risk_basis'] = risk_reservation(prompt,self.config.conditional_research['risk_policy'])
            self.save(); on_sent()
        return QuotaGuardedTransport.dispatch(self,key,prompt,kind=kind,on_sent=sent)


class FairWorkflow(Workflow):
    """Only registration/transport differ; V5 search and evaluator are inherited."""
    def h_asset(self):
        docs, members = source_bundle(self.project_root,self.config,self.dataset)
        H = self.read('H_frozen.json','H_frozen')
        old = docs['H_frozen.json']
        if (H['members'] != old['members'] or H['source_H_hash'] != old['artifact_sha256']
                or H['scope_approval'] != old['scope_approval'] or H['training_files'] != old['training_files']):
            raise ValueError('fair H differs from frozen reviewed source')
        return H, members

    def check(self):
        self.config.check_dispatch(); self.assert_current(); self.h_asset()
        b = history_summary(self.project_root,self.config)
        if budget_inventory(worktree_roots(self.project_root),exclude=self.directory) != b['real_budget_inventory']:
            raise BudgetStop('peer budget/writer changed after registration')

    def client(self):
        if self._client is None:
            self.check()
            b = history_summary(self.project_root,self.config)
            quota = FairQuota(JsonCandidateTransport(self.config),self.directory/'platform_quota.json',
                self.context,retained_extra=b['retained_account_hold'],settlement_min_used=b['latest_saved_account_used'])
            invoice = InvoiceTransport(quota,self.directory/'billing')
            invoice.expected_group = self.config.conditional_research['risk_policy']['group']
            protected = install_protections(invoice,quota,self.directory,self.check,
                metadata_floor=b['metadata_floor'],invoice_floor=b['invoice_floor'])
            self._client = GuardedTransport(protected,self)
        return self._client

    def generate_h(self):
        raise BudgetStop('fixed H only; no new Tier1 requests')

    def select(self, *args, **kwargs):
        raise BudgetStop('fair batch is training only')

    def test(self, *args, **kwargs):
        raise BudgetStop('fair batch is training only')
