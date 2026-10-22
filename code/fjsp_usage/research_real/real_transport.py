"""Single-send bounded JSON-candidate wire protocol, no SDK or HTTP retries.

Wire request: model/prompt/kind/request_id/max_output_tokens/temperature.
Wire response: text, optional {input_tokens,output_tokens} usage, optional
finish_reason ('stop' accepted, any explicit truncation refused).
This is an explicit generic gateway protocol, not a claimed provider SDK.
"""

import http.client
import errno
import json
import multiprocessing as mp
import os
import hashlib
import re
import ssl
import socket
import time
from urllib.parse import urlsplit

from fjsp_usage.research.protocol import digest
from .budget import validate_usage, BudgetStop


class TransportError(RuntimeError):
    pass


WIRE_VERSION = 'bounded-sse-evidence-t1-v1'
OBSERVATION_VERSION = 'paired-stream-observation-d2-v1'
TEMPORARY_CODES = frozenset(('service_unavailable', 'temporarily_unavailable',
                            'server_overloaded', 'rate_limit_exceeded'))
PERMANENT_CODES = frozenset(('insufficient_quota', 'invalid_api_key', 'authentication_error',
                            'model_not_found', 'invalid_request_error', 'invalid_parameter',
                            'permission_denied', 'insufficient_balance'))


def redact_diagnostic(value, secret=''):
    """Recursive defense in depth; structural SSE evidence stores no free text."""
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, '[REDACTED]')
        return re.sub(r'(?i)(bearer\s+\S+|sk-[A-Za-z0-9_-]+)', '[REDACTED]', value)
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if str(k).lower() in
                    ('authorization', 'cookie', 'set-cookie', 'api_key', 'access_token', 'password')
                    else redact_diagnostic(v, secret)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_diagnostic(v, secret) for v in value]
    return value


def field_evidence(value):
    result = {'type': type(value).__name__}
    if isinstance(value, (dict, list)):
        result['count'] = len(value)
    if isinstance(value, str):
        raw = value.encode('utf-8', errors='replace')
        result.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return result


def upstream_error_evidence(data):
    """Keep only recognized machine codes/markers; never server message bodies."""
    error = data.get('error', data) if isinstance(data, dict) else data
    result = {'upstream_error_shape': field_evidence(error)}
    if not isinstance(error, dict):
        return result
    for name in ('code', 'type'):
        value = error.get(name)
        result['error_' + name + '_evidence'] = field_evidence(value)
        if isinstance(value, str) and value in TEMPORARY_CODES | PERMANENT_CODES:
            result['error_' + name] = value
    # This value is an allowlisted marker, not a quote of the provider's message.
    message = error.get('message')
    result['error_message_evidence'] = field_evidence(message)
    if isinstance(message, str):
        markers = ('insufficient balance', 'insufficient funds', 'insufficient quota',
                   'quota exhausted', 'quota exceeded', 'invalid api key', 'unauthorized',
                   'authentication', 'model not found', 'invalid parameter',
                   '余额不足', '额度不足', '欠费', 'service temporarily unavailable')
        result['error_message'] = ' '.join(x for x in markers if x in message.lower())
    status = error.get('status', error.get('http_status'))
    if type(status) is int and status in (400, 401, 402, 403, 404, 405, 422, 429, 502, 503, 504):
        result['upstream_http_status'] = status
    codes = {result.get('error_code'), result.get('error_type')}
    if (codes & PERMANENT_CODES or status in (400, 401, 402, 403, 404, 405, 422)
            or result.get('error_message', '').replace('service temporarily unavailable', '').strip()):
        result['failure_class'] = 'permanent'
    elif (codes & TEMPORARY_CODES or status in (429, 502, 503, 504)
          or result.get('error_message') == 'service temporarily unavailable'):
        result['failure_class'] = 'temporary'
    else:
        result['failure_class'] = 'unknown'
    return result


