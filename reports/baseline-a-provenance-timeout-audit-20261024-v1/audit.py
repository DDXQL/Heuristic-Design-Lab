"""Read recorded evidence only. No heuristic execution, data loading or solves.

Run from repository root with .venv/bin/python -B reports/.../audit.py (3.12).
Historical AST-key formatting is Python-version-specific. Only this audit
directory may be written; socket use and every raw .fjsp open are denied.
"""
import ast
import csv
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
BASE = ROOT / 'runs/tier2-baseline-a-train21-seed501-20261024-v1'
ORIGIN = ROOT / 'runs/leaf-framework-30pct-20261010-v3'
UPSTREAM = ROOT.parent / 'EoH-S'
sys.dont_write_bytecode = True
reads = {}
guard_counts = {'network_attempts_blocked': 0, 'raw_instance_opens_blocked': 0,
                'outside_output_writes_blocked': 0}


def guard(event, args):
    if event.startswith('socket.'):
        guard_counts['network_attempts_blocked'] += 1
        raise RuntimeError('Network forbidden in evidence audit')
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        p = Path(os.fsdecode(args[0])).resolve()
        if p.suffix == '.fjsp':
            guard_counts['raw_instance_opens_blocked'] += 1
            raise RuntimeError('Raw instances forbidden in evidence audit')
        flags = args[2] or 0
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            if not p.is_relative_to(OUT):
                guard_counts['outside_output_writes_blocked'] += 1
                raise RuntimeError('Audit cannot write historical files')


sys.addaudithook(guard)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode())


def label(p):
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


def raw(p):
    p = Path(p).resolve()
    b = p.read_bytes()
    record = {'path': label(p), 'bytes': len(b), 'sha256': sha(b)}
    if p in reads:
        assert reads[p] == record, 'Input changed during audit: ' + str(p)
    reads[p] = record
    return b


def read(p):
    return json.loads(raw(p))


