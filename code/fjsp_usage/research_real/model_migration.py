"""Explicit single-model migration, immutable history and rate-bound risk stop.

Reservations are conditional engineering envelopes, NOT supplier hard maxima.
Old unknown holds are never re-priced. New invoices, not public prices, settle fees.
"""
from dataclasses import replace
from decimal import Decimal, ROUND_CEILING
import http.client
import json
import time
from .budget import BudgetStop
from .quota_guard import QuotaGuardedTransport
from .real_transport import JsonCandidateTransport

VERSION='single-ID-leaf-gpt61-migration-v1-20261014'
MODEL='gpt-6.1-sol'
EXPRESSION='len <= 272000 ? tier("0_272k", p * 2 + cr * 0.1 + cc * 2.5 + c * 10) : tier("272k_plus", p * 4 + cr * 0.2 + cc * 5 + c * 15)'
DIAGNOSTIC_PROMPT='Reply with exactly OK. No explanation.'


def validate_migration(config):
    d=config.conditional_research['model_migration']
    if (not isinstance(d,dict) or set(d)!={'version','retired_run','retired_model','new_model',
            'authorization_reviewer','retirement','diagnostic','risk_policy','preflight_run'}
            or d['version']!=VERSION or d['retired_model']!='gpt-5.6-sol' or d['new_model']!=MODEL
            or d['authorization_reviewer']!='DDXQL'
            or d['retirement']!='MODEL_ACCESS_FAILURE_ABORTED_UNUSED_59_AUTHORIZATION_RETIRED'
            or d['diagnostic']!={'cap':1,'max_output_tokens':256,'prompt':DIAGNOSTIC_PROMPT,
                'candidate':False,'retry':False}
            or config.provider.model!=MODEL or config.provider.expected_response_model!=MODEL
            or config.total_request_cap!=61 or config.seeds!=(201,)):
        raise ValueError('explicit gpt61 migration/retirement/one diagnostic and sixty formal slots required')
    policy=d['risk_policy']
    expected={'basis':'conditional-engineering-envelope-not-certified-provider-bound',
        'expression':EXPRESSION,'max_input_rate':5,'max_output_rate':15,'group':'codex-deafult',
        'group_ratio':0.5,'quota_per_unit':500000,'safety_factor':2,'round_to_points':1000,
        'input_envelope_rule':'max(65536,utf8_prompt_bytes+4096)',
        'output_envelope':32768,'max_per_request_points':1000000}
    if policy!=expected or config.platform_quota_reservation!=1000000:
        raise ValueError('pinned model-specific tariff and engineering envelope required')
    if d['retired_run'] not in config.conditional_research['history_batches']:
        raise ValueError('retired real request must remain in cumulative history')


def check_provider_migration(config,old,docs):
    d=config.conditional_research['model_migration']; old_provider=old['config']['provider']
    expected={**old_provider,'model':MODEL,'expected_response_model':MODEL}
    if expected!=config.payload()['provider'] or old_provider['model']!=d['retired_model']:
        raise ValueError('migration permits only model and exact response-model change')
    retired=docs[d['retired_run']+'/protocol.json']
    budget=docs[d['retired_run']+'/budget.json']
    quota=docs[d['retired_run']+'/platform_quota.json']
    if (retired['config']['provider']!=old_provider or len(budget['records'])!=1
            or sum(bool(r.get('send_confirmed')) for r in budget['records'].values())!=1
            or any(r.get('usage') is not None or r.get('status')!='failed' for r in budget['records'].values())
            or any(q.get('reserved')!=12000000 for q in quota['records'].values())):
        raise ValueError('retired access failure/unknown usage/full old hold must be preserved')
    pre=d['preflight_run']
    pricing=docs[pre+'/pricing.json'];status=docs[pre+'/status.json'];models=docs[pre+'/models.json']
    if (models.get('locked_model_listed') is not True or not pricing.get('success')
            or pricing['models'][0].get('billing_expr')!=EXPRESSION
            or pricing['models'][0].get('enable_groups')!=['codex-deafult']
            or pricing['group_ratio'].get('codex-deafult')!=0.5
            or status['public_fields'].get('quota_per_unit')!=500000):
        raise ValueError('new model listing/groups/public tariff identity inconsistent')


