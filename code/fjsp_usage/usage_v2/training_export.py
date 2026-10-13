"""Export actual responses, every instance result, usage and paired train data.

No strategy is injected or re-evaluated here. Observed variation describes
training trajectories, not universal program behavior or combination benefit.
"""
import csv
from pathlib import Path

from fjsp_usage.research.candidates import parse_response, CandidateError
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from . import VERSION


def observed_profile(result):
    decisions = [d for row in result.get('instances', []) for d in row.get('usage_decisions', [])]
    select = [d for d in decisions if d[0] == 0]
    mix = [d for d in decisions if d[0] == 1]
    dual = [d for d in decisions if len(d[2]) == 2]
    constant_columns = sum(any(bounds[0] == bounds[1] for bounds in trace.get('ranges', {}).values())
        for row in result.get('instances', []) for trace in row.get('state_trajectory', []) if len(trace['support']) == 2)
    return {'complete_train_valid': result.get('valid', False), 'SELECT_steps': len(select),
        'MIX_steps': len(mix), 'dual_member_steps': len(dual),
        'single_member_MIX_steps': sum(len(d[2]) == 1 for d in mix),
        'MIX_observed_but_only_single_member': bool(mix) and not dual,
        'selection_vectors_not_one_hot': any(any(v not in (0, 1) for v in d[1]) or sum(d[1]) != 1 for d in select),
        'selection_scores_vary_on_train': len({tuple(d[1]) for d in select}) > 1,
        'selected_member_varies_on_train': len({tuple(d[2]) for d in select}) > 1,
        'dual_support_varies_on_train': len({tuple(d[2]) for d in dual}) > 1,
        'dual_weights_vary_on_train': len({tuple(d[3]) for d in dual}) > 1,
        'modes_vary_on_train': len({d[0] for d in decisions}) > 1,
        'dual_steps_with_a_constant_column': constant_columns,
        'notice': 'Observed training only. Non-one-hot scores do not prove effective adaptation; two members do not establish benefit. Failed-prefix behavior is not a complete valid candidate.'}


