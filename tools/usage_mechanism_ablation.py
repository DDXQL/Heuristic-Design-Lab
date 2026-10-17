#!/usr/bin/env python3
"""Frozen seed301 diagnostic: four one-shot train evaluations, no API/search.

prepare freezes sources/identities; evaluate refuses a second batch invocation.
Production candidates, executor, protocol and original run are read-only.
"""
import argparse
import ast
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess

from fjsp_usage.offline_v2 import lower_bound_v5
from fjsp_usage.research.candidates import compile_candidate, validate_code
from fjsp_usage.research_real.assets import check_result, check_seal, checked_candidate
from fjsp_usage.research_real.runtime import evaluate
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.usage_v2 import VERSION

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'runs/v22-gpt61-select-mix-301-20261014-v1'
ARCHIVE = ROOT / 'docs/usage-space/real-gpt61-301'
OUT = ROOT / 'reports/usage-v22-mechanism-ablation-301-20261017-v1'
TARGETS = ('B/g0000/000005', 'B/g0000/000003')
RULES = {
    'original': 'Reuse identity-checked complete original evaluation; no replay.',
    'equal': 'Evaluate original scalar expressions once at each terminal return; replace each positive weight with 1, others with 0; MIX host normalizes. All original state computations and support-selection branches retained.',
    'winner': 'Retain original scalar vector and change terminal mode from MIX=1 to SELECT=0. Argmax of raw nonnegative weights equals argmax of normalized weights; first maximum wins. Host calls only this h, with raw action scores.',
}


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')


def transform(code, variant, size=10):
    """Deliberately narrow: validated candidates whose every terminal mode is MIX.

    Generated locals avoid collisions; expressions are evaluated once, in order.
    No wrapper, dict, helper function or change to previous_heuristic semantics.
    """
    original = validate_code(code, interface_version=VERSION, member_count=size)
    if variant not in ('equal', 'winner'):
        raise ValueError('only equal/winner interventions supported')
    tree = ast.parse(original.code)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    prefix = 'ablationWeight'
    while any(f'{prefix}{i}' in names for i in range(size)):
        prefix += 'X'

    class Intervention(ast.NodeTransformer):
        def visit_Return(self, node):
            mode, vector = node.value.elts
            if not isinstance(mode, ast.Constant) or type(mode.value) is not int or mode.value != 1:
                raise ValueError('frozen diagnostic requires literal MIX on every return')
            if variant == 'winner':
                node.value.elts[0] = ast.Constant(0)
                return node
            assignments = [ast.Assign([ast.Name(f'{prefix}{i}', ast.Store())], value)
                           for i, value in enumerate(vector.elts)]
            vector.elts = [ast.IfExp(ast.Compare(ast.Name(f'{prefix}{i}', ast.Load()),
                [ast.Gt()], [ast.Constant(0.0)]), ast.Constant(1.0), ast.Constant(0.0))
                for i in range(size)]
            return assignments + [node]

    changed = ast.unparse(ast.fix_missing_locations(Intervention().visit(tree))) + '\n'
    return validate_code(changed, description=f'Deterministic diagnostic {variant} intervention',
                         interface_version=VERSION, member_count=size)


def compact(result, *, keep_decisions=True):
    """Keep certified primary data/decisions, not duplicate historical replay traces."""
    value = {k: v for k, v in result.items() if k not in ('instances', 'selector_diagnostics')}
    value['instances'] = []
    for row in result['instances']:
        item = {k: v for k, v in row.items() if k not in
                ('state_trajectory', 'predicate_coverage', 'usage_decisions')}
        if keep_decisions:
            item['decision_support_weights'] = [[mode, support, [weights[i] for i in support], dominant]
                for mode, vector, support, weights, dominant in row.get('usage_decisions', [])]
        value['instances'].append(item)
    return value


def resource_snapshot():
    # Do not expose process arguments (which might contain unrelated credentials).
    lines = subprocess.check_output(['ps', '-axo', 'pid,ppid,%cpu,comm'], text=True).splitlines()
    return {'time_utc': datetime.now(timezone.utc).isoformat(),
            'python_processes': [line.strip() for line in lines[1:] if 'python' in line.lower()],
            'isolated': False,
            'note': 'Serial local evaluations; OS resources not reserved. Originals/fixed h have historical timings; descriptive timing only.'}


