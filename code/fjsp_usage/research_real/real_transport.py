"""Single-send bounded JSON-candidate wire protocol, no SDK or HTTP retries.

Wire request: model/prompt/kind/request_id/max_output_tokens/temperature.
Wire response: text, optional {input_tokens,output_tokens} usage, optional
finish_reason ('stop' accepted, any explicit truncation refused).
This is an explicit generic gateway protocol, not a claimed provider SDK.
"""

import http.client
import json
import multiprocessing as mp
import os
import hashlib
import re
import ssl
import time
from urllib.parse import urlsplit

from fjsp_usage.research.protocol import digest
from .budget import validate_usage, BudgetStop


class TransportError(RuntimeError):
    pass


def response_audit(response, secret=''):
    """Allowlisted gateway identifiers, never Authorization/cookies/whole headers."""
    result={'http_status':response.status}
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
        error=json.loads(raw).get('error',{})
        if isinstance(error,dict):
            for field in ('type','code','message'):
                value=error.get(field)
                if isinstance(value,(str,int)):
                    value=str(value).replace(secret,'[REDACTED]') if secret else str(value)
                    value=re.sub(r'(?i)(bearer\s+\S+|sk-[A-Za-z0-9_-]+)', '[REDACTED]', value)
                    result['error_'+field]=value[:300]
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
    size, text_size, event = 0, 0, []
    try:
        if response.getheader('Content-Type', '').split(';')[0].strip() != 'text/event-stream':
            raise TransportError('stream response must use text/event-stream')
        while True:
            line = response.readline(65537)
            size += len(line)
            if not line or len(line) > 65536 or size > 8388608:
                raise TransportError('stream ended without DONE or exceeded byte limit')
            line = line.decode('utf-8').rstrip('\r\n')
            if line:
                if line.startswith('data:'):
                    event.append(line[5:].lstrip(' '))
                elif not line.startswith((':', 'event:', 'id:', 'retry:')):
                    raise TransportError('invalid SSE field')
                continue
            if not event:
                continue
            content, event = '\n'.join(event), []
            if content == '[DONE]':
                if finish != 'stop' or raw_usage is None:
                    raise TransportError('stream requires stop and final usage before DONE')
                return decode_chat({**audit, 'usage':raw_usage, 'choices':[
                    {'message':{'content':''.join(text)}, 'finish_reason':finish}]}, provider)
            chunk = json.loads(content)
            if not isinstance(chunk, dict) or chunk.get('error'):
                raise TransportError('invalid/error stream chunk')
            for field in ('id', 'model'):
                value = chunk.get(field)
                if not isinstance(value, str) or not value or len(value) > 256:
                    raise TransportError('missing stream identity/model')
                if field in audit and audit[field] != value:
                    raise TransportError('stream identity/model changed')
                audit[field] = value
            if provider.expected_response_model and audit['model'] != provider.expected_response_model:
                raise TransportError('stream model differs from locked model')
            choices = chunk.get('choices')
            if not isinstance(choices, list) or len(choices) > 1:
                raise TransportError('stream requires one choice')
            if chunk.get('usage') is not None:
                if raw_usage is not None or finish is None:
                    raise TransportError('duplicate or premature stream usage')
                raw_usage = chunk['usage']
                # Validate details immediately, so later interruption preserves known usage.
                decode_chat({**audit, 'usage':raw_usage, 'choices':[
                    {'message':{'content':''.join(text)}, 'finish_reason':finish}]}, provider)
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
                if reason != 'stop':
                    raise TransportError('stream completion truncated or refused')
    except BaseException as exc:
        error = exc if isinstance(exc, TransportError) else TransportError('malformed or interrupted SSE stream')
        error.metadata = audit
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
    metadata = {}
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
        connection.request('POST', parts.path or '/', body=json.dumps(payload).encode(), headers=headers)
        pipe.send({'kind': 'sent'})
        response = connection.getresponse()
        metadata = response_audit(response,secret)
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
                   'metadata': {**metadata,**(getattr(exc, 'metadata', {}) or {})}})
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
        self.identity = digest({'provider': config.payload()['provider'], 'mode': config.mode})

    def redact(self, text):
        return text.replace(self.secret, '[REDACTED]') if self.secret else text

    def redact_metadata(self, metadata):
        return {k: self.redact(v) if isinstance(v, str) else v for k, v in metadata.items()}

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
