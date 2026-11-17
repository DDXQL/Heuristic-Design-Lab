"""Bounded source import/build receipts; never execute the LKH binary."""
import gzip
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import urllib.request
from heuristic_design.core.storage import read, write, sha

ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT/'configurations/tsp-lkh-candidate-20261117/LKH-source.json'
OFFICIAL_URL = 'https://webhotel4.ruc.dk/~keld/research/LKH-3/LKH-3.0.13.tgz'
ARCHIVE_LIMIT = 20*1024*1024
EXPANDED_LIMIT = 64*1024*1024


def archive_bytes(path):
    with Path(path).open('rb') as f:
        raw = f.read(ARCHIVE_LIMIT+1)
    if len(raw) > ARCHIVE_LIMIT:
        raise ValueError('LKH archive exceeds20MiB')
    return raw


def inspect_archive(raw):
    """Check the complete gzip stream and all tar entries before extraction."""
    if len(raw) > ARCHIVE_LIMIT:
        raise ValueError('LKH archive exceeds20MiB')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
        expanded = f.read(EXPANDED_LIMIT+1)
    if len(expanded) > EXPANDED_LIMIT:
        raise ValueError('LKH expanded tar exceeds64MiB')
    files, names = {}, set()
    with tarfile.open(fileobj=io.BytesIO(expanded), mode='r:') as tf:
        for i, member in enumerate(tf):
            p = PurePosixPath(member.name)
            parts = member.name.rstrip('/').split('/')
            if (i >= 4096 or not parts or parts[0] != 'LKH-3.0.13'
                or p.is_absolute() or any(x in ('', '.', '..') for x in parts)
                or '\\' in member.name or ':' in member.name or str(p) in names
                or not (member.isdir() or member.isfile())
                or member.size < 0 or member.size > 16*1024*1024):
                raise ValueError('unsafe, duplicate or oversized LKH archive entry')
            names.add(str(p))
            if member.isfile():
                data = tf.extractfile(member).read()
                if len(data) != member.size:
                    raise ValueError('truncated LKH member')
                files[str(p)] = hashlib.sha256(data).hexdigest()
        required = ('README.txt', 'Makefile', 'SRC/Makefile', 'SRC/LKHmain.c')
        if any('LKH-3.0.13/'+name not in files for name in required):
            raise ValueError('LKH source/version files missing')
        if 'LKH-3.0.13/LKH' in names:
            raise ValueError('source archive must not supply a precompiled LKH binary')
        text = tf.extractfile('LKH-3.0.13/README.txt').read().decode('utf-8', 'strict')
    if not re.search(r'Version\s+3\.0\.13\b', text):
        raise ValueError('LKH README version differs from3.0.13')
    flat = ' '.join(text.split())
    if 'distributed for research use' not in flat or 'author reserves all rights' not in flat:
        raise ValueError('expected research-use source notice missing; inspect license manually')
    return {'version': '3.0.13', 'entry_count': len(names), 'source_files': files,
            'README_sha256': files['LKH-3.0.13/README.txt'],
            'license_scope': 'research use; author reserves all rights; preserve README/source notices'}


def _extract(raw, out):
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as tf:
        tf.extractall(out, filter='data')


def import_candidate(source, output):
    pin = read(PIN)
    out = Path(output).resolve()
    if out.exists():
        raise FileExistsError('new candidate source folder required; preserve prior receipt')
    raw = archive_bytes(source)
    observed = hashlib.sha256(raw).hexdigest()
    if observed != pin['archive_sha256']:
        raise ValueError('candidate SHA differs from adopted source pin')
    info = inspect_archive(raw)
    out.mkdir(parents=True)
    with (out/'LKH-3.0.13.tgz').open('xb') as f:
        f.write(raw)
    _extract(raw, out)
    record = {**info, 'state': 'imported', 'source_kind': 'third_party_candidate',
              'archive_sha256': observed, 'source_spec_sha256': sha(PIN),
              'input_basename': Path(source).name,
              'repository_url': pin['repository_url'],
              'declared_repository_commit': pin['declared_repository_commit'],
              'repository_commit_independently_verified': False,
              'official_equivalence_verified': False,
              'license_acceptance_required_before_build': True,
              'automatic_retry': False, 'LKH_runs': 0}
    write(out/'source-receipt.json', record)
    return {**record, 'output': str(out), 'LKH_executed': False}


