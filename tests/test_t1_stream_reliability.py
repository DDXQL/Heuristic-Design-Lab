"""T1: in-memory SSE and synthetic journals. No network, credentials or FJSP."""
from contextlib import ExitStack
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research_real.attempt_budget import AttemptJournal, CIRCUIT_VERSION, failure_policy
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig
from fjsp_usage.research_real.real_transport import (
    TransportError, decode_stream, _wire_worker, JsonCandidateTransport, WIRE_VERSION)
from fjsp_usage.usage_v2.access import WireRecorder
from test_chat_stream_transport import chunks, wire, Response


def provider():
    return ProviderConfig('http://localhost/UNIT', 'alias', protocol='openai-chat-v1',
                          stream_response=True, expected_response_model='locked-model')


def decode(body):
    return decode_stream(Response(body), provider())


def stream_fault(body):
    try:
        decode(body)
    except TransportError as error:
        return error
    raise AssertionError('fixture must fail')


def error_frame(code=None, message='synthetic message', **fields):
    return wire([{'error': {'code': code, 'message': message, **fields}}])


class T1StreamTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        for name in ('socket.socket.connect', 'fjsp_usage.research_real.runtime.evaluate',
                     'fjsp_usage.research_real.staged_evaluation.StagedDataset.load',
                     'fjsp_usage.research_real.leafapi.query_status',
                     'fjsp_usage.usage_v2.billing.query_invoices'):
            self.stack.enter_context(patch(name, side_effect=AssertionError('NO NETWORK OR FJSP')))

    def test_correct_stream_done_usage_reasoning_and_parameters(self):
        value = decode(wire(chunks()))
        self.assertEqual(value['usage'], {'input_tokens': 100, 'output_tokens': 60})
        self.assertNotIn('not candidate code', value['text'])
        self.assertEqual(value['metadata']['model'], 'locked-model')
        self.assertEqual(value['metadata']['finish_reason'], 'stop')

    def test_legal_sse_bom_crlf_cr_comments_and_ignored_fields(self):
        expected = decode(wire(chunks()))['text']
        for ending in (b'\n', b'\r\n', b'\r'):
            body = b'\xef\xbb\xbf' + wire(chunks()).replace(b'\n', ending)
            body = body.replace(b'data:', b'x-ignored: yes' + ending + b'data:')
            with self.subTest(ending=ending):
                self.assertEqual(decode(body)['text'], expected)

    def test_chunk_boundaries_split_utf8_and_crlf(self):
        class OneByte(Response):
            def read1(self, _): return super().read1(1)
        body = b'\xef\xbb\xbf' + wire(chunks()).replace(b'\n', b'\r\n')
        self.assertEqual(decode_stream(OneByte(body), provider())['usage']['input_tokens'], 100)

    def test_multiline_data_and_space_handling(self):
        body = wire(chunks()).replace(b', "model":', b',\ndata: "model":')
        self.assertEqual(decode(body)['usage']['output_tokens'], 60)
        self.assertEqual(decode(wire(chunks()).replace(b'data: ', b'data:'))['usage']['input_tokens'], 100)

    def test_content_type_case_and_wrong_content_type(self):
        class Header(Response):
            def getheader(self, *args): return self.header
        response = Header(wire(chunks())); response.header = 'Text/Event-Stream; charset=UTF-8'
        self.assertEqual(decode_stream(response, provider())['finish_reason'], 'stop')
        response = Header(wire(chunks())); response.header = 'application/json'
        with self.assertRaises(TransportError): decode_stream(response, provider())

    def test_identity_and_model_changes_keep_hashed_before_after(self):
        for field in ('id', 'model'):
            rows = chunks(); rows[1][field] = 'sensitive-untrusted-value'
            error = stream_fault(wire(rows))
            self.assertEqual(str(error), 'stream identity/model changed')
            change = error.metadata['identity_change']
            self.assertEqual(change['field'], field)
            self.assertNotEqual(change['previous']['sha256'], change['observed']['sha256'])
            self.assertNotIn('sensitive-untrusted-value', json.dumps(error.metadata))
            self.assertFalse(failure_policy(str(error), error.metadata)[0])

    def test_missing_identity_is_rejected_even_on_usage_frame(self):
        for field in ('id', 'model'):
            for index in (0, 4):
                rows = chunks(); rows[index].pop(field)
                with self.subTest(field=field, index=index):
                    error = stream_fault(wire(rows))
                    self.assertEqual(str(error), 'missing stream identity/model')
                    self.assertNotIn(field, error.metadata['stream_evidence']['last_frame']['fields'])

    def test_wrong_locked_model_rejected_on_first_frame(self):
        rows = chunks()
        for row in rows: row['model'] = 'different-model'
        self.assertEqual(str(stream_fault(wire(rows))), 'stream model differs from locked model')

    def test_unknown_error_frame_is_not_silently_accepted_or_retried(self):
        for body in (error_frame('unknown_vendor_code'), wire([[]]), wire([None]), wire([{'error': None}])):
            error = stream_fault(body)
            self.assertEqual(str(error), 'invalid/error stream chunk')
            self.assertFalse(failure_policy(str(error), error.metadata)[0])
            self.assertTrue(error.metadata['stream_protocol_anomaly'])

    def test_explicit_temporary_codes_statuses_and_permanent_precedence(self):
        for code in ('service_unavailable', 'temporarily_unavailable', 'server_overloaded', 'rate_limit_exceeded'):
            error = stream_fault(error_frame(code))
            self.assertEqual(error.metadata['failure_class'], 'temporary')
            self.assertTrue(failure_policy(str(error), error.metadata)[0])
            self.assertFalse(error.metadata['stream_protocol_anomaly'])
        for status in (429, 502, 503, 504):
            error = stream_fault(error_frame(status=status))
            self.assertTrue(failure_policy(str(error), error.metadata)[0])
        error = stream_fault(error_frame('insufficient_quota', status=503))
        self.assertEqual(failure_policy(str(error), error.metadata),
                         (False, 'permanent_auth_quota_model_or_parameter_error', True))

    def test_auth_model_parameter_errors_never_retry(self):
        for code in ('invalid_api_key', 'authentication_error', 'model_not_found',
                     'invalid_request_error', 'invalid_parameter', 'permission_denied'):
            error = stream_fault(error_frame(code))
            retry, _, halt = failure_policy(str(error), error.metadata)
            self.assertFalse(retry); self.assertTrue(halt)

    def test_error_event_never_becomes_success_even_with_done_or_normal_json(self):
        bodies = [b'event: error\n\n', b'event: error\ndata: [DONE]\n\n',
                  b'event: error\n' + wire([chunks()[0]])[len(b': keepalive\n\n'):],
                  wire([{'type': 'error', 'code': 'server_overloaded'}])]
        for body in bodies:
            with self.subTest(body=body[:30]), self.assertRaises(TransportError): decode(body)

    def test_error_after_complete_content_or_usage_is_not_accepted(self):
        body = wire(chunks(), done=False) + error_frame('server_overloaded')
        error = stream_fault(body)
        self.assertTrue(failure_policy(str(error), error.metadata)[0])
        self.assertEqual(error.usage, {'input_tokens': 100, 'output_tokens': 60})
        self.assertFalse(hasattr(error, 'text'))

    def test_done_without_stop_or_usage_rejected(self):
        for rows in ([], chunks()[:3], chunks()[:-1]):
            error = stream_fault(wire(rows))
            self.assertEqual(str(error), 'stream requires stop and final usage before DONE')

    def test_eof_and_socket_timeout_are_temporary_no_partial_text(self):
        error = stream_fault(wire(chunks(), done=False))
        self.assertTrue(failure_policy(str(error), error.metadata)[0])
        self.assertEqual(error.metadata['network_error_type'], 'stream_eof')
        class Timeout(Response):
            def read1(self, _): raise TimeoutError('UNIT')
        with self.assertRaises(TransportError) as caught: decode_stream(Timeout(), provider())
        self.assertTrue(failure_policy(str(caught.exception), caught.exception.metadata)[0])

    def test_malformed_json_utf8_limits_and_nonstandard_content(self):
        bodies = [b'data: {bad}\n\n', b'data: \xff\n\n', b'data: ' + b'x' * 65537 + b'\n\n']
        for fault in ('length', 'tools', 'index', 'late', 'usage', 'content'):
            rows = chunks()
            if fault == 'length': rows[3]['choices'][0]['finish_reason'] = 'length'
            if fault == 'tools': rows[0]['choices'][0]['delta']['tool_calls'] = [{'secret': 'never save'}]
            if fault == 'index': rows[0]['choices'][0]['index'] = True
            if fault == 'late': rows.append(rows[0])
            if fault == 'usage': rows.append(rows[-1])
            if fault == 'content': rows[0]['choices'][0]['delta']['content'] = ['invalid']
            bodies.append(wire(rows))
        for body in bodies:
            error = stream_fault(body)
            self.assertFalse(failure_policy(str(error), error.metadata)[0])
            self.assertEqual(error.metadata['failure_class'], 'protocol_incompatible')

    def test_structural_evidence_never_saves_untrusted_secrets_or_keys(self):
        sentinel = 'SYNTHETIC-PRIVATE-HEADER-OR-TOKEN'
        body = wire([{'error': {'message': sentinel, 'code': sentinel, 'type': sentinel,
                               'authorization': sentinel}, sentinel: sentinel}])
        metadata = stream_fault(body).metadata
        self.assertNotIn(sentinel, json.dumps(metadata))
        self.assertNotIn('authorization', json.dumps(metadata))
        self.assertEqual(metadata['stream_evidence']['event_index'], 1)
        self.assertIn('sha256', metadata['error_message_evidence'])

    def test_worker_preserves_sse_error_evidence_through_pipe(self):
        class HTTP(Response):
            status = 200
            def getheader(self, key, default=None):
                return 'text/event-stream' if key == 'Content-Type' else default
        class Connection:
            sock = None
            def connect(self): self.sock = self
            def settimeout(self, _): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return HTTP(error_frame('server_overloaded'))
            def close(self): pass
        class Pipe:
            def __init__(self): self.messages = []
            def send(self, value): self.messages.append(value)
            def close(self): pass
        pipe = Pipe()
        with patch('http.client.HTTPConnection', return_value=Connection()):
            _wire_worker(pipe, provider(), {'UNIT': True}, 'SYNTHETIC_SECRET')
        value = pipe.messages[-1]
        self.assertEqual(value['kind'], 'error')
        self.assertEqual(value['metadata']['http_status'], 200)
        self.assertEqual(value['metadata']['error_code'], 'server_overloaded')
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(pipe.messages))


