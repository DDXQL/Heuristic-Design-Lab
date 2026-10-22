"""Versioned B1-NS recovery: isolated sources, inherited budget, gated revalidation.

prepare/check are offline. revalidate/continue require SEPARATE new approvals.
No old protocol, ledger, candidate or result is ever edited.
"""
import argparse
from dataclasses import asdict, replace
import importlib
import inspect
import json
import os
from pathlib import Path
import shutil
import time
import types
from unittest.mock import patch

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.candidates import parse_response
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_result, checked_candidate
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.config import fingerprint
from fjsp_usage.research_real.locking import RunLock
from tools import b1_nonstream_local as ns

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'B1-NS-recovery-B-v1-20261022'
ORIGIN_SHA = '94381988c5536bd19f72aa0cbcdcafc7dfc1b8a4ece7b18fcbd71ad0b4a90083'
DEFAULT = ROOT / 'runs/b1-ns-recovery-B-v1-20261022'
CANDIDATES = ('B/init/000001', 'B/init/000002', 'B/init/000005')
CRITICAL_MODULES = ('tools.b1_ns_recovery', 'tools.b1_nonstream_local',
    'tools.b1_usage_local', 'tools.b1_usage_prompts', 'tools.usage_mechanism_ablation',
    'fjsp_usage.research_real.runtime', 'fjsp_usage.research.candidates',
    'fjsp_usage.research.evolution', 'fjsp_usage.usage_v2.search',
    'fjsp_usage.research_real.attempt_budget',
    'fjsp_usage.usage_v2.execution', 'fjsp_usage.research.scheduler',
    'fjsp_usage.offline_v2', 'fjsp_usage.research_real.state_diagnostics',
    'llm4ad.task.optimization.fjsp_set.scheduler', 'llm4ad.task.optimization.fjsp_set.instances')
read, sha = ns.read, ns.sha


def input_manifest(directory):
    return {str(f.relative_to(directory)): sha(f) for f in sorted(directory.rglob('*')) if f.is_file()}


def verify_files(directory, files):
    for name, expected in files.items():
        f = (directory / name).resolve()
        if not f.is_relative_to(directory.resolve()) or not f.is_file() or sha(f) != expected:
            raise ValueError('frozen input/code differs: ' + name)


def inherited_state(directory):
    c = read(directory / 'inherited/r501/B/checkpoint.json')
    j = read(directory / 'inherited/r501/B/batch_requests.json')
    if (c['phase'], c['init_cursor'], c['generation'], c['cursor'], c['inflight']) != ('initialization', 6, 0, 0, None):
        raise ValueError('source is not the recorded six-task safe checkpoint')
    if (len(j['requests']) != 6 or len(j['api_attempts']) != 6 or len(c['attempts']) != 6
            or set(c['evaluations']) != set(CANDIDATES) or c['children'] or j['halt_reason']):
        raise ValueError('source budget/evaluation state differs')
    for ident, row in j['requests'].items():
        aid = row['accepted_attempt_id']; a = j['api_attempts'][aid]
        if (row['status'] != 'completed' or row['attempt_ids'] != [aid] or a['status'] != 'completed'
                or a['send_confirmed'] is not True or a['logical_id'] != ident or a['number'] != 1
                or row['prompt_key'] != digest({'prompt': row['prompt'], 'kind': 'U'})
                or a['reply']['text'] != row['text'] or a['usage'] != row['usage']
                or row['response_id'] != a['response_id'] or row['response_id'] != aid + '/response'):
            raise ValueError('source response/attempt differs: ' + ident)
    return c, j


