from pathlib import Path
import copy
import math
from heuristic_design.core.storage import read,sha,digest
ROOT=Path(__file__).resolve().parents[2]
VERSION='triad-independent-search-v1'
GROUPS=tuple(p+'-'+m for p in ('fjsp','tsp','obp') for m in ('u','eoh'))


def load(path,*,engineering=False):
    path=Path(path).resolve();c=read(path)
    template=read(ROOT/'experiments/triad/configs'/ (c['group']+'.json'))
    if set(c)!=set(template) or c['version']!=VERSION or c['group'] not in GROUPS:raise ValueError('explicit triad config fields/identity required')
    if c['problem']+'-'+c['method']!=c['group']:raise ValueError('group/problem/method mismatch')
    if c['real_requests_authorized'] is not False:raise ValueError('saved request authorization must remain OFF')
    if c['evolution_request_cap']!=1000 and not (engineering and c['mode']=='mock'):raise ValueError('each research seed requires exactly 1000 evolution attempts; initialization separate')
    if c['mode'] not in ('real','mock') or c['mode']=='mock' and not engineering:raise ValueError('Mock requires explicit engineering entry')
    seeds=c['search_seeds']
    if seeds is not None and (not isinstance(seeds,list) or not seeds or any(type(x) is not int or x<0 for x in seeds) or len(set(seeds))!=len(seeds)):raise ValueError('distinct explicit seeds required')
    if c['repeat_count'] is not None and (type(c['repeat_count']) is not int or c['repeat_count']<1 or seeds is not None and len(seeds)!=c['repeat_count']):raise ValueError('repeat count must equal declared seed count')
    for k in ('population_size','initialization_request_cap','api_attempt_cap','window_seconds','solve_seed'):
        if c[k] is not None and (type(c[k]) is not int or c[k]<(0 if k=='solve_seed' else 1)):raise ValueError('invalid integer '+k)
    if c['population_size'] is not None and c['population_size']<2:raise ValueError('population N>=2')
    if c['population_size'] is not None and c['initialization_request_cap'] is not None and c['initialization_request_cap']<c['population_size']:raise ValueError('independent initialization cap below N')
    if c['api_attempt_cap'] is not None and c['initialization_request_cap'] is not None and c['api_attempt_cap']!=c['initialization_request_cap']+c['evolution_request_cap']:raise ValueError('cumulative cap = init maximum + evolution attempts')
    if c['api_concurrency']!=1 or c['per_candidate_attempt_cap']!=1:raise ValueError('one generation worker; one attempt; no automatic retry')
    if c['evaluation_concurrency'] is not None and (type(c['evaluation_concurrency']) is not int or c['evaluation_concurrency']<1):raise ValueError('invalid evaluation width')
    if c['instance_timeout_seconds']!=30:raise ValueError('shared first/recheck complete-row T30 required')
    if c['mode']=='real' and (c['mock_faults'] or c['pause_after_tasks'] is not None):raise ValueError('engineering controls prohibited in real profile')
    for k in ('data_manifest','h_file','reference_file','frozen_u_template','compatible_fixed_results','state_delivery'):
        if c[k] and isinstance(c[k],str):c[k]=str((path.parent/c[k]).resolve())
    if isinstance(c['state_delivery'],dict):
        c['state_delivery']={**c['state_delivery'],'file':str((path.parent/c['state_delivery']['file']).resolve())}
    if c['problem']=='obp' and c['mode']=='real' and c['obp_h_abi'] not in (None,'obp-vector-feasible-h-v2'):raise ValueError('preset-N formal OBP requires the shared feasible vector H ABI; scalar prototype is engineering-only')
    if c['problem']=='obp' and c['obp_h_abi'] is not None and c['obp_h_abi'] not in ('obp-two-scalar-h-v1','obp-vector-feasible-h-v2'):raise ValueError('retired OBP input ABI; explicit asset/protocol migration required')
    r=c['resources']
    for k in ('cpus','memory_mib','segment_seconds','drain_seconds'):
        if r[k] is not None and (type(r[k]) is not int or r[k]<1):raise ValueError('invalid resource '+k)
    if r['numeric_threads']!=1:raise ValueError('numeric threads must remain 1')
    if r['cpus'] is not None and c['evaluation_concurrency'] is not None and r['cpus']<1+max(c['api_concurrency'],c['evaluation_concurrency']):raise ValueError('controller and staged workers must fit allocation')
    return c


def gaps(c):
    required=['repeat_count','search_seeds','population_size','initialization_request_cap','api_attempt_cap','window_seconds','solve_seed','evaluation_concurrency','data_manifest','budget_basis','protocol_receipt','initialization_policy']
    if c['method']=='u':required+=['h_file']
    if c['problem']=='tsp':required+=['reference_file','data_usage_receipt']
    if c['problem']=='obp':required+=['obp_actions','obp_h_abi','obp_bound','state_delivery','data_usage_receipt']
    missing=[k for k in required if c.get(k) is None]
    if c['freeze_status']!='frozen' and not (c['mode']=='mock' and c['freeze_status']=='engineering_only'):missing.append('freeze_status')
    if c['problem']=='fjsp' and c['method']=='u' and not c['frozen_u_template']:missing.append('frozen_u_template')
    for k in ('cpus','memory_mib','segment_seconds','drain_seconds'):
        if c['resources'][k] is None:missing.append('resources.'+k)
    if c['problem']=='obp' and c['mode']=='real' and isinstance(c['state_delivery'],dict) and c['state_delivery'].get('adoption')!='adopted':missing.append('state_delivery.adoption')
    if c['mode']=='real':
        for k in ('account_exclusion','account_gate','credential_file'):
            if not c[k]:missing.append(k)
    return missing


def budget(c):
    a=c['api_attempt_cap'];n=c['instance_count'];r=c['repeat_count']
    return dict(initialization_max=c['initialization_request_cap'],evolution_attempts=c['evolution_request_cap'],request_cap_per_seed=a,
      requests_all_seeds=None if a is None or r is None else a*r,
      native_passes_per_instance=2,native_solve_cap_per_seed=None if a is None or n is None else 2*a*n,
      H_build_separate=c['h_build'],automatic_retries=0,unknown_attempts_charged=True)