def frame_evidence(chunk, content):
    result = {**field_evidence(chunk), 'frame_sha256': hashlib.sha256(content.encode()).hexdigest()}
    if isinstance(chunk, dict):
        known = ('id', 'model', 'choices', 'usage', 'error', 'object', 'type', 'code', 'message')
        result['fields'] = {k: field_evidence(chunk[k]) for k in known if k in chunk}
        result['other_field_count'] = sum(k not in known for k in chunk)
        choices = chunk.get('choices')
        if isinstance(choices, list):
            result['choice_shapes'] = []
            for choice in choices[:2]:
                shape = field_evidence(choice)
                if isinstance(choice, dict):
                    shape['index'] = field_evidence(choice.get('index'))
                    shape['finish_reason'] = field_evidence(choice.get('finish_reason'))
                    delta = choice.get('delta')
                    shape['delta'] = field_evidence(delta)
                    if isinstance(delta, dict):
                        names = ('role', 'content', 'reasoning_content', 'refusal', 'tool_calls', 'function_call', 'audio')
                        shape['delta_fields'] = {k: field_evidence(delta[k]) for k in names if k in delta}
                result['choice_shapes'].append(shape)
    return result


def sse_lines(response, counters):
    """Bounded LF/CRLF/CR framing, including CR split across HTTP read chunks."""
    pending, after_cr = bytearray(), False
    read = getattr(response, 'read1', None) or response.readline
    while True:
        block = read(4096)
        if not block:
            error = TransportError('stream ended without DONE or exceeded byte limit')
            error.metadata = {'temporary_network_failure': True, 'network_error_type': 'stream_eof'}
            raise error
        counters['wire_bytes_seen'] += len(block)
        if counters['wire_bytes_seen'] > 8388608:
            raise TransportError('stream exceeds byte limit')
        for byte in block:
            if after_cr and byte == 10:
                after_cr = False
                continue
            after_cr = byte == 13
            if byte in (10, 13):
                yield bytes(pending)
                pending.clear()
            else:
                pending.append(byte)
                if len(pending) > 65536:
                    raise TransportError('stream line exceeds byte limit')


def network_failure_metadata(exc):
    """Structured evidence for opt-in retry journals; no transport retries."""
    current = exc
    for _ in range(6):
        if isinstance(current,(TimeoutError,ConnectionError,socket.gaierror,
                               ssl.SSLEOFError,http.client.RemoteDisconnected,http.client.IncompleteRead)) or (
                isinstance(current,OSError) and current.errno in (errno.ECONNRESET,errno.ECONNABORTED,
                    errno.ECONNREFUSED,errno.ETIMEDOUT,errno.ENETUNREACH,errno.EHOSTUNREACH,errno.ENETDOWN,errno.EPIPE)):
            return {'temporary_network_failure':True,'network_error_type':type(current).__name__}
        current = current.__cause__ or current.__context__
        if current is None:break
    return {}


def response_audit(response, secret=''):
    """Allowlisted gateway identifiers, never Authorization/cookies/whole headers."""
    result={'http_status':response.status}
    content_type = response.getheader('Content-Type')
    if isinstance(content_type, str):
        result['http_content_type'] = redact_diagnostic(content_type, secret)[:256]
    for header in ('x-oneapi-request-id','x-request-id','x-new-api-request-id','date'):
        value=response.getheader(header)
        if isinstance(value,str):
            value=value.replace(secret,'[REDACTED]') if secret else value
            result[header]=value[:256]
    result['gateway_request_id']=next((result[h] for h in
        ('x-oneapi-request-id','x-new-api-request-id','x-request-id') if h in result),None)
    return result


def error_audit(raw,secret=''):
    result={'error_body_sha256':hashlib.sha256(raw).hexdigest(),'error_body_bytes_sampled':len(raw)}
    try:
        result.update(upstream_error_evidence(json.loads(raw)))
    except (ValueError,AttributeError):pass
    return result