class Inner:
    identity = 'T1-MOCK-ONLY'; secret = 'UNIT_SECRET'; redact = staticmethod(str)
    def __init__(self, config, outcomes): self.config, self.outcomes, self.sent = config, list(outcomes), []
    def preflight(self, prompt): pass
    def dispatch(self, key, prompt, *, kind='U', on_sent):
        self.sent.append(key); on_sent()
        value = self.outcomes.pop(0) if self.outcomes else wire(chunks())
        if isinstance(value, BaseException): raise value
        return decode(value)


class T1JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.config = ExperimentConfig(provider(), total_request_cap=6, request_budget={
            'version': CIRCUIT_VERSION, 'logical_candidate_cap': 6, 'api_attempt_cap': 9,
            'per_candidate_attempt_cap': 3, 'retry_backoff_seconds': [2, 5],
            'protocol_error_circuit_threshold': 3})
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        for name in ('socket.socket.connect', 'fjsp_usage.research_real.runtime.evaluate',
                     'fjsp_usage.research_real.staged_evaluation.StagedDataset.load',
                     'fjsp_usage.research_real.leafapi.query_status',
                     'fjsp_usage.usage_v2.billing.query_invoices'):
            self.stack.enter_context(patch(name, side_effect=AssertionError('NO NETWORK OR FJSP')))

    def journal(self, outcomes=(), config=None):
        config = config or self.config
        inner = Inner(config, outcomes)
        wire_record = WireRecorder(inner, self.path/'wire')
        journal = AttemptJournal(self.path/'journal.json', config=config, context='T1-SYNTHETIC',
                                 phase='UNIT', transport=wire_record, sleep=lambda _: None)
        return journal, inner

    def test_temporary_stream_error_then_success_first_response_only(self):
        j, inner = self.journal([error_frame('server_overloaded'), wire(chunks())])
        result = j.request('c0', 'unchanged')
        self.assertEqual(result['status'], 'completed'); self.assertEqual(j.attempt_count, 2)
        j.request('c0', 'unchanged'); self.assertEqual(len(inner.sent), 2)
        self.assertEqual(result['accepted_attempt_id'], inner.sent[1])

    def test_unknown_protocol_errors_trip_after_three_and_persist(self):
        j, inner = self.journal([error_frame('unknown')] * 3)
        for n in range(3): self.assertEqual(j.request(str(n), 'p')['status'], 'failed')
        self.assertEqual(j.summary()['consecutive_protocol_errors'], 3)
        with self.assertRaisesRegex(BudgetStop, 'circuit'): j.request('fourth', 'p')
        resumed, after = self.journal()
        with self.assertRaisesRegex(BudgetStop, 'circuit'): resumed.request('fourth', 'p')
        self.assertEqual((j.attempt_count, len(inner.sent), len(after.sent)), (3, 3, 0))
        self.assertEqual(resumed.calls, 3)

    def test_complete_response_resets_streak_even_if_later_code_is_illegal(self):
        j, inner = self.journal([error_frame('unknown')] * 2 + [wire(chunks())] + [error_frame('unknown')] * 2)
        for n in range(5): j.request(str(n), 'p')
        self.assertEqual(j.summary()['consecutive_protocol_errors'], 2)
        self.assertIsNone(j.data['halt_reason'])
        self.assertEqual(len(inner.sent), 5)  # Parsing/fitness are outside the API circuit.

    def test_recovery_of_failed_wire_applies_circuit_before_another_send(self):
        j, inner = self.journal([error_frame('unknown')] * 3)
        j.request('0', 'p'); j.request('1', 'p')
        original = j.save
        def crash_before_failed_journal_commit():
            if any(a['status'] == 'failed' for a in j.data['api_attempts'].values()
                   if a['logical_id'] == '2'):
                raise KeyboardInterrupt('UNIT after failed wire saved')
            original()
        with patch.object(j, 'save', side_effect=crash_before_failed_journal_commit):
            with self.assertRaises(KeyboardInterrupt): j.request('2', 'p')
        resumed, after = self.journal()
        self.assertEqual(resumed.request('2', 'p')['status'], 'failed')
        with self.assertRaisesRegex(BudgetStop, 'circuit'): resumed.request('3', 'p')
        self.assertEqual(len(after.sent), 0); self.assertEqual(resumed.attempt_count, 3)

    def test_complete_wire_recovered_without_resend_or_second_selection(self):
        j, _ = self.journal()
        with patch.object(j, '_accept', side_effect=KeyboardInterrupt('UNIT after wire saved')):
            with self.assertRaises(KeyboardInterrupt): j.request('c', 'p')
        resumed, inner = self.journal()
        self.assertEqual(resumed.request('c', 'p')['status'], 'completed')
        self.assertEqual((resumed.attempt_count, len(inner.sent)), (1, 0))

    def test_interrupt_immediately_after_wire_commit_preserves_success(self):
        from fjsp_usage.research.events import atomic_json
        j, _ = self.journal()
        def commit_then_interrupt(path, value):
            atomic_json(path, value)
            if value.get('status') == 'wire_completed_before_settlement':
                raise KeyboardInterrupt('UNIT after atomic successful wire write')
        with patch('fjsp_usage.usage_v2.access.atomic_json', side_effect=commit_then_interrupt):
            with self.assertRaises(KeyboardInterrupt): j.request('c', 'p')
        saved = json.loads(next((self.path/'wire').glob('*.json')).read_text())
        self.assertEqual(saved['status'], 'wire_completed_before_settlement')
        resumed, inner = self.journal()
        self.assertEqual(resumed.request('c', 'p')['status'], 'completed')
        self.assertEqual((resumed.attempt_count, len(inner.sent)), (1, 0))

    def test_unknown_sent_interruption_is_charged_and_pauses_without_resend(self):
        j, _ = self.journal([KeyboardInterrupt('UNIT unknown delivery')])
        with self.assertRaises(KeyboardInterrupt): j.request('c', 'p')
        resumed, inner = self.journal()
        self.assertEqual(resumed.request('c', 'p')['status'], 'failed')
        self.assertEqual((resumed.attempt_count, len(inner.sent)), (1, 0))
        self.assertEqual(list(resumed.data['api_attempts'].values())[0]['status'], 'interrupted_unknown')
        with self.assertRaisesRegex(BudgetStop, 'uncertain_dispatch'): resumed.request('next', 'p')

    def test_reserved_but_unconfirmed_interruption_is_not_refunded(self):
        j, _ = self.journal()
        with patch.object(j.transport, 'dispatch', side_effect=KeyboardInterrupt('UNIT before wire')):
            with self.assertRaises(KeyboardInterrupt): j.request('c', 'p')
        resumed, inner = self.journal()
        self.assertEqual(resumed.request('c', 'p')['status'], 'failed')
        self.assertEqual(resumed.attempt_count, 1)
        first = list(resumed.data['api_attempts'].values())[0]
        self.assertFalse(first['send_confirmed']); self.assertEqual(first['status'], 'interrupted_unknown')
        self.assertEqual(len(inner.sent), 0)
        with self.assertRaisesRegex(BudgetStop, 'uncertain_dispatch'): resumed.request('next', 'p')

    def test_budget_caps_and_backoff_are_not_reset_by_restart(self):
        j, inner = self.journal([error_frame('server_overloaded')] * 9)
        sleeps = []; j.sleep = sleeps.append
        for n in range(3): self.assertEqual(j.request(str(n), 'p')['status'], 'failed')
        self.assertEqual(len(sleeps), 6)
        self.assertEqual((j.calls, j.attempt_count, len(inner.sent)), (3, 9, 9))
        resumed, after = self.journal()
        with self.assertRaisesRegex(BudgetStop, 'cap'): resumed.request('extra', 'p')
        self.assertEqual(len(after.sent), 0)
        self.assertIsNone(resumed.summary()['actual_cost'])

    def test_legacy_policy_has_no_implicit_circuit_and_cannot_migrate(self):
        budget = dict(self.config.request_budget); budget.pop('protocol_error_circuit_threshold')
        budget['version'] = 'batch-api-attempts-v1'
        config = replace(self.config, request_budget=budget)
        j, _ = self.journal([error_frame('unknown')] * 4, config)
        for n in range(4): j.request(str(n), 'p')
        self.assertIsNone(j.data['halt_reason'])
        with self.assertRaises(ValueError): self.journal(config=self.config)

    def test_wire_metadata_redacted_recursively_even_for_other_transports(self):
        error = TransportError('Bearer UNIT_SECRET sk-TESTSECRET')
        error.metadata = {'nested': {'authorization': 'UNIT_SECRET', 'value': 'Bearer sk-NESTED'}}
        j, _ = self.journal([error]); j.request('c', 'p')
        for path in [self.path/'journal.json', *list((self.path/'wire').glob('*.json'))]:
            content = path.read_text()
            self.assertNotIn('UNIT_SECRET', content); self.assertNotIn('sk-NESTED', content)

    def test_policy_requires_explicit_threshold_and_rejects_boolean(self):
        for value in (True, 0, 11):
            budget = {**self.config.request_budget, 'protocol_error_circuit_threshold': value}
            with self.assertRaises(ValueError): replace(self.config, request_budget=budget)

    def test_unknown_reservation_does_not_clear_prior_protocol_streak(self):
        j, _ = self.journal([error_frame('unknown')] * 2)
        j.request('0', 'p'); j.request('1', 'p')
        with patch.object(j.transport, 'dispatch', side_effect=KeyboardInterrupt('UNIT before send')):
            with self.assertRaises(KeyboardInterrupt): j.request('2', 'p')
        resumed, inner = self.journal([error_frame('unknown')])
        self.assertEqual(resumed.request('2', 'p')['status'], 'failed')
        self.assertEqual(resumed.summary()['consecutive_protocol_errors'], 2)
        self.assertEqual((resumed.attempt_count, len(inner.sent)), (3, 0))
        with self.assertRaisesRegex(BudgetStop, 'uncertain_dispatch'): resumed.request('3', 'p')

    def test_circuit_reconstructs_from_persisted_outcomes_without_reset(self):
        j, _ = self.journal([error_frame('unknown')] * 3)
        for n in range(3): j.request(str(n), 'p')
        # A synthetic interrupted summary commit: outcomes remain authoritative.
        data = json.loads(j.path.read_text()); data['halt_reason'] = None
        j.path.write_text(json.dumps(data))
        resumed, inner = self.journal()
        with self.assertRaisesRegex(BudgetStop, 'circuit'): resumed.request('new', 'p')
        self.assertEqual(len(inner.sent), 0)

    def test_logical_cap_is_independent_of_attempt_cap(self):
        j, inner = self.journal()
        for n in range(6): self.assertEqual(j.request(str(n), 'p')['status'], 'completed')
        with self.assertRaisesRegex(BudgetStop, 'logical'): j.request('extra', 'p')
        self.assertEqual((j.calls, j.attempt_count, len(inner.sent)), (6, 6, 6))

    def test_b1_search_circuit_stops_between_candidates_and_checkpoint_recovers(self):
        from fjsp_usage.research.candidates import Candidate
        from tools.b1_usage_local import B1Search
        config = replace(self.config, population_size=5, cross_parents=2, generations=2,
                         attempts_per_generation=10, seeds=(501,), initialization_cap=20)
        members = tuple(Candidate('MOCK ONLY', f'def priority(x):\n    return {i}\n',
                                  'MOCK_H_' + str(i), 'h') for i in range(10))
        inner = Inner(config, [error_frame('unknown')] * 3)
        transport = WireRecorder(inner, self.path/'wire')
        def engine():
            return B1Search(self.path/'search', experiment=config, training_names=('MOCK',),
                arm='B', config=config.u_search(501), members=members,
                evaluator=lambda _: self.fail('no failed stream may reach evaluation'),
                transport=transport, context='T1-MOCK-ONLY')
        search = engine()
        with self.assertRaisesRegex(BudgetStop, 'circuit'): search.run()
        self.assertEqual(search.state['init_cursor'], 3)
        self.assertIsNone(search.state['inflight'])
        self.assertEqual(search.state['evaluations'], {})
        restarted = engine()
        with self.assertRaisesRegex(BudgetStop, 'circuit'): restarted.run()
        self.assertEqual(len(inner.sent), 3)
        self.assertEqual(restarted.state['generation'], 0)

    def test_transport_revision_changes_wire_identity_without_model_change(self):
        config = ExperimentConfig(provider())
        from fjsp_usage.research.protocol import digest
        transport = JsonCandidateTransport(config)
        old = digest({'provider': config.payload()['provider'], 'mode': config.mode})
        self.assertNotEqual(transport.identity, old)
        self.assertIn('t1', WIRE_VERSION)
