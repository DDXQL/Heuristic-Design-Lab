"""T1-D1 dedicated API diagnostic. prepare/check/status are offline; run needs approval.

No dataset, scheduler, population, selection, or old request ledger is accessed.
Only prepare reads the three explicitly named B1 prompt/config/protocol sources.
"""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess

from fjsp_usage.research.candidates import parse_response
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.attempt_budget import AttemptJournal, CIRCUIT_VERSION
from fjsp_usage.research_real.budget import BudgetStop, validate_usage
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.real_transport import JsonCandidateTransport, WIRE_VERSION
from fjsp_usage.usage_v2 import VERSION as U_VERSION
from fjsp_usage.usage_v2.access import WireRecorder

ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = '2eaabe09f4344d23199906def3152871846df8e0'
VERSION = 'T1-D1-stream-interface-diagnostic-v1-20261022'
DEFAULT = ROOT/'runs/t1-d1-stream-interface-v1-20261022-final'
SOURCE = ROOT/'runs/b1-full-h-free-seed501-k2-v1-20261021'
SOURCE_PROMPT = 'r501/B/prompts/B_init_000000'
PROMPT_SHA = '7307e5fd4d2d781ee0c546e809c5c3f1d0d694eec2915f9c1bc688a5ab68833e'
B1_PROTOCOL_SHA = 'd5ec72d53583c8dd5829b6a9d8f002511956c346127aad99348e1485f8e3e898'
POLICY = {'version': CIRCUIT_VERSION, 'logical_candidate_cap': 2, 'api_attempt_cap': 2,
          'per_candidate_attempt_cap': 1, 'retry_backoff_seconds': [],
          'protocol_error_circuit_threshold': 1}
RUNTIME = (
    'code/fjsp_usage/research_real/real_transport.py',
    'code/fjsp_usage/research_real/attempt_budget.py',
    'code/fjsp_usage/research_real/budget.py',
    'code/fjsp_usage/research_real/config.py',
    'code/fjsp_usage/research_real/locking.py',
    'code/fjsp_usage/research_real/leafapi.py',
    'code/fjsp_usage/usage_v2/access.py', 'code/fjsp_usage/usage_v2/candidates.py',
    'code/fjsp_usage/usage_v2/__init__.py', 'code/fjsp_usage/research/candidates.py',
    'code/fjsp_usage/research/events.py', 'code/fjsp_usage/research/protocol.py')
ENTRY = 'tools/t1_d1_diagnostic.py'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def directory_path(directory):
    directory = Path(directory).resolve()
    if (not directory.name.startswith('t1-d1-') or directory.is_relative_to(SOURCE)
            or (directory.is_relative_to(ROOT/'runs') and directory.parent != ROOT/'runs')):
        raise ValueError('dedicated t1-d1-* directory required; never reuse a research run')
    # Check outputs before reading any state; do not follow a symlink into old runs.
    for name in ('Protocol.json', 'Protocol.sha256', 'Prompt.txt', 'config.pending.json',
                 'Budget_plan.json', 'Authorization.json', 'Diagnostic_checkpoint.json',
                 'Diagnostic_status.json', 'requests/attempts.json', 'wire_responses', 'responses'):
        if not (directory/name).resolve().is_relative_to(directory):
            raise ValueError('diagnostic files must stay inside the independent directory')
    return directory


