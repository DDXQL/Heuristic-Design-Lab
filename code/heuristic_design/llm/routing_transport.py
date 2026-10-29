"""Reuse established bounded wire transport; one attempt per logical request.

The coordinator reserves all attempts before dispatch and persists the first
complete response. Crash-ambiguous reservations are never automatically resent.
"""
import os
import time
from .legacy import ClientConfig, JsonCandidateTransport


def preflight(c, allow_api):
    if c['api_mode']!='real':return
    if not allow_api or c['real_requests_authorized'] is not True:
        raise PermissionError('real search requires config authorization AND --allow-api; no request sent')
    name=c['provider']['api_key_env']
    if not os.environ.get(name):raise ValueError('credential environment variable absent: '+name)


def generate(task,prompt,c,members):
    cap=c['api_attempt_cap']
    client=ClientConfig({'config':{**c,'per_candidate_attempt_cap':1},
                         'budgets':{'logical_generation':cap}})
    transport=JsonCandidateTransport(client)
    sent=[False]
    send_time=[None]
    def on_sent():
        sent[0]=True
        send_time[0]=time.time()
    try:
        transport.preflight(prompt)
        value=transport.dispatch(task['request_key'],prompt,kind='U',on_sent=on_sent)
        return {**value,'sent':sent[0],'wire_send_confirmed_at_unix':send_time[0]}
    except Exception as exc:
        return {'text':None,'sent':sent[0],'error':transport.redact(str(exc))[:500],
                'error_type':type(exc).__name__,'wire_send_confirmed_at_unix':send_time[0],
                'usage':getattr(exc,'usage',None),
                'metadata':transport.redact_metadata(getattr(exc,'metadata',{}))}
