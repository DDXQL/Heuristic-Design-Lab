"""Durable phase/global reservation ledger, conservative unknown settlement."""

import json
import math
import hashlib
from collections import Counter
from pathlib import Path

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest


class BudgetStop(RuntimeError):
    pass


REQUEST_BUDGET_VERSION = 'local-request-budget-v1'


def validate_request_budget(config):
    """Explicit future-only opt-in; never reinterpret an old specialized run."""
    b = config.request_budget
    if isinstance(b,dict) and b.get('version') in ('batch-api-attempts-v1', 'batch-api-attempts-v2-t1'):
        from .attempt_budget import validate_policy
        validate_policy(config)
        return
    if (not isinstance(b, dict) or set(b) != {'version', 'lifetime_request_cap', 'history_source'}
            or b['version'] != REQUEST_BUDGET_VERSION or type(b['lifetime_request_cap']) is not int
            or b['lifetime_request_cap'] != 300):
        raise ValueError('local request budget requires version, cumulative 300 cap and history source')
    if (config.conditional_research or config.development_continuation_source
            or config.development_acceptance or config.development_h_source
            or config.platform_quota_ceiling is not None or config.platform_quota_reservation is not None):
        raise ValueError('new local-budget protocol only; legacy quota/continuation declarations cannot be migrated')
    source = b['history_source']
    if source is None:
        if config.mode == 'real':
            raise ValueError('real local-budget runs must inherit pinned cumulative history')
        return
    if (not isinstance(source, dict) or set(source) != {'directory', 'protocol_sha256', 'budget_sha256'}
            or not isinstance(source['directory'], str) or not Path(source['directory']).is_absolute()
            or any(not isinstance(source[k], str) or len(source[k]) != 64
                   or any(c not in '0123456789abcdef' for c in source[k])
                   for k in ('protocol_sha256', 'budget_sha256'))):
        raise ValueError('history source requires an absolute directory and two SHA256 pins')


def request_history(config, project_root, *, exclude=None):
    """Read local counters only; reuse the existing cross-worktree inventory.

    A pinned predecessor supplies its own slots PLUS its already-bound history.
    No invoice, account snapshot, settlement or fee release is involved.
    """
    from fjsp_usage.usage_v2.registration import inventory as budget_inventory, worktree_roots
    source = config.request_budget['history_source']

    def read_source(pin, seen):
        if pin is None:
            return 0, 0, {}
        folder = Path(pin['directory']).resolve()
        if folder in seen or (exclude is not None and folder == Path(exclude).resolve()):
            raise BudgetStop('local history cannot refer to itself or contain a cycle')
        if (folder/'.writer.lock').exists():
            raise BudgetStop('historical source still has a writer')
        docs = {}
        for name in ('protocol', 'budget'):
            raw = (folder/(name+'.json')).read_bytes()
            if hashlib.sha256(raw).hexdigest() != pin[name+'_sha256']:
                raise BudgetStop('pinned local history changed: '+name)
            docs[name] = json.loads(raw)
        p, ledger = docs['protocol'], docs['budget']
        if ledger['identity'] != digest({'config': p['config'], 'context': digest(p)}):
            raise BudgetStop('historical ledger/protocol identity mismatch')
        previous = p['config'].get('request_budget')
        if previous:
            if previous['version'] != REQUEST_BUDGET_VERSION or previous['lifetime_request_cap'] != 300:
                raise BudgetStop('unsupported historical request budget')
            slots, sends, inventory = read_source(previous['history_source'], seen | {folder})
        else:
            binding = (p['config'].get('conditional_research') or {}).get('history_binding')
            if not binding:
                raise BudgetStop('predecessor has no authoritative cumulative request binding')
            from .assets import check_seal
            check_seal(binding, kind='Fair_history_binding', mode='real')
            if binding['lifetime_request_cap'] != 300:
                raise BudgetStop('historical lifetime cap changed')
            slots, sends = binding['historical_request_slots'], binding['historical_confirmed_sends']
            inventory = dict(binding['real_budget_inventory'])
        if ledger['identity'] in inventory:
            raise BudgetStop('historical ledger already counted')
        inventory[ledger['identity']] = pin['budget_sha256']
        rows = ledger['records'].values()
        return slots+len(ledger['records']), sends+sum(r.get('send_confirmed', False) for r in rows), inventory

    slots, sends, inventory = read_source(source, set())
    if config.mode == 'real':
        if budget_inventory(worktree_roots(project_root), exclude=exclude) != inventory:
            raise BudgetStop('local cumulative inventory changed or omitted a real ledger')
    if slots+config.total_request_cap > config.request_budget['lifetime_request_cap']:
        raise BudgetStop('new batch plus historical slots exceeds lifetime request cap')
    return {'historical_request_slots': slots, 'historical_confirmed_sends': sends,
            'lifetime_request_cap': config.request_budget['lifetime_request_cap']}


