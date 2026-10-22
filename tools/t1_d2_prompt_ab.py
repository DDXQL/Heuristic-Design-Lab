"""T1-D2 prompt-paired interface diagnostic. Real run requires a new approval.

Only prepare reads selected historical request evidence. No search or FJSP.
"""
import argparse
import csv
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.attempt_budget import AttemptJournal, CIRCUIT_VERSION
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig
from fjsp_usage.research_real.real_transport import JsonCandidateTransport, OBSERVATION_VERSION
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.usage_v2.access import WireRecorder
from tools.t1_d1_diagnostic import ROOT, RUNTIME, sha, read, validate_reply

VERSION = 'T1-D2-B2-B1-prompt-paired-v1-20261022'
DEFAULT = ROOT/'runs/t1-d2-b2-b1-prompt-ab-v1-20261022'
ENTRY = 'tools/t1_d2_prompt_ab.py'
DEPENDENCIES = (*RUNTIME, 'tools/t1_d1_diagnostic.py', ENTRY)
POLICY = {'version': CIRCUIT_VERSION, 'logical_candidate_cap': 2, 'api_attempt_cap': 2,
          'per_candidate_attempt_cap': 1, 'retry_backoff_seconds': [],
          'protocol_error_circuit_threshold': 2}
SOURCES = {
    'A': ('h01-state-weight-search-seed501-batch-v3-20261020', 'budgeted_evolution_requests.json',
          'B/g0000/000000', 'CROSS', '3f9c60c00b3b92db43f5b8ceb596b31665449776a2377c96ffe9c1212033d167'),
    'B': ('b1-full-h-free-seed501-k2-v1-20261021', 'batch_requests.json',
          'B/init/000000', 'INIT', '7307e5fd4d2d781ee0c546e809c5c3f1d0d694eec2915f9c1bc688a5ab68833e')}
WINDOW_SECONDS = 900


def directory_path(directory):
    directory = Path(directory).resolve()
    if (not directory.name.startswith('t1-d2-') or
            (directory.is_relative_to(ROOT/'runs') and directory.parent != ROOT/'runs')):
        raise ValueError('independent t1-d2-* directory required')
    for name in ('Protocol.json', 'Protocol.sha256', 'config.pending.json', 'Source_provenance.json',
                 'Prompt_A.txt', 'Prompt_B.txt', 'Authorization.json', 'checkpoint.json',
                 'status.json', 'requests/attempts.json', 'wire_responses', 'send_times', 'responses'):
        if not (directory/name).resolve().is_relative_to(directory):
            raise ValueError('D2 path escapes independent directory')
    return directory


