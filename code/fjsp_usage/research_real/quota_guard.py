"""Serial, fail-closed account-quota checks; no inference retry or CNY conversion.

This is a local conservative stop, not a provider-enforced financial limit.
An interrupted request or unobservable settlement blocks subsequent sends.
"""

import json
from pathlib import Path
import time

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from .budget import BudgetStop
from .leafapi import query_status


class QuotaGuardedTransport:
    def __init__(self, transport, path, context, *, query=None, clock=time.monotonic, sleep=time.sleep,
                 retained_records=None, retained_extra=0, allowed_phase=None,settlement_min_used=0):
        self.transport = transport
        self.config = transport.config
        self.identity = transport.identity
        self.redact = transport.redact
        self.path = Path(path)
        self.query = query or (lambda: query_status(transport.secret,
            quota_path='/api/usage/token/', include_models=False))
        self.clock, self.sleep = clock, sleep
        self._last_verified = None  # persisted balances never count as a fresh process-local observation
        self.retained_records = retained_records or {}
        self.retained_extra = retained_extra
        self.allowed_phase = allowed_phase
        self.settlement_min_used=settlement_min_used
        if (self.retained_records or retained_extra or allowed_phase) and not (
                getattr(self.config,'development_acceptance',None) or getattr(self.config,'conditional_research',None)):
            raise ValueError('retained reservation continuation is explicit development-only')
        identity = digest({'config': self.config.payload(), 'context': context})
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            if self.data['identity'] != identity:
                raise ValueError('quota guard context mismatch')
        else:
            self.data = {'identity': identity, 'records': {}, 'halted': False,
                'ceiling': self.config.platform_quota_ceiling,
                'reservation': self.config.platform_quota_reservation,
                'unit': 'raw platform quota; no verified CNY conversion',
                'limit_basis': 'local conservative guard; provider upper bound not certified'}
            self.save()
        self.check_retained()
        if any(r['status'] == 'pending' and k not in self.retained_records for k,r in self.data['records'].items()):
            self.halt('uncertain interrupted request; no automatic continuation')

    def check_retained(self):
        if any(self.data['records'].get(k)!=v for k,v in self.retained_records.items()):
            raise BudgetStop('retained historical quota reservation changed')
        return self.retained_extra + sum(r['reserved'] for r in self.retained_records.values())

    def save(self):
        atomic_json(self.path, self.data)

    def halt(self, reason):
        self.data.update(halted=True, stop_reason=reason)
        self.save()

    def balance(self, *, allow_cached=False):
        if self._last_verified is not None:
            age = self.clock() - self._last_verified
            interval = self.config.platform_quota_query_interval
            if allow_cached and 0 <= age < interval:
                return self.data['latest_quota']
            # Read-only checks are paced; this never repeats an inference request.
            # Only a recent balance verified by this process is used for preflight.
            remaining = interval - age
            while remaining > 0:
                delay = min(remaining, 1.0)
                self.sleep(delay)
                remaining -= delay
        try:
            result = self.query()
            quota = result.get('quota', {})
            self.data['last_metadata_result'] = quota
            if not quota.get('available') or quota.get('unlimited_quota') is not False:
                raise ValueError()
            used, available, granted = (quota.get(k) for k in
                ('total_used', 'total_available', 'total_granted'))
            if any(type(v) is not int or v < 0 for v in (used, available, granted)):
                raise ValueError()
            if used + available != granted:
                raise ValueError()
            if used < self.data.get('observed_used', used):
                raise ValueError()
            if used < self.settlement_min_used:
                raise ValueError()
            expires = quota.get('expires_at')
            if type(expires) is not int or (expires and expires <= time.time()):
                raise ValueError()
            if quota.get('allowed_by_explicit_token_limit') is False:
                raise ValueError()
        except Exception:
            self.halt('account quota unavailable/inconsistent; no retry')
            raise BudgetStop(self.data['stop_reason']) from None
        self.data.update(observed_used=used, observed_at=time.time(), latest_quota=quota)
        self._last_verified = self.clock()
        self.save()
        return quota

    def reservation_for(self, prompt):
        return self.config.platform_quota_reservation

    def preflight(self, prompt):
        hold = self.check_retained()
        self.transport.preflight(prompt)
        if self.data['halted']:
            raise BudgetStop(self.data['stop_reason'])
        quota = self.balance(allow_cached=True)
        reserve = self.reservation_for(prompt)
        if quota['total_used'] + hold + reserve > self.config.platform_quota_ceiling or quota['total_available'] < hold + reserve:
            self.halt('insufficient account quota for conservative next-request reservation')
            raise BudgetStop(self.data['stop_reason'])

    def dispatch(self, key, prompt, *, kind='U', on_sent=lambda: None):
        if getattr(self.config,'conditional_research',None) and (kind!='U' or key.split('/')[0] not in
                {f'r{s}' for s in self.config.seeds} or '/H/' in key):
            raise BudgetStop('conditional research permits declared U seeds only')
        if self.allowed_phase and not key.startswith(self.allowed_phase):
            raise BudgetStop('retained-reservation development permits P evolution only')
        if key in self.data['records']:
            raise BudgetStop('quota guard forbids repeated dispatch')
        self.preflight(prompt)
        before = self.data['observed_used']
        record = {'status': 'pending', 'before_used': before, 'reserved': self.reservation_for(prompt),
                  'send_confirmed': False, 'started_at': time.time()}
        self.data['records'][key] = record
        self.save()

        def sent():
            record['send_confirmed'] = True
            self.save()
            on_sent()

        reply, error = None, None
        provider_started = self.clock()
        try:
            reply = self.transport.dispatch(key, prompt, kind=kind, on_sent=sent)
        except Exception as exc:
            error = exc
        provider_seconds = self.clock() - provider_started
        if error is None:
            reply = {**reply, 'metadata': {**reply.get('metadata',{}),
                'provider_roundtrip_seconds': provider_seconds}}
        else:
            error.metadata = {**(getattr(error,'metadata',None) or {}),
                'provider_roundtrip_seconds': provider_seconds}
        try:
            after = self.balance()['total_used']
            delta = after - before
            record.update(status='settled', after_used=after, observed_account_delta=delta,
                          finished_at=time.time(), transport_status='failed' if error else 'completed')
            # Zero delta may be delayed billing. A send without usage is ambiguous.
            usage = getattr(error, 'usage', None) if error else reply.get('usage')
            if record['send_confirmed'] and (usage is None or (sum(usage.values()) > 0 and delta == 0)):
                self.halt('unknown usage or possibly delayed account charge; manual investigation required')
            if delta > record['reserved'] or after + self.check_retained() > self.config.platform_quota_ceiling:
                self.halt('observed account debit exceeded reservation/ceiling')
            self.save()
        except BudgetStop as quota_error:
            record.update(status='settlement_unknown', finished_at=time.time())
            self.save()
            if error is None:
                quota_error.usage = reply.get('usage')
                quota_error.metadata = reply.get('metadata', {})
                error = quota_error
        if error is not None:
            raise error
        return reply
