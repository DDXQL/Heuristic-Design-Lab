"""Shared single-ID transport protections; no queries occur at construction."""
import hashlib
import json
from pathlib import Path
import time
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from .budget import BudgetStop

VERSION='single-ID-nonsemantic-recording-settlement-amendment-v1-20261014'


class InvoiceQueryPacer:
    """Serialize read-only invoice GETs, including across process restarts."""
    def __init__(self,query,path,interval,*,clock=time.time,sleep=time.sleep,initial=0):
        self.query,self.path,self.interval,self.clock,self.sleep=query,Path(path),interval,clock,sleep
        self.last=json.loads(self.path.read_text())['last_finished_at'] if self.path.exists() else initial

    def __call__(self):
        delay=self.interval-(self.clock()-self.last)
        while delay>0:
            self.sleep(min(delay,1));delay=self.interval-(self.clock()-self.last)
        try:return self.query()
        finally:
            self.last=self.clock();atomic_json(self.path,{'last_finished_at':self.last,
                'interval':self.interval,'scope':'metadata GET /api/log/token only','inference_requests':0})


class MetadataPacer:
    """Local conservative throttle, NOT a claimed supplier limit or retry."""
    def __init__(self,path,interval=15,*,clock=time.time,sleep=time.sleep):
        self.path,self.interval,self.clock,self.sleep=Path(path),interval,clock,sleep
        self.last=json.loads(self.path.read_text())['last_finished_at'] if self.path.exists() else 0

    def call(self,path,query):
        if path not in ('/api/usage/token/','/api/log/token','/api/pricing','/api/status','/v1/models'):
            raise ValueError('read-only metadata paths only; never inference POST')
        delay=self.interval-(self.clock()-self.last)
        while delay>0:
            self.sleep(min(delay,1));delay=self.interval-(self.clock()-self.last)
        try:return query()
        finally:
            self.last=self.clock();atomic_json(self.path,{'last_finished_at':self.last,'interval':self.interval,
                'last_path':path,'inference_requests':0,'supplier_rate_limit_known':False})


class ProtectedInvoice:
    """Stop after one unsent pre-dispatch failure, before the next slot."""
    def __init__(self,inner,quota):
        self.inner,self.quota,self.identity,self.redact=inner,quota,inner.identity,inner.redact

    def preflight(self,prompt):return self.inner.preflight(prompt)

    def dispatch(self,key,prompt,**kwargs):
        try:return self.inner.dispatch(key,prompt,**kwargs)
        except BudgetStop as exc:
            path=self.inner.directory/(hashlib.sha256(key.encode()).hexdigest()+'.json')
            if str(exc)=='cannot inspect supplier billing before dispatch' and path.exists():
                audit=json.loads(path.read_text())
                if audit['status']=='before_dispatch' and audit['before'].get('success') is not True and key not in self.quota.data['records']:
                    self.quota.halt('before-dispatch supplier invoice metadata unavailable; no inference sent')
            raise


class WireRecorder:
    def __init__(self,inner,directory,verify=lambda:None):
        self.inner,self.directory,self.verify=inner,Path(directory),verify
        self.config,self.identity,self.secret,self.redact=inner.config,inner.identity,inner.secret,inner.redact
        self.directory.mkdir(exist_ok=True)

    def preflight(self,prompt):self.verify();return self.inner.preflight(prompt)

    def dispatch(self,key,prompt,*,kind='U',on_sent=lambda:None):
        self.verify()
        path=self.directory/(hashlib.sha256(key.encode()).hexdigest()+'.json')
        if path.exists():raise BudgetStop('wire recorder forbids request identity replay')
        record={'version':VERSION,'global_key':key,'prompt_key':digest({'prompt':prompt,'kind':kind}),
            'transport_identity':self.identity,'status':'pending','send_confirmed':False}
        atomic_json(path,record)
        def sent():record.update(send_confirmed=True);atomic_json(path,record);on_sent()
        try:
            reply=self.inner.dispatch(key,prompt,kind=kind,on_sent=sent)
            record.update(status='wire_completed_before_settlement',reply=reply)
            atomic_json(path,record)
            return reply
        except Exception as exc:
            record.update(status='wire_failed',error=self.redact(str(exc))[:500],
                usage=getattr(exc,'usage',None),metadata=getattr(exc,'metadata',{}) or {})
            atomic_json(path,record);raise


def install_protections(invoice, quota, directory, verify, *, metadata_floor=0,
                        invoice_floor=0, clock=time.time, sleep=time.sleep):
    """Wrap before the FIRST request; floors inherit the last caller's pacing.

    This function only installs callbacks. All network reads remain inside the
    caller's explicitly authorized preflight/dispatch, never offline prepare.
    """
    from .model_migration import check_live_tariff, public_json
    directory = Path(directory)
    metadata_path = directory/'Metadata_global_pacing.json'
    if not metadata_path.exists():
        atomic_json(metadata_path, {'last_finished_at': metadata_floor, 'interval': 15})
    metadata = MetadataPacer(metadata_path, clock=clock, sleep=sleep)
    quota_query, invoice_query = quota.query, invoice.query
    quota.query = lambda: metadata.call('/api/usage/token/', quota_query)
    def public_query(secret, path, **kwargs):
        return metadata.call(path, lambda: public_json(secret, path, **kwargs))
    quota.tariff_query = lambda secret: check_live_tariff(secret, query=public_query)
    pacer = InvoiceQueryPacer(lambda: metadata.call('/api/log/token', invoice_query),
        directory/'Invoice_query_pacing.json', quota.config.platform_quota_query_interval,
        clock=clock, sleep=sleep, initial=invoice_floor)
    invoice.query = quota.invoice_query = pacer
    quota.transport = WireRecorder(quota.transport, directory/'wire_responses', verify)
    return ProtectedInvoice(invoice, quota)
