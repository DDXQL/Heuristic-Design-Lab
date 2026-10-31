"""Thin paired orchestration around the existing common engine.

Preview/P0 audit are read-only. This module never implements transport, candidate
operators, evaluation, retries or checkpoint recovery. Each paid arm still uses
engine.prepare/run/export with a new Protocol and the original import semantics.
"""
from dataclasses import asdict
from pathlib import Path
import json,os
from contextlib import redirect_stdout,redirect_stderr
import sys

from heuristic_design.core import evolution_v1 as engine, routing
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.core.constructive_state import SPEC_SHA256
from heuristic_design.core.terminal_ops import inputs
from heuristic_design.core.evolution_export import export
from experiments.common._search_reports import protocol_state,finish
from experiments.common._single_run import _Tee
from experiments.common._real_run import existing

POLICIES={'A':'fitness','B':'behavior_first'}
SELECTOR_ONLY={'code/heuristic_design/core/search.py','code/heuristic_design/core/evolution_v1.py'}
EVALUATION_KEYS=('problem','state_schema','solve_seed','window','enabled_groups','instance_timeout_seconds','recording_mode',
                 'api_concurrency','evaluation_concurrency')


def shared_p0(source,config):
    source=Path(source).resolve();p,s=protocol_state(source)
    if (source/'.coordinator.lock').exists() or s['phase'] not in ('completed','paused') or not s['initialization_complete']:
        raise ValueError('P0 source must be safely stopped with complete initialization')
    if p['config']['search_seed']!=config['search_seed']:raise ValueError('P0 origin/search seed mismatch; declare a compatible source for this pair')
    if any(p['config'].get(k,'full' if k=='recording_mode' else None)!=config[k] for k in EVALUATION_KEYS):
        raise ValueError('P0 evaluation/state/seed/deadline configuration mismatch')
    if p['state_spec_sha256']!=SPEC_SHA256 or p['u_abi']!=routing.ABI:raise ValueError('P0 state/ABI mismatch')
    if p['config']['provider']!=config['provider']:raise ValueError('Retain the accepted model/transport settings for this pair')
    now=engine.source_identity()
    if set(now)!=set(p['source_files']):raise ValueError('P0 source file inventory differs')
    changed=sorted(k for k in now if now[k]!=p['source_files'][k])
    if not set(changed)<=SELECTOR_ONLY:raise ValueError('P0 evaluator/transport/state source changed: '+','.join(changed))
    members,data,origin=inputs(config)
    if members!=p['members'] or data!=p['instances'] or origin['H']['sha256']!=p['input_provenance']['H']['sha256'] or origin['data']['sha256']!=p['input_provenance']['data']['sha256']:
        raise ValueError('P0 H/data identity or order mismatch')
    if len(members)!=10 or len(data)!=21 or any(r['split']!='train' for r in data):raise ValueError('Explicit frozen 10H/train21 required')
    pop=read(source/'populations/P000.json')
    if len(pop)!=config['population_size']:raise ValueError('P0 size mismatch')
    if s['generation']:
        rec=s['plans']['1'];plan=source/rec['path']
        if sha(plan)!=rec['sha256'] or read(plan)['population']!=pop:raise ValueError('P0/frozen first-parent plan mismatch')
    elif s['population']!=pop:raise ValueError('P0/checkpoint mismatch')
    imports=[];reference=[];keys=set()
    for row in pop:
        t=s['tasks'][row['id']];candidate=asdict(routing.checked(row['candidate'],len(members)))
        if not t['valid'] or t['stage']!='initialization' or candidate!=t['candidate'] or candidate['key'] in keys:
            raise ValueError('P0 is not N certified AST-distinct initialization candidates')
        keys.add(candidate['key']);ev=s['evaluations'][candidate['key']];path=source/ev['path']
        if sha(path)!=ev['sha256'] or ev['binding']!=digest({'protocol':s['identity'],'candidate':candidate['key']}):raise ValueError('P0 evaluation receipt mismatch')
        result=read(path);rows=result['instances']
        if not result['valid'] or result['fitness']!=row['fitness'] or row['fitness']!=t['fitness']:
            raise ValueError('P0 complete Fitness receipt mismatch')
        if ([r['file'] for r in rows]!=[r['file'] for r in data] or any(not r['feasible'] or r['captured_solves']!=2
             or r['semantic_sha256']!=r['recheck_semantic_sha256'] or r['source_before_sha256']!=r['source_after_sha256']
             or r['source_before_sha256']!=digest(p['source_files']) for r in rows)):
            raise ValueError('P0 incomplete feasibility/recheck/source certification')
        if digest(result['behavior'])!=row['behavior_sha256'] or result['behavior_sha256']!=row['behavior_sha256']:
            raise ValueError('P0 behavior identity mismatch')
        imports.append({'source':f'frozen P0 {s["identity"]}/{row["id"]}', 'candidate':candidate})
        reference.append({'source_id':row['id'],'candidate_key':candidate['key'],'fitness':row['fitness'],
                          'behavior_sha256':row['behavior_sha256'],'evaluation_sha256':ev['sha256']})
    known_in=known_out=unknown=sent=0
    for t in s['tasks'].values():
        if t['stage']!='initialization':continue
        sent+=bool(t.get('sent_confirmed'))
        r=read(source/t['response_path']) if t.get('response_path') else {};u=(r.get('value') or {}).get('usage')
        if isinstance(u,dict):known_in+=u.get('input_tokens',0) or 0;known_out+=u.get('output_tokens',0) or 0
        else:unknown+=bool(t.get('response_path'))
    baseline=source/'launch/baselines.json';baseline_receipt=read(source/'launch/postprocess.receipt.json')
    if sha(baseline)!=baseline_receipt['baselines_sha256']:raise ValueError('Frozen source R1 baseline snapshot changed')
    return {'source_directory':str(source),'protocol_sha256':s['identity'],'checkpoint_sha256':sha(source/'checkpoint.json'),
       'p0_file_sha256':sha(source/'populations/P000.json'),'imports':imports,'reference_evaluations':reference,
       'baseline_snapshot':read(baseline),'baseline_snapshot_sha256':sha(baseline),
       'allowed_source_changes':changed,'evaluation_compatibility':'Only selector/config/dispatch files may differ; evaluation is repeated in each arm. No historical Fitness is seeded.',
       'historical_initialization':{'api_mode':p['config']['api_mode'],'method':p['config']['initialization'],
         'attempts':s['initialization_requests'],'attempt_cap':p['config']['initialization_request_cap'],
         'confirmed_sent':sent,'known_input_tokens':known_in,'known_output_tokens':known_out,'unknown_usage_responses':unknown,
         'upstream_generation_attempts_known':p['config']['initialization']=='llm',
         'actual_currency_cost':None,'new_API_requests_for_reuse':0}}