def decode_chat(data, provider):
    """Normalize totals; detail tokens are subsets, never added twice."""
    usage = None
    metadata = {}
    if not isinstance(data, dict):
        raise TransportError('invalid chat response schema')
    raw = data.get('usage')
    if raw is not None:
        if not isinstance(raw, dict):
            raise TransportError('invalid chat usage')
        usage = validate_usage({'input_tokens': raw.get('prompt_tokens'),
                                'output_tokens': raw.get('completion_tokens')})
        for field, name, total in (
                ('prompt_tokens_details', 'cached_tokens', usage['input_tokens']),
                ('prompt_tokens_details', 'cache_write_tokens', usage['input_tokens']),
                ('completion_tokens_details', 'reasoning_tokens', usage['output_tokens'])):
            details = raw.get(field)
            if details is not None:
                if not isinstance(details, dict):
                    raise TransportError('invalid token details')
                value = details.get(name)
                if value is not None:
                    if type(value) is not int or not 0 <= value <= total:
                        raise TransportError('invalid token detail count')
                    metadata[name] = value
        if provider.protocol == 'deepseek-chat-v1':
            hit, miss = raw.get('prompt_cache_hit_tokens'), raw.get('prompt_cache_miss_tokens')
            if hit is not None or miss is not None:
                if (type(hit) is not int or type(miss) is not int or min(hit, miss) < 0
                        or hit + miss != usage['input_tokens']):
                    raise TransportError('invalid DeepSeek cache usage')
                if 'cached_tokens' in metadata and metadata['cached_tokens'] != hit:
                    raise TransportError('inconsistent DeepSeek cache usage')
                metadata.update(cached_tokens=hit, prompt_cache_hit_tokens=hit,
                                prompt_cache_miss_tokens=miss)
    for field in ('id', 'model', 'system_fingerprint'):
        value = data.get(field)
        if value is not None:
            if not isinstance(value, str) or len(value) > 256:
                raise TransportError('invalid response audit field')
            metadata[field] = value
    try:
        choices = data['choices']
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError()
        choice = choices[0]
        if isinstance(choice.get('finish_reason'), str):
            metadata['finish_reason'] = choice['finish_reason'][:256]
        message = choice['message']
        text = message['content']
        metadata['content_type'] = type(text).__name__
        metadata['refusal_present'] = bool(message.get('refusal'))
        metadata['tool_calls_present'] = bool(message.get('tool_calls'))
        if not isinstance(text, str) or message.get('refusal') or message.get('tool_calls'):
            raise ValueError()
        complete = choice.get('finish_reason') == 'stop'
    except (KeyError, TypeError, ValueError):
        error = TransportError('invalid single text chat completion')
        error.usage = usage
        error.metadata = metadata
        raise error
    if not complete or (provider.expected_response_model is not None
                        and metadata.get('model') != provider.expected_response_model):
        error = TransportError('chat truncated or response model differs from locked model')
        error.usage = usage
        error.metadata = metadata
        raise error
    return {'text': text, 'usage': usage, 'finish_reason': 'stop', 'metadata': metadata}


