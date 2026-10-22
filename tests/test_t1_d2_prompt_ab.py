"""D2A: recorded historical prompt identity + in-memory paired responses only."""
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.attempt_budget import AttemptJournal
from fjsp_usage.research_real.real_transport import decode_stream, JsonCandidateTransport, TransportError
from fjsp_usage.research_real.budget import BudgetStop
from test_chat_stream_transport import Response, wire
from test_t1_d1_diagnostic import mock_stream
from tools import t1_d2_prompt_ab as d


def bad_id():
    rows = mock_stream(); rows[1]['id'] = 'UNIT-DIFFERENT'; return wire(rows)


class Inner:
    identity='D2-MOCK-ONLY'; secret=''; redact=staticmethod(str)
    def __init__(self, config, answers=()): self.config, self.answers, self.sent = config, list(answers), []
    def preflight(self, prompt): pass
    def dispatch(self, key, prompt, *, kind='U', on_sent):
        self.sent.append((key, prompt)); on_sent()
        answer = self.answers.pop(0) if self.answers else wire(mock_stream())
        if isinstance(answer, BaseException): raise answer
        try: reply = decode_stream(Response(answer), self.config.provider)
        except BaseException as exc:
            exc.metadata = {'http_status':200,'http_content_type':'text/event-stream', **getattr(exc,'metadata',{})}; raise
        reply['metadata'].update(http_status=200, http_content_type='text/event-stream')
        return reply


