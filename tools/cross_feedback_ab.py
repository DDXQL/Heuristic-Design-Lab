"""Independent CROSS-feedback preparation and fail-closed monetary preflight.

No inference or scheduling path is constructed by these stages. Formal execution
is blocked by missing verified currency/billable-token bounds, not by permission.
"""
import argparse
from dataclasses import asdict
import difflib
import hashlib
import json
from pathlib import Path
from statistics import median
import subprocess
import time
import unittest

from fjsp_usage.cross_feedback_ab import VERSION, CAPS, validate_parent, render, plan, fee_gate, FeeStop
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import checked_candidate, check_seal
from fjsp_usage.baseline_a.validation import validate_result

ROOT = Path(__file__).resolve().parents[1]
NAME = 'cross-feedback-ab-train21-seed501-v1-20261025'
DEFAULT = ROOT / 'runs' / NAME
REPORT = ROOT / 'reports' / NAME
ORIGIN = ROOT / 'runs/b1-ns-recovery-B-v1-20261022'
SCIENCE = ROOT / 'runs/baseline-a-supplemental-T30-seed501-20261024-v1'
CODE_FILES = ('code/fjsp_usage/cross_feedback_ab.py', 'tools/cross_feedback_ab.py',
              'tests/test_cross_feedback_ab.py', 'tools/b1_usage_prompts.py',
              'code/fjsp_usage/usage_v2/prompts.py', 'code/fjsp_usage/research_real/prompts.py',
              'code/fjsp_usage/research/candidates.py')
