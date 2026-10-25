"""Fixed progress-step H0/H1 family. Local-only certified T30 evaluation.

Independent entry: accept -> prepare -> check -> launch (one shot) -> report.
Never changes a frozen experiment or imports a model client. Unknown reservation,
identity/exit/recheck mismatch or clock gap stops; no automatic retries.
"""
import argparse
from dataclasses import asdict
import importlib
import inspect
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import random
import signal
from statistics import fmean
import subprocess
import sys
import time
import types

from fjsp_usage.research.candidates import validate_code, compile_candidate, U_ARGS
from fjsp_usage.research.events import atomic_json as write
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import checked_candidate
from fjsp_usage.usage_v2 import VERSION as INTERFACE
from fjsp_usage.usage_v2.execution import construct_usage_schedule
from fjsp_usage.baseline_supplemental.lifecycle import collect, classify
from fjsp_usage.baseline_a.validation import validate_result
from tools import baseline_a_supplemental as old

ROOT = Path(__file__).resolve().parents[1]
NAME = 'h01-progress-step-train21-seed501-20261025-v1'
RUN = ROOT / 'runs' / NAME
REPORT = ROOT / 'reports' / NAME
B2 = ROOT / 'runs/h01-state-weight-search-seed501-batch-v3-20261020'
MODULE = 'tools.h01_progress_baseline'
EXTRA = ('tools/h01_progress_baseline.py', 'tools/h01_progress_report.py',
         'tests/test_h01_progress_baseline.py', 'docs/H01_PROGRESS_STEP_PROTOCOL_V1.md')
read = old.v2.read
sha = old.v2.sha


def now():
    return {'wall': time.time(), 'monotonic': time.monotonic(), 'CPU': time.process_time()}


def rules():
    rows = []
    for a in (0., .5, 1.):
        rows.append({'id': f'STATIC_a{int(100*a):03d}', 'tau': None,
                     'alpha_before': a, 'alpha_after': a, 'dynamic': False})
    for t in (.25, .5, .75):
        for a in (0., .5, 1.):
            for b in (0., .5, 1.):
                if a != b:
                    rows.append({'id': f'T{int(100*t):02d}_a{int(100*a):03d}_b{int(100*b):03d}',
                                 'tau': t, 'alpha_before': a, 'alpha_after': b, 'dynamic': True})
    for row in rows:
        if row['dynamic']:
            body = (f"    if progress < {row['tau']!r}:\n        alpha = {row['alpha_before']!r}\n"
                    f"    else:\n        alpha = {row['alpha_after']!r}\n")
        else:
            body = f"    alpha = {row['alpha_before']!r}\n"
        code = 'def use_heuristics(' + ', '.join(U_ARGS) + '):\n' + body
        code += '    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))\n'
        row['candidate'] = asdict(validate_code(code, kind='U', interface_version=INTERFACE,
                                                member_count=10, description='Frozen progress-step baseline'))
    return rows


def aliases():
    return [{'tau': t, 'alpha_before': a, 'alpha_after': b,
             'canonical_id': f'STATIC_a{int(100*a):03d}' if a == b else
             f'T{int(100*t):02d}_a{int(100*a):03d}_b{int(100*b):03d}'}
            for t in (.25, .5, .75) for a in (0., .5, 1.) for b in (0., .5, 1.)]


def attest(module_name, p):
    module = importlib.import_module(module_name)
    path = Path(module.__file__).resolve(); relative = str(path.relative_to(ROOT))
    if sha(path) != p['source_files'][relative]: raise ValueError('source hash mismatch: ' + relative)
    top = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True, optimize=0)
    defs = {c.co_name: c for c in top.co_consts if isinstance(c, types.CodeType)}
    functions = {}
    for name, fn in vars(module).items():
        if inspect.isfunction(fn) and fn.__module__ == module_name:
            if name not in defs or old.v2.code_identity(fn.__code__) != old.v2.code_identity(defs[name]):
                raise ValueError('loaded function changed: ' + name)
            functions[name] = old.v2.code_identity(fn.__code__)
    return {'file': str(path), 'source_sha256': sha(path), 'loaded_functions': functions}