def export_results(flow):
    raw = flow.training_report()
    directory = flow.directory / 'results'; directory.mkdir(exist_ok=True)
    code_dir = directory / 'Generated_U'; code_dir.mkdir(exist_ok=True)
    tables = []; codes = []; groups = []; cost_rows = []; request_metadata = {}
    records = flow.ledger.data['records']
    for entry in [*raw['initialization'], *raw['entries']]:
        evaluations = {r['id']: r.get('result', {}) for r in entry.get('all_evaluations', [])}
        attempts = {r['id']: r for r in entry.get('attempts', [])}
        parsed = 0; returned = 0
        for identifier, request in entry.get('all_requests', {}).items():
            request_metadata[request['global_key']] = request.get('response_metadata', {})
            result = evaluations.get(identifier, {})
            if request.get('text') is not None:
                returned += 1
                try:
                    candidate = parse_response(request['text'], interface_version=VERSION, member_count=flow.config.H_size)
                except CandidateError:
                    pass
                else:
                    parsed += 1
                    name = entry['arm'] + '__' + identifier.replace('/', '__') + '.py'
                    (code_dir / name).write_text(candidate.code)
                    codes.append({'arm': entry['arm'], 'id': identifier, 'source': str((code_dir / name).relative_to(flow.directory)),
                        'code_key': candidate.key, 'description': candidate.description,
                        'category': attempts.get(identifier, {}).get('category'), 'profile': observed_profile(result)})
            for row in result.get('instances', []):
                tables.append({'arm': entry['arm'], 'candidate_id': identifier,
                    'candidate_complete_train_valid': result.get('valid', False), 'file': row['file'],
                    'makespan': row.get('makespan'), 'lower_bound': row.get('lower_bound'), 'score': row.get('score'),
                    'feasible': row.get('feasible'), 'single_solve_seconds': row.get('single_solve_seconds'),
                    'deterministic_recheck_seconds': row.get('deterministic_recheck_seconds'),
                    'diagnostic_replay_seconds': row.get('diagnostic_replay_seconds'),
                    'combination_processing_seconds': row.get('combination_processing_seconds'),
                    'recheck_combination_processing_seconds': row.get('recheck_combination_processing_seconds'),
                    'selected_h_scoring_seconds': row.get('selected_h_scoring_seconds'),
                    'recheck_selected_h_scoring_seconds': row.get('recheck_selected_h_scoring_seconds'),
                    'single_h_calls': sum(row.get('single_h_calls', [])),
                    'recheck_h_calls': sum(row.get('deterministic_recheck_h_calls', [])),
                    'diagnostic_h_calls': sum(row['diagnostic_h_calls']) if 'diagnostic_h_calls' in row else None})
            if result.get('failed_instance_result'):
                row = result['failed_instance_result']
                tables.append({'arm': entry['arm'], 'candidate_id': identifier,
                    'candidate_complete_train_valid': False, 'file': row['file'],
                    'makespan': None, 'lower_bound': None, 'score': None, 'feasible': row.get('feasible')})
        categories = entry.get('categories', {})
        slots = sum(r['phase'] == f'r301/{"init" if entry["arm"] == "INIT" else entry["arm"]}' for r in records.values())
        duplicates = sum(v for k, v in categories.items() if 'duplicate' in k)
        groups.append({'arm': entry['arm'], 'status': entry['status'], 'request_slots': slots,
            'returned_text_responses': returned, 'syntax_legal_responses': parsed,
            'syntax_legal_rate_per_slot': parsed / slots if slots else None,
            'complete_valid_new_candidates': categories.get('valid', 0),
            'complete_valid_rate_per_slot': categories.get('valid', 0) / slots if slots else None,
            'duplicate_count': duplicates, 'duplicate_rate_per_slot': duplicates / slots if slots else None,
            'failure_categories': {k: v for k, v in categories.items() if k != 'valid'},
            'usage_all_evaluated_prefixes': entry.get('usage'),
            'mean_final_population_train_fitness': entry.get('mean_population_train_fitness'),
            'population_changes': {'final_ids': [r['id'] for r in entry.get('population', [])],
                'new_final_ids': [r['id'] for r in entry.get('population', []) if not r['id'].startswith('INIT/')],
                'attempts_with_parents': entry.get('attempts', [])},
            'cost': {k: entry.get(k) for k in ('cost', 'certified_h_calls', 'primary_evaluation_seconds',
                'independent_diagnostic_seconds', 'unknown_failed_h_calls', 'missing_failed_solve_costs')}})
    quota_path = flow.directory / 'platform_quota.json'
    import json
    quota = json.loads(quota_path.read_text()) if quota_path.exists() else {'records': {}}
    for key, record in records.items():
        q = quota['records'].get(key, {})
        metadata = request_metadata.get(key, {})
        cost_rows.append({'request_key': key, 'phase': record['phase'], 'status': record['status'],
            'send_confirmed': record.get('send_confirmed'), 'usage': record.get('usage'),
            'unknown_token_reservation': record['reservation'] if record.get('usage') is None else None,
            'request_elapsed_seconds': record.get('elapsed_seconds'),
            'observed_account_debit_raw_quota': q.get('observed_account_delta'),
            'actual_supplier_charge_platform_units': metadata.get('actual_platform_units') if metadata.get('billing_certified') else None,
            'supplier_charge_certified': metadata.get('billing_certified', False),
            'settlement_status': q.get('status'), 'currency_charge': None,
            'currency_note': 'No verified quota-to-currency conversion; account debit is in provider raw quota units.'})
    entries = {r['arm']: r for r in raw['entries']}
    paired = []
    best_profiles = {}
    if all(entries.get(a, {}).get('population') for a in ('A', 'B')):
        left, right = entries['A']['population'][0], entries['B']['population'][0]
        all_results = {r['id']: r.get('result', {}) for entry in [*raw['initialization'], *raw['entries']]
            for r in entry.get('all_evaluations', [])}
        left_result = left.get('training_result') or all_results[left['id']]
        right_result = right.get('training_result') or all_results[right['id']]
        best_profiles = {'A': {'id': left['id'], 'profile': observed_profile(left_result)},
            'B': {'id': right['id'], 'profile': observed_profile(right_result)}}
        for a, b in zip(left_result['instances'], right_result['instances']):
            if a['file'] != b['file']:
                raise ValueError('paired instance order mismatch')
            paired.append({'file': a['file'], 'A_id': left['id'], 'B_id': right['id'],
                'A_makespan': a['makespan'], 'B_makespan': b['makespan'],
                'B_minus_A_makespan': b['makespan'] - a['makespan'],
                'A_score': a['score'], 'B_score': b['score'], 'B_minus_A_score': b['score'] - a['score'],
                'notice': 'Best final candidates selected on this same train split; not validation or generalization.'})
    summary_budget = flow.ledger.summary()
    complete = all(entries.get(a, {}).get('status') == 'completed' for a in ('A', 'B'))
    initialized_failed = any(e['status'] == 'initialization_failed' for e in raw['initialization'])
    from .prompts import PROMPT_VERSION
    missing_debits = sum('observed_account_delta' not in quota['records'].get(key, {}) for key, r in records.items() if r.get('send_confirmed'))
    certified_debit = sum(q['observed_account_delta'] for q in quota['records'].values() if 'observed_account_delta' in q)
    supplier_missing = sum(r.get('send_confirmed') and not request_metadata.get(key, {}).get('billing_certified') for key, r in records.items())
    supplier_debit = sum(m.get('actual_platform_units', 0) for m in request_metadata.values() if m.get('billing_certified'))
    report = {'status': 'COMPLETED_TRAINING_ONLY' if complete else 'INITIALIZATION_FAILED_NO_ARMS' if initialized_failed else 'PARTIAL_OR_GATE_STOPPED',
        'prompt_version': PROMPT_VERSION, 'groups': groups, 'actual_generated_code': codes,
        'paired_best_train_results': paired, 'request_slots': len(records),
        'paired_train_summary': {'B_better_instances': sum(r['B_minus_A_makespan'] < 0 for r in paired),
            'A_better_instances': sum(r['B_minus_A_makespan'] > 0 for r in paired),
            'equal_instances': sum(r['B_minus_A_makespan'] == 0 for r in paired),
            'mean_B_minus_A_score': sum(r['B_minus_A_score'] for r in paired) / len(paired) if paired else None},
        'best_final_candidate_profiles': best_profiles,
        'known_input_tokens': summary_budget['known_input_tokens'], 'known_output_tokens': summary_budget['known_output_tokens'],
        'budget': summary_budget, 'request_cost_records': cost_rows,
        'observed_total_account_debit_raw_quota': certified_debit if missing_debits == 0 else None,
        'observed_account_debit_certified_partial_sum': certified_debit,
        'unsettled_debit_records': missing_debits,
        'actual_supplier_charge_platform_units': supplier_debit if supplier_missing == 0 else None,
        'uncertified_supplier_charge_requests': supplier_missing,
        'account_quota_gate': {k: quota.get(k) for k in ('halted', 'stop_reason', 'observed_used', 'ceiling')},
        'actual_currency_charge': None, 'currency_conversion_verified': False,
        'holdouts_evaluated': False, 'handwritten_candidates_imported': 0,
        'notice': 'Single-seed train-only pilot. Generated mixture code is not evidence of mixture benefit. Missing failed solve/call costs remain unknown.'}
    atomic_json(directory / 'Training_results.json', report)
    atomic_json(directory / 'All_instance_results.json', tables)
    if tables:
        fields = list(dict.fromkeys(k for row in tables for k in row))
        with (directory / 'All_instance_results.csv').open('w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=fields); writer.writeheader(); writer.writerows(tables)
    return report
