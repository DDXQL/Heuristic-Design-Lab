"""Bind an existing reviewed H to a NEW local-request-budget scalar-U protocol.

No H generation, review fabrication, training re-evaluation or ledger migration.
Only the generic staged Workflow uses this adapter; old specialized runs stay closed.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from fjsp_usage.research.candidates import Candidate
from fjsp_usage.research.protocol import digest
from .assets import check_seal, validate_row
from .budget import BudgetStop

VERSION = 'fixed-H-single-ID-local-budget-v1'
# These recorded files changed only in protocol/budget/asset routing. Every
# other recorded code file, and all runtime/dependency identities, must match.
ROUTING_FILES = {'code/fjsp_usage/research_real/budget.py',
    'code/fjsp_usage/research_real/config.py', 'code/fjsp_usage/research_real/workflow.py',
    'code/fjsp_usage/research_real/conditional_research.py'}


def validate_source_declaration(config):
    d = config.fixed_h_source
    if (config.request_budget is None or config.purpose != 'research'
            or not isinstance(d, dict)
            or set(d) != {'version', 'run', 'protocol_sha256', 'H_frozen_sha256'}
            or d['version'] != VERSION or not isinstance(d['run'], str)
            or Path(d['run']).name != d['run'] or d['run'] in ('', '.', '..')
            or any(not isinstance(d[k], str) or len(d[k]) != 64
                   or any(c not in '0123456789abcdef' for c in d[k])
                   for k in ('protocol_sha256','H_frozen_sha256'))):
        raise ValueError('fixed H requires a new local-budget research protocol and two pinned source files')


def source_bundle(root, config, dataset):
    """Validate frozen evidence without executing h or opening holdout files."""
    from .config import fingerprint
    from .prompts import prompt_manifest
    validate_source_declaration(config)
    d = config.fixed_h_source
    folder = (Path(root)/'runs'/d['run']).resolve()
    if not folder.is_relative_to((Path(root)/'runs').resolve()):
        raise ValueError('H source path escapes runs/')
    if (folder/'.writer.lock').exists():
        raise BudgetStop('fixed H source has a writer')
    docs = {}
    for name in ('protocol','H_frozen'):
        raw = (folder/(name+'.json')).read_bytes()
        if hashlib.sha256(raw).hexdigest() != d[name+'_sha256']:
            raise ValueError('fixed H source changed: '+name)
        docs[name] = json.loads(raw)
    p, H = docs['protocol'], docs['H_frozen']
    check_seal(H, kind='H_frozen', mode=config.mode, context=digest(p))
    if (p['mode'] != config.mode or p['dataset'] != dataset.metadata
            or p['prompt_pack'] != prompt_manifest()
            or any(p['config'][k] != config.payload()[k]
                   for k in ('provider','H_size','instance_timeout','review_timeout','training_diagnostics'))
            or H['training_files'] != list(dataset.names['train'])
            or H['member_count'] != config.H_size or len(H['members']) != config.H_size):
        raise ValueError('fixed H mode/data/prompt/provider/evaluation contract mismatch')
    now = fingerprint(root)
    old = p['implementation']
    if any(now[k] != old[k] for k in ('version','python','platform','dependencies')):
        raise ValueError('cached H requires the original runtime/dependencies')
    for name, expected in old['files'].items():
        if name.startswith('code/') and name not in ROUTING_FILES and now['files'].get(name) != expected:
            raise ValueError('cached H semantic dependency changed: '+name)
    approval = H.get('scope_approval')
    keys = [r['candidate']['key'] for r in H['members']]
    if config.mode == 'real' and (not isinstance(approval, dict)
            or approval.get('scope') != 'conditional-fixed-H-research'
            or not approval.get('reviewer') or approval.get('member_code_keys') != keys):
        raise ValueError('existing fixed H research scope/code-order approval required')
    members = []
    for i, row in enumerate(H['members']):
        candidate = validate_row(row, dataset.names['train'], config.mode, 'h')
        review = row['review']
        if (type(row['member_id']) is not int or row['member_id'] != i
                or review.get('reviewed_code_key') != candidate.key
                or review.get('sample_sha256') != digest(review.get('samples'))
                or any(not isinstance(review.get(k), str) or not review[k].strip()
                       for k in ('description','reviewer','method','note'))
                or (config.mode == 'real' and review['method'].startswith('synthetic'))
                or not all(r.get('feasible') is True for r in row['training_result']['instances'])):
            raise ValueError('fixed H member numbering/review/complete feasibility mismatch')
        members.append(Candidate(review['description'], candidate.code, candidate.key, 'h'))
    if len(set(keys)) != config.H_size:
        raise ValueError('fixed H contains duplicate code keys')
    return H, tuple(members)


def bind_h(flow):
    """Copy unchanged member evidence into a context-bound new H reference."""
    if flow.config.fixed_h_source is None:
        raise ValueError('bind-fixed-h requires fixed_h_source')
    flow.assert_current()
    flow.dataset.verify('train')
    H, _ = source_bundle(flow.project_root, flow.config, flow.dataset)
    if (flow.directory/'H_frozen.json').exists():
        return h_asset(flow)[0]
    return flow.write('H_frozen.json','H_frozen', members=deepcopy(H['members']),
        member_count=H['member_count'], training_files=H['training_files'],
        scope_approval=deepcopy(H.get('scope_approval')),
        source_H_hash=H['artifact_sha256'], source_binding=deepcopy(flow.config.fixed_h_source),
        source_mechanism=VERSION, new_H_requests=0, new_H_evaluations=0, new_technical_reviews=0)


def h_asset(flow):
    flow.dataset.verify('train')
    original, members = source_bundle(flow.project_root, flow.config, flow.dataset)
    bound = flow.read('H_frozen.json','H_frozen')
    if (bound['source_binding'] != flow.config.fixed_h_source
            or bound['source_H_hash'] != original['artifact_sha256']
            or any(bound[k] != original[k] for k in ('members','member_count','training_files'))
            or bound['scope_approval'] != original.get('scope_approval')
            or bound['source_mechanism'] != VERSION
            or any(bound[k] != 0 for k in ('new_H_requests','new_H_evaluations','new_technical_reviews'))):
        raise ValueError('new fixed H reference differs from its frozen source')
    return bound, members
