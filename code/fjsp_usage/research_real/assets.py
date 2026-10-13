"""Sealed, context-bound research assets, complete fitness and receipt checks.

Hashes detect changes and mode/context confusion; they are not signatures against
a privileged owner deliberately fabricating an entire run and its provenance.
"""

from dataclasses import asdict
import math
from statistics import fmean

from fjsp_usage.research.candidates import Candidate, parse_response, validate_code
from fjsp_usage.research.protocol import digest
from .review_execution import ACTION_SAMPLES, score_samples


def seal(payload):
    payload = dict(payload)
    if 'artifact_sha256' in payload:
        raise ValueError('payload must be unsealed')
    return {**payload, 'artifact_sha256': digest(payload)}


def check_seal(asset, *, kind=None, mode=None, context=None):
    if not isinstance(asset, dict):
        raise ValueError('asset must be an object')
    payload = {k: v for k, v in asset.items() if k != 'artifact_sha256'}
    if asset.get('artifact_sha256') != digest(payload):
        raise ValueError('asset seal mismatch')
    if kind is not None and asset.get('kind') != kind:
        raise ValueError('asset kind mismatch')
    if mode is not None and asset.get('mode') != mode:
        raise ValueError('synthetic/mock asset cannot be promoted into a real experiment')
    if context is not None and asset.get('context') != context:
        raise ValueError('asset protocol context mismatch')
    return asset


def checked_candidate(value, kind):
    if value.get('kind') != kind:
        raise ValueError('candidate kind mismatch')
    candidate = validate_code(value['code'], description=value['description'], kind=kind,
        interface_version=value.get('interface_version'), member_count=value.get('member_count'))
    if candidate.key != value['key']:
        raise ValueError('candidate code key mismatch')
    return candidate


def check_result(result, names):
    if type(result.get('valid')) is not bool:
        raise ValueError('explicit boolean result validity required')
    records = result.get('instances', [])
    if result.get('total_instances') != len(names):
        raise ValueError('batch size mismatch')
    if not result['valid']:
        if result.get('fitness') is not None:
            raise ValueError('invalid batch must not have partial mean fitness')
        return result
    if [r.get('file') for r in records] != list(names):
        raise ValueError('complete ordered instance results required')
    for row in records:
        if type(row.get('makespan')) is not int or row['makespan'] <= 0:
            raise ValueError('positive integer makespan required')
        if type(row.get('lower_bound')) not in (int, float) or not math.isfinite(row['lower_bound']) or row['lower_bound'] <= 0:
            raise ValueError('finite positive LB required')
        if (type(row.get('score')) not in (int, float) or not math.isfinite(row['score'])
                or not math.isclose(row['score'], -row['makespan']/row['lower_bound'], rel_tol=1e-12)):
            raise ValueError('score must match makespan and V5 LB')
    if (type(result.get('fitness')) not in (int, float) or not math.isfinite(result['fitness'])
            or not math.isclose(result['fitness'], fmean(r['score'] for r in records), rel_tol=1e-12)):
        raise ValueError('fitness must be full-batch mean of ratios')
    return result


def make_receipt(candidate, record, ledger, config, transport_identity):
    charged = ledger.data['records'][record['global_key']]
    response = parse_response(record['text'], kind=candidate.kind,
        interface_version=getattr(candidate, 'interface_version', None),
        member_count=getattr(candidate, 'member_count', None))
    if record['status'] != 'completed' or response.key != candidate.key or not charged['send_confirmed']:
        raise ValueError('candidate requires completed matching confirmed HTTP receipt')
    return {'mode': config.mode, 'model': config.provider.model, 'protocol': config.provider.protocol,
            'transport_identity': transport_identity, 'ledger_identity': ledger.identity,
            'global_key': record['global_key'], 'prompt_key': record['prompt_key'],
            'status': record['status'], 'send_confirmed': charged['send_confirmed'],
            'response_text': record['text'], 'response_sha256': digest(record['text']),
            'usage': record['usage']}