KERNEL_FILES = ('code/fjsp_usage/usage_v2/execution.py', 'code/fjsp_usage/offline_v2.py',
                'code/fjsp_usage/research/scheduler.py',
                'code/llm4ad/task/optimization/fjsp_set/instances.py',
                'code/llm4ad/task/optimization/fjsp_set/scheduler.py')


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parents_audit():
    """Targeted original records + byte identities; zero parent rescheduling."""
    p = read(ORIGIN/'Protocol.json'); c = read(ORIGIN/'r501/B/checkpoint.json')
    modern = read(SCIENCE/'Protocol.json'); frozen = read(SCIENCE/'H_frozen.json')
    check_seal(frozen, mode='real')
    if (sha(ORIGIN/'Protocol.json') != (ORIGIN/'Protocol.sha256').read_text().strip()
            or sha(SCIENCE/'Protocol.json') != (SCIENCE/'Protocol.sha256').read_text().strip()
            or p['H_order'] != modern['H_order'] or p['train_names'] != [r['file'] for r in modern['instances']]
            or [m['candidate']['key'] for m in frozen['members']] != p['H_order']
            or sha(SCIENCE/'H_frozen.json') != modern['H_sha256']):
        raise ValueError('original protocol/H/train identity mismatch')
    if p['config']['seeds'] != [501] or p['config']['H_size'] != 10:
        raise ValueError('original seed/H count mismatch')
    scientific = {'H_order': p['H_order'], 'seed': 501, 'interface': 'U-usage-v2-select-or-mix-20261012',
                  'metric': 'complete mean(-Cmax/LB), unrounded LB', 'instances': modern['instances'],
                  'kernel_sha256': {n: sha(ROOT/n) for n in KERNEL_FILES}}
    files = {str(f.relative_to(ROOT)): sha(f) for f in [ORIGIN/'Protocol.json',
        ORIGIN/'Protocol.sha256', ORIGIN/'r501/B/checkpoint.json', ORIGIN/'Revalidation.json',
        ORIGIN/'Final_identity_checks.json', SCIENCE/'Protocol.json', SCIENCE/'Protocol.sha256',
        SCIENCE/'H_frozen.json']}
    for n in KERNEL_FILES:
        if sha(ROOT/n) != p['snapshot_files'][n]:
            raise ValueError('scientific implementation differs from parent source: '+n)
        files[n] = sha(ROOT/n)
    for r in modern['instances']:
        source_name = 'data/fjsp/' + r['file']
        if p['snapshot_files'][source_name] != r['sha256'] or sha(SCIENCE/r['relative_path']) != r['sha256']:
            raise ValueError('parent data identity mismatch')
        files[str((SCIENCE/r['relative_path']).relative_to(ROOT))] = r['sha256']
    if read(ORIGIN/'Revalidation.json')['ready'] is not True:
        raise ValueError('P0 revalidation gate not ready')
    identities = {row['id']: row for row in read(ORIGIN/'Final_identity_checks.json')['complete_valid_child_before_after_checks']}
    parents, timings = [], []
    for row in c['population_snapshots']['P0']:
        key = row['candidate']['key']; result = c['evaluations'][row['id']]['result']
        checked = validate_parent(row, result, modern['instances'], scientific, scientific)
        validate_result(result, modern['instances'], 'legacy_pair')
        wi = result['worker_identity']; witnesses = []
        for when in ['before', 'after']:
            path = ORIGIN/'worker_evidence'/(key+'.'+when+'.json'); witness = read(path)
            if sha(path) != wi[when+'_sha256'] or witness['identity'] != digest(witness['modules']) or witness['identity'] != wi['loaded_identity']:
                raise ValueError('parent child attestation mismatch')
            for module in witness['modules'].values():
                # Preserve the hash-bound historical path in the witness;
                # read its pinned relative counterpart in this migrated tree.
                from heuristic_design.problems.fjsp.provenance import relocated_snapshot_source
                source, relative = relocated_snapshot_source(
                    module['file'], p['source_snapshot'], ORIGIN/'source_snapshot')
                if sha(source) != module['source_sha256'] or module['source_sha256'] != p['snapshot_files'][relative]:
                    raise ValueError('parent attested source changed')
                files[str(source.relative_to(ROOT))] = sha(source)
            files[str(path.relative_to(ROOT))] = sha(path); witnesses.append(witness)
        if witnesses[0]['pid'] != witnesses[1]['pid'] or identities[row['id']]['key'] != key:
            raise ValueError('parent worker/identity index mismatch')
        receipt = ORIGIN/'evaluation_receipts'/(key+'.json')
        if read(receipt) != {k: v for k, v in result.items() if k != 'worker_identity'}:
            raise ValueError('parent raw receipt/checkpoint mismatch')
        files[str(receipt.relative_to(ROOT))] = sha(receipt)
        compact = [{k: x[k] for k in ['file', 'makespan', 'lower_bound', 'score',
                   'physical_schedule_sha256', 'recheck_physical_schedule_sha256',
                   'single_solve_seconds', 'deterministic_recheck_seconds']} for x in result['instances']]
        seconds = sum(x['single_solve_seconds'] + x['deterministic_recheck_seconds'] for x in result['instances'])
        timings.append(seconds)
        parents.append({'id': row['id'], 'candidate': asdict(checked), 'fitness': row['fitness'],
                        'instances': compact, 'source_result_digest': digest(result),
                        'source_result_path': 'runs/b1-ns-recovery-B-v1-20261022/r501/B/checkpoint.json',
                        'source_result_key': 'evaluations.'+row['id']+'.result',
                        'worker_identity': wi, 'context_sha256': digest(scientific)})
    if len({p['candidate']['key'] for p in parents}) != len(parents):
        raise ValueError('duplicate parent source keys; do not sample as distinct programs')
    provider = p['config']['provider']
    return parents, frozen, scientific, files, {'provider': provider,
        'parent_kind': 'historical B1 free SELECT/MIX P0, not B2 fixed weights',
        'valid_parents': len(parents), 'unordered_pairs_available': len(parents)*(len(parents)-1)//2,
        'parent_resource_protocol': 'legacy T15 complete solve/recheck + original before/after source evidence',
        'parent_two_solve_train_seconds': timings,
        'projected_30_evaluations_seconds_at_parent_median': 30*median(timings),
        'projected_30_evaluations_seconds_at_parent_max': 30*max(timings),
        'projection_limit': 'saved parent compute time only; child programs/API/IPC may differ; not a duration guarantee'}