def prepare(directory):
    directory = Path(directory).resolve()
    if directory.parent != ROOT / 'runs' or directory.exists():
        raise ValueError('new independent project runs child required')
    origin = ns.DEFAULT
    p, config, dataset, members = ns.check(origin)  # hashes/provenance only; no instance load
    if sha(origin / 'Protocol.json') != ORIGIN_SHA or (origin / '.writer.lock').exists():
        raise ValueError('origin identity/writer differs')
    original = input_manifest(origin)
    archived = read(ROOT/'reports/b1-ns-b-full-h-free-seed501-k2-v1-20261022/Evidence_manifest.json')
    if original != {name: row['sha256'] for name,row in archived['files'].items()}:
        raise ValueError('origin differs from the already committed six-request evidence')
    directory.mkdir()
    inherited = directory / 'inherited'
    # Immutable evidence only; old approval is archived here, NEVER an active approval.
    for name in original:
        target = inherited / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin / name, target)
    c, j = inherited_state(directory)
    for row in c['population']:
        candidate = checked_candidate(row['candidate'], 'U')
        if parse_response(j['requests'][row['id']]['text'], kind='U',
                interface_version=candidate.interface_version, member_count=10).key != candidate.key:
            raise ValueError('inherited candidate/source differs')
        check_result(c['evaluations'][row['id']]['result'], p['train_names'])
    snapshot = directory / 'source_snapshot'
    files = set(p['pins']) | set(p['implementation']['files'])
    files |= {str(f.relative_to(ROOT)) for f in (ROOT / 'tools').glob('*.py')}
    files |= {str((ns.SOURCE / n).relative_to(ROOT)) for n in ('Protocol.json', 'config.pending.json')}
    files.add('data/fjsp_manifest.json')
    manifest = read(ROOT / 'data/fjsp_manifest.json')
    files |= {str(Path(manifest['portable_root']) / name) for name in p['train_names']}
    for name in sorted(files):
        target = snapshot / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    verify_files(snapshot, p['pins'])
    if fingerprint(snapshot) != p['implementation'] or input_manifest(origin) != original:
        raise ValueError('source changed during snapshot creation')
    protocol = {'version': VERSION, 'run_directory': str(directory), 'source_snapshot': str(snapshot),
        'origin_directory': str(origin), 'origin_protocol_sha256': ORIGIN_SHA,
        'origin_files': original, 'snapshot_files': input_manifest(snapshot),
        'config': config.payload(), 'implementation': p['implementation'], 'original_pins': p['pins'],
        'train_names': p['train_names'], 'H_order': [m.key for m in members], 'dataset': dataset.metadata,
        'credential_source': p['credential_source'], 'critical_modules': list(CRITICAL_MODULES),
        'inherited_logical_tasks': 6, 'inherited_api_attempts': 6, 'revalidation_ids': list(CANDIDATES),
        'request_phase': ns.NSSearch.request_phase, 'request_policy': j['policy'],
        'scientific_change': None, 'old_Fitness_replaced_only_in_new_checkpoint': True,
        'comparison_fields': ['makespan','lower_bound','score','feasible','deterministic_schedule_sha256',
            'physical_schedule_sha256','recheck_physical_schedule_sha256','commit_sequence_sha256','captured_solves'],
        'comparison': 'exact per-instance fields and full Fitness; timings excluded; all three must match',
        'evaluation_limit': 'three complete train21 evaluations, each at most once; interrupted/failed stops',
        'real_execution_authorized': False}
    atomic_json(directory / 'Protocol.json', protocol)
    (directory / 'Protocol.sha256').write_text(sha(directory / 'Protocol.json') + '\n')
    for stage in ('revalidate', 'continue'):
        atomic_json(directory / (stage + '.Authorization.template.json'), approval(directory, stage, False))
    for tree in (snapshot, inherited):
        for f in tree.rglob('*'):
            if f.is_file(): f.chmod(0o444)
        for f in sorted((f for f in tree.rglob('*') if f.is_dir()), key=lambda f: len(f.parts), reverse=True):
            f.chmod(0o555)
        tree.chmod(0o555)
    return check(directory)


