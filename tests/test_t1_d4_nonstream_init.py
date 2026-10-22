"""Full-prompt D4 offline acceptance; synthetic replies never become research U."""
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research.candidates import U_ARGS
from fjsp_usage.research_real.attempt_budget import AttemptJournal
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real import real_transport as rt
from tools import t1_d4_nonstream_init as d


TEXT = '{Synthetic offline interface fixture only}\n```python\ndef use_heuristics('+', '.join(U_ARGS)+'):\n    return (1, (0.5, 0.5, 0, 0, 0, 0, 0, 0, 0, 0))\n```'


def reply(text=TEXT):
    return {'id': 'UNIT-RESPONSE', 'model': 'gpt-6.1-sol',
        'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 5300, 'completion_tokens': 350,
                  'completion_tokens_details': {'reasoning_tokens': 120}}}


class Inner:
    identity = 'D4-MOCK-ONLY'; secret = ''; redact = staticmethod(str)
    def __init__(self, config, answer=None): self.config, self.answer, self.calls = config, answer, []
    def preflight(self, prompt):
        if len(prompt.encode()) != 21250: raise AssertionError('unexpected full prompt')
    def dispatch(self, key, prompt, *, kind='U', on_sent):
        self.calls.append(key); on_sent()
        if isinstance(self.answer, BaseException): raise self.answer
        try: parsed = rt.decode_chat(self.answer if self.answer is not None else reply(), self.config.provider)
        except Exception as exc:
            exc.metadata = {'http_status': 200, 'failure_stage': 'http_receive', **getattr(exc,'metadata',{})}; raise
        parsed['metadata'].update(http_status=200, http_content_type='application/json', gateway_request_id='UNIT-GATEWAY')
        return parsed