def historical_sources():
    prompts, origins, provider = {}, {}, None
    for arm, (name, ledger, logical, operator, expected_sha) in SOURCES.items():
        root = ROOT/'runs'/name
        ledger_path = root/'r501/B'/ledger
        journal = read(ledger_path); record = journal['requests'][logical]
        attempt_id = record.get('accepted_attempt_id', record['attempt_ids'][0])
        attempt = journal['api_attempts'][attempt_id]
        prompt_path = root/'r501/B/prompts'/logical.replace('/', '_')
        wire_path = root/'wire_responses'/(hashlib.sha256(attempt_id.encode()).hexdigest()+'.json')
        wire = read(wire_path); raw = prompt_path.read_bytes(); text = raw.decode('utf-8')
        key = digest({'prompt': text, 'kind': 'U'})
        if (sha(prompt_path) != expected_sha or raw != record['prompt'].encode()
                or not attempt['send_confirmed'] or not wire['send_confirmed']
                or attempt['logical_id'] != logical or wire['global_key'] != attempt_id
                or any(v != key for v in (record['prompt_key'], attempt['prompt_key'], wire['prompt_key']))):
            raise ValueError('historical prompt/request/wire source mismatch')
        if arm == 'A':
            if (record['status'] != 'completed' or attempt['status'] != 'completed'
                    or wire['status'] != 'wire_completed_before_settlement'
                    or wire['reply'] != attempt['reply'] or wire['reply']['text'] != record['text']
                    or record.get('response_metadata') != wire['reply'].get('metadata')
                    or record.get('usage') != attempt.get('usage') or attempt.get('usage') != wire['reply'].get('usage')
                    or 'AT LEAST TWO parents' not in text):
                raise ValueError('A must be the selected historical successful CROSS')
            validate_reply(record)  # AST only, no evaluation or fitness lookup.
        elif ('There are no parents.' not in text or record['status'] != 'failed'
                or attempt['status'] != 'failed' or wire['status'] != 'wire_failed'):
            raise ValueError('B must be the selected historical sent INIT')
        current = read(root/'config.pending.json')['provider']
        if provider is not None and current != provider:
            raise ValueError('historical providers differ; no silent parameter alignment')
        provider = current
        files = (prompt_path, ledger_path, wire_path, root/'config.pending.json')
        origins[arm] = {'source_run': str(root), 'historical_logical_id': logical,
            'historical_attempt_id': attempt_id, 'operator': operator,
            'prompt_file': str(prompt_path), 'prompt_sha256': expected_sha, 'utf8_bytes': len(raw),
            'historical_usage': attempt.get('usage'),
            'historical_reasoning_tokens_subset': (record.get('response_metadata') or {}).get('reasoning_tokens'),
            'historical_request_status': record['status'], 'historical_confirmed_send': True,
            'historical_wire_status': wire['status'], 'files_sha256': {str(p): sha(p) for p in files}}
        prompts[arm] = raw
    if (provider['model'] != 'gpt-6.1-sol' or provider['expected_response_model'] != 'gpt-6.1-sol'
            or provider['max_output_tokens'] != 8192 or provider['stream_response'] is not True):
        raise ValueError('locked common gpt61 streaming parameters required')
    return prompts, origins, provider


