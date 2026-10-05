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
import ssl
import time
from urllib.parse import urlsplit

from fjsp_usage.research.protocol import digest
from .budget import validate_usage, BudgetStop


class TransportError(RuntimeError):
    pass


def _wire_worker(pipe, provider, payload, secret):
    connection = None
    usage = None
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
        if response.status != 200:
            raise TransportError(f'HTTP status {response.status}; response body omitted')
        body = response.read(524289)
        if len(body) > 524288:
            raise TransportError('response exceeds 512 KiB')
        data = json.loads(body)
        if not isinstance(data, dict) or not isinstance(data.get('text'), str):
            raise TransportError('invalid response schema')
        usage = validate_usage(data.get('usage'))
        if data.get('finish_reason') not in (None, 'stop'):
            raise TransportError('response incomplete/truncated')
        if len(data['text'].encode()) > 32768:
            raise TransportError('candidate text exceeds 32 KiB')
        pipe.send({'kind': 'reply', 'text': data['text'], 'usage': usage})
    except BaseException as exc:
        # Do not echo endpoint, headers, server bodies or credentials.
        message = str(exc) if isinstance(exc, TransportError) else type(exc).__name__
        if secret:
            message = message.replace(secret, '[REDACTED]')
        pipe.send({'kind': 'error', 'error': message, 'usage': usage})
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
        worker = context.Process(target=_wire_worker, args=(send, self.provider, payload, self.secret))
        started = time.monotonic()
        worker.start()
        send.close()
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
                elif message['kind'] == 'error':
                    error = TransportError(self.redact(message['error']))
                    error.usage = message.get('usage')
                    raise error
                else:
                    return {'text': self.redact(message['text']), 'usage': message['usage']}
        finally:
            receive.close()
            worker.join(timeout=0.05)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=0.5)
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=0.5)