def inputs():
    protocol = read(RUN / 'protocol.json')
    for relative, expected in protocol['implementation']['files'].items():
        if sha(ROOT / relative) != expected:
            raise ValueError(f'production implementation changed: {relative}')
    dataset = StagedDataset(ROOT / 'data/fjsp_manifest.json', project_root=ROOT, mode='real')
    if dataset.metadata != protocol['dataset']:
        raise ValueError('dataset manifest identity changed')
    names = list(dataset.names['train'])
    if len(names) != 21 or protocol['config']['instance_timeout'] != 15:
        raise ValueError('requires original train21 and 15-second deadline')
    frozen, reassessment = read(RUN / 'H_frozen.json'), read(RUN / 'Conditional_H_reassessment.json')
    check_seal(frozen, kind='H_frozen', mode='real')
    check_seal(reassessment, kind='Conditional_H_reassessment', mode='real', context=frozen['context'])
    if (frozen['source_hash'] != reassessment['artifact_sha256']
            or frozen['scope_approval']['source_H_sha256'] != reassessment['source_H_hash']
            or frozen['training_files'] != names or reassessment['training_files'] != names):
        raise ValueError('H source/order/data mismatch')
    if len(frozen['members']) != 10 or len(reassessment['rows']) != 10:
        raise ValueError('requires frozen ten H')
    members = []
    for member, row in zip(frozen['members'], reassessment['rows']):
        if member['id'] != row['source_row']['id'] or member['candidate'] != row['source_row']['candidate']:
            raise ValueError('fixed h reassessment/member identity mismatch')
        members.append(checked_candidate(member['candidate'], 'h'))
        check_result(row['result'], names)
    return protocol, dataset, frozen, reassessment, tuple(members), names


def prepare():
    protocol, dataset, frozen, reassessment, members, names = inputs()
    dataset.verify('train')
    checkpoint_path = RUN / 'r301/B/checkpoint.json'
    checkpoint = read(checkpoint_path)
    index = read(ARCHIVE / 'All_generated_candidates.json')
    OUT.mkdir(parents=True, exist_ok=False)
    (OUT / 'sources').mkdir()
    (OUT / 'results').mkdir()
    pins = [RUN / 'protocol.json', RUN / 'H_frozen.json', RUN / 'Conditional_H_reassessment.json',
            checkpoint_path, ARCHIVE / 'All_generated_candidates.json', ARCHIVE / 'All_instance_results.csv',
            ARCHIVE / 'Final_evidence_manifest.json', ROOT / 'data/fjsp_manifest.json']
    versions = []
    for target in TARGETS:
        entry = next(row for row in index if row['id'] == target)
        source = ARCHIVE / entry['source']
        pins.append(source)
        candidate = validate_code(source.read_text(), interface_version=VERSION, member_count=10)
        if candidate.key != entry['code_key']:
            raise ValueError('source/index identity mismatch')
        result = checkpoint['evaluations'][target]['result']
        check_result(result, names)
        if not result['valid'] or not math.isclose(result['fitness'], entry['fitness'], rel_tol=1e-12):
            raise ValueError('target must be a complete valid original')
        # Bind the actual checkpoint attempt, not only the public index.
        attempt = next(x for x in checkpoint['attempts'] if x['id'] == target)
        if attempt['code_key'] != candidate.key:
            raise ValueError('checkpoint code key mismatch')
        for variant in ('original', 'equal', 'winner'):
            derived = candidate if variant == 'original' else transform(candidate.code, variant)
            label = f'B{int(target.rsplit("/",1)[1])}_{variant}'
            source_path = OUT / 'sources' / f'{label}.py'
            source_path.write_text(derived.code)
            row = {'id': label, 'original_id': target, 'variant': variant,
                   'candidate': asdict(derived), 'source_sha256': sha(source_path),
                   'rule': RULES[variant], 'reused': variant == 'original'}
            versions.append(row)
            if variant == 'original':
                write(OUT / 'results' / f'{label}.json', compact(result))
    # Only compact already-existing evidence for the three failures.
    failures = {}
    for key, value in checkpoint['evaluations'].items():
        result = value['result']
        if not result['valid']:
            entry = next(x for x in index if x['id'] == key)
            source = ARCHIVE / entry['source']
            pins.append(source)
            failures[key] = {'source': str(source.relative_to(ROOT)),
                             'result': compact(result, keep_decisions=False)}
    write(OUT / 'Historical_timeouts.json', failures)
    fixed = [{'id': f'H{i}', 'source_id': member['id'], 'code_key': member['candidate']['key'],
              'result': row['result']} for i, (member, row) in enumerate(zip(frozen['members'], reassessment['rows']))]
    write(OUT / 'Fixed_H_reused.json', fixed)
    pins += list(dataset.paths['train'])
    pins += [ROOT / p for p in protocol['implementation']['files']]
    write(OUT / 'Plan.json', {'original_run': str(RUN.relative_to(ROOT)), 'new_model_requests': 0,
        'train_only': True, 'timeout_seconds': 15, 'independent_diagnostic_replay': False,
        'max_versions': 6, 'new_full_evaluations': 4, 'reused_full_evaluations': 2,
        'names': names, 'versions': versions, 'transformation_rules': RULES,
        'history_notice': 'Host updates previous_heuristic from actual intervention output; equal-weight ties may change dominant id and later states. These are whole-policy interventions, not coefficient-isolated counterfactuals.',
        'pins': {str(p.relative_to(ROOT)): sha(p) for p in pins},
        'H_source_hash': frozen['source_hash'], 'H_order': [m['candidate']['key'] for m in frozen['members']],
        'score': 'mean(-Cmax/max(max_j shortest_work_j, sum_j shortest_work_j/M)); unrounded',
        'timing_notice': resource_snapshot()})
    print('Prepared six frozen versions; two reused, four pending; no evaluation yet.', flush=True)