def checked_record(source, *, built=False):
    out = Path(source).resolve()
    record = read(out/'source-receipt.json')
    allowed = ('built',) if built else ('downloaded', 'imported')
    if record.get('state') not in allowed:
        raise PermissionError('matching imported/downloaded source or completed build required')
    raw = archive_bytes(out/'LKH-3.0.13.tgz')
    observed = hashlib.sha256(raw).hexdigest()
    expected = record.get('archive_sha256', record.get('observed_archive_sha256'))
    if observed != expected:
        raise PermissionError('retained LKH archive identity differs')
    info = inspect_archive(raw)
    if record.get('source_kind') == 'third_party_candidate':
        pin = read(PIN)
        if (observed != pin['archive_sha256'] or record.get('source_spec_sha256') != sha(PIN)
            or record.get('declared_repository_commit') != pin['declared_repository_commit']
            or record.get('official_equivalence_verified') is not False
            or record.get('repository_commit_independently_verified') is not False
            or record.get('repository_url') != pin['repository_url']
            or 'official_URL' in record or record.get('source_files') != info['source_files']):
            raise PermissionError('candidate provenance differs; never relabel as official')
    elif record.get('source_kind', 'official') != 'official' or record.get('official_URL') != OFFICIAL_URL:
        raise PermissionError('unrecognized LKH source origin')
    for name, h in info['source_files'].items():
        path = out/name
        if (not path.resolve().is_relative_to(out) or path.is_symlink()
            or any(p.is_symlink() for p in path.parents if p != out and p.is_relative_to(out))
            or not path.is_file() or sha(path) != h):
            raise PermissionError('extracted source differs from retained archive: '+name)
    if built:
        binary = out/'LKH-3.0.13/LKH'
        if binary.is_symlink() or not binary.is_file() or str(binary) != record.get('binary') or sha(binary) != record.get('binary_sha256'):
            raise PermissionError('compiled LKH binary identity differs')
        if record.get('source_kind') == 'third_party_candidate':
            build = read(out/'build-reservation.json')
            if build.get('state') != 'completed' or build.get('returncode') != 0 or sha(out/'build.log') != record.get('build_log_sha256'):
                raise PermissionError('candidate needs a completed actual build/log receipt')
    return record


def prepare_source(output, download=False, build=False, academic=False):
    out = Path(output).resolve()
    receipt = out/'source-receipt.json'
    if not (download or build) or build and not academic:
        raise PermissionError('explicit download/build action; building requires research-license acceptance')
    if download:
        if out.exists():
            raise FileExistsError('new official source folder required; no overwrite/retry')
        out.mkdir(parents=True)
        write(receipt, {'state': 'download_reserved', 'official_URL': OFFICIAL_URL, 'automatic_retry': False})
        with urllib.request.urlopen(OFFICIAL_URL, timeout=30) as response:
            raw = response.read(ARCHIVE_LIMIT+1)
        info = inspect_archive(raw)
        with (out/'LKH-3.0.13.tgz').open('xb') as f:
            f.write(raw)
        _extract(raw, out)
        write(receipt, {**info, 'state': 'downloaded', 'source_kind': 'official', 'official_URL': OFFICIAL_URL,
                        'observed_archive_sha256': sha(out/'LKH-3.0.13.tgz'),
                        'independent_official_digest': 'not available; observed official-origin bytes only', 'LKH_runs': 0})
    if build:
        record = checked_record(out)
        claim = out/'build-reservation.json'
        binary = out/'LKH-3.0.13/LKH'
        if claim.exists() or binary.exists() or binary.is_symlink():
            raise FileExistsError('prior build/binary retained; no automatic rebuild')
        with claim.open('x') as f:
            import json
            json.dump({'state': 'reserved', 'automatic_retry': False}, f)
        try:
            with (out/'build.log').open('x') as log:
                subprocess.run(['make'], cwd=out/'LKH-3.0.13', stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
            checked_record(out)
            if binary.is_symlink() or not binary.is_file():
                raise ValueError('make did not produce a regular LKH binary')
            record.update(state='built', binary=str(binary), binary_sha256=sha(binary),
                          build_log_sha256=sha(out/'build.log'), research_license_accepted=True)
            write(claim, {'state': 'completed', 'returncode': 0, 'automatic_retry': False})
            write(receipt, record)
        except BaseException as e:
            write(claim, {'state': 'failed_or_unknown', 'error_type': type(e).__name__, 'automatic_retry': False})
            raise
    return {**read(receipt), 'LKH_executed': False}


def bind(source, output):
    record = checked_record(source, built=True)
    target = Path(output)
    if target.exists():
        raise FileExistsError('preserve prior bound LKH spec')
    spec = read(ROOT/'experiments/triad/lkh.pending.json')
    spec.update(lkh_binary=record['binary'], lkh_binary_sha256=record['binary_sha256'],
                source_identity={k: record.get(k) for k in ('source_kind', 'official_URL', 'archive_sha256', 'observed_archive_sha256', 'declared_repository_commit', 'official_equivalence_verified')},
                source_receipt_sha256=sha(Path(source)/'source-receipt.json'))
    # Candidate receipts never acquire an official URL, even with null value.
    if record.get('source_kind') == 'third_party_candidate':
        spec['source_identity'].pop('official_URL', None)
    write(target, spec)
    return {'bound_spec': str(target), 'source_kind': record.get('source_kind', 'official'), 'LKH_executed': False}
