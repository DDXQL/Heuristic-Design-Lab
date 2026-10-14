"""v2.2 supplier invoices; no inference retry and no invented usage.

Invoice/account reconciliation is separate from response token accounting.
Only a unique new receipt, matching model/window/debit, can settle a failed send.
"""
from copy import deepcopy
import hashlib
import http.client
import json
from pathlib import Path
import time
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research.events import atomic_json

VERSION = 'v22-supplier-settlement-v1-20261013'


def certified_reconciliation(key, quota_record, reconciliations, docs, run, model):
    """A pinned invoice resolves account hold, never invents response tokens."""
    matches = [r for r in reconciliations if r.get('global_key') == key]
    if len(matches) != 1:
        return None
    reconciliation = matches[0]
    name = reconciliation.get('proof_file', '')
    if not name or Path(name).name != name:
        raise ValueError('invoice proof must be a pinned billing filename')
    proof = docs.get(run + '/billing/' + name)
    if (not proof or proof.get('global_key') != key or proof.get('status') != 'invoice_account_matched'
            or proof.get('wire_usage') is not None or proof.get('transport_status') != 'failed'
            or proof.get('original_quota_record') != reconciliation.get('original_quota_record')):
        raise ValueError('settled unknown-wire request lacks pinned failed-send invoice proof')
    original = reconciliation['original_quota_record']
    if original.get('send_confirmed') is not True:
        raise ValueError('invoice proof is not a confirmed sent request')
    if quota_record != original:
        raise ValueError('settled invoice original quota record changed')
    invoice = match_invoice(proof['before'], proof['after'], original, model, failed=True)
    if invoice != proof.get('invoice') or invoice != reconciliation.get('invoice'):
        raise ValueError('invoice reconciliation differs from independently matched receipt')
    return invoice


def query_invoices(secret):
    result = {'version':VERSION,'inference_requests':0,'metadata_requests':1,
              'observed_at':time.time(),'path':'/api/log/token','success':False,'records':[]}
    connection = http.client.HTTPSConnection('leafapi.cc', timeout=15)
    try:
        connection.request('GET','/api/log/token',headers={'Authorization':'Bearer '+secret,'Accept':'application/json'})
        response = connection.getresponse();result['http_status']=response.status
        raw=response.read(524289)
        if response.status != 200 or len(raw)>524288:return result
        body=json.loads(raw);data=body.get('data',[])
        if isinstance(data,dict):data=data.get('items',data.get('data',data.get('logs',[])))
        if not isinstance(data,list) or body.get('success',body.get('code')) is not True:return result
        fields=('id','created_at','type','model_name','quota','prompt_tokens','completion_tokens','use_time','request_id')
        for row in data:
            if not isinstance(row,dict):raise ValueError('invalid invoice row')
            result['records'].append({k:(row[k].replace(secret,'[REDACTED]') if isinstance(row[k],str) else row[k])
                for k in fields if k in row and type(row[k]) in (str,int,float,bool)})
        result['success']=True
    except Exception as exc:
        result['error_type']=type(exc).__name__  # never emit server text/credentials
    finally:connection.close()
    return result


def match_invoice(before, after, account, model, *, failed, response_id=None):
    if before.get('success') is not True or after.get('success') is not True:
        raise BudgetStop('supplier billing metadata unavailable; no settlement inferred')
    seen={row.get('request_id') for row in before['records'] if row.get('request_id')}
    candidates=[]
    for row in after['records']:
        identifier=row.get('request_id');created=row.get('created_at')
        if (not identifier or identifier in seen or row.get('model_name')!=model
                or row.get('type') not in ((2,5) if failed else (2,))
                or type(row.get('quota')) is not int or row['quota']<0
                or type(created) not in (int,float)
                or not account['started_at']-2 <= created <= account['finished_at']+30):continue
        if response_id is not None and identifier != response_id:continue
        candidates.append(row)
    if len(candidates)!=1:raise BudgetStop('no unique supplier receipt matching new request/model/window')
    row=candidates[0]
    if (account.get('status')!='settled' or account.get('observed_account_delta')!=row['quota']
            or account.get('after_used',-1)<account['before_used']+row['quota']):
        raise BudgetStop('supplier invoice/account debit mismatch; preserve reservation')
    return row


