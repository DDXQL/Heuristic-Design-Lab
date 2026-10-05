"""Loopback-only HTTP faults and handwritten responses; never a real LLM."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

from fjsp_usage.research.candidates import H_ARGS, U_ARGS


def fixture_response(payload, index):
    kind = payload['kind']
    if kind == 'h':
        code = 'def priority(' + ', '.join(H_ARGS) + '):\n    return -earliest_finish + ' + str(index/100) + ' * processing_time'
    else:
        code = ('def select_heuristic(' + ', '.join(U_ARGS) + '):\n    if progress < '
                + str(index/10000) + ':\n        return 0\n    else:\n        return 1')
    return {'text': '{Handwritten local HTTP acceptance fixture.}\n```python\n' + code + '\n```',
            'usage': {'input_tokens': 64, 'output_tokens': 48}, 'finish_reason': 'stop'}


@contextmanager
def fixture_server(*, script=(), responder=fixture_response, port=0):
    """script: per-request status, delay, malformed, truncated, missing_usage, drip."""
    state = {'requests': [], 'lock': threading.Lock()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                with state['lock']:
                    state['requests'].append(payload)
                    index = len(state['requests'])
                option = script[index-1] if index <= len(script) else {}
                time.sleep(option.get('delay', 0))
                response = responder(payload, index)
                if option.get('missing_usage'):
                    response.pop('usage', None)
                if option.get('truncated'):
                    response['finish_reason'] = 'length'
                body = b'not-json' if option.get('malformed') else json.dumps(response).encode()
                self.send_response(option.get('status', 200))
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                if option.get('drip'):
                    for char in body:
                        self.wfile.write(bytes([char]))
                        self.wfile.flush()
                        time.sleep(option['drip'])
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port) + '/candidate', state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
