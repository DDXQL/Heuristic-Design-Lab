#!/usr/bin/env python3
"""GET-only settlement/rate audit, outside the frozen experiment closure.

No inference, redirects, cookies, key-in-URL, retries or ledger changes.
Write a NEW local evidence directory. Only allowlisted metadata survives.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_CEILING
import hashlib
import http.client
import json
import math
from pathlib import Path
import sys
import time
from urllib.parse import urlencode,urlsplit
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
from fjsp_usage.research_real.leafapi import load_local_key

HEADER_FIELDS=('date','age','cache-control','etag','last-modified','cf-cache-status','content-type','x-request-id','x-oneapi-request-id','x-new-api-request-id')
ROW_FIELDS=('id','created_at','type','model_name','quota','prompt_tokens','completion_tokens','use_time','request_id','token_id','user_id','group')
RATE_FIELDS=('model_ratio','group_ratio','completion_ratio','cache_ratio','cache_creation_ratio','billing_mode','billing_expr','tier','tier_name','pricing_version')
ALLOWED_PATHS={'/api/usage/token/','/api/log/token','/api/log/self','/api/pricing','/api/status','/v1/models'}


def sanitize(value,secret):
    if isinstance(value,str):return value.replace(secret,'[REDACTED]') if secret else value
    if isinstance(value,list):return [sanitize(x,secret) for x in value]
    if isinstance(value,dict):return {sanitize(str(k),secret):sanitize(v,secret) for k,v in value.items()}
    return value


def rows_from(body):
    data=body.get('data',[])
    if isinstance(data,dict):data=data.get('items',data.get('data',data.get('logs',[])))
    if not isinstance(data,list):raise ValueError('log list missing')
    rows=[]
    for row in data:
        if not isinstance(row,dict):raise ValueError('invalid log row')
        item={k:row[k] for k in ROW_FIELDS if k in row and type(row[k]) in (str,int,float,bool)}
        other=row.get('other',{})
        if isinstance(other,str):
            try:other=json.loads(other)
            except ValueError:other={}
        if isinstance(other,dict):item['pricing_metadata']={k:other[k] for k in RATE_FIELDS if k in other}
        rows.append(item)
    return rows


def extract(body,kind):
    result={'success':body.get('success',body.get('code')) is True,
            'top_keys':sorted(body),'data_shape':type(body.get('data')).__name__}
    data=body.get('data')
    if isinstance(data,dict):result['data_keys']=sorted(data)
    if kind=='logs':
        result['records']=rows_from(body) if result['success'] else []
        result['pagination_metadata']={k:body[k] for k in ('total','p','page','page_size','next','has_more') if k in body}
        if isinstance(data,dict):result['pagination_metadata'].update({k:data[k] for k in ('total','p','page','page_size','next','has_more') if k in data})
    elif kind=='quota' and isinstance(data,dict):
        fields=('total_used','total_available','total_granted','unlimited_quota','expires_at','model_limits_enabled','group','token_group')
        result['quota']={k:data[k] for k in fields if k in data}
        result['identity_fields_present']=[k for k in ('id','token_id','user_id','name','username') if k in data]
        result['identity_fingerprints']={k:hashlib.sha256(json.dumps(data[k],sort_keys=True).encode()).hexdigest()
            for k in result['identity_fields_present']}
    elif kind=='pricing':
        models=data if isinstance(data,list) else (data.get('model',[]) if isinstance(data,dict) else body.get('model',[]))
        result['models']=[{k:v for k,v in m.items() if k in ('model_name','quota_type','model_ratio','model_price','completion_ratio','enable_groups','billing_mode','billing_expr')}
                          for m in models if isinstance(m,dict) and m.get('model_name')=='gpt-5.6-sol']
        for name in ('group_ratio','pricing_version'):
            if name in body:result[name]=body[name]
            elif isinstance(data,dict) and name in data:result[name]=data[name]
    elif kind=='models' and isinstance(data,list):
        if 'success' not in body and 'code' not in body:result['success']=True
        result['model_count']=len(data)
        result['locked_model_listed']=any(isinstance(row,dict) and row.get('id')=='gpt-5.6-sol' for row in data)
    elif kind=='status' and isinstance(data,dict):
        result['public_fields']={k:data[k] for k in ('version','quota_per_unit','quota_display_type','display_in_currency','price') if k in data}
    return result


def get_metadata(secret,path,kind,*,connection_factory=http.client.HTTPSConnection,authenticated=True):
    parts=urlsplit(path)
    if parts.scheme or parts.netloc or parts.path not in ALLOWED_PATHS or parts.fragment or (secret and secret in path):
        raise ValueError('allowlisted same-origin GET only; no secret in URL')
    result={'method':'GET','origin':'https://leafapi.cc','path':path,'inference_requests':0,
            'observed_at':time.time(),'response_headers_scope':'this metadata GET, not the failed POST'}
    connection=connection_factory('leafapi.cc',timeout=15)
    try:
        headers={'Accept':'application/json','Cache-Control':'no-cache','Pragma':'no-cache'}
        if authenticated:headers['Authorization']='Bearer '+secret
        connection.request('GET',path,headers=headers)
        response=connection.getresponse();result['http_status']=response.status
        result['headers']={k:response.getheader(k) for k in HEADER_FIELDS if response.getheader(k) is not None}
        raw=response.read(2097153);result['response_bytes']=len(raw);result['response_sha256']=hashlib.sha256(raw).hexdigest()
        if len(raw)>2097152:raise ValueError('metadata exceeds byte bound')
        if response.status==200:
            body=json.loads(raw)
            if not isinstance(body,dict):raise ValueError('metadata must be object')
            result.update(extract(body,kind))
        else:result['success']=False
    except Exception as exc:result.update(success=False,error_type=type(exc).__name__)
    finally:connection.close()
    return sanitize(result,secret)


def engineering_reservation(input_tokens, output_tokens, *, input_rate=12.5, output_rate=45,
                            group_ratio=5.5, quota_per_unit=500000, safety_factor=1.25):
    """Conditional local risk estimate; never a certified fee or usage value."""
    if any(type(v) is not int or v<0 for v in (input_tokens,output_tokens)):
        raise ValueError('nonnegative built-in token envelopes required')
    numbers=(input_rate,output_rate,group_ratio,quota_per_unit,safety_factor)
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in numbers):
        raise ValueError('positive finite rates/engineering factor required')
    raw=(Decimal(input_tokens)*Decimal(str(input_rate))+Decimal(output_tokens)*Decimal(str(output_rate)))
    raw=raw*Decimal(str(group_ratio))*Decimal(str(quota_per_unit))/Decimal(1000000)
    padded=raw*Decimal(str(safety_factor))
    rounded=int((padded/Decimal(100000)).to_integral_value(rounding=ROUND_CEILING))*100000
    return {'raw_conditional_points':float(raw),'proposed_next_request_reservation':max(5000000,rounded),
            'within_original_12000000_per_request_max':max(5000000,rounded)<=12000000,
            'certified_provider_upper_bound':False}


def summarize(result):
    rows=result.get('records',[])
    stamps=[v['created_at'] for v in rows if type(v.get('created_at')) in (int,float)]
    return {'http_status':result.get('http_status'),'success':result.get('success'),
        'rows':len(rows),'types':dict(Counter(v.get('type') for v in rows)),
        'min_time':min(stamps) if stamps else None,'max_time':max(stamps) if stamps else None,
        'pagination_metadata':result.get('pagination_metadata',{}),'headers':result.get('headers',{})}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True);parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--env-file',type=Path,required=True);args=parser.parse_args()
    run=args.run_dir.resolve();out=args.out_dir.resolve()
    if not run.is_relative_to(ROOT/'runs') or not out.is_relative_to(ROOT/'runs') or out.exists():parser.error('own runs paths; new output only')
    key=load_local_key(args.env_file)
    audit=json.loads(next((run/'billing').glob('*.json')).read_text());q=audit['original_quota_record']
    start=int(q['started_at'])-600;end=int(q['finished_at'])+600
    base={'p':1,'page_size':100,'start_timestamp':start,'end_timestamp':end,'model_name':'gpt-5.6-sol'}
    paths=[('quota','/api/usage/token/','quota',True),('token_latest','/api/log/token','logs',True),
           ('token_window_p1','/api/log/token?'+urlencode(base),'logs',True),
           ('token_window_p2','/api/log/token?'+urlencode({**base,'p':2}),'logs',True),
           ('user_window','/api/log/self?'+urlencode(base),'logs',True),
           ('public_pricing','/api/pricing','pricing',False),('public_status','/api/status','status',False),
           ('locked_model_listing','/v1/models','models',True)]
    out.mkdir(parents=True)
    collected={}
    for label,path,kind,auth in paths:
        data=get_metadata(key,path,kind,authenticated=auth);collected[label]=data
        (out/(label+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        print(label,json.dumps(summarize(data) if kind=='logs' else {'success':data.get('success'),'http_status':data.get('http_status')},ensure_ascii=False),flush=True)
    original_ids={v.get('request_id') for v in audit['before']['records'] if v.get('request_id')}
    fresh=collected['token_latest'].get('records',[])
    rows_in_window=[v for v in fresh if type(v.get('created_at')) in (int,float) and start<=v['created_at']<=end]
    new=[v for v in fresh if v.get('request_id') and v['request_id'] not in original_ids]
    summary={'date_local':'2026-10-14 Asia/Manila','inference_requests':0,'metadata_requests':len(paths),
        'failed_local_request_key':audit['global_key'],'supplier_request_id_retained':False,
        'UTC_start':datetime.fromtimestamp(q['started_at'],timezone.utc).isoformat(),
        'UTC_end_account_check':datetime.fromtimestamp(q['finished_at'],timezone.utc).isoformat(),
        'Asia_Manila_start':datetime.fromtimestamp(q['started_at'],timezone(timedelta(hours=8))).isoformat(),
        'provider_roundtrip_seconds':next(iter(json.loads((run/'r201/INIT/budgeted_initial_requests.json').read_text())['requests'].values()))['response_metadata']['provider_roundtrip_seconds'],
        'current_key_fingerprint':hashlib.sha256(key.encode()).hexdigest(),
        'old_key_fingerprint_recorded':False,'credential_file_mtime':args.env_file.stat().st_mtime,
        'token_log_queries':{k:summarize(collected[k]) for k in ('token_latest','token_window_p1','token_window_p2','user_window')},
        'token_window_p1_equal_p2':collected['token_window_p1'].get('records')==collected['token_window_p2'].get('records'),
        'window_query_equals_unfiltered':collected['token_window_p1'].get('records')==fresh,
        'rows_in_wide_window':rows_in_window,'new_vs_failed_request_before_snapshot':new,
        'remaining_uncertainty':'Recent token logs may exclude unlogged errors, retired/removed entries and other account keys. Query parameters are not assumed effective. No log absence or unchanged balance proves zero charge.',
        'quota':collected['quota'].get('quota'),
        'locked_model_listed':collected['locked_model_listing'].get('locked_model_listed'),
        'no_ledger_or_protocol_mutation':True}
    (out/'Audit_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print('AUDIT_SAVED',str(out),flush=True)

if __name__=='__main__':main()
