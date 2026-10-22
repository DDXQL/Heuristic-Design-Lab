"""One-shot full B1 INIT non-stream diagnostic; prepare/check/status are offline.

No H/U execution, datasets, search or financial queries. Real run needs a new
T1-D4B approval. Reuses public transport, journal, recorder and static parser.
"""
import argparse
from dataclasses import asdict, replace
import hashlib
from pathlib import Path

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.attempt_budget import AttemptJournal, CIRCUIT_VERSION
from fjsp_usage.research_real.budget import BudgetStop, validate_usage
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.real_transport import JsonCandidateTransport
from tools.t1_d1_diagnostic import ROOT, SOURCE, SOURCE_PROMPT, PROMPT_SHA, B1_PROTOCOL_SHA, sha, read, validate_reply
from tools.t1_d2_prompt_ab import TimedRecorder, DEPENDENCIES as D2_DEPENDENCIES

VERSION = 'T1-D4-full-B1-INIT-nonstream-v1-20261022'
DEFAULT = ROOT/'runs/t1-d4-full-b1-init-nonstream-v1-20261022'
ENTRY = 'tools/t1_d4_nonstream_init.py'
DEPENDENCIES = (*D2_DEPENDENCIES, ENTRY)
ENV_FILE = (ROOT.parent/'FJSP-Heuristic-Research/.env.leafapi.local').resolve()
LOGICAL_ID = 'B1-INIT'
POLICY = {'version': CIRCUIT_VERSION, 'logical_candidate_cap': 1, 'api_attempt_cap': 1,
          'per_candidate_attempt_cap': 1, 'retry_backoff_seconds': [],
          'protocol_error_circuit_threshold': 1}


def directory_path(directory):
    directory = Path(directory).resolve()
    if (not directory.name.startswith('t1-d4-') or
            (directory.is_relative_to(ROOT/'runs') and directory.parent != ROOT/'runs')):
        raise ValueError('independent t1-d4-* directory required')
    for name in ('Protocol.json', 'Protocol.sha256', 'config.pending.json', 'Source_provenance.json',
                 'Prompt.txt', 'Authorization.json', 'checkpoint.json', 'status.json',
                 'requests/attempts.json', 'wire_responses', 'send_times', 'response.txt',
                 'Response.json', 'Diagnostic_result.json'):
        if not (directory/name).resolve().is_relative_to(directory):
            raise ValueError('D4 output escapes independent directory')
    return directory


def source_snapshot():
    """Read only five selected B1 source files; never touch its authorization."""
    raw = (SOURCE/SOURCE_PROMPT).read_bytes(); text = raw.decode('utf-8')
    original = read(SOURCE/'Protocol.json'); config = read(SOURCE/'config.pending.json')
    ledger_path = SOURCE/'r501/B/batch_requests.json'
    journal = read(ledger_path); rec = journal['requests']['B/init/000000']
    aid = 'r501/B/B/init/000000/attempt/01'; attempt = journal['api_attempts'][aid]
    wire_path = SOURCE/'wire_responses'/(hashlib.sha256(aid.encode()).hexdigest()+'.json')
    wire = read(wire_path); key = digest({'prompt': text, 'kind': 'U'})
    if (sha(SOURCE/'Protocol.json') != B1_PROTOCOL_SHA or original['config'] != config
            or hashlib.sha256(raw).hexdigest() != PROMPT_SHA or len(raw) != 21250
            or raw != rec['prompt'].encode() or rec['attempt_ids'][0] != aid
            or attempt['logical_id'] != 'B/init/000000' or wire['global_key'] != aid
            or not attempt['send_confirmed'] or not wire['send_confirmed']
            or rec['status'] != 'failed' or attempt['status'] != 'failed' or wire['status'] != 'wire_failed'
            or any(x != key for x in (rec['prompt_key'], attempt['prompt_key'], wire['prompt_key']))):
        raise ValueError('original B1 INIT identity/provenance differs')
    provider = config['provider']
    if (provider['model'] != 'gpt-6.1-sol' or provider['expected_response_model'] != 'gpt-6.1-sol'
            or provider['endpoint'] != 'https://leafapi.cc/v1/chat/completions'
            or provider['protocol'] != 'openai-chat-v1' or provider['max_output_tokens'] != 8192
            or provider['stream_response'] is not True
            or [provider[x] for x in ('connect_timeout','read_timeout','total_timeout')] != [10,240,300]):
        raise ValueError('original common provider or deadlines differ')
    files = [SOURCE/SOURCE_PROMPT, SOURCE/'Protocol.json', SOURCE/'config.pending.json', ledger_path, wire_path]
    provenance = {'source_run': str(SOURCE), 'source_prompt_file': str(SOURCE/SOURCE_PROMPT),
        'historical_logical_id': 'B/init/000000', 'historical_attempt_id': aid,
        'source_protocol_sha256': B1_PROTOCOL_SHA, 'prompt_sha256': PROMPT_SHA, 'utf8_bytes': len(raw),
        'historical_usage': attempt.get('usage'), 'source_files_sha256': {str(p): sha(p) for p in files},
        'provider_original': provider, 'provider_delta': {'stream_response': {'old': True, 'new': False}}}
    return raw, provenance, {**provider, 'stream_response': False}