def check_receipt(receipt, candidate, mode):
    if (receipt.get('mode') != mode or receipt.get('status') != 'completed'
            or receipt.get('send_confirmed') is not True or not receipt.get('model')
            or not receipt.get('global_key') or not receipt.get('ledger_identity')):
        raise ValueError('completed same-mode generation provenance required')
    if receipt.get('response_sha256') != digest(receipt['response_text']):
        raise ValueError('receipt response hash mismatch')
    if parse_response(receipt['response_text'], kind=candidate.kind,
        interface_version=getattr(candidate, 'interface_version', None),
        member_count=getattr(candidate, 'member_count', None)).key != candidate.key:
        raise ValueError('receipt code does not match asset code')


def review_member(candidate, *, description, reviewer, method, note, timeout=3):
    if not all(isinstance(x, str) and x.strip() for x in (description, reviewer, method, note)):
        raise ValueError('explicit behavior description/reviewer/method/note required')
    if len(description) > 1000:
        raise ValueError('review description too long')
    samples = score_samples(candidate, timeout=timeout)
    return {'reviewed_code_key': candidate.key, 'description': description, 'reviewer': reviewer,
            'method': method, 'note': note, 'samples': samples, 'sample_sha256': digest(samples)}


def validate_row(row, names, mode, kind):
    candidate = checked_candidate(row['candidate'], kind)
    check_result(row['training_result'], names)
    if not row['training_result']['valid']:
        raise ValueError('asset members require valid complete train fitness')
    if row['scores'] != [r['score'] for r in row['training_result']['instances']] or row['fitness'] != row['training_result']['fitness']:
        raise ValueError('row score/fitness mismatch')
    check_receipt(row['receipt'], candidate, mode)
    return candidate


def load_h(asset, *, mode, context, size, names, review_timeout=3):
    check_seal(asset, kind='H_frozen', mode=mode, context=context)
    members = asset.get('members', [])
    if asset.get('member_count') != size or len(members) != size or size < 2:
        raise ValueError('exact configured K required, no silent reduction')
    if [r.get('member_id') for r in members] != list(range(size)) or any(type(r['member_id']) is not int for r in members):
        raise ValueError('contiguous built-in int member IDs required')
    if asset.get('training_files') != list(names):
        raise ValueError('H training split mismatch')
    candidates = []
    for row in members:
        candidate = validate_row(row, names, mode, 'h')
        review = row.get('review')
        if not isinstance(review, dict) or review.get('reviewed_code_key') != candidate.key:
            raise ValueError('H behavior review absent or bound to another code')
        if not all(isinstance(review.get(k), str) and review[k].strip() for k in ('description', 'reviewer', 'method', 'note')):
            raise ValueError('incomplete behavior review')
        if mode == 'real' and review['method'].startswith('synthetic'):
            raise ValueError('synthetic review is not a formal review')
        expected = review_member(candidate, description=review['description'], reviewer=review['reviewer'],
                                 method=review['method'], note=review['note'], timeout=review_timeout)
        if review != expected:
            raise ValueError('review samples/hash inconsistent with h code')
        candidates.append(Candidate(review['description'], candidate.code, candidate.key, 'h'))
    if len({c.key for c in candidates}) != size:
        raise ValueError('duplicate H code')
    return tuple(candidates)


def check_population(asset, *, mode, context, kind, H_hash, names, size):
    check_seal(asset, kind=kind, mode=mode, context=context)
    if asset.get('H_hash') != H_hash or asset.get('training_files') != list(names):
        raise ValueError('population H or train binding mismatch')
    rows = asset.get('population', [])
    if len(rows) != size or len({r['id'] for r in rows}) != size:
        raise ValueError('population must contain exactly N distinct IDs')
    for row in rows:
        validate_row(row, names, mode, 'U')
    if len({r['candidate']['key'] for r in rows}) != size:
        raise ValueError('duplicate population code')
    return rows
