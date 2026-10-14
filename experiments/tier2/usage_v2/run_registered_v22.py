#!/usr/bin/env python3
"""Authorized v2.2 preparation/serial training; no validation/test stage.

Offline preparation lives outside runs so it cannot block the peer's dispatch.
Final registration requires the peer's terminal settled ledger, then pins it.
"""
import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'code'))
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.conditional_research import prepare, freeze_h, check_origin, history_summary
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.usage_v2.config import UsageConfig
from fjsp_usage.usage_v2.exports import export_prompts
from fjsp_usage.usage_v2.prompts import PROMPT_VERSION
from fjsp_usage.usage_v2.registration import (VERSION, RegisteredUsageWorkflow, SerialGuard,
    peer_terminal_audit, file_hash, inventory, worktree_roots, verify_source_group)

ORIGIN = ROOT.parent / 'FJSP-Heuristic-Research'
PEER = ROOT.parent / 'FJSP-Heuristic-Research-u-single-experiments'
SOURCE = 'leaf-tier2-single-P-acceptance-20261010-v4'
AUTHORIZATION = {
    'confirmation_person': 'DDXQL', 'scope': 'SELECT and SELECT/MIX conditional fixed-H training research',
    'prompt_version': PROMPT_VERSION, 'seed': 301, 'N': 5, 'init_cap': 20,
    'arms': {'A': [0], 'B': [0, 1]}, 'generations': 1, 'slots_per_arm': 10,
    'operators_per_arm': {'CROSS': 5, 'MUTATE': 5}, 'new_request_cap': 40,
    'only_train': True, 'lifetime_cap': 300, 'account_ceiling': 30000000,
    'note': 'Explicit user authorization in this chat on 2026-10-13; no second approval for this batch. Wait for the single-member batch to finish/stop and reconcile settlement. Preserve original H technical reviews.'}


@dataclass(frozen=True)
class V22Config(UsageConfig):
    registration_version: str = VERSION

    def __post_init__(self):
        super().__post_init__()
        if self.registration_version != VERSION or self.seeds != (301,):
            raise ValueError('this v2.2 registration is seed301 only')


def snapshot_sources(source_root, pins=None):
    source_root = Path(source_root)
    if list((source_root / 'runs').rglob('.writer.lock')):
        raise BudgetStop('source writer lock; do not snapshot an active source')
    pins = pins or {str(p.relative_to(source_root / 'runs')): file_hash(p)
        for p in sorted((source_root / 'runs').rglob('*')) if p.is_file()}
    for name, sha in pins.items():
        source = source_root / 'runs' / name; target = ROOT / 'runs' / name
        if file_hash(source) != sha:
            raise BudgetStop('source changed while taking snapshot')
        if target.exists():
            if file_hash(target) != sha:
                raise BudgetStop('existing source copy differs; never overwrite')
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Peer guards must never see a half-written budget.json copy.
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
                temporary.write(source.read_bytes())
                temporary_path = Path(temporary.name)
            temporary_path.replace(target)
            target.chmod(0o444)
    verify_source_group(ROOT, source_root, pins)
    return {'root': str(source_root.resolve()), 'files_sha256': pins}


def copy_train():
    manifest = json.loads((ROOT / 'data/fjsp_manifest.json').read_text())
    if file_hash(ROOT / 'data/fjsp_manifest.json') != file_hash(ORIGIN / 'data/fjsp_manifest.json'):
        raise BudgetStop('source dataset manifest mismatch')
    for name in manifest['split']['train']:
        relative = Path(manifest['portable_root']) / name
        source, target = ORIGIN / relative, ROOT / relative
        if file_hash(source) != manifest['files'][name]['sha256']:
            raise BudgetStop('source training file hash mismatch')
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
        if file_hash(target) != manifest['files'][name]['sha256']:
            raise BudgetStop('local training file hash mismatch')
    # Validation/test filenames and hashes remain metadata; no files are copied or loaded.


def make_config(groups, peer=None, paid=False):
    data = json.loads((ORIGIN / 'runs/leaf-usage-v2-AB-preparation-20261012-v2/config.pending.json').read_text())
    declaration = data['conditional_research']
    pins = {name: sha for group in groups for name, sha in group['files_sha256'].items() if len(Path(name).parts) >= 2}
    declaration['source_files_sha256'] = pins
    if peer:
        declaration['history_batches'] = [*declaration['history_batches'], peer['run_name']]
    H = json.loads((ROOT / 'runs' / SOURCE / 'H_frozen.json').read_text())
    declaration['scope_approval'] = {'reviewer': 'DDXQL', 'scope': 'conditional-fixed-H-research',
        'note': AUTHORIZATION['scope'] + '; original reviews unchanged; this is research-use confirmation, not new technical review.',
        'source_H_sha256': H['artifact_sha256'], 'member_code_keys': [r['candidate']['key'] for r in H['members']]}
    data.update(real_requests_authorized=paid, registration_version=VERSION,
        phase_request_caps={'r301/init': 20, 'r301/A': 10, 'r301/B': 10})
    return V22Config.from_dict(data)


