"""Offline closeout of saved IND/EVO evidence. Never generate or schedule.

Writes only a new closeout-v1 report directory, leaving original records intact.
Run from repository root with PYTHONPATH=code:. and the project Python.
"""
from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random
import subprocess
from statistics import fmean, median
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tools import ind_evo_h01 as x
from tools import ind_evo_h01_recover as recovery

OUT = x.REPORT / 'closeout-v1'
CHAMPIONS = ('r1_EVO_s07', 'r2_EVO_s16')


def stamp(epoch):
    return datetime.fromtimestamp(epoch, ZoneInfo('Asia/Manila')).isoformat()


def code_sha(code):
    return hashlib.sha256(code.encode('utf-8')).hexdigest()


def save(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def csv_save(name, rows):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with (OUT / name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys, lineterminator='\n')
        w.writeheader()
        w.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                     for k, v in r.items()} for r in rows)


def forbid(*args, **kwargs):
    raise AssertionError('Closeout is offline: API and scheduling prohibited')


def process_snapshot(state):
    """Inspect this campaign's known PIDs/keepawake targets only; never signal."""
    launches = [x.RUN/'Launch_identity.json', x.RUN/'continuation-v1/Launch_identity.json',
                recovery.R/'Launch_identity.json']
    controllers = {x.read(p)['pid'] for p in launches}
    workers = {x.read((x.RUN/e['result_path']).parent/'lifecycle.json')['pid']
               for e in state['evaluations'].values() if e['origin'] == 'new'}
    process_rows = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,comm=,args='], text=True)
    alive = []; keepawake = []; matching_controllers = []
    for line in process_rows.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid, ppid = int(parts[0]), int(parts[1]); comm, args = parts[2:]
        if pid in controllers | workers:
            alive.append({'pid': pid, 'ppid': ppid, 'comm': comm,
                          'identity': 'PID currently exists; not assumed same process without command identity'})
        tokens = args.split()
        if comm.endswith('caffeinate'):
            targets = [int(tokens[i+1]) for i, v in enumerate(tokens[:-1]) if v == '-w' and tokens[i+1].isdigit()]
            if set(targets) & controllers:
                keepawake.append({'pid': pid, 'controller_targets': targets})
        if any(('from tools.'+m+' import run') in args or ('-m tools.'+m+' run') in args
               for m in ('ind_evo_h01', 'ind_evo_h01_continue', 'ind_evo_h01_recover')):
            matching_controllers.append({'pid': pid, 'ppid': ppid, 'comm': comm})
    result = {'at_manila': stamp(datetime.now().timestamp()), 'controller_pids': sorted(controllers),
              'worker_pids_checked': len(workers), 'known_pids_still_present': alive,
              'matching_campaign_controllers': matching_controllers,
              'campaign_caffeinate': keepawake, 'signals_sent': 0,
              'old_end_receipts_cleaned': [x.read(p.parent/'End_summary.json')['caffeinate_cleaned'] for p in launches],
              'known_stop_lock_retained': (x.RUN/'.execution.lock').exists()}
    assert not alive and not keepawake and not matching_controllers
    assert all(result['old_end_receipts_cleaned'])
    return result


