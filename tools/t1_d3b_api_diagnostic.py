"""Isolated T1-D3B simple-prompt stream comparison.

prepare/check/mock-test are offline. `run` requires a separate authorization
record and reads the existing original-project credential file in process.
No FJSP data, candidates, fitness, or prior research run is loaded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.attempt_budget import AttemptJournal, CIRCUIT_VERSION
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.real_transport import JsonCandidateTransport, WIRE_VERSION
from fjsp_usage.usage_v2.access import WireRecorder

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / 'runs/t1-d3b-api-pair-20261022'
ORIGINAL_ENV = (ROOT.parent / 'FJSP-Heuristic-Research' / '.env.leafapi.local').resolve()
VERSION = 'T1-D3B-simple-prompt-stream-pair-v1-20261022'
BASE_COMMIT = 'c4e388613c2e0928d209dcd9d91e3c5826630675'
PROMPT = '你好，请只回复OK'
MODEL = 'gpt-6.1-sol'
ENDPOINT = 'https://leafapi.cc/v1/chat/completions'
MAX_TOKENS = 128
GROUPS = ('A', 'B')
POLICY = {
    'version': CIRCUIT_VERSION,
    'logical_candidate_cap': 1,
    'api_attempt_cap': 1,
    'per_candidate_attempt_cap': 1,
    'retry_backoff_seconds': [],
    'protocol_error_circuit_threshold': 1,
}
PINNED_SOURCES = (
    'code/fjsp_usage/research_real/config.py',
    'code/fjsp_usage/research_real/real_transport.py',
    'code/fjsp_usage/research_real/attempt_budget.py',
    'code/fjsp_usage/usage_v2/access.py',
    'code/fjsp_usage/research/events.py',
    'code/fjsp_usage/research/protocol.py',
)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def file_sha256(path):
    return sha256_bytes(Path(path).read_bytes())


def build_protocol():
    return {
        'version': VERSION,
        'stage': 'T1-D3B',
        'base_commit': BASE_COMMIT,
        'purpose': 'simple_prompt_api_transport_diagnostic_only',
        'credential_source': '../FJSP-Heuristic-Research/.env.leafapi.local',
        'credential_env_var': 'LEAFAPI_API_KEY',
        'credential_content_or_hash_recorded': False,
        'model': MODEL,
        'expected_response_model': MODEL,
        'endpoint': ENDPOINT,
        'provider_protocol': 'openai-chat-v1',
        'prompt': PROMPT,
        'common_generation': {
            'max_output_tokens': MAX_TOKENS,
            'temperature': None,
            'reasoning_effort': None,
            'n': 1,
            'connect_timeout': 10,
            'read_timeout': 240,
            'total_timeout': 300,
        },
        'groups': {
            'A': {'stream_response': False, 'stream_options': None},
            'B': {'stream_response': True, 'stream_options': {'include_usage': True}},
        },
        'order': list(GROUPS),
        'budget': {
            'logical_requests_per_group': 1,
            'attempts_per_group': 1,
            'total_attempts': 2,
            'automatic_retries': False,
            'append_requests': False,
        },
        'continuation_policy': {
            'ordinary_http_200_protocol_error_may_continue_to_next_group': True,
            'stop_on_auth_quota_rate_limit_model_identity_or_unknown_send': True,
        },
        'scope': {
            'real_requests_authorized': False,
            'account_or_invoice_queries': False,
            'fjsp_evaluation': False,
            'train21_validation11_test28_access': False,
            'candidate_or_fitness_creation': False,
        },
        'transport_version': WIRE_VERSION,
        'source_sha256': {name: file_sha256(ROOT / name) for name in PINNED_SOURCES},
        'response_fields': [
            'http_status', 'gateway_request_id', 'complete_response', 'response_text',
            'finish_reason', 'usage', 'error_type', 'redacted_error_metadata',
        ],
    }


def canonical_json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def protocol_paths(directory):
    directory = Path(directory)
    return directory / 'Protocol.json', directory / 'Protocol.sha256'


def write_protocol(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    protocol_path, sha_path = protocol_paths(directory)
    raw = canonical_json(build_protocol())
    protocol_path.write_bytes(raw)
    sha_path.write_text(sha256_bytes(raw) + '\n', encoding='ascii')
    return sha256_bytes(raw)


def verify_protocol(directory):
    protocol_path, sha_path = protocol_paths(directory)
    raw = protocol_path.read_bytes()
    expected = sha_path.read_text(encoding='ascii').strip()
    actual = sha256_bytes(raw)
    if actual != expected:
        raise ValueError('T1-D3B frozen protocol SHA256 mismatch')
    saved = json.loads(raw)
    if saved != build_protocol():
        raise ValueError('T1-D3B protocol or pinned public runtime changed')
    return saved, actual


def make_config(stream, *, authorized):
    provider = ProviderConfig(
        endpoint=ENDPOINT,
        model=MODEL,
        protocol='openai-chat-v1',
        api_key_env='LEAFAPI_API_KEY',
        connect_timeout=10,
        read_timeout=240,
        total_timeout=300,
        max_output_tokens=MAX_TOKENS,
        output_token_reservation=MAX_TOKENS,
        temperature=None,
        reasoning_effort=None,
        expected_response_model=MODEL,
        stream_response=stream,
    )
    return ExperimentConfig(
        provider=provider,
        mode='real',
        real_requests_authorized=authorized,
        total_request_cap=1,
        request_budget=dict(POLICY),
    )


def _attempt_for(journal, request):
    ids = request.get('attempt_ids', [])
    return journal.data['api_attempts'].get(ids[-1]) if ids else None


def _is_global_stop(request, attempt):
    if attempt is None or not attempt.get('send_confirmed'):
        return True, 'send_state_unknown_or_unconfirmed'
    metadata = attempt.get('metadata') or request.get('response_metadata') or {}
    status = metadata.get('http_status')
    upstream = metadata.get('upstream_http_status')
    code = str(metadata.get('error_code', '')).lower()
    error_type = str(metadata.get('error_type', '')).lower()
    error_text = str((attempt or {}).get('error') or request.get('error') or '').lower()
    if status in (401, 402, 403, 404, 429) or upstream in (401, 402, 403, 404, 429):
        return True, 'authentication_quota_model_or_rate_limit_response'
    if metadata.get('failure_class') == 'permanent' or any(term in code + ' ' + error_type for term in (
        'authentication', 'unauthorized', 'invalid_api_key', 'permission_denied',
        'insufficient_quota', 'insufficient_balance', 'model_not_found',
    )):
        return True, 'authentication_quota_or_model_error'
    if metadata.get('identity_change', {}).get('field') == 'model':
        return True, 'response_model_identity_changed'
    stream_observation = metadata.get('stream_observation') or {}
    if stream_observation.get('model_matches_expected') is False:
        return True, 'response_model_does_not_match_locked_model'
    response_model = metadata.get('model')
    if response_model is not None and response_model != MODEL:
        return True, 'response_model_does_not_match_locked_model'
    if 'model differs from locked model' in error_text or 'response model differs from locked model' in error_text:
        return True, 'response_model_does_not_match_locked_model'
    if metadata.get('temporary_network_failure') or status is None:
        return True, 'response_or_delivery_status_unknown'
    if request.get('status') == 'completed':
        return False, None
    # A complete HTTP 200 carrying a protocol/stream error is local to this
    # transport mode. The failed slot remains consumed; the next group may run.
    if status == 200 and not metadata.get('failure_class') == 'permanent':
        return False, None
    return True, 'non_protocol_or_unclassified_failure'


def _group_result(journal, request):
    attempt = _attempt_for(journal, request)
    metadata = (attempt or {}).get('metadata') or request.get('response_metadata') or {}
    reply = (attempt or {}).get('reply') or {}
    complete = request.get('status') == 'completed' and attempt is not None
    return {
        'status': 'completed' if complete else 'failed',
        'send_confirmed': bool((attempt or {}).get('send_confirmed')),
        'http_status': metadata.get('http_status'),
        'gateway_request_id': metadata.get('gateway_request_id'),
        'complete_response': complete,
        'response_text': request.get('text') if complete else None,
        # The shared decoder keeps the observed/validated finish reason in
        # response metadata; stream completion additionally requires stop+DONE.
        'finish_reason': metadata.get('finish_reason') if complete else None,
        'usage': request.get('usage') if complete else (attempt or {}).get('usage'),
        'error_type': (attempt or {}).get('error_type') or request.get('error_type'),
        'error': (attempt or {}).get('error') or request.get('error'),
        'redacted_error_metadata': metadata,
        'attempt_id': (attempt or {}).get('id'),
    }


def run_groups(directory, transport_factory):
    """Execute/recover A then B using injected transports; tests inject only Mocks."""
    directory = Path(directory)
    _, protocol_sha = verify_protocol(directory)
    result_path = directory / 'T1-D3B_result.json'
    state = json.loads(result_path.read_text()) if result_path.exists() else {
        'protocol_sha256': protocol_sha,
        'status': 'prepared',
        'groups': {},
        'next_group': 'A',
        'global_stop_reason': None,
    }
    if state.get('protocol_sha256') != protocol_sha:
        raise ValueError('T1-D3B result/checkpoint belongs to another protocol')
    if state.get('global_stop_reason'):
        return state

    group_a_dir = directory / 'requests' / 'A'
    group_b_dir = directory / 'requests' / 'B'
    if group_b_dir.exists() and not group_a_dir.exists():
        state.update(status='stopped', global_stop_reason='orphan_B_journal_without_A_history')
        atomic_json(result_path, state)
        return state
    if 'A' in state['groups'] and not (group_a_dir / 'attempts.json').exists():
        state.update(status='stopped', global_stop_reason='A_result_without_A_attempt_journal')
        atomic_json(result_path, state)
        return state
    if 'B' in state['groups'] and not (group_b_dir / 'attempts.json').exists():
        state.update(status='stopped', global_stop_reason='B_result_without_B_attempt_journal')
        atomic_json(result_path, state)
        return state

    for group in GROUPS:
        if group in state['groups']:
            prior = state['groups'][group]
            if prior.get('global_stop'):
                state.update(status='stopped', global_stop_reason=prior['global_stop'])
                break
            continue
        config = make_config(group == 'B', authorized=True)
        group_dir = directory / 'requests' / group
        group_dir.mkdir(parents=True, exist_ok=True)
        wire_dir = group_dir / 'wire_responses'
        inner = transport_factory(config, wire_dir)
        transport = WireRecorder(inner, wire_dir, verify=lambda: verify_protocol(directory))
        journal = AttemptJournal(
            group_dir / 'attempts.json', config=config,
            context={'protocol_sha256': protocol_sha, 'group': group},
            phase='T1-D3B/' + group, transport=transport,
        )
        request = journal.request('hello-000001', PROMPT, kind='diagnostic')
        summary = _group_result(journal, request)
        global_stop, reason = _is_global_stop(request, _attempt_for(journal, request))
        summary['global_stop'] = reason if global_stop else None
        state['groups'][group] = summary
        state['next_group'] = 'B' if group == 'A' else None
        if global_stop:
            state.update(status='stopped', global_stop_reason=reason)
        else:
            state['status'] = 'completed' if group == 'B' else 'running'
        atomic_json(result_path, state)
        if global_stop:
            break
    if state['status'] == 'running' and 'B' in state['groups']:
        state['status'] = 'completed'
    atomic_json(result_path, state)
    return state


def _real_transport_factory(config, wire_dir):
    return JsonCandidateTransport(config)


def verify_authorization(directory, protocol_sha):
    path = Path(directory) / 'T1-D3B_authorization.json'
    auth = json.loads(path.read_text())
    expected = {
        'stage': 'T1-D3B',
        'approved': True,
        'protocol_sha256': protocol_sha,
        'logical_request_cap': 2,
        'api_attempt_cap': 2,
        'groups': ['A', 'B'],
        'automatic_retries': False,
        'authorization_source': 'explicit user authorization in current conversation',
    }
    if auth != expected:
        raise ValueError('separate T1-D3B authorization does not match the frozen two-request scope')


def run_real(directory):
    protocol, protocol_sha = verify_protocol(directory)
    verify_authorization(directory, protocol_sha)
    if not ORIGINAL_ENV.is_file() or not os.access(ORIGINAL_ENV, os.R_OK):
        raise ValueError('original-project credential file is unavailable; no request sent')
    from fjsp_usage.research_real.leafapi import KEY_ENV, load_local_key
    os.environ[KEY_ENV] = load_local_key(ORIGINAL_ENV)
    return run_groups(directory, _real_transport_factory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'check', 'run'))
    args = parser.parse_args(argv)
    directory = DEFAULT_RUN.resolve()
    if args.stage == 'prepare':
        sha = write_protocol(directory)
        print(json.dumps({'status': 'prepared_not_authorized', 'protocol_sha256': sha,
                          'run_directory': str(directory)}, ensure_ascii=False))
        return 0
    protocol, sha = verify_protocol(directory)
    if args.stage == 'check':
        print(json.dumps({'status': 'protocol_verified_not_authorized', 'protocol_sha256': sha,
                          'real_requests_authorized': protocol['scope']['real_requests_authorized'],
                          'authorization_present': (directory / 'T1-D3B_authorization.json').exists()},
                         ensure_ascii=False))
        return 0
    with RunLock(directory):
        result = run_real(directory)
    print(json.dumps({'status': result['status'], 'protocol_sha256': sha,
                      'groups': list(result['groups']), 'global_stop_reason': result.get('global_stop_reason')},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