def decode_stream(response, provider):
    """Bounded SSE assembly; incomplete streams never become candidates.

    Ignore reasoning deltas for code assembly, but retain their billed token
    count from the final usage frame. No reconnect or partial acceptance.
    """
    text, audit, raw_usage, finish = [], {}, None, None
    text_size, event, event_type, event_size = 0, [], '', 0
    counters = {'wire_bytes_seen': 0, 'event_index': 0}
    evidence, current_frame, first_line = {}, None, True
    observed = {'version': OBSERVATION_VERSION, 'stop_received': False, 'usage_received': False,
                'usage_validated': False, 'DONE_received': False, 'complete_text': False,
                'id_check': 'not_observed', 'model_check': 'not_observed',
                'model_matches_expected': None}

    def observation():
        return {**observed, 'data_events_seen': counters['event_index'],
                'wire_bytes_seen': counters['wire_bytes_seen'], 'text_bytes_seen': text_size,
                'scope': 'parsed_prefix_only_unless_complete'}
    try:
        if response.getheader('Content-Type', '').split(';')[0].strip().lower() != 'text/event-stream':
            raise TransportError('stream response must use text/event-stream')
        for raw_line in sse_lines(response, counters):
            line = raw_line.decode('utf-8-sig' if first_line else 'utf-8')
            first_line = False
            if line:
                if line.startswith(':'):
                    continue
                field, _, value = line.partition(':')
                if value.startswith(' '):
                    value = value[1:]
                if field == 'data':
                    event.append(value)
                    event_size += len(raw_line)
                    if event_size > 8388608:
                        raise TransportError('SSE event exceeds byte limit')
                elif field == 'event':
                    event_type = value
                # SSE id/retry and unknown fields do not alter JSON identities,
                # reconnect, or change local backoff. See WHATWG SSE framing.
                continue
            if not event:
                if event_type == 'error':
                    raise TransportError('error event without structured data')
                event_type = ''
                continue
            content, event, event_size = '\n'.join(event), [], 0
            counters['event_index'] += 1
            current_frame = frame_evidence(None, content)
            if content == '[DONE]':
                observed['DONE_received'] = True
                if event_type == 'error':
                    raise TransportError('error event cannot terminate successfully')
                if finish != 'stop' or raw_usage is None:
                    raise TransportError('stream requires stop and final usage before DONE')
                result = decode_chat({**audit, 'usage':raw_usage, 'choices':[
                    {'message':{'content':''.join(text)}, 'finish_reason':finish}]}, provider)
                observed['complete_text'] = True
                result['metadata']['stream_observation'] = observation()
                return result
            chunk = json.loads(content)
            current_frame = frame_evidence(chunk, content)
            if isinstance(chunk, dict) and isinstance(chunk.get('model'), str) and provider.expected_response_model:
                match = chunk['model'] == provider.expected_response_model
                observed['model_matches_expected'] = match if observed['model_matches_expected'] is not False else False
            if (not isinstance(chunk, dict) or 'error' in chunk or
                    chunk.get('type') == 'error' or event_type == 'error'):
                evidence.update(upstream_error_evidence(chunk))
                evidence.setdefault('failure_class', 'unknown' if isinstance(chunk, dict) else 'protocol_incompatible')
                raise TransportError('invalid/error stream chunk')
            event_type = ''
            for field in ('id', 'model'):
                value = chunk.get(field)
                if not isinstance(value, str) or not value or len(value) > 256:
                    observed[field + '_check'] = 'missing_or_invalid'
                    raise TransportError('missing stream identity/model')
                if field in audit and audit[field] != value:
                    observed[field + '_check'] = 'changed'
                    evidence['identity_change'] = {'field': field,
                        'previous': field_evidence(audit[field]), 'observed': field_evidence(value)}
                    raise TransportError('stream identity/model changed')
                audit[field] = value
                observed[field + '_check'] = 'observed_consistent'
            if provider.expected_response_model and audit['model'] != provider.expected_response_model:
                raise TransportError('stream model differs from locked model')
            choices = chunk.get('choices')
            if not isinstance(choices, list) or len(choices) > 1:
                raise TransportError('stream requires one choice')
            if chunk.get('usage') is not None:
                observed['usage_received'] = True
                if raw_usage is not None or finish is None:
                    raise TransportError('duplicate or premature stream usage')
                raw_usage = chunk['usage']
                # Validate details immediately, so later interruption preserves known usage.
                decode_chat({**audit, 'usage':raw_usage, 'choices':[
                    {'message':{'content':''.join(text)}, 'finish_reason':finish}]}, provider)
                observed['usage_validated'] = True
            if not choices:
                if chunk.get('usage') is None:
                    raise TransportError('empty choice without final usage')
                continue
            choice = choices[0]
            if not isinstance(choice, dict) or type(choice.get('index')) is not int or choice['index'] != 0 or finish is not None:
                raise TransportError('invalid or late stream choice')
            delta = choice.get('delta')
            if not isinstance(delta, dict) or any(delta.get(k) for k in ('refusal','tool_calls','function_call','audio')):
                raise TransportError('stream contains non-text output')
            if delta.get('role') not in (None, 'assistant'):
                raise TransportError('invalid stream role')
            value = delta.get('content')
            if value is not None:
                if not isinstance(value, str):
                    raise TransportError('invalid stream content')
                text_size += len(value.encode('utf-8'))
                if text_size > 32768:
                    raise TransportError('candidate text exceeds 32 KiB')
                text.append(value)
            reason = choice.get('finish_reason')
            if reason is not None:
                finish = reason
                observed['stop_received'] = reason == 'stop'
                if reason != 'stop':
                    raise TransportError('stream completion truncated or refused')
    except BaseException as exc:
        error = exc if isinstance(exc, TransportError) else TransportError('malformed or interrupted SSE stream')
        # Do not retain raw error frames, messages, arbitrary fields or identities.
        network = network_failure_metadata(exc)
        error.metadata = {**evidence, **(getattr(exc,'metadata',{}) or {}), **network,
            'transport_version': WIRE_VERSION, 'failure_stage': 'sse_decode',
            'stream_observation': observation(),
            'stream_evidence': {**counters, 'text_bytes_seen': text_size,
                'last_frame': current_frame,
                'identities': {k: field_evidence(v) for k, v in audit.items()}}}
        error.metadata.setdefault('failure_class', 'temporary' if
            error.metadata.get('temporary_network_failure') else 'protocol_incompatible')
        error.metadata['stream_protocol_anomaly'] = (not error.metadata.get('temporary_network_failure', False)
            and error.metadata['failure_class'] in ('protocol_incompatible', 'unknown'))

        error.usage = getattr(exc, 'usage', None)
        if error.usage is None and isinstance(raw_usage, dict):
            try:
                error.usage = validate_usage({'input_tokens':raw_usage.get('prompt_tokens'),
                                              'output_tokens':raw_usage.get('completion_tokens')})
            except (ValueError, TypeError):
                pass
        raise error


