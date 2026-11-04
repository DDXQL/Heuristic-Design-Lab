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


WIRE_VERSION = 'bounded-wire-reliability-v4'
OBSERVATION_VERSION = 'bounded-sse-prefix-observation-v2'
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
    if type(status) is int and status in (400, 401, 402, 403, 404, 405, 422, 429, 502, 503, 504, 524):
        result['upstream_http_status'] = status
    codes = {result.get('error_code'), result.get('error_type')}
    if (codes & PERMANENT_CODES or status in (400, 401, 402, 403, 404, 405, 422)
            or result.get('error_message', '').replace('service temporarily unavailable', '').strip()):
        result['failure_class'] = 'permanent'
    elif (codes & TEMPORARY_CODES or status in (429, 502, 503, 504, 524)
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


def sse_lines(response, counters, on_data=None):
    """Bounded LF/CRLF/CR framing, including CR split across HTTP read chunks."""
    pending, after_cr = bytearray(), False
    read = getattr(response, 'read1', None) or response.readline
    while True:
        block = read(4096)
        if not block:
            error = TransportError('stream ended without DONE or exceeded byte limit')
            error.metadata = {'temporary_network_failure': True, 'network_error_type': 'stream_eof'}
            raise error
        if on_data is not None:on_data(len(block))
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
    for header in ('x-oneapi-request-id','x-request-id','x-new-api-request-id','date',
                   'cf-ray','server','via','x-envoy-upstream-service-time'):
        value=response.getheader(header)
        if isinstance(value,str):
            result[header]=redact_diagnostic(value,secret)[:256]
    result['gateway_request_id']=next((result[h] for h in
        ('x-oneapi-request-id','x-new-api-request-id','x-request-id') if h in result),None)
    return result


def error_audit(raw,secret=''):
    result={'error_body_sha256':hashlib.sha256(raw).hexdigest(),'error_body_bytes_sampled':len(raw)}
    try:
        body=json.loads(raw)
        result.update(upstream_error_evidence(body))
        error=body.get('error',body) if isinstance(body,dict) else None
        if isinstance(error,dict):
            fields={k:error[k][:1500] if isinstance(error[k],str) else error[k]
                    for k in ('code','type','message','status')
                    if k in error and type(error[k]) in (str,int,float,bool,type(None))}
            result['diagnostic_error']=redact_diagnostic(fields,secret)
    except (ValueError,AttributeError):
        result['diagnostic_error_text']=redact_diagnostic(raw.decode('utf-8',errors='replace')[:500],secret)
    return result


def request_audit(payload,body):
    """Exact serialized-body evidence, never headers or prompt/secret contents."""
    messages=payload.get('messages',[])
    return {'serialized_body_bytes':len(body),'serialized_body_sha256':hashlib.sha256(body).hexdigest(),
            'body_fields':sorted(payload),'model':payload.get('model'),
            'max_completion_tokens':payload.get('max_completion_tokens'),'stream':payload.get('stream'),
            'n':payload.get('n'),'messages_count':len(messages),
            'messages':[{'role':m.get('role'),'content':field_evidence(m.get('content'))} for m in messages],
            'scope':'body passed to HTTP client; excludes authorization headers; not proof of server context or billing'}


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


def decode_stream(response, provider, on_data=None, secret='', on_progress=None):
    """Bounded SSE assembly; incomplete streams never become candidates.

    Ignore reasoning deltas for code assembly, but retain their billed token
    count from the final usage frame. No reconnect or partial acceptance.
    """
    text, audit, raw_usage, finish = [], {}, None, None
    text_size, event, event_type, event_size = 0, [], '', 0
    counters = {'wire_bytes_seen': 0, 'event_index': 0}
    evidence, current_frame, first_line = {}, None, True
    decode_started=time.monotonic()
    trace={'version':'bounded-sse-frame-trace-v1','first_events':[],'last_event':None}
    observed = {'version': OBSERVATION_VERSION, 'stop_received': False, 'usage_received': False,
                'usage_validated': False, 'DONE_received': False, 'complete_text': False,
                'id_check': 'not_observed', 'model_check': 'not_observed',
                'model_matches_expected': None}

    def observation():
        return {**observed, 'data_events_seen': counters['event_index'],
                'wire_bytes_seen': counters['wire_bytes_seen'], 'text_bytes_seen': text_size,
                'scope': 'parsed_prefix_only_unless_complete'}
    def snapshot():
        return {'stream_trace':{'version':trace['version'],'first_events':list(trace['first_events']),
                                'last_event':trace['last_event']},'stream_observation':observation()}
    def observe_frame(chunk, content):
        # No raw JSON, content, arbitrary keys or full identities. At most 5 summaries.
        summary={'event_index':counters['event_index'],
                 'since_decode_start_seconds':time.monotonic()-decode_started,
                 'shape':frame_evidence(chunk,content)}
        if isinstance(chunk,dict):
            value=chunk.get('id')
            summary['id_format_family']=next((prefix for prefix in ('chatcmpl-','chatcmpl_','resp_')
                                             if isinstance(value,str) and value.startswith(prefix)),'other')
            model=chunk.get('model')
            summary['model_matches_expected']=(model==provider.expected_response_model
                if isinstance(model,str) and provider.expected_response_model else None)
        if len(trace['first_events'])<4:trace['first_events'].append(summary)
        trace['last_event']=summary
        if on_progress is not None and (counters['event_index']<=4 or content=='[DONE]' or
                isinstance(chunk,dict) and (chunk.get('usage') is not None or 'error' in chunk)):
            on_progress(snapshot())
    try:
        if response.getheader('Content-Type', '').split(';')[0].strip().lower() != 'text/event-stream':
            raise TransportError('stream response must use text/event-stream')
        for raw_line in sse_lines(response, counters, on_data):
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
                observe_frame(None,content)
                observed['DONE_received'] = True
                if event_type == 'error':
                    raise TransportError('error event cannot terminate successfully')
                if finish != 'stop' or raw_usage is None:
                    raise TransportError('stream requires stop and final usage before DONE')
                result = decode_chat({**audit, 'usage':raw_usage, 'choices':[
                    {'message':{'content':''.join(text)}, 'finish_reason':finish}]}, provider)
                observed['complete_text'] = True
                result['metadata'].update(snapshot())
                return result
            chunk = json.loads(content)
            current_frame = frame_evidence(chunk, content)
            observe_frame(chunk,content)
            if isinstance(chunk, dict) and isinstance(chunk.get('model'), str) and provider.expected_response_model:
                match = chunk['model'] == provider.expected_response_model
                observed['model_matches_expected'] = match if observed['model_matches_expected'] is not False else False
            if (not isinstance(chunk, dict) or 'error' in chunk or
                    chunk.get('type') == 'error' or event_type == 'error'):
                evidence.update(error_audit(content.encode()[:4096], secret))
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
                    evidence['failure_subtype']='sse_id_changed' if field=='id' else 'sse_model_changed'
                    evidence['identity_change'] = {'field': field,
                        'previous': field_evidence(audit[field]), 'observed': field_evidence(value)}
                    raise TransportError('stream identity/model changed')
                audit[field] = value
                observed[field + '_check'] = 'observed_consistent'
            if provider.expected_response_model and audit['model'] != provider.expected_response_model:
                evidence['failure_subtype']='sse_model_mismatch'
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
                if on_progress is not None:on_progress(snapshot())
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
                if on_progress is not None:on_progress(snapshot())
    except BaseException as exc:
        error = exc if isinstance(exc, TransportError) else TransportError('malformed or interrupted SSE stream')
        # Retain bounded sanitized error fields and frame summaries, never raw frames/identities.
        network = network_failure_metadata(exc)
        error.metadata = {**evidence, **(getattr(exc,'metadata',{}) or {}), **network,
            'transport_version': WIRE_VERSION, 'failure_stage': 'sse_decode',
            **snapshot(),
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
    body=json.dumps(payload).encode()
    started=time.monotonic()
    metadata = {'failure_stage': 'connect','local_request':request_audit(payload,body),
                'send_status':'not_started','wire_timing':{'started_at_unix':time.time()},
                'connection':{'mode':'direct_https' if provider.endpoint.startswith('https:') else 'direct_loopback_http',
                              'application_proxy':False,'proxy_environment_used':False,'system_tun':'not_observed'}}
    def stamp(name):metadata['wire_timing'][name]=time.monotonic()-started
    def emit():pipe.send({'kind':'audit','metadata':redact_diagnostic(metadata,secret)})
    def first_data(count):
        if 'first_body_data_seconds' not in metadata['wire_timing']:
            stamp('first_body_data_seconds');metadata['first_body_chunk_bytes']=count;emit()
    def bounded_body(response,limit):
        chunks=[];size=0;reader=getattr(response,'read1',None) or response.read
        while size<=limit:
            block=reader(min(4096,limit+1-size))
            if not block:break
            first_data(len(block));chunks.append(block);size+=len(block)
        return b''.join(chunks)
    try:
        parts = urlsplit(provider.endpoint)
        metadata['connection'].update(host=parts.hostname,port=parts.port or (443 if parts.scheme=='https' else 80))
        emit()
        cls = http.client.HTTPSConnection if parts.scheme == 'https' else http.client.HTTPConnection
        kwargs = {'timeout': provider.connect_timeout}
        if parts.scheme == 'https':
            kwargs['context'] = ssl.create_default_context()
        connection = cls(parts.hostname, parts.port, **kwargs)
        connection.connect()
        stamp('connected_seconds')
        connection.sock.settimeout(provider.read_timeout)
        try:metadata['connection']['peer']=list(connection.sock.getpeername())[:2]
        except (AttributeError,OSError):pass
        headers = {'Content-Type': 'application/json'}
        if secret:
            headers['Authorization'] = 'Bearer ' + secret
        metadata['failure_stage'] = 'http_send'
        metadata['send_status']='unknown';emit()
        connection.request('POST', parts.path or '/', body=body, headers=headers)
        stamp('send_confirmed_seconds');metadata['send_status']='confirmed'
        pipe.send({'kind': 'sent'})
        metadata['failure_stage'] = 'http_receive'
        emit()  # preserve confirmed send even if response headers never arrive
        response = connection.getresponse()
        stamp('response_headers_seconds')
        metadata = {**metadata, **response_audit(response,secret)}
        emit()
        if response.status != 200:
            metadata.update(error_audit(bounded_body(response,4095),secret))
            metadata.setdefault('failure_class','temporary' if response.status in (429,502,503,504,524) else
                                'permanent' if response.status in (400,401,402,403,404,405,422) else 'unknown')
            raise TransportError(f'HTTP status {response.status}; response body omitted')
        if getattr(provider, 'stream_response', False):
            stamp('sse_decode_started_seconds')
            def progress(value):
                metadata.update(value);emit()
            data = decode_stream(response, provider, first_data, secret, progress)
            metadata = {**metadata,**data['metadata']}
        else:
            body = bounded_body(response,524288)
            if len(body) > 524288:
                raise TransportError('response exceeds 512 KiB')
            stamp('body_complete_seconds');metadata['failure_stage']='json_decode'
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
        stamp('finished_seconds')
        pipe.send({'kind': 'reply', 'text': data['text'], 'usage': usage, 'metadata': metadata})
    except BaseException as exc:
        stamp('finished_seconds')
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


def request_payload(provider,key,prompt,kind='U'):
    """One shared serializer input for wire dispatch and pre-send audit."""
    payload={'model':provider.model,'prompt':prompt,'kind':kind,'request_id':key,
             'max_output_tokens':provider.max_output_tokens,'temperature':provider.temperature}
    if provider.protocol in ('openai-chat-v1','deepseek-chat-v1'):
        payload={'model':provider.model,'messages':[{'role':'user','content':prompt}],
                 'max_completion_tokens':provider.max_output_tokens,'stream':False,'n':1}
        if provider.temperature is not None:payload['temperature']=provider.temperature
        if provider.reasoning_effort is not None:payload['reasoning_effort']=provider.reasoning_effort
        if provider.protocol=='deepseek-chat-v1':
            payload['max_tokens']=payload.pop('max_completion_tokens');payload['thinking']={'type':provider.thinking}
        if provider.stream_response:payload.update(stream=True,stream_options={'include_usage':True})
    return payload


def failure_category(error, metadata):
    """Observed layer only; unknown HTTP status is never guessed to be 200."""
    m=metadata or {};status=m.get('http_status');net=m.get('network_error_type')
    if m.get('failure_stage')=='connect':
        return 'dns_failure' if net=='gaierror' else 'connect_dns_tcp_tls_unresolved'
    if status is not None and status!=200:
        return 'http_524' if status==524 else 'http_gateway' if status>=500 else 'http_rejection'
    if m.get('deadline_kind') or net in ('TimeoutError','TotalDeadline'):
        return 'http200_read_or_total_timeout' if status==200 else 'timeout_http_status_unknown'
    if m.get('failure_subtype') in ('sse_id_changed','sse_model_changed','sse_model_mismatch'):
        return m['failure_subtype']
    if m.get('upstream_error_shape'):return 'sse_upstream_error'
    if m.get('temporary_network_failure'):return 'network_interruption'
    return 'response_acceptance_failure'


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
        payload=request_payload(self.provider,key,prompt,kind)
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
            exc.metadata={**audit,**(getattr(exc,'metadata',{}) or {}),
                          'dispatch_elapsed_seconds':time.monotonic()-started}
            if 'total network deadline exceeded' in str(exc):
                exc.metadata.update(deadline_kind='total', last_observed_stage=exc.metadata.get('failure_stage'),
                                    temporary_network_failure=True, network_error_type='TotalDeadline')
            exc.metadata['failure_category']=failure_category(str(exc),exc.metadata)
            exc.metadata=self.redact_metadata(exc.metadata)
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