def risk_reservation(prompt,policy):
    if not isinstance(prompt,str):raise ValueError('text prompt required')
    inputs=max(65536,len(prompt.encode('utf-8'))+4096)
    raw=(Decimal(inputs)*Decimal(policy['max_input_rate'])+
         Decimal(policy['output_envelope'])*Decimal(policy['max_output_rate']))
    raw=raw*Decimal(str(policy['group_ratio']))*Decimal(policy['quota_per_unit'])/Decimal(1000000)
    padded=raw*Decimal(str(policy['safety_factor']))
    unit=policy['round_to_points']
    amount=int((padded/Decimal(unit)).to_integral_value(rounding=ROUND_CEILING))*unit
    if amount>policy['max_per_request_points']:
        raise BudgetStop('prompt-based engineering risk exceeds registered per-request cap; no clipping')
    return {'points':amount,'input_envelope':inputs,'output_envelope':policy['output_envelope'],
        'raw_conditional_points':float(raw),'certified_provider_upper_bound':False}


def public_json(secret,path,*,authenticated=False):
    if path not in ('/api/pricing','/api/status','/v1/models'):raise ValueError('metadata allowlist only')
    connection=http.client.HTTPSConnection('leafapi.cc',timeout=15)
    try:
        headers={'Accept':'application/json','Cache-Control':'no-cache'}
        if authenticated:headers['Authorization']='Bearer '+secret
        connection.request('GET',path,headers=headers)
        response=connection.getresponse();raw=response.read(2097153)
        if response.status!=200 or len(raw)>2097152:raise BudgetStop('new-model pricing/list metadata unavailable')
        return json.loads(raw)
    except (ValueError,OSError):raise BudgetStop('new-model pricing/list metadata unavailable') from None
    finally:connection.close()


def check_live_tariff(secret,*,query=public_json):
    pricing=query(secret,'/api/pricing');status=query(secret,'/api/status')
    models=query(secret,'/v1/models',authenticated=True)
    rows=[r for r in pricing.get('data',[]) if r.get('model_name')==MODEL]
    if (pricing.get('success') is not True or len(rows)!=1 or rows[0].get('billing_expr')!=EXPRESSION
            or rows[0].get('enable_groups')!=['codex-deafult']
            or pricing.get('group_ratio',{}).get('codex-deafult')!=0.5
            or status.get('success') is not True or status.get('data',{}).get('quota_per_unit')!=500000
            or not any(r.get('id')==MODEL for r in models.get('data',[]))):
        raise BudgetStop('live model/group/tariff differs from registered migration; no fallback')
    return {'checked_at':time.time(),'model':MODEL,'group':'codex-deafult',
        'expression':EXPRESSION,'group_ratio':0.5,'quota_per_unit':500000,
        'pricing_version':pricing.get('pricing_version'),'certified_provider_upper_bound':False}


class MigrationWire(JsonCandidateTransport):
    def dispatch(self,key,prompt,*,kind='U',on_sent=lambda:None):
        if key.startswith('r201/diagnostic/'):
            if prompt!=DIAGNOSTIC_PROMPT:raise BudgetStop('diagnostic must use the registered short non-candidate input')
            small=replace(self.config,provider=replace(self.config.provider,max_output_tokens=256))
            return JsonCandidateTransport(small).dispatch(key,prompt,kind=kind,on_sent=on_sent)
        return super().dispatch(key,prompt,kind=kind,on_sent=on_sent)


class MigrationQuota(QuotaGuardedTransport):
    def __init__(self,*args,tariff_query=check_live_tariff,**kwargs):
        self.tariff_query=tariff_query;self._tariff_at=None
        super().__init__(*args,**kwargs)

    def reservation_for(self,prompt):
        policy=self.config.conditional_research['model_migration']['risk_policy']
        return risk_reservation(prompt,policy)['points']

    def preflight(self,prompt):
        if self._tariff_at is None or self.clock()-self._tariff_at>=self.config.platform_quota_query_interval:
            try:audit=self.tariff_query(self.transport.secret)
            except BudgetStop as exc:
                self.halt(str(exc));raise
            self.data['latest_tariff_check']=audit;self.save();self._tariff_at=self.clock()
        super().preflight(prompt)

    def dispatch(self,key,prompt,*,kind='U',on_sent=lambda:None):
        parts=key.split('/')
        if len(parts)<3 or '/'.join(parts[:2]) not in self.config.phase_caps() or parts[1]=='H':
            raise BudgetStop('undeclared migration dispatch phase')
        def sent():
            self.data['records'][key]['risk_basis']=risk_reservation(prompt,
                self.config.conditional_research['model_migration']['risk_policy'])
            self.save();on_sent()
        return super().dispatch(key,prompt,kind=kind,on_sent=sent)
