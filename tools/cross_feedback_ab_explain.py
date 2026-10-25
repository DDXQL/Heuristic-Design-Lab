"""Read saved CROSS A/B evidence; never import/evaluate U, a solver or transport.

Outputs are post-hoc descriptive analyses, not a new experimental protocol.
AST similarities ignore formatting/local names; they are NOT behavior distances.
"""
import ast
from collections import Counter
import csv
import difflib
import hashlib
import json
from pathlib import Path
import re
import statistics as st
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'runs/cross-feedback-ab-train21-seed501-v1-20261025'
EX = BASE / 'execution-v2'
OLD = ROOT / 'reports/cross-feedback-ab-train21-seed501-v1-20261025/execution-v2'
OUT = ROOT / 'reports/cross-feedback-ab-explanation-20261025-v1'
INPUTS = {}


def guard(event, args):
    if event.startswith(('socket.', 'subprocess.', 'os.system', 'os.fork', 'os.posix_spawn')):
        raise RuntimeError('offline analysis forbids network/process launch')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        name = str(args[0]).lower()
        parts = set(Path(name).parts)
        if name.endswith('.fjsp') or '.env' in name or parts & {'validation', 'validation11', 'test28'}:
            raise RuntimeError('no instance/holdout/credential reads')


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def read(p):
    INPUTS[str(p.relative_to(ROOT))] = sha(p)
    return json.loads(p.read_text())


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def table(name, rows):
    assert rows
    with (OUT / name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n'); w.writeheader()
        for row in rows:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                        for k, v in row.items()})


def zero(node):
    return isinstance(node, ast.Constant) and node.value == 0


def logic(code, erase_literals=False):
    """Body-only sparse-return AST, local-alpha normalized; mode/H ids retained.

    Both metrics preserve control-flow order. Shape metric erases numeric values
    except output mode and vector indices. They do NOT normalize semantic logic.
    """
    fn = ast.parse(code).body[0]
    args = {a.arg for a in fn.args.args}
    locals_ = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id not in args:
            locals_.setdefault(n.id, 'local_' + str(len(locals_)))

    def walk(n):
        if isinstance(n, list): return [walk(x) for x in n]
        if isinstance(n, ast.Name): return ['Name', locals_.get(n.id, n.id)]
        if isinstance(n, ast.Constant):
            return ['Constant', 'NUM' if erase_literals and type(n.value) in (int, float) else n.value]
        if isinstance(n, ast.Return):
            mode, vector = n.value.elts
            return ['Return', ast.literal_eval(mode),
                    [[i, walk(v)] for i, v in enumerate(vector.elts) if not zero(v)]]
        if isinstance(n, ast.AST):
            return [type(n).__name__, [[k, walk(v)] for k, v in ast.iter_fields(n) if k != 'ctx']]
        return n
    result = walk(fn.body)
    # Atomic JSON tokens, not character similarity. No autojunk deletion.
    def tokens(x):
        if isinstance(x, list):
            return ['['] + [v for y in x for v in tokens(y)] + [']']
        return [json.dumps(x, ensure_ascii=False)]
    return result, tokens(result)


def signature(code):
    fn = ast.parse(code).body[0]
    modes, support = set(), set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Return):
            mode, vector = n.value.elts; m = ast.literal_eval(mode); modes.add(m)
            if m == 0:
                vals = ast.literal_eval(vector)
                support.add(max(range(10), key=lambda i: vals[i]))
            else:
                support.update(i for i, v in enumerate(vector.elts) if not zero(v))
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    inputs = [a.arg for a in fn.args.args if a.arg in names]
    return {'modes_in_source': '+'.join('SELECT' if m == 0 else 'MIX' for m in sorted(modes)),
            'static_possible_members': sorted(support), 'state_inputs_in_source': inputs,
            'if_nodes': sum(isinstance(n, ast.If) for n in ast.walk(fn)),
            'AST_nodes': sum(1 for n in ast.walk(fn))}