class InvoiceTransport:
    """Wrap existing quota guard, preserving all historical holds and caps."""
    def __init__(self, inner, directory, *, query=None):
        self.inner,self.directory,self.identity=inner,Path(directory),inner.identity
        self.redact=inner.redact
        self.query=query or (lambda:query_invoices(inner.transport.secret))
        self.directory.mkdir(exist_ok=True)

    def preflight(self,prompt):return self.inner.preflight(prompt)

    def dispatch(self,key,prompt,*,kind='U',on_sent=lambda:None):
        if kind!='U':raise BudgetStop('v2.2 research invoice adapter permits U only')
        name=hashlib.sha256(key.encode()).hexdigest();path=self.directory/(name+'.json')
        if path.exists():raise BudgetStop('billing adapter forbids replay of request identity')
        before=self.query()
        audit={'version':VERSION,'global_key':key,'before':before,'wire_usage':None,
               'actual_platform_units':None,'status':'before_dispatch'}
        atomic_json(path,audit)
        if before.get('success') is not True:raise BudgetStop('cannot inspect supplier billing before dispatch')
        print('真实请求开始 '+key,flush=True)
        reply,error=None,None
        try:reply=self.inner.dispatch(key,prompt,kind=kind,on_sent=on_sent)
        except Exception as exc:error=exc
        account=deepcopy(self.inner.data['records'].get(key))
        usage=getattr(error,'usage',None) if error else reply.get('usage')
        audit.update(after=self.query(),original_quota_record=account,wire_usage=usage,
                     transport_status='failed' if error else 'completed')
        try:
            if not account or not account.get('send_confirmed'):raise BudgetStop('request not confirmed sent; preserve slot and do not retry')
            # Gateway headers identify the supplier invoice; the chat completion
            # id is a different identifier. Preserve both and require a gateway
            # match when that header is available.
            metadata=(getattr(error,'metadata',{}) or {}) if error else reply.get('metadata',{})
            audit['response_metadata']=metadata
            invoice=match_invoice(before,audit['after'],account,self.inner.config.provider.model,
                failed=error is not None,response_id=metadata.get('gateway_request_id'))
            audit.update(status='invoice_account_matched',invoice=invoice,actual_platform_units=invoice['quota'])
            if self.inner.data['halted']:
                reason=self.inner.data.get('stop_reason')
                if reason!='unknown usage or possibly delayed account charge; manual investigation required':
                    raise BudgetStop('quota guard halted for another reason; invoice cannot override it')
                # A successful response with unknown token usage remains blocked.
                if error is None and usage is None:raise BudgetStop('successful response has unknown usage; preserve reservation')
                self.inner.data.setdefault('invoice_reconciliations',[]).append({
                    'global_key':key,'original_quota_record':account,'original_stop_reason':reason,
                    'invoice':invoice,'proof_file':path.name,'wire_usage_still_unknown':usage is None})
                self.inner.data.update(halted=False,stop_reason=None)
                self.inner.save()
            elif error is not None and usage is None:
                raise BudgetStop('unknown wire failure was not safely reconciled')
        except BudgetStop as exc:
            audit.update(status='settlement_not_certified',settlement_error=str(exc))
            self.inner.halt(str(exc))
            if error is None:
                exc.usage=usage;exc.metadata=(reply or {}).get('metadata',{})
                error=exc
        atomic_json(path,audit)
        print('真实请求结束 '+key+'；'+audit['status']+'；平台单位='+str(audit['actual_platform_units'])+'；usage='+str(usage),flush=True)
        if error is not None:
            error.metadata={**(getattr(error,'metadata',{}) or {}),'billing_file':str(path),
                            'actual_platform_units':audit['actual_platform_units'],
                            'billing_certified':audit['status']=='invoice_account_matched'}
            raise error
        return {**reply,'metadata':{**reply.get('metadata',{}),'billing_file':str(path),
                'actual_platform_units':audit['actual_platform_units'],'billing_certified':True}}
