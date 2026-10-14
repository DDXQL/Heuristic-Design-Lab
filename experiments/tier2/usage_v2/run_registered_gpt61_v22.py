#!/usr/bin/env python3
"""New-model v2.2 pilot: prepare concurrently, dispatch only after peer gates.

This entry has no access-diagnostic stage. The peer owns the single diagnostic.
Risk follows the peer's new public tariff, never the old model's fixed buffer.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'code'))
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_seal, check_result
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.conditional_research import check_origin, history_summary, freeze_h
from fjsp_usage.research_real.config import fingerprint
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.usage_v2.exports import export_prompts
from fjsp_usage.usage_v2.model_migration import (MODEL, MIGRATION_VERSION, PROVIDER_MIGRATION_VERSION,
    MigratedUsageConfig, audit_common_evidence, RISK_POLICY, check_preflight, risk_reservation)
from fjsp_usage.usage_v2.registration import (RegisteredUsageWorkflow, SerialGuard, file_hash,
    inventory, worktree_roots, peer_terminal_audit)
from experiments.tier2.usage_v2.run_registered_v22 import (ORIGIN, PEER, SOURCE,
    AUTHORIZATION as OLD_AUTHORIZATION, snapshot_sources, copy_train, V22Config)

OLD_PEER_RUN = 'single-ID-paired-training-20261013-authorized-v1'
PREVIOUS_PREPARATION = ROOT / 'preparations/v22-select-mix-20261013-v2'
AUTHORIZATION = {**OLD_AUTHORIZATION, 'model': MODEL, 'approved_at': '2026-10-14',
    'diagnostic_owner': 'single-member chat only; zero diagnostic requests here',
    'base_historical_slots': 80, 'planned_global_upper_bound': 181,
    'note': 'DDXQL approved the new model batch directly. Old gpt-5.6-sol grants stay suspended. '
            'Wait for one certified common access diagnostic, new model risk basis, peer terminal ledger '
            'and global budget clearance. Preserve every unknown historical usage/reservation.'}


def pending_config(groups):
    data = deepcopy(json.loads((PREVIOUS_PREPARATION / 'config.v22.offline.json').read_text()))
    source_provider = deepcopy(data['provider'])
    data['provider'].update(model=MODEL, expected_response_model=MODEL)
    data.update(registration_version=MIGRATION_VERSION, real_requests_authorized=False,
                platform_quota_reservation=RISK_POLICY['max_per_request_points'])
    data['conditional_research']['source_files_sha256'] = {
        name: sha for g in groups for name, sha in g['files_sha256'].items()
        if len(Path(name).parts) >= 2}
    data['provider_migration'] = {'version': PROVIDER_MIGRATION_VERSION,
        'confirmation_person': 'DDXQL', 'source_provider': source_provider,
        'target_provider': deepcopy(data['provider']),
        'source_H_sha256': data['conditional_research']['scope_approval']['source_H_sha256'],
        'risk_policy': deepcopy(RISK_POLICY)}
    return data


def checked_previous_evaluation(dataset):
    old_protocol = json.loads((PREVIOUS_PREPARATION / 'protocol.json').read_text())
    old = json.loads((PREVIOUS_PREPARATION / 'Conditional_H_reassessment.json').read_text())
    check_seal(old, kind='Conditional_H_reassessment', mode='real', context=digest(old_protocol))
    # A generator-only migration cannot silently reuse results after a solver
    # change. Compare every previously fingerprinted code file except the two
    # policy/registration files deliberately changed for this migration.
    current = fingerprint(ROOT)
    excepted = {'code/fjsp_usage/research_real/conditional_research.py',
                'code/fjsp_usage/usage_v2/registration.py',
                'code/fjsp_usage/research_real/quota_guard.py',
                'code/fjsp_usage/research_real/real_transport.py'}
    excepted.add('code/fjsp_usage/usage_v2/billing.py')
    for name, sha in old_protocol['implementation']['files'].items():
        if name.startswith('code/') and name not in excepted and current['files'].get(name) != sha:
            raise BudgetStop('solver/runtime/parser changed; old H evaluation cannot be reused: ' + name)
    if old_protocol['dataset'] != dataset.metadata or old['training_files'] != list(dataset.names['train']):
        raise BudgetStop('previous complete H evaluation dataset binding changed')
    if len(old['rows']) != 10:
        raise BudgetStop('previous complete H evaluation missing members')
    for row in old['rows']:
        check_result(row['result'], dataset.names['train'])
        if not row['result']['valid'] or not row['same_training_makespans_as_source']:
            raise BudgetStop('previous H evaluation incomplete')
    return old


def offline_prepare(directory):
    groups = [snapshot_sources(ORIGIN)]; copy_train()
    ds = StagedDataset(ROOT / 'data/fjsp_manifest.json', project_root=ROOT, mode='real')
    previous = checked_previous_evaluation(ds)
    previous_config = V22Config.from_dict(json.loads((PREVIOUS_PREPARATION / 'config.v22.offline.json').read_text()))
    source, members, _ = check_origin(ROOT, previous_config, ds)
    if previous['source_H_hash'] != source['artifact_sha256']:
        raise BudgetStop('H source identity changed')
    preflight = PEER / 'runs/single-ID-gpt61-preflight-20261014-v1'
    metadata = {name: json.loads((preflight / name).read_text())
                for name in ('pricing.json', 'status.json', 'models.json')}
    check_preflight(metadata['pricing.json'], metadata['status.json'], metadata['models.json'])
    directory.mkdir(parents=True)
    planned = pending_config(groups)
    MigratedUsageConfig.from_dict(planned)
    atomic_json(directory / 'config.gpt61.offline.json', planned)
    for name in metadata:
        atomic_json(directory / 'common_preflight' / name, metadata[name])
    atomic_json(directory / 'User_authorization.json', AUTHORIZATION)
    exported = export_prompts(directory / 'prompts', members, planned['provider']['max_prompt_bytes'])
    result = {'kind': 'Gpt61_offline_readiness', 'version': MIGRATION_VERSION,
        'status': 'OFFLINE_PREPARED_WAIT_COMMON_ACCESS_RISK_AND_PEER_FINAL',
        'config_state': 'typed offline config, dispatch false; diagnostic and final handoff not yet verified',
        'model': MODEL, 'provider_parameters_state': 'model-only change from common provider; compare final peer provider before registration',
        'source_groups': groups, 'source_H_sha256': source['artifact_sha256'],
        'ordered_H_keys': [m.key for m in members], 'original_reviews_preserved': True,
        'previous_complete_H_evaluation': {'path': str(PREVIOUS_PREPARATION / 'Conditional_H_reassessment.json'),
            'sha256': file_hash(PREVIOUS_PREPARATION / 'Conditional_H_reassessment.json'), 'valid_H': 10,
            'train_instances': 21, 'reuse_basis': 'unchanged solver/runtime/parser and identical dataset; no new technical review'},
        'prompt_comparison': exported['comparison'], 'prompt_pack': exported['prompt_pack'],
        'code_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'implementation': fingerprint(ROOT), 'model_requests': 0, 'diagnostic_requests': 0,
        'risk_policy': RISK_POLICY, 'prompt_risk_examples': {op: risk_reservation((directory / 'prompts' / ('B.' + op + '.txt')).read_text())
            for op in ('I1', 'CROSS', 'MUTATE')},
        'common_preflight_files_sha256': {str(preflight / name): file_hash(preflight / name) for name in metadata},
        'actual_shared_initial_exists': False, 'holdouts_loaded': False,
        'source_H_fitness_does_not_depend_on_generator_model': True,
        'slot_basis': {'base': 80, 'common_diagnostic_cap': 1, 'peer_generation_cap': 60,
                       'own_generation_cap': 40, 'planned_maximum': 181, 'lifetime_cap': 300},
        'pending': ['certified common diagnostic', 'final new-model pricing and risk basis',
                    'peer terminal unique ledger', 'global account and cumulative budget allow dispatch']}
    atomic_json(directory / 'Gpt61_offline_readiness.json', result)
    return result


def register(directory):
    common = audit_common_evidence(PEER)  # before any new run/ledger
    all_roots = worktree_roots(ROOT); before = inventory(all_roots)
    peer_pins = dict(common['files_sha256'])
    for path in (PEER / 'runs' / OLD_PEER_RUN).rglob('*'):
        if path.is_file(): peer_pins[str(path.relative_to(PEER / 'runs'))] = file_hash(path)
    groups = [snapshot_sources(ORIGIN), snapshot_sources(PEER, peer_pins)]; copy_train()
    data = pending_config(groups)
    data['provider'] = deepcopy(common['provider'])
    data['provider_migration']['target_provider'] = deepcopy(common['provider'])
    data['platform_quota_reservation'] = common['reservation']
    data['real_requests_authorized'] = True
    data['conditional_research']['history_batches'] += list(dict.fromkeys([OLD_PEER_RUN, *common['history_runs']]))
    config = MigratedUsageConfig.from_dict(data)
    # The original snapshot includes legacy continuation identities. Additional
    # paid identities must be the old one-slot peer batch or the new common runs.
    allowed = set()
    for g in groups:
        for name in g['files_sha256']:
            if name.endswith('/budget.json'):
                body = json.loads((ROOT / 'runs' / name).read_text())
                if body.get('mode') == 'real' and body.get('records'): allowed.add(body['identity'])
    if set(before) - allowed:
        raise BudgetStop('unregistered additional paid ledger; unique global reconciliation required')
    ds = StagedDataset(ROOT / 'data/fjsp_manifest.json', project_root=ROOT, mode='real')
    if common['dataset'] != ds.metadata:
        raise BudgetStop('paired training data metadata differs')
    for key, value in common['paired_inputs'].items():
        if config.payload()[key] != value:
            raise BudgetStop('paired generation/evaluation condition differs: ' + key)
    H_scope = common['H_scope'] or {}
    ours = config.conditional_research['scope_approval']
    if (H_scope.get('source_H_sha256') != ours['source_H_sha256']
            or H_scope.get('member_code_keys') != ours['member_code_keys']):
        raise BudgetStop('paired fixed H source/code/order differs')
    current = fingerprint(ROOT)
    if any(current['files'].get(name) != sha for name, sha in common['state_scheduler_parser_sha256'].items()):
        raise BudgetStop('paired state/scheduler/parser implementation differs')
    previous = checked_previous_evaluation(ds)
    source, members, _ = check_origin(ROOT, config, ds)
    for row, member in zip(previous['rows'], source['members']):
        if row['source_row'] != member: raise BudgetStop('previous H evaluation source row changed')
    history = history_summary(ROOT, config)
    flow = RegisteredUsageWorkflow(directory, config=config, dataset=ds, project_root=ROOT)
    atomic_json(directory / 'config.gpt61.authorized.json', config.payload())
    atomic_json(directory / 'User_authorization.json', AUTHORIZATION)
    flow.write('Conditional_H_reassessment.json', 'Conditional_H_reassessment',
        source_H_hash=source['artifact_sha256'], source_run=SOURCE,
        training_files=list(ds.names['train']), rows=previous['rows'], history=history,
        research_scope_approved=True, reused_evaluation_evidence={
            'path': str(PREVIOUS_PREPARATION / 'Conditional_H_reassessment.json'),
            'sha256': file_hash(PREVIOUS_PREPARATION / 'Conditional_H_reassessment.json')},
        notice='Generator migration only; prior complete train evaluation reused under unchanged solver/data; original reviews unchanged.')
    binding = flow.write('V22_binding.json', 'V22_binding', version=MIGRATION_VERSION,
        source_groups=groups, peer=common['peer'], common_evidence=None, common_audit=common,
        inventory=inventory(all_roots, exclude=directory), historical_slots=history['historical_request_slots'],
        code_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip())
    SerialGuard(flow, binding).check(); freeze_h(flow)
    export_prompts(directory / 'prompts', members, config.provider.max_prompt_bytes)
    return {'status': 'REGISTERED_GPT61_PEER_SETTLED', 'historical_slots': history['historical_request_slots'],
            'new_request_cap': 40, 'reservation': common['reservation'], 'live_quota_checked_at_dispatch': True}


def run(directory, report_only=False):
    config = MigratedUsageConfig.from_dict(json.loads((directory / 'config.gpt61.authorized.json').read_text()))
    ds = StagedDataset(ROOT / 'data/fjsp_manifest.json', project_root=ROOT, mode='real')
    with RunLock(directory):
        flow = RegisteredUsageWorkflow(directory, config=config, dataset=ds, project_root=ROOT)
        if not report_only:
            SerialGuard(flow, flow.read('V22_binding.json', 'V22_binding')).check()
            if not os.environ.get(config.provider.api_key_env):
                from fjsp_usage.research_real.leafapi import load_local_key
                os.environ[config.provider.api_key_env] = load_local_key(ORIGIN / '.env.leafapi.local')
            initialized = flow.initialize_u(301)
            if initialized['status'] == 'initialized':
                statuses = []
                for arm in ('A', 'B'):
                    result = flow.search_arm(301, arm); statuses.append(result['status'])
                    if result['status'] != 'completed': break
                if statuses == ['completed', 'completed']: flow.search_all()
            flow.training_report()
        from fjsp_usage.usage_v2.training_export import export_results
        report = export_results(flow)
        return {'status': report['status'], 'new_request_slots': report['request_slots'],
                'known_input_tokens': report['known_input_tokens'], 'known_output_tokens': report['known_output_tokens']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('offline-prepare', 'peer-status', 'register', 'run', 'report'))
    parser.add_argument('--directory', type=Path)
    args = parser.parse_args()
    if args.stage == 'peer-status':
        try:
            common = audit_common_evidence(PEER)
            result = {'ready': True, 'peer_run': common['peer']['run_name'], 'reservation': common['reservation']}
        except (BudgetStop, ValueError) as exc:
            result = {'ready': False, 'reason': str(exc)}
    else:
        if not args.directory: parser.error('--directory required')
        directory = args.directory.resolve()
        parent = ROOT / ('preparations' if args.stage == 'offline-prepare' else 'runs')
        if directory.parent != parent: parser.error('own direct preparations/ or runs/ child required')
        if args.stage in ('offline-prepare', 'register') and directory.exists():
            parser.error('new directory required; preserve old evidence')
        if args.stage == 'offline-prepare':
            result = offline_prepare(directory)
            result = {k: result[k] for k in ('status', 'model', 'model_requests', 'diagnostic_requests', 'pending')}
        elif args.stage == 'register': result = register(directory)
        else: result = run(directory, report_only=args.stage == 'report')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
