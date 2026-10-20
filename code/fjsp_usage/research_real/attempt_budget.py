"""Opt-in per-batch API attempts; no historical quota or account dependencies.

Single-writer journal, not a concurrent queue. Uses the existing wire transport
and WireRecorder; response selection never consults parsing or fitness.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from .budget import BudgetStop, validate_usage

VERSION = 'batch-api-attempts-v1'


def validate_policy(config):
    b = config.request_budget
    if (not isinstance(b,dict) or set(b) != {'version','logical_candidate_cap','api_attempt_cap','per_candidate_attempt_cap','retry_backoff_seconds'}
            or b['version'] != VERSION
            or any(type(b[k]) is not int or b[k] < 1 for k in
                   ('logical_candidate_cap','api_attempt_cap','per_candidate_attempt_cap'))
            or b['logical_candidate_cap'] != config.total_request_cap
            or not b['logical_candidate_cap'] <= b['api_attempt_cap'] <= b['logical_candidate_cap']*b['per_candidate_attempt_cap']
            or not isinstance(b['retry_backoff_seconds'],list)
            or len(b['retry_backoff_seconds']) != b['per_candidate_attempt_cap']-1
            or any(type(x) not in (int,float) or not 1 <= x <= 60 for x in b['retry_backoff_seconds'])
            or any(getattr(config,k,None) is not None for k in ('conditional_research','development_h_source',
                'development_acceptance','development_continuation_source','platform_quota_ceiling','platform_quota_reservation'))):
        raise ValueError('explicit independent batch attempt policy required')


def failure_policy(message, metadata=None, error_type=''):
    """Conservative allowlist. Explicit billing/auth/config errors take priority."""
    m = metadata or {}
    text = (' '.join(str(m.get(k,'')) for k in ('error_code','error_type','error_message'))+' '+message).lower()
    fatal = ('insufficient_quota','insufficient quota','quota exhausted','quota exceeded',
             'insufficient balance','insufficient funds','余额不足','额度不足','欠费',
             'invalid_api_key','authentication','unauthorized','invalid api key',
             'model_not_found','model not found','does not exist','invalid_request_error',
             'invalid_parameter','invalid parameter')
    status = m.get('http_status')
    if any(word in text for word in fatal) or status in (400,401,402,403,404,405,422):
        return False, 'permanent_auth_quota_model_or_parameter_error', True
    if status in (429,502,503,504):
        return True, 'temporary_http_'+str(status), False
    if m.get('temporary_network_failure') or error_type in (
            'TimeoutError','ConnectionError','ConnectionResetError','ConnectionAbortedError',
            'ConnectionRefusedError','RemoteDisconnected','IncompleteRead','gaierror','SSLEOFError'):
        return True, 'temporary_connection_or_timeout', False
    # The existing worker uses this exact bounded-deadline error.
    if message.startswith('total network deadline exceeded'):
        return True, 'temporary_total_deadline', False
    if (m.get('error_code') in ('service_unavailable','temporarily_unavailable','server_overloaded')
            or 'service temporarily unavailable' in text):
        return True, 'explicit_temporary_service_error', False
    return False, 'non_retryable_unclassified_error', False


class AttemptJournal:
    """20 logical jobs / 30 reserved attempts / 3 attempts per job, persisted.

    A reserved attempt is charged even after an uncertain process interruption.
    Revision checks detect observed stale writers, but are NOT atomic exclusion.
    """
    def __init__(self,path,*,config,context,phase,transport,clock=time.time,sleep=time.sleep):
        validate_policy(config)
        self.path,self.config,self.transport = Path(path),config,transport
        self._config_key = digest(config.payload())
        self.phase,self.clock,self.sleep = phase,clock,sleep
        self.policy = json.loads(json.dumps(config.request_budget))
        self.identity = digest({'version':VERSION,'config':config.payload(),'context':context,
                                'transport':transport.identity,'phase':phase,'journal_path':str(self.path.resolve())})
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.data = {'identity':self.identity,'version':VERSION,'policy':self.policy,'revision':0,
                     'requests':{},'api_attempts':{},'halt_reason':None}
        self._disk = None
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            if self.data['identity'] != self.identity or self.data['policy'] != self.policy or self.data['version'] != VERSION:
                raise ValueError('attempt journal protocol, batch or transport identity changed')
            self._disk = digest(self.data)
        self.validate_counts()

    def validate_counts(self):
        requests,attempts = self.data['requests'],self.data['api_attempts']
        keys = [k for r in requests.values() for k in r['attempt_ids']]
        if (len(requests)>self.policy['logical_candidate_cap'] or len(attempts)>self.policy['api_attempt_cap']
                or len(keys)!=len(set(keys)) or set(keys)!=set(attempts)):
            raise ValueError('corrupt attempt counts or orphan records; no automatic reset')
        for key,r in requests.items():
            if len(r['attempt_ids'])>self.policy['per_candidate_attempt_cap']:
                raise ValueError('per-candidate attempt cap exceeded in saved journal')
            for n,aid in enumerate(r['attempt_ids'],1):
                if aid != self.phase+'/'+key+f'/attempt/{n:02d}' or attempts[aid]['number']!=n:
                    raise ValueError('saved API attempt identity differs')

    @property
    def calls(self):
        return len(self.data['requests'])

    @property
    def attempt_count(self):
        return len(self.data['api_attempts'])

    def save(self):
        if digest(self.config.payload()) != self._config_key:
            raise ValueError('batch configuration changed during execution')
        self.validate_counts()
        current = digest(json.loads(self.path.read_text())) if self.path.exists() else None
        if current != self._disk:
            raise BudgetStop('stale/concurrent journal writer detected; stop, do not merge or resend')
        self.data['revision'] += 1
        atomic_json(self.path,self.data)
        self._disk = digest(self.data)

    def ensure_capacity(self):
        if self.data['halt_reason']:
            raise BudgetStop(self.data['halt_reason'])
        if self.attempt_count >= self.policy['api_attempt_cap']:
            raise BudgetStop('batch API attempt cap exhausted')

    def summary(self):
        attempts = list(self.data['api_attempts'].values())
        return {'budget_policy':VERSION,'logical_candidate_cap':self.policy['logical_candidate_cap'],
                'logical_candidates':self.calls,'api_attempt_cap':self.policy['api_attempt_cap'],
                'logical_candidate_cap_reached':self.calls >= self.policy['logical_candidate_cap'],
                'api_attempt_cap_exhausted':len(attempts) >= self.policy['api_attempt_cap'],
                'api_attempts_consumed':len(attempts),'per_candidate_attempt_cap':self.policy['per_candidate_attempt_cap'],
                'confirmed_sends':sum(a.get('send_confirmed',False) for a in attempts),
                'attempt_statuses':dict(Counter(a['status'] for a in attempts)),
                'logical_statuses':dict(Counter(r['status'] for r in self.data['requests'].values())),
                'known_input_tokens':sum(a['usage']['input_tokens'] for a in attempts if a.get('usage') is not None),
                'known_output_tokens':sum(a['usage']['output_tokens'] for a in attempts if a.get('usage') is not None),
                'unknown_usage_attempts':sum(a.get('usage') is None for a in attempts),
                'actual_cost':None,'actual_cost_status':'unknown; no account, tariff or invoice queries',
                'global_history_gate':False,'cross_worktree_lock_gate':False,'stop_reason':self.data['halt_reason'],
                'count_basis':'reserved attempts, conservatively includes uncertain pre-dispatch interruptions'}

    def _accept(self,record,attempt,reply):
        if not isinstance(reply,dict) or not isinstance(reply.get('text'),str):
            raise ValueError('complete normalized response required')
        usage = validate_usage(reply.get('usage'))
        metadata = reply.get('metadata',{}) or {}
        attempt.update(status='completed',usage=usage,response_id=attempt['id']+'/response',reply=reply)
        record.update(status='completed',text=reply['text'],usage=usage,response_metadata=metadata,
                      accepted_attempt_id=attempt['id'],response_id=attempt['response_id'])

    def _recover(self,record):
        for key in record['attempt_ids']:
            a = self.data['api_attempts'][key]
            if a['status'] == 'completed':
                self._accept(record,a,a['reply']);self.save();return
            if a['status'] != 'pending':
                continue
            wire = self.transport.directory/(hashlib.sha256(key.encode()).hexdigest()+'.json')
            if wire.exists():
                raw = json.loads(wire.read_text())
                if raw['global_key'] != key or raw['prompt_key'] != record['prompt_key']:
                    raise ValueError('wire response identity/prompt differs')
                a['send_confirmed'] = raw.get('send_confirmed',False)
                if raw['status'] == 'wire_completed_before_settlement':
                    self._accept(record,a,raw['reply']);self.save();return
                if raw['status'] == 'wire_failed':
                    retry,reason,halt = failure_policy(raw.get('error',''),raw.get('metadata'),raw.get('error_type',''))
                    a.update(status='failed',error=raw.get('error'),error_type=raw.get('error_type'),
                             metadata=raw.get('metadata',{}),usage=validate_usage(raw.get('usage')),
                             retryable=retry,retry_reason=reason)
                    if halt:self.data['halt_reason'] = reason
                else:
                    a.update(status='interrupted_unknown',retryable=True,retry_reason='uncertain_dispatch_charged')
            else:
                a.update(status='interrupted_unknown',retryable=True,retry_reason='uncertain_reservation_charged')
            a['elapsed_seconds'] = None
            a['observed_after_restart_at'] = self.clock()
            if len(record['attempt_ids']) < self.policy['per_candidate_attempt_cap']:
                a['retry_not_before'] = self.clock()+self.policy['retry_backoff_seconds'][len(record['attempt_ids'])-1]
            self.save()

    def request(self,key,prompt,*,kind='U'):
        prompt_key = digest({'prompt':prompt,'kind':kind})
        record = self.data['requests'].get(key)
        if record:
            if record['prompt_key'] != prompt_key or record['kind'] != kind:
                raise ValueError('logical id reused with changed prompt/kind')
            if record['status'] in ('completed','failed'):
                return record
            self._recover(record)
            if record['status'] == 'completed':return record
        else:
            self.ensure_capacity()
            if self.calls >= self.policy['logical_candidate_cap']:
                raise BudgetStop('logical candidate cap exhausted')
            self.transport.preflight(prompt)  # no attempt is charged for a local preflight failure
            record = {'status':'pending','prompt':prompt,'prompt_key':prompt_key,'kind':kind,
                      'global_key':self.phase+'/'+key,'logical_id':key,'attempt_ids':[],'usage':None}
            self.data['requests'][key] = record
            self.save()
        while True:
            prior = self.data['api_attempts'][record['attempt_ids'][-1]] if record['attempt_ids'] else None
            if (prior and not prior['retryable']) or self.data['halt_reason']:
                break
            n = len(record['attempt_ids'])
            if n >= self.policy['per_candidate_attempt_cap'] or self.attempt_count >= self.policy['api_attempt_cap']:
                break
            if prior:
                delay = self.policy['retry_backoff_seconds'][n-1]
                until = prior.get('retry_not_before',prior.get('finished_at',prior['started_at'])+delay)
                self.sleep(max(0,until-self.clock()))
            self.transport.preflight(prompt)
            attempt_id = record['global_key']+f'/attempt/{n+1:02d}'
            a = {'id':attempt_id,'logical_id':key,'number':n+1,'status':'pending','send_confirmed':False,
                 'prompt_key':prompt_key,'started_at':self.clock(),'usage':None}
            self.data['api_attempts'][attempt_id] = a;record['attempt_ids'].append(attempt_id)
            self.save()  # Durable, conservatively charged before any network dispatch.
            def sent():
                a['send_confirmed'] = True;self.save()
            try:
                reply = self.transport.dispatch(attempt_id,prompt,kind=kind,on_sent=sent)
            except Exception as exc:
                metadata = getattr(exc,'metadata',{}) or {}
                message = self.transport.redact(str(exc))[:500]
                retry,reason,halt = failure_policy(message,metadata,type(exc).__name__)
                a.update(status='failed',error=message,error_type=type(exc).__name__,metadata=metadata,
                         usage=validate_usage(getattr(exc,'usage',None)),retryable=retry,retry_reason=reason)
                if halt:self.data['halt_reason'] = reason
            else:
                self._accept(record,a,reply)
            a['finished_at'] = self.clock();a['elapsed_seconds'] = max(0,a['finished_at']-a['started_at'])
            self.save()
            if record['status'] == 'completed':
                record['elapsed_seconds'] = self.logical_elapsed(record)
                self.save();return record
        reason = ('non_retryable_error' if prior and not prior.get('retryable',False) else
                  'batch_halted' if self.data['halt_reason'] else
                  'batch_api_attempt_cap' if self.attempt_count >= self.policy['api_attempt_cap'] else 'per_candidate_attempt_cap')
        record.update(status='failed',error='API attempts exhausted or non-retryable failure',failure_reason=reason,
                      error_type='GenerationTransportFailure',elapsed_seconds=self.logical_elapsed(record))
        self.save();return record

    def logical_elapsed(self,record):
        times = [self.data['api_attempts'][k].get('elapsed_seconds') for k in record['attempt_ids']]
        return sum(times) if all(x is not None for x in times) else None
