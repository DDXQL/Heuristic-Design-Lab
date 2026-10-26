"""Compatibility bridge to the established API journal and wire transport.

Legacy package paths remain stable; these classes do not inspect problem state.
"""
from dataclasses import asdict
import time
from fjsp_usage.research_real.config import ProviderConfig
from fjsp_usage.research_real.attempt_budget import AttemptJournal, CIRCUIT_VERSION
from fjsp_usage.research_real.real_transport import JsonCandidateTransport
from fjsp_usage.usage_v2.access import WireRecorder

class ClientConfig:
    """Minimal protocol adapter; avoids old four-arm SearchConfig's 10-slot rule.

ProviderConfig and AttemptJournal still perform their original validations.
No financial/account fields or account client are installed.
"""
    def __init__(self,p):
        c=p['config'];self.provider=ProviderConfig(**c['provider'])
        self.mode='real' if c['api_mode']=='real' else 'synthetic'
        self.real_requests_authorized=c['real_requests_authorized']
        self.total_request_cap=p['budgets']['logical_generation']
        self.request_budget={'version':CIRCUIT_VERSION,'logical_candidate_cap':self.total_request_cap,
            'api_attempt_cap':c['api_attempt_cap'],'per_candidate_attempt_cap':c['per_candidate_attempt_cap'],
            'retry_backoff_seconds':[2]*(c['per_candidate_attempt_cap']-1),'protocol_error_circuit_threshold':3}
    def payload(self):
        return {'provider':asdict(self.provider),'mode':self.mode,'real_requests_authorized':self.real_requests_authorized,
                'total_request_cap':self.total_request_cap,'request_budget':self.request_budget}
    def check_dispatch(self):
        if self.mode=='real' and not self.real_requests_authorized:raise PermissionError('configuration does not authorize real API')


class DeadlineTransport:
    def __init__(self,wire,deadline):
        self.wire=wire;self.deadline=deadline;self.directory=wire.directory;self.identity=wire.identity;self.redact=wire.redact
    def preflight(self,prompt):
        if time.time()>=self.deadline:raise ValueError('persistent deadline reached before API attempt')
        self.wire.preflight(prompt)
    def dispatch(self,*a,**k):return self.wire.dispatch(*a,**k)


