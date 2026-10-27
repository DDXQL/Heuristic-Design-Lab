"""Isolated, authorized continuation of the original ten B1 generation-2 slots.

No modification of frozen science or old records. prepare/check are offline;
run alone dispatches real requests. Execute from the prepared source snapshot.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import types

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research.evolution import select_parents, _tuple_tree
from fjsp_usage.research_real.assets import check_result, checked_candidate
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.config import fingerprint
from fjsp_usage.research_real.locking import RunLock
from tools import b1_ns_recovery as legacy
from tools import b1_timeout_boundary as boundary

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'B1-P1-to-P2-isolated-T15-v1-20261027'
ORIGIN_NAME = 'b1-ns-recovery-B-v1-20261022'
DEFAULT_NAME = 'b1-p1-to-p2-T15-seed501-20261027-v1'
ORIGIN_SHA = '565537b020173b30a6bd41d316228691892c500c8bcecb3266491d70193bcd72'
read, sha = legacy.read, legacy.sha


def files(folder):
    return {str(f.relative_to(folder)): sha(f) for f in sorted(folder.rglob('*'))
            if f.is_file() and '__pycache__' not in f.parts}


def frozen_state(c, j):
    cursor=c['cursor']; inherited=19+cursor
    if (c['phase'], c['generation'], c['init_cursor'], c['inflight']) != ('evolution', 1, 9, None) or cursor not in (0,4):
        raise ValueError('not the frozen P1 boundary')
    expected_children=[a['id'] for a in c['attempts'][19:] if a['status']=='valid']
    if ([x.get('id') for x in c['children']]!=expected_children or len(c['population']) != 5 or len(c['attempts']) != inherited):
        raise ValueError('P1 children/population/attempt counts differ')
    if len(j['requests']) != inherited or len(j['api_attempts']) != inherited or j['halt_reason']:
        raise ValueError('inherited budget differs')
    if any(v['status'] != 'completed' for v in c['evaluations'].values()):
        raise ValueError('unknown inherited evaluation')
    for ident, r in j['requests'].items():
        aid = r['accepted_attempt_id']; a = j['api_attempts'][aid]
        if (r['status'] != 'completed' or a['status'] != 'completed'
                or not a['send_confirmed'] or a['reply']['text'] != r['text']
                or r['prompt_key'] != digest({'prompt': r['prompt'], 'kind': 'U'})):
            raise ValueError('inherited request is not complete and bound: '+ident)


def migrate(c, j, config, transport_identity, context, target, h_order, phase):
    frozen_state(c, j)
    c, j = deepcopy(c), deepcopy(j)
    c['signature'] = digest({'arm': 'B', 'kind': 'U', 'config': asdict(config.u_search(501)),
        'H': h_order, 'context': context, 'transport': transport_identity, 'initial': None})
    j['recovery_source_P1'] = {'identity': j['identity'], 'requests':len(j['requests']), 'attempts':len(j['api_attempts'])}
    j['identity'] = digest({'version': j['version'], 'config': config.payload(),
        'context': context, 'transport': transport_identity, 'phase': phase,
        'journal_path': str((target/'batch_requests.json').resolve())})
    return {'checkpoint.json': c, 'batch_requests.json': j}


def prepare(directory, resume_from=None):
    directory = Path(directory).resolve()
    authorized_names={DEFAULT_NAME,DEFAULT_NAME[:-2]+'v2',DEFAULT_NAME[:-2]+'v3'}
    if directory.name not in authorized_names:
        raise ValueError('this tool binds only the three directories of this one user-authorized continuation; not a new-campaign authorization generator')
    if directory.parent != ROOT/'runs' or directory.exists():
        raise ValueError('new independent project run required; never overwrite')
    origin = Path(resume_from).resolve() if resume_from else ROOT/'runs'/ORIGIN_NAME
    p = read(origin/'Protocol.json')
    expected_origin_sha=sha(origin/'Protocol.json') if resume_from else ORIGIN_SHA
    if sha(origin/'Protocol.json') != expected_origin_sha or (origin/'.writer.lock').exists():
        raise ValueError('origin identity/writer differs')
    c, j = (read(origin/'r501/B'/n) for n in ('checkpoint.json', 'batch_requests.json'))
    frozen_state(c, j)
    if resume_from:
        stop=read(origin/'Safety_stop.json');key=stop['candidate']
        life=read(origin/'worker_evidence'/(key+'.lifecycle.json'))
        native=read(origin/'evaluation_receipts'/(key+'.json'))
        if (c['cursor']!=4 or stop['error']!='unexpected_worker_exit'
                or life['alive'] is not False or life['exitcode']!=-15 or life['trigger'] is not None
                or life['cleanup']!=['join_0.05','terminate'] or native['valid'] is not True
                or c['attempts'][-1]['status']!='invalid' or c['attempts'][-1]['code_key']!=key):
            raise BudgetStop('not the diagnosed normal-result cleanup race; cannot auto-continue')
        legacy.verify_worker_evidence(origin,key,{
            'worker_identity':{'before_sha256':sha(origin/'worker_evidence'/(key+'.before.json')),
                'after_sha256':sha(origin/'worker_evidence'/(key+'.after.json')),
                'loaded_identity':read(origin/'worker_evidence'/(key+'.before.json'))['identity']}})
    directory.mkdir()
    snapshot = directory/'source_snapshot'
    shutil.copytree(origin/'source_snapshot', snapshot)
    legacy.verify_files(snapshot,p['snapshot_files'])
    for folder in [snapshot,*[f for f in snapshot.rglob('*') if f.is_dir()]]:folder.chmod(0o755)
    for name in ('tools/b1_timeout_boundary.py', 'tools/b1_p1_resume.py',
                 'tools/b1_exit_grace.py',
                 'tests/test_b1_p1_resume.py', 'tests/test_b1_timeout_boundary.py',
                 'tests/test_b1_nonstream_local.py', 'tests/test_b1_usage_local.py'):
        (snapshot/name).parent.mkdir(parents=True,exist_ok=True)
        if (snapshot/name).exists():(snapshot/name).chmod(0o644)
        shutil.copyfile(ROOT/name, snapshot/name)
    legacy.verify_files(snapshot, p['original_pins'])
    origin_files = files(origin)
    for name, payload in [('checkpoint.json', c), ('batch_requests.json', j)]:
        atomic_json(directory/'inherited'/name, payload)
    # Existing certified population only: never re-evaluate the failed old child.
    for row in c['population']+c['children']:
        candidate = checked_candidate(row['candidate'], 'U')
        result = c['evaluations'][row['id']]['result']
        check_result(result, p['train_names'])
        if not result['valid'] or result['fitness'] != row['fitness']:
            raise ValueError('P1 result not certified')
        evidence_origin=origin
        for _ in range(4):
            if (evidence_origin/'worker_evidence'/(candidate.key+'.before.json')).exists():break
            ancestor=read(evidence_origin/'Protocol.json')
            evidence_origin=Path(ancestor['origin_directory'])
            if sha(evidence_origin/'Protocol.json')!=ancestor['origin_protocol_sha256']:
                raise BudgetStop('ancestor protocol mismatch')
        legacy.verify_worker_evidence(evidence_origin,candidate.key,result)
    for name in ('H_source_binding.json',):
        if (origin/name).exists(): shutil.copyfile(origin/name, directory/name)
    protocol = {**{k: p[k] for k in ('config', 'implementation', 'original_pins', 'train_names',
                    'H_order', 'dataset', 'credential_source', 'request_phase', 'request_policy')},
        'version': VERSION, 'run_directory': str(directory), 'source_snapshot': str(snapshot),
        'origin_directory': str(origin), 'origin_protocol_sha256':expected_origin_sha,
        'origin_files': origin_files, 'snapshot_files': files(snapshot),
        'critical_modules': list(dict.fromkeys(p['critical_modules']+['tools.b1_timeout_boundary', 'tools.b1_p1_resume']
            +(['tools.b1_exit_grace'] if resume_from else []))),
        'inherited_files': files(directory/'inherited'),
        'remaining_ids': [f'B/g0001/{i:06d}' for i in range(c['cursor'],10)],
        'inherited_logical_tasks':len(c['attempts']), 'inherited_api_attempts':len(j['api_attempts']),
        'baseline_P1_directory':p.get('baseline_P1_directory',p['origin_directory'] if resume_from else str(origin)),
        'new_logical_cap':10-c['cursor'], 'new_api_cap':(10-c['cursor'])*3, 'cumulative_logical_cap': 40,
        'cumulative_api_cap': 60, 'per_candidate_attempt_cap': 3,
        'new_instance_evaluation_cap':(10-c['cursor'])*21, 'new_solve_cap':(10-c['cursor'])*42,
        'window_seconds': 3600, 'task_start_reserve_seconds': 1260,
        'lifecycle_delta': ('same poll(15), recv; post-result normal exit grace 1s, then terminate/.5/kill/.5; normal exitcode=0 still required'
            if resume_from else 'same poll(15), recv and .05/.5/.5 cleanup; persist PID/exitcode/alive/actions'),
        'exit_grace_seconds':1.0 if resume_from else 0.05,
        'inherited_clock':read(origin/'Run_clock.json') if resume_from else None,
        'timeout_acceptance': 'only confirmed SIGTERM/SIGKILL timeout may be invalid-and-continue; otherwise Stop',
        'old_failure': 'unchanged invalid, missing final identity/termination; no prefix quality or retry',
        'analysis': 'all 10 slots incl failures; P0/P1/P2 mean and best; no prediction; train only',
        'scientific_change': None}
    atomic_json(directory/'Protocol.json', protocol)
    (directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    atomic_json(directory/'Authorization.json', {
        'approved': True, 'user_message': '好的，请继续补跑',
        'scope_context': '接续已认证P1，仅原第二代5 CROSS+5 MUTATE；最小安全接入验收；运行窗口60分钟；保留原预算及旧停止记录',
        'protocol_sha256': sha(directory/'Protocol.json'),
        'new_logical_cap':protocol['new_logical_cap'], 'new_api_cap':protocol['new_api_cap'], 'per_candidate_attempt_cap': 3,
        'inherited_logical_tasks':len(c['attempts']), 'overall_new_slot_cap_from_P1':10,
        'deadline_inherited_without_extension':bool(resume_from),
        'real_API_and_train21': True, 'no_push': True, 'created_utc': utc()})
    for tree in (snapshot, directory/'inherited'):
        for f in tree.rglob('*'):
            if f.is_file(): f.chmod(0o444)
    return {'prepared': str(directory), 'protocol_sha256': sha(directory/'Protocol.json')}


def utc():
    return datetime.now(timezone.utc).isoformat()


def identity_probe(pipe, protocol, members, instances, names, allowed_modes):
    """Real spawned process, source-attestation ONLY: no data/solver/provider."""
    before = legacy.source_attestation(protocol)
    after = legacy.source_attestation(protocol)
    pipe.send({'file': names[0], 'before': before, 'after': after})
    pipe.close()
    if protocol.get('exit_grace_seconds')==1.0:
        time.sleep(.2)  # Synthetic teardown AFTER full result: no scheduler work.


def offline_check(directory):
    p = check(directory, full_origin=True)
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join(str(ROOT/n) for n in ('code','.','tests')),
           'B1_RESUME_TEST_ORIGIN':p.get('baseline_P1_directory',p['origin_directory']),
           'B1_RESUME_TEST_PARTIAL':p['origin_directory'] if p['inherited_logical_tasks']==23 else ''}
    tests = subprocess.run([sys.executable,'-B','-m','unittest','test_b1_p1_resume',
                           'test_b1_timeout_boundary','-v'], cwd=ROOT, env=env,
                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (directory/'Offline_tests.log').write_text(tests.stdout)
    if tests.returncode: raise BudgetStop('offline tests failed; no formal run')
    expected = legacy.source_attestation(p)['identity']
    collect=collector_for(p)
    rows, failure, lifecycle = collect(mp.get_context('spawn'),
        identity_probe,p,(),(),('SYNTHETIC_IDENTITY_ONLY',),15,None,
        lambda x:atomic_json(directory/'Identity_probe_lifecycle.json',x))
    if failure or len(rows)!=1: raise BudgetStop('spawned identity-only probe failed')
    row = rows[0]
    atomic_json(directory/'Identity_probe.json',row)
    decision = boundary.classify_boundary({'valid':True,'fitness':-1},before=row['before'],after=row['after'],
        lifecycle=lifecycle,expected_identity=expected,expected_files=p['snapshot_files'],
        start_files=files(ROOT),end_files=files(ROOT))
    if decision['decision']!='original_result_checks_required':
        raise BudgetStop('spawned identity/lifecycle mismatch: '+decision['reason'])
    result={'passed':True,'protocol_sha256':sha(directory/'Protocol.json'),
        'test_log_sha256':sha(directory/'Offline_tests.log'),'identity_probe':decision,
        'real_API_requests':0,'FJSP_solves':0,'utc':utc()}
    atomic_json(directory/'Offline_acceptance.json',result)
    return result


def collector_for(p):
    if p.get('exit_grace_seconds',0.05)==1.0:
        from tools.b1_exit_grace import collect_with_exit_grace
        return collect_with_exit_grace
    return boundary.collect_with_lifecycle


def check(directory, full_origin=False):
    p = read(directory/'Protocol.json')
    if p['version'] != VERSION or sha(directory/'Protocol.json') != (directory/'Protocol.sha256').read_text().strip():
        raise BudgetStop('protocol identity mismatch')
    if str(directory) != p['run_directory'] or ROOT != Path(p['source_snapshot']):
        raise BudgetStop('run/check only from bound isolated snapshot')
    a = read(directory/'Authorization.json')
    if not a['approved'] or a['protocol_sha256'] != sha(directory/'Protocol.json'):
        raise BudgetStop('new authorization missing/different')
    legacy.verify_files(ROOT, p['snapshot_files'])
    legacy.verify_files(ROOT, p['original_pins'])
    legacy.verify_files(directory/'inherited', p['inherited_files'])
    if fingerprint(ROOT) != p['implementation']:
        raise BudgetStop('scientific runtime identity mismatch')
    origin = Path(p['origin_directory'])
    if (origin/'.writer.lock').exists(): raise BudgetStop('origin writer exists')
    selected = p['origin_files'] if full_origin else {k:p['origin_files'][k] for k in (
        'Protocol.json', 'r501/B/checkpoint.json', 'r501/B/batch_requests.json', 'Identity_stop.json',
        'Safety_stop.json', 'End.json') if k in p['origin_files']}
    legacy.verify_files(origin, selected)
    if full_origin and files(origin) != p['origin_files']:
        raise BudgetStop('origin file set changed')
    return p


def check_live(directory, p, starting=False):
    check(directory)
    if (directory/'Safety_stop.json').exists(): raise BudgetStop('persistent safety stop; review required')
    if (directory/'Stop.request').exists(): raise BudgetStop('safe boundary pause requested')
    clock = read(directory/'Run_clock.json')
    remaining = clock['deadline_unix']-time.time()
    if remaining < 0 or (starting and remaining < p['task_start_reserve_seconds']):
        raise BudgetStop('persisted time window/reserved task margin exhausted')
    q = directory/'r501/B/batch_requests.json'
    if q.exists():
        j = read(q); new = set(j['requests'])-set(read(directory/'inherited/batch_requests.json')['requests'])
        if not new <= set(p['remaining_ids']) or len(j['api_attempts'])-p['inherited_api_attempts'] > p['new_api_cap'] or len(j['requests']) > 29:
            raise BudgetStop('continuation budget or task identity differs')
        if any(x['status'] in ('pending', 'interrupted_unknown') for x in j['api_attempts'].values()):
            raise BudgetStop('unknown request; never retry blindly')


def make_evaluator(directory, p, config):
    dataset, _, members = legacy.ns.b1.b2.data_and_h(config, directory)
    if dataset.metadata != p['dataset'] or [m.key for m in members] != p['H_order']:
        raise BudgetStop('H/data identity mismatch')
    instances = dataset.load('train')
    from fjsp_usage.research_real import runtime
    from fjsp_usage.usage_v2 import execution

    def evaluate_inner(candidate):
        check(directory); dataset.verify('train')
        evidence = directory/'worker_evidence'/candidate.key
        if list(evidence.parent.glob(candidate.key+'.*.json')):
            raise BudgetStop('existing evaluation reservation; no repeat')
        expected = legacy.source_attestation(p, execution.construct_usage_schedule)['identity']
        start_files = {k: sha(ROOT/k) for k in p['snapshot_files']}
        os.environ['B1_NS_RECOVERY_RUN'] = str(directory)
        os.environ['B1_NS_RECOVERY_CANDIDATE'] = candidate.key
        def collector(target, c, h, data, names, timeout, allowed_modes=None):
            rows, failure, lifecycle = collector_for(p)(mp.get_context('spawn'),
                legacy.identity_worker, c, h, data, names, timeout, allowed_modes,
                lambda x: atomic_json(evidence.with_suffix('.lifecycle.json'), x))
            return rows, failure
        # Same evaluate bytecode and result checks; only its collector binding differs.
        delegated = types.FunctionType(runtime.evaluate.__code__,
            {**runtime.evaluate.__globals__, '_collect': collector}, 'evaluate')
        delegated.__kwdefaults__ = runtime.evaluate.__kwdefaults__
        try:
            result = delegated(candidate, members, instances, p['train_names'],
                timeout=15, diagnostics=False, allowed_modes=(0, 1))
            atomic_json(directory/'evaluation_receipts'/(candidate.key+'.json'), result)
            end_files = {k:sha(ROOT/k) for k in p['snapshot_files']}
            witness = lambda suffix: read(evidence.with_suffix(suffix)) if evidence.with_suffix(suffix).exists() else None
            classification = boundary.classify_boundary(result, before=witness('.before.json'),
                after=witness('.after.json'), lifecycle=witness('.lifecycle.json'),
                expected_identity=expected, expected_files=p['snapshot_files'], start_files=start_files,
                end_files=end_files, worker_failure=evidence.with_suffix('.failure.json').exists())
            atomic_json(evidence.with_suffix('.classification.json'), classification)
            if classification['decision'] == 'stop': raise BudgetStop(classification['reason'])
            check_result(result, p['train_names'])
            if result['valid']:
                legacy.verify_files(ROOT, p['original_pins'])
                result['worker_identity'] = {'before_sha256': sha(evidence.with_suffix('.before.json')),
                    'after_sha256': sha(evidence.with_suffix('.after.json')), 'loaded_identity': expected}
                for row in result['instances']:
                    if row.get('captured_solves') != 2 or row.get('physical_schedule_sha256') != row.get('recheck_physical_schedule_sha256'):
                        raise BudgetStop('solve/recheck schedule identity differs')
            result['lifecycle_classification'] = classification
            atomic_json(directory/'evaluation_receipts'/(candidate.key+'.json'), result)
            return result
        except BaseException as exc:
            atomic_json(directory/'Safety_stop.json', {'candidate':candidate.key,
                'error_type':type(exc).__name__, 'error':str(exc)[:1000], 'utc':utc()})
            raise
    def evaluate(candidate):
        try:
            return evaluate_inner(candidate)
        except BaseException as exc:
            atomic_json(directory/'Safety_stop.json', {'candidate': candidate.key,
                'error_type': type(exc).__name__, 'error': str(exc)[:1000], 'utc': utc()})
            raise
    return evaluate, members


class ResumeSearch(legacy.ns.NSSearch):
    def _prepare(self, *, initial):
        if initial or self.state['generation'] != 1:
            raise BudgetStop('only generation 2 is authorized')
        check_live(self.directory.parents[1], self.resume_protocol, starting=True)
        super()._prepare(initial=initial)

    def _attempt(self):
        super()._attempt()
        if (self.directory.parents[1]/'Safety_stop.json').exists():
            raise BudgetStop('candidate recorded; persistent safety stop')


def transport_for(directory, config):
    from fjsp_usage.research_real.real_transport import JsonCandidateTransport
    profile = legacy.ns.CompleteNonstreamTransport(JsonCandidateTransport(config), directory/'received_responses')
    return legacy.ns.TimedRecorder(profile, directory/'wire_responses', lambda: check(directory))


def run(directory):
    p = check(directory, full_origin=True)
    acceptance=read(directory/'Offline_acceptance.json')
    if (not acceptance.get('passed') or acceptance['protocol_sha256']!=sha(directory/'Protocol.json')
            or acceptance['test_log_sha256']!=sha(directory/'Offline_tests.log')):
        raise BudgetStop('offline acceptance required')
    if (directory/'.writer.lock').exists(): raise BudgetStop('existing lock; never auto-clear')
    with RunLock(directory):
        cpath = directory/'Run_clock.json'
        if not cpath.exists():
            started = time.time()
            atomic_json(cpath, p.get('inherited_clock') or {'started_unix': started, 'deadline_unix': started+p['window_seconds'],
                'started_utc':utc(), 'window_seconds':p['window_seconds'], 'restart_resets':False})
        check_live(directory, p)
        from fjsp_usage.research_real.leafapi import load_local_key, KEY_ENV
        os.environ[KEY_ENV] = load_local_key(p['credential_source'])
        config = replace(legacy.ns.Config.from_dict(p['config']), real_requests_authorized=True)
        transport = transport_for(directory, config)
        target = directory/'r501/B'; target.mkdir(parents=True, exist_ok=True)
        if not (directory/'Migration_complete.json').exists():
            c, j = read(directory/'inherited/checkpoint.json'), read(directory/'inherited/batch_requests.json')
            bundle = migrate(c, j, config, transport.identity, sha(directory/'Protocol.json'),
                target, p['H_order'], p['request_phase'])
            pending = directory/'Migration_bundle.json'
            if pending.exists() and read(pending) != bundle: raise BudgetStop('migration plan differs')
            if not pending.exists(): atomic_json(pending, bundle)
            for name, value in bundle.items():
                if (target/name).exists() and read(target/name) != value:
                    raise BudgetStop('uncertain migration; never overwrite')
                if not (target/name).exists(): atomic_json(target/name, value)
            atomic_json(directory/'Migration_complete.json', {'bundle_sha256':sha(pending), 'utc':utc()})
        else:
            if read(directory/'Migration_complete.json')['bundle_sha256'] != sha(directory/'Migration_bundle.json'):
                raise BudgetStop('migration evidence differs')
            c = read(target/'checkpoint.json')
            if c['inflight'] or any(v['status'] == 'pending' for v in c['evaluations'].values()):
                raise BudgetStop('unknown evaluation/request reservation; manual review required')
        evaluate, members = make_evaluator(directory, p, config)
        engine = ResumeSearch(target, experiment=config, training_names=p['train_names'],
            verify=lambda:check_live(directory,p), arm='B', config=config.u_search(501), members=members,
            evaluator=evaluate, transport=transport, context=sha(directory/'Protocol.json'))
        engine.resume_protocol = p
        inhibitor = None
        if shutil.which('caffeinate'):
            inhibitor = subprocess.Popen(['caffeinate','-i','-w',str(os.getpid())])
        started = time.monotonic()
        try:
            engine.run()
            check(directory, full_origin=True)
            atomic_json(directory/'End.json', {'status':engine.state['phase'], 'utc':utc(),
                'elapsed_seconds':time.monotonic()-started})
        except BaseException as exc:
            atomic_json(directory/'End.json', {'status':'stopped', 'utc':utc(),
                'error_type':type(exc).__name__, 'error':str(exc)[:1000], 'elapsed_seconds':time.monotonic()-started})
            raise
        finally:
            if inhibitor is not None:
                inhibitor.terminate(); inhibitor.wait(timeout=5)
            atomic_json(directory/'Search_status.json',engine.report())
            atomic_json(directory/'Final_or_partial_population.json',engine.export_rows())
            report(directory)


def report(directory):
    import csv
    from statistics import fmean
    c = read(directory/'r501/B/checkpoint.json')
    j = read(directory/'r501/B/batch_requests.json')
    old = read(directory/'inherited/checkpoint.json')
    out = directory/'results'; out.mkdir(exist_ok=True)
    populations = {'P0':old['population_snapshots']['P0'], 'P1':old['population']}
    if c['phase'] == 'completed' and c['generation'] == 2: populations['P2'] = c['population']
    metrics = {k:{'best':max(x['fitness'] for x in v), 'mean':fmean(x['fitness'] for x in v),
        'ids':[x['id'] for x in v]} for k,v in populations.items()}
    new = c['attempts'][19:]
    summary = {'status':c['phase'], 'generation':c['generation'], 'new_slots':len(new),
        'cumulative_slots':len(c['attempts']), 'cumulative_api_attempts':len(j['api_attempts']),
        'new_api_attempts':len(j['api_attempts'])-19, 'new_valid':sum(x['status']=='valid' for x in new),
        'outcomes':new, 'populations':metrics, 'new_evaluations':len(c['evaluations'])-len(old['evaluations']),
        'api_input_tokens':sum((x.get('usage') or {}).get('input_tokens',0) for x in list(j['api_attempts'].values())[19:]),
        'api_output_tokens':sum((x.get('usage') or {}).get('output_tokens',0) for x in list(j['api_attempts'].values())[19:]),
        'verified_monetary_cost':None, 'cost_note':'Token按返回记录；未知账单不填零',
        'protocol_sha256':sha(directory/'Protocol.json'), 'prediction_used':False}
    atomic_json(out/'Summary.json',summary)
    with (out/'Candidates.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=['id','operator','parents','status','fitness','code_key','error_type'])
        w.writeheader()
        for a in c['attempts']:
            w.writerow({k:(c['evaluations'].get(a['id'],{}).get('result',{}).get('fitness') if k=='fitness' else a.get(k)) for k in w.fieldnames})
    with (out/'Instances.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=['id','file','makespan','lower_bound','score','physical_schedule_sha256',
            'single_solve_seconds','deterministic_recheck_seconds']); w.writeheader()
        for ident, cache in c['evaluations'].items():
            for row in cache['result'].get('instances',[]):
                w.writerow({k:ident if k=='id' else row.get(k) for k in w.fieldnames})
    (out/'REPORT_ZH.md').write_text('# 10成员自由搜索：原第二代接续结果\n\n'
        +'本报告只汇总真实记录，不含预测。旧超时与停止记录保持不变。\n\n'
        +f"状态：{c['phase']}；新增逻辑槽{len(new)}/10；新增API尝试{summary['new_api_attempts']}/30。\n\n"
        +'|种群|冠军Fitness|平均Fitness|\n|---|---:|---:|\n'
        +''.join(f"|{k}|{v['best']:.12f}|{v['mean']:.12f}|\n" for k,v in metrics.items())
        +'\nFitness为完整train21平均−Cmax/LB，越大越好。种群均值改善不等于冠军改善；本实验不支持训练外泛化结论。\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare','check','offline-check','run','report'))
    parser.add_argument('--run-dir',type=Path,default=ROOT/'runs'/DEFAULT_NAME)
    parser.add_argument('--resume-from',type=Path)
    args=parser.parse_args(); d=args.run_dir.resolve()
    if args.stage=='prepare': print(prepare(d,args.resume_from))
    elif args.stage=='check': print({'passed':bool(check(d,full_origin=True))})
    elif args.stage=='offline-check': print(offline_check(d))
    elif args.stage=='report': print(json.dumps(report(d),ensure_ascii=False))
    else: run(d)


if __name__=='__main__': main()