def check(directory):
    directory = Path(directory).resolve(); p = read(directory / 'Protocol.json')
    if (sha(directory / 'Protocol.json') != (directory / 'Protocol.sha256').read_text().strip()
            or p['version'] != VERSION or p['run_directory'] != str(directory)
            or p['origin_protocol_sha256'] != ORIGIN_SHA or p['critical_modules'] != list(CRITICAL_MODULES)):
        raise ValueError('recovery protocol differs')
    snapshot = Path(p['source_snapshot'])
    if snapshot != directory / 'source_snapshot': raise ValueError('snapshot path differs')
    verify_files(snapshot, p['snapshot_files']); verify_files(snapshot, p['original_pins'])
    verify_files(directory / 'inherited', p['origin_files'])
    verify_files(Path(p['origin_directory']), p['origin_files'])
    if input_manifest(Path(p['origin_directory'])) != p['origin_files']:
        raise ValueError('origin run file set changed or has a writer')
    if any((snapshot/name).stat().st_mode & 0o222 for name in p['snapshot_files']):
        raise ValueError('source snapshot must remain read-only')
    if sha(directory / 'inherited/Protocol.json') != ORIGIN_SHA:
        raise ValueError('original protocol differs')
    old = read(directory / 'inherited/Protocol.json')
    if any(p[k] != old[k] for k in ('config','implementation','train_names','H_order','dataset')):
        raise ValueError('frozen research identity differs')
    if p['original_pins'] != old['pins'] or p['request_policy'] != ns.POLICY:
        raise ValueError('Frozen Input Guard or request budget changed')
    if fingerprint(snapshot) != p['implementation']:
        raise ValueError('snapshot runtime/evaluator identity differs')
    manifest = read(snapshot / 'data/fjsp_manifest.json')
    if manifest['split']['train'] != p['train_names']: raise ValueError('train21 order differs')
    for name in p['train_names']:
        if sha(snapshot / manifest['portable_root'] / name) != p['dataset']['hashes'][name]:
            raise ValueError('train21 identity differs')
    inherited_state(directory)
    return p


def approval(directory, stage, approved):
    return {'stage': 'B1-NS-recovery-B/' + stage, 'approved': approved, 'person': 'DDXQL',
        'protocol_sha256': sha(Path(directory) / 'Protocol.json'),
        'inherited_logical_tasks': 6, 'inherited_api_attempts': 6,
        'logical_candidate_cap': 40, 'api_attempt_cap': 60, 'per_candidate_attempt_cap': 3}


def require_execution(directory, stage):
    f = Path(directory) / (stage + '.Authorization.json')
    if not f.exists() or read(f) != approval(directory, stage, True):
        raise BudgetStop('new stage-specific approval required: ' + stage)
    p = check(directory)
    if ROOT != Path(p['source_snapshot']) or ns.ROOT != ROOT or ns.b1.b2.ROOT != ROOT:
        raise BudgetStop('execute only from the isolated source snapshot')
    return p


def code_identity(code):
    def constant(value):
        if isinstance(value, types.CodeType): return code_identity(value)
        if isinstance(value, tuple): return [constant(x) for x in value]
        if isinstance(value, frozenset): return sorted(repr(x) for x in value)
        return repr(value)
    return digest({k: (code.co_code.hex() if k == 'co_code' else
        [constant(x) for x in code.co_consts] if k == 'co_consts' else getattr(code,k))
        for k in ('co_code','co_consts','co_names','co_varnames','co_freevars','co_cellvars',
                  'co_argcount','co_posonlyargcount','co_kwonlyargcount','co_flags')})


def source_attestation(p, execution_original=None):
    """Compare loaded function bytecode to freshly compiled, pinned source.

    Recorded source is the child's own module file, not a parent-only file hash.
    Aliases preserve the two original functions temporarily observed by the adapter.
    """
    from tools import usage_mechanism_ablation as common
    rows = {}
    for name in p['critical_modules']:
        module = importlib.import_module(name); file = Path(module.__file__).resolve()
        if not file.is_relative_to(Path(p['source_snapshot'])):
            raise ValueError('loaded module outside snapshot: ' + name)
        relative = str(file.relative_to(Path(p['source_snapshot'])))
        if sha(file) != p['snapshot_files'][relative]: raise ValueError('worker source differs: ' + relative)
        compiled = compile(file.read_bytes(), str(file), 'exec', dont_inherit=True, optimize=0)
        definitions = {x.co_name: x for x in compiled.co_consts if isinstance(x, types.CodeType)}
        functions = {}
        for key, value in vars(module).items():
            if name == 'fjsp_usage.research_real.runtime' and key == '_worker': value = common.native_worker
            if name == 'fjsp_usage.usage_v2.execution' and key == 'construct_usage_schedule' and execution_original:
                value = execution_original
            if inspect.isclass(value) and value.__module__ == name and key in definitions:
                methods={x.co_name:x for x in definitions[key].co_consts if isinstance(x,types.CodeType)}
                for method, function in vars(value).items():
                    if isinstance(function,(staticmethod,classmethod)): function=function.__func__
                    if not inspect.isfunction(function) or method not in methods: continue  # e.g. generated dataclass __init__
                    if code_identity(function.__code__) != code_identity(methods[method]):
                        raise ValueError('loaded method/source differs: '+name+'.'+key+'.'+method)
                    functions[key+'.'+method]=code_identity(function.__code__)
            if not inspect.isfunction(value) or value.__module__ != name: continue
            if key not in definitions or code_identity(value.__code__) != code_identity(definitions[key]):
                raise ValueError('loaded function/source differs: ' + name + '.' + key)
            functions[key] = code_identity(value.__code__)
        rows[name] = {'file': str(file), 'source_sha256': sha(file), 'loaded_functions': functions}
    return {'pid': os.getpid(), 'time_unix': time.time(), 'modules': rows, 'identity': digest(rows)}


