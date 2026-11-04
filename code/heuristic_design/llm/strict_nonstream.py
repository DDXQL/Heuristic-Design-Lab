"""Strict caller admission over the byte-identical admitted common wire. No retry."""
from pathlib import Path
from fjsp_usage.research_real.real_transport import JsonCandidateTransport,TransportError,WIRE_VERSION
from fjsp_usage.research_real.attempt_budget import AttemptJournal,failure_policy
from fjsp_usage.research_real.budget import validate_usage
from heuristic_design.core.storage import read,write,sha,digest

POLICY='strict-nonstream-model-stop-usage-v1'
STOP_POLICY={'version':'fjsp-eoh-api-stop-v1','explicit_refusal_or_response_protocol':'first failure stops',
 'temporary_or_unclassified_transport':'3 consecutive failed tasks pause',
 'candidate_parse_or_evaluation_invalid':'record scientific failure; no infrastructure stop',
 'unknown_inflight_or_evaluation':'retain evidence/lock; no replay',
 'automatic_retry':False,'automatic_restart':False,'failure_budget_refund':False}

def verify_binding(config,root):
    spec=config['transport_binding']
    if not isinstance(spec,dict) or set(spec)!={'evidence_file','sha256'}:raise ValueError('explicit shared-client binding required')
    path=Path(spec['evidence_file']);path=path if path.is_absolute() else Path(root)/path
    if sha(path)!=spec['sha256']:raise ValueError('client binding receipt changed')
    b=read(path)
    if b['version']!='fjsp-common-nonstream-binding-v1' or b['caller_acceptance_policy']!=POLICY or b['wire_version']!=WIRE_VERSION:
        raise ValueError('caller/wire policy differs from admitted preparation')
    if config['provider']!=b['provider'] or config['provider']['stream_response'] is not False:raise ValueError('bound nonstream provider differs')
    for name,value in {**b['local_runtime_sources'],**b['local_evidence_files']}.items():
        if sha(Path(root)/name)!=value:raise ValueError('bound runtime/evidence changed: '+name)
    return b

def admit(value,expected_model):
    """Common wire enforces full JSON; caller also requires normalized usage."""
    meta=(value.get('metadata') or {}) if isinstance(value,dict) else {}
    reason=None
    if meta.get('http_status')!=200:reason='HTTP200 required'
    elif meta.get('model')!=expected_model:reason='exact response model required'
    elif meta.get('finish_reason')!='stop' or meta.get('refusal_present') or meta.get('tool_calls_present'):reason='complete unrefused stop required'
    elif not isinstance(value.get('text'),str) or not value['text'].strip():reason='complete nonempty text required'
    else:
        try:
            if validate_usage(value.get('usage')) is None:reason='valid usage required'
        except ValueError:reason='valid usage required'
    if reason:
        error=TransportError('caller response rejected: '+reason)
        error.metadata={**meta,'caller_hard_stop':True,'caller_acceptance_policy':POLICY,'failure_stage':'caller_admission'}
        try:error.usage=validate_usage(value.get('usage'))
        except (ValueError,AttributeError):error.usage=None
        raise error
    return value

class StrictNonstreamTransport(JsonCandidateTransport):
    def __init__(self,config):
        if config.provider.stream_response is not False:raise ValueError('strict nonstream path only')
        super().__init__(config)
        self.identity=digest({'common_wire_identity':self.identity,'caller_acceptance_policy':POLICY})
    def dispatch(self,*args,**kwargs):
        try:value=super().dispatch(*args,**kwargs)
        except Exception as error:
            m=getattr(error,'metadata',{}) or {}
            temporary,_,permanent=failure_policy(str(error),m,type(error).__name__)
            if permanent or (m.get('http_status')==200 and not temporary):
                error.metadata={**m,'caller_hard_stop':True,'caller_acceptance_policy':POLICY}
            raise
        try:return admit(value,self.provider.expected_response_model)
        except TransportError:
            folder=getattr(self,'rejection_directory',None)
            if folder is not None:
                key=args[0] if args else kwargs['key']
                filename=__import__('hashlib').sha256(key.encode()).hexdigest()+'.json'
                write(Path(folder)/filename,{'caller_acceptance_policy':POLICY,'normalized_response':self.redact_metadata(value),
                                            'admitted':False,'global_request_id':key})
            raise

class StopAwareJournal(AttemptJournal):
    def request(self,*args,**kwargs):
        record=super().request(*args,**kwargs)
        if record['status']=='failed' and record['attempt_ids']:
            last=self.data['api_attempts'][record['attempt_ids'][-1]]
            if last['status']=='failed' and last.get('metadata',{}).get('caller_hard_stop') and not self.data['halt_reason']:
                self.data['halt_reason']='strict_nonstream_response_rejected';self.save()
        return record