def prepare(directory):
    directory = directory_path(directory)
    if directory.exists(): raise ValueError('never overwrite a D4 preparation or run')
    raw, source, provider = source_snapshot()
    config = ExperimentConfig(ProviderConfig(**provider), mode='real', total_request_cap=1,
                              request_budget=dict(POLICY))
    p = {'version': VERSION, 'stage': 'T1-D4B', 'experiment_id': directory.name,
        'run_directory': str(directory), 'config': config.payload(), 'logical_id': LOGICAL_ID,
        'prompt_sha256': PROMPT_SHA, 'prompt_bytes': len(raw), 'source_provenance_sha256': digest(source),
        'pins': {name: sha(ROOT/name) for name in DEPENDENCIES},
        'credential_source': str(ENV_FILE), 'credential_content_or_hash_recorded': False,
        'stream': False, 'stream_options': 'omitted', 'same_arm_retry': False,
        'complete_response_requires': ['text','id','locked_model','stop','validated_usage'],
        'static_U_check_only': True, 'execute_U': False, 'FJSP_evaluation': False,
        'data_loading': False, 'population': False, 'actual_cost': None,
        'no_financial_queries': True, 'enforceable_monetary_cap': False,
        'timeout_seconds': {'connect': 10, 'read': 240, 'total': 300},
        'timeout_or_unknown_send_consumes_attempt_no_resend': True,
        'response_storage': 'complete public-client normalized reply; not raw HTTP body or reasoning text'}
    directory.mkdir(parents=True)
    (directory/'Prompt.txt').write_bytes(raw)
    atomic_json(directory/'Source_provenance.json', source)
    atomic_json(directory/'config.pending.json', config.payload())
    atomic_json(directory/'Protocol.json', p)
    (directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    atomic_json(directory/'Budget_plan.json', {**POLICY, 'started': False, 'actual_cost': None})
    atomic_json(directory/'Authorization.template.json', approval(directory, False))
    return check(directory)


def check(directory):
    directory = directory_path(directory); p = read(directory/'Protocol.json')
    if (sha(directory/'Protocol.json') != (directory/'Protocol.sha256').read_text().strip()
            or p['version'] != VERSION or p['stage'] != 'T1-D4B'
            or p['run_directory'] != str(directory) or p['experiment_id'] != directory.name
            or p['config'] != read(directory/'config.pending.json') or p['config']['request_budget'] != POLICY
            or p['prompt_sha256'] != PROMPT_SHA or sha(directory/'Prompt.txt') != PROMPT_SHA
            or p['source_provenance_sha256'] != digest(read(directory/'Source_provenance.json'))
            or p['credential_source'] != str(ENV_FILE) or p['logical_id'] != LOGICAL_ID
            or p['config']['provider']['stream_response'] is not False
            or p['config']['provider']['max_output_tokens'] != 8192
            or set(p['pins']) != set(DEPENDENCIES)):
        raise ValueError('D4 frozen identity differs')
    for name, expected in p['pins'].items():
        if sha(ROOT/name) != expected: raise ValueError('D4 runtime differs: '+name)
    return p, ExperimentConfig.from_dict(p['config'])


def approval(directory, approved):
    return {'stage': 'T1-D4B', 'approved': approved, 'person': 'DDXQL',
        'protocol_sha256': sha(Path(directory)/'Protocol.json'), 'logical_task_cap': 1,
        'api_attempt_cap': 1, 'automatic_retries': False,
        'unknown_cost_risk_accepted': approved, 'no_U_execution_or_FJSP': True}


def require_approval(directory):
    p, c = check(directory); auth_path = Path(directory)/'Authorization.json'
    if not auth_path.exists() or read(auth_path) != approval(directory, True):
        raise BudgetStop('T1-D4B not authorized; offline preparation only')
    return p, replace(c, real_requests_authorized=True)


def result_row(directory, rec, attempt):
    m = attempt.get('metadata') or (attempt.get('reply') or {}).get('metadata', {})
    row = {'attempt_id': attempt['id'], 'response_id': rec.get('response_id'),
        'public_transport_received': rec['status'] == 'completed', 'complete_response': False,
        'output_legal': None, 'diagnostic_pass': False, 'usage': attempt.get('usage'), 'actual_cost': None,
        'attempt_reserved_at': attempt['started_at'], 'finished_at': attempt.get('finished_at'),
        'elapsed_seconds': attempt.get('elapsed_seconds'), 'send_confirmed': attempt['send_confirmed'],
        'send_confirmation_at': None, 'http_status': m.get('http_status'),
        'http_content_type': m.get('http_content_type'), 'gateway_request_id': m.get('gateway_request_id'),
        'metadata': m, 'error_type': attempt.get('error_type'), 'error': attempt.get('error'),
        'failure_stage': m.get('failure_stage'), 'finish_reason': m.get('finish_reason'),
        'response_model': m.get('model'), 'delivery_unknown': attempt['status'] in ('pending','interrupted_unknown'),
        'failure_class': None,
        'source': 'INTERFACE_DIAGNOSTIC_NOT_RESEARCH'}
    timing = Path(directory)/'send_times'/(hashlib.sha256(attempt['id'].encode()).hexdigest()+'.json')
    if timing.exists(): row['send_confirmation_at'] = read(timing)['send_confirmation_at']
    if rec['status'] != 'completed':
        if row['delivery_unknown']: row['failure_class'] = 'delivery_unknown'
        elif m.get('model') is not None and m['model'] != 'gpt-6.1-sol':
            row['failure_class'] = 'model_identity_mismatch'
        elif m.get('finish_reason') is not None and m['finish_reason'] != 'stop':
            row['failure_class'] = 'truncated_or_refused'
        elif m.get('temporary_network_failure') or 'total network deadline exceeded' in (attempt.get('error') or ''):
            row['failure_class'] = 'timeout_or_network_failure'
        elif m.get('http_status') is not None and m['http_status'] != 200:
            row['failure_class'] = 'HTTP_error'
        else: row['failure_class'] = 'response_protocol_or_unknown_error'
        return row
    # Preserve the first complete normalized public-client response before static checks.
    atomic_json(Path(directory)/'Response.json', attempt['reply'])
    (Path(directory)/'response.txt').write_text(rec['text'])
    try:
        if (validate_usage(rec.get('usage')) is None or m.get('finish_reason') != 'stop'
                or m.get('model') != 'gpt-6.1-sol' or not isinstance(m.get('id'), str) or not m['id']):
            raise ValueError('complete text, usage, stop and locked response identity required')
    except ValueError as exc:
        row.update(failure_stage='response_completeness', failure_class='incomplete_response_profile',
                   error_type=type(exc).__name__, error=str(exc))
        return row
    row['complete_response'] = True
    try: candidate = validate_reply(rec)
    except ValueError as exc:
        row.update(output_legal=False, failure_stage='U_static_validation', failure_class='invalid_U_output',
                   error_type=type(exc).__name__, error=str(exc)[:500])
    else:
        row.update(output_legal=True, diagnostic_pass=True, failure_stage=None, candidate=asdict(candidate))
    return row


def session(directory, config, transport, *, provenance):
    directory = directory_path(directory); p, _ = check(directory)
    if provenance == 'real':
        if require_approval(directory)[1].payload() != config.payload(): raise ValueError('approved config differs')
    if (provenance not in ('mock-only','real') or digest(config.payload()) !=
            digest({**p['config'], 'real_requests_authorized': config.real_requests_authorized})):
        raise ValueError('D4 config/provenance differs')
    cp, jp = directory/'checkpoint.json', directory/'requests/attempts.json'
    if cp.exists() and not jp.exists(): raise ValueError('missing D4 journal; never reset')
    if jp.exists() and not cp.exists() and read(jp)['requests']: raise ValueError('orphan D4 journal; never reset')
    if not jp.exists() and any((directory/'wire_responses').glob('*.json')):
        raise ValueError('orphan D4 wire; never reset')
    journal = AttemptJournal(jp, config=config, phase='T1-D4', transport=transport,
        context={'protocol_sha256': sha(directory/'Protocol.json'), 'provenance': provenance})
    if not jp.exists(): journal.save()  # Durable empty identity before the initial checkpoint.
    state = read(cp) if cp.exists() else {'protocol_sha256': sha(directory/'Protocol.json'),
        'journal_identity': journal.identity, 'provenance': provenance, 'phase': 'prepared', 'outcome': None}
    if (state['protocol_sha256'] != sha(directory/'Protocol.json') or state['journal_identity'] != journal.identity
            or state['provenance'] != provenance or list(journal.data['requests']) not in ([], [LOGICAL_ID])):
        raise ValueError('D4 checkpoint/request identity differs')
    for rec in journal.data['requests'].values():
        if (rec['prompt'].encode() != (directory/'Prompt.txt').read_bytes() or rec['kind'] != 'U'
                or rec['prompt_key'] != digest({'prompt': rec['prompt'], 'kind': 'U'})):
            raise ValueError('D4 saved prompt differs')
    if state['outcome']:
        rec = journal.data['requests'].get(LOGICAL_ID)
        if (not rec or state['outcome']['attempt_id'] not in rec['attempt_ids']
                or state['outcome']['response_id'] != rec.get('response_id')):
            raise ValueError('D4 saved outcome differs')
    if state['phase'] in ('completed','stopped_local'):
        atomic_json(directory/'status.json', {**state, 'budget': journal.summary(),
            'data_loaded': False, 'FJSP_evaluations': 0, 'U_executed': False})
        return state
    try:
        state['phase'] = 'running'; atomic_json(cp, state)
        check(directory)
        rec = journal.request(LOGICAL_ID, (directory/'Prompt.txt').read_text(), kind='U')
        attempt = journal.data['api_attempts'][rec['attempt_ids'][-1]]
        state.update(phase='completed', outcome=result_row(directory, rec, attempt))
        atomic_json(cp, state)
    except Exception as exc:
        state.update(phase='stopped_local', stop_reason='local_error:'+type(exc).__name__)
        atomic_json(cp, state); raise
    except BaseException:
        state['phase'] = 'interrupted'; atomic_json(cp, state); raise
    finally:
        atomic_json(directory/'status.json', {**state, 'budget': journal.summary(),
            'data_loaded': False, 'FJSP_evaluations': 0, 'U_executed': False})
    return state


def run_real(directory, env_file):
    _, config = require_approval(directory)
    if env_file is None or Path(env_file).resolve() != ENV_FILE:
        raise ValueError('explicit original-project credential path required')
    from fjsp_usage.research_real.leafapi import KEY_ENV, load_local_key
    import os
    os.environ[KEY_ENV] = load_local_key(env_file)
    transport = TimedRecorder(JsonCandidateTransport(config), Path(directory)/'wire_responses', lambda: check(directory))
    return session(directory, config, transport, provenance='real')


def status(directory):
    check(directory); directory = Path(directory); jp = directory/'requests/attempts.json'
    j = read(jp) if jp.exists() else {'requests': {}, 'api_attempts': {}}
    return {'phase': read(directory/'checkpoint.json')['phase'] if (directory/'checkpoint.json').exists() else 'prepared',
        'logical_tasks': len(j['requests']), 'api_attempts': len(j['api_attempts']),
        'authorization_present': (directory/'Authorization.json').exists(), 'actual_cost': None}


def report(directory):
    check(directory); directory = Path(directory); saved = read(directory/'status.json')
    atomic_json(directory/'Diagnostic_result.json', {'version': VERSION, **saved,
        'claim': 'one nonstream interface observation only; no U execution, fitness or population'})
    return {'phase': saved['phase'], 'diagnostic_pass': (saved['outcome'] or {}).get('diagnostic_pass')}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=('prepare','check','status','run','report'))
    p.add_argument('--run-dir', type=Path, default=DEFAULT); p.add_argument('--env-file', type=Path)
    a = p.parse_args(); directory = directory_path(a.run_dir)
    if a.stage == 'prepare': prepare(directory); print(status(directory))
    elif a.stage in ('check','status'): print(status(directory))
    elif a.stage == 'report':
        with RunLock(directory): print(report(directory))
    else:
        require_approval(directory)
        with RunLock(directory): print(run_real(directory, a.env_file)['phase'])


if __name__ == '__main__': main()
