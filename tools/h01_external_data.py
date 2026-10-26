"""Pinned public data conversion, identity audit and outcome-blind sampling only."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
import tarfile

from tools import ind_evo_h01 as old

NAME = 'h01-champion-hurink-rdata20-seed501-20261026-v1'
ROOT = old.ROOT
RUN = ROOT/'runs'/NAME
REPORT = ROOT/'reports'/NAME
COMMIT = 'ac4c3402312bfbeafcf4472d78be567d4e6b46ab'
SEED = 2026102617
RULE = ROOT/'docs/H01_EXTERNAL_CONFIRMATION_SELECTION_V1.md'
sha = old.sha
read = old.read
write = old.write


def parse_text(text):
    values = [int(v) for v in text.split()]
    if len(values) < 2: raise ValueError('missing jobs/machines')
    nj, nm = values[:2]; index = 2; jobs = []
    if nj < 1 or nm < 1: raise ValueError('empty problem')
    for _ in range(nj):
        no = values[index]; index += 1; job = []
        if no < 1: raise ValueError('empty job')
        for _ in range(no):
            na = values[index]; index += 1; alternatives = []
            if na < 1: raise ValueError('empty alternatives')
            for _ in range(na):
                m, p = values[index:index+2]; index += 2
                if not 0 <= m < nm or p < 1: raise ValueError('invalid machine/time')
                alternatives.append((m, p))
            if len({m for m, _ in alternatives}) != na: raise ValueError('duplicate machine')
            job.append(tuple(sorted(alternatives)))
        jobs.append(tuple(job))
    if index != len(values): raise ValueError('trailing/truncated tokens')
    return nm, tuple(jobs)


def from_instance(instance):
    return instance.machine_count, tuple(tuple(tuple(op.alternatives) for op in job) for job in instance.jobs)


def from_json(data):
    return data['machines'], tuple(tuple(tuple(sorted((a['machine'], a['processing']) for a in op))
                                       for op in job) for job in data['jobs'])


def identities(problem):
    nm, jobs = problem
    coarse = sorted(tuple(tuple(sorted(p for _, p in op)) for op in job) for job in jobs)
    return {'ordered_content': old.digest(problem), 'job_permutation_content': old.digest((nm, sorted(jobs))),
            'machine_label_free_conservative': old.digest((nm, coarse))}


def independent_lb(problem):
    nm, jobs = problem
    work = [sum(min(p for _, p in op) for op in job) for job in jobs]
    return float(max(Fraction(max(work)), Fraction(sum(work), nm)))


def serialize(problem, name):
    nm, jobs = problem
    lines = [f'NAME: {name}', 'TYPE: FJSP', f'JOBS: {len(jobs)}', f'MACHINES: {nm}', 'JOB_SECTION']
    for job in jobs:
        row = [len(job)]
        for op in job:
            row.append(len(op))
            for m, p in op: row.extend((m+1, p))
        lines.append(' '.join(map(str, row)))
    return '\n'.join(lines)+'\n'


def stratum(operations):
    return 0 if operations <= 100 else 1 if operations <= 200 else 2


def select(pool):
    rng = random.Random(SEED); selected = []
    for layer, quota in enumerate((7, 7, 6)):
        eligible = sorted((r for r in pool if r['eligible'] and r['stratum'] == layer), key=lambda r: r['source_path'])
        selected.extend(rng.sample(eligible, min(quota, len(eligible))))
    return selected


def prepare():
    if (RUN/'Data_manifest.json').exists(): raise ValueError('data manifest already frozen; no re-sampling')
    REPORT.mkdir(exist_ok=True); (RUN/'inputs').mkdir(exist_ok=True)
    source = RUN/'source'; archive = source/'SchedulingLab_ac4c340.tar.gz'
    previous = old.check(); cp = read(old.RUN/'checkpoint.json'); old.ledger(cp, previous)
    known = []; seen = {k: set() for k in identities((1, ((( (0, 1), ),),)))}
    legacy = ROOT.parent/'FJSP-Heuristic-Research/data/fjsp'
    files = sorted(legacy.glob('Behnke*.fjsp'))
    if len(files) != 60: raise ValueError('must account for all original Behnke60')
    manifest = read(ROOT/'data/fjsp_manifest.json')
    # No old strategy results consulted. Old holdout files only parsed to detect duplicates.
    for path in files:
        instance = old.certified.s.v2.load_instance(path); ids = identities(from_instance(instance))
        row = {'file': path.name, 'sha256': sha(path), **ids,
               'old_partition': next(k for k in ('train', 'validation', 'test') if path.name in manifest['split'][k])}
        known.append(row)
        for k, value in ids.items(): seen[k].add(value)
    pool = []; prefix = 'fjsp-instances-'+COMMIT+'/'
    with tarfile.open(archive, 'r:gz') as tar:
        for name in ('README.md', 'LICENSE'):
            (source/name).write_bytes(tar.extractfile(prefix+name).read())
        for number in range(1, 41):
            relative = f'hurink/rdata/la{number:02d}'; txt = tar.extractfile(prefix+relative+'.txt').read()
            js = tar.extractfile(prefix+relative+'.json').read()
            (source/f'la{number:02d}.txt').write_bytes(txt); (source/f'la{number:02d}.json').write_bytes(js)
            problem = parse_text(txt.decode()); assert problem == from_json(json.loads(js))
            nm, jobs = problem; operations = sum(map(len, jobs)); ids = identities(problem)
            output = RUN/'inputs'/f'HurinkR_la{number:02d}.fjsp'
            output.write_text(serialize(problem, output.stem))
            loaded = old.certified.s.v2.load_instance(output)
            assert from_instance(loaded) == problem
            lb = independent_lb(problem); assert lb == old.certified.s.v2.lower_bound_v5(loaded)
            duplicates = [k for k, value in ids.items() if value in seen[k]]
            eligible = 10 <= len(jobs) <= 30 and 5 <= nm <= 15 and 50 <= operations <= 300 and not duplicates
            pool.append({'file': output.name, 'relative_path': str(output.relative_to(RUN)), 'sha256': sha(output),
                'source_path': relative+'.txt', 'raw_source_sha256': hashlib.sha256(txt).hexdigest(),
                'source_json_sha256': hashlib.sha256(js).hexdigest(), 'source_txt_json_equal': True,
                'jobs': len(jobs), 'machines': nm, 'operations': operations, 'LB': lb,
                'flexibility': sum(len(op) for job in jobs for op in job)/(operations*nm),
                'stratum': stratum(operations), 'eligible': eligible, 'duplicate_exclusions': duplicates, **ids})
            if eligible:
                for k, value in ids.items(): seen[k].add(value)
    selected = select(pool)
    if not selected: raise ValueError('no eligible new data')
    write(RUN/'Data_manifest.json', {'source_commit': COMMIT, 'source_archive_sha256': sha(archive),
        'source_url': 'https://github.com/SchedulingLab/fjsp-instances', 'selection_rule_sha256': sha(RULE),
        'selection_seed': SEED, 'quota': [7, 7, 6], 'candidate_pool': pool, 'instances': selected,
        'legacy_content_comparisons': known, 'score_or_BKS_used_for_selection': False,
        'distribution': 'cross-benchmark and smaller-machine-count transfer; NOT same-distribution holdout'})
    source_audit = read(old.B2/'Plan.json')
    history = {'original_train_H_B2': source_audit['names'], 'current_IND_EVO_inputs': [r['file'] for r in previous['instances']],
        'new_Hurink_usage_found_in_named_H_B2_IND_EVO_protocols': False,
        'local_inventory': {'current': sorted(p.name for p in (ROOT/'data/fjsp').glob('*.fjsp')),
                            'main': sorted(p.name for p in legacy.glob('*.fjsp'))},
        'known_project_holdouts_excluded': ['validation11', 'test28'],
        'limits': 'Bounded named-protocol/inventory audit, not proof against unregistered human/external use or LLM pretraining. Public distribution differs from training.',
        'old60_read_purpose': 'canonical duplicate detection only; no old holdout scheduling or performance comparisons'}
    write(RUN/'Data_history.json', history)
    print({'pool': len(pool), 'eligible': sum(r['eligible'] for r in pool), 'selected': len(selected), 'seed': SEED})


if __name__ == '__main__': prepare()