def witness(p):
    modules = old.witness(p)['modules']
    for name in (MODULE, 'fjsp_usage.usage_v2.execution'):
        modules[name] = attest(name, p)
    return {'pid': os.getpid(), 'modules': modules, 'identity': digest(modules)}


def accept():
    import unittest
    REPORT.mkdir(exist_ok=True)
    if (REPORT / 'Offline_acceptance.json').exists(): raise ValueError('acceptance already exists')
    suite = unittest.defaultTestLoader.loadTestsFromName('tests.test_h01_progress_baseline')
    with (REPORT / 'Offline_acceptance.log').open('w') as f:
        result = unittest.TextTestRunner(stream=f, verbosity=2).run(suite)
    write(REPORT / 'Offline_acceptance.json', {'passed': result.wasSuccessful(), 'tests': result.testsRun,
          'failures': len(result.failures), 'errors': len(result.errors),
          'files': {n: sha(ROOT/n) for n in EXTRA}, 'formal_solves': 0, 'API': 0,
          'scope': 'pure output/boundary checks, toy V1 equivalence, existing T30 synthetic lifecycle tests'})
    if not result.wasSuccessful(): raise ValueError('offline tests failed')


def prepare():
    if RUN.exists(): raise ValueError('no overwrite or re-prepare')
    acceptance = read(REPORT / 'Offline_acceptance.json')
    if not acceptance['passed'] or any(sha(ROOT/n) != h for n,h in acceptance['files'].items()):
        raise ValueError('accepted implementation changed')
    origin = old.check(old.DEFAULT)
    frozen = read(old.DEFAULT / 'H_frozen.json'); plan = read(B2 / 'Plan.json')
    if frozen['members'] != read(B2/'H_frozen.json')['members'] or origin['H_order'] != plan['H_order']:
        raise ValueError('B2 H/order mismatch')
    if [r['file'] for r in origin['instances']] != plan['names']: raise ValueError('train order mismatch')
    config = read(B2 / 'Protocol.json')['config']
    if config['seeds'] != [501] or config['population_size'] != 5: raise ValueError('B2 seed/N changed')
    core = ('code/fjsp_usage/offline_v2.py', 'code/fjsp_usage/usage_v2/execution.py',
            'code/fjsp_usage/research/candidates.py', 'code/llm4ad/task/optimization/fjsp_set/instances.py',
            'code/llm4ad/task/optimization/fjsp_set/scheduler.py')
    for n in core:
        if sha(ROOT/n) != plan['pins'][n]: raise ValueError('B2 scientific kernel changed: ' + n)
    hashes = read(ROOT/'reports'/B2.name/'Original_result_hashes.json')
    b2cp = B2/'r501/B/checkpoint.json'
    if sha(b2cp) != hashes[str(b2cp.relative_to(ROOT))]: raise ValueError('B2 raw checkpoint changed')
    cp = read(b2cp); champ = max(cp['population'], key=lambda r: r['fitness'])
    checked_candidate(champ['candidate'], 'U'); champion = cp['evaluations'][champ['id']]['result']
    validate_result(champion, origin['instances'], 'legacy_pair')
    if champ['fitness'] != champion['fitness']: raise ValueError('B2 binding mismatch')
    RUN.mkdir(); (RUN/'cache').mkdir(); (RUN/'references').mkdir(); (RUN/'sources').mkdir()
    (RUN/'inputs/train').mkdir(parents=True)
    (RUN/'H_frozen.json').write_bytes((old.DEFAULT/'H_frozen.json').read_bytes())
    for r in origin['instances']:
        (RUN/r['relative_path']).write_bytes((old.DEFAULT/r['relative_path']).read_bytes())
    definitions = rules(); write(RUN/'Rules.json', definitions); write(RUN/'Aliases_27.json', aliases())
    for row in definitions: (RUN/'sources'/(row['id']+'.py')).write_text(row['candidate']['code'])
    cache = {}; protected = {}
    for n in ('Protocol.json', 'Protocol.sha256', 'checkpoint.json', 'H_frozen.json', 'Expected_loaded_identity.json'):
        f = old.DEFAULT/n; protected[str(f.relative_to(ROOT))] = sha(f)
    oldstate = read(old.DEFAULT/'checkpoint.json')
    for identifier, source_id in [('STATIC_a050', 'H0_H1_WS'), ('STATIC_a100', 'H0')]:
        entry = oldstate['strategies'][source_id]; path = old.DEFAULT/entry['result_path']; result = read(path)
        if sha(path) != entry['result_sha256']: raise ValueError('static cache changed')
        validate_result(result, origin['instances'], 'modern')
        expected = {**origin['source_files'], **origin['protected_files']}
        folder = path.parent
        boundary = classify(result, before=read(folder/'before.json'), after=read(folder/'after.json'),
            lifecycle=read(folder/'lifecycle.json'), expected_identity=read(old.DEFAULT/'Expected_loaded_identity.json')['identity'],
            expected_files=expected, start_files=expected, end_files=expected)
        if boundary['decision'] != 'accepted': raise ValueError('static terminal receipt not certified')
        for n in ('result.json','before.json','after.json','lifecycle.json'):
            f = folder/n; protected[str(f.relative_to(ROOT))] = sha(f)
        (RUN/'cache'/(identifier+'.json')).write_bytes(path.read_bytes())
        cache[identifier] = {'source': str(path.relative_to(ROOT)), 'sha256': sha(path),
                             'result_path': 'cache/'+identifier+'.json', 'level': 'modern_T30'}
    base = ROOT/'runs/tier2-baseline-a-train21-seed501-20261024-v1'
    h1entry = read(base/'checkpoint.json')['strategies']['H1']; h1path = base/h1entry['result_path']
    if sha(h1path) != h1entry['result_sha256']: raise ValueError('legacy H1 result changed')
    h1 = read(h1path); validate_result(h1, origin['instances'], 'legacy_single')
    write(RUN/'references/H1_legacy.json', h1)
    write(RUN/'references/B2_champion.json', {'parent': champ, 'result': champion})
    for f in (B2/'Plan.json', B2/'Protocol.json', B2/'H_frozen.json', b2cp,
              ROOT/'reports'/B2.name/'Original_result_hashes.json', h1path):
        protected[str(f.relative_to(ROOT))] = sha(f)
    protected[str((REPORT/'Offline_acceptance.json').relative_to(ROOT))] = sha(REPORT/'Offline_acceptance.json')
    assets = {str(f.relative_to(RUN)): sha(f) for f in RUN.rglob('*') if f.is_file()}
    authority = {'origin': 'current human task H0/H1简单动态权重基线：实现并执行, continued after interruption',
                 'authorized': True, 'max_canonical_strategies': 21, 'max_program_instances': 441,
                 'max_solve_passes': 882, 'API': 0, 'holdout': 0, 'launch_window_seconds': 21600,
                 'no_A4_no_CROSS_no_push_no_extra_rules': True}
    write(RUN/'Authorization.json', authority)
    p = {'version': NAME, 'base_commit': '7dc57aa13aba7e1c7ddd6aa92e5eea68b8a61529',
         'seed': 501, 'historical_population_N': 5, 'N_note': 'N5 historical population; fixed-policy evaluation has no population selection',
         'instances': origin['instances'], 'H_order': origin['H_order'], 'cache': cache,
         'source_files': {**origin['source_files'], **acceptance['files']}, 'protected_files': protected,
         'assets': assets, 'authorization_sha256': sha(RUN/'Authorization.json'),
         'rule_ids': [r['id'] for r in definitions], 'logical_count': 21,
         'effective_new_evaluation_cap': 399, 'effective_new_solve_pass_cap': 798,
         'absolute_evaluation_cap': 441, 'absolute_solve_pass_cap': 882,
         'result_wait_seconds': 30, 'exit_grace_seconds': 2., 'launch_seconds': 21600,
         'science': 'p=scheduled count/total count; p<tau before else after; MIX H0=alpha,H1=1-alpha; single support raw scores; dual independently minmax; action job/machine first maximum; complete mean(-Cmax/unrounded LB)',
         'order': 'three canonical statics alpha ascending, then tau/before/after ascending with unequal before/after; frozen before evaluation',
         'failure': 'any failed instance => null; confirmed T30 terminated timeout continue other fixed policies; unknown source/recheck/exit/reservation/budget STOP; no retry',
         'clock': 'wall-monotonic delta discrepancy >2s quarantines active result; persistent 6h limit new policy starts only; never reset',
         'diagnostic': 'same two solves record actual U progress and raw H0/H1 weights; no diagnostic solves or extra U/H calls',
         'H1_cache_excluded': 'legacy native double solve accepted historically; lacks modern terminal receipt; run H1 once at T30; do not invalidate or rewrite historical record',
         'B2_reference': {'id': champ['id'], 'key': champ['candidate']['key'], 'fitness': champion['fitness'],
                          'resource': 'legacy T15, native/physical recheck; not contemporaneous lifecycle/cost',
                          'scientific_core_identical': True, 'config_seed': 501, 'population_N': 5},
         'API_cap': 0, 'holdout_access': False, 'analysis': 'all21 incl failures, dynamic18 comparisons vs equal/B2, per-instance Cmax and normalized contributions; no efficiency/generality claim'}
    write(RUN/'Protocol.json', p); (RUN/'Protocol.sha256').write_text(sha(RUN/'Protocol.json')+'\n')
    write(RUN/'Expected_loaded_identity.json', witness(p))
    state = {'protocol_sha256': sha(RUN/'Protocol.json'), 'phase': 'prepared', 'strategies': {}}
    for id, r in cache.items():
        state['strategies'][id] = {'status': 'completed', 'origin': 'cache',
            'result_path': r['result_path'], 'result_sha256': r['sha256'], 'reserved_instances': 0, 'reserved_solves': 0}
    write(RUN/'checkpoint.json', state); check(); print('FROZEN', sha(RUN/'Protocol.json'), flush=True)