def preview(parameters,*,source,pair_directory,root,entry,pair_attempt_cap):
    # This entry intentionally supports one explicit pair, not a seeds loop.
    c=engine.config(parameters)
    if (c['problem']!='fjsp' or c['api_mode']!='real' or c['evaluation_mode']!='solve' or c['initialization']!='import'
        or c['p0_file'] is not None or c['survival_policy']!='fitness'):
        raise ValueError('Pair base must explicitly use real FJSP/imported shared P0 and fitness policy')
    n=c['population_size'];g=c['generations']
    if g<1 or c['generation_request_cap']!=2*n*g or c['api_attempt_cap']!=2*n*g or pair_attempt_cap!=4*n*g:
        raise ValueError('Explicit per-arm 2NG and pair 4NG attempt budgets must agree')
    if c['initialization_candidate_cap']!=n or c['initialization_request_cap']!=n:raise ValueError('Imported P0 caps must equal N; initialization sends zero requests')
    for k in ('h_file','data_manifest'):
        c[k]=str((root/c[k]).resolve())
    bundle=shared_p0(source,c)
    configs={arm:{**c,'survival_policy':policy} for arm,policy in POLICIES.items()}
    assert {k for k in configs['A'] if configs['A'][k]!=configs['B'][k]}=={'survival_policy'}
    directory=(root/pair_directory).resolve();sources=engine.source_identity()
    helpers={str(Path(__file__).relative_to(root)):sha(Path(__file__)),
             'experiments/common/_search_reports.py':sha(root/'experiments/common/_search_reports.py'),
             'experiments/common/_real_run.py':sha(root/'experiments/common/_real_run.py')}
    fingerprint=digest({'configs':{a:{**cfg,'real_requests_authorized':True} for a,cfg in configs.items()},
         'P0':digest(bundle),'source_files':sources,'helper_sources':helpers,'pair_directory':str(directory),'pair_attempt_cap':pair_attempt_cap})
    plan={'pair_directory':str(directory),'pair_fingerprint':fingerprint,'arm_configs':configs,
          'source_files':sources,'helper_sources':helpers,'shared_p0':bundle,'shared_p0_sha256':digest(bundle),
          'budget':{'new_P0_generation_API_attempts':0,'per_arm_evolution_attempts':2*n*g,'pair_API_attempt_cap':pair_attempt_cap,
                    'per_arm_P0_re_evaluations':n,'max_program_instances_per_arm':(n+2*n*g)*21,
                    'max_solve_passes_per_pair':2*(n+2*n*g)*21*2},
          'limits':'One pair only; no automatic repeat, retry, initialization replacement or validation. Imported P0 is fully re-evaluated by the unchanged engine in each arm.',
          'API_requests_sent':0,'solves':0}
    return plan