def verify_pins(plan):
    for relative, expected in plan['pins'].items():
        if sha(ROOT / relative) != expected:
            raise ValueError(f'original evidence changed: {relative}')


def run_evaluations():
    plan = read(OUT / 'Plan.json')
    verify_pins(plan)
    protocol, dataset, frozen, reassessment, members, names = inputs()
    if names != plan['names'] or [m.key for m in members] != plan['H_order']:
        raise ValueError('prepared inputs changed')
    instances = dataset.load('train')  # Only authorized train file contents opened.
    bounds = {name: lower_bound_v5(instance) for name, instance in zip(names, instances)}
    for row in read(OUT / 'Fixed_H_reused.json'):
        for item in row['result']['instances']:
            if not math.isclose(item['lower_bound'], bounds[item['file']], rel_tol=1e-12):
                raise ValueError('fixed h LB differs from current unrounded V5 LB')
    for row in plan['versions']:
        if row['reused']:
            for item in read(OUT / 'results' / f'{row["id"]}.json')['instances']:
                if not math.isclose(item['lower_bound'], bounds[item['file']], rel_tol=1e-12):
                    raise ValueError('original U LB mismatch')
    # Exclusive marker precedes every solve: interrupted/unknown calls cannot be
    # repeated merely by invoking the command again.
    write(OUT / 'Evaluation_started.json', resource_snapshot())
    for row in plan['versions']:
        if row['reused']:
            continue
        candidate = checked_candidate(row['candidate'], 'U')
        if sha(OUT / 'sources' / f'{row["id"]}.py') != row['source_sha256']:
            raise ValueError('derived source changed after freeze')
        write(OUT / 'results' / f'{row["id"]}.started.json', resource_snapshot())
        print(f'Start {row["id"]}: one train21 evaluation + recheck, 15s/instance.', flush=True)
        result = evaluate(candidate, members, instances, names, timeout=15,
                          diagnostics=False, allowed_modes=(0, 1))
        check_result(result, names)
        write(OUT / 'results' / f'{row["id"]}.json', compact(result))
        print(f'End {row["id"]}: valid={result["valid"]}, fitness={result["fitness"]}, '
              f'completed={len(result["instances"])}/21, failed={result.get("failed_instance")}', flush=True)
        verify_pins(plan)
    write(OUT / 'Evaluation_complete.json', {'new_full_evaluations': 4,
          'reused_originals': 2, 'new_model_requests': 0, 'opened': dataset.opened,
          'original_pins_unchanged': True, 'bounds': bounds,
          'resource_snapshot': resource_snapshot()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'evaluate'))
    arguments = parser.parse_args()
    (prepare if arguments.stage == 'prepare' else run_evaluations)()