def validate_usage(usage):
    if usage is None:
        return None
    if not isinstance(usage, dict) or set(usage) != {'input_tokens', 'output_tokens'}:
        raise ValueError('usage must contain input_tokens and output_tokens, or be null')
    if any(type(v) is not int or v < 0 for v in usage.values()):
        raise ValueError('usage values must be nonnegative built-in integers')
    return dict(usage)


class BudgetLedger:
    def __init__(self, path, config, context):
        if (config.request_budget or {}).get('version') == 'batch-api-attempts-v1':
            raise ValueError('batch attempt policy requires AttemptJournal, not the legacy global BudgetLedger')
        self.path = Path(path)
        self.config = config
        self.config_key = digest(config.payload())
        self.identity = digest({'config': config.payload(), 'context': context})
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            if self.data['identity'] != self.identity:
                raise ValueError('ledger configuration/context mismatch')
        else:
            self.data = {'identity': self.identity, 'mode': config.mode,
                         'records': {}, 'halted': False}
            self.save()

    def save(self):
        atomic_json(self.path, self.data)

    def cost(self, usage):
        c = self.config
        if c.input_price_per_million is None or usage is None:
            return None
        return (usage['input_tokens'] * c.input_price_per_million
                + usage['output_tokens'] * c.output_price_per_million) / 1e6

    def request_history(self):
        return request_history(self.config, self.path.parent.parent.parent, exclude=self.path.parent)

    def summary(self):
        records = list(self.data['records'].values())
        phases = {}
        for record in records:
            phase = phases.setdefault(record['phase'], {'reserved_requests': 0, 'confirmed_sends': 0,
                'usage_known': 0, 'usage_unknown': 0, 'input_tokens': 0, 'output_tokens': 0,
                'reserved_or_settled_tokens': 0, 'cost_estimate': None if self.config.input_price_per_million is None else 0.0, 'elapsed_seconds': 0.0})
            phase['reserved_requests'] += 1
            phase['confirmed_sends'] += record.get('send_confirmed', False)
            usage = record.get('usage')
            phase['usage_known' if usage is not None else 'usage_unknown'] += 1
            if usage:
                phase['input_tokens'] += usage['input_tokens']
                phase['output_tokens'] += usage['output_tokens']
            charge = usage if usage is not None else record['reservation']
            phase['reserved_or_settled_tokens'] += sum(charge.values())
            if phase['cost_estimate'] is not None:
                phase['cost_estimate'] += self.cost(charge)
            phase['elapsed_seconds'] += record.get('elapsed_seconds', 0.0)
        result = {'mode': self.config.mode, 'request_hard_cap': self.config.total_request_cap,
                'request_slots': len(records), 'confirmed_sends': sum(r.get('send_confirmed', False) for r in records),
                'remaining_request_slots': self.config.total_request_cap-len(records),
                'settlement_statuses': dict(Counter(r['status'] for r in records)),
                'phase_remaining_slots': {p: cap-sum(r['phase'] == p for r in records) for p,cap in self.config.phase_caps().items()},
                'unknown_usage_requests': sum(r.get('usage') is None for r in records),
                'token_limit_basis': 'configured reservation; provider upper bound not certified',
                'money_limit_basis': 'price-based estimate, not verified provider billing/hard cap',
                'price_source': self.config.price_source,
                'cost_currency': getattr(self.config, 'price_currency', None),
                'estimated_cost_stop': self.config.cost_cap_estimate,
                'known_input_tokens': sum(r['usage']['input_tokens'] for r in records if r.get('usage') is not None),
                'known_output_tokens': sum(r['usage']['output_tokens'] for r in records if r.get('usage') is not None),
                'known_usage_cost_estimate': (sum(self.cost(r['usage']) for r in records if r.get('usage') is not None)
                    if self.config.input_price_per_million is not None else None),
                'reserved_or_settled_cost_estimate': (sum(self.cost(r.get('usage') if r.get('usage') is not None else r['reservation']) for r in records)
                    if self.config.input_price_per_million is not None else None),
                'stop_reason': self.data.get('smoke_stop_reason'),
                'phases': phases, 'halted': self.data['halted']}
        if self.config.request_budget is not None:
            historical = self.request_history()
            result.update(**historical,
                budget_policy=REQUEST_BUDGET_VERSION,
                lifetime_request_slots=historical['historical_request_slots']+len(records),
                lifetime_confirmed_sends=historical['historical_confirmed_sends']+result['confirmed_sends'],
                actual_cost=None, actual_cost_status='unknown; no account or invoice queries',
                account_amount_limit_enforced=False,
                historical_costs_and_reservations='unchanged in pinned source; not released or settled')
        elif getattr(self.config,'conditional_research',None):
            from .conditional_research import history_summary
            historical = history_summary(self.path.parent.parent.parent,self.config)
            result.update(budget_scope='local new batch plus separately pinned immutable history',
                historical_request_slots=historical['historical_request_slots'],
                lifetime_request_slots=historical['historical_request_slots']+len(records),
                lifetime_confirmed_sends=historical['historical_confirmed_sends']+result['confirmed_sends'],
                lifetime_request_cap=historical['lifetime_request_cap'],
                retained_historical_account_hold=historical['retained_account_hold'])
        return result

    def reserve(self, key, phase, prompt_key):
        if digest(self.config.payload()) != self.config_key:
            raise ValueError('budget configuration mutated during run')
        records = self.data['records']
        if key in records:
            if records[key]['prompt_key'] != prompt_key or records[key]['phase'] != phase:
                raise ValueError('request key reused with changed prompt/phase')
            return records[key]
        if self.config.request_budget is not None:
            historical = self.request_history()
            if historical['historical_request_slots']+len(records) >= historical['lifetime_request_cap']:
                raise BudgetStop('lifetime request cap exhausted before dispatch')
        if getattr(self.config, 'development_continuation_source', None) is not None:
            import hashlib
            declaration = self.config.development_continuation_source
            source = (self.path.parent.parent/declaration['run']/'budget.json').resolve()
            raw = source.read_bytes()
            if hashlib.sha256(raw).hexdigest() != declaration['files_sha256']['budget.json']:
                raise BudgetStop('original continuation ledger changed; no dispatch')
            original = json.loads(raw)['records']
            if (not self.data.get('continuation_binding_hash') or any(records.get(k)!=v for k,v in original.items())):
                raise BudgetStop('historical request counters/reservations missing or modified; no dispatch')
        acceptance = getattr(self.config,'development_acceptance',None)
        research_history = None
        if getattr(self.config,'conditional_research',None):
            from .conditional_research import budget_check
            research_history = budget_check(self,key,phase)
        if acceptance:
            from .development_acceptance import check_budget_scope
            check_budget_scope(self,key,phase)
        if self.data.get('continuation_unresolved_requests') and not acceptance:
            raise BudgetStop('inherited sent request settlement remains unknown; no new reservation')
        if self.data['halted']:
            raise BudgetStop('ledger halted after an observed reservation overrun')
        caps = self.config.phase_caps()
        if phase not in caps:
            raise ValueError('undeclared budget phase')
        if len(records) >= self.config.total_request_cap or sum(r['phase'] == phase for r in records.values()) >= caps[phase]:
            raise BudgetStop('hard global/phase request cap exhausted before dispatch')
        reservation = {'input_tokens': self.config.provider.input_token_reservation,
                       'output_tokens': (getattr(self.config.provider, 'output_token_reservation', None)
                                         or self.config.provider.max_output_tokens)}
        charges = [r.get('usage') if r.get('usage') is not None else r['reservation'] for r in records.values()]
        if research_history:
            charges += research_history['historical_token_charges']
        if acceptance:
            from .development_acceptance import previous_charges
            charges += previous_charges(self.path.parent.parent,acceptance)
        if self.config.total_token_cap is not None and sum(sum(u.values()) for u in charges) + sum(reservation.values()) > self.config.total_token_cap:
            raise BudgetStop('configured token reservation cap insufficient')
        if self.config.cost_cap_estimate is not None and sum(self.cost(u) for u in charges) + self.cost(reservation) > self.config.cost_cap_estimate:
            raise BudgetStop('estimated-cost reservation cap insufficient')
        record = {'phase': phase, 'prompt_key': prompt_key, 'status': 'reserved',
                  'reservation': reservation, 'usage': None, 'send_confirmed': False}
        records[key] = record
        self.save()
        return record

    def confirm_send(self, key):
        self.data['records'][key]['send_confirmed'] = True
        self.save()

    def settle(self, key, *, status, usage, elapsed_seconds):
        usage = validate_usage(usage)
        record = self.data['records'][key]
        record.update(status=status, usage=usage, elapsed_seconds=elapsed_seconds)
        if usage and any(usage[k] > record['reservation'][k] for k in usage):
            record['reservation_overrun'] = True
            self.data['halted'] = True
        self.save()