def fingerprint(plan):
    return digest({'configs':{a:{**c,'real_requests_authorized':True} for a,c in plan['arm_configs'].items()},
        'P0':digest(plan['shared_p0']),'source_files':plan['source_files'],'helper_sources':plan['helper_sources'],
        'pair_directory':plan['pair_directory'],'pair_attempt_cap':plan['budget']['pair_API_attempt_cap']})


def show(plan):
    return {k:v for k,v in plan.items() if k not in ('source_files','helper_sources','shared_p0')} | {
        'shared_p0':{k:v for k,v in plan['shared_p0'].items() if k not in ('imports','reference_evaluations','baseline_snapshot')}}


def read_pair(directory,root):
    path=directory/'Pair.json';plan=read(path)
    if read(directory/'Pair.receipt.json')!={'sha256':sha(path)}:raise ValueError('Frozen pair receipt changed')
    if Path(plan['pair_directory'])!=directory:raise ValueError('Pair directory changed')
    if plan['source_files']!=engine.source_identity():raise ValueError('Frozen pair execution source changed')
    if any(sha(root/name)!=value for name,value in plan['helper_sources'].items()):raise ValueError('Frozen pair helper changed')
    if digest(plan['shared_p0'])!=plan['shared_p0_sha256']:raise ValueError('Frozen shared P0 changed')
    if fingerprint(plan)!=plan['pair_fingerprint']:raise ValueError('Frozen pair config/P0/budget fingerprint changed')
    return plan


def approval(path,plan,root):
    # No approval is created by this entry, preview or tests.
    if path is None:raise PermissionError('No fresh survival-ab-pair authorization; historical 1050/8 approvals cannot be reused')
    path=(root/path).resolve();record=read(path)
    if (record.get('stage')!='survival-ab-pair' or record.get('status')!='approved'
        or record.get('pair_fingerprint')!=plan['pair_fingerprint'] or record.get('max_attempts')!=plan['budget']['pair_API_attempt_cap']):
        raise PermissionError('Authorization does not match this exact pair/config/P0/source/budget')
    return path


def launch(plan,arm,*,root,entry,authorization_file):
    if arm not in POLICIES:raise ValueError('Explicit arm A or B required')
    directory=Path(plan['pair_directory'])
    if directory.exists():plan=read_pair(directory,root)
    c=plan['arm_configs'][arm]
    if not c['real_requests_authorized']:raise PermissionError('API switch remains OFF; no pair, arm or approval created')
    if fingerprint(plan)!=plan['pair_fingerprint']:raise ValueError('Pair config/P0/budget fingerprint changed')
    auth=approval(authorization_file,plan,root)
    if not os.environ.get(c['provider']['api_key_env']):raise ValueError('Credential environment variable absent')
    claim=auth.with_suffix('.claim.json')
    if not directory.exists():
        if claim.exists():raise PermissionError('Pair approval already claimed; inspect its original directory')
        directory.mkdir(parents=True,exist_ok=False)
        with claim.open('x') as f:json.dump({'pair_directory':str(directory),'pair_fingerprint':plan['pair_fingerprint']},f)
        write(directory/'Pair.json',plan);write(directory/'Pair.receipt.json',{'sha256':sha(directory/'Pair.json')})
    elif (not claim.exists() or read(claim)!={'pair_directory':str(directory),'pair_fingerprint':plan['pair_fingerprint']}):
        raise PermissionError('Pair claim mismatch; no automatic release or rebind')
    target=directory/arm
    other=directory/('B' if arm=='A' else 'A')
    if (other/'.coordinator.lock').exists():raise ValueError('Other arm has a writer/unknown lock; run arms sequentially')
    if target.exists():raise FileExistsError('Arm already exists; use status or safe resume, never ordinary relaunch')
    engine.prepare(target,c,imports=plan['shared_p0']['imports'])
    check_arm_binding(target,arm,plan)
    folder=target/'launch';folder.mkdir()
    # Each arm retains its own frozen config/source identity and shared-P0 receipt.
    write(folder/'shared_p0.json',plan['shared_p0']);write(folder/'pair.json',{'pair_fingerprint':plan['pair_fingerprint'],'arm':arm})
    for name in ('_search_reports.py','_real_run.py','_survival_ab.py'):
        (folder/name).write_bytes((root/'experiments/common'/name).read_bytes())
    (folder/Path(entry).name).write_bytes(Path(entry).read_bytes())
    # Existing resume/export helper expects an optional frozen baseline snapshot.
    write(folder/'baselines.json',plan['shared_p0']['baseline_snapshot'])
    if sha(folder/'baselines.json')!=plan['shared_p0']['baseline_snapshot_sha256']:raise ValueError('Frozen baseline serialization changed')
    write(folder/'postprocess.receipt.json',{'baselines_sha256':sha(folder/'baselines.json'),'helper_sha256':sha(folder/'_search_reports.py')})
    with (target/'terminal.log').open('x') as log,redirect_stdout(_Tee(sys.stdout,log)),redirect_stderr(_Tee(sys.stderr,log)):
        print(json.dumps({'arm':arm,'directory':str(target),'config':c,'shared_p0_sha256':plan['shared_p0_sha256']},ensure_ascii=False,indent=2))
        result=engine.run(target,allow_api=True,before_evolution=lambda d:p0_generation_gate(d,plan))
        if result['phase']=='blocked':
            print(json.dumps({'phase':'blocked','generation':result['generation'],
                              'notice':'Stopped; inspect checkpoint and launch/p0-recheck.json. No automatic retry.'}))
            return 2
        summary=export(target);finish(target,summary)
        certify_imported_p0(target,plan)
        print(json.dumps({'phase':summary['phase'],'generations':summary['generation'],'results':str(target/'exports')},ensure_ascii=False))
    return 0 if summary['phase']=='completed' else 2