class D4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'t1-d4-mock'; d.prepare(self.path)
        _, self.config = d.check(self.path)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        native = Path.open
        def no_history(path, *args, **kwargs):
            if path.resolve().is_relative_to(d.ROOT/'runs'):
                raise AssertionError('NO HISTORICAL ACCESS AFTER PREPARE')
            return native(path, *args, **kwargs)
        self.stack.enter_context(patch.object(Path,'open',no_history))
        for name in ('socket.socket.connect', 'fjsp_usage.research_real.staged_evaluation.StagedDataset.load',
                     'fjsp_usage.research_real.runtime.evaluate', 'fjsp_usage.research.candidates.compile_candidate',
                     'fjsp_usage.research.evolution.Search.__init__', 'fjsp_usage.research_real.leafapi.load_local_key',
                     'fjsp_usage.research_real.leafapi.query_status', 'fjsp_usage.usage_v2.billing.query_invoices'):
            self.stack.enter_context(patch(name, side_effect=AssertionError('NO REAL API, DATA, KEY, EXECUTION OR ACCOUNT')))

    def session(self, answer=None):
        inner = Inner(self.config, answer)
        state = d.session(self.path,self.config,d.TimedRecorder(inner,self.path/'wire_responses'),provenance='mock-only')
        return state, inner

    def test_original_full_prompt_and_common_config_only_stream_delta(self):
        source=d.read(self.path/'Source_provenance.json');new=self.config.payload()['provider']
        self.assertEqual(source['historical_logical_id'],'B/init/000000')
        self.assertEqual(source['historical_attempt_id'],'r501/B/B/init/000000/attempt/01')
        self.assertEqual(d.sha(self.path/'Prompt.txt'),d.PROMPT_SHA)
        self.assertEqual(new,{**source['provider_original'],'stream_response':False})
        self.assertEqual([new[k] for k in ('connect_timeout','read_timeout','total_timeout')],[10,240,300])
        self.assertEqual(new['max_output_tokens'],8192)
        self.assertFalse((self.path/'Authorization.json').exists());self.assertFalse((self.path/'requests').exists())

    def test_complete_response_saves_usage_text_identity_without_execution(self):
        state,inner=self.session();row=state['outcome']
        self.assertEqual(state['phase'],'completed');self.assertTrue(row['diagnostic_pass'])
        self.assertTrue(row['complete_response']);self.assertTrue(row['output_legal'])
        self.assertEqual(row['usage'],{'input_tokens':5300,'output_tokens':350})
        self.assertEqual(row['metadata']['reasoning_tokens'],120)
        self.assertEqual((self.path/'response.txt').read_text(),TEXT)
        self.assertEqual(d.read(self.path/'Response.json')['text'],TEXT)
        self.assertIsNotNone(row['send_confirmation_at']);self.assertIsNotNone(row['finished_at'])
        self.assertIsNone(row['actual_cost']);self.assertEqual(len(inner.calls),1)
        d.report(self.path);self.assertFalse(d.read(self.path/'Diagnostic_result.json')['U_executed'])

    def test_illegal_output_formats_and_restricted_returns_do_not_retry(self):
        for text in ('no description or fenced program',TEXT.replace('(1, (','(1, {'),TEXT.replace(', 0, 0))',', 0))')):
            with self.subTest(text=text[:30]):
                parsed=rt.decode_chat(reply(text),self.config.provider)
                rec={'status':'completed','text':parsed['text'],'usage':parsed['usage'],
                     'response_metadata':parsed['metadata'],'response_id':'UNIT'}
                attempt={'id':'UNIT','status':'completed','reply':parsed,'usage':parsed['usage'],
                         'started_at':1,'send_confirmed':True}
                row=d.result_row(self.path,rec,attempt)
                self.assertTrue(row['complete_response']);self.assertFalse(row['output_legal'])
                self.assertFalse(row['diagnostic_pass'])
        state,inner=self.session(reply('UNIT illegal output'))
        self.assertFalse(state['outcome']['output_legal']);self.assertEqual(len(inner.calls),1)
        _,later=self.session();self.assertEqual(len(later.calls),0)

    def test_model_mismatch_preserves_known_usage_and_fails(self):
        body=reply();body['model']='wrong-model';state,inner=self.session(body)
        self.assertEqual(state['outcome']['failure_class'],'model_identity_mismatch')
        self.assertIsNone(state['outcome']['output_legal']);self.assertEqual(len(inner.calls),1)
        self.assertEqual(state['outcome']['usage']['output_tokens'],350)

    def test_truncated_response_never_accepted_as_U(self):
        body=reply();body['choices'][0]['finish_reason']='length';state,inner=self.session(body)
        self.assertEqual(state['outcome']['failure_class'],'truncated_or_refused')
        self.assertFalse(state['outcome']['complete_response']);self.assertEqual(len(inner.calls),1)

    def test_missing_stop_and_tool_calls_rejected_by_unchanged_public_decoder(self):
        body=reply();body['choices'][0].pop('finish_reason')
        with self.assertRaises(rt.TransportError):rt.decode_chat(body,self.config.provider)
        body=reply();body['choices'][0]['message']['tool_calls']=[{'UNIT':'unsupported'}]
        with self.assertRaises(rt.TransportError):rt.decode_chat(body,self.config.provider)

    def test_truncated_HTTP_JSON_rejected_without_reply_or_sensitive_body(self):
        messages=[]
        class Pipe:
            def send(self,v):messages.append(v)
            def close(self):pass
        class Connection:
            status=200
            def __init__(self,*a,**kw):self.sock=self
            def connect(self):pass
            def settimeout(self,_):pass
            def request(self,*a,**kw):pass
            def getresponse(self):return self
            def getheader(self,n,default=None):return 'application/json' if n=='Content-Type' else default
            def read(self,_):return b'{"id":"UNIT","choices":['
            def close(self):pass
        with patch.object(rt.http.client,'HTTPSConnection',Connection):
            rt._wire_worker(Pipe(),self.config.provider,{'UNIT':'mock payload'},'UNIT-NOT-REAL')
        self.assertEqual(messages[-1]['kind'],'error')
        self.assertEqual(messages[-1]['error'],'JSONDecodeError')
        self.assertFalse(any(x['kind']=='reply' for x in messages))
        self.assertEqual(messages[-1]['metadata']['http_status'],200)

    def test_missing_usage_or_id_is_not_complete_diagnostic(self):
        for field in ('usage','id'):
            with self.subTest(field=field):
                # Test the existing parser and the stricter diagnostic profile separately.
                body=reply();body.pop(field)
                parsed=rt.decode_chat(body,self.config.provider)
                rec={'status':'completed','text':parsed['text'],'usage':parsed['usage'],
                     'response_metadata':parsed['metadata'],'response_id':'UNIT'}
                attempt={'id':'UNIT','status':'completed','reply':parsed,'usage':parsed['usage'],
                         'started_at':1,'send_confirmed':True}
                row=d.result_row(self.path,rec,attempt)
                self.assertFalse(row['complete_response']);self.assertIsNone(row['output_legal'])

    def test_explicit_timeout_stops_with_one_attempt_and_unknown_cost(self):
        exc=rt.TransportError('total network deadline exceeded; no retry')
        state,inner=self.session(exc)
        self.assertEqual(state['outcome']['failure_class'],'timeout_or_network_failure')
        self.assertEqual(len(inner.calls),1);self.assertIsNone(state['outcome']['usage'])
        again,later=self.session();self.assertEqual(len(later.calls),0)
        self.assertIsNone(again['outcome']['actual_cost'])

    def test_unknown_sent_interruption_conservatively_consumed_never_resent(self):
        with self.assertRaises(KeyboardInterrupt):self.session(KeyboardInterrupt('UNIT sent result unknown'))
        state,later=self.session()
        self.assertEqual(len(later.calls),0);self.assertTrue(state['outcome']['delivery_unknown'])
        self.assertEqual(d.status(self.path)['api_attempts'],1)

    def test_reserved_but_unconfirmed_attempt_never_refunded(self):
        inner=Inner(self.config);transport=d.TimedRecorder(inner,self.path/'wire_responses')
        with patch.object(transport,'dispatch',side_effect=KeyboardInterrupt('UNIT before wire')):
            with self.assertRaises(KeyboardInterrupt):d.session(self.path,self.config,transport,provenance='mock-only')
        state,later=self.session()
        self.assertEqual(len(later.calls),0);self.assertTrue(state['outcome']['delivery_unknown'])
        self.assertFalse(state['outcome']['send_confirmed']);self.assertEqual(d.status(self.path)['api_attempts'],1)

    def test_complete_wire_before_acceptance_restored_without_new_request(self):
        with patch.object(AttemptJournal,'_accept',side_effect=KeyboardInterrupt('UNIT complete wire saved')):
            with self.assertRaises(KeyboardInterrupt):self.session()
        state,later=self.session()
        self.assertEqual(len(later.calls),0);self.assertTrue(state['outcome']['diagnostic_pass'])

    def test_finished_restart_no_resend_and_missing_status_can_be_rebuilt(self):
        self.session();(self.path/'status.json').unlink()
        state,later=self.session();self.assertEqual(len(later.calls),0)
        self.assertTrue((self.path/'status.json').exists());self.assertTrue(state['outcome']['diagnostic_pass'])

    def test_one_task_one_attempt_cap_prevents_second_task(self):
        self.session();inner=Inner(self.config);transport=d.TimedRecorder(inner,self.path/'wire_responses')
        j=AttemptJournal(self.path/'requests/attempts.json',config=self.config,phase='T1-D4',transport=transport,
            context={'protocol_sha256':d.sha(self.path/'Protocol.json'),'provenance':'mock-only'})
        with self.assertRaises(BudgetStop):j.request('EXTRA','UNIT')
        self.assertEqual(len(inner.calls),0)

    def test_missing_ledger_and_orphan_wire_never_reset_budget(self):
        self.session();(self.path/'requests/attempts.json').unlink()
        with self.assertRaisesRegex(ValueError,'missing D4 journal'):self.session()
        (self.path/'checkpoint.json').unlink()
        with self.assertRaisesRegex(ValueError,'orphan D4 wire'):self.session()

    def test_orphan_journal_without_checkpoint_refuses_restart(self):
        self.session();(self.path/'checkpoint.json').unlink()
        with self.assertRaisesRegex(ValueError,'orphan D4 journal'):self.session()

    def test_new_authorization_required_before_credentials(self):
        with self.assertRaises(BudgetStop):d.run_real(self.path,d.ENV_FILE)
        auth=d.approval(self.path,True);auth['stage']='T1-D3B'
        (self.path/'Authorization.json').write_text(json.dumps(auth))
        with self.assertRaises(BudgetStop):d.run_real(self.path,d.ENV_FILE)

    def test_wrong_credential_path_refused_without_read(self):
        (self.path/'Authorization.json').write_text(json.dumps(d.approval(self.path,True)))
        with self.assertRaises(ValueError):d.run_real(self.path,Path('/not/the/original/env'))

    def test_mock_cannot_be_relabelled_as_real(self):
        self.session();(self.path/'Authorization.json').write_text(json.dumps(d.approval(self.path,True)))
        c=replace(self.config,real_requests_authorized=True)
        with self.assertRaises(ValueError):d.session(self.path,c,d.TimedRecorder(Inner(c),self.path/'wire_responses'),provenance='real')

    def test_copy_and_symlink_escape_rejected(self):
        other=Path(self.temp.name)/'t1-d4-copy';shutil.copytree(self.path,other)
        with self.assertRaises(ValueError):d.check(other)
        (self.path/'requests').symlink_to(d.SOURCE,target_is_directory=True)
        with self.assertRaises(ValueError):d.check(self.path)

    def test_prompt_tamper_rejected_without_requests(self):
        (self.path/'Prompt.txt').write_text('UNIT changed')
        with self.assertRaises(ValueError):self.session()

    def test_real_payload_worker_and_public_nonstream_parser_with_fake_HTTP_only(self):
        messages=[];payloads=[];timeouts=[]
        class Pipe:
            def send(self,value):messages.append(value)
            def recv(self):return messages.pop(0)
            def poll(self,_):return bool(messages)
            def close(self):pass
        class Response:
            status=200
            def getheader(self,name,default=None):return {'Content-Type':'application/json','x-request-id':'UNIT-GATEWAY'}.get(name,default)
            def read(self,_):return json.dumps(reply()).encode()
        class Connection:
            def __init__(self,*args,**kwargs):timeouts.append(kwargs['timeout']);self.sock=self
            def connect(self):pass
            def settimeout(self,t):timeouts.append(t)
            def request(self,method,path,*,body,headers):payloads.append(json.loads(body))
            def getresponse(self):return Response()
            def close(self):pass
        class Process:
            def __init__(self,target,args):self.target,self.args=target,args
            def start(self):self.target(*self.args)
            def join(self,**kwargs):pass
            def is_alive(self):return False
        class Context:
            def Pipe(self,**kwargs):return Pipe(),Pipe()
            def Process(self,target,args):return Process(target,args)
        c=replace(self.config,real_requests_authorized=True)
        with patch.dict('os.environ',{'LEAFAPI_API_KEY':'UNIT-NOT-REAL'}),patch.object(rt.mp,'get_context',return_value=Context()),patch.object(rt.http.client,'HTTPSConnection',Connection):
            transport=rt.JsonCandidateTransport(c)
            response=transport.dispatch('UNIT',(self.path/'Prompt.txt').read_text())
        self.assertTrue(response['text'].startswith('{Synthetic'))
        self.assertEqual(response['metadata']['model'],'gpt-6.1-sol')
        self.assertEqual(response['metadata']['http_content_type'],'application/json')
        self.assertEqual(len(payloads),1);self.assertIs(payloads[0]['stream'],False)
        self.assertNotIn('stream_options',payloads[0]);self.assertEqual(payloads[0]['max_completion_tokens'],8192)
        self.assertEqual(payloads[0]['messages'][0]['content'],(self.path/'Prompt.txt').read_text())
        self.assertNotIn('temperature',payloads[0]);self.assertNotIn('reasoning_effort',payloads[0])
        self.assertEqual(timeouts,[10,240]);self.assertEqual(c.provider.total_timeout,300)


if __name__=='__main__':unittest.main()