def prepare(directory):
    directory = directory_path(directory)
    if directory.exists(): raise ValueError('do not overwrite any existing D2 preparation')
    prompts, origins, provider = historical_sources()
    config = ExperimentConfig(ProviderConfig(**provider), mode='real', total_request_cap=2,
                              request_budget=dict(POLICY))
    protocol = {'version': VERSION, 'stage': 'T1-D2B', 'run_directory': str(directory),
        'experiment_id': directory.name, 'config': config.payload(), 'order': ['A', 'B'],
        'pair_window_seconds': WINDOW_SECONDS, 'observation_version': OBSERVATION_VERSION,
        'acceptance_reference_commit': '2eaabe09f4344d23199906def3152871846df8e0',
        'telemetry_delta_only': ['HTTP Content-Type', 'stream completion observations', 'send confirmation timestamp'],
        'pins': {name: sha(ROOT/name) for name in DEPENDENCIES},
        'prompt_sha256': {a: hashlib.sha256(p).hexdigest() for a, p in prompts.items()},
        'source_provenance_sha256': digest(origins), 'ordinary_failure_continue_other_arm': True,
        'same_arm_retry': False, 'source_or_model_or_unknown_delivery_failure_stops': True,
        'data_loading': False, 'FJSP_evaluation': False, 'population': False,
        'cost': {'actual_cost': None, 'known_static_tariff': None, 'no_financial_queries': True,
                 'enforceable_monetary_cap': False}}
    directory.mkdir(parents=True)
    for arm, raw in prompts.items(): (directory/f'Prompt_{arm}.txt').write_bytes(raw)
    atomic_json(directory/'Source_provenance.json', origins)
    atomic_json(directory/'config.pending.json', config.payload())
    atomic_json(directory/'Protocol.json', protocol)
    (directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    atomic_json(directory/'Budget_plan.json', {**POLICY, 'reserved_attempts': 0, 'started': False})
    atomic_json(directory/'Authorization.template.json', approval(directory, False))
    return check(directory)


def check(directory):
    directory = directory_path(directory); p = read(directory/'Protocol.json')
    if (sha(directory/'Protocol.json') != (directory/'Protocol.sha256').read_text().strip()
            or p['version'] != VERSION or p['run_directory'] != str(directory)
            or p['experiment_id'] != directory.name or p['order'] != ['A', 'B']
            or p['pair_window_seconds'] != WINDOW_SECONDS or p['observation_version'] != OBSERVATION_VERSION
            or p['config'] != read(directory/'config.pending.json') or p['config']['request_budget'] != POLICY
            or digest(read(directory/'Source_provenance.json')) != p['source_provenance_sha256']
            or set(p['pins']) != set(DEPENDENCIES)):
        raise ValueError('D2 frozen protocol identity differs')
    for name, h in p['pins'].items():
        if sha(ROOT/name) != h: raise ValueError('D2 frozen code differs: '+name)
    for arm, source in SOURCES.items():
        if p['prompt_sha256'][arm] != source[-1] or sha(directory/f'Prompt_{arm}.txt') != source[-1]:
            raise ValueError('D2 frozen prompt differs')
    return p, ExperimentConfig.from_dict(p['config'])


def approval(directory, approved):
    return {'stage': 'T1-D2B', 'approved': approved, 'person': 'DDXQL',
        'protocol_sha256': sha(Path(directory)/'Protocol.json'), 'api_attempt_cap': 2,
        'per_arm_attempt_cap': 1, 'continue_other_arm_after_ordinary_failure': True,
        'unknown_cost_risk_accepted': approved, 'no_research_or_scheduling': True}


def require_approval(directory):
    p, c = check(directory); path = Path(directory)/'Authorization.json'
    auth = read(path) if path.exists() else {}
    if (auth != approval(directory, True) or auth.get('approved') is not True
            or auth.get('unknown_cost_risk_accepted') is not True):
        raise BudgetStop('T1-D2B not authorized; offline preparation only')
    return p, replace(c, real_requests_authorized=True)


class TimedRecorder(WireRecorder):
    def dispatch(self, key, prompt, *, kind='U', on_sent=lambda: None):
        def sent():
            path = self.directory.parent/'send_times'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
            atomic_json(path, {'attempt_id': key, 'send_confirmation_at': time.time()})
            on_sent()
        return super().dispatch(key, prompt, kind=kind, on_sent=sent)


def safety(attempt, journal):
    m = attempt.get('metadata', attempt.get('reply', {}).get('metadata', {})) or {}
    obs = m.get('stream_observation', {})
    if attempt['status'] in ('pending', 'interrupted_unknown'):
        return 'global_unknown_delivery'
    if obs.get('model_matches_expected') is False:
        return 'global_locked_model_mismatch'
    if journal.data['halt_reason'] not in (None, 'transport_protocol_circuit_open'):
        return 'global_' + journal.data['halt_reason']
    if attempt['status'] == 'completed':
        if (not all(obs.get(k) is True for k in ('complete_text','stop_received','usage_received','usage_validated','DONE_received','model_matches_expected'))
                or obs.get('id_check') != 'observed_consistent' or obs.get('model_check') != 'observed_consistent'):
            return 'global_missing_complete_transport_profile'
        return None
    if not attempt['send_confirmed']: return 'global_unconfirmed_delivery'
    if ((m.get('http_status') == 200 and m.get('failure_stage') == 'sse_decode')
            or m.get('http_status') in (429, 502, 503, 504)):
        return None  # A finalized response failure, NOT retrying this group.
    return 'global_unclassified_transport_safety'


def outcome(directory, arm, record, attempt, journal):
    m = attempt.get('metadata', attempt.get('reply', {}).get('metadata', {})) or {}
    timing = Path(directory)/'send_times'/(hashlib.sha256(attempt['id'].encode()).hexdigest()+'.json')
    row = {'group': arm, 'logical_id': arm, 'attempt_id': attempt['id'],
        'response_id': record.get('response_id'), 'transport_success': record['status'] == 'completed',
        'output_legal': None, 'source': 'INTERFACE_DIAGNOSTIC_NOT_RESEARCH',
        'send_confirmation_at': read(timing)['send_confirmation_at'] if timing.exists() else None,
        'attempt_reserved_at': attempt['started_at'], 'finished_at': attempt.get('finished_at'),
        'elapsed_seconds': attempt.get('elapsed_seconds'), 'gateway_request_id': m.get('gateway_request_id'),
        'http_status': m.get('http_status'), 'http_content_type': m.get('http_content_type'),
        'stream_observation': m.get('stream_observation'), 'identity_change': m.get('identity_change'),
        'usage': attempt.get('usage'), 'actual_cost': None, 'error_type': attempt.get('error_type'),
        'error': attempt.get('error'), 'stage': m.get('failure_stage'),
        'global_stop_reason': safety(attempt, journal)}
    obs, usage = m.get('stream_observation', {}), attempt.get('usage') or {}
    row.update(data_events_seen=obs.get('data_events_seen'), complete_text=obs.get('complete_text'),
        stop_received=obs.get('stop_received'), usage_received=obs.get('usage_received'),
        DONE_received=obs.get('DONE_received'), id_check=obs.get('id_check'), model_check=obs.get('model_check'),
        input_tokens=usage.get('input_tokens'), output_tokens=usage.get('output_tokens'))
    if row['transport_success']:
        folder = Path(directory)/'responses'; folder.mkdir(exist_ok=True)
        (folder/f'{arm}.txt').write_text(record['text'])
        try: candidate = validate_reply(record)
        except ValueError as exc:
            row.update(output_legal=False, stage='U_static_validation', error_type=type(exc).__name__, error=str(exc)[:500])
        else: row.update(output_legal=True, stage='complete', candidate=asdict(candidate))
    return row


def session(directory, config, transport, *, provenance, clock=time.time):
    directory = directory_path(directory); p, _ = check(directory)
    if provenance == 'real':
        _, approved = require_approval(directory)
        if approved.payload() != config.payload(): raise ValueError('approved config differs')
    if (provenance not in ('real','mock-only') or digest(config.payload()) !=
            digest({**p['config'], 'real_requests_authorized': config.real_requests_authorized})):
        raise ValueError('D2 config/provenance differs')
    cp, jp = directory/'checkpoint.json', directory/'requests/attempts.json'
    if cp.exists() and not jp.exists() and (read(cp)['outcomes'] or read(cp)['inflight']):
        raise ValueError('missing D2 journal; never reset')
    if jp.exists() and not cp.exists() and read(jp)['requests']:
        raise ValueError('orphan D2 journal; never restart')
    journal = AttemptJournal(jp, config=config, phase='T1-D2', transport=transport,
        context={'protocol_sha256': sha(directory/'Protocol.json'), 'provenance': provenance})
    state = read(cp) if cp.exists() else {'protocol_sha256': sha(directory/'Protocol.json'),
        'journal_identity': journal.identity, 'provenance': provenance, 'phase': 'prepared',
        'outcomes': [], 'inflight': None, 'window_started_at': clock(), 'global_stop_reason': None}
    n = len(state['outcomes'])
    if (state['protocol_sha256'] != sha(directory/'Protocol.json') or state['journal_identity'] != journal.identity
            or state['provenance'] != provenance or not n <= journal.calls <= n+1
            or [o['group'] for o in state['outcomes']] != ['A','B'][:n]
            or list(journal.data['requests']) != ['A','B'][:journal.calls]
            or (journal.calls > n and state['inflight'] != ['A','B'][n])):
        raise ValueError('D2 checkpoint/request identity differs')
    for arm, rec in journal.data['requests'].items():
        if rec['prompt'].encode() != (directory/f'Prompt_{arm}.txt').read_bytes():
            raise ValueError('D2 saved prompt differs')
    for row in state['outcomes']:
        rec = journal.data['requests'][row['group']]
        if row['attempt_id'] not in rec['attempt_ids'] or row['response_id'] != rec.get('response_id'):
            raise ValueError('D2 saved outcome differs')
    cached_stop = next((r['global_stop_reason'] for r in state['outcomes'] if r['global_stop_reason']), None)
    if cached_stop:
        state.update(phase='stopped_global', global_stop_reason=cached_stop)
        atomic_json(cp, state)
        atomic_json(directory/'status.json', {**state, 'budget': journal.summary(),
            'pair_observed': len(state['outcomes']) == 2, 'data_loaded': False, 'FJSP_evaluations': 0})
        return state
    if state['phase'] in ('completed','stopped_global'): return state
    try:
        for arm in ['A','B'][n:]:
            check(directory)
            if clock() - state['window_started_at'] > WINDOW_SECONDS:
                state.update(phase='stopped_global', global_stop_reason='pair_window_expired'); break
            state.update(phase='running', inflight=arm); atomic_json(cp, state)
            rec = journal.request(arm, (directory/f'Prompt_{arm}.txt').read_text(), kind='U')
            attempt = journal.data['api_attempts'][rec['attempt_ids'][-1]]
            row = outcome(directory, arm, rec, attempt, journal)
            state['outcomes'].append(row); state['inflight'] = None
            atomic_json(cp, state)
            if row['global_stop_reason']:
                state.update(phase='stopped_global', global_stop_reason=row['global_stop_reason']); break
        else: state['phase'] = 'completed'  # Both observed, NOT necessarily successful.
        atomic_json(cp, state)
    except Exception as exc:
        state.update(phase='stopped_global', global_stop_reason='global_local_error:'+type(exc).__name__)
        atomic_json(cp, state); raise
    except BaseException:
        state['phase'] = 'interrupted'; atomic_json(cp, state); raise
    finally:
        atomic_json(directory/'status.json', {**state, 'budget': journal.summary(),
            'pair_observed': len(state['outcomes']) == 2, 'data_loaded': False, 'FJSP_evaluations': 0})
    return state


def run_real(directory, env_file):
    _, config = require_approval(directory)
    if env_file is None: raise ValueError('explicit credential file required after authorization')
    from fjsp_usage.research_real.leafapi import load_local_key, KEY_ENV
    import os
    os.environ[KEY_ENV] = load_local_key(env_file)
    transport = TimedRecorder(JsonCandidateTransport(config), Path(directory)/'wire_responses', lambda: check(directory))
    return session(directory, config, transport, provenance='real')


def status(directory):
    check(directory); directory = Path(directory)
    jp = directory/'requests/attempts.json'; j = read(jp) if jp.exists() else {'requests':{},'api_attempts':{}}
    return {'phase': read(directory/'checkpoint.json')['phase'] if (directory/'checkpoint.json').exists() else 'prepared',
        'logical_tasks': len(j['requests']), 'api_attempts': len(j['api_attempts']),
        'authorization_present': (directory/'Authorization.json').exists(), 'actual_cost': None}


def report(directory):
    check(directory); directory = Path(directory); saved = read(directory/'status.json')
    rows = {r['group']: r for r in saved['outcomes']}
    paired = [rows.get(a, {'group': a, 'status': 'not_sent', 'reason': saved['global_stop_reason']}) for a in ['A','B']]
    atomic_json(directory/'AB_result.json', {'version': VERSION, **saved, 'groups': paired,
        'both_transport_passed': len(rows) == 2 and all(r['transport_success'] for r in rows.values()),
        'both_output_contract_passed': len(rows) == 2 and all(r['output_legal'] is True for r in rows.values()),
        'claim': 'one paired observation; no prompt-length causality, fitness, or population'})
    fields = ['group','transport_success','output_legal','send_confirmation_at','finished_at','elapsed_seconds',
              'http_status','http_content_type','gateway_request_id','data_events_seen','id_check','model_check',
              'complete_text','stop_received','usage_received','DONE_received','input_tokens','output_tokens',
              'stage','error_type','error','actual_cost']
    with (directory/'AB_result.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); writer.writeheader(); writer.writerows(paired)
    return paired


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare','check','status','run','report'))
    parser.add_argument('--run-dir', type=Path, default=DEFAULT); parser.add_argument('--env-file', type=Path)
    a = parser.parse_args(); directory = directory_path(a.run_dir)
    if a.stage == 'prepare': prepare(directory); print(status(directory))
    elif a.stage in ('check','status'): print(status(directory))
    elif a.stage == 'report':
        with RunLock(directory): print(report(directory))
    else:
        require_approval(directory)
        with RunLock(directory): print(run_real(directory, a.env_file)['phase'])


if __name__ == '__main__': main()