def identity_worker(pipe, *args):
    """Only evidence around the SAME native two-solve worker; no scheduling change."""
    directory = Path(os.environ['B1_NS_RECOVERY_RUN']); p = read(directory / 'Protocol.json')
    evidence = directory / 'worker_evidence' / os.environ['B1_NS_RECOVERY_CANDIDATE']
    from fjsp_usage.usage_v2 import execution
    from tools.usage_mechanism_ablation import schedule_recording_worker
    original = execution.construct_usage_schedule
    try:
        before = source_attestation(p, original); atomic_json(evidence.with_suffix('.before.json'), before)
        class ObservedPipe:
            count = 0
            def send(self, row):
                self.count += 1
                if 'error' in row or self.count == len(args[3]):
                    after = source_attestation(p, original)
                    atomic_json(evidence.with_suffix('.after.json'), after)
                    if before['identity'] != after['identity']: raise ValueError('worker loaded identity changed')
                pipe.send(row)
            def close(self): pipe.close()
        schedule_recording_worker(ObservedPipe(), *args)
    except BaseException as exc:
        atomic_json(evidence.with_suffix('.failure.json'), {'error_type': type(exc).__name__, 'error': str(exc)[:500]})
        try: pipe.send({'error_type': 'SourceIdentityError', 'error': str(exc)[:500]})
        finally: pipe.close()


def evaluator(directory, p, config):
    dataset, H, members = ns.b1.b2.data_and_h(config, directory)
    if dataset.metadata != p['dataset'] or [m.key for m in members] != p['H_order']:
        raise ValueError('original H/data provenance differs')
    instances = dataset.load('train')
    def evaluate(candidate):
        check(directory); dataset.verify('train')
        evidence = directory / 'worker_evidence' / candidate.key
        if any(evidence.parent.glob(candidate.key + '.*.json')):
            raise BudgetStop('worker evidence already exists; no automatic evaluation repeat')
        from fjsp_usage.research_real import runtime
        with patch.dict(os.environ, {'B1_NS_RECOVERY_RUN': str(directory), 'B1_NS_RECOVERY_CANDIDATE': candidate.key}), \
                patch.object(runtime, '_worker', identity_worker):
            result = runtime.evaluate(candidate, members, instances, p['train_names'],
                timeout=15, diagnostics=False, allowed_modes=(0,1))
        # Persist the native result/prefix even if the following identity guard
        # fails. This receipt is evidence, never an accepted fitness cache.
        atomic_json(directory/'evaluation_receipts'/(candidate.key+'.json'), result)
        check(directory)
        before, after = evidence.with_suffix('.before.json'), evidence.with_suffix('.after.json')
        if (evidence.with_suffix('.failure.json').exists() or not before.exists() or not after.exists()
                or read(before)['identity'] != read(after)['identity']):
            atomic_json(directory / 'Identity_stop.json', {'candidate_key': candidate.key, 'reason': 'missing/differing child attestation'})
            raise BudgetStop('child source identity not certified')
        result['worker_identity'] = {'before_sha256': sha(before), 'after_sha256': sha(after),
                                     'loaded_identity': read(before)['identity']}
        return check_result(result, p['train_names'])
    return evaluate, members


def compare_results(old, new, p):
    check_result(old, p['train_names']); check_result(new, p['train_names'])
    if not new['valid'] or not new.get('worker_identity') or old['fitness'] != new['fitness']:
        raise ValueError('revalidation invalid, identity missing or Fitness differs')
    differences = []
    for a,b in zip(old['instances'], new['instances']):
        for field in p['comparison_fields']:
            if a.get(field) != b.get(field) or field not in a or field not in b:
                differences.append({'file': a['file'], 'field': field, 'old': a.get(field), 'new': b.get(field)})
    if differences: raise ValueError('revalidation mismatch: ' + json.dumps(differences, ensure_ascii=False)[:1500])
    return {'matched': True, 'instances': len(new['instances']), 'old_fitness': old['fitness'], 'new_fitness': new['fitness']}


