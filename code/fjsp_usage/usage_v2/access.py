"""Small transport protections for the registered pilot; no candidate changes."""
import hashlib
import json
from pathlib import Path
import time
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.real_transport import redact_diagnostic


class MetadataPacer:
    def __init__(self, path, interval=15, *, clock=time.time, sleep=time.sleep):
        self.path, self.interval, self.clock, self.sleep = Path(path), interval, clock, sleep
        self.last = json.loads(self.path.read_text())['last_finished_at'] if self.path.exists() else 0

    def call(self, path, query):
        if path not in ('/api/usage/token/', '/api/log/token', '/api/pricing', '/api/status', '/v1/models'):
            raise ValueError('read-only metadata paths only')
        while self.clock() - self.last < self.interval:
            self.sleep(min(1, self.interval - (self.clock() - self.last)))
        try: return query()
        finally:
            self.last = self.clock()
            atomic_json(self.path, {'last_finished_at': self.last, 'last_path': path,
                                   'interval': self.interval, 'inference_requests': 0})


class InvoicePacer:
    def __init__(self, query, path, metadata, *, interval=75, clock=time.time, sleep=time.sleep):
        self.query, self.path, self.metadata = query, Path(path), metadata
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.last = json.loads(self.path.read_text())['last_finished_at'] if self.path.exists() else 0

    def __call__(self):
        while self.clock() - self.last < self.interval:
            self.sleep(min(1, self.interval - (self.clock() - self.last)))
        try: return self.metadata.call('/api/log/token', self.query)
        finally:
            self.last = self.clock()
            atomic_json(self.path, {'last_finished_at': self.last, 'interval': self.interval, 'inference_requests': 0})


class WireRecorder:
    """Commit the complete normalized reply before quota/invoice GETs happen."""
    def __init__(self, inner, directory, verify=None):
        self.inner, self.directory = inner, Path(directory)
        self.verify = verify
        self.config, self.identity, self.secret = inner.config, inner.identity, inner.secret
        self.redact = lambda text: redact_diagnostic(inner.redact(text), self.secret)
        self.directory.mkdir(exist_ok=True)

    def preflight(self, prompt):
        if self.verify is not None: self.verify()
        return self.inner.preflight(prompt)

    def dispatch(self, key, prompt, *, kind='U', on_sent=lambda:None):
        if self.verify is not None: self.verify()
        path = self.directory / (hashlib.sha256(key.encode()).hexdigest() + '.json')
        if path.exists(): raise BudgetStop('wire recorder forbids sent or uncertain request replay')
        record = {'global_key': key, 'prompt_key': digest({'prompt':prompt, 'kind':kind}),
                  'status':'pending', 'send_confirmed':False}
        atomic_json(path, record)
        def sent():
            record['send_confirmed'] = True; atomic_json(path, record); on_sent()
        try:
            reply = self.inner.dispatch(key, prompt, kind=kind, on_sent=sent)
            record.update(status='wire_completed_before_settlement', reply=reply)
            atomic_json(path, record)
            return reply
        except BaseException as exc:
            # An interrupt immediately after atomic commit must not downgrade
            # the first durable response and make recovery request it again.
            persisted = json.loads(path.read_text())
            if (persisted.get('status') == 'wire_completed_before_settlement'
                    and persisted.get('global_key') == key
                    and persisted.get('prompt_key') == record['prompt_key']):
                raise
            record.update(status='wire_failed' if isinstance(exc, Exception) else 'interrupted_unknown',
                          error=redact_diagnostic(self.redact(str(exc)), self.secret)[:500],
                          error_type=type(exc).__name__,
                          usage=getattr(exc,'usage',None),
                          metadata=redact_diagnostic(getattr(exc,'metadata',{}) or {}, self.secret))
            exc.metadata = record['metadata']
            atomic_json(path, record); raise
