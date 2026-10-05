"""All-or-invalid training batch evaluation, separate from validation and test."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Sequence

from llm4ad.task.optimization.fjsp_set import load_instance
from .offline_v2 import Priority, Selector, construct_usage_schedule


@dataclass(frozen=True)
class InstanceResult:
    file: str
    instance: str
    makespan: int
    lower_bound: float
    score: float


@dataclass(frozen=True)
class TrainingResult:
    valid: bool
    total_instances: int
    instances: tuple[InstanceResult, ...]
    mean_training_fitness: float | None
    failed_instance: str | None = None
    error: str | None = None


class TrainingEvaluation:
    """Load only train entries from an explicit manifest; hash-check those files.

    Validation and test names are inspected solely to check split separation.
    Their data files are never opened. Any failed solve invalidates the entire U;
    successful prefix records are diagnostics, never a partial fitness estimate.
    """

    def __init__(self, manifest_path: str | Path, *, project_root: str | Path):
        manifest_path = Path(manifest_path)
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        self.manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        data_root = (Path(project_root) / manifest['portable_root']).resolve()
        split = manifest['split']
        paths_by_split = {}
        for name in ('train', 'validation', 'test'):
            paths = tuple((data_root / item).resolve() for item in split[name])
            if any(not path.is_relative_to(data_root) for path in paths):
                raise ValueError(f'{name} contains a path outside data root')
            if len(set(paths)) != len(paths):
                raise ValueError(f'{name} contains duplicate paths')
            paths_by_split[name] = paths
        if not paths_by_split['train']:
            raise ValueError('training batch must contain at least one instance')
        for left, right in (('train', 'validation'), ('train', 'test'), ('validation', 'test')):
            if set(paths_by_split[left]) & set(paths_by_split[right]):
                raise ValueError(f'{left} and {right} splits overlap')

        self.training_files = tuple(split['train'])
        self.training_hashes = {}
        instances = []
        for name, path in zip(self.training_files, paths_by_split['train']):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != manifest['files'][name]['sha256']:
                raise ValueError(f'training instance SHA-256 mismatch: {name}')
            self.training_hashes[name] = digest
            instances.append(load_instance(path))
        self.instances = tuple(instances)

    def evaluate(self, heuristics: Sequence[Priority], selector: Selector) -> TrainingResult:
        members = tuple(heuristics)
        records = []
        for name, instance in zip(self.training_files, self.instances):
            try:
                result = construct_usage_schedule(instance, members, selector)
            except Exception as exc:
                cause = f'; caused by {type(exc.__cause__).__name__}: {exc.__cause__}' if exc.__cause__ else ''
                return TrainingResult(False, len(self.instances), tuple(records), None,
                                      name, f'{type(exc).__name__}: {exc}{cause}')
            records.append(InstanceResult(name, instance.name, result.schedule.makespan,
                                          result.lower_bound, result.score))
        return TrainingResult(True, len(self.instances), tuple(records),
                              fmean(record.score for record in records))