def accept():
    if (REPORT/'Offline_acceptance.json').exists():
        raise ValueError('acceptance already exists; preserve evidence')
    REPORT.mkdir(exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromName('tests.test_cross_feedback_ab')
    with (REPORT/'Offline_acceptance.log').open('w') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    evidence = {'passed': result.wasSuccessful(), 'tests_run': result.testsRun,
                'failures': len(result.failures), 'errors': len(result.errors),
                'files': {n: sha(ROOT/n) for n in CODE_FILES},
                'real_API_calls': 0, 'formal_solves': 0, 'toy_solves': 0,
                'scope': 'synthetic dictionaries, prompt byte equality and pure cost/plan guards; network/solver patched to fail'}
    atomic_json(REPORT/'Offline_acceptance.json', evidence)
    if not evidence['passed']:
        raise ValueError('offline acceptance failed')


def prepare():
    if DEFAULT.exists():
        raise ValueError('existing campaign; never reprepare or redraw')
    acceptance = read(REPORT/'Offline_acceptance.json')
    if not acceptance['passed'] or any(sha(ROOT/n) != h for n, h in acceptance['files'].items()):
        raise ValueError('accepted code changed')
    parents, frozen, science, files, audit = parents_audit()
    plans = plan([r['id'] for r in parents])  # no Fitness input to the sampler
    DEFAULT.mkdir(); (DEFAULT/'prompts').mkdir()
    atomic_json(DEFAULT/'Parents.json', parents); atomic_json(DEFAULT/'Tasks.json', plans)
    (DEFAULT/'H_frozen.json').write_bytes((SCIENCE/'H_frozen.json').read_bytes())
    by_id = {r['id']: r for r in parents}
    members = []
    for row in frozen['members']:
        c = checked_candidate(row['candidate'], 'h')
        from fjsp_usage.research.candidates import Candidate
        members.append(Candidate(row['review']['description'], c.code, c.key, 'h'))
    prompt_hashes = {}
    for task in plans['tasks']:
        ordered = [by_id[i] for i in task['parents']]
        raw = render(task['condition'], ordered, members, [r['fitness'] for r in ordered])
        name = task['task_id']+'.txt'; (DEFAULT/'prompts'/name).write_text(raw)
        prompt_hashes[name] = sha(DEFAULT/'prompts'/name)
    first = plans['pairs'][0]
    a = (DEFAULT/'prompts'/(first['pair_id']+'_r1_A.txt')).read_text().splitlines(keepends=True)
    b = (DEFAULT/'prompts'/(first['pair_id']+'_r1_B.txt')).read_text().splitlines(keepends=True)
    (REPORT/'Rendered_AB.diff').write_text(''.join(difflib.unified_diff(a, b, fromfile='A current CROSS', tofile='B only score block')))
    authorization = {'approved': True, 'origin': 'human user instruction in this conversation, 2026-10-25',
        'scope': 'CROSS feedback A/B; historical P0; 5 unordered pairs x3 x2; real generation and train21 evaluation allowed after all gates',
        'caps': CAPS, 'no_C_no_reflection_call': True, 'no_A4_no_holdout_no_push': True,
        'fee_requirement': 'reliable <=20 CNY including uncertain requests; stop before real dispatch if absent',
        'approval_is_not_a_technical_fee_certificate': True}
    atomic_json(DEFAULT/'Authorization.json', authorization)
    p = {'version': VERSION, 'base_commit': 'd793c7a980a6443b57619b66ae1a22d275552d1c',
         'science': science, 'population_N': 5, 'caps': CAPS, 'parent_audit': audit,
         'provider': audit['provider'], 'generation_seed': None,
         'generation_seed_note': 'current configured provider does not send a seed parameter',
         'source_files': acceptance['files'], 'protected_files': files, 'prompt_sha256': prompt_hashes,
         'asset_sha256': {n: sha(DEFAULT/n) for n in ['Parents.json', 'Tasks.json', 'H_frozen.json', 'Authorization.json']},
         'result_wait_seconds': 30, 'exit_grace_seconds': 2., 'solve_seed': 501,
         'evaluator_reference': 'fjsp_usage.baseline_supplemental.lifecycle.collect/classify; existing V1 usage kernel',
         'formal_adapter_status': 'not connected/accepted; monetary gate blocked before any formal dispatch',
         'launch_window': '21600 seconds from first actual run; no Run_clock is created by prepare/check',
         'deadline': 'limit new starts; finish active candidate with original T30/exit rules; persistent and never reset',
         'feedback_delta': 'Fitness(parent_2/PARENT 1) minus Fitness(parent_1/PARENT 0); supersedes prior draft direction',
         'retry': 'complete response parsed once even if invalid; only evidenced transient transport failures; <=2/task, <=40 total; uncertain holds retained; no refill',
         'cache': 'identity-matched certified duplicates may save solves but consume logical slots; never historical children as new A',
         'analysis': {'quality': 'valid certified only: pair x arm mean/median/min/max; null for no valid child',
              'process': 'all planned/started/completed slots, parsing, duplicate, retries, timeouts and certification separately',
              'improvement': 'strict Fchild>max(Fparent1,Fparent2); counts divided by all allocated slots and valid child count separately',
              'paired_unit': 'pair_id x repeat_id, no assumption of paired stochastic model output',
              'pair_difference': 'B-A within each parent pair; incomplete arm =>null; best child supplementary',
              'uncertainty': '5 parent contexts, 3 correlated generations each; descriptive only; no multi-generation/generalization claim'},
         'stop': 'unknown identity/exit/recheck/ledger/reservation, fee proof missing, deadline, source mismatch; never clear unknown state automatically'}
    atomic_json(DEFAULT/'Protocol.json', p); (DEFAULT/'Protocol.sha256').write_text(sha(DEFAULT/'Protocol.json')+'\n')
    atomic_json(DEFAULT/'checkpoint.json', {'protocol_sha256': sha(DEFAULT/'Protocol.json'),
        'phase': 'prepared_not_run', 'logical_started': 0, 'completed_responses': 0, 'tasks': {}})
    atomic_json(DEFAULT/'API_cost_ledger.json', {'protocol_sha256': sha(DEFAULT/'Protocol.json'),
        'attempts': {}, 'logical': {}, 'actual_cost_CNY': 0, 'conservative_unknown_CNY': 0,
        'hold_rule': 'no attempts =>zero new inference cost; future unknown billing keeps full verified reservation'})
    atomic_json(DEFAULT/'Evaluation_ledger.json', {'protocol_sha256': sha(DEFAULT/'Protocol.json'),
        'program_instances_reserved': 0, 'solve_passes_reserved': 0, 'solve_passes_started': 0, 'evaluations': {}})
    atomic_json(REPORT/'Parent_audit.json', {**audit, 'science_sha256': digest(science),
        'parents': [{'id': r['id'], 'key': r['candidate']['key'], 'fitness': r['fitness']} for r in parents],
        'files_sha256': files})
    check()


def check():
    p = read(DEFAULT/'Protocol.json')
    if sha(DEFAULT/'Protocol.json') != (DEFAULT/'Protocol.sha256').read_text().strip():
        raise ValueError('protocol changed')
    for n, h in {**p['source_files'], **p['protected_files']}.items():
        if sha(ROOT/n) != h:
            raise ValueError('frozen source/evidence changed: '+n)
    for n, h in p['asset_sha256'].items():
        if sha(DEFAULT/n) != h:
            raise ValueError('frozen campaign asset changed')
    for n, h in p['prompt_sha256'].items():
        if sha(DEFAULT/'prompts'/n) != h:
            raise ValueError('frozen prompt changed')
    if plan([r['id'] for r in read(DEFAULT/'Parents.json')]) != read(DEFAULT/'Tasks.json'):
        raise ValueError('frozen sampling/order mismatch')
    if read(DEFAULT/'checkpoint.json')['protocol_sha256'] != sha(DEFAULT/'Protocol.json'):
        raise ValueError('checkpoint protocol mismatch')
    return p


def preflight():
    check()
    pricing = read(REPORT/'Preflight_1.json'); status = read(REPORT/'Preflight_0.json')
    quota = read(REPORT/'Preflight_2.json'); models = read(REPORT/'Preflight_3.json')
    rows = pricing.get('models', [])
    proof = {'live_model_and_tariff_verified': (pricing.get('success') is True and len(rows) == 1
             and rows[0]['model_name'] == 'gpt-6.1-sol' and rows[0]['billing_mode'] == 'tiered_expr'
             and models.get('locked_model_listed') is True),
         'CNY_conversion_verified': False,
         'billable_token_upper_bound_verified': False,
         'other_task_account_encumbrance_verified': False,
         'monetary_adapter_accepted': False,
         'currency_evidence': status.get('public_fields'), 'quota_snapshot': quota.get('quota'),
         'existing_risk_policy': 'code/fjsp_usage/usage_v2/model_migration.py: certified_provider_upper_bound=False',
         'evidence_missing': ['actual merchant-debit CNY conversion, not USD display/exchange setting',
             'provider-backed maximum billable input/output/reasoning/cache counts for configured request',
             'current account encumbrance/exclusive-caller proof, not merely absence of local processes',
             'accepted monetary reservation/receipt settlement adapter'],
         'inference_requests': 0, 'formal_solves': 0}
    try:
        fee_gate(proof)
    except FeeStop as exc:
        proof.update(decision='STOP_BEFORE_INFERENCE', reason=str(exc), authorization_missing=False)
        atomic_json(DEFAULT/'Fee_stop.json', proof)
        state = read(DEFAULT/'checkpoint.json'); state['phase'] = 'blocked_before_inference_by_fee_gate'
        atomic_json(DEFAULT/'checkpoint.json', state)
        atomic_json(REPORT/'Fee_gate.json', proof)
        return proof
    raise RuntimeError('new verified money adapter needs independent acceptance; no implicit run path')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('accept', 'prepare', 'check', 'preflight'))
    args = parser.parse_args()
    if args.stage == 'accept': accept()
    elif args.stage == 'prepare': prepare()
    elif args.stage == 'check': check()
    else: preflight()
    print(args.stage, 'completed; real model requests=0, FJSP solves=0', flush=True)


if __name__ == '__main__': main()