class BudgetJournal:
    """Search-compatible journal with no repeat of completed/uncertain dispatch."""
    def __init__(self, path, *, phase, cap, transport, ledger):
        self.path, self.phase, self.cap = Path(path), phase, cap
        self.transport, self.ledger = transport, ledger
        identity = digest({'transport': transport.identity, 'phase': phase, 'cap': cap,
                           'ledger': ledger.identity})
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            if self.data['identity'] != identity:
                raise ValueError('request journal identity changed')
        else:
            self.data = {'identity': identity, 'requests': {}}

    @property
    def calls(self):
        return len(self.data['requests'])

    def request(self, key, prompt, *, kind='U'):
        import time
        prompt_key = digest({'prompt': prompt, 'kind': kind})
        global_key = self.phase + '/' + key
        records = self.data['requests']
        if key in records:
            record = records[key]
            if record['prompt_key'] != prompt_key:
                raise ValueError('request id/prompt mismatch')
            if record['status'] == 'pending':
                record.update(status='interrupted', error='uncertain interrupted dispatch; no replay')
                charged = self.ledger.data['records'][global_key]
                self.ledger.settle(global_key, status='interrupted', usage=charged.get('usage'),
                                   elapsed_seconds=charged.get('elapsed_seconds', 0))
                atomic_json(self.path, self.data)
            return record
        if self.calls >= self.cap:
            raise BudgetStop('search request cap exhausted')
        self.transport.preflight(prompt)  # no reservation/dispatch if context is too large
        existed = global_key in self.ledger.data['records']
        self.ledger.reserve(global_key, self.phase, prompt_key)
        record = {'status': 'pending', 'prompt_key': prompt_key, 'prompt': prompt,
                  'kind': kind, 'global_key': global_key, 'usage': None}
        records[key] = record
        atomic_json(self.path, self.data)
        if existed:
            # Crash between ledger reservation and journal commit: no assumption
            # that it was unsent, even though this may conservatively lose a slot.
            record.update(status='interrupted', error='uncertain orphan reservation; no replay')
            charged = self.ledger.data['records'][global_key]
            self.ledger.settle(global_key, status='interrupted', usage=charged.get('usage'),
                               elapsed_seconds=charged.get('elapsed_seconds', 0))
            atomic_json(self.path, self.data)
            return record
        started = time.monotonic()
        try:
            reply = self.transport.dispatch(global_key, prompt, kind=kind,
                                            on_sent=lambda: self.ledger.confirm_send(global_key))
            record.update(status='completed', text=reply['text'], usage=validate_usage(reply.get('usage')),
                          response_metadata=reply.get('metadata', {}))
        except Exception as exc:
            record.update(status='failed', error=self.transport.redact(str(exc))[:500],
                          error_type=type(exc).__name__, usage=validate_usage(getattr(exc, 'usage', None)),
                          response_metadata=getattr(exc, 'metadata', {}))
        elapsed = time.monotonic() - started
        self.ledger.settle(global_key, status=record['status'], usage=record['usage'], elapsed_seconds=elapsed)
        record['elapsed_seconds'] = elapsed
        atomic_json(self.path, self.data)
        return record