def check():
    p = read(RUN/'Protocol.json')
    if sha(RUN/'Protocol.json') != (RUN/'Protocol.sha256').read_text().strip(): raise ValueError('protocol identity')
    for n,h in {**p['source_files'], **p['protected_files']}.items():
        if sha(ROOT/n) != h: raise ValueError('source/provenance changed: ' + n)
    for n,h in p['assets'].items():
        if sha(RUN/n) != h: raise ValueError('frozen asset changed: ' + n)
    if sha(RUN/'Authorization.json') != p['authorization_sha256']: raise ValueError('authorization identity')
    if read(RUN/'Rules.json') != rules() or read(RUN/'Aliases_27.json') != aliases(): raise ValueError('family changed')
    if p['rule_ids'] != [r['id'] for r in rules()] or p['seed'] != 501: raise ValueError('order/seed')
    if witness(p)['identity'] != read(RUN/'Expected_loaded_identity.json')['identity']: raise ValueError('loaded identity')
    return p


def ledger(state, p):
    if state['protocol_sha256'] != sha(RUN/'Protocol.json'): raise ValueError('checkpoint protocol')
    if not set(state['strategies']) <= set(p['rule_ids']): raise ValueError('unknown strategy')
    new = 0
    for id, r in state['strategies'].items():
        if r['status'] != 'completed': raise ValueError('unknown reservation, no replay: '+id)
        expected = (0, 0) if id in p['cache'] else (21, 42)
        if (r['reserved_instances'], r['reserved_solves']) != expected: raise ValueError('budget ledger mismatch')
        path = RUN/r['result_path']
        if not path.resolve().is_relative_to(RUN) or sha(path) != r['result_sha256']: raise ValueError('result identity')
        validate_result(read(path), p['instances'], 'modern')
        if id not in p['cache']: new += 21
    if new > p['effective_new_evaluation_cap']: raise ValueError('budget exceeded')
    return new