def similar(a, b, shape=False):
    return difflib.SequenceMatcher(None, logic(a, shape)[1], logic(b, shape)[1], autojunk=False).ratio()


def category(f, better, worse):
    if f > better: return 'above_better'
    if f == better: return 'equal_better'
    if f > worse: return 'between_strict'
    if f == worse: return 'equal_worse'
    return 'below_worse'


def main():
    sys.addaudithook(guard)
    OUT.mkdir(exist_ok=True)
    p = read(BASE / 'Protocol.json'); plan = read(BASE / 'Tasks.json')
    parents = {x['id']: x for x in read(BASE / 'Parents.json')}
    cp = read(EX / 'checkpoint.json'); journal = read(EX / 'API_attempts.json')
    binding = read(EX / 'Execution_binding.json'); manifest = read(OLD / 'Raw_evidence_manifest.json')
    annotations = read(OUT / 'Manual_code_review.json')
    # Static parser invariants only: these function strings are never executed.
    sample = ('def f(progress):\n    x = progress + 0.2\n'
              '    return (1, (x, 0, 0, 0, 0, 0, 0, 0, 0, 1))\n')
    renamed = sample.replace('x', 'renamed')
    assert logic(sample) == logic(renamed)
    assert logic(sample)[0] != logic(sample.replace('0.2', '0.3'))[0]
    assert logic(sample, True)[0] == logic(sample.replace('0.2', '0.3'), True)[0]
    assert logic(sample)[0] != logic(sample.replace('(x, 0,', '(0, x,'))[0]
    checks = []
    # Hash recorded source assets, never raw .fjsp data. Preserve before/after hashes.
    for name, expected in {**binding['source_files'], **binding['protected_files']}.items():
        if name.endswith('.fjsp'): continue
        path = ROOT / name; INPUTS[name] = sha(path)
        assert INPUTS[name] == expected, name
    for name, expected in manifest['files'].items():
        if Path(name).name in {'checkpoint.json', 'API_attempts.json', 'Execution_binding.json'}:
            assert sha(ROOT / name) == expected['sha256']
    original = read(ROOT / next(iter(parents.values()))['source_result_path'])
    for x in parents.values():
        full = original['evaluations'][x['id']]['result']
        source = next(y for y in original['population_snapshots']['P0'] if y['id'] == x['id'])
        assert source['candidate'] == x['candidate'] and source['fitness'] == x['fitness']
        assert digest(full) == x['source_result_digest'] and full['valid']
        assert full['fitness'] == x['fitness']
        assert all(all(r[k] == fr[k] for k in r) for r,fr in zip(x['instances'],full['instances']))
        rows = x['instances']; assert len(rows) == 21
        assert x['fitness'] == st.fmean(r['score'] for r in rows)
        assert [r['file'] for r in rows] == [r['file'] for r in p['science']['instances']]
        for a, b in zip(rows, p['science']['instances']):
            assert a['lower_bound'] == b['LB'] and a['score'] == -a['makespan'] / b['LB']
            assert a['physical_schedule_sha256'] == a['recheck_physical_schedule_sha256']
    for pair in plan['pairs']:
        ps = [parents[i] for i in pair['parents']]; f, g = [x['fitness'] for x in ps]
        block = ('COMPLETE TRAIN21 EVALUATION FEEDBACK\n'
                 f'parent_1 (PARENT 0) complete train21 Fitness = {f!r}.\n'
                 f'parent_2 (PARENT 1) complete train21 Fitness = {g!r}.\n'
                 f'delta = Fitness(parent_2) - Fitness(parent_1) = {g-f!r}.\n'
                 'Higher Fitness is better.\n'
                 'Whole-program Fitness differences do not establish a causal effect of a specific state branch; '
                 'explanations for proposed modifications are hypotheses to be tested.\n')
        prompts = {}
        for cond in ('A', 'B'):
            for r in range(1, 4):
                task = f'{pair["pair_id"]}_r{r}_{cond}'; path = BASE / 'prompts' / (task + '.txt')
                INPUTS[str(path.relative_to(ROOT))] = sha(path); prompt = path.read_text()
                assert sha(path) == p['prompt_sha256'][path.name]
                assert journal['requests'][task]['prompt'] == prompt
                offsets = [prompt.index(f'\nPARENT {i}\nDescription: {par["candidate"]["description"]}\nCode:\n{par["candidate"]["code"]}\n') for i, par in enumerate(ps)]
                assert offsets == sorted(offsets)
                if cond in prompts: assert prompts[cond] == prompt
                prompts[cond] = prompt
        assert prompts['B'].count(block) == 1 and prompts['B'].replace(block, '', 1) == prompts['A']
        checks.append({'pair_id': pair['pair_id'], 'ordered_parents': pair['parents'],
                       'parent_1_fitness': f, 'parent_2_fitness': g, 'delta': g-f,
                       'prompts_match_sent_journal': True, 'only_feedback_block_diff': True})
    child_rows, details, diffs, results, snippets = [], {}, [], {}, []
    similarities = []
    for task in plan['tasks']:
        tid = task['task_id']; t = cp['tasks'][tid]; par = [parents[i] for i in task['parents']]
        assert all(t[k] == v for k, v in task.items())
        better, worse = sorted(par, key=lambda x: -x['fitness'])
        row = {**task, 'status': t['status'], 'fitness': t.get('fitness'),
               'delta_better': None, 'delta_worse': None, 'category': None}
        if 'candidate' not in t:
            assert tid == 'pair_03_r1_A' and t['status'] == 'transport_failed'
            attempt = journal['api_attempts'][journal['requests'][tid]['attempt_ids'][0]]
            assert attempt['metadata']['http_status'] == 524
            row.update(failure_class='HTTP_524_no_complete_response', modes_in_source='',
                       static_possible_members=[], state_inputs_in_source=[], if_nodes=None,
                       AST_nodes=None, observed_members=[], same_schedule_better_instances=None,
                       same_schedule_worse_instances=None, main_logic_change='无完整响应，未准入代码／求解')
            child_rows.append(row); continue
        code = t['candidate']['code']; description = t['candidate']['description']; key = t['evaluation_key']
        request = journal['requests'][tid]
        raw_code = re.findall(r'```(?:python)?\s*\n(.*?)```', request['text'], re.S)
        assert request['status'] == 'completed' and len(raw_code) == 1
        assert ast.dump(ast.parse(raw_code[0])) == ast.dump(ast.parse(code))
        assert description in request['text']
        assert request['response_metadata']['model'] == binding['provider']['model']
        assert request['response_metadata']['finish_reason'] == 'stop'
        result_path = EX / cp['evaluations'][key]['result_path']; result = read(result_path)
        assert sha(result_path) == cp['evaluations'][key]['result_sha256']
        assert result['valid'] and result['boundary']['decision'] == 'accepted'
        assert result['fitness'] == row['fitness'] == st.fmean(r['score'] for r in result['instances'])
        assert len(result['instances']) == 21
        life = read(result_path.parent / 'lifecycle.json')
        assert life['exitcode'] == 0 and not life['alive'] and life['receiver_thread_stopped']
        observed = set(); same = {}
        for parent in par:
            same[parent['id']] = 0
            for r, pr in zip(result['instances'], parent['instances']):
                assert r['file'] == pr['file'] and r['lower_bound'] == pr['lower_bound']
                assert r['score'] == -r['makespan']/r['lower_bound']
                assert r['feasible'] is True and type(r['makespan']) is int and r['makespan'] > 0
                assert r['captured_solves'] == 2 and r['single_h_calls'] == r['recheck_h_calls']
                assert r['physical_schedule_sha256'] == r['recheck_physical_schedule_sha256']
                observed.update(i for i, n in enumerate(r['single_h_calls']) if n)
                eq = r['physical_schedule_sha256'] == pr['physical_schedule_sha256']
                same[parent['id']] += eq
                dc = r['makespan'] - pr['makespan']
                diffs.append({'task_id': tid, 'pair_id': task['pair_id'], 'condition': task['condition'],
                              'parent_id': parent['id'], 'parent_role': 'better' if parent is better else 'worse',
                              'file': r['file'], 'LB': r['lower_bound'], 'child_Cmax': r['makespan'],
                              'parent_Cmax': pr['makespan'], 'raw_Cmax_child_minus_parent': dc,
                              'delta_F_contribution': -dc / (21*r['lower_bound']), 'physical_schedule_equal': eq})
        row.update(delta_better=row['fitness']-better['fitness'], delta_worse=row['fitness']-worse['fitness'],
                   category=category(row['fitness'], better['fitness'], worse['fitness']), failure_class='',
                   **signature(code), observed_members=sorted(observed),
                   same_schedule_better_instances=same[better['id']], same_schedule_worse_instances=same[worse['id']],
                   main_logic_change=annotations[tid]['main_logic_change'])
        child_rows.append(row); results[tid] = result
        details[tid] = {'code': code, 'description': description, 'key': key, 'physical': [r['physical_schedule_sha256'] for r in result['instances']]}
        snippets.append({'task_id': tid, 'description': description, **annotations[tid]})
        for role, parent in [('better', better), ('worse', worse)]:
            pc = parent['candidate']['code']
            similarities.append({'task_id': tid, 'condition': task['condition'], 'pair_id': task['pair_id'],
                                 'parent_role': role, 'parent_id': parent['id'],
                                 'exact_source': code == pc,
                                 'exact_AST': ast.dump(ast.parse(code)) == ast.dump(ast.parse(pc)),
                                 'alpha_body_equal': logic(code)[0] == logic(pc)[0],
                                 'shape_equal': logic(code, True)[0] == logic(pc, True)[0],
                                 'alpha_similarity': similar(code, pc), 'shape_similarity': similar(code, pc, True),
                                 'same_physical_instances': same[parent['id']]})
    # Per-instance contrasts use group means, NOT repeat-id pairs.
    contrast, pair_stats = [], []
    for pair in plan['pairs']:
        pid = pair['pair_id']; groups = {}
        for cond in ('A', 'B'):
            rows = [r for r in child_rows if r['pair_id'] == pid and r['condition'] == cond and r['fitness'] is not None]
            fs = [r['fitness'] for r in rows]; groups[cond] = rows
            pair_stats.append({'pair_id': pid, 'condition': cond, 'n': len(fs),
                               'all_Fitness': fs, 'mean': st.fmean(fs), 'median': st.median(fs),
                               'minimum': min(fs), 'maximum': max(fs),
                               **{k: sum(r['category'] == k for r in rows) for k in
                                  ['above_better','equal_better','between_strict','equal_worse','below_worse']}})
        for i, expected in enumerate(p['science']['instances']):
            ms = {c: st.fmean(results[r['task_id']]['instances'][i]['makespan'] for r in rs) for c, rs in groups.items()}
            contrast.append({'pair_id': pid, 'file': expected['file'], 'LB': expected['LB'],
                             'n_A': len(groups['A']), 'n_B': len(groups['B']),
                             'mean_Cmax_A': ms['A'], 'mean_Cmax_B': ms['B'],
                             'raw_mean_Cmax_B_minus_A': ms['B']-ms['A'],
                             'delta_F_B_minus_A_contribution': (ms['A']-ms['B'])/(21*expected['LB'])})
        actual = st.fmean(r['fitness'] for r in groups['B'])-st.fmean(r['fitness'] for r in groups['A'])
        assert abs(actual-sum(r['delta_F_B_minus_A_contribution'] for r in contrast if r['pair_id'] == pid)) < 1e-14
    for row in child_rows:
        if row['fitness'] is None: continue
        ds = [d for d in diffs if d['task_id'] == row['task_id'] and d['parent_role'] == 'better']
        row['vs_better_instance_W_L_T'] = [sum(d['raw_Cmax_child_minus_parent'] < 0 for d in ds),
                                          sum(d['raw_Cmax_child_minus_parent'] > 0 for d in ds),
                                          sum(d['raw_Cmax_child_minus_parent'] == 0 for d in ds)]
        row['sum_Cmax_difference_vs_better'] = sum(d['raw_Cmax_child_minus_parent'] for d in ds)
        assert abs(sum(d['delta_F_contribution'] for d in ds)-row['delta_better']) < 1e-14
    parent_summaries = []
    for tid in details:
        for role in ('better', 'worse'):
            ds = [d for d in diffs if d['task_id'] == tid and d['parent_role'] == role]
            parent_summaries.append({'task_id': tid, 'parent_role': role, 'parent_id': ds[0]['parent_id'],
                'W': sum(d['raw_Cmax_child_minus_parent'] < 0 for d in ds),
                'L': sum(d['raw_Cmax_child_minus_parent'] > 0 for d in ds),
                'T': sum(d['raw_Cmax_child_minus_parent'] == 0 for d in ds),
                'delta_F': sum(d['delta_F_contribution'] for d in ds),
                'sum_raw_Cmax_child_minus_parent': sum(d['raw_Cmax_child_minus_parent'] for d in ds),
                'physical_equal_instances': sum(d['physical_schedule_equal'] for d in ds)})
    tails = []
    for row in child_rows:
        if row['condition'] != 'B' or row['fitness'] is None: continue
        amean = next(r['mean'] for r in pair_stats if r['pair_id'] == row['pair_id'] and r['condition'] == 'A')
        tails.append({'pair_id': row['pair_id'], 'task_id': row['task_id'],
                      'B_Fitness': row['fitness'], 'A_mean': amean,
                      'additive_term_in_pair_mean_B_minus_A': (row['fitness']-amean)/3})
    # Keep CSV schema shared with failed logical slot.
    for row in child_rows:
        row.setdefault('vs_better_instance_W_L_T', []); row.setdefault('sum_Cmax_difference_vs_better', None)
    pair_contrasts = []
    for pair in plan['pairs']:
        pid = pair['pair_id']
        a, b = [next(r for r in pair_stats if r['pair_id'] == pid and r['condition'] == c) for c in ('A','B')]
        rs = [r for r in contrast if r['pair_id'] == pid]
        delta = b['mean']-a['mean']
        assert abs(delta-sum(r['additive_term_in_pair_mean_B_minus_A'] for r in tails if r['pair_id'] == pid)) < 1e-14
        pair_contrasts.append({'pair_id': pid, 'A_n': a['n'], 'B_n': b['n'],
            'delta_mean_B_minus_A': delta, 'delta_median_B_minus_A': b['median']-a['median'],
            'B_instance_mean_W': sum(r['raw_mean_Cmax_B_minus_A'] < 0 for r in rs),
            'B_instance_mean_L': sum(r['raw_mean_Cmax_B_minus_A'] > 0 for r in rs),
            'B_instance_mean_T': sum(r['raw_mean_Cmax_B_minus_A'] == 0 for r in rs),
            'sum_raw_mean_Cmax_B_minus_A': sum(r['raw_mean_Cmax_B_minus_A'] for r in rs)})
    matches = []
    ids = sorted(details)
    for i, a in enumerate(ids):
        for b in ids[i+1:]:
            da, db = details[a], details[b]
            exact = da['code'] == db['code']; ae = ast.dump(ast.parse(da['code'])) == ast.dump(ast.parse(db['code']))
            alpha = logic(da['code'])[0] == logic(db['code'])[0]
            physical = da['physical'] == db['physical']
            matches.append({'task_a': a, 'task_b': b, 'exact_source': exact, 'exact_AST': ae,
                            'alpha_body_equal': alpha, 'shape_equal': logic(da['code'],True)[0] == logic(db['code'],True)[0],
                            'all21_physical_equal': physical,
                            'physical_equal_instances': sum(x == y for x,y in zip(da['physical'], db['physical']))})
    assert len(journal['api_attempts']) == 30 and len(results) == 29
    assert len(diffs) == 1218 and len(contrast) == 105
    table('Children.csv', child_rows); table('Parent_similarity.csv', similarities)
    table('Child_similarity.csv', matches); table('Pair_statistics.csv', pair_stats)
    table('Instance_vs_parents.csv', diffs); table('Instance_AB_contributions.csv', contrast)
    table('Parent_comparison_summary.csv', parent_summaries); table('Tail_decomposition.csv', tails)
    table('Pair_contrasts.csv', pair_contrasts)
    dump('Response_review.json', snippets); dump('Prompt_audit.json', {'pairs': checks, 'provider': binding['provider'],
          'shared_config': binding['config'], 'method': 'sent journal == frozen prompts; B minus exact score block == A; source hash match'})
    dump('Summary.json', {'groups': {c: {'complete': sum(r['condition'] == c and r['fitness'] is not None for r in child_rows),
         'mean_Fitness': st.fmean(r['fitness'] for r in child_rows if r['condition'] == c and r['fitness'] is not None),
         'median_Fitness': st.median(r['fitness'] for r in child_rows if r['condition'] == c and r['fitness'] is not None),
         'categories': dict(Counter(r['category'] for r in child_rows if r['condition'] == c and r['fitness'] is not None)),
         'modes': dict(Counter(r['modes_in_source'] for r in child_rows if r['condition'] == c and r['fitness'] is not None)),
         'mean_similarity_better': st.fmean(r['alpha_similarity'] for r in similarities if r['condition'] == c and r['parent_role'] == 'better'),
         'mean_shape_similarity_better': st.fmean(r['shape_similarity'] for r in similarities if r['condition'] == c and r['parent_role'] == 'better'),
         'all21_equal_better': sum(r['same_physical_instances'] == 21 for r in similarities if r['condition'] == c and r['parent_role'] == 'better'),
         'exact_parent_copies': sum(r['exact_source'] for r in similarities if r['condition'] == c),
         'alpha_parent_copies': sum(r['alpha_body_equal'] for r in similarities if r['condition'] == c),
         'mean_if_nodes': st.fmean(r['if_nodes'] for r in child_rows if r['condition'] == c and r['fitness'] is not None)} for c in ('A','B')},
         'unique_AST': len({d['key'] for d in details.values()}),
         'unique_physical21': len({tuple(d['physical']) for d in details.values()}),
         'exact_child_duplicate_pairs': sum(m['exact_source'] for m in matches),
         'alpha_child_duplicate_pairs': sum(m['alpha_body_equal'] for m in matches),
         'all21_equal_child_pairs': sum(m['all21_physical_equal'] for m in matches),
         'new_API': 0, 'new_solves': 0, 'no_U_execution': True})
    assert all(sha(ROOT / n) == h for n, h in INPUTS.items()), 'input changed during analysis'
    dump('Input_evidence.json', {'source_commit': 'c7efd1169764117380de2b5e5e5c2a2db99750',
          'inputs_sha256': INPUTS, 'all_inputs_unchanged_after_analysis': True,
          'checks': ['30 actual sent prompts', '29 full responses', '29 accepted exit0 results',
                     '609 solve/recheck rows', '5 matched parents and 105 parent rows',
                     '1218 child-parent per-instance contrasts', '105 group mean instance contributions'],
          'limits': 'post-hoc descriptive analysis; no hypothesis test; no U execution or new schedules'})
    dump('Offline_validation.json', {'passed': True, 'AST_only_invariants':
          ['local rename invariant', 'literal retained by alpha metric', 'literal erased by shape metric',
           'member coordinate retained'], 'evidence_arithmetic_assertions': True,
          'network_process_guard_enabled': True, 'new_API': 0, 'new_solves': 0,
          'candidate_code_execution': False, 'analysis_script_sha256': sha(Path(__file__))})
    print(json.dumps({'outputs': str(OUT), 'children': len(results), 'new_API': 0, 'new_solves': 0}))


if __name__ == '__main__': main()
