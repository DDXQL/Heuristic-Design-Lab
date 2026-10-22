"""T1-D1A acceptance: synthetic SSE only; no real API/data/U execution."""
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research.candidates import U_ARGS
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.real_transport import decode_stream, JsonCandidateTransport, TransportError
from fjsp_usage.usage_v2.access import WireRecorder
from test_chat_stream_transport import chunks, wire, Response
from tools import t1_d1_diagnostic as diagnostic


def mock_stream(text=None):
    if text is None:
        text = '{Synthetic interface fixture only}\n```python\ndef use_heuristics('+', '.join(U_ARGS)+'):\n    return (1, (0.5, 0.5, 0, 0, 0, 0, 0, 0, 0, 0))\n```'
    rows = chunks()
    for row in rows: row['model'] = 'gpt-6.1-sol'
    rows[0]['choices'][0]['delta']['content'] = text
    rows[2]['choices'][0]['delta']['content'] = ''
    return rows


class Inner:
    identity = 'T1-D1-MOCK-ONLY'; secret = ''; redact = staticmethod(str)
    def __init__(self, config, answers=()): self.config, self.answers, self.sent = config, list(answers), []
    def preflight(self, prompt): pass
    def dispatch(self, key, prompt, *, kind='U', on_sent):
        self.sent.append((key, prompt)); on_sent()
        answer = self.answers.pop(0) if self.answers else wire(mock_stream())
        if isinstance(answer, BaseException): raise answer
        return decode_stream(Response(answer), self.config.provider)


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'t1-d1-mock'
        diagnostic.prepare(self.path)
        _, self.config = diagnostic.check(self.path)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.allowed_historical_reads = set(); self.historical_reads = []
        native_open = Path.open
        def guarded_open(path, mode='r', *args, **kwargs):
            resolved = path.resolve()
            if resolved.is_relative_to(diagnostic.SOURCE):
                if any(c in mode for c in 'wax+') or resolved not in self.allowed_historical_reads:
                    raise AssertionError('NO OLD B1 STATE OR HISTORICAL WRITES')
                self.historical_reads.append(resolved)
            return native_open(path, mode, *args, **kwargs)
        self.stack.enter_context(patch.object(Path, 'open', guarded_open))
        for name in ('socket.socket.connect', 'fjsp_usage.research_real.staged_evaluation.StagedDataset.load',
                     'fjsp_usage.research_real.runtime.evaluate', 'fjsp_usage.research.candidates.compile_candidate',
                     'fjsp_usage.research.evolution.Search.__init__',
                     'fjsp_usage.research_real.leafapi.load_local_key',
                     'fjsp_usage.research_real.leafapi.provider', 'fjsp_usage.research_real.leafapi.query_status',
                     'fjsp_usage.usage_v2.billing.query_invoices'):
            self.stack.enter_context(patch(name, side_effect=AssertionError('NO REAL API, DATA, U EXECUTION OR ACCOUNT')))

    def session(self, answers=()):
        inner = Inner(self.config, answers)
        transport = WireRecorder(inner, self.path/'wire_responses')
        result = diagnostic.session(self.path, self.config, transport, provenance='mock-only')
        return result, inner

    def test_source_whitelist_prompt_exact_and_prepare_refuses_overwrite(self):
        self.allowed_historical_reads = {diagnostic.SOURCE/n for n in
            ('Protocol.json', 'config.pending.json', diagnostic.SOURCE_PROMPT)}
        other = Path(self.tmp.name)/'t1-d1-another'
        diagnostic.prepare(other)
        self.assertEqual(set(self.historical_reads), self.allowed_historical_reads)
        self.assertEqual(hashlib.sha256((other/'Prompt.txt').read_bytes()).hexdigest(), diagnostic.PROMPT_SHA)
        with self.assertRaises(ValueError): diagnostic.prepare(other)

    def test_prepared_authorization_false_and_no_request_records(self):
        status = diagnostic.status(self.path)
        self.assertEqual((status['logical_tasks'], status['api_attempts']), (0, 0))
        self.assertFalse(status['authorization_present'])
        self.assertFalse(diagnostic.read(self.path/'Authorization.template.json')['approved'])
        self.assertFalse((self.path/'requests/attempts.json').exists())
        self.assertFalse(self.config.real_requests_authorized)

    def test_success_two_identical_AST_allowed_no_population_or_evaluation(self):
        result, inner = self.session()
        self.assertEqual(result['phase'], 'completed')
        self.assertEqual(len(inner.sent), 2)
        self.assertEqual(len({r['candidate']['key'] for r in result['outcomes']}), 1)
        self.assertTrue(all(r['valid'] and not r['evaluated'] for r in result['outcomes']))
        self.assertEqual({p for _, p in inner.sent}, {(self.path/'Prompt.txt').read_text()})
        self.assertTrue(inner.sent[0][0].endswith('/attempt/01'))
        self.assertTrue(inner.sent[1][0].endswith('/attempt/01'))
        self.assertEqual(diagnostic.status(self.path)['api_attempts'], 2)
        self.assertFalse((self.path/'P0.json').exists())
        self.assertEqual(len(list((self.path/'responses').glob('*.txt'))), 2)

    def test_temporary_http_failure_stops_after_one_no_retry_no_second_task(self):
        error = TransportError('HTTP status 503; response body omitted')
        error.metadata = {'http_status': 503}
        result, inner = self.session([error])
        self.assertEqual(result['phase'], 'stopped'); self.assertEqual(len(inner.sent), 1)
        again, later = self.session()
        self.assertEqual(again['phase'], 'stopped'); self.assertEqual(len(later.sent), 0)
        self.assertEqual(diagnostic.status(self.path)['api_attempts'], 1)

    def test_error_frame_trip_threshold_one(self):
        result, inner = self.session([wire([{'error': {'code': 'vendor_unknown'}}])])
        self.assertEqual(result['phase'], 'stopped'); self.assertEqual(len(inner.sent), 1)
        journal = diagnostic.read(self.path/'requests/attempts.json')
        self.assertEqual(journal['halt_reason'], 'transport_protocol_circuit_open')
        metadata = next(iter(journal['api_attempts'].values()))['metadata']
        self.assertIn('stream_evidence', metadata)

    def test_identity_change_remains_failure_with_evidence(self):
        rows = mock_stream(); rows[1]['id'] = 'UNIT-CHANGED'
        result, inner = self.session([wire(rows)])
        self.assertEqual(result['phase'], 'stopped'); self.assertEqual(len(inner.sent), 1)
        journal = diagnostic.read(self.path/'requests/attempts.json')
        self.assertEqual(next(iter(journal['api_attempts'].values()))['metadata']['identity_change']['field'], 'id')

    def test_wrong_model_is_rejected(self):
        rows = mock_stream(); rows[0]['model'] = 'gpt-5.6-sol'
        result, inner = self.session([wire(rows)])
        self.assertEqual(result['phase'], 'stopped'); self.assertEqual(len(inner.sent), 1)

    def test_missing_done_not_accepted_or_retried(self):
        result, inner = self.session([wire(mock_stream(), done=False)])
        self.assertEqual(result['phase'], 'stopped'); self.assertEqual(len(inner.sent), 1)

    def test_missing_usage_not_accepted(self):
        result, inner = self.session([wire(mock_stream()[:-1])])
        self.assertEqual(result['phase'], 'stopped'); self.assertEqual(len(inner.sent), 1)

    def test_illegal_output_full_response_preserved_no_retry(self):
        result, inner = self.session([wire(mock_stream('UNIT deliberately illegal'))])
        self.assertEqual(result['outcomes'][0]['status'], 'output_contract_failed')
        self.assertEqual(result['phase'], 'stopped'); self.assertEqual(len(inner.sent), 1)
        self.assertEqual((self.path/'responses/00.txt').read_text(), 'UNIT deliberately illegal')
        later, fresh = self.session()
        self.assertEqual(later['phase'], 'stopped'); self.assertEqual(len(fresh.sent), 0)

    def test_vector_length_and_forbidden_dictionary_fail_static_validation(self):
        for source in ('return (0, (1, 0))', 'return {0: 1}'):
            text = '{UNIT}\n```python\ndef use_heuristics('+', '.join(U_ARGS)+'):\n    '+source+'\n```'
            record = {'text': text, 'usage': {'input_tokens': 1, 'output_tokens': 1},
                'response_metadata': {'id': 'UNIT', 'model': 'gpt-6.1-sol', 'finish_reason': 'stop'}}
            with self.assertRaises(ValueError): diagnostic.validate_reply(record)

    def test_reply_requires_usage_stop_and_model_even_with_valid_code(self):
        record = {'text': decode_stream(Response(wire(mock_stream())), self.config.provider)['text'],
            'usage': {'input_tokens': 1, 'output_tokens': 1},
            'response_metadata': {'id': 'UNIT', 'model': 'gpt-6.1-sol', 'finish_reason': 'stop'}}
        for field in ('id', 'model', 'finish_reason'):
            changed = {**record, 'response_metadata': dict(record['response_metadata'])}
            changed['response_metadata'].pop(field)
            with self.assertRaises(ValueError): diagnostic.validate_reply(changed)
        with self.assertRaises(ValueError): diagnostic.validate_reply({**record, 'usage': None})

    def test_unauthorized_run_never_reads_credentials_or_constructs_client(self):
        with patch.object(diagnostic, 'JsonCandidateTransport', side_effect=AssertionError('NO CLIENT')):
            with self.assertRaises(BudgetStop): diagnostic.run_real(self.path, Path('/not/read'))
        self.assertFalse((self.path/'requests').exists())

    def test_template_and_wrong_protocol_approval_do_not_authorize(self):
        for auth in (diagnostic.approval(self.path, approved=False),
                     {**diagnostic.approval(self.path, approved=True), 'protocol_sha256': '0'*64}):
            (self.path/'Authorization.json').write_text(json.dumps(auth))
            with self.assertRaises(BudgetStop): diagnostic.run_real(self.path, None)

    def test_unknown_sent_restart_preserves_count_and_stops_without_resend(self):
        inner = Inner(self.config, [KeyboardInterrupt('UNIT unknown sent')])
        with self.assertRaises(KeyboardInterrupt):
            diagnostic.session(self.path, self.config, WireRecorder(inner, self.path/'wire_responses'), provenance='mock-only')
        result, later = self.session()
        self.assertEqual(result['phase'], 'stopped'); self.assertEqual(len(later.sent), 0)
        self.assertEqual(diagnostic.status(self.path)['api_attempts'], 1)
        self.assertEqual(diagnostic.read(self.path/'requests/attempts.json')['halt_reason'], 'uncertain_dispatch_requires_review')

    def test_reserved_before_wire_restart_does_not_refund_or_send(self):
        inner = Inner(self.config); transport = WireRecorder(inner, self.path/'wire_responses')
        with patch.object(transport, 'dispatch', side_effect=KeyboardInterrupt('UNIT before wire')):
            with self.assertRaises(KeyboardInterrupt):
                diagnostic.session(self.path, self.config, transport, provenance='mock-only')
        result, later = self.session()
        self.assertEqual(result['phase'], 'stopped'); self.assertEqual(len(inner.sent)+len(later.sent), 0)
        self.assertEqual(diagnostic.status(self.path)['api_attempts'], 1)

    def test_saved_wire_recovered_and_only_unstarted_second_task_sent(self):
        from fjsp_usage.research_real.attempt_budget import AttemptJournal
        inner = Inner(self.config); transport = WireRecorder(inner, self.path/'wire_responses')
        with patch.object(AttemptJournal, '_accept', side_effect=KeyboardInterrupt('UNIT after wire saved')):
            with self.assertRaises(KeyboardInterrupt):
                diagnostic.session(self.path, self.config, transport, provenance='mock-only')
        result, later = self.session()
        self.assertEqual(result['phase'], 'completed')
        self.assertEqual((len(inner.sent), len(later.sent)), (1, 1))
        self.assertIn('000001', later.sent[0][0])
        self.assertEqual(diagnostic.status(self.path)['api_attempts'], 2)

    def test_completed_run_never_resends(self):
        self.session(); again, later = self.session()
        self.assertEqual(again['phase'], 'completed'); self.assertEqual(len(later.sent), 0)

    def test_missing_budget_is_not_recreated(self):
        self.session(); (self.path/'requests/attempts.json').unlink()
        with self.assertRaisesRegex(ValueError, 'missing diagnostic budget'): self.session()

    def test_orphan_budget_is_not_restarted(self):
        self.session(); (self.path/'Diagnostic_checkpoint.json').unlink()
        with self.assertRaisesRegex(ValueError, 'orphan diagnostic budget'): self.session()

    def test_mock_cannot_resume_as_real(self):
        self.session()
        (self.path/'Authorization.json').write_text(json.dumps(diagnostic.approval(self.path, approved=True)))
        config = replace(self.config, real_requests_authorized=True)
        with self.assertRaises(ValueError):
            diagnostic.session(self.path, config, WireRecorder(Inner(config), self.path/'wire_responses'), provenance='real')

    def test_symlink_to_old_state_and_old_directory_are_rejected_before_reads(self):
        (self.path/'requests').symlink_to(diagnostic.SOURCE, target_is_directory=True)
        with self.assertRaises(ValueError): diagnostic.check(self.path)
        with self.assertRaises(ValueError): diagnostic.directory_path(diagnostic.SOURCE)
        with self.assertRaises(ValueError): diagnostic.directory_path(diagnostic.SOURCE/'t1-d1-invalid')

    def test_frozen_prompt_and_configuration_changes_are_rejected(self):
        original = (self.path/'Prompt.txt').read_bytes(); (self.path/'Prompt.txt').write_bytes(original+b'changed')
        with self.assertRaises(ValueError): diagnostic.check(self.path)
        (self.path/'Prompt.txt').write_bytes(original)
        config = diagnostic.read(self.path/'config.pending.json'); config['provider']['model'] = 'gpt-5.6-sol'
        (self.path/'config.pending.json').write_text(json.dumps(config))
        with self.assertRaises(ValueError): diagnostic.check(self.path)

    def test_protocol_cannot_be_copied_to_reset_batch_budget(self):
        other = Path(self.tmp.name)/'t1-d1-copied'
        shutil.copytree(self.path, other)
        with self.assertRaisesRegex(ValueError, 'frozen identity'): diagnostic.check(other)

    def test_environment_model_names_do_not_override_frozen_provider(self):
        with patch.dict('os.environ', {'MODEL': 'gpt-5.6-sol', 'OPENAI_MODEL': 'other'}):
            _, config = diagnostic.check(self.path)
            self.assertEqual(config.provider.model, 'gpt-6.1-sol')
            self.assertEqual(config.provider.max_output_tokens, 8192)
            self.assertIsNone(config.provider.temperature); self.assertIsNone(config.provider.reasoning_effort)

    def test_actual_payload_builder_receives_frozen_generation_parameters(self):
        messages, payloads = [], []
        class Pipe:
            def close(self): pass
            def poll(self, _): return bool(messages)
            def recv(self): return messages.pop(0)
        class Process:
            def __init__(self, target, args): payloads.append(args[2])
            def start(self):
                reply = decode_stream(Response(wire(mock_stream())), self_provider)
                messages.extend([{'kind': 'sent'}, {'kind': 'reply', **reply}])
            def join(self, **kwargs): pass
            def is_alive(self): return False
        class Context:
            def Process(self, target, args): return Process(target, args)
            def Pipe(self, **kwargs): return Pipe(), Pipe()
        self_provider = self.config.provider
        config = replace(self.config, real_requests_authorized=True)
        with patch.dict('os.environ', {'LEAFAPI_API_KEY': 'UNIT-MOCK-ONLY'}), \
                patch('fjsp_usage.research_real.real_transport.mp.get_context', return_value=Context()):
            transport = JsonCandidateTransport(config)
            transport.dispatch('UNIT', (self.path/'Prompt.txt').read_text())
        payload = payloads[0]
        self.assertEqual(payload['model'], 'gpt-6.1-sol'); self.assertEqual(payload['max_completion_tokens'], 8192)
        self.assertTrue(payload['stream']); self.assertEqual(payload['stream_options'], {'include_usage': True})
        self.assertNotIn('temperature', payload); self.assertNotIn('reasoning_effort', payload)
        self.assertNotIn('UNIT-MOCK-ONLY', json.dumps(payload))