def write_preparation(directory, config, groups, peer=None):
    ds = StagedDataset(ROOT / 'data/fjsp_manifest.json', project_root=ROOT, mode='real')
    with patch('fjsp_usage.research_real.workflow.JsonCandidateTransport', side_effect=AssertionError('offline stage cannot create client')):
        flow = RegisteredUsageWorkflow(directory, config=config, dataset=ds, project_root=ROOT)
        name = 'config.v22.authorized.json' if config.real_requests_authorized else 'config.v22.offline.json'
        atomic_json(directory / name, config.payload())
        atomic_json(directory / 'User_authorization.json', AUTHORIZATION)
        audit = prepare(flow)
        source, members, _ = check_origin(ROOT, config, ds)
        exported = export_prompts(directory / 'prompts', members, config.provider.max_prompt_bytes)
        if peer:
            history = history_summary(ROOT, config)
            # Own empty ledger is excluded; historical copies deduplicate for integrity.
            binding = flow.write('V22_binding.json', 'V22_binding', version=VERSION,
                source_groups=groups, peer=peer, inventory=inventory(worktree_roots(ROOT), exclude=directory),
                historical_slots=history['historical_request_slots'],
                code_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip())
            SerialGuard(flow, binding).check()
            freeze_h(flow)
        result = flow.write('V22_readiness.json', 'V22_readiness', version=VERSION,
            status='REGISTERED_AUTHORIZED_SERIAL_READY' if peer else 'OFFLINE_PREPARED_WAITING_PEER_TERMINAL_SETTLEMENT',
            user_authorization=AUTHORIZATION, source_H_hash=source['artifact_sha256'],
            ordered_H_keys=[m.key for m in members], original_reviews_preserved=True,
            H_valid=sum(r['result']['valid'] for r in audit['rows']),
            H_makespans_reproduced=sum(r['same_training_makespans_as_source'] for r in audit['rows']),
            historical_budget=audit['history'], maximum_lifetime_slots=audit['history']['historical_request_slots'] + 40,
            planned_two_batch_maximum=179,
            peer=peer, source_groups=groups, prompt_comparison=exported['comparison'], opened=ds.opened,
            model_requests=0, holdouts_loaded=False)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('offline-prepare', 'peer-status', 'register', 'run', 'report'))
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--env-file', type=Path, help='existing local credential file; read only after serial gate passes')
    args = parser.parse_args()
    if args.stage in ('register', 'run'):
        raise BudgetStop('old gpt-5.6-sol batch suspended; use run_registered_gpt61_v22.py for the explicitly authorized migration')
    if args.stage == 'peer-status':
        try:
            peer = peer_terminal_audit(PEER)
            print(json.dumps({'ready': True, 'peer': {k: peer[k] for k in ('run_name', 'request_slots', 'observed_used', 'terminal')}}, ensure_ascii=False))
        except BudgetStop as exc:
            print(json.dumps({'ready': False, 'reason': str(exc)}, ensure_ascii=False))
        return
    if not args.directory:
        parser.error('--directory required')
    directory = args.directory.resolve()
    expected = ROOT / ('preparations' if args.stage == 'offline-prepare' else 'runs')
    if directory.parent != expected:
        parser.error('own worktree direct preparations/ or runs/ child required')
    if args.stage in ('offline-prepare', 'register'):
        if directory.exists():
            parser.error('new directory required; do not overwrite evidence')
        # Gate before new run creation. Offline preparation needs no peer terminal state.
        peer = peer_terminal_audit(PEER) if args.stage == 'register' else None
        groups = [snapshot_sources(ORIGIN)]
        if peer:
            groups.append(snapshot_sources(PEER, peer['files_sha256']))
        copy_train()
        config = make_config(groups, peer, paid=peer is not None)
        result = write_preparation(directory, config, groups, peer)
        print(json.dumps({k: result[k] for k in ('status', 'H_valid', 'H_makespans_reproduced', 'maximum_lifetime_slots')}, ensure_ascii=False))
        return
    config = V22Config.from_dict(json.loads((directory / 'config.v22.authorized.json').read_text()))
    ds = StagedDataset(ROOT / 'data/fjsp_manifest.json', project_root=ROOT, mode='real')
    with RunLock(directory):
        flow = RegisteredUsageWorkflow(directory, config=config, dataset=ds, project_root=ROOT)
        if args.stage == 'run':
            SerialGuard(flow, flow.read('V22_binding.json', 'V22_binding')).check()
            if not os.environ.get(config.provider.api_key_env):
                from fjsp_usage.research_real.leafapi import load_local_key
                os.environ[config.provider.api_key_env] = load_local_key(args.env_file or ORIGIN / '.env.leafapi.local')
            initialized = flow.initialize_u(301)
            if initialized['status'] == 'initialized':
                statuses = []
                for arm in ('A', 'B'):
                    result = flow.search_arm(301, arm)
                    statuses.append(result['status'])
                    if result['status'] != 'completed':
                        break  # A budget/settlement stop never starts B.
                if statuses == ['completed', 'completed']:
                    flow.search_all()
            flow.training_report()
        from fjsp_usage.usage_v2.training_export import export_results
        report = export_results(flow)
        print(json.dumps({'status': report['status'], 'new_request_slots': report['request_slots'],
            'known_input_tokens': report['known_input_tokens'], 'known_output_tokens': report['known_output_tokens']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
