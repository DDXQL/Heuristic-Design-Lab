import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real import real_transport
from tools import t1_d3b_api_diagnostic as d3b


class FakeTransport:
    def __init__(self, config, directory, outcome, calls):
        self.config = config
        self.directory = Path(directory)
        self.identity = digest({'mock_provider': config.payload()['provider']})
        self.secret = ''
        self.outcome = outcome
        self.calls = calls

    @staticmethod
    def redact(text):
        return text

    def preflight(self, prompt):
        if prompt != d3b.PROMPT:
            raise AssertionError('unexpected prompt')

    def dispatch(self, key, prompt, *, kind='U', on_sent=lambda: None):
        self.calls.append({'stream': self.config.provider.stream_response,
                           'key': key, 'prompt': prompt, 'kind': kind})
        if self.outcome.get('sent', True):
            on_sent()
        if self.outcome.get('interrupt'):
            raise KeyboardInterrupt('mock interruption')
        if self.outcome.get('error'):
            exc = RuntimeError(self.outcome['error'])
            exc.metadata = dict(self.outcome.get('metadata', {}))
            raise exc
        return {
            'text': self.outcome.get('text', 'OK'),
            'usage': self.outcome.get('usage', {'input_tokens': 12, 'output_tokens': 1}),
            'metadata': dict(self.outcome.get('metadata', {'http_status': 200,
                                                            'gateway_request_id': 'mock-gateway',
                                                            'finish_reason': 'stop'})),
        }


