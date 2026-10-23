"""Targeted read-only source/P1/journal review. No API, candidate execution or solve.

Writes only this NEW report and a preparation-only protocol; never edits a source
run. Refuses to replace an existing preparation. All historical bytes/mtimes are
checked again after the review. The preparation has no execution entry point.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import random

from fjsp_usage.research.candidates import parse_response
from fjsp_usage.research.evolution import select_parents
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research.sets import ranked
from fjsp_usage.research_real.attempt_budget import AttemptJournal
from tools import b1_ns_recovery as old
from tools.b1_timeout_boundary import classify_boundary

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'runs/b1-ns-recovery-B-v1-20261022'
OUT = Path(__file__).resolve().parent
PREP = ROOT/'runs/b1-ns-timeout-boundary-preparation-v1-20261023'
FAILED = 'B/g0000/000009'
KEY = 'baf445cc463558cc8fc5e85218f5099d3273f484c2a740c314453a8c1e3fff13'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(directory):
    return {str(f.relative_to(directory)): {'sha256': sha(f), 'mtime_ns': f.stat().st_mtime_ns}
            for f in sorted(directory.rglob('*')) if f.is_file()}


def main():
    if PREP.exists():
        raise FileExistsError('Existing preparation is never overwritten')
    history_before = manifest(SOURCE)
    p = old.check(SOURCE)  # frozen file/provenance hashes only; no instance loading
    c, j = read(SOURCE/'r501/B/checkpoint.json'), read(SOURCE/'r501/B/batch_requests.json')
    budget = object.__new__(AttemptJournal)
    budget.data, budget.policy, budget.phase = j, j['policy'], p['request_phase']
    budget.validate_counts()  # pure validation, not constructor/request/recovery
    assert len(j['requests']) == len(j['api_attempts']) == len(c['attempts']) == 19
    assert set(j['requests']) == {f'B/init/{n:06}' for n in range(9)} | {f'B/g0000/{n:06}' for n in range(10)}
    assert all(r['status'] == 'completed' for r in j['requests'].values())
    assert all(a['status'] == 'completed' and a['send_confirmed'] for a in j['api_attempts'].values())
    assert all(r['prompt_key'] == digest({'prompt': r['prompt'], 'kind': r['kind']})
               for r in j['requests'].values())
    assert c['phase'] == 'evolution' and c['generation'] == 1 and c['cursor'] == 0
    assert c['init_cursor'] == 9 and c['inflight'] is None and not c['children']
    assert all(e['status'] == 'completed' for e in c['evaluations'].values())

    accepted, parsed, identities = {}, {}, []
    for ident, entry in c['evaluations'].items():
        if not entry['result']['valid']:
            continue
        r = entry['result']
        old.check_result(r, p['train_names'])
        assert r['total_instances'] == len(r['instances']) == 21
        candidate = parse_response(j['requests'][ident]['text'], kind='U',
            interface_version='U-usage-v2-select-or-mix-20261012')
        old.verify_worker_evidence(SOURCE, candidate.key, r)
        witness = read(SOURCE/'worker_evidence'/(candidate.key+'.before.json'))
        assert set(witness['modules']) == set(p['critical_modules'])
        accepted[ident], parsed[ident] = r, candidate
        identities.append(witness['identity'])
    assert len(accepted) == 14 and len(set(identities)) == 1
    def member(ident):
        return {'id': ident, 'candidate': parsed[ident].__dict__, 'fitness': accepted[ident]['fitness'],
                'scores': [r['score'] for r in accepted[ident]['instances']]}
    pools = c['generation_parent_pools']
    assert set(pools) == {'0'}
    P0 = pools['0']
    assert P0 == c['population_snapshots']['P0']
    children = [member(a['id']) for a in c['attempts'] if a['operator'] != 'I1' and a['id'] in accepted]
    expected = ranked(P0+children)[:5]
    signature = lambda rows: [(r['id'], r['fitness'], r['candidate']['key']) for r in rows]
    assert signature(expected) == signature(c['population'])
    assert FAILED not in {r['id'] for r in c['population']}
    rng = random.Random(501)
    for a in c['attempts']:
        if a['operator'] == 'I1':
            continue
        assert a['generation'] == 0
        assert [r['id'] for r in select_parents(P0, 2 if a['operator']=='CROSS' else 1, rng)] == a['parents']
    assert json.loads(json.dumps(rng.getstate())) == c['rng']
    assert not any('/g0001/' in key for key in j['requests'])

    receipt = read(SOURCE/'evaluation_receipts'/(KEY+'.json'))
    before = read(SOURCE/'worker_evidence'/(KEY+'.before.json'))
    assert before['identity'] == identities[0] == digest(before['modules'])
    assert receipt['valid'] is False and receipt['fitness'] is None and len(receipt['instances']) == 20
    assert receipt['error_type'] == 'Timeout' and receipt['failed_instance'] == 'Behnke57.fjsp'
    assert not (SOURCE/'worker_evidence'/(KEY+'.after.json')).exists()
    try:
        os.kill(before['pid'], 0)
        pid_observation = 'present_or_reused_not_historically_certified'
    except ProcessLookupError:
        pid_observation = 'not_present_at_review_only'
    except PermissionError:
        pid_observation = 'not_observable'
    snapshot_files = {name: sha(Path(p['source_snapshot'])/name) for name in p['snapshot_files']}
    historical = classify_boundary(receipt, before=before, after=None, lifecycle=None,
        expected_identity=identities[0], expected_files=p['snapshot_files'],
        start_files=snapshot_files, end_files=snapshot_files)
    # These current hashes are NOT substituted for missing historical boundaries.
    assert historical['decision'] == 'stop' and historical['reason'] == 'termination_unknown'
    original = Path(p['origin_directory'])
    original_observed = read(ROOT/'reports/b1-ns-recovery-scope-check-20261022/Read_only_checks.json')['original_files_unchanged']
    assert all(sha(original/name) == row['sha256'] and (original/name).stat().st_mtime_ns == row['mtime_ns']
               for name, row in original_observed.items())
    assert history_before == manifest(SOURCE)
    atomic_json(OUT/'Source_manifest.json', history_before)
    result = {'scope': 'targeted offline review; no API/evaluation/replay',
        'snapshot_files_checked': len(p['snapshot_files']), 'original_pins_checked': len(p['original_pins']),
        'current_core_mismatches': [], 'original_47_sha_mtime_unchanged': True,
        'source_run_all_sha_mtime_unchanged': True, 'complete_valid_identity_pairs': len(accepted),
        'logical_tasks': 19, 'api_attempts': 19, 'pending_requests': 0, 'pending_evaluations': 0,
        'journal_halt_reason': j['halt_reason'], 'identity_stop_exists': (SOURCE/'Identity_stop.json').exists(),
        'P1_matches_original_survival': True, 'P1': signature(c['population']),
        'RNG_matches_first_generation_parent_draws': True, 'generation': 1, 'cursor': 0,
        'second_generation_requests': 0, 'failed_candidate': FAILED,
        'native_failure': {k: receipt[k] for k in ('error_type', 'error', 'failed_instance', 'fitness', 'parent_observed_instance_seconds')},
        'before_pid': before['pid'], 'pid_observation': pid_observation,
        'historical_exitcode_and_terminal_receipt': None,
        'historical_boundary_decision': historical,
        'writer_lock_exists': (SOURCE/'.writer.lock').exists(), 'ready_for_real_resume': False}
    atomic_json(OUT/'Review.json', result)

    PREP.mkdir()
    protocol = {'version': 'B1-NS-timeout-boundary-preparation-v1-20261023',
        'status': 'PREPARATION_ONLY_NOT_EXECUTABLE', 'run_directory': str(PREP),
        'source_run': str(SOURCE), 'source_protocol_sha256': sha(SOURCE/'Protocol.json'),
        'source_manifest_sha256': sha(OUT/'Source_manifest.json'), 'review_sha256': sha(OUT/'Review.json'),
        'source_checkpoint_sha256': sha(SOURCE/'r501/B/checkpoint.json'),
        'source_journal_sha256': sha(SOURCE/'r501/B/batch_requests.json'),
        'unchanged_scientific_fields': {k: deepcopy(p[k]) for k in
            ('config','implementation','original_pins','train_names','H_order','dataset','request_policy')},
        'helper_sha256': sha(ROOT/'tools/b1_timeout_boundary.py'),
        'mock_tests_sha256': sha(ROOT/'tests/test_b1_timeout_boundary.py'),
        'inherited_logical_tasks': 19, 'inherited_api_attempts': 19,
        'future_planned_logical_tasks': 10, 'future_attempt_upper_bound': 30,
        'caps_unchanged': {'logical': 40, 'api': 60, 'per_task': 3},
        'future_policy': {'normal_completion': 'matching before/after plus original result checks',
            'confirmed_timeout': 'dead joined same PID, SIGTERM/SIGKILL exit, full source boundary hashes, valid before; invalid fitness only',
            'mismatch_or_unknown': 'stop', 'prefix_fitness': 'prohibited',
            'historical_failure': 'preserve original invalid cache and identity stop; never fabricate after or rerun'},
        'blockers': ['Historical final exit/termination cannot be reconstructed.',
            'No production adapter/migration has been installed; current helper is offline only.',
            'New executable protocol must explicitly bind historical failed/unattested exclusion, snapshot, P1/RNG/seen/cache and all19 requests.',
            'Future explicit execution authorization required.'],
        'real_execution_authorized': False}
    atomic_json(PREP/'Protocol.json', protocol)
    (PREP/'Protocol.sha256').write_text(sha(PREP/'Protocol.json')+'\n')
    atomic_json(OUT/'Prepared_protocol.json', protocol)
    (OUT/'Prepared_protocol.sha256').write_text(sha(PREP/'Protocol.json')+'\n')
    assert history_before == manifest(SOURCE)
    print(json.dumps({k: result[k] for k in ('logical_tasks','api_attempts','P1_matches_original_survival',
        'current_core_mismatches','historical_boundary_decision','ready_for_real_resume')}, ensure_ascii=False))
    print('preparation_protocol_sha256='+sha(PREP/'Protocol.json'))


if __name__ == '__main__':
    main()