def main():
    OUT.mkdir(exist_ok=True)
    manifest = x.read(x.REPORT/'Raw_primary_manifest.json')
    # Full primary archive manifest, not successful results alone.
    for name, receipt in manifest['files'].items():
        assert x.sha(x.ROOT/name) == receipt['sha256'], name
    assert x.sha(x.REPORT/manifest['archive']) == manifest['archive_sha256']
    original_reports = {str(p.relative_to(x.ROOT)): x.sha(p) for p in x.REPORT.rglob('*')
                        if p.is_file() and OUT not in p.parents and 'incomplete_NOT_CERTIFIED' not in p.name}
    p, _ = recovery.check()
    state = x.read(x.RUN/'checkpoint.json'); x.ledger(state, p)
    plans = x.read(x.RUN/'Tasks.json'); p0 = x.read(x.RUN/'P0.json'); best_p0 = x.ranked(p0)[0]
    assert len(plans) == 120 and plans == x.plan()
    assert len(state['tasks']) == state['cursor']
    journals = {f.stem: x.read(f) for f in sorted((x.RUN/'journals').glob('*.json'))}
    wire_paths = list((x.RUN/'wire_responses').glob('*.json'))
    assert len(wire_paths) == sum(len(j['api_attempts']) for j in journals.values()) == 117
    for journal in journals.values():
        for aid, attempt in journal['api_attempts'].items():
            path = x.RUN/'wire_responses'/(hashlib.sha256(aid.encode()).hexdigest()+'.json')
            wire = x.read(path)
            assert wire['global_key'] == aid and wire['prompt_key'] == attempt['prompt_key']
            assert wire['send_confirmed'] == attempt['send_confirmed']
            if attempt['status'] == 'completed':
                assert wire['status'] == 'wire_completed_before_settlement' and wire['reply'] == attempt['reply']
            else:
                assert attempt['status'] == 'failed' and wire['status'] == 'wire_failed'
    results = {k: x.read(x.RUN/e['result_path']) for k, e in state['evaluations'].items()}
    members = [x.checked_candidate(r['candidate'], 'h') for r in x.read(x.RUN/'H_frozen.json')['members']]
    counts = []; curves = []; detail = []; failure_rows = []; flows = []; valid_curves = []
    new_certifications = []; expected = {**p['source_files'], **p['protected_files']}
    expected_identity = x.read(x.RUN/'Solver_expected_identity.json')['identity']
    for key, e in state['evaluations'].items():
        if e['origin'] != 'new':
            continue
        folder = (x.RUN/e['result_path']).parent; r = results[key]; life = x.read(folder/'lifecycle.json')
        raw = x.read(folder/'raw_result.json')
        assert {k: v for k, v in r.items() if k != 'boundary'} == raw
        boundary = x.certified.certify(r, dict(before=x.read(folder/'before.json'),
            after=x.read(folder/'after.json') if (folder/'after.json').exists() else None,
            lifecycle=life, expected_identity=expected_identity, expected_files=expected,
            start_files=expected, end_files=expected, worker_failure=(folder/'worker_failure.json').exists()))
        assert boundary == r['boundary'] == x.read(folder/'boundary.json')
        new_certifications.append({'key': key, 'owner': e['owner_task'], 'valid': r['valid'],
                                   'decision': boundary['decision'], 'reason': boundary['reason']})
    for repeat, seed in enumerate(x.SEEDS, 1):
        for arm in ('IND', 'EVO'):
            uid = f'r{repeat}_{arm}'; unit = state['units'][uid]; j = journals[uid]
            ids = unit['attempts']; assert len(ids) == len(j['requests'])
            assert len(j['api_attempts']) <= 30
            pool = x.ranked(p0); children = []; rng = random.Random(seed)
            seen = {r['candidate']['key'] for r in p0}; best = best_p0['fitness']; best_id = best_p0['id']
            qvalues = []; above = 0; first = None; incumbent_updates = 0
            curves.append({'repeat': repeat, 'arm': arm, 'logical_query': 0, 'best_fitness': best,
                           'incumbent_id': best_id, 'valid_count': 0})
            valid_curves.append({'repeat': repeat, 'arm': arm, 'valid_count': 0, 'best_fitness': best})
            for index, tid in enumerate(ids, 1):
                t = state['tasks'][tid]; request = j['requests'][tid]
                assert request['status'] in ('completed', 'failed') and t['status'] == 'completed'
                assert len(request['attempt_ids']) <= 2
                assert all(a in j['api_attempts'] for a in request['attempt_ids'])
                assert len(request['attempt_ids']) == t['API_attempts']
                if arm == 'IND':
                    assert not t['parents'] and not t['parent_pool']
                    prompt = x.independent_prompt(members)
                else:
                    parents = x.select_parents(pool, 5 if t['operator'] == 'CROSS' else 1, rng)
                    assert [r['id'] for r in parents] == t['parents']
                    assert [r['candidate']['key'] for r in parents] == t['parent_code_keys']
                    assert [r['id'] for r in pool] == t['parent_pool']
                    prompt = x.legacy.build_prompt('B', t['operator'], parents, members)
                assert prompt == request['prompt'] == (x.RUN/'prompts'/(tid+'.txt')).read_text()
                if request['status'] == 'completed':
                    assert request == x.read(x.RUN/'responses'/(tid+'.json'))
                    child = x.parse_response(request['text'], kind='U', interface_version=x.INTERFACE, member_count=10)
                    child = x.legacy.validate(child.code, child.description)
                    assert child.code == t['candidate']['code'] and child.key == t['code_key']
                    assert child.key == t['evaluation_key']
                    assert request['response_metadata']['model'] == p['provider']['model']
                    assert t['duplicate'] == (child.key in seen)
                    seen.add(child.key)
                next_child = None
                if t.get('certified_valid'):
                    r = results[t['evaluation_key']]
                    assert r['valid'] and len(r['instances']) == 21 and r['fitness'] == t['fitness']
                    qvalues.append(t['fitness'])
                    if t['fitness'] > best_p0['fitness']:
                        above += 1
                        if first is None: first = index
                    if t['fitness'] > best:
                        best, best_id = t['fitness'], tid
                        incumbent_updates += 1
                    valid_curves.append({'repeat': repeat, 'arm': arm, 'valid_count': len(qvalues),
                                         'best_fitness': best, 'logical_query': index})
                    if t['admitted']:
                        next_child = {'id': t['source_id'], 'candidate': t['candidate'], 'fitness': t['fitness'],
                                      'scores': [r['score'] for r in r['instances']]}
                else:
                    assert not t['admitted'] and t['fitness'] is None
                detail.append({'task_id': tid, 'repeat': repeat, 'arm': arm, 'logical_query': index,
                    'complete_response': request['status'] == 'completed', 'certified': bool(t.get('certified_valid')),
                    'fitness': t['fitness'], 'outcome': t['outcome'], 'API_attempts': t['API_attempts'],
                    'cache_hit': t['cache_hit'], 'AST_duplicate': t['duplicate']})
                curves.append({'repeat': repeat, 'arm': arm, 'logical_query': index, 'best_fitness': best,
                               'incumbent_id': best_id, 'valid_count': len(qvalues)})
                if arm == 'EVO':
                    if next_child: children.append(next_child)
                    if index % 10 == 0:
                        pool = x.ranked(pool+children)[:5]; children = []
                        assert [r['id'] for r in pool] == unit['snapshots']['P'+str(index//10)]
                        flows.append({'repeat': repeat, 'completed_generation': index//10,
                                      'population': [r['id'] for r in pool], 'champion_fitness': pool[0]['fitness']})
            if arm == 'EVO':
                assert [r['id'] for r in pool] == [r['id'] for r in unit['population']]
                assert max(r['fitness'] for r in pool+children) == best
            failures = [a for a in j['api_attempts'].values() if a['status'] != 'completed']
            assert all(a['status'] == 'failed' and a.get('send_confirmed') is True for a in failures)
            for a in failures:
                failure_rows.append({'repeat': repeat, 'arm': arm, 'task_id': a['logical_id'],
                    'attempt_id': a['id'], 'HTTP_status': a.get('metadata', {}).get('http_status'),
                    'error_type': a.get('error_type'), 'at_manila': stamp(a['started_at'])})
            statuses = Counter(a.get('metadata', {}).get('http_status') for a in failures)
            full = sum(r['status'] == 'completed' for r in j['requests'].values())
            counts.append({'repeat': repeat, 'arm': arm, 'planned': 20, 'consumed': len(ids),
                'API_attempts': len(j['api_attempts']), 'complete_responses': full,
                'HTTP503_attempts': statuses[503], 'HTTP524_attempts': statuses[524],
                'other_failed_attempts': sum(v for k, v in statuses.items() if k not in (503, 524)),
                'transport_failed_slots': sum(t['status'] == 'failed' for t in j['requests'].values()),
                'code_failures': sum(state['tasks'][tid]['outcome'] == 'parse_or_constraint_error' for tid in ids),
                'evaluation_failures': full-len(qvalues), 'certified_children': len(qvalues),
                'unfinished_or_unknown': 0, 'unstarted': 20-len(ids), 'full_budget': len(ids) == 20,
                'best_including_P0': best, 'best_task_id': best_id, 'delta_P0': best-best_p0['fitness'],
                'new_mean': fmean(qvalues), 'new_median': median(qvalues), 'new_min': min(qvalues),
                'new_max': max(qvalues), 'certified_per_consumed': len(qvalues)/len(ids),
                'certified_per_complete_response': len(qvalues)/full, 'above_P0_count': above,
                'strict_incumbent_updates': incumbent_updates,
                'first_above_P0_query': first, 'cache_hits': sum(state['tasks'][tid]['cache_hit'] for tid in ids)})
    assert sum(r['consumed'] for r in counts) == 113
    assert sum(r['API_attempts'] for r in counts) == 117
    assert sum(r['complete_responses'] for r in counts) == 108
    assert sum(r['certified_children'] for r in counts) == 107
    assert sum(r['unstarted'] for r in counts) == 7
    common = []
    for repeat in (1, 2, 3):
        pair = [r for r in counts if r['repeat'] == repeat]; q = min(r['consumed'] for r in pair)
        rows = {arm: next(r for r in curves if r['repeat'] == repeat and r['arm'] == arm and r['logical_query'] == q)
                for arm in ('IND', 'EVO')}
        common.append({'repeat': repeat, 'common_logical_endpoint': q, 'IND_best': rows['IND']['best_fitness'],
                       'EVO_best': rows['EVO']['best_fitness'],
                       'EVO_minus_IND': rows['EVO']['best_fitness']-rows['IND']['best_fitness'],
                       'IND_certified_at_endpoint': rows['IND']['valid_count'],
                       'EVO_certified_at_endpoint': rows['EVO']['valid_count'],
                       'scope': 'planned20 endpoint' if q == 20 else 'partial descriptive common prefix'})
    csv_save('Completion.csv', counts); csv_save('Search_curves.csv', curves)
    csv_save('Valid_candidate_curves_SUPPLEMENT.csv', valid_curves)
    csv_save('Common_logical_budget.csv', common); csv_save('Candidates.csv', detail)
    csv_save('HTTP_failures.csv', failure_rows); save('Population_replay.json', flows)
    # Bind the historical B2 reference through its frozen checkpoint/pins.
    b2cp = x.read(x.B2/'r501/B/checkpoint.json'); b2p = x.read(x.B2/'Plan.json')
    historical = max(b2cp['population'], key=lambda r: r['fitness'])
    b2 = b2cp['evaluations'][historical['id']]['result']
    external = x.read(x.RUN/'External_quality_references.json')['B2']
    assert external['candidate_key'] == historical['candidate']['key'] and external['result'] == b2
    assert b2p['H_order'] == p['H_order']
    assert b2p['dataset']['split']['train'] == [r['file'] for r in p['instances']]
    assert all(b2p['dataset']['hashes'][r['file']] == r['sha256'] for r in p['instances'])
    science_files = ('code/fjsp_usage/usage_v2/execution.py', 'code/fjsp_usage/offline_v2.py')
    for name in science_files:
        assert b2p['pins'][name] == p['source_files'][name]
    references = [('P0_equal', results[best_p0['candidate']['key']]), ('historical_B2', b2)]
    comparisons = []; comparison_summary = []; champion_proofs = []; ancestry = []; member_usage = []
    for tid in CHAMPIONS:
        task = state['tasks'][tid]; e = state['evaluations'][task['evaluation_key']]
        r = results[task['evaluation_key']]; folder = (x.RUN/e['result_path']).parent
        life = x.read(folder/'lifecycle.json'); before = x.read(folder/'before.json'); after = x.read(folder/'after.json')
        assert e['origin'] == 'new' and e['owner_task'] == tid and not task['cache_hit']
        assert before['identity'] == after['identity'] == expected_identity
        assert before['pid'] == after['pid'] == life['pid']
        assert life['alive'] is False and life['exitcode'] == 0 and life['rows_received'] == 21
        assert life['receiver_thread_stopped'] is True and all(i['timely'] for i in life['instance_receives'])
        assert not task.get('clock_quarantined') and not (folder/'Clock_quarantine.json').exists()
        assert len(r['instances']) == r['total_instances'] == 21
        for row, definition in zip(r['instances'], p['instances']):
            assert row['file'] == definition['file'] and row['lower_bound'] == definition['LB']
            progress = x.read(folder/(Path(row['file']).stem+'.progress.json'))
            assert progress['first_completed'] and progress['recheck_started'] and progress['completed']
            assert progress['first_start'] <= progress['first_end'] <= progress['recheck_start'] <= progress['recheck_end']
            assert row['physical_schedule_sha256'] == row['recheck_physical_schedule_sha256']
            member_usage.append({'task_id': tid, 'file': row['file'],
                'H0_dominant_steps': row['member_usage']['dominant_counts'][0],
                'H1_dominant_steps': row['member_usage']['dominant_counts'][1],
                'steps': row['member_usage']['steps'],
                'note': 'Existing dominant member counts, not per-step alpha or counterfactual reward'})
        proof = {'task_id': tid, 'repeat': task['repeat'], 'generation_zero_based': task['generation'],
            'generation_one_based': task['generation']+1, 'logical_query': task['slot']+1,
            'source_id_repeat_scoped': task['source_id'], 'operator': task['operator'],
            'AST_candidate_key': task['candidate']['key'], 'UTF8_code_sha256': code_sha(task['candidate']['code']),
            'result_sha256': e['result_sha256'], 'result_path': e['result_path'], 'fitness': r['fitness'],
            'full_train21': True, 'rows': 21, 'captured_passes': sum(v['captured_solves'] for v in r['instances']),
            'all_first_recheck_physical_hashes_equal': True, 'network_guard_zero': all(not any(v['network_guard'].values()) for v in r['instances']),
            'before_after_identity_equal': True, 'worker_exitcode': life['exitcode'], 'all_T30_receives_timely': True,
            'max_instance_receive_seconds': max(i['finished']-i['started'] for i in life['instance_receives']),
            'exit_wait_seconds': life['exit_wait_observed_seconds'], 'new_physical_evaluation_no_cache': True,
            'response_parsed_code_equals_ledger_and_evaluation_key': True,
            'accepted_attempt_id': journals[f"r{task['repeat']}_EVO"]['requests'][tid]['accepted_attempt_id'],
            'wire_response_accepted_attempt_reply_matched': True,
            'binding_limit': 'Worker input payload/U hash is not separately persisted; binding follows pinned controller data flow + response/code/evaluation-key receipts. No claim of independent worker-input payload attestation.',
            'start_manila': stamp(task['started']['wall']), 'finish_manila': stamp(task['finished']['wall']),
            'task_wall_seconds': task['finished']['wall']-task['started']['wall'],
            'task_monotonic_seconds': task['finished']['monotonic']-task['started']['monotonic'],
            'wall_minus_monotonic_seconds': (task['finished']['wall']-task['started']['wall'])-(task['finished']['monotonic']-task['started']['monotonic']),
            'physical_train21_fingerprint': x.digest([v['physical_schedule_sha256'] for v in r['instances']]),
            'Cmax_vector_fingerprint': x.digest([[v['file'], v['makespan']] for v in r['instances']]),
            'dominant_counts': [sum(v['member_usage']['dominant_counts'][i] for v in r['instances']) for i in (0, 1)]}
        proof['instances_with_both_dominant_members'] = [v['file'] for v in r['instances']
            if all(v['member_usage']['dominant_counts'][i] > 0 for i in (0, 1))]
        assert abs(proof['wall_minus_monotonic_seconds']) < 2
        champion_proofs.append(proof)
        freeze = OUT/'Champions'; freeze.mkdir(exist_ok=True)
        (freeze/(tid+'.py')).write_text(task['candidate']['code'])
        for label, reference in references:
            x.validate_result(reference, p['instances'], 'legacy_pair')
            rows = []
            for child, parent in zip(r['instances'], reference['instances']):
                assert child['file'] == parent['file'] and child['lower_bound'] == parent['lower_bound']
                d = child['makespan']-parent['makespan']
                rows.append({'task_id': tid, 'reference': label, 'file': child['file'], 'LB': child['lower_bound'],
                    'Cmax': child['makespan'], 'reference_Cmax': parent['makespan'], 'delta_Cmax': d,
                    'normalized_ratio_gain': -d/child['lower_bound'], 'delta_F_contribution': -d/(21*child['lower_bound'])})
            comparisons.extend(rows); gain = r['fitness']-reference['fitness']
            assert abs(sum(a['delta_F_contribution'] for a in rows)-gain) < 1e-14
            positive = sorted((v for v in rows if v['delta_F_contribution'] > 0), key=lambda v: -v['delta_F_contribution'])
            gross_positive = sum(v['delta_F_contribution'] for v in positive)
            negative = sum(v['delta_F_contribution'] for v in rows if v['delta_F_contribution'] < 0)
            comparison_summary.append({'task_id': tid, 'reference': label, 'fitness': r['fitness'],
                'reference_fitness': reference['fitness'], 'delta_F': gain,
                'relative_mean_Cmax_LB_improvement_percent': gain/(-reference['fitness'])*100,
                'wins': sum(v['delta_Cmax'] < 0 for v in rows), 'losses': sum(v['delta_Cmax'] > 0 for v in rows),
                'ties': sum(v['delta_Cmax'] == 0 for v in rows), 'Cmax_sum': sum(v['Cmax'] for v in rows),
                'reference_Cmax_sum': sum(v['reference_Cmax'] for v in rows), 'sum_delta_Cmax': sum(v['delta_Cmax'] for v in rows),
                'gross_positive_F': gross_positive, 'gross_negative_F': negative,
                'top1_share_of_gross_positive': positive[0]['delta_F_contribution']/gross_positive,
                'top3_share_of_gross_positive': sum(v['delta_F_contribution'] for v in positive[:3])/gross_positive,
                'net_delta_F_excluding_largest_positive': gain-positive[0]['delta_F_contribution'],
                'largest_normalized_gain': positive[0], 'largest_normalized_loss': min(rows, key=lambda v: v['delta_F_contribution']),
                'largest_raw_gain': min(rows, key=lambda v: v['delta_Cmax']),
                'largest_raw_loss': max(rows, key=lambda v: v['delta_Cmax'])})
        # Source ids such as B/g0000/000007 repeat across repeats; scope first.
        own = [t for t in state['tasks'].values() if t['repeat'] == task['repeat'] and t['arm'] == 'EVO']
        children_using = [t for t in own if task['source_id'] in t['parents']]
        snapshots = state['units'][f"r{task['repeat']}_EVO"]['snapshots']
        ancestry.append({'task_id': tid, 'parents': task['parents'], 'repeat': task['repeat'],
            'parent_generated_tasks_in_same_repeat': [{'task_id': t['task_id'], 'source_id': t['source_id'],
                'AST_key': t['code_key'], 'fitness': t['fitness']} for t in own
                if t.get('source_id') in task['parents']],
            'present_in_saved_populations': [k for k, ids in snapshots.items() if task['source_id'] in ids],
            'used_as_parent_tasks': [{'task_id': t['task_id'], 'operator': t['operator'], 'fitness': t['fitness']} for t in children_using],
            'strictly_better_descendants_among_direct_children': [t['task_id'] for t in children_using if t['fitness'] is not None and t['fitness'] > task['fitness']],
            'generation_update_complete': 'P'+str(task['generation']+1) in snapshots})
    assert champion_proofs[0]['AST_candidate_key'] != champion_proofs[1]['AST_candidate_key']
    assert champion_proofs[0]['physical_train21_fingerprint'] != champion_proofs[1]['physical_train21_fingerprint']
    assert champion_proofs[0]['Cmax_vector_fingerprint'] != champion_proofs[1]['Cmax_vector_fingerprint']
    save('Champion_certification.json', champion_proofs); save('Champion_ancestry.json', ancestry)
    csv_save('Champion_member_usage.csv', member_usage)
    csv_save('Champion_instance_differences.csv', comparisons); save('Gain_concentration.json', comparison_summary)
    csv_save('Champion_comparisons.csv', [{k: v for k, v in r.items() if not isinstance(v, dict)} for r in comparison_summary])
    save('Champion_freeze.json', {'selection': 'Largest complete certified train21 Fitness among existing consumed slots; no holdout selection',
        'primary_champion': 'r2_EVO_s16', 'audit_secondary': 'r1_EVO_s07', 'proofs': champion_proofs,
        'protocol_sha256': x.sha(x.RUN/'Protocol.json'), 'H_file_sha256': p['assets']['H_frozen.json'],
        'H_order': p['H_order'], 'interface': x.INTERFACE, 'solve_seed': 501, 'instances': p['instances'],
        'evaluation': p['evaluation'], 'source_files': p['source_files'], 'launch_or_holdout_evaluation_authorized_by_this_freeze': False})
    # Existing audit metadata and an explicit historical validation-selection rule.
    audit_path = x.ROOT/'runs/conditional-paired-research-20261011-v4/Dataset_usage_audit.json'
    audit = x.read(audit_path)
    source_checks = []
    for item in audit['sources']:
        source = Path(item['path']); assert x.sha(source) == item['sha256']
        data = x.read(source)
        source_checks.append({'path': str(source), 'sha256': item['sha256'],
            'partition': data.get('partition'), 'selection_criterion': data.get('selection', {}).get('criterion'),
            'scope': 'Only historical metadata/selection rule used; no holdout instance or strategy score comparison'})
    save('Holdout_exposure_metadata.json', {'audit': str(audit_path.relative_to(x.ROOT)), 'audit_sha256': x.sha(audit_path),
        'validation11_already_evaluated': audit['validation11_already_evaluated'], 'sources': source_checks,
        'test28': 'Already exposed per current user/current protocols; older 20261021 negative scan is time-bounded, not current cleanliness proof.',
        'influence_limit': 'Historical single-rule validation selection is explicit; extent of influence on later H/U design cannot be quantified from these records.'})
    timeline = []
    for label, base in [('initial', x.RUN), ('continuation', recovery.c.C), ('recovery', recovery.R)]:
        end = x.read(base/'End_summary.json'); clock_base = recovery.c.C if label == 'recovery' else base
        clock = x.read(clock_base/'Run_clock.json')
        stop = x.read(base/'Stop.json') if (base/'Stop.json').exists() else None
        timeline.append({'phase': label, 'start': stamp(clock['start']['wall']), 'deadline': stamp(clock['deadline']),
            'end_receipt': stamp(end['end']['wall']), 'end_cursor': end['cursor'], 'end_phase': end['phase'],
            'stop': stop, 'notice': 'Recovery uses continuation clock, not a new window' if label == 'recovery' else None})
    save('Timeline.json', timeline); save('Process_closeout.json', process_snapshot(state))
    old_costs = x.read(x.REPORT/'Summary.json')['arms']
    save('Costs_saved_only.json', {'arms': old_costs, 'association': 'Platform points matched by existing token/time heuristic, not verified request-ID invoices.',
        'CNY': None, 'new_account_or_billing_queries': 0, 'candidate_active_seconds': sum(t['finished']['wall']-t['started']['wall'] for t in state['tasks'].values())})
    for name, receipt in manifest['files'].items():
        assert x.sha(x.ROOT/name) == receipt['sha256']
    assert all(x.sha(x.ROOT/n) == h for n, h in original_reports.items())
    save('Verification.json', {'passed': True, 'real_API_calls': 0, 'new_solves': 0, 'unknown_requests': 0,
        'unknown_evaluations': 0, 'original_primary_files_verified_unchanged': len(manifest['files']),
        'original_report_files_verified_unchanged': len(original_reports), 'new_result_certifications_replayed': new_certifications,
        'wire_attempts_verified': 117,
        'all_saved_prompts_and_parent_sampling_replayed': True, 'candidate_source_ids_scoped_to_repeat': True,
        'B2_quality_compatible_H_train_LB_scoring': True, 'B2_time_wrapper': 'T15 historical vs T30 current; not timing or budget fair',
        'base_commit': '9402247cdcd9602fab1b82c76f4ff606a193b1c9', 'analysis_script_sha256': x.sha(Path(__file__))})
    save('Closeout_status.json', {'status': 'partial_closed_by_current_user_instruction', 'planned': 120,
        'consumed': 113, 'unstarted_not_to_resume': [t for t in plans if t['task_id'] not in state['tasks']],
        'API_attempts': 117, 'remaining_slots_not_reallocated': True, 'old_checkpoint_and_Stop_unchanged': True,
        'supersedes_previous_report_recommendation_to_complete_remaining7': True, 'automatic_restart': False})
    write_report(counts, common, comparison_summary, champion_proofs, ancestry, timeline, old_costs)
    print(json.dumps({'status': 'partial_closed', 'logical_consumed': 113, 'API_attempts': 117,
                      'unknown': 0, 'output': str(OUT)}, ensure_ascii=False))


def write_report(counts, common, comparisons, proofs, ancestry, timeline, costs):
    lines = ['# IND vs EVO本轮正式收尾（partial）', '',
        '本轮以113/120逻辑槽位正式收尾，7个未启动槽位不再补跑。117次API尝试，108份完整响应，107个完整认证子代成绩（含1次跨搜索评价缓存复用）。没有未知请求或未知求解预留。本次新增API、求解、账单查询均为0。原始账本、Stop、期限及9402247的报告不改；本报告取代其中“补剩余7个”的后续建议。', '',
        '## 完成情况', '',
        '|重复|方法|原定/消耗|API尝试|完整响应|503/524失败尝试|传输失败槽位|代码/评价失败|认证子代|未知|未启动|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in counts:
        lines.append(f"|{r['repeat']}|{r['arm']}|20/{r['consumed']}|{r['API_attempts']}|{r['complete_responses']}|{r['HTTP503_attempts']}/{r['HTTP524_attempts']}|{r['transport_failed_slots']}|{r['code_failures']}/{r['evaluation_failures']}|{r['certified_children']}|0|{r['unstarted']}|")
    lines += ['', '第1组的IND和EVO均消耗20个逻辑槽位；有效认证均18个，完整响应分别18和19个。第2、3组均为partial。HTTP失败共9次尝试（8次503、1次524），对应5个失败逻辑槽位；另有EVO第1组1个程序Behnke57超时，完整Fitness=null。113消耗绝不等于113个有效程序。', '',
        '## 搜索结果与相同逻辑预算比较', '',
        '共同P0冠军为等权H0/H1，Fitness −1.983144294915。下表“当前档案最好”含P0；新增分布只含完整认证子代，不给失败填分。完整0～实际消耗曲线见Search_curves.csv及Search_curves.png，不能把右侧空白外推为继续保持冠军。', '',
        '|重复|方法|完成性|当前档案最好|新增最佳|新增均值/中位数|新增最差|认证/消耗|超过P0子代数|首次位置|',
        '|---|---|---|---:|---:|---|---:|---:|---:|---:|']
    for r in counts:
        lines.append(f"|{r['repeat']}|{r['arm']}|{'20槽位完整' if r['full_budget'] else 'partial'}|{r['best_including_P0']:.12f}|{r['new_max']:.12f}|{r['new_mean']:.12f}/{r['new_median']:.12f}|{r['new_min']:.12f}|{r['certified_children']}/{r['consumed']}|{r['above_P0_count']}|{r['first_above_P0_query'] or '无'}|")
    lines += ['', '|重复|共同逻辑位置|IND档案最好|EVO档案最好|EVO−IND|认证数IND/EVO|', '|---|---:|---:|---:|---:|---:|']
    for r in common:
        lines.append(f"|{r['repeat']}|{r['common_logical_endpoint']}|{r['IND_best']:.12f}|{r['EVO_best']:.12f}|{r['EVO_minus_IND']:+.12f}|{r['IND_certified_at_endpoint']}/{r['EVO_certified_at_endpoint']}|")
    lines += ['', '第1组使用原定20端点；第2、3组使用各自共同已完成18端点，属于partial描述。六条路径共同前18的既有辅助比较仍保留，但不能替代20预算主目标。按有效候选数的辅助曲线另存，绝不回填失败或重设预算。',
        '503在第1组IND造成2槽失败、EVO造成1槽失败，在第2组IND又造成1槽失败；524在第2组EVO造成1槽失败。最终两方法各54份完整响应是总数上的巧合，单个重复、逻辑位置和代际操作获得的机会仍不平衡。共同18处第2组EVO仅17份响应，IND为18份。HTTP缺失与EVO一次评价超时应分开。',
        '两条改善均已在夜间形成，503发生于白天续跑。因此503没有生成或造成这两名冠军；它截断了原定后续机会，不能反推出无故障时完整20端点一定仍有相同方法差异。',
        '观察到EVO两条不同重复改善强P0，IND未改善；但EVO新增均值只在重复1较好，重复2、3更差。仅一组完整预算，加上缺失机会及共享缓存，支持“演化流程值得复核”，不支持稳定优越、显著性、泛化或交叉/变异单独有效。', '',
        '## 冠军质量认证与时间证据', '',
        '全campaign冠军r2_EVO_s16，重复2、第2代（代码generation=1）、该路径第17个新增逻辑候选，MUTATE；Fitness −1.975488675215。它是第二代缓冲区中已认证的已见最好子代，该代未结束，未宣称已经进入P2。', '',
        '|候选|原始UTF-8代码SHA256|AST代码键|认证完成时间（马尼拉）|', '|---|---|---|---|']
    for r in proofs:
        lines.append(f"|{r['task_id']}|`{r['UTF8_code_sha256']}`|`{r['AST_candidate_key']}`|{r['finish_manila']}|")
    lines += ['', '两个冠军均为本轮新物理评价，无缓存；API首份完整响应重新解析得到的源码、AST键、任务、评价键一致。协议固定H身份/顺序、七状态接口、21个文件字节SHA、LB、seed501、评分核心和同分规则；逐项通过冻结身份检查。21行顺序齐全，score=−Cmax/LB，完整均值复算一致；42遍首解/复检证据、物理指纹和H调用数一致。原始result与raw_result除认证边界字段外一致。',
        'before/after源码身份和worker PID一致，生命周期terminal、exitcode=0、接收线程结束，21次接收均在各自30秒期限内；2秒退出等待与结果期限分离。运行核心遇非法U、负权、非有限数或不一致即抛错，无主策略回退分支；不能将合法端点退化误称回退。没有漏实例、前缀均值、错误缓存或Clock_quarantine记录。',
        '绑定边界：worker没有另存一份带U代码SHA的输入payload；API→实际评价绑定依赖冻结控制器源码及响应/任务/评价键链，而非独立worker输入签章。既有认证规则已满足，未发现矛盾，不据此擅自作废；未来可独立增强输入留证，但不在本轮改执行器。',
        '两冠军完成于断电前；候选处理段墙钟−单调时间差均小于2秒，逐实例及时接收且正常退出。因此现有证据支持其质量认证，未见休眠侵入这两个候选。整个campaign跨断电的墙钟跨度不能当作计算成本，也不是严格CPU运行时间认证。只保留既有断电事实，不开展额外电源诊断。', '',
        '## 收益、退化与集中程度', '',
        '历史B2由原冻结checkpoint绑定，H/训练文件/未取整LB/评分核心匹配，故只作质量参照；其T15封装与本轮T30不同，不是同期时间或预算公平对照。相对改善=(参照平均Cmax/LB−子代平均Cmax/LB)/参照平均Cmax/LB。', '',
        '|子代|参照|ΔFitness|相对平均Cmax/LB改善|胜/负/平|ΣCmax差|正收益最大1/3例占全部正收益|去最大收益后的净ΔF|',
        '|---|---|---:|---:|---|---:|---|---:|']
    for r in comparisons:
        lines.append(f"|{r['task_id']}|{r['reference']}|{r['delta_F']:+.12f}|{r['relative_mean_Cmax_LB_improvement_percent']:.4f}%|{r['wins']}/{r['losses']}/{r['ties']}|{r['sum_delta_Cmax']:+d}|{r['top1_share_of_gross_positive']:.1%}/{r['top3_share_of_gross_positive']:.1%}|{r['net_delta_F_excluding_largest_positive']:+.12f}|")
    lines += ['', '集中比例以全部正贡献为分母，不以正负抵消后的净收益为分母。“去最大收益”只是既有21行的敏感性描述，不改变正式Fitness或删除实例。r2冠军原始总Cmax比等权多23，但归一化主指标更好，正说明总Cmax不能替代该目标。', '']
    lines += ['r2对等权P0的正收益前三例占全部正贡献48.4%；但最大一例Behnke43贡献约占正负抵消后净改善的91.5%，移除此项仅余+0.000652819。收益不是完全只有一例，却有明显抵消和脆弱性，训练外验证应优先于扩大搜索。', '']
    for r in comparisons:
        hi = r['largest_normalized_gain']; lo = r['largest_normalized_loss']
        rawhi = r['largest_raw_gain']; rawlo = r['largest_raw_loss']
        lines.append(f"- {r['task_id']}对{r['reference']}：归一化最大收益{hi['file']}（Cmax差{hi['delta_Cmax']:+d}，ΔF贡献{hi['delta_F_contribution']:+.9f}），最大退化{lo['file']}（{lo['delta_Cmax']:+d}，{lo['delta_F_contribution']:+.9f}）；原始Cmax最大收益/退化为{rawhi['file']} {rawhi['delta_Cmax']:+d} / {rawlo['file']} {rawlo['delta_Cmax']:+d}。")
    lines += ['', '## 演化轨迹与已有行为证据', '',
        'r1_EVO_s07：第1代第8槽，从共同等权P0经MUTATE产生；公式alpha=clip(0.5+remaining_work_std−machine_ready_std)。进入P1，后来确实作为第二代CROSS/MUTATE父代；P2仍保留。其后代未严格超过它，两份后代达到同分；同分不自动解释为全状态行为相同。',
        'r2_EVO_s16：第2代第17槽，来自同一重复的第一代CROSS子代r2_EVO_s04（B/g0000/000004）。该中间子代进入P1并实际成为后续父代；r2_EVO_s16未代末更新，未进入已保存群体，也尚未作为后续父代。该重复后续已认证候选没有再超过它。其alpha是工作均值/离散度、机器就绪、进度、候选比例和上一成员的加减组合，合法性由原host保持。',
        '重要映射约束：B/g... ID会在不同重复中重复，谱系关联必须同时带repeat；本次逐步重放了父代抽样与代末更新，并以repeat限定查后代。两个冠军代码键、Cmax向量、完整train21物理排程指纹均不同，来自两个新重复。',
        '已有member_usage证明两冠军至少在Behnke1同一实例内均访问两种主导成员：r1为H0/H1主导7/43步，r2为12/38步。权重主导确实发生变化，见Champion_member_usage.csv；但该记录不含每步全部alpha，不能量化具体分支/精确权重与反事实收益。未新增轨迹或诊断求解，不能把整体改善因果归于某一状态项。', '',
        '## 执行与费用收尾', '']
    for t in timeline:
        lines.append(f"- {t['phase']}：时窗{t['start']}至{t['deadline']}；终态落盘{t['end_receipt']}，cursor={t['end_cursor']}，{t['end_phase']}。")
    lines += ['', '原始6小时窗记录未覆盖或延期；用户确认夜间断电，不进一步专项诊断。另授权2小时仅续原11槽；续跑三槽各两次503后停止；下一原槽两次恢复探测仍503，沿用同一2小时截止。503 Stop、已知终态锁和旧账本保留。当前关闭是用户指令，不以成绩调整计划。',
        '本campaign原控制器PID、107个评价worker PID均不在当前进程表；未见同模块正式控制器或针对这些控制器的caffeinate。三个阶段终态回执均记录清理防休眠任务。本轮没有向任何进程发信号、清锁、释放未知预留或改旧状态；新的Closeout_status.json单独记录partial关闭。', '']
    for arm, r in costs.items():
        lines.append(f"- {arm}：API {r['API_attempts']}次；已知输入/输出Token {r['known_input_tokens']}/{r['known_output_tokens']}，usage未知{r['unknown_usage_attempts']}次；可关联平台点{r['associated_points']}，费用关联未知{r['unknown_invoice_attempts']}次。")
    lines += ['', '可关联平台点合计448710，关联依据是既有Token/时间匹配，非精确request-ID账单认证；人民币金额未知。未把503计费假定为0，也未以账户差值冒充本轮准确费用。新增物理评价107，实际启动首解/复检4494遍；1次评价缓存仍占逻辑槽位。评价父进程区间合计2537.731秒，候选处理区间合计4728.475秒，后者含API/准入/评价；跨断电总墙钟另列，不等同计算耗时。', '',
        '## 下一步：两条研究线分别规划，不执行', '',
        '**优先策略质量线。** 冻结唯一主冠军r2_EVO_s16及本目录Champion_freeze.json，用它与等权P0做一次训练外固定策略比较；B2可作预登记第三参照，不能按新集结果再换成r1冠军或改参数。建议最小新集20个预先确定、未被项目开发接触的实例，按规模/机器数分层，全部保留，2策略最多40项/80遍；加B2则60项/120遍。仍拟采用T30、首解复检及普通超时全Fitness=null规则，需另立数据身份和授权；本建议未创建可启动执行协议。',
        'validation11不是新确认集：既有Dataset_usage_audit明确记已评价，原始单规则记录的selection.criterion明确按全部11例均值选优；对应源SHA本次复核一致。能证实历史选择使用，无法量化对以后H/U设计的全部影响。test28已暴露；若未来使用，只能称已知基准上的固定策略追加比较。本轮没读取这些实例，也没比较其策略成绩。',
        '启动质量线前缺失：新实例的具体来源/名单、项目使用历史声明及跨集合近重复/同构核查范围；外部新来源是否需要另行许可；完整评价失败时的主分析；固定数据后评估的明确授权。预登记ΔF、逐实例胜负平和区间描述，不从训练外结果重新挑训练冠军或调参；不将20例本身当普遍泛化证明。',
        '**搜索方法线暂列第二优先。** 服务稳定后新建3组完整独立搜索重复，仍为共同P0、IND20/EVO20（120新逻辑槽位、最多180次API尝试），新seed、独立协议与时窗，两组交错。它是探索性复核，非高功效显著性试验；较大重复数需后续基于成本另定。先查服务公告和非生成状态，但这些不能保证实际生成可用；新实验首槽仍按预算与失败保护执行，不以持续付费探测或单臂重试凑齐有效程序。失败仍占逻辑预算，不补本轮5失败槽或7未启动槽；若服务再持续失败则整批保留partial。',
        '新比较前缺失：稳定服务的实际可用性、共同模型/参数可复用情况、新时窗与固定规模授权。保持相同P0和先验，单列共同P0历史投入、缓存和Token成本；不让某组独享本轮冠军代码。最终仍比较整套演化流程，不拆分宣称CROSS或MUTATE单独贡献。', '',
        '## 文件与离线复现', '',
        '- Completion.csv：逐重复/方法总表；Search_curves.csv/png/pdf：含P0的逻辑预算曲线；Valid_candidate_curves_SUPPLEMENT.csv仅辅助。',
        '- Champion_certification.json、Champion_freeze.json及Champions/：冠军身份和已有认证链；Champion_instance_differences.csv、Gain_concentration.json：逐实例贡献。',
        '- Champion_ancestry.json、Population_replay.json：限定重复的谱系与种群重放；HTTP_failures.csv、Timeline.json、Process_closeout.json：故障和终态证据。',
        '- Verification.json：3438份既有主记录及旧报告保持不变；Closeout_status.json：7未执行槽及partial关闭决定。旧Raw_primary_evidence.tar.gz为主证据归档，压缩包SHA由原manifest认证。', '',
        '离线复现（不联网、不求解）：`PYTHONPATH=code:. .venv/bin/python -B -m tools.ind_evo_h01_closeout`；绘图另用`python3 tools/ind_evo_h01_closeout_plot.py`读取本目录CSV。原始运行源码/提示词/历史记录均未修改。']
    (OUT/'REPORT_ZH.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':
    # Do not monkeypatch pinned execution modules: their loaded identities must
    # remain authentic during check(). This script never calls solve/run APIs.
    with patch('socket.socket.connect', side_effect=forbid):
        main()