def prepare(directory):
    directory = directory_path(directory)
    if directory.exists():
        raise ValueError('preparation already exists; never overwrite frozen inputs')
    # Whitelist exactly these historical files. No old authorization/ledger/checkpoint.
    source_protocol = read(SOURCE/'Protocol.json')
    source_config = read(SOURCE/'config.pending.json')
    prompt = (SOURCE/SOURCE_PROMPT).read_bytes()
    if (sha(SOURCE/'Protocol.json') != B1_PROTOCOL_SHA
            or hashlib.sha256(prompt).hexdigest() != PROMPT_SHA
            or source_protocol['config'] != source_config):
        raise ValueError('original B1 prompt/config/protocol identity differs')
    provider = source_config['provider']
    if (provider['model'] != 'gpt-6.1-sol' or provider['expected_response_model'] != 'gpt-6.1-sol'
            or provider['max_output_tokens'] != 8192 or provider['stream_response'] is not True):
        raise ValueError('original common model/stream/output parameters required')
    pins = {}
    for name in RUNTIME:
        blob = subprocess.check_output(['git', 'show', BASE_COMMIT+':'+name], cwd=ROOT)
        pins[name] = hashlib.sha256(blob).hexdigest()
        if sha(ROOT/name) != pins[name]:
            raise ValueError('T1 implementation differs: '+name)
    pins[ENTRY] = sha(ROOT/ENTRY)
    config = ExperimentConfig(ProviderConfig(**provider), mode='real',
                              total_request_cap=2, request_budget=dict(POLICY))
    protocol = {'version': VERSION, 'stage': 'T1-D1', 'T1_commit': BASE_COMMIT,
        'experiment_id': directory.name, 'run_directory': str(directory),
        'transport_version': WIRE_VERSION, 'purpose': 'API_DIAGNOSTIC_ONLY_NOT_B1_RESEARCH',
        'config': config.payload(), 'source_files': {n: sha(SOURCE/n) for n in
            ('Protocol.json', 'config.pending.json', SOURCE_PROMPT)},
        'source_directory': str(SOURCE), 'H_order_from_source': source_protocol['H_order'],
        'prompt_sha256': PROMPT_SHA, 'prompt_bytes': len(prompt), 'pins': pins,
        'validation': {'interface_version': U_VERSION, 'member_count': 10,
            'AST_duplicates_allowed': True, 'execute_U': False,
            'DONE_and_identity_evidence': 'frozen T1 decode_stream success path'},
        'first_failure_stops_batch': True, 'same_prompt_for_both_tasks': True,
        'data_loading': False, 'FJSP_evaluation': False, 'population': False,
        'cost': {'actual_cost': None, 'no_account_or_billing_queries': True,
                 'suggested_risk_budget_cny': 5, 'enforceable_monetary_cap': False}}
    directory.mkdir(parents=True)
    (directory/'Prompt.txt').write_bytes(prompt)
    atomic_json(directory/'config.pending.json', config.payload())
    atomic_json(directory/'Protocol.json', protocol)
    (directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    atomic_json(directory/'Budget_plan.json', {**POLICY, 'requests_started': False,
        'logical_tasks_reserved': 0, 'api_attempts_reserved': 0, 'actual_cost': None})
    atomic_json(directory/'Authorization.template.json', approval(directory, approved=False))
    return check(directory)


def check(directory):
    directory = directory_path(directory)
    protocol = read(directory/'Protocol.json')
    if (sha(directory/'Protocol.json') != (directory/'Protocol.sha256').read_text().strip()
            or protocol['version'] != VERSION or protocol['T1_commit'] != BASE_COMMIT
            or protocol['experiment_id'] != directory.name or protocol['run_directory'] != str(directory)
            or protocol['transport_version'] != WIRE_VERSION
            or protocol['prompt_sha256'] != PROMPT_SHA or sha(directory/'Prompt.txt') != PROMPT_SHA
            or read(directory/'config.pending.json') != protocol['config']
            or protocol['config']['request_budget'] != POLICY
            or set(protocol['pins']) != set(RUNTIME) | {ENTRY}):
        raise ValueError('diagnostic frozen identity differs')
    for name, expected in protocol['pins'].items():
        if sha(ROOT/name) != expected:
            raise ValueError('diagnostic runtime changed: '+name)
    return protocol, ExperimentConfig.from_dict(protocol['config'])


def approval(directory, *, approved):
    return {'stage': 'T1-D1', 'approved': approved, 'person': 'DDXQL',
        'protocol_sha256': sha(Path(directory)/'Protocol.json'),
        'logical_task_cap': 2, 'api_attempt_cap': 2, 'per_task_attempt_cap': 1,
        'unknown_cost_risk_accepted': approved, 'no_research_or_scheduling': True}


def require_approval(directory):
    protocol, config = check(directory)
    path = Path(directory)/'Authorization.json'
    auth = read(path) if path.exists() else {}
    if (auth != approval(directory, approved=True) or auth.get('approved') is not True
            or auth.get('unknown_cost_risk_accepted') is not True):
        raise BudgetStop('T1-D1 real execution not authorized; preparation/Mock only')
    return protocol, replace(config, real_requests_authorized=True)


def validate_reply(record):
    metadata = record.get('response_metadata', {})
    if (validate_usage(record.get('usage')) is None or metadata.get('finish_reason') != 'stop'
            or metadata.get('model') != 'gpt-6.1-sol' or not isinstance(metadata.get('id'), str)
            or not metadata['id']):
        raise ValueError('complete text/usage/stop/locked identity required')
    # Static validation only. No compile_candidate, h scoring or state sampling.
    return parse_response(record['text'], kind='U', interface_version=U_VERSION, member_count=10)


def session(directory, config, transport, *, provenance):
    """Used by authorized real entry or temporary-directory Mock tests only."""
    directory = directory_path(directory)
    protocol, _ = check(directory)
    if provenance == 'real':
        _, approved_config = require_approval(directory)
        if approved_config.payload() != config.payload():
            raise ValueError('authorized real diagnostic config required')
    expected_config = {**protocol['config'], 'real_requests_authorized': config.real_requests_authorized}
    if digest(config.payload()) != digest(expected_config) or provenance not in ('real', 'mock-only'):
        raise ValueError('diagnostic runtime config/provenance differs')
    checkpoint, journal_path = directory/'Diagnostic_checkpoint.json', directory/'requests/attempts.json'
    if checkpoint.exists() and not journal_path.exists():
        saved = read(checkpoint)
        if saved['outcomes'] or saved['inflight']:
            raise ValueError('missing diagnostic budget; never reset or replay')
    if journal_path.exists() and not checkpoint.exists() and read(journal_path)['requests']:
        raise ValueError('orphan diagnostic budget; do not recreate checkpoint')
    journal = AttemptJournal(journal_path, config=config,
        context={'protocol_sha256': sha(directory/'Protocol.json'), 'provenance': provenance},
        phase='T1-D1', transport=transport)
    state = read(checkpoint) if checkpoint.exists() else {
        'protocol_sha256': sha(directory/'Protocol.json'), 'provenance': provenance,
        'journal_identity': journal.identity, 'phase': 'prepared', 'inflight': None, 'outcomes': []}
    if (state['protocol_sha256'] != sha(directory/'Protocol.json')
            or state['journal_identity'] != journal.identity or state['provenance'] != provenance
            or not len(state['outcomes']) <= journal.calls <= len(state['outcomes'])+1):
        raise ValueError('diagnostic checkpoint/budget identity or counts differ')
    expected_ids = ['D1/'+f'{n:06d}' for n in range(2)]
    if ([r['id'] for r in state['outcomes']] != expected_ids[:len(state['outcomes'])]
            or list(journal.data['requests']) != expected_ids[:journal.calls]
            or (journal.calls > len(state['outcomes']) and state['inflight'] != expected_ids[len(state['outcomes'])])):
        raise ValueError('diagnostic logical identities differ; no automatic recovery')
    prompt = (directory/'Prompt.txt').read_text()
    if (hashlib.sha256(prompt.encode()).hexdigest() != PROMPT_SHA
            or any(r['prompt'] != prompt for r in journal.data['requests'].values())):
        raise ValueError('diagnostic saved request prompt differs')
    for outcome in state['outcomes']:
        record = journal.data['requests'][outcome['id']]
        if (outcome['attempt_ids'] != record['attempt_ids']
                or outcome['accepted_response_id'] != record.get('response_id')
                or (outcome['valid'] and record['status'] != 'completed')):
            raise ValueError('diagnostic saved outcome/response differs')
    if state['phase'] in ('completed', 'stopped'):
        return state
    try:
        for index in range(len(state['outcomes']), 2):
            check(directory)
            identifier = expected_ids[index]
            state.update(phase='running', inflight=identifier)
            atomic_json(checkpoint, state)
            record = journal.request(identifier, prompt, kind='U')
            outcome = {'id': identifier, 'accepted_response_id': record.get('response_id'),
                'attempt_ids': list(record['attempt_ids']), 'valid': False,
                'source': 'INTERFACE_DIAGNOSTIC_ONLY', 'evaluated': False}
            if record['status'] == 'completed':
                response_dir = directory/'responses'; response_dir.mkdir(exist_ok=True)
                (response_dir/f'{index:02d}.txt').write_text(record['text'])
                try:
                    candidate = validate_reply(record)
                except ValueError as exc:
                    outcome.update(status='output_contract_failed', error_type=type(exc).__name__,
                                   error=transport.redact(str(exc))[:500])
                else:
                    outcome.update(status='passed', valid=True, candidate=asdict(candidate),
                        DONE_evidence=protocol['validation']['DONE_and_identity_evidence'])
            else:
                attempt = journal.data['api_attempts'][record['attempt_ids'][-1]]
                category = attempt.get('metadata', {}).get('failure_class', 'unknown')
                if attempt['status'] == 'interrupted_unknown': category = 'unknown_delivery'
                elif attempt.get('retryable'): category = 'temporary'
                elif (journal.data['halt_reason'] or '').startswith('permanent_'): category = 'permanent'
                outcome.update(status='transport_failed', error_type=record.get('error_type'),
                               failure_class=category, retry_reason=attempt.get('retry_reason'))
            state['outcomes'].append(outcome)
            state.update(inflight=None, phase='running' if outcome['valid'] else 'stopped')
            atomic_json(checkpoint, state)
            if not outcome['valid']:
                break  # Includes temporary failure, invalid code and unknown delivery.
        else:
            state.update(phase='completed')
            atomic_json(checkpoint, state)
    except BaseException:
        state['phase'] = 'interrupted'
        atomic_json(checkpoint, state)
        raise
    finally:
        atomic_json(directory/'Diagnostic_status.json', {'version': VERSION, **state,
            'budget': journal.summary(), 'actual_cost': None, 'data_loaded': False,
            'FJSP_evaluations': 0, 'research_population_created': False})
    return state


def run_real(directory, env_file):
    _, config = require_approval(directory)  # Before credential reads/client construction.
    if env_file is None:
        raise ValueError('explicit credential file required after T1-D1 authorization')
    from fjsp_usage.research_real.leafapi import load_local_key, KEY_ENV
    import os
    os.environ[KEY_ENV] = load_local_key(env_file)
    transport = WireRecorder(JsonCandidateTransport(config), Path(directory)/'wire_responses',
                             verify=lambda: check(directory))
    return session(directory, config, transport, provenance='real')


def status(directory):
    check(directory)
    directory = Path(directory)
    path = directory/'requests/attempts.json'
    journal = read(path) if path.exists() else {'requests': {}, 'api_attempts': {}}
    checkpoint = directory/'Diagnostic_checkpoint.json'
    return {'phase': read(checkpoint)['phase'] if checkpoint.exists() else 'prepared',
            'logical_tasks': len(journal['requests']), 'api_attempts': len(journal['api_attempts']),
            'actual_cost': None, 'authorization_present': (directory/'Authorization.json').exists()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'check', 'status', 'run'))
    parser.add_argument('--run-dir', type=Path, default=DEFAULT)
    parser.add_argument('--env-file', type=Path)
    args = parser.parse_args(); directory = directory_path(args.run_dir)
    if args.stage == 'prepare':
        prepare(directory); print(status(directory))
    elif args.stage in ('check', 'status'):
        print(status(directory))
    else:
        require_approval(directory)
        with RunLock(directory):
            print(run_real(directory, args.env_file)['phase'])


if __name__ == '__main__':
    main()