def verify_worker_evidence(directory, key, result):
    identity = result['worker_identity']; prefix = directory/'worker_evidence'/key
    before,after = prefix.with_suffix('.before.json'),prefix.with_suffix('.after.json')
    if (not before.exists() or not after.exists() or sha(before) != identity['before_sha256']
            or sha(after) != identity['after_sha256']):
        raise ValueError('saved worker attestation missing/changed')
    for f in (before,after):
        evidence=read(f)
        if evidence['identity'] != digest(evidence['modules']) or evidence['identity'] != identity['loaded_identity']:
            raise ValueError('saved loaded source identity differs')


def comparison_table(old,new,p):
    def indexed(result): return {row['file']:row for row in result.get('instances',[])}
    left,right=indexed(old),indexed(new)
    return {'old_valid':old['valid'],'new_valid':new.get('valid'),
        'old_fitness':old['fitness'],'new_fitness':new.get('fitness'),
        'instances':[{'file':name,
            'old':{k:left.get(name,{}).get(k) for k in p['comparison_fields']},
            'new':{k:right.get(name,{}).get(k) for k in p['comparison_fields']}}
            for name in p['train_names']]}


def revalidate_saved(directory, p, evaluate):
    c, _ = inherited_state(directory)
    path = directory / 'Revalidation.json'
    state = read(path) if path.exists() else {'protocol_sha256': sha(directory/'Protocol.json'), 'rows': {}, 'ready': False}
    if state['protocol_sha256'] != sha(directory/'Protocol.json'): raise ValueError('revalidation identity differs')
    for ident in p['revalidation_ids']:
        candidate = checked_candidate(next(row for row in c['population'] if row['id'] == ident)['candidate'], 'U')
        if ident in state['rows']:
            if state['rows'][ident]['status'] != 'matched': raise BudgetStop('failed/uncertain revalidation; no repeat')
            verify_worker_evidence(directory,candidate.key,state['rows'][ident]['result'])
            compare_results(c['evaluations'][ident]['result'], state['rows'][ident]['result'], p)
            continue
        state['rows'][ident] = {'status': 'pending'}; atomic_json(path, state)
        try:
            result = evaluate(candidate)
            state['rows'][ident].update(result=result)  # save new evidence even when comparison fails
            atomic_json(path, state)
            atomic_json(directory/'Revalidation_comparisons'/(ident.replace('/','_')+'.json'),
                comparison_table(c['evaluations'][ident]['result'],result,p))
            verify_worker_evidence(directory,candidate.key,result)
            comparison = compare_results(c['evaluations'][ident]['result'], result, p)
        except Exception as exc:
            state['rows'][ident].update(status='stopped', error_type=type(exc).__name__, error=str(exc)[:2000])
            atomic_json(path, state); raise BudgetStop('revalidation stopped: ' + ident) from exc
        state['rows'][ident].update(status='matched', comparison=comparison); atomic_json(path, state)
    state['ready'] = True; atomic_json(path, state)
    return state