def _wire_worker(pipe, provider, payload, secret):
    connection = None
    usage = None
    metadata = {'failure_stage': 'connect'}
    try:
        parts = urlsplit(provider.endpoint)
        cls = http.client.HTTPSConnection if parts.scheme == 'https' else http.client.HTTPConnection
        kwargs = {'timeout': provider.connect_timeout}
        if parts.scheme == 'https':
            kwargs['context'] = ssl.create_default_context()
        connection = cls(parts.hostname, parts.port, **kwargs)
        connection.connect()
        connection.sock.settimeout(provider.read_timeout)
        headers = {'Content-Type': 'application/json'}
        if secret:
            headers['Authorization'] = 'Bearer ' + secret
        metadata['failure_stage'] = 'http_send'
        connection.request('POST', parts.path or '/', body=json.dumps(payload).encode(), headers=headers)
        pipe.send({'kind': 'sent'})
        metadata['failure_stage'] = 'http_receive'
        response = connection.getresponse()
        metadata = {**metadata, **response_audit(response,secret)}
        pipe.send({'kind':'audit','metadata':metadata})
        if response.status != 200:
            metadata.update(error_audit(response.read(4096),secret))
            raise TransportError(f'HTTP status {response.status}; response body omitted')
        if getattr(provider, 'stream_response', False):
            data = decode_stream(response, provider)
            metadata = {**metadata,**data['metadata']}
        else:
            body = response.read(524289)
            if len(body) > 524288:
                raise TransportError('response exceeds 512 KiB')
            data = json.loads(body)
        if provider.protocol in ('openai-chat-v1', 'deepseek-chat-v1') and not getattr(provider, 'stream_response', False):
            if isinstance(data, dict) and isinstance(data.get('usage'), dict):
                usage = validate_usage({'input_tokens': data['usage'].get('prompt_tokens'),
                                        'output_tokens': data['usage'].get('completion_tokens')})
            data = decode_chat(data, provider)
            metadata = {**metadata,**data['metadata']}
        if not isinstance(data, dict) or not isinstance(data.get('text'), str):
            raise TransportError('invalid response schema')
        usage = validate_usage(data.get('usage'))
        if data.get('finish_reason') not in (None, 'stop'):
            raise TransportError('response incomplete/truncated')
        if len(data['text'].encode()) > 32768:
            raise TransportError('candidate text exceeds 32 KiB')
        pipe.send({'kind': 'reply', 'text': data['text'], 'usage': usage, 'metadata': metadata})
    except BaseException as exc:
        # Do not echo endpoint, headers, server bodies or credentials.
        message = str(exc) if isinstance(exc, TransportError) else type(exc).__name__
        if secret:
            message = message.replace(secret, '[REDACTED]')
        pipe.send({'kind': 'error', 'error': message, 'usage': getattr(exc, 'usage', usage),
                   'metadata': {**metadata,**(getattr(exc, 'metadata', {}) or {}),**network_failure_metadata(exc)}})
    finally:
        if connection is not None:
            connection.close()
        pipe.close()