def worker(pipe, payload, members, instances, names, allowed_modes):
    p = payload['protocol']; spec = payload['spec']; folder = Path(payload['folder'])
    os.environ.pop('LEAFAPI_API_KEY', None)
    network = old.v2.local_guard(payload['train_paths'])
    try:
        write(folder/'before.json', witness(p)); random.seed(501)
        hs = tuple(compile_candidate(h) for h in members)
        u = compile_candidate(checked_candidate(spec['candidate'], 'U'))
        for name, instance in zip(names, instances):
            stem = folder/Path(name).stem; phase = {'file': name, 'first_started': True,
                'recheck_started': False, 'completed': False}; old.phase(stem, phase, 'first_start')
            records = []; costs = []
            def observed(*args):
                out = u(*args); records.append([args[0], out[1][0], out[1][1]]); return out
            t = time.perf_counter(); first = construct_usage_schedule(instance, hs, observed, cost=costs.append)
            first_seconds = time.perf_counter()-t; saved = records[:]; firstcost = costs[:]
            phase.update(first_completed=True, recheck_started=True); old.phase(stem, phase, 'first_end')
            records.clear(); costs.clear(); old.phase(stem, phase, 'recheck_start'); t = time.perf_counter()
            second = construct_usage_schedule(instance, hs, observed, cost=costs.append)
            second_seconds = time.perf_counter()-t; old.phase(stem, phase, 'recheck_end')
            if first != second or saved != records: raise ValueError('complete solve/recheck or progress mismatch')
            total = len(saved)
            if total != sum(len(job) for job in instance.jobs): raise ValueError('operation count mismatch')
            for k, (progress, a, b) in enumerate(saved):
                expected = spec['alpha_before'] if not spec['dynamic'] or progress < spec['tau'] else spec['alpha_after']
                if progress != k/total or (a,b) != (expected, 1-expected): raise ValueError('actual U progress/weight mismatch')
            physical = old.v2.physical(first.schedule)
            row = {'file': name, 'makespan': first.schedule.makespan, 'lower_bound': first.lower_bound,
                'score': first.score, 'feasible': True, 'captured_solves': 2,
                'single_solve_seconds': first_seconds, 'deterministic_recheck_seconds': second_seconds,
                'single_h_calls': list(first.member_calls), 'recheck_h_calls': list(second.member_calls),
                'physical_schedule': physical, 'physical_schedule_sha256': digest(physical),
                'recheck_physical_schedule_sha256': digest(old.v2.physical(second.schedule)),
                'commit_sequence_sha256': digest(asdict(first.schedule)),
                'observed_progress_H0_H1': saved, 'recheck_progress_weights_sha256': digest(records),
                'progress_weights_sha256': digest(saved), 'decision_weights_sha256': digest(first.decisions),
                'before_steps': sum(x[0] < spec['tau'] for x in saved) if spec['dynamic'] else None,
                'after_steps': sum(x[0] >= spec['tau'] for x in saved) if spec['dynamic'] else None,
                'actual_weight_changes': sum(a[1:] != b[1:] for a,b in zip(saved,saved[1:])),
                'cost_first': {k: sum(r[k] for r in firstcost) for k in firstcost[0]},
                'cost_recheck': {k: sum(r[k] for r in costs) for k in costs[0]}, 'network_guard': dict(network)}
            write(stem.with_suffix('.result.json'), row); phase['completed'] = True; old.phase(stem, phase, 'result_write_end')
            if name == names[-1]: write(folder/'after.json', witness(p))
            pipe.send(row)
    except BaseException as exc:
        write(folder/'worker_failure.json', {'error_type': type(exc).__name__, 'error': str(exc)[:1000]})
        write(folder/'after.json', witness(p)); pipe.send({'error_type': type(exc).__name__, 'error': str(exc)[:1000]})
    finally:
        try: write(folder/'network_guard.json', network)
        finally: pipe.close()


