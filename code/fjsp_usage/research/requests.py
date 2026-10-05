"""Durable, bounded one-attempt transport journal. No retry/repair policy.

The repository ships ONLY a mock transport. A real provider must report real
usage, provide finite network deadlines, and be explicitly configured later.
"""

import json
from pathlib import Path
import time

from .candidates import U_ARGS, H_ARGS
from .events import atomic_json
from .protocol import digest


class RequestJournal:
    def __init__(self, path, *, cap, transport, identity):
        self.path = Path(path)
        self.cap = cap
        self.transport = transport
        self.identity = identity
        if type(cap) is not int or cap < 1:
            raise ValueError('positive integer request cap required')
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            if self.data['cap'] != cap or self.data['identity'] != identity:
                raise ValueError('cannot resume with changed transport identity or budget')
        else:
            self.data = {'cap': cap, 'identity': identity, 'requests': {}}

    @property
    def calls(self):
        # A pending reservation is conservatively charged, even if a crash
        # occurred before dispatch. Such an uncertain request is never retried.
        return len(self.data['requests'])

    def request(self, key, prompt, *, kind='U'):
        prompt_key = digest({'prompt': prompt, 'kind': kind})
        records = self.data['requests']
        if key in records:
            record = records[key]
            if record['prompt_key'] != prompt_key:
                raise ValueError('request id reused with different prompt')
            if record['status'] == 'pending':
                record.update(status='interrupted', error='uncertain interrupted request; no retry')
                atomic_json(self.path, self.data)
            return record
        if self.calls >= self.cap:
            raise ValueError('hard request budget exhausted')
        record = {'status': 'pending', 'prompt_key': prompt_key, 'prompt': prompt,
                  'kind': kind, 'usage': None, 'started_unix': time.time()}
        records[key] = record
        atomic_json(self.path, self.data)
        started = time.monotonic()
        try:
            reply = self.transport(key, prompt, kind=kind)
            if not isinstance(reply, dict) or not isinstance(reply.get('text'), str):
                raise ValueError('transport must provide text and optional actual usage')
            record.update(status='completed', text=reply['text'], usage=reply.get('usage'))
        except Exception as exc:
            record.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        record['elapsed_seconds'] = time.monotonic() - started
        atomic_json(self.path, self.data)
        return record


class MockTransport:
    """Deterministic handwritten fixture responses, not model generations."""
    identity = 'handwritten-mock-v1'

    def __call__(self, key, prompt, *, kind='U'):
        # Candidate identity derives from the attempt id, not reward or scores.
        parts = key.split('/')
        number = int(parts[-1])
        if parts[-2].startswith('g'):
            number += 10 * (1 + int(parts[-2][1:]))
        if kind == 'U':
            threshold = (number + 1) / 101
            body = f'    return 0 if progress < {threshold!r} else 1'
            description = f'Use member zero before progress {threshold!r}, otherwise member one.'
            code = 'def select_heuristic(' + ', '.join(U_ARGS) + '):\n' + body
        else:
            if number == 0:
                expression = '-earliest_finish'
            elif number == 1:
                expression = '-processing_time'
            else:
                expression = f'-earliest_finish - {number / 101!r} * processing_time'
            description = 'Return ' + expression + ' for one raw action.'
            code = 'def priority(' + ', '.join(H_ARGS) + '):\n    return ' + expression
        return {'text': '{' + description + '}\n```python\n' + code + '\n```', 'usage': None}
