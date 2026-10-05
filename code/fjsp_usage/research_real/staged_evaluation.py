"""Manifest-only metadata preflight, split loading gated by sealed stage assets."""

import hashlib
import json
from pathlib import Path

from fjsp_usage.research.protocol import digest
from .runtime import evaluate
from llm4ad.task.optimization.fjsp_set import load_instance
from .assets import check_seal, check_result


class StagedDataset:
    def __init__(self, manifest, *, project_root, mode):
        self.path = Path(manifest)
        raw = self.path.read_bytes()
        self.manifest = json.loads(raw)
        self.mode = mode
        if self.manifest.get('synthetic', False) != (mode == 'synthetic'):
            raise ValueError('dataset synthetic/real mode mismatch')
        self.root = (Path(project_root) / self.manifest['portable_root']).resolve()
        self.names = {}
        self.paths = {}
        self.opened = []
        for split in ('train', 'validation', 'test'):
            names = self.manifest['split'][split]
            if not names or len(set(names)) != len(names):
                raise ValueError('each split must be nonempty and unique')
            paths = [(self.root / name).resolve() for name in names]
            if any(not p.is_relative_to(self.root) for p in paths) or len(set(paths)) != len(paths):
                raise ValueError('path escape or alias duplicate')
            for name in names:
                sha = self.manifest['files'][name]['sha256']
                if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
                    raise ValueError('valid file hashes required in manifest')
            self.names[split], self.paths[split] = tuple(names), tuple(paths)
        for left, right in (('train', 'validation'), ('train', 'test'), ('validation', 'test')):
            if set(self.paths[left]) & set(self.paths[right]):
                raise ValueError('data splits overlap')
        self.metadata = {'manifest_sha256': hashlib.sha256(raw).hexdigest(),
                         'synthetic': mode == 'synthetic', 'split': self.manifest['split'],
                         'hashes': {name: self.manifest['files'][name]['sha256']
                                    for split in self.names.values() for name in split}}
        self.key = digest(self.metadata)

    def authorize(self, split, *, context=None, gate=None, population_hash=None):
        if split not in self.names:
            raise ValueError('unknown split')
        if split != 'train':
            kind = 'Search_complete' if split == 'validation' else 'Experiment_frozen'
            check_seal(gate, kind=kind, mode=self.mode, context=context)
            if gate.get('dataset_hash') != self.key:
                raise ValueError('stage gate/data binding mismatch')
            if split == 'validation' and (population_hash is None or population_hash not in
                    gate.get('population_hashes', []) + [gate.get('reference_H_hash')]):
                raise ValueError('only final registered populations may access validation')
            if split == 'test' and not gate.get('selection_hash'):
                raise ValueError('test requires validation selection and experiment freeze')

    def verify(self, split, *, context=None, gate=None, population_hash=None):
        self.authorize(split, context=context, gate=gate, population_hash=population_hash)
        for name, path in zip(self.names[split], self.paths[split]):
            if hashlib.sha256(path.read_bytes()).hexdigest() != self.manifest['files'][name]['sha256']:
                raise ValueError(f'instance hash mismatch: {name}')

    def load(self, split, *, context=None, gate=None, population_hash=None):
        self.verify(split, context=context, gate=gate, population_hash=population_hash)
        instances = []
        for name, path in zip(self.names[split], self.paths[split]):
            expected = self.manifest['files'][name]['sha256']
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f'instance hash mismatch: {name}')
            instance = load_instance(path)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f'instance changed during load: {name}')
            self.opened.append((split, name))
            instances.append(instance)
        return tuple(instances)

    def evaluate(self, candidate, members, split, *, timeout, context=None, gate=None,
                 population_hash=None, instances=None):
        self.authorize(split, context=context, gate=gate, population_hash=population_hash)
        if instances is None:
            instances = self.load(split, context=context, gate=gate, population_hash=population_hash)
        result = evaluate(candidate, members, instances, self.names[split], timeout=timeout)
        return check_result(result, self.names[split])


def create_synthetic_dataset(directory, *, count=2):
    """Tracked-format fixture files only; no access to benchmark directories."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {'synthetic': True, 'portable_root': '.', 'split': {}, 'files': {}}
    for split in ('train', 'validation', 'test'):
        manifest['split'][split] = []
        for i in range(count):
            name = f'{split}_{i}.fjsp'
            text = (f'NAME: {split}_{i}\nTYPE: FJSP\nJOBS: 2\nMACHINES: 2\nJOB_SECTION\n'
                    f'2 2 1 {3+i} 2 {2+i} 2 1 2 2 4\n1 2 1 2 2 {3+i}\n')
            path = directory / name
            path.write_text(text)
            manifest['split'][split].append(name)
            manifest['files'][name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    path = directory / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    return path