def install_progress(directory, p, config, transport):
    """Controlled NEW checkpoint/journal binding, with an interruption-safe bundle.

    Original IDs, all six records, counters, RNG and seen are retained verbatim.
    Only new-context identities and the three certified result caches are rebound.
    """
    state = read(directory / 'Revalidation.json')
    if (not state['ready'] or set(state['rows']) != set(CANDIDATES)
            or state['protocol_sha256'] != sha(directory/'Protocol.json')):
        raise BudgetStop('three matching revalidations bound to this protocol required')
    c,j = inherited_state(directory)
    for ident in CANDIDATES:
        row = state['rows'][ident]
        if row['status'] != 'matched': raise BudgetStop('three matching revalidations required')
        key=next(item['candidate']['key'] for item in c['population'] if item['id']==ident)
        verify_worker_evidence(directory,key,row['result'])
        compare_results(c['evaluations'][ident]['result'], row['result'], p)
        c['evaluations'][ident] = {'status': 'completed', 'result': row['result']}
    target = directory / 'r501/B'; target.mkdir(parents=True, exist_ok=True)
    context = sha(directory / 'Protocol.json')
    c['signature'] = digest({'arm':'B','kind':'U','config':asdict(config.u_search(501)),
        'H':p['H_order'],'context':context,'transport':transport.identity,'initial':None})
    old_identity = j['identity']
    j['identity'] = digest({'version':j['version'],'config':config.payload(),'context':context,
        'transport':transport.identity,'phase':p['request_phase'],'journal_path':str((target/'batch_requests.json').resolve())})
    j['recovery_source'] = {'journal_identity':old_identity,'journal_sha256':p['origin_files']['r501/B/batch_requests.json'],
        'origin_protocol_sha256':ORIGIN_SHA,'inherited_logical_tasks':6,'inherited_api_attempts':6}
    bundle = {'checkpoint.json': c, 'batch_requests.json': j}
    planned = directory / 'Migration_bundle.json'; done = directory / 'Migration_complete.json'
    if done.exists():
        if read(done)['bundle_sha256'] != sha(planned) or not all((target/name).exists() for name in bundle):
            raise ValueError('migration marker/files differ')
        return
    if planned.exists() and read(planned) != bundle: raise ValueError('migration plan changed')
    if not planned.exists(): atomic_json(planned, bundle)
    for name, payload in bundle.items():
        if (target/name).exists() and read(target/name) != payload: raise ValueError('partial migration differs; never overwrite')
        if not (target/name).exists(): atomic_json(target/name, payload)
    for folder in ('wire_responses','received_responses','send_times','r501/B/prompts'):
        for f in (directory/'inherited'/folder).glob('*'):
            out = directory/folder/f.name; out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists() and sha(out) != sha(f): raise ValueError('inherited receipt copy differs')
            if not out.exists(): shutil.copyfile(f,out)
    atomic_json(done, {'bundle_sha256':sha(planned),'inherited_logical_tasks':6,'inherited_api_attempts':6})


def execute(directory, stage, env_file=None):
    p = require_execution(directory, stage)
    config = ns.Config.from_dict(p['config'])
    if stage == 'continue':
        # Revalidation gate precedes credential reads and provider creation.
        state = read(directory/'Revalidation.json') if (directory/'Revalidation.json').exists() else {}
        if not state.get('ready'): raise BudgetStop('revalidation not ready; no API permitted')
    with RunLock(directory):
        if stage == 'revalidate':
            evaluate, _ = evaluator(directory,p,config)
            return revalidate_saved(directory,p,evaluate)
        if env_file is None or Path(env_file).resolve() != Path(p['credential_source']):
            raise ValueError('original credential source required')
        from fjsp_usage.research_real.leafapi import load_local_key, KEY_ENV
        from fjsp_usage.research_real.real_transport import JsonCandidateTransport
        os.environ[KEY_ENV] = load_local_key(env_file)
        config = replace(config,real_requests_authorized=True)
        profile = ns.CompleteNonstreamTransport(JsonCandidateTransport(config), directory/'received_responses')
        transport = ns.TimedRecorder(profile,directory/'wire_responses',lambda:check(directory))
        install_progress(directory,p,config,transport)
        evaluate, members = evaluator(directory,p,config)
        def verify():
            check(directory)
            if (directory/'Identity_stop.json').exists(): raise BudgetStop('source identity stop requires review')
        engine = ns.NSSearch(directory/'r501/B',experiment=config,training_names=p['train_names'],verify=verify,
            arm='B',config=config.u_search(501),members=members,evaluator=evaluate,transport=transport,
            context=sha(directory/'Protocol.json'))
        try: engine.run()
        finally:
            atomic_json(directory/'Search_status.json',engine.report())
            atomic_json(directory/'Final_or_partial_population.json',engine.export_rows())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('prepare','check','revalidate','continue'))
    parser.add_argument('--run-dir',type=Path,default=DEFAULT); parser.add_argument('--env-file',type=Path)
    args=parser.parse_args(); directory=args.run_dir.resolve()
    if args.stage=='prepare': prepare(directory)
    elif args.stage=='check': print({'protocol_sha256':sha(directory/'Protocol.json'),'PASS':bool(check(directory))})
    else: execute(directory,args.stage,args.env_file)


if __name__=='__main__': main()
