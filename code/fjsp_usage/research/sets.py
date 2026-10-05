"""Audited, minimal EoH-S complementary survival/parent mechanisms.

Adapted from source population.py at b3b67d6; ties are explicitly stabilised.
Equal fitness/vectors do not imply duplicate code. This adapter's bounded
generation protocol is separate from the original threaded EoH-S runner.
"""

from itertools import combinations
import math

from .candidates import validate_code
from .events import atomic_json
from .protocol import digest


def ranked(population):
    return sorted(population, key=lambda row: (-row['fitness'], row['id']))


def complementary_survival(population, size):
    remaining = ranked(population)
    if not remaining:
        return []
    width = len(remaining[0]['scores'])
    if width < 1 or any(len(p['scores']) != width or any(not math.isfinite(x) for x in p['scores'])
                        for p in remaining):
        raise ValueError('aligned finite training vectors required')
    survivors = [remaining.pop(0)]
    while remaining and len(survivors) < size:
        envelope = [max(row['scores'][i] for row in survivors) for i in range(width)]
        # remaining stays sorted by mean/id, so zero improvement ties are stable.
        best = max(range(len(remaining)), key=lambda index: sum(
            max(a, b) - a for a, b in zip(envelope, remaining[index]['scores'])))
        survivors.append(remaining.pop(best))
    return survivors


def complementary_parents(population, rng, *, top_k=5):
    pool = ranked(population)[:top_k]
    pairs = list(combinations(pool, 2))
    if not pairs:
        raise ValueError('two H parents required')
    pairs.sort(key=lambda pair: (-sum(abs(a-b) for a, b in zip(pair[0]['scores'], pair[1]['scores'])),
                                  pair[0]['id'], pair[1]['id']))
    return list(rng.choices(pairs, weights=[1/(i+1) for i in range(len(pairs))], k=1)[0])


def export_mock_set(path, population, *, size, training_files, audit_sha256):
    if len(population) != size:
        raise ValueError('insufficient H members; never silently reduce K')
    members = []
    for index, row in enumerate(population):
        candidate = validate_code(row['candidate']['code'], description=row['candidate']['description'], kind='h')
        if len(row['scores']) != len(training_files) or not all(math.isfinite(x) for x in row['scores']):
            raise ValueError('H export requires complete finite training scores')
        members.append({'member_id': index, **row['candidate'], 'scores': row['scores'],
                        'source_candidate_id': row['id'], 'code_sha256': candidate.key,
                        'behavior_reviewed': False})
    artifact = {'status': 'MOCK adapter verification; not a formal EoH-S-generated set',
                'training_files': list(training_files), 'audit_sha256': audit_sha256,
                'members': members, 'member_count': size}
    artifact['artifact_sha256'] = digest(artifact)
    atomic_json(path, artifact)
    return artifact
