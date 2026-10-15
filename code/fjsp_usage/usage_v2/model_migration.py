"""Approved generator migration; H identity and historical billing stay intact.

No access diagnostic is sent here. The peer's native final handoff names its
raw ledgers, response, invoice and pricing, checked again before
registration and every dispatch. Missing common evidence is a stop, not consent
to reuse the old batch or its reservation.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
import http.client
import json
from pathlib import Path, PurePosixPath
import time

from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.budget import BudgetStop, validate_usage
from fjsp_usage.research_real.quota_guard import QuotaGuardedTransport
from fjsp_usage.research_real.assets import check_seal
from .config import UsageConfig
from .billing import match_invoice

MODEL = 'gpt-6.1-sol'
MIGRATION_VERSION = 'registered-v22-gpt61-serial-train-20261014'
PROVIDER_MIGRATION_VERSION = 'approved-fixed-H-generator-migration-v1'
EXPRESSION = 'len <= 272000 ? tier("0_272k", p * 2 + cr * 0.1 + cc * 2.5 + c * 10) : tier("272k_plus", p * 4 + cr * 0.2 + cc * 5 + c * 15)'
RISK_POLICY = {'basis': 'conditional-engineering-envelope-not-certified-provider-bound',
    'expression': EXPRESSION, 'max_input_rate': 5, 'max_output_rate': 15,
    'group': 'codex-deafult', 'group_ratio': 0.5, 'quota_per_unit': 500000,
    'safety_factor': 2, 'round_to_points': 1000,
    'input_envelope_rule': 'max(65536,utf8_prompt_bytes+4096)',
    'output_envelope': 32768, 'max_per_request_points': 1000000}


def check_provider_migration(config, source_provider, H_hash):
    migration = getattr(config, 'provider_migration', None)
    expected = {'version', 'confirmation_person', 'source_provider', 'target_provider', 'source_H_sha256', 'risk_policy'}
    if (not isinstance(migration, dict) or set(migration) != expected
            or migration['version'] != PROVIDER_MIGRATION_VERSION
            or migration['confirmation_person'] != 'DDXQL'
            or migration['source_provider'] != source_provider
            or migration['source_H_sha256'] != H_hash
            or migration['target_provider'] != config.payload()['provider']
            or migration['risk_policy'] != RISK_POLICY
            or source_provider['model'] != 'gpt-5.6-sol'
            or config.provider.model != MODEL or config.provider.expected_response_model != MODEL
            or config.provider.endpoint != source_provider['endpoint']
            or config.provider.protocol != source_provider['protocol']):
        raise ValueError('conditional source cannot silently change provider/model/parameters; exact approved migration required')
    if migration['target_provider'] != {**source_provider, 'model': MODEL, 'expected_response_model': MODEL}:
        raise ValueError('approved migration changes only the model and response-model fields')


@dataclass(frozen=True)
class MigratedUsageConfig(UsageConfig):
    registration_version: str = MIGRATION_VERSION
    provider_migration: dict | None = None

    def __post_init__(self):
        super().__post_init__()
        if (self.registration_version != MIGRATION_VERSION or self.seeds != (301,)
                or self.provider.model != MODEL or self.provider.expected_response_model != MODEL):
            raise ValueError('this migration permits only seed301 and locked gpt-6.1-sol')
        if not self.provider_migration:
            raise ValueError('explicit fixed-H generator migration binding required')
        check_provider_migration(self, self.provider_migration['source_provider'],
                                 self.conditional_research['scope_approval']['source_H_sha256'])
        if self.platform_quota_reservation != RISK_POLICY['max_per_request_points']:
            raise ValueError('new model registered risk envelope cap must match the common policy')


def read_peer_file(peer_root, relative):
    relative_path = PurePosixPath(relative)
    base = (Path(peer_root) / 'runs').resolve()
    path = (base / relative_path).resolve()
    if (relative_path.is_absolute() or '..' in relative_path.parts or len(relative_path.parts) < 2
            or not path.is_relative_to(base) or not path.is_file()):
        raise BudgetStop('common evidence must name an existing peer runs child file')
    try:
        return json.loads(path.read_text()), path
    except (ValueError, OSError):
        raise BudgetStop('common evidence is missing or unreadable') from None


def check_preflight(pricing, status, models):
    prices = [r for r in pricing.get('models', []) if r.get('model_name') == MODEL]
    if (pricing.get('success') is not True or pricing.get('inference_requests') != 0
            or len(prices) != 1 or prices[0].get('billing_expr') != EXPRESSION
            or prices[0].get('enable_groups') != ['codex-deafult']
            or pricing.get('group_ratio', {}).get('codex-deafult') != 0.5
            or status.get('public_fields', {}).get('quota_per_unit') != 500000
            or models.get('locked_model_listed') is not True):
        raise BudgetStop('common new-model listing/group/public tariff evidence differs')


def risk_reservation(prompt, policy=RISK_POLICY):
    if policy != RISK_POLICY or not isinstance(prompt, str):
        raise BudgetStop('unregistered common new-model risk policy')
    inputs = max(65536, len(prompt.encode('utf-8')) + 4096)
    raw = (Decimal(inputs) * Decimal(5) + Decimal(32768) * Decimal(15)) * Decimal('0.5') * Decimal(500000) / Decimal(1000000)
    amount = int((raw * 2 / Decimal(1000)).to_integral_value(rounding=ROUND_CEILING)) * 1000
    if amount > 1000000:
        raise BudgetStop('prompt-based engineering risk exceeds registered cap; no clipping')
    return {'points': amount, 'input_envelope': inputs, 'output_envelope': 32768,
            'raw_conditional_points': float(raw), 'certified_provider_upper_bound': False}


def audit_common_evidence(peer_root, index=None):
    """Consume the peer's actual migration protocol/diagnostic/handoff format."""
    from .registration import peer_terminal_audit, file_hash
    if index is not None:
        raise BudgetStop('only the native verified peer handoff may certify common access')
    peer = peer_terminal_audit(peer_root, model=MODEL)
    directory = Path(peer_root) / 'runs' / peer['run_name']
    protocol = json.loads((directory / 'protocol.json').read_text()); context = digest(protocol)
    config = protocol['config']; provider = config['provider']
    declaration = config.get('conditional_research', {}).get('model_migration', {})
    if (config.get('total_request_cap') != 61 or config.get('platform_quota_ceiling') != 30000000
            or config.get('platform_quota_reservation') != 1000000
            or provider.get('expected_response_model') != MODEL
            or provider.get('endpoint') != 'https://leafapi.cc/v1/chat/completions'
            or provider.get('protocol') != 'openai-chat-v1'
            or config.get('population_size') != 5 or config.get('instance_timeout') != 15
            or config.get('initialization_cap') != 20 or config.get('generations') != 1
            or config.get('attempts_per_generation') != 10
            or declaration.get('risk_policy') != RISK_POLICY):
        raise BudgetStop('paired model/generation/evaluation/risk conditions differ')
    final_path = directory / 'Migration_final.json'; handoff_path = directory / 'Exclusive_call_handoff.json'
    verified_path = directory / 'Diagnostic_verified.json'
    if not all(p.is_file() for p in (final_path, handoff_path, verified_path)):
        raise BudgetStop('WAIT_COMMON_DIAGNOSTIC_AND_TERMINAL_HANDOFF')
    final = check_seal(json.loads(final_path.read_text()), kind='Migration_final', mode='real', context=context)
    verified = check_seal(json.loads(verified_path.read_text()), kind='Diagnostic_verified', mode='real', context=context)
    handoff = json.loads(handoff_path.read_text())
    if (final.get('status') not in ('STOPPED', 'COMPLETED_TRAIN_ONLY') or verified.get('candidate') is not False
            or handoff.get('caller_released') is not True or handoff.get('status') != final['status']
            or handoff.get('budget_file_sha256') != file_hash(directory / 'budget.json')):
        if 'final_costs' not in peer or verified.get('candidate') is not False or handoff.get('caller_released') is not True:
            raise BudgetStop('peer terminal/exclusive-caller evidence not bound to final ledger')
    budget = json.loads((directory / 'budget.json').read_text())
    quota = json.loads((directory / 'platform_quota.json').read_text())
    if handoff.get('quota') != quota:
        raise BudgetStop('peer final account/settlement handoff changed')
    diagnostics = {k: r for k, r in budget['records'].items() if r.get('phase') == 'r201/diagnostic'}
    if len(diagnostics) != 1:
        raise BudgetStop('exactly one common diagnostic is required; no retry')
    key, request = next(iter(diagnostics.items())); record = verified['record']
    usage = validate_usage(request.get('usage')); q = quota['records'].get(key)
    metadata = record.get('response_metadata', {})
    if (not q or usage is None or request.get('status') != 'completed' or not request.get('send_confirmed')
            or record.get('global_key') != key or record.get('usage') != usage or record.get('text', '').strip() != 'OK'
            or record.get('status') != 'completed' or metadata.get('model') != MODEL
            or not metadata.get('id') or not metadata.get('gateway_request_id')
            or metadata.get('billing_certified') is not True):
        raise BudgetStop('common access diagnostic failed/model differs/usage or request tracking unknown')
    proofs = [json.loads(p.read_text()) for p in (directory / 'billing').glob('*.json')]
    matches = [b for b in proofs if b.get('global_key') == key]
    if len(matches) != 1:
        raise BudgetStop('common diagnostic actual invoice proof missing or ambiguous')
    billing = matches[0]
    invoice = match_invoice(billing['before'], billing['after'], q, MODEL, failed=False,
                            response_id=metadata['gateway_request_id'])
    if (billing.get('status') != 'invoice_account_matched' or billing.get('transport_status') != 'completed'
            or billing.get('wire_usage') != usage or billing.get('original_quota_record') != q
            or billing.get('invoice') != invoice or billing.get('actual_platform_units') != invoice['quota']):
        raise BudgetStop('common diagnostic actual invoice/account settlement not certified')
    preflight = declaration.get('preflight_run')
    if not isinstance(preflight, str) or not preflight:
        raise BudgetStop('common public model pricing evidence missing')
    pricing, _ = read_peer_file(peer_root, preflight + '/pricing.json')
    status, _ = read_peer_file(peer_root, preflight + '/status.json')
    models, _ = read_peer_file(peer_root, preflight + '/models.json')
    check_preflight(pricing, status, models)
    pins = dict(peer['files_sha256'])
    for name in ('pricing.json', 'status.json', 'models.json'):
        relative = preflight + '/' + name
        _, path = read_peer_file(peer_root, relative); pins[relative] = file_hash(path)
    return {'peer': peer, 'provider': provider, 'reservation': 1000000, 'risk_policy': RISK_POLICY,
            'diagnostic_usage': usage, 'diagnostic_invoice': invoice, 'history_runs': [peer['run_name']],
            'files_sha256': pins, 'preflight_run': preflight,
            'paired_inputs': {k: config[k] for k in ('H_size', 'population_size', 'cross_parents',
                'mutation_parents', 'initialization_cap', 'generations', 'attempts_per_generation',
                'instance_timeout', 'review_timeout', 'training_diagnostics')},
            'dataset': protocol.get('dataset'),
            'H_scope': config['conditional_research'].get('scope_approval'),
            'state_scheduler_parser_sha256': {name: protocol.get('implementation', {}).get('files', {}).get(name)
                for name in ('code/fjsp_usage/offline_v2.py', 'code/fjsp_usage/research/scheduler.py',
                    'code/llm4ad/task/optimization/fjsp_set/scheduler.py',
                    'code/llm4ad/task/optimization/fjsp_set/instances.py')},
            'notice': 'Dynamic risk envelope matches peer; public tariff is neither invoice nor certified hard maximum.'}