class T1D3BTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / 'run'
        self.directory.mkdir()
        raw = d3b.canonical_json(d3b.build_protocol())
        (self.directory / 'Protocol.json').write_bytes(raw)
        (self.directory / 'Protocol.sha256').write_text(d3b.sha256_bytes(raw) + '\n')

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, outcomes):
        calls = []

        def factory(config, wire_dir):
            group = 'B' if config.provider.stream_response else 'A'
            return FakeTransport(config, wire_dir, outcomes[group], calls)

        return calls, factory

    def test_two_successes_share_prompt_and_differ_only_by_stream(self):
        calls, factory = self.runner({'A': {}, 'B': {}})
        result = d3b.run_groups(self.directory, factory)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(calls), 2)
        self.assertEqual([c['stream'] for c in calls], [False, True])
        self.assertEqual([c['prompt'] for c in calls], [d3b.PROMPT, d3b.PROMPT])
        self.assertEqual([c['kind'] for c in calls], ['diagnostic', 'diagnostic'])
        for group in ('A', 'B'):
            row = result['groups'][group]
            self.assertTrue(row['complete_response'])
            self.assertEqual(row['response_text'], 'OK')
            self.assertEqual(row['finish_reason'], 'stop')
            self.assertEqual(row['usage']['output_tokens'], 1)

    def test_id_mismatch_is_group_failure_and_allows_b(self):
        ordinary = {
            'error': 'stream identity/model changed',
            'metadata': {'http_status': 200, 'model': d3b.MODEL,
                         'failure_class': 'protocol_incompatible',
                         'identity_change': {'field': 'id'},
                         'stream_protocol_anomaly': True},
        }
        calls, factory = self.runner({'A': ordinary, 'B': {}})
        result = d3b.run_groups(self.directory, factory)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['groups']['A']['status'], 'failed')
        self.assertIsNone(result['groups']['A']['global_stop'])
        self.assertEqual(result['groups']['B']['status'], 'completed')

    def test_a_success_then_b_stream_protocol_failure_finishes_without_retry(self):
        bad_stream = {'error': 'stream identity/model changed',
                      'metadata': {'http_status': 200, 'model': d3b.MODEL,
                                   'failure_class': 'protocol_incompatible',
                                   'identity_change': {'field': 'id'},
                                   'stream_protocol_anomaly': True}}
        calls, factory = self.runner({'A': {}, 'B': bad_stream})
        result = d3b.run_groups(self.directory, factory)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['groups']['A']['status'], 'completed')
        self.assertEqual(result['groups']['B']['status'], 'failed')
        journals = [json.loads((self.directory / 'requests' / group / 'attempts.json').read_text())
                    for group in ('A', 'B')]
        self.assertEqual([len(j['api_attempts']) for j in journals], [1, 1])

    def test_illegal_http_200_frame_is_not_retried_and_b_proceeds(self):
        invalid = {'error': 'invalid/error stream chunk',
                   'metadata': {'http_status': 200, 'model': d3b.MODEL,
                                'failure_class': 'protocol_incompatible',
                                'stream_protocol_anomaly': True}}
        calls, factory = self.runner({'A': invalid, 'B': {}})
        result = d3b.run_groups(self.directory, factory)
        self.assertEqual(len(calls), 2)
        self.assertEqual([c['stream'] for c in calls], [False, True])
        self.assertEqual(result['groups']['A']['status'], 'failed')
        self.assertEqual(result['groups']['B']['status'], 'completed')
        attempts = [json.loads((self.directory / 'requests' / group / 'attempts.json').read_text())
                    for group in ('A', 'B')]
        self.assertEqual([len(j['api_attempts']) for j in attempts], [1, 1])

    def test_auth_quota_and_model_identity_errors_stop_b(self):
        cases = [
            {'http_status': 401},
            {'http_status': 402},
            {'http_status': 429},
            {'http_status': 200, 'model': 'unexpected-model',
             'failure_class': 'permanent'},
            {'http_status': 200, 'model': d3b.MODEL,
             'identity_change': {'field': 'model'}},
        ]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                with tempfile.TemporaryDirectory() as temp:
                    directory = Path(temp) / 'run'
                    directory.mkdir()
                    raw = d3b.canonical_json(d3b.build_protocol())
                    (directory / 'Protocol.json').write_bytes(raw)
                    (directory / 'Protocol.sha256').write_text(d3b.sha256_bytes(raw) + '\n')
                    calls, factory = self.runner({'A': {'error': 'mock global error',
                                                         'metadata': metadata}, 'B': {}})
                    result = d3b.run_groups(directory, factory)
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(result['status'], 'stopped')
                    self.assertNotIn('B', result['groups'])

    def test_unconfirmed_send_stops_b(self):
        calls, factory = self.runner({'A': {'error': 'mock uncertain send', 'sent': False,
                                             'metadata': {'http_status': 200}}, 'B': {}})
        result = d3b.run_groups(self.directory, factory)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['global_stop_reason'], 'send_state_unknown_or_unconfirmed')

    def test_repeat_resume_does_not_repeat_completed_requests(self):
        calls, factory = self.runner({'A': {}, 'B': {}})
        first = d3b.run_groups(self.directory, factory)
        second = d3b.run_groups(self.directory, factory)
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(second['status'], 'completed')
        self.assertEqual(len(calls), 2)

    def test_interrupted_send_is_recovered_without_replay(self):
        calls, first_factory = self.runner({'A': {'interrupt': True}, 'B': {}})
        with self.assertRaises(KeyboardInterrupt):
            d3b.run_groups(self.directory, first_factory)
        _, resume_factory = self.runner({'A': {}, 'B': {}})
        result = d3b.run_groups(self.directory, resume_factory)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['status'], 'stopped')
        self.assertNotIn('B', result['groups'])
        self.assertIn('A', result['groups'])

    def test_configs_change_only_stream_fields(self):
        a = d3b.make_config(False, authorized=True).payload()['provider']
        b = d3b.make_config(True, authorized=True).payload()['provider']
        self.assertEqual({k: v for k, v in a.items() if k != 'stream_response'},
                         {k: v for k, v in b.items() if k != 'stream_response'})
        self.assertEqual(a['max_output_tokens'], 128)
        self.assertIsNone(a['temperature'])
        self.assertIsNone(a['reasoning_effort'])

    def test_public_transport_builds_a_b_requests_with_only_stream_delta(self):
        sent_requests = []

        class Sock:
            def settimeout(self, _):
                pass

        class Response:
            status = 200
            change_id = False

            def __init__(self, stream):
                self.headers = {'Content-Type': 'text/event-stream' if stream else 'application/json',
                                'x-oneapi-request-id': 'mock-gateway-id'}
                if stream:
                    frames = [
                        {'id': 'mock-response-id', 'model': d3b.MODEL,
                         'choices': [{'index': 0, 'delta': {'role': 'assistant'}}]},
                        {'id': 'mock-response-id', 'model': d3b.MODEL,
                         'choices': [{'index': 0, 'delta': {'content': 'OK'}}]},
                        {'id': 'mock-response-id', 'model': d3b.MODEL,
                         'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]},
                        {'id': 'mock-response-id', 'model': d3b.MODEL,
                         'choices': [], 'usage': {'prompt_tokens': 12, 'completion_tokens': 1}},
                    ]
                    if self.change_id:
                        frames[2]['id'] = 'changed-mock-response-id'
                    self.body = b''.join(b'data: ' + json.dumps(row).encode() + b'\n\n'
                                         for row in frames) + b'data: [DONE]\n\n'
                else:
                    self.body = json.dumps({
                        'id': 'mock-response-id', 'model': d3b.MODEL,
                        'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}],
                        'usage': {'prompt_tokens': 12, 'completion_tokens': 1},
                    }).encode()
                self.read1_used = False

            def getheader(self, name, default=None):
                return self.headers.get(name, default)

            def read(self, _):
                return self.body

            def read1(self, _):
                if self.read1_used:
                    return b''
                self.read1_used = True
                return self.body

        class Connection:
            def __init__(self, *_args, **_kwargs):
                self.sock = Sock()
                self.response = None

            def connect(self):
                pass

            def request(self, method, path, *, body, headers):
                request = json.loads(body)
                sent_requests.append((method, path, request, dict(headers)))
                self.response = Response(request['stream'])

            def getresponse(self):
                return self.response

            def close(self):
                pass

        class Pipe:
            def __init__(self, queue):
                self.queue = queue

            def send(self, value):
                self.queue.append(value)

            def close(self):
                pass

        class Receive(Pipe):
            def poll(self, _timeout):
                return bool(self.queue)

            def recv(self):
                return self.queue.pop(0)

        class Process:
            def __init__(self, target, args):
                self.target, self.args = target, args

            def start(self):
                self.target(*self.args)

            def join(self, timeout=None):
                pass

            @staticmethod
            def is_alive():
                return False

        class Context:
            @staticmethod
            def Pipe(duplex=False):
                queue = []
                return Receive(queue), Pipe(queue)

            @staticmethod
            def Process(target, args):
                return Process(target, args)

        replies = []
        with patch.dict(os.environ, {'LEAFAPI_API_KEY': 'offline-mock-only'}), \
             patch.object(real_transport.mp, 'get_context', return_value=Context()), \
             patch.object(real_transport.http.client, 'HTTPSConnection', Connection):
            for streaming in (False, True):
                config = d3b.make_config(streaming, authorized=True)
                client = real_transport.JsonCandidateTransport(config)
                replies.append(client.dispatch('mock-key', d3b.PROMPT,
                                               on_sent=lambda: None))
            Response.change_id = True
            stream_client = real_transport.JsonCandidateTransport(d3b.make_config(True, authorized=True))
            with self.assertRaises(real_transport.TransportError) as caught:
                stream_client.dispatch('mock-id-mismatch', d3b.PROMPT)

        self.assertEqual([row[0:2] for row in sent_requests],
                         [('POST', '/v1/chat/completions'), ('POST', '/v1/chat/completions'),
                          ('POST', '/v1/chat/completions')])
        a, b = (row[2] for row in sent_requests[:2])
        self.assertEqual({k: v for k, v in a.items() if k not in ('stream', 'stream_options')},
                         {k: v for k, v in b.items() if k not in ('stream', 'stream_options')})
        self.assertIs(a['stream'], False)
        self.assertNotIn('stream_options', a)
        self.assertIs(b['stream'], True)
        self.assertEqual(b['stream_options'], {'include_usage': True})
        self.assertEqual(sent_requests[0][3]['Content-Type'], 'application/json')
        self.assertTrue(sent_requests[0][3]['Authorization'].startswith('Bearer '))
        self.assertEqual([reply['text'] for reply in replies], ['OK', 'OK'])
        self.assertEqual([reply['metadata']['finish_reason'] for reply in replies], ['stop', 'stop'])
        self.assertTrue(all(reply['metadata']['gateway_request_id'] == 'mock-gateway-id'
                            for reply in replies))
        self.assertEqual(caught.exception.metadata['identity_change']['field'], 'id')
        self.assertTrue(caught.exception.metadata['stream_observation']['model_matches_expected'])


if __name__ == '__main__':
    unittest.main()
