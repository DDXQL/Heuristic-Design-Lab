"""Local SSE delivery and failure cases; no credentials or paid requests."""
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import unittest

from fjsp_usage.research_real.config import ProviderConfig, ExperimentConfig
from fjsp_usage.research_real.real_transport import decode_stream, JsonCandidateTransport, TransportError
from fjsp_usage.research_real.budget import BudgetLedger, BudgetJournal


def chunks():
    base = {'id':'local-stream', 'model':'locked-model'}
    return [
        {**base, 'choices':[{'index':0,'delta':{'role':'assistant','content':'{rule}\n'},'finish_reason':None}]},
        {**base, 'choices':[{'index':0,'delta':{'reasoning_content':'not candidate code'},'finish_reason':None}]},
        {**base, 'choices':[{'index':0,'delta':{'content':'```python\ndef x():\n return 1\n```'},'finish_reason':None}]},
        {**base, 'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]},
        {**base, 'choices':[], 'usage':{'prompt_tokens':100,'completion_tokens':60,
            'prompt_tokens_details':{'cached_tokens':40},'completion_tokens_details':{'reasoning_tokens':20}}}]


def wire(rows, done=True):
    return b': keepalive\n\n' + b''.join(('data: '+json.dumps(r)+'\n\n').encode() for r in rows) + (b'data: [DONE]\n\n' if done else b'')


class Response(BytesIO):
    def getheader(self, key, default=None):
        return 'text/event-stream; charset=utf-8'


@contextmanager
def stream_server(rows=None):
    traffic=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            traffic.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for frame in wire(chunks() if rows is None else rows).splitlines(keepends=True):
                self.wfile.write(frame);self.wfile.flush()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}/chat',traffic
    finally: server.shutdown();server.server_close();thread.join()


class StreamTests(unittest.TestCase):
    def test_observed_output_above_request_hint_within_explicit_reservation(self):
        # Reproduce the paid observation with local HTTP only. Output details
        # remain subsets; a declared larger reservation covers provider totals.
        rows=chunks();rows[-1]['usage'].update(prompt_tokens=930,completion_tokens=9967)
        rows[-1]['usage']['completion_tokens_details']['reasoning_tokens']=9711
        with stream_server(rows) as (url,traffic),tempfile.TemporaryDirectory() as tmp:
            config=ExperimentConfig(replace(self.provider(),endpoint=url,
                max_output_tokens=8192,output_token_reservation=32768))
            ledger=BudgetLedger(Path(tmp)/'budget.json',config,'local-sse-overrun')
            journal=BudgetJournal(Path(tmp)/'journal.json',phase='H/search',cap=2,
                transport=JsonCandidateTransport(config),ledger=ledger)
            first=journal.request('one','prompt',kind='h')
            self.assertEqual(first['status'],'completed')
            self.assertEqual(first['usage']['output_tokens'],9967)
            self.assertEqual(first['response_metadata']['reasoning_tokens'],9711)
            self.assertFalse(ledger.summary()['halted'])
            self.assertEqual(journal.request('one','prompt',kind='h'),first)
            journal.request('two','another candidate',kind='h')
            self.assertEqual(len(traffic),2)
            self.assertEqual(traffic[0]['max_completion_tokens'],8192)
            self.assertEqual(ledger.summary()['known_output_tokens'],19934)

    def provider(self):
        return ProviderConfig('http://localhost/chat','alias',protocol='openai-chat-v1',
            stream_response=True,expected_response_model='locked-model',temperature=None)

    def test_complete_stream_and_real_local_http_wire(self):
        result=decode_stream(Response(wire(chunks())),self.provider())
        self.assertNotIn('not candidate code',result['text'])
        self.assertEqual(result['usage'],{'input_tokens':100,'output_tokens':60})
        self.assertEqual(result['metadata']['reasoning_tokens'],20)
        with stream_server() as (url, traffic):
            transport=JsonCandidateTransport(ExperimentConfig(replace(self.provider(),endpoint=url)))
            sent=[];reply=transport.dispatch('one','prompt',on_sent=lambda:sent.append(True))
            self.assertEqual(reply['text'],result['text']);self.assertEqual(sent,[True])
            self.assertEqual(len(traffic),1)
            self.assertTrue(traffic[0]['stream'])
            self.assertEqual(traffic[0]['stream_options'],{'include_usage':True})
            self.assertNotIn('temperature',traffic[0])

    def test_incomplete_stream_retains_known_usage_but_no_partial_candidate(self):
        with self.assertRaises(TransportError) as caught:
            decode_stream(Response(wire(chunks(),done=False)),self.provider())
        self.assertEqual(caught.exception.usage,{'input_tokens':100,'output_tokens':60})
        for rows in (chunks()[:-1], chunks()[:3]):
            with self.assertRaises(TransportError): decode_stream(Response(wire(rows)),self.provider())

    def test_identity_truncation_tools_schema_and_limits(self):
        for fault in ('model','identity','index','choices','content','tools','length','usage','late','bytes','json'):
            rows=chunks()
            if fault=='model': rows[1]['model']='other'
            if fault=='identity': rows[1]['id']='other'
            if fault=='index': rows[1]['choices'][0]['index']=1
            if fault=='choices': rows[1]['choices']*=2
            if fault=='content': rows[1]['choices'][0]['delta']['content']=5
            if fault=='tools': rows[1]['choices'][0]['delta']['tool_calls']=[{}]
            if fault=='length': rows[3]['choices'][0]['finish_reason']='length'
            if fault=='usage': rows[4]['usage']['completion_tokens_details']['reasoning_tokens']=61
            if fault=='late': rows.append(rows[0])
            if fault=='bytes': rows[2]['choices'][0]['delta']['content']='x'*32769
            body=wire(rows) if fault!='json' else b'data: {bad}\n\n'
            with self.subTest(fault=fault),self.assertRaises(TransportError):
                decode_stream(Response(body),self.provider())
        with self.assertRaises(ValueError): replace(self.provider(),protocol='json-candidate-v1')
        with self.assertRaises(ValueError): replace(self.provider(),stream_response=1)
