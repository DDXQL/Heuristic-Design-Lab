"""Read-only inclusion of an existing completed 501. Never copy or resume it."""
from pathlib import Path
import math
import copy
from heuristic_design.core.storage import read,write,sha,digest
from . import problems
ROOT=Path(__file__).resolve().parents[2]
PROTECTED_501=Path('/Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-mac-20261112/runs/fjsp-u1000-20261112-mac-seed-501')


def existing_profile(c):
    """Narrow completed-result adoption does not freeze any future run budget."""
    if c['freeze_status']=='frozen' and c.get('protocol_receipt'):return c
    adoption=read(ROOT/'experiments/triad/repetition-approval.json')
    if not (adoption.get('adopted') is True and adoption.get('include_existing_fjsp_u501_read_only') is True and c['repeat_count']==adoption['repeat_count'] and c['search_seeds']==adoption['search_seeds']):raise PermissionError('explicit completed501/repetition adoption required')
    effective=copy.deepcopy(c);template=read(ROOT/'preparations/triad/fjsp/U_frozen_template.json')['settings']
    fields=('population_size','initialization_request_cap','api_attempt_cap','solve_seed','api_concurrency','evaluation_concurrency','instance_timeout_seconds','provider')
    for k in fields:
        if effective[k] is not None and effective[k]!=template[k]:raise ValueError('read-only adoption cannot alter actual501 setting: '+k)
        effective[k]=template[k]
    original=template['execution_contract']['initialization_policy']
    if effective['initialization_policy'] not in (None,original):raise ValueError('actual501 initialization differs')
    effective['initialization_policy']=original
    return effective


def check_profile(p,c,data,H_keys):
    expected=read(ROOT/'preparations/triad/fjsp/public-runtime-923781f.json')['files']
    if p['source_files']!=expected:raise ValueError('existing source/actual Prompt differs from frozen 923781f profile')
    template=read(ROOT/'preparations/triad/fjsp/U_frozen_template.json')['settings']
    for field in ('problem','initialization','evaluation_mode','window','enabled_groups'):
        if p['config'][field]!=template[field]:raise ValueError('existing frozen scientific profile differs: '+field)
    for field in ('population_size','initialization_request_cap','api_attempt_cap','solve_seed','api_concurrency','evaluation_concurrency','instance_timeout_seconds','provider'):
        if p['config'][field]!=c[field]:raise ValueError('existing scientific setting differs: '+field)
    if p['config']['generation_request_cap']!=c['evolution_request_cap'] or p['config']['search_seed']!=501:raise ValueError('existing seed/evolution budget differs')
    if [r['sha256'] for r in p['instances']]!=[r['sha256'] for r in data] or [r['file'] for r in p['instances']]!=[r['file'] for r in data]:raise ValueError('existing ordered train21 differs')
    if [r['key'] for r in p['members']]!=H_keys:raise ValueError('existing frozen H order differs')
    if p['config']['execution_contract']['initialization_policy']!=c['initialization_policy']:raise ValueError('existing initialization policy differs')


def profile_identity(c,data,hs):
    fields=('population_size','initialization_request_cap','api_attempt_cap','solve_seed','api_concurrency','evaluation_concurrency','instance_timeout_seconds','provider','initialization_policy','evolution_request_cap')
    return {'settings':{k:c[k] for k in fields},'H_keys':[r['key'] for r in hs],
      'ordered_data':[{'file':r['file'],'sha256':r['sha256']} for r in data],
      'public_source_manifest_sha256':sha(ROOT/'preparations/triad/fjsp/public-runtime-923781f.json')}


def check_snapshot(snapshot,c):
    if snapshot.get('phase')!='completed' or snapshot.get('unknown_sends')!=0:raise ValueError('only settled complete evidence may be included')
    init=snapshot.get('initialization_attempts');evo=snapshot.get('evolution_attempts')
    if type(init) is not int or not 0<=init<=c['initialization_request_cap'] or evo!=c['evolution_request_cap'] or snapshot.get('request_reservations')!=init+evo:raise ValueError('existing completion/budget counters differ')
    if type(snapshot.get('best_J')) not in (int,float) or not math.isfinite(snapshot['best_J']) or not snapshot.get('champion_id'):raise ValueError('complete valid champion evidence required')


def accept_receipt(row,c,path,expected_sha,accept=False):
    if not accept or sha(path)!=expected_sha:raise PermissionError('explicit read-only receipt SHA and acceptance required')
    if row['group']!='fjsp-u' or row['seed']!=501:raise PermissionError('only existing FJSP U501 is adopted')
    c=existing_profile(c)
    receipt=read(path)
    if receipt.get('kind')!='existing-completed-read-only-registration-v1' or receipt.get('checkpoint_copied') is not False or receipt.get('execution_prohibited') is not True or receipt.get('snapshot',{}).get('phase')!='completed' or receipt.get('new_API_requests')!=0 or receipt.get('new_solves')!=0:raise ValueError('not a complete read-only existing-run receipt')
    check_snapshot(receipt['snapshot'],c)
    data,refs,hs=problems.load_inputs(c)
    if receipt.get('profile_identity')!=profile_identity(c,data,hs):raise ValueError('imported existing-run scientific identity differs')
    return receipt


def register(row,c,accept=False):
    if not accept:raise PermissionError('explicit --accept-existing-completed required; no existing run read')
    if row['group']!='fjsp-u' or row['seed']!=501:raise PermissionError('only existing FJSP U501 is adopted')
    c=existing_profile(c)
    source=PROTECTED_501
    summary=read(source/'exports/summary.json')
    if any((source/n).exists() for n in ('.coordinator.lock','.execution.lock','Stop.json')):raise PermissionError('existing 501 is not complete/settled; never restart, copy checkpoint or take over')
    check_snapshot(summary,c)
    p=read(source/'Protocol.json');identity=sha(source/'Protocol.json')
    if read(source/'Protocol.receipt.json')['sha256']!=identity or summary['protocol_sha256']!=identity:raise ValueError('existing immutable protocol/summary mismatch')
    cp=read(source/'checkpoint.receipt.json')
    if cp!={'identity':identity,'sha256':sha(source/'checkpoint.json')}:raise ValueError('existing checkpoint receipt mismatch; not copied or reinterpreted')
    data,refs,hs=problems.load_inputs(c);check_profile(p,c,data,[r['key'] for r in hs])
    curve=[]
    import csv
    path=source/'exports/candidates.csv'
    if path.exists():
        for row in csv.DictReader(path.open()):
            if row.get('best_J') not in (None,''):curve.append({'evolution_attempt':int(row['evolution_attempt']),'best_J':float(row['best_J'])})
    return {'curve':curve,'curve_source_sha256':sha(path) if path.exists() else None,'profile_identity':profile_identity(c,data,hs),'kind':'existing-completed-read-only-registration-v1','source_directory':str(source),'source_protocol_sha256':identity,
      'source_summary_sha256':sha(source/'exports/summary.json'),'source_checkpoint_receipt_sha256':sha(source/'checkpoint.receipt.json'),
      'snapshot':{**{k:summary.get(k) for k in ('phase','run_id','initialization_attempts','evolution_attempts','request_reservations','confirmed_sends','unknown_sends','candidate_failures','duplicates','best_J','champion_id','known_usage_subtotal','unknown_usage_attempts','actual_cost')},'failures':summary.get('candidate_failures')},
      'new_API_requests':0,'new_solves':0,'checkpoint_copied':False,'execution_prohibited':True,'future_run_parameters_authorized':False}