class D2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'t1-d2-mock'; d.prepare(self.path)
        _, self.config = d.check(self.path)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        native_open = Path.open
        def no_old_state(path, *args, **kwargs):
            if any(path.resolve().is_relative_to(d.ROOT/'runs'/item[0]) for item in d.SOURCES.values()):
                raise AssertionError('NO HISTORICAL READS AFTER PREPARE')
            return native_open(path, *args, **kwargs)
        self.stack.enter_context(patch.object(Path, 'open', no_old_state))
        for name in ('socket.socket.connect','fjsp_usage.research_real.staged_evaluation.StagedDataset.load',
                     'fjsp_usage.research_real.runtime.evaluate','fjsp_usage.research.candidates.compile_candidate',
                     'fjsp_usage.research.evolution.Search.__init__','fjsp_usage.research_real.leafapi.load_local_key',
                     'fjsp_usage.research_real.leafapi.query_status','fjsp_usage.usage_v2.billing.query_invoices'):
            self.stack.enter_context(patch(name, side_effect=AssertionError('NO API, DATA, CANDIDATE EXECUTION OR ACCOUNT')))

    def session(self, answers=(), **kwargs):
        inner = Inner(self.config, answers); recorder = d.TimedRecorder(inner, self.path/'wire_responses')
        return d.session(self.path, self.config, recorder, provenance='mock-only', **kwargs), inner

    def test_frozen_sources_real_confirmed_requests_and_original_token_counts(self):
        origins = d.read(self.path/'Source_provenance.json')
        self.assertEqual(origins['A']['historical_logical_id'],'B/g0000/000000')
        self.assertEqual(origins['A']['historical_wire_status'],'wire_completed_before_settlement')
        self.assertEqual(origins['A']['historical_usage'],{'input_tokens':2759,'output_tokens':515})
        self.assertEqual(origins['B']['historical_logical_id'],'B/init/000000')
        self.assertTrue(origins['B']['historical_confirmed_send']); self.assertIsNone(origins['B']['historical_usage'])
        for arm, origin in origins.items():
            self.assertEqual(d.sha(self.path/f'Prompt_{arm}.txt'),origin['prompt_sha256'])
            self.assertEqual(len((self.path/f'Prompt_{arm}.txt').read_bytes()),origin['utf8_bytes'])
        self.assertFalse((self.path/'Authorization.json').exists()); self.assertFalse((self.path/'requests').exists())

    def test_A_success_B_failure(self):
        state, inner = self.session([wire(mock_stream()),bad_id()])
        self.assertEqual(state['phase'],'completed'); self.assertEqual(len(inner.sent),2)
        self.assertEqual([r['transport_success'] for r in state['outcomes']],[True,False])
        d.report(self.path); r=d.read(self.path/'AB_result.json')
        self.assertTrue(r['pair_observed']); self.assertFalse(r['both_transport_passed'])

    def test_A_failure_B_success_is_another_arm_not_retry(self):
        state, inner = self.session([bad_id(),wire(mock_stream())])
        self.assertEqual(state['phase'],'completed')
        self.assertEqual([key for key,_ in inner.sent],['T1-D2/A/attempt/01','T1-D2/B/attempt/01'])
        self.assertEqual([r['transport_success'] for r in state['outcomes']],[False,True])
        self.assertNotEqual(inner.sent[0][1],inner.sent[1][1])
        self.assertEqual(d.status(self.path)['api_attempts'],2)

    def test_both_fail_pair_is_complete_not_transport_pass(self):
        state, inner = self.session([bad_id(),bad_id()])
        self.assertEqual(state['phase'],'completed'); self.assertEqual(len(inner.sent),2)
        self.assertTrue(all(not r['transport_success'] for r in state['outcomes']))
        self.assertEqual(d.read(self.path/'requests/attempts.json')['halt_reason'],'transport_protocol_circuit_open')
        d.report(self.path); self.assertFalse(d.read(self.path/'AB_result.json')['both_output_contract_passed'])

    def test_both_succeed_identical_AST_allowed_and_complete_metrics(self):
        state, inner = self.session()
        self.assertEqual(len(inner.sent),2)
        self.assertEqual(len({r['candidate']['key'] for r in state['outcomes']}),1)
        for row in state['outcomes']:
            self.assertTrue(row['output_legal']); self.assertTrue(row['complete_text'])
            self.assertTrue(row['stop_received']); self.assertTrue(row['usage_received']); self.assertTrue(row['DONE_received'])
            self.assertEqual(row['http_content_type'],'text/event-stream')
            self.assertEqual(row['data_events_seen'],6)  # 5 JSON data events plus DONE.
            self.assertIsNotNone(row['send_confirmation_at']); self.assertIsNotNone(row['finished_at'])
            self.assertEqual(row['id_check'],'observed_consistent')
        d.report(self.path)
        self.assertIn('input_tokens',(self.path/'AB_result.csv').read_text())

    def test_illegal_U_does_not_become_transport_failure_or_retry(self):
        state, inner = self.session([wire(mock_stream('UNIT illegal output')),wire(mock_stream())])
        self.assertEqual(len(inner.sent),2)
        self.assertTrue(state['outcomes'][0]['transport_success'])
        self.assertFalse(state['outcomes'][0]['output_legal']); self.assertTrue(state['outcomes'][1]['output_legal'])

    def test_stream_eof_is_finalized_failure_continue_other_arm_no_retry(self):
        state, inner = self.session([wire(mock_stream(),done=False),wire(mock_stream())])
        self.assertEqual(len(inner.sent),2); self.assertFalse(state['outcomes'][0]['DONE_received'])
        self.assertEqual(state['outcomes'][0]['input_tokens'],100)

    def test_auth_and_quota_are_global_stops(self):
        error=TransportError('HTTP status 401'); error.metadata={'http_status':401}
        state, inner = self.session([error])
        self.assertEqual(state['phase'],'stopped_global'); self.assertEqual(len(inner.sent),1)
        d.report(self.path); self.assertEqual(d.read(self.path/'AB_result.json')['groups'][1]['status'],'not_sent')

    def test_quota_error_inside_HTTP200_stops_before_B(self):
        body=wire([{'error':{'code':'insufficient_quota','message':'UNIT'}}])
        state, inner = self.session([body])
        self.assertEqual(state['phase'],'stopped_global'); self.assertEqual(len(inner.sent),1)

    def test_locked_model_mismatch_is_global_not_ordinary_id_error(self):
        rows=mock_stream(); rows[1]['model']='different-model'
        state, inner = self.session([wire(rows)])
        self.assertEqual(state['global_stop_reason'],'global_locked_model_mismatch')
        self.assertEqual(len(inner.sent),1)

    def test_temporary_known_HTTP_status_is_not_same_arm_retry(self):
        error=TransportError('HTTP status 503'); error.metadata={'http_status':503}
        state, inner=self.session([error,wire(mock_stream())])
        self.assertEqual(state['phase'],'completed'); self.assertEqual(len(inner.sent),2)

    def test_unclassified_network_safety_stops_conservatively(self):
        state, inner=self.session([ConnectionError('UNIT no HTTP response')])
        self.assertEqual(state['phase'],'stopped_global'); self.assertEqual(len(inner.sent),1)

    def test_unknown_sent_interrupt_charged_and_resume_never_sends_B(self):
        inner=Inner(self.config,[KeyboardInterrupt('UNIT unknown sent')])
        with self.assertRaises(KeyboardInterrupt):
            d.session(self.path,self.config,d.TimedRecorder(inner,self.path/'wire_responses'),provenance='mock-only')
        state, later=self.session()
        self.assertEqual(state['global_stop_reason'],'global_unknown_delivery')
        self.assertEqual(len(later.sent),0); self.assertEqual(d.status(self.path)['api_attempts'],1)

    def test_reserved_but_unconfirmed_attempt_cannot_be_refunded_or_resent(self):
        transport=d.TimedRecorder(Inner(self.config),self.path/'wire_responses')
        with patch.object(transport,'dispatch',side_effect=KeyboardInterrupt('UNIT before wire')):
            with self.assertRaises(KeyboardInterrupt): d.session(self.path,self.config,transport,provenance='mock-only')
        state, later=self.session()
        self.assertEqual(state['phase'],'stopped_global'); self.assertEqual(len(later.sent),0)
        self.assertEqual(d.status(self.path)['api_attempts'],1)

    def test_complete_wire_restored_without_resending_A(self):
        inner=Inner(self.config); transport=d.TimedRecorder(inner,self.path/'wire_responses')
        with patch.object(AttemptJournal,'_accept',side_effect=KeyboardInterrupt('UNIT after complete wire')):
            with self.assertRaises(KeyboardInterrupt): d.session(self.path,self.config,transport,provenance='mock-only')
        state, later=self.session()
        self.assertEqual(state['phase'],'completed'); self.assertEqual(len(later.sent),1)
        self.assertEqual(later.sent[0][0],'T1-D2/B/attempt/01')

    def interrupt_after_A(self, answer, clock=lambda:10):
        native=d.atomic_json; interrupted=False
        def interrupted_commit(path,value):
            nonlocal interrupted
            native(path,value)
            if Path(path).name=='checkpoint.json' and len(value.get('outcomes',[]))==1 and not interrupted:
                interrupted=True; raise KeyboardInterrupt('UNIT between A and B')
        inner=Inner(self.config,[answer]); transport=d.TimedRecorder(inner,self.path/'wire_responses')
        with patch.object(d,'atomic_json',side_effect=interrupted_commit):
            with self.assertRaises(KeyboardInterrupt): d.session(self.path,self.config,transport,provenance='mock-only',clock=clock)

    def test_resume_ordinary_A_failure_only_sends_B_within_window(self):
        self.interrupt_after_A(bad_id())
        state, later=self.session(clock=lambda:20)
        self.assertEqual(state['phase'],'completed'); self.assertEqual(len(later.sent),1)
        self.assertEqual(later.sent[0][0],'T1-D2/B/attempt/01')

    def test_cached_global_failure_cannot_be_lost_in_interrupt(self):
        rows=mock_stream(); rows[0]['model']='wrong-model'; self.interrupt_after_A(wire(rows))
        state, later=self.session(clock=lambda:20)
        self.assertEqual(state['phase'],'stopped_global'); self.assertEqual(len(later.sent),0)

    def test_expired_pair_window_does_not_send_second_group(self):
        self.interrupt_after_A(wire(mock_stream()))
        state, later=self.session(clock=lambda:1000)
        self.assertEqual(state['global_stop_reason'],'pair_window_expired'); self.assertEqual(len(later.sent),0)

    def test_complete_restart_and_third_request_cap(self):
        self.session(); state, later=self.session()
        self.assertEqual(state['phase'],'completed'); self.assertEqual(len(later.sent),0)
        self.assertEqual(d.status(self.path)['api_attempts'],2)
        inner=Inner(self.config); transport=d.TimedRecorder(inner,self.path/'wire_responses')
        journal=AttemptJournal(self.path/'requests/attempts.json',config=self.config,phase='T1-D2',transport=transport,
            context={'protocol_sha256':d.sha(self.path/'Protocol.json'),'provenance':'mock-only'})
        with self.assertRaises(BudgetStop):journal.request('EXTRA','UNIT')
        self.assertEqual(len(inner.sent),0)

    def test_frozen_identity_change_after_A_stops_B_and_stays_stopped(self):
        original=(self.path/'Prompt_B.txt').read_bytes()
        inner=Inner(self.config); recorder=d.TimedRecorder(inner,self.path/'wire_responses')
        native=inner.dispatch
        def change_after_response(*args,**kwargs):
            response=native(*args,**kwargs)
            (self.path/'Prompt_B.txt').write_bytes(original+b'CHANGED')
            return response
        with patch.object(inner,'dispatch',side_effect=change_after_response):
            with self.assertRaises(ValueError):d.session(self.path,self.config,recorder,provenance='mock-only')
        self.assertEqual(len(inner.sent),1)
        (self.path/'Prompt_B.txt').write_bytes(original)
        state,later=self.session()
        self.assertEqual(state['phase'],'stopped_global');self.assertEqual(len(later.sent),0)

    def test_orphan_checkpoint_or_missing_ledger_never_resets(self):
        self.session(); (self.path/'requests/attempts.json').unlink()
        with self.assertRaisesRegex(ValueError,'missing D2'): self.session()

    def test_orphan_ledger_never_reinitializes(self):
        self.session(); (self.path/'checkpoint.json').unlink()
        with self.assertRaisesRegex(ValueError,'orphan D2'): self.session()

    def test_no_auth_and_old_stage_approval_do_not_read_credentials(self):
        with self.assertRaises(BudgetStop): d.run_real(self.path,Path('/never/read'))
        auth=d.approval(self.path,True); auth['stage']='T1-D1'
        (self.path/'Authorization.json').write_text(json.dumps(auth))
        with self.assertRaises(BudgetStop): d.run_real(self.path,Path('/never/read'))

    def test_copied_protocol_and_historical_symlink_rejected(self):
        other=Path(self.tmp.name)/'t1-d2-copy'; shutil.copytree(self.path,other)
        with self.assertRaises(ValueError): d.check(other)
        (self.path/'requests').symlink_to(d.ROOT/'runs'/d.SOURCES['B'][0],target_is_directory=True)
        with self.assertRaises(ValueError): d.check(self.path)

    def test_mock_cannot_be_promoted_to_real(self):
        self.session(); (self.path/'Authorization.json').write_text(json.dumps(d.approval(self.path,True)))
        c=replace(self.config,real_requests_authorized=True)
        with self.assertRaises(ValueError): d.session(self.path,c,d.TimedRecorder(Inner(c),self.path/'wire_responses'),provenance='real')

    def test_response_metadata_counts_do_not_relax_T1_acceptance(self):
        # Execute trusted historical module definitions, not generated code.
        legacy={'__name__':'fjsp_usage.research_real.t1_reference','__package__':'fjsp_usage.research_real'}
        blob=subprocess.check_output(['git','show','2eaabe09:code/fjsp_usage/research_real/real_transport.py'],cwd=d.ROOT)
        exec(compile(blob,'T1_REFERENCE','exec'),legacy)
        bodies=[wire(mock_stream()),bad_id(),wire(mock_stream(),done=False),wire([{'error':{'code':'server_overloaded'}}]),b'data: {bad}\n\n']
        rows=mock_stream(); rows[1]['model']='wrong'; bodies.append(wire(rows))
        for body in bodies:
            results=[]
            for decoder in (legacy['decode_stream'],decode_stream):
                try: results.append(('success',decoder(Response(body),self.config.provider)['text']))
                except Exception as exc: results.append(('failure',str(exc)))
            self.assertEqual(results[0],results[1])

    def test_actual_payload_configuration_identical_except_prompt(self):
        messages=[]; payloads=[]; provider=self.config.provider
        class Pipe:
            def close(self):pass
            def poll(self,_):return bool(messages)
            def recv(self):return messages.pop(0)
        class Process:
            def __init__(self,target,args):payloads.append(args[2])
            def start(self):messages.extend([{'kind':'sent'},{'kind':'reply',**decode_stream(Response(wire(mock_stream())),provider)}])
            def join(self,**kwargs):pass
            def is_alive(self):return False
        class Context:
            def Process(self,target,args):return Process(target,args)
            def Pipe(self,**kwargs):return Pipe(),Pipe()
        c=replace(self.config,real_requests_authorized=True)
        with patch.dict('os.environ',{'LEAFAPI_API_KEY':'UNIT-NOT-REAL'}),patch('fjsp_usage.research_real.real_transport.mp.get_context',return_value=Context()):
            transport=JsonCandidateTransport(c)
            for arm in ['A','B']:transport.dispatch(arm,(self.path/f'Prompt_{arm}.txt').read_text())
        self.assertNotEqual(payloads[0]['messages'],payloads[1]['messages'])
        self.assertEqual({k:v for k,v in payloads[0].items() if k!='messages'},{k:v for k,v in payloads[1].items() if k!='messages'})
        self.assertEqual(payloads[0]['model'],'gpt-6.1-sol'); self.assertEqual(payloads[0]['max_completion_tokens'],8192)
        self.assertEqual(payloads[0]['stream_options'],{'include_usage':True})