def event(kind, **data):
    with (RUN/'Events.jsonl').open('a') as f:
        f.write(json.dumps({'event': kind, **now(), **data})+'\n'); f.flush(); os.fsync(f.fileno())


def run():
    p = check()
    if (RUN/'End_summary.json').exists(): return
    if (RUN/'Stop.json').exists(): raise ValueError('persistent stop')
    fd = os.open(RUN/'.execution.lock', os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
    with os.fdopen(fd,'w') as f: json.dump({'pid': os.getpid(), 'start': now()},f)
    signal.signal(signal.SIGHUP, signal.SIG_IGN); keep = None; normal = False
    state = read(RUN/'checkpoint.json')
    try:
        ledger(state,p)
        if not (RUN/'Run_clock.json').exists():
            if state.get('clock_sha256'): raise ValueError('persistent clock missing')
            start = now(); write(RUN/'Run_clock.json', {'start': start, 'deadline': start['wall']+21600})
            state['clock_sha256'] = sha(RUN/'Run_clock.json'); write(RUN/'checkpoint.json',state)
        if sha(RUN/'Run_clock.json') != state['clock_sha256']: raise ValueError('clock identity')
        clock = read(RUN/'Run_clock.json')
        if clock['deadline'] != clock['start']['wall']+21600: raise ValueError('time budget changed')
        guard = old.v2.local_guard([RUN/r['relative_path'] for r in p['instances']])
        keep = subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        write(RUN/'Run_identity.json', {'pid': os.getpid(), 'ppid': os.getppid(), 'sid': os.getsid(0), 'start': now()})
        members = tuple(checked_candidate(m['candidate'],'h') for m in read(RUN/'H_frozen.json')['members'])
        paths = [RUN/r['relative_path'] for r in p['instances']]
        instances = tuple(old.v2.load_instance(x) for x in paths); names = [r['file'] for r in p['instances']]
        event('started', deadline=clock['deadline'])
        for spec in read(RUN/'Rules.json'):
            id = spec['id']
            if id in state['strategies']: continue
            check(); used = ledger(state,p)
            if time.time() >= clock['deadline']: state['phase']='deadline_partial'; break
            if (RUN/'Pause_request.json').exists(): state['phase']='paused_boundary'; break
            if used+21 > p['effective_new_evaluation_cap']: raise ValueError('budget exceeded before start')
            folder = RUN/'evidence'/id; folder.mkdir(parents=True,exist_ok=False)
            state['phase']='running'; state['strategies'][id]={'status':'reserved','origin':'new',
                                                           'reserved_instances':21,'reserved_solves':42}
            write(RUN/'checkpoint.json',state); event('reserved',id=id)
            expected={**p['source_files'], **p['protected_files']}; before={n:sha(ROOT/n) for n in expected}; t=now()
            rows, failure, life = collect(mp.get_context('spawn'), worker,
                {'protocol':p,'spec':spec,'folder':str(folder),'train_paths':[str(x) for x in paths]},
                members,instances,names,30,(0,1),lambda r:write(folder/'lifecycle.json',r))
            result={'valid':failure is None,'fitness':fmean(r['score'] for r in rows) if failure is None else None,
                    'total_instances':21,'instances':rows,'primary_evaluation_seconds':time.monotonic()-t['monotonic'],**(failure or {})}
            write(folder/'raw_result.json',result)
            boundary=classify(result,before=read(folder/'before.json') if (folder/'before.json').exists() else None,
                after=read(folder/'after.json') if (folder/'after.json').exists() else None,lifecycle=life,
                expected_identity=read(RUN/'Expected_loaded_identity.json')['identity'],expected_files=expected,
                start_files=before,end_files={n:sha(ROOT/n) for n in expected},worker_failure=(folder/'worker_failure.json').exists())
            write(folder/'boundary.json',boundary)
            if boundary['decision']=='stop': raise ValueError('boundary stop: '+boundary['reason'])
            validate_result(result,p['instances'],'modern'); check(); end=now()
            gap=(end['wall']-t['wall'])-(end['monotonic']-t['monotonic'])
            if abs(gap)>2:
                write(folder/'Clock_quarantine.json',{'before':t,'after':end,'gap':gap,'accepted':False})
                raise ValueError('clock gap; no auto re-evaluation')
            if id=='STATIC_a000' and result['valid']:
                legacy=read(RUN/'references/H1_legacy.json')
                if [(r['makespan'],r['score']) for r in rows] != [(r['makespan'],r['score']) for r in legacy['instances']]:
                    raise ValueError('H1 historical quality mismatch')
            result['boundary']=boundary; write(folder/'result.json',result)
            state['strategies'][id].update(status='completed',result_path=str((folder/'result.json').relative_to(RUN)),
                                           result_sha256=sha(folder/'result.json'))
            write(RUN/'checkpoint.json',state); event('committed',id=id,valid=result['valid'],fitness=result['fitness'])
        else: state['phase']='completed'
        write(RUN/'checkpoint.json',state); ledger(state,p); write(RUN/'Network_guard.json',guard); normal=True
    except BaseException as exc:
        state['phase']='stopped'; write(RUN/'checkpoint.json',state)
        write(RUN/'Stop.json',{'error_type':type(exc).__name__,'error':str(exc)[:1500],'at':now(),'automatic_retry':False})
        event('stopped',error=str(exc)[:1000])
    finally:
        if keep is not None:
            keep.terminate()
            try: keep.wait(timeout=2)
            except subprocess.TimeoutExpired: keep.kill(); keep.wait()
        write(RUN/'End_summary.json',{'phase':state['phase'],'end':now(),'completed_strategies':
            sum(r['status']=='completed' for r in state['strategies'].values()),'lock_retained':not normal,
            'caffeinate_cleaned':keep is not None,'API':0})
        if normal: (RUN/'.execution.lock').unlink()
        try:
            from tools.h01_progress_report import report
            report()
        except BaseException as exc:
            write(RUN/'Report_error.json',{'error_type':type(exc).__name__,'error':str(exc)[:1000]})


def launch():
    check()
    if any((RUN/n).exists() for n in ('Launch_identity.json','Run_clock.json','End_summary.json','.execution.lock')):
        raise ValueError('already started/unknown; no implicit replay')
    env={**os.environ,'PYTHONPATH':str(ROOT/'code')+':'+str(ROOT),'PYTHONDONTWRITEBYTECODE':'1'}
    env.pop('LEAFAPI_API_KEY',None)
    with (RUN/'Console.log').open('ab',buffering=0) as f:
        child=subprocess.Popen([sys.executable,'-B','-c','from '+MODULE+' import run; run()'],cwd=ROOT,env=env,
            stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True,close_fds=True)
    write(RUN/'Launch_identity.json',{'pid':child.pid,'at':now(),'method':'detached session; logs to files; SIGHUP ignored'})
    print(json.dumps({'launched':child.pid,'run':str(RUN)}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('stage',choices=('accept','prepare','check','launch','run','report'))
    stage=parser.parse_args().stage
    if stage=='accept': accept()
    elif stage=='prepare': prepare()
    elif stage=='check': check(); ledger(read(RUN/'checkpoint.json'),read(RUN/'Protocol.json')); print('PASS')
    elif stage=='launch': launch()
    elif stage=='run': run()
    else:
        from tools.h01_progress_report import report
        report()


if __name__=='__main__': main()