def existing_arm(directory,arm,*,root,resume=False):
    plan=read_pair(directory,root)
    if arm not in POLICIES:raise ValueError('Explicit arm A or B required')
    if resume and (directory/('B' if arm=='A' else 'A')/'.coordinator.lock').exists():
        raise ValueError('Other arm is running or has an unknown writer lock')
    check_arm_binding(directory/arm,arm,plan)
    status=existing(directory/arm,root=root,resume=resume,
                    before_evolution=lambda d:p0_generation_gate(d,plan))
    certify_imported_p0(directory/arm,plan)
    return status


def check_arm_binding(directory,arm,plan):
    p=read(directory/'Protocol.json')
    if (p['config']!=plan['arm_configs'][arm] or p['source_files']!=plan['source_files']
        or p['imports']!=plan['shared_p0']['imports']):
        raise ValueError('Arm Protocol differs from its frozen pair config/source/P0')


def p0_generation_gate(directory,plan):
    passed=certify_imported_p0(directory,plan)
    state=read(directory/'checkpoint.json')
    path=directory/'launch/p0-before-generation.json'
    if not path.exists():
        write(path,{'passed':passed,'generation':state['generation'],
                    'generation_requests':state['generation_requests'],
                    'shared_p0_sha256':plan['shared_p0_sha256'],
                    'notice':'Checked before generation planning/reservation; no API request or solve in this gate.'})
    return passed


def certify_imported_p0(directory,plan):
    """Pre-generation gate (and export audit), never a re-solve or score seed."""
    state=read(directory/'checkpoint.json');path=directory/'populations/P000.json'
    if not path.exists():
        write(directory/'launch/p0-recheck.json',{'status':'not_complete','passed':False,'shared_p0_sha256':plan['shared_p0_sha256']})
        return False
    pop=read(path);expected={r['candidate_key']:r for r in plan['shared_p0']['reference_evaluations']}
    passed=(len(pop)==len(expected) and {r['candidate']['key'] for r in pop}==set(expected)
            and all(abs(r['fitness']-expected[r['candidate']['key']]['fitness'])<=1e-12
                    and r['behavior_sha256']==expected[r['candidate']['key']]['behavior_sha256'] for r in pop))
    write(directory/'launch/p0-recheck.json',{'status':'complete','passed':passed,
          'shared_p0_sha256':plan['shared_p0_sha256'],'new_generation_API_requests_for_P0':0,
          'notice':'Actual per-arm import reevaluations compared with frozen P0; historical scores were not seeded.'})
    if not passed and state['generation']>0:raise ValueError('Imported P0 results differ; do not treat this pair as comparable')
    return passed
