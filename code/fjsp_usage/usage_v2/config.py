"""Two-arm, training-only protocol. Old four-arm configurations remain unchanged."""
from dataclasses import dataclass
from fjsp_usage.research_real.config import ExperimentConfig
from fjsp_usage.research_real.state_diagnostics import state_contract
from .prompts import prompt_manifest
from . import VERSION,LANGUAGE,NORMALIZATION,HISTORY

ARMS=('A','B')
LOCAL_REQUEST_EXPERIMENT='SELECT-vs-SELECT-or-MIX-local-requests-v1'
@dataclass(frozen=True)
class UsageConfig(ExperimentConfig):
    u_interface_version: str=VERSION
    max_active_members: int=2
    action_score_normalization: str=NORMALIZATION
    history_rule: str=HISTORY
    usage_experiment_version: str='SELECT-vs-SELECT-or-MIX-train-v1-20261012'
    fixed_h_source: dict | None=None

    def search_arms(self):return ARMS
    def default_phase_caps(self):
        return {key:cap for s in self.seeds for key,cap in
            [(f'r{s}/init',self.initialization_cap)]+[(f'r{s}/{a}',self.generations*self.attempts_per_generation) for a in ARMS]}
    def __post_init__(self):
        super().__post_init__()
        if self.fixed_h_source is not None:
            from .fixed_h import validate_declaration
            validate_declaration(self)
        expected_version=LOCAL_REQUEST_EXPERIMENT if self.request_budget is not None else 'SELECT-vs-SELECT-or-MIX-train-v1-20261012'
        if (self.u_interface_version!=VERSION or type(self.max_active_members) is not int or self.max_active_members!=2
                or self.action_score_normalization!=NORMALIZATION or self.history_rule!=HISTORY
                or self.usage_experiment_version!=expected_version
                or self.development_h_source or self.development_continuation_source or self.development_acceptance):
            raise ValueError('usage-v2 protocol must use explicit fixed semantics, never old development continuation')
        if self.mode=='real' and ((not self.conditional_research and self.request_budget is None) or len(self.seeds)!=1 or self.population_size!=5
                or self.cross_parents!=5 or self.mutation_parents!=1 or self.initialization_cap!=20
                or self.generations!=1 or self.attempts_per_generation!=10 or self.total_request_cap!=40):
            raise ValueError('real pilot requires explicit conditional/local protocol, N5, init20, one seed, one generation of ten slots per arm, cap40')
    def allowed_modes(self,arm):
        if arm not in ('INIT',*ARMS): raise ValueError('unknown paired arm')
        return (0,1) if arm=='B' else (0,)
    def payload(self):
        value=super().payload()
        if self.fixed_h_source is None:value.pop('fixed_h_source')
        return value


def protocol(config,dataset,implementation):
    return {'version':config.usage_experiment_version,'mode':config.mode,'config':config.payload(),
        'dataset':dataset,'implementation':implementation,'prompt_pack':prompt_manifest(),
        'language':LANGUAGE,'state':'V5-seven-scalars','state_contract':{**state_contract(),'previous_semantics':HISTORY},
        'u_interface':VERSION,'actions':NORMALIZATION,'arm_modes':{a:list(config.allowed_modes(a)) for a in ('INIT',*ARMS)},
        'fitness':'complete-train mean(-makespan/unrounded-V5-LB)',
        'holdouts':'training-only entry; validation/test unavailable',
        'evaluation_deadlines':'two primary solves share instance deadline; observation has independent same deadline'}