def write(name, obj):
    (OUT/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def csv_write(name, rows):
    with (OUT/name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def git(*args, cwd=ROOT, optional=False):
    p = subprocess.run(['git', *args], cwd=cwd, capture_output=True, check=False)
    if p.returncode and not optional:
        raise RuntimeError(p.stderr.decode())
    return p.stdout if p.returncode == 0 else None


def functions(path, names, namespace):
    """Execute only named host arithmetic/selection functions, never H or U code."""
    tree = ast.parse(raw(path))
    found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in found} == set(names)
    exec(compile(ast.Module(body=found, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def code_key(code):
    t = ast.parse(code)
    fn = t.body[0]
    for a in fn.args.args:
        a.annotation = None
    fn.returns = None
    if (isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant)
            and isinstance(fn.body[0].value.value, str)):
        fn.body.pop(0)
    return sha(ast.dump(t, include_attributes=False).encode())


def response_key(text):
    m = re.fullmatch(r'\s*\{([^{}]+)\}\s*```python\s*\n(.*?)\n```\s*', text, re.S)
    assert m is not None
    return code_key(m[2])


def result_check(result, names):
    assert result['valid'] and result['total_instances'] == len(names)
    assert [r['file'] for r in result['instances']] == names
    assert all(r['feasible'] and r['score'] == -r['makespan']/r['lower_bound']
               for r in result['instances'])
    assert math.isclose(statistics.fmean(r['score'] for r in result['instances']),
                        result['fitness'], rel_tol=0, abs_tol=1e-14)


def quantile(values, p):
    s = sorted(values)
    x = (len(s)-1)*p
    lo = math.floor(x)
    hi = math.ceil(x)
    return s[lo] + (s[hi]-s[lo])*(x-lo)


def summary(values):
    return {'n': len(values), 'min': min(values), 'median': quantile(values, .5),
            'q90': quantile(values, .90), 'q95': quantile(values, .95),
            'max': max(values), 'sum': sum(values)}


def provenance():
    current = read(ROOT/'reports/tier2-baseline-a-train21-seed501-20261024-v1/H_frozen.json')
    candidates = read(ORIGIN/'H_candidates.json')
    frozen = read(ORIGIN/'H_frozen.json')
    packet = read(ORIGIN/'H_review_packet.json')
    review = read(ORIGIN/'H_review_completed_20261010.json')
    approval = read(ORIGIN/'human_review_confirmation_20261010.json')
    config = read(ORIGIN/'protocol.json')
    names = current['training_files']
    assert names == config['dataset']['split']['train'] == frozen['training_files']
    assert names == candidates['training_files'] == packet['training_files']
    assert [x['file'] for x in read(BASE/'Protocol.json')['instances']] == names
    assert config['config']['H_seed'] == 7
    assert config['fitness'] == 'complete-split mean(-makespan/unrounded-V5-LB)'
    pop = candidates['population']
    ns = functions(ROOT/'code/fjsp_usage/research/sets.py',
                   ['ranked', 'complementary_survival', 'complementary_parents'],
                   {'math': math, 'combinations': itertools.combinations})
    ranked = ns['ranked'](pop)
    keys = [x['candidate']['key'] for x in ranked]
    assert len(set(keys)) == len(keys) == 10
    assert len({x['candidate']['code'] for x in ranked}) == 10
    assert all(a['fitness'] > b['fitness'] for a, b in zip(ranked, ranked[1:]))
    assert [x['candidate']['key'] for x in frozen['members']] == keys
    assert [x['candidate']['key'] for x in current['members']] == keys
    assert [x['candidate']['key'] for x in packet['rows']] == keys
    assert list(review) == keys == approval['code_keys'] and approval['human_approved'] is True
    assert sha(raw(ORIGIN/'H_review_completed_20261010.json')) == approval['review_file_sha256']
    assert frozen['source_hash'] == candidates['artifact_sha256'] == packet['source_hash']
    assert approval['H_source_hash'] == candidates['artifact_sha256']
    cp = read(ORIGIN/'H/checkpoint.json')
    sources = read(ORIGIN/'H_development_source.json')['population']
    initial = read(ORIGIN/'H/budgeted_initial_requests.json')['requests']
    evolved = read(ORIGIN/'H/budgeted_evolution_requests.json')['requests']
    journal = {**initial, **evolved}
    ledger = read(ORIGIN/'budget.json')
    rows = {x['id']: x for x in sources}
    for attempt in cp['attempts']:
        id = attempt['id']
        if attempt['status'] == 'valid':
            result = cp['evaluations'][id]['result']
            result_check(result, names)
            key = response_key(journal[id]['text'])
            assert key == attempt['code_key']
            rows[id] = {'id': id, 'candidate': {'key': key}, 'fitness': result['fitness'],
                        'scores': [r['score'] for r in result['instances']]}
    pop_replay = ns['ranked'](sources + [rows[a['id']] for a in cp['attempts']
                                      if a['operator'] == 'I1' and a['status'] == 'valid'])
    assert len(pop_replay) == 10
    generation_events = [json.loads(line) for line in raw(ORIGIN/'H/events.jsonl').splitlines()
                         if json.loads(line)['kind'] == 'generation']
    replay = []
    parent_replay = []
    ns = functions(ROOT/'code/fjsp_usage/research/evolution.py', ['select_parents'], ns)
    rng = random.Random(7)
    for gen in range(2):
        attempts = [a for a in cp['attempts'] if a['id'].startswith(f'H/g{gen:04d}/')]
        assert len(attempts) == 10
        for a in attempts:
            parents = (ns['complementary_parents'](pop_replay, rng) if a['operator'] == 'E1'
                       else ns['select_parents'](pop_replay, 1, rng))
            match = [r['id'] for r in parents] == a['parents']
            parent_replay.append({'id': a['id'], 'operator': a['operator'],
                                  'recorded_parents': a['parents'], 'seed7_replay_matches': match})
        children = [rows[a['id']] for a in attempts if a['status'] == 'valid']
        pop_replay = ns['complementary_survival'](pop_replay+children, 10)
        actual = next(e for e in generation_events if e['generation'] == gen+1)
        assert [r['id'] for r in pop_replay] == actual['population_ids']
        replay.append({'generation': gen+1, 'valid_children': len(children),
                       'survival_ids': actual['population_ids'], 'matches_recorded_order': True})
    assert [r['id'] for r in pop_replay] == [r['id'] for r in pop]
    # Parent replay is an explicitly scoped consistency test; complete historical
    # evolution.py identity is not recovered, even if every parent matches.
    assert all(x['seed7_replay_matches'] for x in parent_replay)
    v1 = ROOT/'runs/leaf-framework-30pct-20261009-v1'
    old_journal = read(v1/'H/budgeted_initial_requests.json')['requests']
    old_cp = read(v1/'H/checkpoint.json')
    old_ledger = read(v1/'budget.json')
    mapping = []
    for i, row in enumerate(ranked):
        key = row['candidate']['key']
        assert key == code_key(row['candidate']['code'])
        original_run = v1 if key == '2a4ed2af0119955215aaf03ccd10d3ff9185b19eb64a147905cfb0b8ffa3dca8' else ORIGIN
        original_id = 'H/init/000001' if original_run == v1 else row['id']
        source_req = (old_journal if original_run == v1 else journal)[original_id]
        source_cp = old_cp if original_run == v1 else cp
        source_ledger = old_ledger if original_run == v1 else ledger
        receipt = row['receipt']
        assert receipt['send_confirmed'] and receipt['status'] == 'completed'
        assert source_req['text'] == receipt['response_text']
        assert response_key(source_req['text']) == key
        assert digest(source_req['text']) == receipt['response_sha256']
        assert digest({'prompt':source_req['prompt'],'kind':source_req['kind']}) == receipt['prompt_key']
        assert source_req['global_key'] == receipt['global_key']
        assert source_req['prompt_key'] == receipt['prompt_key']
        assert source_ledger['identity'] == receipt['ledger_identity']
        bill = source_ledger['records'][receipt['global_key']]
        assert bill['send_confirmed'] and bill['status'] == 'completed'
        assert bill['prompt_key'] == receipt['prompt_key']
        original_result = source_cp['evaluations'][original_id]['result']
        result_check(original_result, names)
        result_check(row['training_result'], names)
        assert original_result['fitness'] == row['fitness']
        baseline = read(BASE/f'cache/H{i}.json')
        result_check(baseline, names)
        assert baseline['fitness'] == row['fitness'] == current['members'][i]['fitness']
        assert [r['makespan'] for r in original_result['instances']] == [r['makespan'] for r in baseline['instances']]
        assert [r['lower_bound'] for r in original_result['instances']] == [r['lower_bound'] for r in baseline['instances']]
        assert row['scores'] == [r['score'] for r in original_result['instances']]
        assert current['members'][i]['candidate'] == row['candidate']
        assert current['members'][i]['member_id'] == i
        assert all(frozen['members'][i][k] == row[k] for k in ['id','candidate','fitness','scores','receipt','training_result'])
        assert frozen['members'][i]['member_id'] == i
        mapping.append({'H': f'H{i}', 'code_key': key, 'original_run': original_run.name,
                        'canonical_code_sha256':sha(row['candidate']['code'].encode()),
                        'original_candidate_id': original_id, 'frozen_source_id': row['id'],
                        'original_fitness': original_result['fitness'], 'baseline_A_fitness': baseline['fitness'],
                        'final_survival_position_1based': next(j+1 for j,p in enumerate(pop) if p['id']==row['id']),
                        'operator': next(a['operator'] for a in source_cp['attempts'] if a['id'] == original_id),
                        'receipt_response_sha256': receipt['response_sha256'],
                        'receipt_global_key': receipt['global_key'], 'journal_ledger_mapping_matches': True})
    # Verify declared source imports and the code-key chain, without rerunning H.
    imports = []
    for child in ['leaf-framework-30pct-20261009-v2', ORIGIN.name]:
        directory = ROOT/'runs'/child
        proto = read(directory/'protocol.json')
        spec = proto['config']['development_h_source']
        origin_dir = ROOT/'runs'/spec['run']
        for field, filename in [('protocol_sha256','protocol.json'),('checkpoint_sha256','H/checkpoint.json'),
                                ('budget_sha256','budget.json'),('journal_sha256','H/budgeted_initial_requests.json')]:
            assert sha(raw(origin_dir/filename)) == spec[field]
        previous = read(origin_dir/'H/checkpoint.json')['population']
        imported = read(directory/'H_development_source.json')['population']
        assert len(previous) == len(imported)
        prev = {r['candidate']['key']: r for r in previous}
        for r in imported:
            a = prev[r['candidate']['key']]
            assert r['id'] == 'H/source/'+a['id']
            assert (r['candidate'],r['fitness'],r['scores']) == (a['candidate'],a['fitness'],a['scores'])
        imports.append({'from': spec['run'], 'to': child, 'count': len(imported), 'source_hashes_match': True})
    continuation_dir = ROOT/'runs/leaf-tier2-single-P-acceptance-20261010-v4'
    continuation = read(continuation_dir/'protocol.json')['config']['development_continuation_source']
    pinned = ['H_candidates.json','H_frozen.json','H_review_packet.json','H/checkpoint.json',
              'H/events.jsonl','H/budgeted_initial_requests.json','H/budgeted_evolution_requests.json',
              'H_review_completed_20261010.json','human_review_confirmation_20261010.json']
    for name in pinned:
        assert sha(raw(ORIGIN/name)) == continuation['files_sha256'][name]
    for p in [continuation_dir/'H_frozen.json', ROOT/'runs/v22-gpt61-select-mix-301-20261014-v1/H_frozen.json',
              BASE/'H_frozen.json']:
        asset = read(p)
        assert [r['candidate']['key'] for r in asset['members']] == keys
        assert all(r['member_id'] == i for i,r in enumerate(asset['members']))
        assert [r['candidate'] for r in asset['members']] == [r['candidate'] for r in ranked]
    events = [json.loads(line) for line in raw(ORIGIN/'events.jsonl').splitlines()]
    stage_events = [e for e in events if e.get('stage') in ['H_REVIEW_REQUIRED','H_FROZEN']]
    write('H_origin_checks.json', {'train21': names, 'H_search_seed': 7, 'metric': config['fitness'],
        'search_attempts': len(cp['attempts']), 'attempt_status_counts': {
            x: sum(a['status']==x for a in cp['attempts']) for x in sorted({a['status'] for a in cp['attempts']})},
        'source_imports': imports, 'current_keys_unique': True, 'original_and_baseline_Cmax_match_all210': True,
        'generation_replay': replay, 'parent_replay': parent_replay,
        'stage_events': stage_events, 'scope': 'Static record/code-key/selection replay only; no H execution'})
    csv_write('H_mapping.csv', mapping)
    return mapping, config


def source_history(config):
    for p in ['code/fjsp_usage/research/protocol.py','code/fjsp_usage/research_real/assets.py',
              'code/fjsp_usage/research_real/review_packet.py','code/fjsp_usage/research_real/config.py',
              'code/fjsp_usage/research_real/continuation.py','code/fjsp_usage/research_real/conditional_h.py']:
        path = ROOT/p
        if path.exists():
            raw(path)
    paths = ['code/fjsp_usage/research/sets.py','code/fjsp_usage/research/evolution.py',
             'code/fjsp_usage/research_real/workflow.py','code/fjsp_usage/research_real/runtime.py']
    records = []
    for path in paths:
        expected = config['implementation']['files'][path]
        current = sha(raw(ROOT/path))
        matches = []
        commits = git('log','--all','--format=%H','--',path).decode().splitlines()
        for c in commits:
            b = git('show',f'{c}:{path}',optional=True)
            if b is not None and sha(b) == expected:
                matches.append(c)
        records.append({'path': path, 'recorded_sha256': expected, 'current_sha256': current,
                        'current_matches': current==expected, 'path_history_commits_checked': len(commits),
                        'exact_sha256_found_at_path_commits': matches})
    path = 'code/llm4ad/method/eohs/population.py'
    upstream = git('show',f'b3b67d6:{path}',cwd=UPSTREAM)
    assert upstream == raw(UPSTREAM/path)
    profiler = 'code/llm4ad/method/eohs/profiler.py'
    old_profiler = git('show',f'b3b67d6:{profiler}',cwd=UPSTREAM)
    cur_profiler = raw(UPSTREAM/profiler)
    for p in ['code/llm4ad/method/eohs/eohs.py','examples/training/fjsp_set/run_eohs.py']:
        raw(UPSTREAM/p)
    result = {'native_historical_source_comparison': records,
              'limitation': 'No full historical executable closure recovered; path-touch commit search only, not all unreachable Git objects.',
              'upstream_head': git('rev-parse','HEAD',cwd=UPSTREAM).decode().strip(),
              'upstream_population_commit': 'b3b67d6', 'population_sha256': sha(upstream),
              'population_matches_current_file': True,
              'upstream_profiler_export_present_at_commit': b'def export_final_set' in old_profiler,
              'upstream_profiler_export_present_in_dirty_worktree': b'def export_final_set' in cur_profiler,
              'upstream_dirty_status': git('status','--short',cwd=UPSTREAM).decode().splitlines()}
    write('Historical_source_identity.json', result)
    return result


def prompts_and_mock(mapping):
    members = read(BASE/'H_frozen.json')['members']
    paths = [ROOT/'runs/b1-ns-recovery-B-v1-20261022/r501/B/batch_requests.json',
             ROOT/'runs/h01-state-weight-search-seed501-batch-v3-20261020/r501/B/budgeted_evolution_requests.json']
    rows = []
    for p in paths:
        for id, req in read(p)['requests'].items():
            text = req['prompt']
            labels = re.findall(r'H MEMBER\s+(\d+)',text)
            expected = [str(i) for i in range(10 if 'b1-ns-' in str(p) else 2)]
            assert labels == expected
            contexts = re.findall(r'H MEMBER\s+\d+\n(.*?)(?=\nH MEMBER\s+\d+|\Z)', text, re.S)
            codes_present = all(members[int(i)]['candidate']['code'].strip() in context
                                for i,context in zip(labels, contexts))
            assert len(contexts)==len(expected) and codes_present
            # Last context can include subsequent U examples. Search for exact
            # aggregate numbers only, and do not infer absence of all performance hints.
            numbers = [str(m['original_fitness']) for m in mapping]
            rows.append({'source': label(p), 'logical_id': id, 'prompt_sha256': sha(text.encode()),
                         'ordered_member_labels': labels,
                         'categorical_quality_disclaimer': bool(re.search(r'(?:not quality ranks|do not imply quality)',text,re.I)),
                         'exact_H_training_fitness_literals_present': [s for s in numbers if s in text],
                         'all_H_code_blocks_present': codes_present})
    assert len(rows) == 39 and all(r['categorical_quality_disclaimer'] for r in rows)
    assert not any(r['exact_H_training_fitness_literals_present'] for r in rows)
    write('Prompt_index_audit.json', {'requests_read': len(rows), 'records': rows,
        'limitation': '39 saved requests from specified B1/B2 batches, not every historical prompt; numeric scan is exact literals only; no causal LLM inference.'})
    for path in ['tools/b1_usage_prompts.py','tools/h01_weight_search.py',
                 'code/fjsp_usage/usage_v2/prompts.py','code/fjsp_usage/research_real/prompts.py']:
        raw(ROOT/path)
    ns = functions(ROOT/'code/fjsp_usage/usage_v2/execution.py', ['_number','decode_output','normalize_scores','combine_scores'],
                   {'SELECT':0, 'MIX':1, 'math':math, 'UsageOutputError':ValueError, 'NormalizationError':ValueError})
    # Constants are verified from the actual interface rather than assumed.
    init = raw(ROOT/'code/fjsp_usage/usage_v2/__init__.py').decode()
    assert re.search(r'SELECT,\s*MIX\s*=\s*0,\s*1', init)
    zero = ns['decode_output']((0,(0,)*10),10)
    tied = ns['decode_output']((1,(0,0,0,0,1,0,0,1,0,0)),10)
    assert zero['dominant'] == 0 and tied['dominant'] == 4
    cols = [(0.,4.,2.),(8.,2.,5.)]
    a,_ = ns['combine_scores'](cols,(.5,.5),(0,1))
    b,_ = ns['combine_scores'](cols[::-1],(.5,.5),(0,1))
    assert a == b
    decision = max(range(len(a)),key=lambda i:a[i])
    tests = [
        {'name':'all_tied_SELECT_uses_lowest_member_index','passed':zero['support']==(0,)},
        {'name':'equal_MIX_dominant_is_lowest_active_member_index','passed':tied['dominant']==4},
        {'name':'static_equal_WS_invariant_to_joint_member_column_permutation','passed':a==b},
        {'name':'static_WS_action_tie_keeps_first_legal_action','passed':decision==0},
        {'name':'generation_survival_replay_and_seed7_parent_choices','passed':True},
        {'name':'raw_responses_match_10_keys_and_210_cached_instance_Cmax','passed':True}]
    assert all(t['passed'] for t in tests)
    write('Offline_acceptance.json', {'tests':tests, 'H_executions':0, 'FJSP_solves':0,
        'LLM_API_requests':0, 'note':'Named host functions extracted by AST, no scheduler/evaluator imports; synthetic columns only.'})


def costs():
    proto = read(BASE/'Protocol.json')
    cp = read(BASE/'checkpoint.json')
    expected = read(BASE/'Expected_loaded_identity.json')
    assert expected['identity'] == digest(expected['modules'])
    assert sha(raw(BASE/'H_frozen.json')) == proto['H_sha256']
    for path, expected_sha in proto['source_files'].items():
        assert sha(raw(ROOT/path)) == expected_sha
    assert cp['phase'] == 'completed'
    all_rows = []
    timeout_rows = []
    summaries = []
    results = {}
    for id, entry in cp['strategies'].items():
        p = BASE/entry['result_path']
        assert sha(raw(p)) == entry['result_sha256']
        result = read(p)
        results[id] = result
        if entry['origin'] != 'new':
            continue
        folder = p.parent
        before = read(folder/'before.json')
        life = read(folder/'lifecycle.json')
        boundary = read(folder/'boundary.json')
        assert before['identity'] == expected['identity']
        assert before['modules'] == expected['modules']
        assert before['identity'] == digest(before['modules'])
        for module in before['modules'].values():
            assert module['source_sha256'] == proto['source_files'][str(Path(module['file']).relative_to(ROOT))]
        assert life['pid'] == before['pid'] and life['status']=='terminal' and life['alive'] is False
        assert life['deadline_seconds']==15 and life['exit_grace_seconds']==2
        raw_result = read(folder/'raw_result.json')
        assert raw_result['instances'] == result['instances']
        if result['valid']:
            after = read(folder/'after.json')
            assert after['modules'] == before['modules'] and after['identity'] == before['identity']
            assert after['pid'] == before['pid'] and life['exitcode'] == 0
            assert life['exit_grace_used'] and life['all_results_received']
        else:
            assert result['fitness'] is None and result['error_type']=='Timeout'
            assert boundary['decision']=='candidate_invalid_continue'
            assert boundary['reason']=='confirmed_timeout_termination'
            assert boundary['prefix_quality_accepted'] is False
            assert life['trigger']=='parent_poll_timeout' and life['exitcode']==-15
            assert life['cleanup']==['join_0.05','terminate']
            assert life['exit_grace_used'] is False and life['all_results_received'] is False
            stem = folder/Path(result['failed_instance']).stem
            progress = read(stem.with_suffix('.progress.json'))
            assert progress['first_completed'] and progress['first_started'] and progress['recheck_started']
            assert progress['completed'] is False
            assert not stem.with_suffix('.result.json').exists()
            assert not (folder/'after.json').exists() and not (folder/'worker_failure.json').exists()
            timeout_rows.append({'strategy':id,'failed_instance':result['failed_instance'],
                'successful_prefix_instances':len(result['instances']),
                'parent_wait_seconds':result['parent_observed_instance_seconds'],
                'cleanup_join_observed_seconds':life['exit_wait_observed_seconds'],
                'exitcode':life['exitcode'],'pid':life['pid'], 'first_completed':True,
                'recheck_started':True,'full_instance_row':False,'end_identity':'unavailable; invalidity certified only',
                'total_candidate_primary_seconds':result['primary_evaluation_seconds']})
        for row in result['instances']:
            assert row['physical_schedule_sha256']==row['recheck_physical_schedule_sha256']
            assert row['single_h_calls']==row['recheck_h_calls']
            assert row['captured_solves']==2 and row['feasible']
            t = row['single_solve_seconds']+row['deterministic_recheck_seconds']
            all_rows.append({'strategy':id,'strategy_valid':result['valid'],'file':row['file'],
                'first_seconds':row['single_solve_seconds'], 'recheck_seconds':row['deterministic_recheck_seconds'],
                'combined_solve_seconds':t,'worker_seconds':row['instance_worker_seconds'],
                'CPU_seconds':row['instance_CPU_seconds'],
                'host_inside_worker_residual_seconds':row['instance_worker_seconds']-t,
                'h_scoring_seconds':sum(row[k]['h_scoring_seconds'] for k in ['first_costs','recheck_costs']),
                'fusion_seconds':sum(row[k]['fusion_seconds'] for k in ['first_costs','recheck_costs']),
                'h_calls':sum(row['single_h_calls'])+sum(row['recheck_h_calls']),
                'peak_RSS_bytes_macos':row['peak_RSS_bytes_macos'],
                'Cmax':row['makespan'], 'LB':row['lower_bound'],
                'physical_schedule_sha256':row['physical_schedule_sha256']})
    assert len(all_rows)==841 and len(timeout_rows)==6
    expected_ids = ['H0_H4_WS','H4_H5_WS','H4_H6_WS','H4_H7_WS','H5_H6_WS','H5_H7_WS']
    assert sorted(r['strategy'] for r in timeout_rows)==expected_ids
    for id in expected_ids:
        rows = [r for r in all_rows if r['strategy']==id]
        s=summary([r['combined_solve_seconds'] for r in rows])
        summaries.append({'strategy':id,**s, 'longest_success_instance':max(rows,key=lambda r:r['combined_solve_seconds'])['file'],
            'h_scoring_share':sum(r['h_scoring_seconds'] for r in rows)/s['sum'],
            'CPU_to_worker_wall':sum(r['CPU_seconds'] for r in rows)/sum(r['worker_seconds'] for r in rows),
            'residual_worker_seconds':sum(r['host_inside_worker_residual_seconds'] for r in rows)})
    instances = []
    for name in ['Behnke36.fjsp','Behnke57.fjsp']:
        rows = [r for r in all_rows if r['file']==name]
        instances.append({'file':name,**summary([r['combined_solve_seconds'] for r in rows]),
                          'max_strategy':max(rows,key=lambda r:r['combined_solve_seconds'])['strategy'],
                          'timeouts':sum(r['failed_instance']==name for r in timeout_rows),
                          'not_reached':41-len(rows)-sum(r['failed_instance']==name for r in timeout_rows)})
    for path in ['tools/tier2_baseline_a.py','code/fjsp_usage/fusion_v4/lifecycle.py','tools/b1_timeout_boundary.py']:
        raw(ROOT/path)
    csv_write('Timeout_evidence.csv',timeout_rows)
    csv_write('Successful_instance_costs.csv',all_rows)
    csv_write('Affected_strategy_costs.csv',summaries)
    csv_write('Heavy_instance_costs.csv',instances)
    write('Timing_summary.json', {'new_strategies':41,'valid':35,'timeout':6,'successful_rows':841,
        'affected_strategy_summaries':summaries,'heavy_instances':instances,
        'global_successful_two_pass_seconds':summary([r['combined_solve_seconds'] for r in all_rows]),
        'successful_host_residual_seconds':summary([r['host_inside_worker_residual_seconds'] for r in all_rows]),
        'timing_scope':'Completed rows only; first+recheck construct timers, not complete parent/lifecycle wall; censored failures have no first-end timestamp.'})
    return timeout_rows, summaries, instances


def main():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('Use repository .venv Python 3.12 for historical AST keys; do not reinterpret 3.13 ast.dump hashes as identity mismatches.')
    base_commit = git('rev-parse','HEAD').decode().strip()
    # A later documentation-only commit may reproduce the same evidence. Pin the
    # requested starting commit separately; never reset the worktree.
    assert git('rev-parse','7fa0ff2').decode().strip() == '7fa0ff264edb9dea4888126bab7b934cc70d6bb1'
    mapping, config = provenance()
    identity = source_history(config)
    prompts_and_mock(mapping)
    timeouts, summaries, instances = costs()
    for p, record in list(reads.items()):
        assert sha(p.read_bytes()) == record['sha256'], 'Evidence changed: '+str(p)
    write('Source_manifest.json', {'requested_base_commit':'7fa0ff2','audit_started_at_HEAD':base_commit,
        'audit_script_sha256':sha(Path(__file__).read_bytes()), 'python':sys.version,
        'inputs':[reads[p] for p in sorted(reads)], 'unchanged_at_end':True,
        'guard':guard_counts, 'new_FJSP_solves':0,'new_H_executions':0,'new_LLM_API_requests':0,
        'excluded':'Raw .fjsp files; validation11/test28 results; credentials; new formal execution.'})
    print(json.dumps({'members':len(mapping),'parent_choices_replayed':20,'generations_replayed':2,
        'successful_instance_rows':841,'timeouts':len(timeouts),'guard':guard_counts,
        'new_solves':0,'API':0},ensure_ascii=False))


if __name__ == '__main__':
    main()