class JsonCandidateTransport:
    def __init__(self, config):
        self.config = config
        self.provider = config.provider
        config.check_dispatch()
        self.secret = os.environ.get(self.provider.api_key_env, '') if self.provider.api_key_env else ''
        if self.provider.api_key_env and not self.secret:
            raise ValueError('configured local credential environment variable is absent')
        self.identity = digest({'provider': config.payload()['provider'], 'mode': config.mode,
                                'transport_version': WIRE_VERSION, 'observation_version': OBSERVATION_VERSION})

    def redact(self, text):
        return text.replace(self.secret, '[REDACTED]') if self.secret else text

    def redact_metadata(self, metadata):
        return redact_diagnostic(metadata, self.secret)

    def preflight(self, prompt):
        if not isinstance(prompt, str) or len(prompt.encode()) > self.provider.max_prompt_bytes:
            raise BudgetStop('prompt exceeds the locked context byte limit; no truncation or dispatch')

    def dispatch(self, key, prompt, *, kind='U', on_sent=lambda: None):
        self.preflight(prompt)
        context = mp.get_context('spawn')
        receive, send = context.Pipe(duplex=False)
        payload = {'model': self.provider.model, 'prompt': prompt, 'kind': kind,
                   'request_id': key, 'max_output_tokens': self.provider.max_output_tokens,
                   'temperature': self.provider.temperature}
        if self.provider.protocol in ('openai-chat-v1', 'deepseek-chat-v1'):
            payload = {'model': self.provider.model, 'messages': [{'role': 'user', 'content': prompt}],
                       'max_completion_tokens': self.provider.max_output_tokens, 'stream': False, 'n': 1}
            if self.provider.temperature is not None:
                payload['temperature'] = self.provider.temperature
            if self.provider.reasoning_effort is not None:
                payload['reasoning_effort'] = self.provider.reasoning_effort
            if self.provider.protocol == 'deepseek-chat-v1':
                payload['max_tokens'] = payload.pop('max_completion_tokens')
                payload['thinking'] = {'type': self.provider.thinking}
            if self.provider.stream_response:
                payload['stream'] = True
                payload['stream_options'] = {'include_usage': True}
        worker = context.Process(target=_wire_worker, args=(send, self.provider, payload, self.secret))
        started = time.monotonic()
        worker.start()
        send.close()
        audit = {}
        try:
            while True:
                remaining = self.provider.total_timeout - (time.monotonic() - started)
                if remaining <= 0 or not receive.poll(remaining):
                    raise TransportError('total network deadline exceeded; no retry')
                try:
                    message = receive.recv()
                except EOFError as exc:
                    raise TransportError('network worker exited without a final reply') from exc
                if message['kind'] == 'sent':
                    on_sent()
                elif message['kind'] == 'audit':
                    audit.update(message['metadata'])
                elif message['kind'] == 'error':
                    error = TransportError(self.redact(message['error']))
                    error.usage = message.get('usage')
                    error.metadata = self.redact_metadata(message.get('metadata', {}))
                    raise error
                else:
                    return {'text': self.redact(message['text']), 'usage': message['usage'],
                            'metadata': self.redact_metadata(message.get('metadata', {}))}
        except BaseException as exc:
            exc.metadata={**audit,**(getattr(exc,'metadata',{}) or {})}
            raise
        finally:
            receive.close()
            worker.join(timeout=0.05)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=0.5)
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=0.5)
