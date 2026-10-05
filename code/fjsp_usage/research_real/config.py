"""Strict independent experiment parameters and transitive source fingerprints."""

from dataclasses import dataclass, asdict
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
from urllib.parse import urlsplit
import ipaddress

from fjsp_usage.research.protocol import SearchConfig, digest
from . import VERSION


def positive_int(value, label, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{label} requires a built-in integer >= {minimum}')
    return value


def finite_positive(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{label} requires a finite positive number')
    return value


def loopback_url(url):
    parts = urlsplit(url)
    try:
        return parts.hostname == 'localhost' or ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class ProviderConfig:
    endpoint: str
    model: str
    protocol: str = 'json-candidate-v1'
    api_key_env: str | None = None
    connect_timeout: float = 2.0
    read_timeout: float = 2.0
    total_timeout: float = 5.0
    max_output_tokens: int = 1024
    max_prompt_bytes: int = 262144
    input_token_reservation: int = 65536
    temperature: float = 0.0

    def __post_init__(self):
        parts = urlsplit(self.endpoint)
        if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username
                or parts.password or parts.query or parts.fragment):
            raise ValueError('endpoint must have a host and no credentials/query/fragment')
        if parts.scheme == 'http' and not loopback_url(self.endpoint):
            raise ValueError('HTTP is only allowed on loopback; remote endpoints require HTTPS')
        if not self.model or self.protocol not in ('json-candidate-v1',):
            raise ValueError('model and supported wire protocol required')
        if self.api_key_env is not None and (not self.api_key_env.isidentifier()
                                             or self.api_key_env.startswith('_')):
            raise ValueError('api_key_env must name a local environment variable')
        for name in ('connect_timeout', 'read_timeout', 'total_timeout'):
            finite_positive(getattr(self, name), name)
        for name in ('max_output_tokens', 'max_prompt_bytes', 'input_token_reservation'):
            positive_int(getattr(self, name), name)
        if type(self.temperature) not in (int, float) or not math.isfinite(self.temperature) or self.temperature < 0:
            raise ValueError('invalid temperature')


@dataclass(frozen=True)
class ExperimentConfig:
    provider: ProviderConfig
    mode: str = 'synthetic'
    real_requests_authorized: bool = False
    H_size: int = 10
    H_generations: int = 1
    H_attempts: int = 10
    H_initialization_cap: int = 50
    H_seed: int = 7
    population_size: int = 10
    cross_parents: int = 5
    mutation_parents: int = 1
    attempts_per_generation: int = 50
    generations: int = 20
    initialization_cap: int = 50
    seeds: tuple[int, ...] = (101, 102, 103)
    instance_timeout: float = 2.0
    total_request_cap: int = 12210
    total_token_cap: int | None = None
    phase_request_caps: dict | None = None
    cost_cap_estimate: float | None = None
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None
    price_source: str | None = None
    analysis: str = 'mean_population_std_and_paired_differences_v1'

    def __post_init__(self):
        if not isinstance(self.provider, ProviderConfig) or self.mode not in ('synthetic', 'real'):
            raise ValueError('provider and explicit synthetic/real mode required')
        if type(self.real_requests_authorized) is not bool:
            raise ValueError('real_requests_authorized must be bool')
        if self.mode == 'synthetic' and (not loopback_url(self.provider.endpoint)
                                         or self.provider.api_key_env):
            raise ValueError('synthetic mode requires loopback and no real credentials')
        positive_int(self.H_size, 'H_size', 2)
        for name in ('H_generations', 'H_attempts', 'H_initialization_cap', 'population_size',
                     'cross_parents', 'attempts_per_generation', 'generations',
                     'initialization_cap', 'total_request_cap'):
            positive_int(getattr(self, name), name)
        if self.H_initialization_cap < self.H_size or self.H_attempts % 10:
            raise ValueError('H initialization must cover K and attempts be a multiple of 10')
        if type(self.mutation_parents) is not int or self.mutation_parents != 1:
            raise ValueError('V5 mutation requires exactly one parent')
        if not self.seeds or len(set(self.seeds)) != len(self.seeds) or any(type(s) is not int for s in self.seeds):
            raise ValueError('nonempty predeclared distinct built-in integer seeds required')
        if type(self.H_seed) is not int:
            raise ValueError('H_seed must be an integer')
        finite_positive(self.instance_timeout, 'instance_timeout')
        self.u_search(self.seeds[0])  # validates N independently of K/crossover
        if self.total_token_cap is not None:
            positive_int(self.total_token_cap, 'total_token_cap')
        if self.phase_request_caps is not None:
            if set(self.phase_request_caps) != set(self.default_phase_caps()):
                raise ValueError('phase budgets must explicitly cover every predeclared phase')
            for value in self.phase_request_caps.values():
                positive_int(value, 'phase_request_cap')
            if len({self.phase_request_caps[f'r{s}/{a}'] for s in self.seeds for a in ('B0','B1','B2','P')}) != 1:
                raise ValueError('all paired groups/repeats require identical evolution request caps')
        prices = (self.input_price_per_million, self.output_price_per_million)
        if any(p is not None for p in prices):
            if any(type(p) not in (int, float) or not math.isfinite(p) or p < 0 for p in prices) or not self.price_source:
                raise ValueError('two nonnegative prices and their source required')
        if self.cost_cap_estimate is not None:
            finite_positive(self.cost_cap_estimate, 'cost_cap_estimate')
            if any(p is None for p in prices):
                raise ValueError('estimated cost cap requires prices')
        if self.analysis != 'mean_population_std_and_paired_differences_v1':
            raise ValueError('unsupported predeclared analysis')

    def check_dispatch(self):
        if self.mode == 'real' and not self.real_requests_authorized:
            raise ValueError('real requests have not been explicitly authorized in the run configuration')

    def u_search(self, seed):
        return SearchConfig(self.population_size, self.cross_parents, self.attempts_per_generation,
                            self.generations, self.initialization_cap, seed, self.instance_timeout)

    def h_search(self):
        return SearchConfig(self.H_size, 2, self.H_attempts, self.H_generations,
                            self.H_initialization_cap, self.H_seed, self.instance_timeout)

    def default_phase_caps(self):
        result = {'H/init': self.H_initialization_cap,
                  'H/search': self.H_generations * self.H_attempts}
        for seed in self.seeds:
            result[f'r{seed}/init'] = self.initialization_cap
            for arm in ('B0', 'B1', 'B2', 'P'):
                result[f'r{seed}/{arm}'] = self.generations * self.attempts_per_generation
        return result

    def phase_caps(self):
        return dict(self.phase_request_caps or self.default_phase_caps())

    def payload(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        value['provider'] = ProviderConfig(**value['provider'])
        if 'seeds' in value:
            value['seeds'] = tuple(value['seeds'])
        return cls(**value)


def fingerprint(root):
    """Conservative transitive closure: all project Python + versioned configs."""
    root = Path(root)
    paths = list((root / 'code').rglob('*.py'))
    paths += list((root / 'experiments').rglob('*.py'))
    paths += list((root / 'baselines').rglob('*.py'))
    paths += list((root / 'experiments').rglob('*.json'))
    paths += [root / 'requirements.txt']
    files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(paths) if '__pycache__' not in p.parts}
    dependencies = {}
    for name in ('numpy', 'pytz', 'tqdm'):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    return {'version': VERSION, 'files': files, 'python': platform.python_version(),
            'platform': platform.platform(), 'dependencies': dependencies}


def protocol(config, dataset, implementation):
    config = config.payload()
    return {'version': VERSION, 'mode': config['mode'], 'config': config,
            'dataset': dataset, 'implementation': implementation,
            'language': 'closed-numeric-AST-v1', 'state': 'V5-seven-scalars',
            'fitness': 'complete-split mean(-makespan/unrounded-V5-LB)',
            'actions': 'append-only; one U per step; selected h only; job/machine ties',
            'validation_tie': 'stable candidate ID', 'analysis': config['analysis']}