def check_live_tariff(secret, metadata_pacer=None):
    replies = {}
    for path in ('/api/pricing', '/api/status', '/v1/models'):
        connection = http.client.HTTPSConnection('leafapi.cc', timeout=15)
        try:
            headers = {'Accept': 'application/json', 'Cache-Control': 'no-cache'}
            if path == '/v1/models': headers['Authorization'] = 'Bearer ' + secret
            def query():
                connection.request('GET', path, headers=headers)
                response = connection.getresponse(); raw = response.read(2097153)
                if response.status != 200 or len(raw) > 2097152: raise BudgetStop('live new-model metadata unavailable')
                return json.loads(raw)
            replies[path] = metadata_pacer.call(path, query) if metadata_pacer else query()
        except (ValueError, OSError):
            raise BudgetStop('live new-model metadata unavailable; no fallback') from None
        finally: connection.close()
    check_preflight({'success': replies['/api/pricing'].get('success'), 'inference_requests': 0,
        'models': replies['/api/pricing'].get('data', []), 'group_ratio': replies['/api/pricing'].get('group_ratio', {})},
        {'public_fields': replies['/api/status'].get('data', {})},
        {'locked_model_listed': any(r.get('id') == MODEL for r in replies['/v1/models'].get('data', []))})
    return {'checked_at': time.time(), 'model': MODEL, 'expression': EXPRESSION,
            'certified_provider_upper_bound': False}


class Gpt61UsageQuota(QuotaGuardedTransport):
    def __init__(self, *args, tariff_query=check_live_tariff, **kwargs):
        self.tariff_query = tariff_query; self._tariff_at = None
        super().__init__(*args, **kwargs)

    def reservation_for(self, prompt):
        return risk_reservation(prompt, self.config.provider_migration['risk_policy'])['points']

    def preflight(self, prompt):
        if self._tariff_at is None or self.clock() - self._tariff_at >= self.config.platform_quota_query_interval:
            try: self.data['latest_tariff_check'] = self.tariff_query(self.transport.secret)
            except BudgetStop as exc: self.halt(str(exc)); raise
            self.save(); self._tariff_at = self.clock()
        super().preflight(prompt)

    def dispatch(self, key, prompt, *, kind='U', on_sent=lambda: None):
        def sent():
            self.data['records'][key]['risk_basis'] = risk_reservation(prompt)
            self.save(); on_sent()
        return super().dispatch(key, prompt, kind=kind, on_sent=sent)
