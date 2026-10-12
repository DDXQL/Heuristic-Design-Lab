"""Explicit development-only reuse; original paid receipts are never reattributed.

The algorithm, prompt, dataset and scoring closure must match. Transport/guard
changes are allowed only in this development protocol, never in research mode.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fjsp_usage.research.protocol import digest
from .assets import checked_candidate, make_receipt, check_seal

ENGINEERING_FILES = {'code/fjsp_usage/research_real/config.py',
    'code/fjsp_usage/research_real/leafapi.py', 'code/fjsp_usage/research_real/quota_guard.py',
    'code/fjsp_usage/research_real/workflow.py', 'code/fjsp_usage/research_real/development_reuse.py',
    'code/fjsp_usage/research_real/report.py', 'code/fjsp_usage/research_real/real_transport.py'}


def source_rows(root, config, dataset_metadata, implementation, _ancestors=(), *, _historical_prompt_pack=None):
    if config.purpose != 'framework_development' or not config.development_h_source:
        raise ValueError('foreign H reuse is forbidden in research mode')
    declaration = config.development_h_source
    runs = (Path(root)/'runs').resolve()
    source = (runs/declaration['run']).resolve()
    if source.parent != runs:
        raise ValueError('source must remain inside the project runs directory')
    if source in _ancestors or len(_ancestors) >= 8:
        raise ValueError('cyclic or excessive development source ancestry')
    documents = {}
    for name, relative in (('protocol', 'protocol.json'), ('checkpoint', 'H/checkpoint.json'),
                           ('budget', 'budget.json'), ('journal', 'H/budgeted_initial_requests.json')):
        raw = (source/relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != declaration[name+'_sha256']:
            raise ValueError('declared source changed: '+name)
        documents[name] = json.loads(raw)
    protocol, checkpoint, budget, journal = (documents[k] for k in ('protocol','checkpoint','budget','journal'))
    old = protocol['config']
    if protocol['mode'] != 'real' or protocol['dataset'] != dataset_metadata:
        raise ValueError('same real dataset manifest and splits required')
    from .prompts import prompt_manifest
    if protocol['prompt_pack'] != (_historical_prompt_pack or prompt_manifest()):
        raise ValueError('source prompt pack differs')
    for field in ('H_size','H_seed','H_generations','H_attempts','instance_timeout','review_timeout'):
        if old[field] != getattr(config, field):
            raise ValueError('source H generation/evaluation contract differs: '+field)
    from .config import ProviderConfig, ExperimentConfig
    from dataclasses import asdict
    provider = config.payload()['provider']
    normalized_old = asdict(ProviderConfig(**old['provider']))
    delivery = ('connect_timeout','read_timeout','total_timeout','stream_response')
    if {k:v for k,v in normalized_old.items() if k not in delivery} != {
            k:v for k,v in provider.items() if k not in delivery}:
        raise ValueError('source model, wire parameters or token reservations differ')
    original = protocol['implementation']
    if any(original[k] != implementation[k] for k in ('version','python','platform','dependencies')):
        raise ValueError('source runtime differs')
    a, b = original['files'], implementation['files']
    changed = {p for p in set(a)|set(b) if a.get(p) != b.get(p)}
    if changed - ENGINEERING_FILES:
        raise ValueError('source algorithm/config closure differs: '+','.join(sorted(changed-ENGINEERING_FILES)))
    expected_ledger = digest({'config': old, 'context': digest(protocol)})
    if budget['identity'] != expected_ledger or journal['requests'] is None:
        raise ValueError('source ledger context mismatch')
    if any(v['status'] in ('pending','reserved') for v in budget['records'].values()):
        raise ValueError('source contains unresolved request records')
    source_config = SimpleNamespace(mode='real', provider=SimpleNamespace(**old['provider']))
    source_ledger = SimpleNamespace(data=budget, identity=budget['identity'])
    imported = None
    if any(r.get('source_import_hash') for r in checkpoint['population']):
        # Re-verify the original ancestry instead of giving copied receipts a
        # new ledger identity. Each earlier raw checkpoint remains hash-pinned.
        previous_config = ExperimentConfig.from_dict(old)
        originals, previous_audit = source_rows(root, previous_config, dataset_metadata,
            original, (*_ancestors, source), _historical_prompt_pack=_historical_prompt_pack)
        imported = check_seal(json.loads((source/'H_development_source.json').read_text()),
            kind='H_development_source', mode='real', context=digest(protocol))
        check_imported_rows(imported, originals, previous_audit)
    rows = []
    for row in checkpoint['population']:
        if '/init/' not in row['id']:
            raise ValueError('development reuse supports evaluated initialization h only')
        candidate = checked_candidate(row['candidate'], 'h')
        if row.get('source_import_hash'):
            matches = [r for r in imported['population'] if r['id'] == row['id']]
            if (row['source_import_hash'] != imported['artifact_sha256'] or len(matches) != 1
                    or any(row.get(k) != v for k,v in matches[0].items())):
                raise ValueError('source imported checkpoint differs from original evidence')
            clean = {k:v for k,v in row.items() if k != 'source_import_hash'}
            rows.append({**clean, 'id':'H/source/'+row['id']})
            continue
        result = checkpoint['evaluations'][row['id']]['result']
        if not result.get('valid') or row['scores'] != [r['score'] for r in result['instances']] or row['fitness'] != result['fitness']:
            raise ValueError('source candidate evaluation incomplete/inconsistent')
        record = journal['requests'][row['id']]
        charged = budget['records'][record['global_key']]
        if (charged['status'] != 'completed' or charged['usage'] != record['usage']
                or charged['prompt_key'] != record['prompt_key']
                or record.get('response_metadata',{}).get('model') != provider['expected_response_model']):
            raise ValueError('source response/ledger/model mismatch')
        identity = digest({'provider': old['provider'], 'mode':'real'})
        receipt = make_receipt(candidate, record, source_ledger, source_config, identity)
        rows.append({**row, 'id':'H/source/'+row['id'], 'receipt':receipt,
            'training_result':result, 'origin_id':row['id'], 'origin_context':digest(protocol)})
    if not rows or len(rows) > config.H_size or len({r['candidate']['key'] for r in rows}) != len(rows):
        raise ValueError('nonempty distinct source h, no more than K, required')
    return rows, {'declaration':declaration, 'original_context':digest(protocol),
                  'engineering_changes':sorted(changed), 'original_confirmed_sends':sum(
                      r.get('send_confirmed',False) for r in budget['records'].values())}


def check_imported_rows(asset, originals, audit):
    if asset['audit'] != audit or len(asset['population']) != len(originals):
        raise ValueError('development source audit/population changed')
    for row, origin in zip(asset['population'], originals):
        if any(row[k] != v for k,v in origin.items() if k != 'training_result'):
            raise ValueError('imported row not bound to original response and scores')
        a, b = row['training_result'], origin['training_result']
        fields = ('file','makespan','lower_bound','score')
        if (not a['valid'] or a['fitness'] != b['fitness'] or a['total_instances'] != b['total_instances']
                or [{k:r[k] for k in fields} for r in a['instances']] != [{k:r[k] for k in fields} for r in b['instances']]):
            raise ValueError('imported training schedules differ from original evidence')
