"""Offline protocol drafts, prompt previews and train-only timing calibration.

No client construction, secret loading, requests or real holdout evaluation.
All preview H/U programs are explicitly handwritten interface fixtures.
"""

from dataclasses import replace
import math
from pathlib import Path

from fjsp_usage.research.candidates import H_ARGS, U_ARGS, validate_code
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from .config import ExperimentConfig, ProviderConfig, fingerprint, finite_positive
from .diagnostics import h_complementarity
from .prompts import build_prompt, prompt_manifest
from .runtime import evaluate


def preview_members(size=10):
    return tuple(validate_code('def priority(' + ', '.join(H_ARGS) + '):\n    return -earliest_finish + '
        + str(i/100) + ' * processing_time', kind='h',
        description=f'Handwritten preview fixture {i}: negative finish plus {i/100} times duration; NOT formal H.')
        for i in range(size))


def preview_parents(size=5):
    return [{'candidate': {'description': f'Handwritten preview parent {i}; not generated or evaluated.',
        'code': 'def select_heuristic(' + ', '.join(U_ARGS) + '):\n    if progress < '
            + str((i+1)/10) + ':\n        return 0\n    return 1'}} for i in range(size)]


def draft_configs(*, instance_timeout=2.0, provider=None):
    provider = provider or ProviderConfig('https://api.deepseek.com/chat/completions', 'deepseek-flash',
        protocol='deepseek-chat-v1', api_key_env='DEEPSEEK_API_KEY', thinking='disabled',
        temperature=.7, connect_timeout=10, read_timeout=30, total_timeout=90,
        max_output_tokens=2048, input_token_reservation=65536)
    formal = ExperimentConfig(provider=provider, mode='real', real_requests_authorized=False,
        instance_timeout=instance_timeout)
    pilot = replace(formal, seeds=(101,), attempts_per_generation=10, generations=1,
                    total_request_cap=150)
    return {label: replace(c, total_request_cap=sum(c.default_phase_caps().values()),
                           phase_request_caps=c.default_phase_caps())
            for label, c in (('paired-pilot', pilot), ('formal', formal))}


def calibrate_training(dataset, *, timeout=10.0):
    finite_positive(timeout, 'calibration timeout')
    opened_before = len(dataset.opened)
    instances = dataset.load('train')
    # Reuse the EFT/SPT expressions from the earlier development demo.
    members = tuple(validate_code('def priority(' + ', '.join(H_ARGS) + '):\n    return ' + expression,
        kind='h', description=description) for expression, description in (
            ('-earliest_finish', 'EFT handwritten calibration fixture.'),
            ('-processing_time', 'SPT handwritten calibration fixture.')))
    selectors = [(f'constant-{k}', validate_code('def select_heuristic(' + ', '.join(U_ARGS)
                    + '):\n    return ' + str(k), description='Handwritten constant calibration fixture.'))
                    for k in range(2)]
    selectors.append(('state-demo', validate_code('def select_heuristic(' + ', '.join(U_ARGS)
        + '):\n    if progress < 0.5:\n        return 0\n    return 1', description='Handwritten progress switch fixture.')))
    results = {name: evaluate(candidate, members, instances, dataset.names['train'], timeout=timeout)
               for name, candidate in selectors}
    h_results = [evaluate(c, (), instances, dataset.names['train'], timeout=timeout) for c in members]
    equivalence = []
    for k, h_result in enumerate(h_results):
        u_result = results[f'constant-{k}']
        equal = bool(u_result['valid'] and h_result['valid'] and
            [r['makespan'] for r in u_result['instances']] == [r['makespan'] for r in h_result['instances']])
        equivalence.append({'member_id': k, 'constant_U_matches_single_h': equal})
        if u_result['valid'] and h_result['valid'] and not equal:
            raise ValueError('constant U / original h schedule mismatch')
    all_results = list(results.values()) + h_results
    complete = all(r['valid'] for r in all_results)
    max_solve = max((r['single_solve_seconds'] for b in all_results for r in b['instances']), default=0)
    max_pair = max((r['single_solve_seconds']+r['deterministic_recheck_seconds']
                   for b in all_results for r in b['instances']), default=0)
    overhead = max((max(0, b['elapsed_seconds']-sum(r['single_solve_seconds']+
                r['deterministic_recheck_seconds'] for r in b['instances'])) for b in all_results), default=0)
    suggested = max(2, math.ceil(3*(max_pair+overhead))) if complete else None
    h_rows = [{'id': f'handwritten-{i}', 'scores': [r['score'] for r in b['instances']]}
              for i, b in enumerate(h_results)]
    return {'mode': 'offline handwritten train calibration; NOT a formal H/U experiment',
        'model_requests': 0, 'holdout_instances_opened': sum(split != 'train' for split, _ in dataset.opened[opened_before:]),
        'training_files': list(dataset.names['train']), 'dataset': dataset.metadata,
        'calibration_deadline_seconds': timeout, 'all_batches_valid': complete,
        'selector_results': results, 'h_results': h_results, 'constant_equivalence': equivalence,
        'demo_H_diagnostics': h_complementarity(h_rows, dataset.names['train'])
            if all(b['valid'] for b in h_results) else None,
        'max_single_solve_seconds': max_solve, 'max_solve_plus_recheck_seconds': max_pair,
        'max_batch_overhead_seconds': overhead, 'suggested_instance_timeout_seconds': suggested,
        'timing_note': 'suggestion includes conservative measured overhead and 3x margin; fixtures do not bound generated program runtime'}


