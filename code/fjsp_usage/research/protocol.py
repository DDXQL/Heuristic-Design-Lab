"""Machine-checkable offline protocol and source/dataset fingerprints."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

from . import VERSION


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class SearchConfig:
    population_size: int = 5
    cross_parents: int = 5
    attempts_per_generation: int = 10
    generations: int = 2
    initialization_cap: int = 25
    seed: int = 20261005
    instance_timeout: float = 2.0

    def __post_init__(self):
        for name in ('population_size', 'cross_parents', 'attempts_per_generation',
                     'generations', 'initialization_cap', 'seed'):
            if type(getattr(self, name)) is not int:
                raise ValueError(f'{name} must be a built-in int')
        if not 2 <= self.cross_parents <= self.population_size:
            raise ValueError('distinct crossover parents require 2 <= p <= N')
        if self.generations < 1 or self.attempts_per_generation < 1 or self.attempts_per_generation % 10:
            raise ValueError('four-arm generations require positive multiples of 10 attempts')
        if (self.initialization_cap < self.population_size or type(self.instance_timeout) not in (int, float)
                or not math.isfinite(self.instance_timeout) or self.instance_timeout <= 0):
            raise ValueError('initialization cap/timeout invalid')


def build_protocol(config, *, training_files, training_hashes, data_manifest_sha256, members):
    return {
        'version': VERSION, 'mode': 'offline-mock', 'paid_requests_authorized': False,
        'H_status': 'handwritten development fixture, not a formal EoH-S set',
        'U_language': 'closed numeric AST-v1; no imports, attributes, containers or external calls; numeric intermediates <=1e100',
        'config': asdict(config), 'train_order': list(training_files),
        'train_sha256': dict(training_hashes), 'data_manifest_sha256': data_manifest_sha256,
        'H_keys': [member.key for member in members],
        'state': 'offline_v2 V5 seven scalars; one U invocation per scheduled operation',
        'score': '-makespan / max(longest shortest-work job,total shortest-work/M); arithmetic mean over ALL train',
        'tie_break': 'action: job then machine; population: fitness descending then stable candidate id',
        'operators': {'B0': ['E1', 'E2', 'M1', 'M2', 'M3'],
                      'B1': ['E1', 'E2', 'M1', 'M2', 'M3'],
                      'B2': ['CROSS', 'MUTATE'], 'P': ['CROSS', 'MUTATE']},
        'source': 'EoH paper section 3.4, https://arxiv.org/html/2401.02051v3',
        'validation_evaluated': False, 'test_evaluated': False,
    }


def source_hashes(root):
    root = Path(root)
    paths = list((root / 'code/fjsp_usage/research').glob('*.py')) + [
        root / 'code/fjsp_usage/offline_v2.py', root / 'code/fjsp_usage/training_v2.py',
        root / 'code/llm4ad/task/optimization/fjsp_set/scheduler.py',
        root / 'code/llm4ad/task/optimization/fjsp_set/instances.py',
    ]
    paths += list((root / 'experiments/tier2/research_v1').glob('*.py'))
    paths += list((root / 'experiments/tier2/research_v1').glob('*.json'))
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}
