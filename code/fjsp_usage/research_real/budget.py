"""Durable phase/global reservation ledger, conservative unknown settlement."""

import json
import math
from collections import Counter
from pathlib import Path

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest


class BudgetStop(RuntimeError):
    pass


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
        return {'mode': self.config.mode, 'request_hard_cap': self.config.total_request_cap,
                'request_slots': len(records), 'confirmed_sends': sum(r.get('send_confirmed', False) for r in records),
                'remaining_request_slots': self.config.total_request_cap-len(records),
                'settlement_statuses': dict(Counter(r['status'] for r in records)),
                'phase_remaining_slots': {p: cap-sum(r['phase'] == p for r in records) for p,cap in self.config.phase_caps().items()},
                'unknown_usage_requests': sum(r.get('usage') is None for r in records),
                'token_limit_basis': 'configured reservation; provider upper bound not certified',
                'money_limit_basis': 'price-based estimate, not verified provider billing/hard cap',
                'price_source': self.config.price_source, 'phases': phases, 'halted': self.data['halted']}

    def reserve(self, key, phase, prompt_key):
        if digest(self.config.payload()) != self.config_key:
            raise ValueError('budget configuration mutated during run')
        records = self.data['records']
        if key in records:
            if records[key]['prompt_key'] != prompt_key or records[key]['phase'] != phase:
                raise ValueError('request key reused with changed prompt/phase')
            return records[key]
        if self.data['halted']:
            raise BudgetStop('ledger halted after an observed reservation overrun')
        caps = self.config.phase_caps()
        if phase not in caps:
            raise ValueError('undeclared budget phase')
        if len(records) >= self.config.total_request_cap or sum(r['phase'] == phase for r in records.values()) >= caps[phase]:
            raise BudgetStop('hard global/phase request cap exhausted before dispatch')
        reservation = {'input_tokens': self.config.provider.input_token_reservation,
                       'output_tokens': self.config.provider.max_output_tokens}
        charges = [r.get('usage') if r.get('usage') is not None else r['reservation'] for r in records.values()]
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
            record.update(status='completed', text=reply['text'], usage=validate_usage(reply.get('usage')))
        except Exception as exc:
            record.update(status='failed', error=self.transport.redact(str(exc))[:500],
                          error_type=type(exc).__name__, usage=validate_usage(getattr(exc, 'usage', None)))
        elapsed = time.monotonic() - started
        self.ledger.settle(global_key, status=record['status'], usage=record['usage'], elapsed_seconds=elapsed)
        record['elapsed_seconds'] = elapsed
        atomic_json(self.path, self.data)
        return record