def write_preparation(directory, *, root, dataset, calibration=None, provider=None):
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()):
        raise ValueError('use a new offline preparation directory; do not overwrite existing evidence')
    directory.mkdir(parents=True, exist_ok=True)
    deadline = (calibration or {}).get('suggested_instance_timeout_seconds') or 2.0
    configs = draft_configs(instance_timeout=deadline, provider=provider)
    members, parents = preview_members(), preview_parents()
    previews = []
    requests = [('shared-initial', 'B0', 'I1', [], members, 'U'),
                ('H-initial', 'H', 'I1', [], (), 'h'),
                ('H-CS-E1', 'H', 'E1', parents[:2], (), 'h'),
                ('H-LS-M1', 'H', 'M1', parents[:1], (), 'h')]
    # H-parent previews need h interfaces, not selector functions.
    h_parents = [{'candidate': {'description': m.description, 'code': m.code}} for m in members]
    requests[2] = ('H-CS-E1', 'H', 'E1', h_parents[:2], (), 'h')
    requests[3] = ('H-LS-M1', 'H', 'M1', h_parents[:1], (), 'h')
    for arm in ('B0', 'B1', 'B2', 'P'):
        operators = ('E1', 'E2', 'M1', 'M2', 'M3') if arm in ('B0', 'B1') else ('CROSS', 'MUTATE')
        for op in operators:
            requests.append((arm+'-'+op, arm, op, parents[:5] if op in ('E1','E2','CROSS') else parents[:1], members, 'U'))
    for label, arm, op, pp, hh, kind in requests:
        prompt = build_prompt(arm, op, pp, hh, kind=kind)
        path = directory/'prompt_previews'/f'{label}.txt'
        path.parent.mkdir(exist_ok=True)
        path.write_text(prompt, encoding='utf-8')
        previews.append({'file': str(path.relative_to(directory)), 'prompt_sha256': digest(prompt),
            'utf8_bytes': len(prompt.encode('utf-8')), 'kind': kind, 'parent_count': len(pp)})
    atomic_json(directory/'prompt_pack.json', prompt_manifest())
    for label, c in configs.items():
        atomic_json(directory/f'config.{label}.draft.json', c.payload())
    if calibration is not None:
        atomic_json(directory/'train_calibration.json', calibration)
    plan = {'kind': 'V5 offline preparation; DRAFT, not paid authorization or formal registration',
        'model_requests': 0, 'prompt_pack': prompt_manifest(), 'dataset': dataset.metadata,
        'implementation': fingerprint(root), 'preview_status': 'handwritten H and parents; NOT reviewed formal assets',
        'prompt_previews': previews, 'largest_preview_utf8_bytes': max(r['utf8_bytes'] for r in previews),
        'preview_fits_configured_bytes': all(r['utf8_bytes'] <= configs['formal'].provider.max_prompt_bytes for r in previews),
        'capacity_note': 'preview length is not a token count or an upper bound on real H+parent prompts; every real request checks bytes before send',
        'request_caps': {label: {'phases': c.phase_caps(), 'total': c.total_request_cap,
                               'estimated_cost': None, 'real_requests_authorized': c.real_requests_authorized}
                         for label, c in configs.items()},
        'H_protocol': {'K': 10, 'seed': 7, 'initialization_cap': 50, 'generations': 1, 'attempts_per_generation': 10,
            'CS': 'E1, two complementary parents, first half of slots', 'LS': 'M1, one rank-selected parent, second half',
            'CPM': 'best mean first, then maximal training-envelope gain; stable mean/id ties',
            'status': 'small reference draft; generation budget and quality evidence NOT approved',
            'review': 'exact generated code keys; four review strings and recomputed sample scores; exact K, full train, no synthetic promotion'},
        'pending_API_tasks': [
            'provider/model and usage/billing calibration, including real long H+5-parent prompts',
            'generate a real EoH-S-adapter H; no handwritten/sample promotion',
            'generate shared initialization and real paired four-arm pilot candidates',
            'generate R repeats of formal B0/B1/B2/P candidates'],
        'pending_offline_or_human_tasks': [
            'confirm provider/model snapshot and final K/R/H-search budget/currency cap before enabling requests',
            'read actual generated H and review behavior, then freeze exact K',
            'validate generated candidates on full train; select on validation only after complete search; freeze and run test',
            'H is context-bound to its run; reusing a pilot H under a changed protocol needs an audited import, not copying JSON'],
        'claim_boundaries': ['synthetic end-to-end is software acceptance only', 'train fixtures do not prove P gains',
                             'validation/test local solving needs no API but requires completed real search and freeze gates']}
    atomic_json(directory/'offline_plan.json', plan)
    return plan
