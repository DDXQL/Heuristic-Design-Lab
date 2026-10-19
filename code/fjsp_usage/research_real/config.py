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
from .prompts import prompt_manifest


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
    output_token_reservation: int | None = None
    max_prompt_bytes: int = 262144
    input_token_reservation: int = 65536
    temperature: float | None = 0.0
    reasoning_effort: str | None = None
    expected_response_model: str | None = None
    thinking: str | None = None
    stream_response: bool = False

    def __post_init__(self):
        if type(self.stream_response) is not bool or (self.stream_response and self.protocol != "openai-chat-v1"):
            raise ValueError("stream_response requires openai-chat-v1 and a boolean")
        parts = urlsplit(self.endpoint)
        if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username
                or parts.password or parts.query or parts.fragment):
            raise ValueError('endpoint must have a host and no credentials/query/fragment')
        if parts.scheme == 'http' and not loopback_url(self.endpoint):
            raise ValueError('HTTP is only allowed on loopback; remote endpoints require HTTPS')
        if not self.model or self.protocol not in ('json-candidate-v1', 'openai-chat-v1', 'deepseek-chat-v1'):
            raise ValueError('model and supported wire protocol required')
        if self.api_key_env is not None and (not self.api_key_env.isidentifier()
                                             or self.api_key_env.startswith('_')):
            raise ValueError('api_key_env must name a local environment variable')
        for name in ('connect_timeout', 'read_timeout', 'total_timeout'):
            finite_positive(getattr(self, name), name)
        for name in ('max_output_tokens', 'max_prompt_bytes', 'input_token_reservation'):
            positive_int(getattr(self, name), name)
        if self.output_token_reservation is not None:
            positive_int(self.output_token_reservation, 'output_token_reservation', self.max_output_tokens)
        if self.temperature is not None and (type(self.temperature) not in (int, float) or not math.isfinite(self.temperature) or self.temperature < 0):
            raise ValueError('invalid temperature')
        if self.reasoning_effort is not None and self.reasoning_effort not in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'):
            raise ValueError('invalid reasoning_effort')
        if self.expected_response_model is not None and (not isinstance(self.expected_response_model, str) or not self.expected_response_model):
            raise ValueError('expected_response_model must be a nonempty string')
        if self.protocol == 'json-candidate-v1' and (self.reasoning_effort is not None or self.expected_response_model is not None):
            raise ValueError('model audit/reasoning fields require openai-chat-v1')
        if self.thinking is not None and (self.protocol != 'deepseek-chat-v1' or self.thinking not in ('enabled', 'disabled')):
            raise ValueError('thinking requires deepseek-chat-v1 and enabled/disabled')
        if self.protocol == 'deepseek-chat-v1':
            if self.thinking is None:
                raise ValueError('DeepSeek thinking mode must be explicitly locked')
            if self.thinking == 'disabled' and self.reasoning_effort not in (None, 'none'):
                raise ValueError('disabled thinking conflicts with reasoning effort')
            if self.thinking == 'enabled' and (self.reasoning_effort == 'none' or self.temperature is not None):
                raise ValueError('enabled thinking requires no temperature and a compatible effort')


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
    review_timeout: float = 3.0
    total_request_cap: int = 12210
    total_token_cap: int | None = None
    platform_quota_ceiling: int | None = None
    platform_quota_reservation: int | None = None
    platform_quota_query_interval: float = 75.0
    phase_request_caps: dict | None = None
    cost_cap_estimate: float | None = None
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None
    price_source: str | None = None
    analysis: str = 'mean_population_std_and_paired_differences_v1'
    purpose: str = 'research'
    development_h_source: dict | None = None
    development_continuation_source: dict | None = None
    development_acceptance: dict | None = None
    training_diagnostics: bool = False
    conditional_research: dict | None = None

    def __post_init__(self):
        if type(self.training_diagnostics) is not bool:
            raise ValueError('training_diagnostics must be boolean')
        if self.conditional_research is not None:
            from .conditional_research import validate_declaration
            validate_declaration(self)
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
        finite_positive(self.review_timeout, 'review_timeout')
        self.u_search(self.seeds[0])  # validates N independently of K/crossover
        if self.total_token_cap is not None:
            positive_int(self.total_token_cap, 'total_token_cap')
        if self.platform_quota_ceiling is not None or self.platform_quota_reservation is not None:
            positive_int(self.platform_quota_ceiling, 'platform_quota_ceiling')
            positive_int(self.platform_quota_reservation, 'platform_quota_reservation')
            if (self.mode != 'real' or self.provider.endpoint != 'https://leafapi.cc/v1/chat/completions'
                    or self.provider.api_key_env != 'LEAFAPI_API_KEY'):
                raise ValueError('platform quota guard requires the explicit real Leaf origin/credential')
            if self.platform_quota_reservation > self.platform_quota_ceiling:
                raise ValueError('quota reservation exceeds ceiling')
        finite_positive(self.platform_quota_query_interval, 'platform_quota_query_interval')
        if self.phase_request_caps is not None:
            if set(self.phase_request_caps) != set(self.default_phase_caps()):
                raise ValueError('phase budgets must explicitly cover every predeclared phase')
            for value in self.phase_request_caps.values():
                positive_int(value, 'phase_request_cap')
            if len({self.phase_request_caps[f'r{s}/{a}'] for s in self.seeds for a in self.search_arms()}) != 1:
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
        if self.purpose not in ('research', 'framework_development'):
            raise ValueError('explicit research/framework_development purpose required')
        if self.development_h_source is not None:
            source = self.development_h_source
            fields = {'run', 'protocol_sha256', 'checkpoint_sha256', 'budget_sha256', 'journal_sha256'}
            if (self.purpose != 'framework_development' or self.mode != 'real'
                    or not isinstance(source, dict) or set(source) != fields):
                raise ValueError('H source reuse requires explicit real framework development and four hashes')
            from pathlib import PurePosixPath
            path = PurePosixPath(source['run'])
            if path.is_absolute() or '..' in path.parts or len(path.parts) != 1:
                raise ValueError('development source must name one project runs child')
            for field in fields - {'run'}:
                value = source[field]
                if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                    raise ValueError('source hashes must be SHA256 hex')

        if self.development_continuation_source is not None:
            from pathlib import PurePosixPath
            source = self.development_continuation_source
            if (self.purpose != 'framework_development' or self.mode != 'real'
                    or self.development_h_source is not None
                    or not isinstance(source, dict)
                    or set(source) not in ({'run', 'files_sha256'}, {'run', 'files_sha256', 'search_change'})):
                raise ValueError('continuation requires real development, hash pins and no H-generation import')
            path = PurePosixPath(source['run'])
            if path.is_absolute() or len(path.parts) != 1 or '..' in path.parts:
                raise ValueError('continuation source must name one project runs child')
            if not isinstance(source['files_sha256'], dict) or not source['files_sha256']:
                raise ValueError('continuation source requires file hash pins')
            for name, value in source['files_sha256'].items():
                path = PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or str(path) != name:
                    raise ValueError('continuation file must be a normal relative path')
                if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                    raise ValueError('continuation file hash must be SHA256 hex')
            if 'search_change' in source:
                change = source['search_change']
                fields = {'from','to','shared_initial','scope','first_arm','reason'}
                snapshots = {'population_size','generations','attempts_per_generation','phase_request_caps'}
                if (not isinstance(change,dict) or set(change)!=fields
                        or change['shared_initial']!='reuse_only' or change['scope']!='train_only'
                        or change['first_arm']!='P' or not isinstance(change['reason'],str)
                        or not change['reason'].strip()
                        or any(not isinstance(change[k],dict) or set(change[k])!=snapshots for k in ('from','to'))):
                    raise ValueError('development search change requires exact parameter snapshots and train-only P-first reuse')

        if self.development_acceptance is not None:
            d = self.development_acceptance
            fields = {'version','arm','max_new_requests','retained_unknown_requests',
                      'validation_names','test_names','previous_batches','billing_evidence','authorization'}
            if (self.purpose != 'framework_development' or self.mode != 'real'
                    or not self.development_continuation_source
                    or 'search_change' not in self.development_continuation_source
                    or not isinstance(d,dict) or not fields<=set(d)
                    or set(d)-fields-{'search_resume_source','settled_failed_requests'}
                    or d['version']!='single-P-seen-train-v1' or d['arm']!='P'
                    or d['max_new_requests']!=10 or len(self.seeds)!=1
                    or self.population_size!=5 or self.cross_parents!=5 or self.mutation_parents!=1
                    or self.generations!=1 or self.attempts_per_generation!=10
                    or not isinstance(d['authorization'],str) or not d['authorization'].strip()):
                raise ValueError('single-P development acceptance requires explicitly authorized N5/one generation/ten slots')
            if (not isinstance(d['retained_unknown_requests'],dict)
                    or any(not isinstance(k,str) or type(v)!=int or v<=0 for k,v in d['retained_unknown_requests'].items())
                    or not isinstance(d['previous_batches'],dict) or not isinstance(d['billing_evidence'],dict)):
                raise ValueError('explicit retained reservations and historical evidence required')
            for key in ('validation_names','test_names'):
                if (not isinstance(d[key],list) or not d[key] or len(set(d[key]))!=len(d[key])
                        or any(not isinstance(n,str) for n in d[key])):
                    raise ValueError('nonempty unique seen-training development subsets required')
            if set(d['validation_names']) & set(d['test_names']):
                raise ValueError('development validation/test subsets must be disjoint')

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
        if (self.conditional_research or {}).get('version') == 'single-ID-update-frequency-v1':
            return {'r201/A':30,'r201/B':30}
        result = {'H/init': self.H_initialization_cap,
                  'H/search': self.H_generations * self.H_attempts}
        for seed in self.seeds:
            result[f'r{seed}/init'] = self.initialization_cap
            if self.conditional_research and self.conditional_research.get('model_migration'):
                result[f'r{seed}/diagnostic'] = 1
            for arm in self.search_arms():
                result[f'r{seed}/{arm}'] = self.generations * self.attempts_per_generation
        return result

    def search_arms(self):
        if (self.conditional_research or {}).get('version') == 'single-ID-update-frequency-v1':
            return ('A','B')
        return ('B0', 'B1', 'B2', 'P')

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
    from .state_diagnostics import state_contract
    return {'version': VERSION, 'mode': config['mode'], 'config': config,
            'prompt_pack': prompt_manifest(),
            'dataset': dataset, 'implementation': implementation,
            'language': 'closed-numeric-AST-v1', 'state': 'V5-seven-scalars',
            'state_contract': state_contract(),
            'evaluation_deadlines': 'Two primary solves share instance_timeout; observational replay has a separate instance_timeout and cannot change primary validity/fitness.',
            'fitness': 'complete-split mean(-makespan/unrounded-V5-LB)',
            'actions': 'append-only; one U per step; selected h only; job/machine ties',
            'H_review_execution': 'spawned process; whole-sample deadline incl compile/startup; deterministic recheck',
            'validation_tie': 'stable candidate ID', 'analysis': config['analysis']}
