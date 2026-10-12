"""Leaf API configuration and read-only token status; never generates text.

The received New API connection is an API credential, not a dashboard login.
Only allowlisted metadata is returned; redirects and automatic retries are off.
"""

from dataclasses import replace
import http.client
import json
import math
import multiprocessing as mp
from pathlib import Path
import re
from urllib.parse import urlsplit

from .config import ProviderConfig, ExperimentConfig, loopback_url

BASE_URL = 'https://leafapi.cc'
MODEL = 'gpt-5.6-sol'
KEY_ENV = 'LEAFAPI_API_KEY'


def provider():
    return ProviderConfig(BASE_URL+'/v1/chat/completions', MODEL, protocol='openai-chat-v1',
        api_key_env=KEY_ENV, connect_timeout=10, read_timeout=120, total_timeout=180,
        max_output_tokens=4096, temperature=None, reasoning_effort=None, expected_response_model=MODEL)


def pilot_config():
    c = ExperimentConfig(provider=provider(), mode='real', real_requests_authorized=False,
        attempts_per_generation=10, generations=1, seeds=(101,), instance_timeout=15,
        total_request_cap=150)
    return replace(c, phase_request_caps=c.default_phase_caps())


def load_local_key(path):
    path = Path(path)
    if not path.exists():
        raise ValueError('请先填写本机 .env.leafapi.local')
    lines = [s.strip() for s in path.read_text().splitlines() if s.strip() and not s.lstrip().startswith('#')]
    if len(lines) != 1 or not lines[0].startswith(KEY_ENV+'='):
        raise ValueError('密钥文件只接受一行 LEAFAPI_API_KEY=完整密钥，可附加注释')
    value = lines[0].split('=',1)[1].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    if not re.fullmatch(r'sk-[A-Za-z0-9_-]{12,}', value):
        raise ValueError('本机密钥未填写完整，不能只填 sk-、遮挡值或占位文本')
    return value


def _metadata_worker(pipe, base_url, key, quota_path, include_models=True):
    parts = urlsplit(base_url)
    connection_type = http.client.HTTPSConnection if parts.scheme == 'https' else http.client.HTTPConnection
    try:
        result = {}
        # Keys travel only in a header to the configured origin, never in a URL.
        paths = [('quota', quota_path)]
        if include_models:
            paths.append(('models', '/v1/models'))
        for label, path in paths:
            connection = connection_type(parts.hostname, parts.port, timeout=5)
            try:
                connection.request('GET', path, headers={'Authorization':'Bearer '+key, 'Accept':'application/json'})
                response = connection.getresponse()
                if response.status != 200:
                    result[label] = {'available':False, 'http_status':response.status}
                    continue
                raw = response.read(131073)
                if len(raw) > 131072:
                    result[label] = {'available':False, 'error':'metadata response too large'}
                    continue
                try:
                    body = json.loads(raw)
                    if label == 'quota':
                        result[label] = normalize_quota(body)
                    else:
                        data = body['data']
                        if not isinstance(data, list) or any(not isinstance(r,dict) or not isinstance(r.get('id'),str) for r in data):
                            raise ValueError('invalid model list')
                        result[label] = {'available':True, 'model_ids':[r['id'].replace(key,'[REDACTED]') for r in data]}
                except (ValueError, KeyError, TypeError):
                    result[label] = {'available':False, 'error':'unrecognized metadata response'}
            finally:
                connection.close()
        pipe.send(result)
    except Exception:
        # Never return an exception containing server text, headers or secrets.
        pipe.send({'error':'metadata connection failed; no retry'})
    finally:
        pipe.close()


def normalize_quota(body):
    if not isinstance(body, dict) or not (body.get('code') is True or body.get('success') is True):
        raise ValueError('quota query did not succeed')
    data = body['data']
    result = {'available':True, 'unit':'raw platform quota; NOT automatically CNY'}
    for name in ('total_granted','total_used','total_available'):
        value = data[name]
        if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
            raise ValueError('invalid quota value')
        result[name] = value
    for name in ('unlimited_quota','model_limits_enabled'):
        if type(data.get(name)) is not bool:
            raise ValueError('invalid quota flag')
        result[name] = data[name]
    if type(data.get('expires_at')) is not int or data['expires_at'] < 0:
        raise ValueError('invalid expiration')
    result['expires_at'] = data['expires_at']
    limits = data.get('model_limits',{})
    if not isinstance(limits,dict) or any(not isinstance(k,str) or type(v) is not bool for k,v in limits.items()):
        raise ValueError('invalid model limits')
    result['allowed_by_explicit_token_limit'] = limits.get(MODEL) if result['model_limits_enabled'] else None
    return result


def query_status(key, *, base_url=BASE_URL, timeout=15, quota_path='/api/usage/token', include_models=True):
    parts = urlsplit(base_url)
    if (parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ('','/')
            or (parts.scheme == 'http' and not loopback_url(base_url))):
        raise ValueError('metadata origin must be HTTPS (or loopback test), without credentials/path/query')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('finite positive metadata deadline required')
    if quota_path not in ('/api/usage/token','/api/usage/token/'):
        raise ValueError('only the two explicit same-origin token usage paths are allowed')
    if type(include_models) is not bool:
        raise ValueError('include_models must be bool')
    context = mp.get_context('spawn')
    receive, send = context.Pipe(duplex=False)
    worker = context.Process(target=_metadata_worker, args=(send,base_url,key,quota_path,include_models))
    worker.start(); send.close()
    try:
        if not receive.poll(timeout):
            result = {'error':'metadata deadline exceeded; no retry'}
        else:
            try:
                result = receive.recv()
            except EOFError:
                result = {'error':'metadata worker exited; no retry'}
    finally:
        receive.close(); worker.join(timeout=.05)
        if worker.is_alive():
            worker.terminate(); worker.join(timeout=.5)
        if worker.is_alive():
            worker.kill(); worker.join(timeout=.5)
    models = result.get('models',{})
    return {'base_url':base_url, 'requested_model':MODEL, 'inference_requests':0,
            'requested_model_listed':MODEL in models['model_ids'] if models.get('available') else None,
            **result}
