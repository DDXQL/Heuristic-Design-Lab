"""Scoped read-only evidence check; never constructs a search or an evaluator."""
import gzip
import hashlib
import json
import random
from pathlib import Path

from fjsp_usage.research.candidates import CandidateError, parse_response
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_result, checked_candidate
from fjsp_usage.research_real.config import fingerprint
from tools import b1_usage_prompts as prompts

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'runs/b1-ns-full-h-free-seed501-k2-v1-20261022'
OUT = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'reports/b1-ns-b-full-h-free-seed501-k2-v1-20261022'
PROTOCOL_SHA = '94381988c5536bd19f72aa0cbcdcafc7dfc1b8a4ece7b18fcbd71ad0b4a90083'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot():
    return {str(p.relative_to(RUN)): {'sha256': sha(p), 'mtime_ns': p.stat().st_mtime_ns}
            for p in RUN.rglob('*') if p.is_file()}


def main():
    before = snapshot()
    p = read(RUN / 'Protocol.json')
    assert sha(RUN / 'Protocol.json') == PROTOCOL_SHA
    assert (RUN / 'Protocol.sha256').read_text().strip() == PROTOCOL_SHA
    mismatches = [n for n, h in p['pins'].items() if not (ROOT / n).is_file() or sha(ROOT / n) != h]
    assert not mismatches, mismatches
    assert fingerprint(ROOT) == p['implementation']
    assert p['prompt_pack'] == prompts.manifest()
    assert read(RUN / 'config.pending.json') == p['config']
    manifest = read(ROOT / 'data/fjsp_manifest.json')
    assert sha(ROOT / 'data/fjsp_manifest.json') == p['dataset']['manifest_sha256']
    assert p['train_names'] == manifest['split']['train']
    data_root = ROOT / manifest['portable_root']
    for name in p['train_names']:
        assert sha(data_root / name) == p['dataset']['hashes'][name]
    h = read(RUN / 'H_source_binding.json')
    assert [m['candidate']['key'] for m in h['members']] == p['H_order']
    j = read(RUN / 'r501/B/batch_requests.json')
    c = read(RUN / 'r501/B/checkpoint.json')
    assert (c['phase'], c['init_cursor'], c['generation'], c['cursor'], c['inflight']) == ('initialization', 6, 0, 0, None)
    assert not c['children'] and not list(RUN.rglob('*.lock'))
    assert c['rng'] == json.loads(json.dumps(random.Random(501).getstate()))
    assert len(j['requests']) == len(j['api_attempts']) == len(c['attempts']) == 6
    assert j['halt_reason'] is None
    assert (j['policy']['logical_candidate_cap'], j['policy']['api_attempt_cap'],
            j['policy']['per_candidate_attempt_cap']) == (40, 60, 3)
    by_id = {a['id']: a for a in c['attempts']}
    pool = {a['id']: a for a in c['population']}
    assert set(pool) == set(c['evaluations']) == {'B/init/000001', 'B/init/000002', 'B/init/000005'}
    records = []
    for ident, r in j['requests'].items():
        assert r['status'] == 'completed' and len(r['attempt_ids']) == 1
        a = j['api_attempts'][r['accepted_attempt_id']]
        assert r['attempt_ids'] == [a['id']] and a['logical_id'] == ident
        assert a['number'] == 1 and a['status'] == 'completed' and a['send_confirmed'] is True
        assert r['response_id'] == a['response_id'] == a['id'] + '/response'
        assert r['prompt_key'] == a['prompt_key'] == digest({'prompt': r['prompt'], 'kind': 'U'})
        assert (RUN / 'r501/B/prompts' / ident.replace('/', '_')).read_text() == r['prompt']
        label = hashlib.sha256(a['id'].encode()).hexdigest() + '.json'
        wire = read(RUN / 'wire_responses' / label)
        received = read(RUN / 'received_responses' / label)
        sent = read(RUN / 'send_times' / label)
        assert wire['global_key'] == sent['attempt_id'] == a['id']
        assert wire['send_confirmed'] is True and wire['prompt_key'] == r['prompt_key']
        for reply in (wire['reply'], received, a['reply']):
            assert reply['text'] == r['text'] and reply['usage'] == r['usage'] == a['usage']
            assert reply['metadata']['model'] == 'gpt-6.1-sol'
            assert reply['metadata']['finish_reason'] == 'stop' and reply['metadata']['http_status'] == 200
        if ident in pool:
            candidate = checked_candidate(pool[ident]['candidate'], 'U')
            parsed = parse_response(r['text'], kind='U', interface_version=candidate.interface_version, member_count=10)
            assert parsed.key == candidate.key == by_id[ident]['code_key']
            assert c['seen'][candidate.key] == ident and by_id[ident]['status'] == 'valid'
            evaluation = c['evaluations'][ident]
            assert evaluation['status'] == 'completed'
            result = check_result(evaluation['result'], p['train_names'])
            assert result['valid'] and result['fitness'] == pool[ident]['fitness']
            assert pool[ident]['scores'] == [row['score'] for row in result['instances']]
            for row in result['instances']:
                assert row['feasible'] is True and row['captured_solves'] == 2
                assert row['physical_schedule']['makespan'] == row['makespan']
                assert digest(row['physical_schedule']) == row['physical_schedule_sha256'] == row['recheck_physical_schedule_sha256']
        else:
            assert by_id[ident]['status'] == 'parse_or_constraint_error'
            try:
                parse_response(r['text'], kind='U', interface_version=pool[next(iter(pool))]['candidate']['interface_version'], member_count=10)
            except CandidateError:
                pass
            else:
                raise AssertionError('historical rejected response unexpectedly parses')
        records.append({'logical_id': ident, 'attempt_id': a['id'], 'response_id': a['response_id'],
                        'status': 'completed', 'candidate_status': by_id[ident]['status'],
                        'fitness': pool[ident]['fitness'] if ident in pool else None})
    assert len(c['seen']) == 3
    status = read(RUN / 'Search_status.json')
    assert status['evaluations_reserved'] == len(c['evaluations'])
    assert [row['id'] for row in status['population']] == list(pool)
    assert {row['id'] for row in status['all_evaluations']} == set(pool)
    for row in status['all_evaluations']:
        assert row['status'] == 'completed' and row['valid'] is True
        assert row['fitness'] == pool[row['id']]['fitness'] and row['completed_instances'] == 21
    archive_manifest = read(ARCHIVE / 'Evidence_manifest.json')['files']
    for name, entry in archive_manifest.items():
        assert sha(RUN / name) == entry['sha256']
        saved = ARCHIVE / entry['archived_as']
        raw = gzip.decompress(saved.read_bytes()) if entry['compression'] else saved.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry['sha256']
    assert snapshot() == before, 'original run changed during read-only check'
    report = {'protocol_sha256': PROTOCOL_SHA, 'pins_checked': len(p['pins']), 'mismatches': mismatches,
              'implementation_fingerprint_equal': True, 'ordered_train_files_hashed': 21,
              'H_order_equal': True, 'prompt_pack_equal': True, 'original_files_unchanged': before,
              'archive_entries_matched': len(archive_manifest), 'request_records': records,
              'completed_requests': 6, 'pending_attempts': 0, 'completed_evaluations': 3,
              'instance_records_checked': 63, 'recorded_physical_rechecks_matched': 63,
              'API_or_solve_calls_in_this_check': 0, 'native_state_modified': False,
              'inheritance': {'responses_and_sources': 'internally consistent; no resend needed',
                              'evaluation_records': 'internally consistent, but worker-time source identity not certified',
                              'automatic_resume_ready': False}}
    (OUT / 'Read_only_checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('original_files_unchanged', 'request_records')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
