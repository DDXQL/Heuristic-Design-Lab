#!/usr/bin/env python3
"""Bounded H0/H1 alpha search: a narrow adapter over the existing Search/runtime.

prepare/check are offline. register/grid/search require a final peer handoff.
No stage creates instances, initializes via LLM, retries a send or visits holdouts.
"""
import argparse
import ast
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import fmean
import tarfile
import time
import platform
import importlib.metadata
from unittest.mock import patch

from fjsp_usage.research.candidates import U_ARGS, CandidateError, parse_response, compile_candidate
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_result, check_seal, seal
from fjsp_usage.research_real.budget import BudgetLedger, BudgetStop
from fjsp_usage.research_real.config import ExperimentConfig
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.runtime import evaluate
from fjsp_usage.research_real.search import BudgetedSearch
from fjsp_usage.research_real.prompts import U_TASK, H_CONTEXT, P_CROSS, P_MUTATE
from fjsp_usage.usage_v2 import VERSION as INTERFACE
from fjsp_usage.usage_v2.candidates import validate_usage_code
from fjsp_usage.usage_v2.prompts import NEW_OUTPUT
from tools import usage_mechanism_ablation as common
from tools.report_usage_ablation import costs, outcome, table

ROOT = common.ROOT
VERSION = 'H01-alpha-search-seed501-v1-20261019'
DEFAULT = ROOT / 'runs/h01-state-weight-search-seed501-20261019-v1'
PEER = ROOT.parent / 'FJSP-Heuristic-Research-u-single-experiments'
PEER_RUN = PEER / 'runs/single-ID-update-frequency-seed201-v1-20261018'
GRID = ROOT / 'reports/usage-fixed-pair-weight-grid-20261018-v1'
PHASE = 'r501/B'
INITIAL = (0, 25, 50, 75, 100)
TASK = U_TASK[:U_TASK.index('Every path returns a built-in Python int')].replace(
    'heuristic selector U', 'H0/H1 weight policy U').replace(
    'uses ONLY the selected h to score ALL legal pairs.', 'uses the active H0/H1 members to score ALL legal pairs.').replace(
    'otherwise the previous member id;', 'otherwise the previous largest normalized-weight member id (ties to smaller id);')
# Keep the complete original bound specification rather than truncating it with
# the old integer-return instructions above.
from fjsp_usage.research_real.state_diagnostics import BOUND_TEXT
TASK += BOUND_TEXT + '''
K=10 preserves the original frozen numbering; ONLY H0 and H1 may be active.
Every return is exactly (1, (alpha, 1.0-alpha, 0, 0, 0, 0, 0, 0, 0, 0)).
Use a scalar local alpha, or repeat the same scalar expression and its complement.
Two literal numeric complementary constants are also legal. Other eight entries must be literal zero.
alpha must be a built-in finite number in [0,1], never bool. No host clipping or repair.
Endpoints are legal: alpha=0 uses only H1; alpha=1 uses only H0, in raw action-score units.
With both positive, each h scores ALL current legal actions. The host min-max normalizes each full
column (constant column -> zero), combines with normalized weights, and takes the largest action score.
Final action ties use job then machine. Host normalization uses positive maximum then sum.
previous_heuristic records the actual dominant member at the last step, initially -1; it is not weight history.
Weights, raw h action scores and combined action scores are different quantities. U sees no action scores.
Constants, conditions and linear/nonlinear formulas in the existing closed language are legal.
No phase partition, switching, dynamic dependence, complexity or improvement is required.
Member ids are categories and are not quality ranks. Do not generate SELECT or any other member pair.
Complete training fitness is used by external selection only. Do not invent state-level correct members,
rewards, per-instance feedback or performance claims. You receive no such feedback.
'''


def validate(code, description=''):
    """Same closed AST, plus a syntactically certified complementary pair."""
    candidate = validate_usage_code(code, description=description, member_count=10)
    for node in ast.walk(ast.parse(candidate.code)):
        if not isinstance(node, ast.Return):
            continue
        mode, vector = node.value.elts
        if not isinstance(mode, ast.Constant) or type(mode.value) is not int or mode.value != 1:
            raise CandidateError('H01 protocol requires literal MIX mode 1')
        a, b, *zeros = vector.elts
        if any(not isinstance(z, ast.Constant) or type(z.value) not in (int, float) or z.value != 0 for z in zeros):
            raise CandidateError('H2..H9 must be literal zero')
        literals = all(isinstance(x, ast.Constant) and type(x.value) in (int, float) for x in (a, b))
        if literals:
            if not (0 <= a.value <= 1 and b.value == 1-a.value):
                raise CandidateError('literal weights must be alpha and 1-alpha')
        elif not (isinstance(b, ast.BinOp) and isinstance(b.op, ast.Sub)
                  and isinstance(b.left, ast.Constant) and type(b.left.value) in (int, float)
                  and b.left.value == 1 and ast.dump(b.right) == ast.dump(a)):
            raise CandidateError('second weight must be syntactic 1-alpha')
    return candidate


def checked_function(function):
    def call(*args):
        result = function(*args)
        if type(result) is not tuple or len(result) != 2:
            raise ValueError('H01 output shape')
        mode, vector = result
        if type(mode) is not int or mode != 1 or type(vector) is not tuple or len(vector) != 10:
            raise ValueError('H01 MIX/vector constraint')
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
            raise ValueError('H01 finite scalar constraint')
        if not (0 <= vector[0] <= 1 and vector[1] == 1-vector[0] and all(v == 0 for v in vector[2:])):
            raise ValueError('H01 alpha/complement constraint')
        return result
    return call


def constant(percent):
    a = percent/100
    # Match the three actual cached candidate ASTs, including float zero fields.
    vector = [a, 1-a] + [0.]*8
    code = 'def use_heuristics('+', '.join(U_ARGS)+'):\n    return (1, ('+', '.join(map(repr, vector))+'))\n'
    return validate(code, f'Frozen manual H0/H1 alpha={a:g}; not LLM-generated')


def build_prompt(arm, operator, parents, members, *, kind='U'):
    if arm != 'B' or kind != 'U' or operator not in ('CROSS', 'MUTATE'):
        raise ValueError('H01 supports evolution only')
    if len(parents) != (5 if operator == 'CROSS' else 1) or len(members) != 10:
        raise ValueError('five distinct crossover parents or one mutation parent required')
    if len({p['id'] for p in parents}) != len(parents):
        raise ValueError('distinct parents required')
    context = H_CONTEXT.replace('The host calls the chosen h for each legal action.',
                                'The host calls only the positive-weight H0/H1 members for each legal action.')
    for i in (0, 1):
        context += f'\nH MEMBER {i}\nReviewed behavior: {members[i].description}\nCode:\n{members[i].code}\n'
    operation = (P_CROSS if operator == 'CROSS' else P_MUTATE).replace(
        'H members', 'H0/H1 weights').replace('selection relationship', 'weight relationship').replace(
        'member mappings and parameters', 'alpha formulas and parameters').replace(
        'hold/switch conditions or thresholds', 'alpha conditions, formulas or thresholds').replace(
        'state-to-member mappings', 'state-to-alpha mappings').replace('selection logic', 'weight logic')
    parent_text = ''.join(f'\nPARENT {i}\nDescription: {p["candidate"]["description"]}\nCode:\n{p["candidate"]["code"]}\n'
                          for i, p in enumerate(parents))
    return '\n'.join((TASK, context, parent_text, operation, NEW_OUTPUT,
                      'def use_heuristics('+', '.join(U_ARGS)+'):'))


@dataclass(frozen=True)
class Config(ExperimentConfig):
    experiment_version: str = VERSION

    def default_phase_caps(self):
        return {PHASE: 20}

    def search_arms(self):
        return ('B',)

    def __post_init__(self):
        if (self.experiment_version != VERSION or self.mode != 'real' or self.purpose != 'research'
                or (self.H_size, self.population_size, self.cross_parents, self.mutation_parents,
                    self.generations, self.attempts_per_generation, self.initialization_cap,
                    self.seeds, self.instance_timeout, self.total_request_cap) != (10,5,5,1,2,10,5,(501,),15,20)
                or self.training_diagnostics or self.conditional_research is not None
                or any((self.development_h_source, self.development_acceptance, self.development_continuation_source))
                or self.platform_quota_ceiling != 30000000 or self.platform_quota_reservation != 1000000
                or self.total_token_cap is not None or self.cost_cap_estimate is not None):
            raise ValueError('exact H01 bounded protocol required')
        super().__post_init__()
        source = common.read(common.RUN/'config.gpt61.authorized.json')['provider']
        if asdict(self.provider) != source:
            raise ValueError('shared registered gpt-6.1-sol generation parameters changed')


class WeightSearch(BudgetedSearch):
    _build_prompt = staticmethod(build_prompt)

    def _parse_candidate(self, text, *, kind='U'):
        c = parse_response(text, kind=kind, interface_version=INTERFACE, member_count=10)
        return validate(c.code, c.description)

    def initialize(self, **kwargs):
        if self.state['phase'] == 'initialization' or len(self.state['population']) != 5:
            raise BudgetStop('manual five-source P0 required; no model initialization')
        return True

    def _prepare(self, *, initial):
        if initial:
            raise BudgetStop('no initialization allowed')
        super()._prepare(initial=False)
        # Actual per-request prompt is durable before dispatch, separately readable.
        pending = self.state['inflight']
        path = self.directory/'prompts'/pending['id'].replace('/', '_')
        path.parent.mkdir(exist_ok=True)
        if path.exists() and path.read_text() != pending['prompt']:
            raise ValueError('frozen prompt changed')
        path.write_text(pending['prompt'])

    def _attempt(self):
        super()._attempt()
        # Inference/API candidate failures may continue. Financial, settlement
        # or access gates stop the loop before another slot is reserved.
        transport = self.evolution_requests.transport
        if hasattr(transport, 'check_after'):
            transport.check_after()


def weight_worker(pipe, *args):
    import fjsp_usage.research_real.runtime as runtime
    native_compile = runtime.compile_candidate
    def compile_checked(candidate, **kwargs):
        function = native_compile(candidate, **kwargs)
        return checked_function(function) if candidate.kind == 'U' else function
    with patch.object(runtime, 'compile_candidate', compile_checked):
        common.schedule_recording_worker(pipe, *args)


def evaluate_weight(candidate, members, instances, names):
    import fjsp_usage.research_real.runtime as runtime
    validate(candidate.code, candidate.description)
    with patch.object(runtime, '_worker', weight_worker):
        result = evaluate(candidate, members, instances, names, timeout=15, diagnostics=False, allowed_modes=(1,))
    # Read alpha from the PRIMARY solve, not a third replay. Keep per-step data.
    for row in result['instances']:
        row['observed_alpha'] = [d[1][0] for d in row['usage_decisions']]
    return common.compact(result)


def pins_check(directory):
    plan = common.read(directory/'Plan.json')
    for name, sha in plan['pins'].items():
        if common.sha(ROOT/name) != sha:
            raise ValueError('frozen input/source changed: '+name)
    pending = Config.from_dict(common.read(directory/'config.pending.json'))
    if (directory/'protocol.json').exists():
        protocol = common.read(directory/'protocol.json')
        expected = pending.payload();expected['real_requests_authorized'] = True
        if (protocol['config'] != json.loads(json.dumps(expected))
                or common.read(directory/'config.authorized.json') != protocol['config']
                or protocol['plan_sha256'] != common.sha(directory/'Plan.json')
                or protocol['history_sha256'] != common.sha(directory/'History_binding.json')):
            raise ValueError('registered configuration/protocol/frozen inputs changed')
    return plan


def evaluation_runtime():
    return {'python':platform.python_version(),
        'dependencies':{name:importlib.metadata.version(name) for name in ('numpy','pytz','tqdm')}}


def check_evaluation_runtime(plan):
    if evaluation_runtime() != plan['evaluation_runtime']:
        raise ValueError('use original .venv evaluation Python/dependencies; artifact Python is report-only')


def prepare(directory):
    protocol, dataset, frozen, reassessment, members, names = common.inputs()
    runtime = evaluation_runtime()
    if runtime != {k:protocol['implementation'][k] for k in ('python','dependencies')}:
        raise ValueError('reference reuse requires original .venv Python/dependencies')
    dataset.verify('train')
    old_plan = common.read(GRID/'Plan.json')
    common.verify_pins(old_plan)
    if old_plan['names'] != names or old_plan['H_order'] != [m.key for m in members]:
        raise ValueError('fixed grid H/data identity differs')
    # Reviewed behavior, without changing actual H code/key/order.
    from fjsp_usage.research.candidates import Candidate
    members = tuple(Candidate(r['review']['description'], m.code, m.key, 'h')
                    for r, m in zip(frozen['members'], members))
    versions, reused, paths = [], {}, []
    for percent in range(0, 101, 5):
        c = constant(percent); key = f'alpha_{percent:03d}'
        row = {'id':key, 'alpha':percent/100, 'candidate':asdict(c),
               'origin':'predeclared manual reference grid; never a new LLM candidate', 'reused':False}
        if percent in (25,50,75):
            source_id = f'H0_H1_w{percent:02d}_{100-percent:02d}'
            source = next(v for v in old_plan['versions'] if v['id']==source_id)
            if c.key != source['candidate']['key']:
                raise ValueError('cached constant AST differs')
            path = GRID/'results'/f'{source_id}.json'; result = common.read(path)
            row['reuse'] = {'kind':'exact candidate/H/data/executor identity',
                'source_id':source_id, 'path':str(path.relative_to(ROOT)), 'sha256':common.sha(path)}
            paths.append(path)
        elif percent in (0,100):
            i = 1 if percent == 0 else 0
            result = reassessment['rows'][i]['result']
            # This is semantic reuse, explicitly NOT the same candidate key or
            # observed U overhead/call instrumentation. No invented cache identity.
            row['reuse'] = {'kind':'certified single-support MIX/raw-h scheduling equivalence',
                'source_h':i, 'source_h_code_key':members[i].key,
                'source':str((common.RUN/'Conditional_H_reassessment.json').relative_to(ROOT)),
                'cost_notice':'native fixed-h timing only; U overhead and certified U h-call counts unknown',
                'proof':'execution.combine_scores one-support bypasses min-max; priority raw, same legal actions/ties/append; constant U ignores previous_heuristic'}
        else:
            versions.append(row); continue
        check_result(result, names)
        if not result['valid']:
            raise ValueError('incomplete reference cannot be initial fitness')
        row['reused'] = True
        versions.append(row); reused[key] = result
    cfg = common.read(common.RUN/'config.gpt61.authorized.json')
    allowed = set(Config.__dataclass_fields__)
    cfg = {k:v for k,v in cfg.items() if k in allowed}
    cfg.update(experiment_version=VERSION, real_requests_authorized=False, conditional_research=None,
        development_h_source=None, development_continuation_source=None, development_acceptance=None,
        population_size=5, cross_parents=5, mutation_parents=1, attempts_per_generation=10,
        generations=2, initialization_cap=5, seeds=[501], total_request_cap=20,
        phase_request_caps={PHASE:20}, training_diagnostics=False, instance_timeout=15,
        total_token_cap=None, cost_cap_estimate=None, platform_quota_reservation=1000000)
    config = Config.from_dict(cfg)
    directory.mkdir(parents=True, exist_ok=False)
    for name in ('sources','results','prompt_templates'):
        (directory/name).mkdir()
    atomic_json(directory/'config.pending.json', config.payload())
    initial = []
    for row in versions:
        path = directory/'sources'/f'{row["id"]}.py'; path.write_text(row['candidate']['code']); paths.append(path)
        if row['reused']:
            atomic_json(directory/'results'/f'{row["id"]}.json', reused[row['id']])
        if int(round(100*row['alpha'])) in INITIAL:
            result = reused[row['id']]
            initial.append({'id':'MANUAL/init/'+row['id'], 'candidate':row['candidate'],
                'fitness':result['fitness'], 'scores':[r['score'] for r in result['instances']],
                'receipt':{'origin':'manual reference P0, zero initialization requests', 'reuse':row['reuse']},
                'training_result':result})
    atomic_json(directory/'Initial_population.json', initial)
    atomic_json(directory/'H_context.json', [asdict(m) for m in members])
    for operator, parents in (('CROSS',initial),('MUTATE',[initial[2]])):
        path = directory/'prompt_templates'/f'{operator}.txt'
        path.write_text(build_prompt('B',operator,parents,members)); paths.append(path)
    paths += [ROOT/'tools/h01_weight_search.py', ROOT/'tools/h01_weight_report.py',
        ROOT/'tests/test_h01_weight_search.py', common.RUN/'protocol.json', common.RUN/'H_frozen.json',
        common.RUN/'Conditional_H_reassessment.json', GRID/'Plan.json', GRID/'Config.json',
        directory/'config.pending.json', directory/'Initial_population.json', directory/'H_context.json',
        ROOT/'data/fjsp_manifest.json']
    paths += [ROOT/n for n in protocol['implementation']['files']] + list(dataset.paths['train'])
    plan = {'version':VERSION, 'names':names, 'dataset':dataset.metadata, 'H_order':[m.key for m in members],
        'evaluation_runtime':runtime,
        'versions':versions, 'initial_ids':[r['id'] for r in initial], 'new_full_evaluation_cap':36,
        'endpoint_fallback_cap':2, 'absolute_full_evaluation_cap':38, 'new_model_request_cap':20,
        'new_grid_evaluations':16, 'reused_reference_evaluations':5, 'instance_timeout':15,
        'score':protocol['fitness'], 'physical_schedule':old_plan.get('physical_schedule_schema',
            'sorted [job,operation,machine,start,end], excludes usage/history labels'),
        'independent_diagnostic_replays':0, 'holdout_access':False,
        'peer_run':str(PEER_RUN), 'start_condition':'peer final released, fully settled and global budget valid',
        'pins':{str(p.relative_to(ROOT)):common.sha(p) for p in paths}}
    atomic_json(directory/'Plan.json', plan)
    atomic_json(directory/'User_authorization.json', {'approved':True,'person':'DDXQL',
        'source':'current user instruction 2026-10-19', 'max_new_requests':20,
        'scope':'fixed H0/H1 train21 seed501 N5 two generations; grid16 plus max20 new candidates',
        'authorization_excerpt':'本条明确授权必要局部修改、离线检查、以下限定的本地评价及最多20次新增模型请求。',
        'start_condition':'第一页完成、释放调用权并交付最终账本；全局预算及历史预留有效',
        'pending_config_sha256':digest(config.payload())})
    print('Offline preparation complete: 21 references, 5 manual P0, 16 new grid evaluations pending, max20 inference requests; no solves/network.')


def peer_history(directory):
    """Final native requests AND invoice proofs, inherited history counted once."""
    from fjsp_usage.usage_v2.registration import audit_final_handoff, inventory, worktree_roots
    if (PEER_RUN/'.writer.lock').exists():
        raise BudgetStop('WAIT_PEER_WRITER_LOCK: update-frequency batch still active')
    for name in ('Final_budget_handoff.json','Update_status.json','History_binding.json'):
        if not (PEER_RUN/name).exists():
            raise BudgetStop('WAIT_PEER_FINAL_HANDOFF: '+name)
    old = common.read(PEER_RUN/'History_binding.json')
    check_seal(old,kind='Fair_history_binding',mode='real')
    for name, sha in old['files_sha256'].items():
        if common.sha(Path(name)) != sha:
            raise BudgetStop('inherited evidence changed: '+name)
    ledger = common.read(PEER_RUN/'budget.json'); quota = common.read(PEER_RUN/'platform_quota.json')
    p = common.read(PEER_RUN/'protocol.json'); h = common.read(PEER_RUN/'Final_budget_handoff.json')
    if ledger['identity'] != digest({'config':p['config'],'context':digest(p)}) or quota['identity'] != ledger['identity']:
        raise BudgetStop('peer ledger/protocol/quota identity differs')
    if ledger['halted'] or quota['halted'] or any(r['status'] in ('pending','reserved') for r in ledger['records'].values()):
        raise BudgetStop('peer unresolved budget/account gate')
    status = check_seal(common.read(PEER_RUN/'Update_status.json'),kind='Update_status',mode='real',context=digest(p))
    if status['status'] != 'completed':
        raise BudgetStop('peer update-frequency phases not complete')
    successful_model_access = False
    for arm, generations in (('A',3),('B',1)):
        checkpoint = common.read(PEER_RUN/f'r201/{arm}/checkpoint.json')
        journal = common.read(PEER_RUN/f'r201/{arm}/budgeted_evolution_requests.json')['requests']
        if (checkpoint.get('phase') != 'completed' or checkpoint.get('generation') != generations
                or checkpoint.get('inflight') is not None or len(checkpoint['attempts']) != 30
                or len(journal) != 30 or status['arms'][arm]['phase'] != 'completed'):
            raise BudgetStop('peer raw generation/journal terminal evidence differs')
        for row in journal.values():
            key = row['global_key']; raw = ledger['records'].get(key)
            if (not raw or raw['phase'] != f'r201/{arm}' or row['usage'] != raw['usage']
                    or row['prompt_key'] != raw['prompt_key'] or row['status'] != raw['status']):
                raise BudgetStop('peer per-request journal/ledger binding differs')
            if row['status']=='completed' and row.get('response_metadata',{}).get('model')=='gpt-6.1-sol':
                successful_model_access = True
    if not successful_model_access:
        raise BudgetStop('no successful common-model response in final peer journal')
    if len(ledger['records']) != 60:
        raise BudgetStop('peer final batch must account for all60 declared generation slots')
    plan = common.read(directory/'Plan.json')
    H = check_seal(common.read(PEER_RUN/'H_frozen.json'),kind='H_frozen',mode='real',context=digest(p))
    if (p['dataset'] != plan['dataset'] or [m['candidate']['key'] for m in H['members']] != plan['H_order']
            or p['config'].get('conditional_research',{}).get('version') != 'single-ID-update-frequency-v1'):
        raise BudgetStop('peer registered version/H/data differs')
    evidence = audit_final_handoff(PEER_RUN,ledger,quota,'gpt-6.1-sol')
    for row in evidence['rows']:
        if row['state'] != 'sent_settled':
            continue
        stem = hashlib.sha256(row['key'].encode()).hexdigest()+'.json'
        bill = common.read(PEER_RUN/'billing'/stem)
        supplement = PEER_RUN/'billing_reconciliations'/stem
        invoice = common.read(supplement)['invoice'] if supplement.exists() else bill.get('invoice',{})
        if invoice.get('group') != 'codex-deafult':
            raise BudgetStop('current peer invoice group not certified')
    if p['config']['provider'] != common.read(directory/'config.pending.json')['provider']:
        raise BudgetStop('peer common generation parameters differ')
    expected = dict(old['real_budget_inventory'])
    if ledger['identity'] in expected:
        raise BudgetStop('peer ledger already counted in inherited history')
    expected[ledger['identity']] = common.sha(PEER_RUN/'budget.json')
    if inventory(worktree_roots(ROOT), exclude=directory) != expected:
        raise BudgetStop('unregistered/changed cumulative consumption or foreign caller lock')
    slots = old['historical_request_slots']+len(ledger['records'])
    sends = old['historical_confirmed_sends']+evidence['confirmed_sends']
    if (slots != h['summary']['lifetime_request_slots'] or sends != h['summary']['lifetime_confirmed_sends']
            or slots+20 > 300 or old['retained_account_hold'] != 24000000):
        raise BudgetStop('cumulative boundary or inherited hold differs')
    latest = max(quota['observed_used'],h['latest_verified_used_points'])
    account = quota.get('latest_quota',{})
    if (account.get('total_used') != latest or account.get('unlimited_quota') is not False
            or type(account.get('total_available')) is not int
            or latest+24000000+1000000 > 30000000 or account['total_available'] < 25000000):
        raise BudgetStop('final saved account cannot cover old holds plus next-request risk; live check still required before sending')
    files = dict(old['files_sha256'])
    # A bounded scan of THIS final batch is necessary to bind per-request proof.
    for path in PEER_RUN.rglob('*.json'):
        files[str(path)] = common.sha(path)
    return {'historical_request_slots':slots,'historical_confirmed_sends':sends,
        'historical_token_charges':old['historical_token_charges']+
            [r['usage'] if r.get('usage') is not None else r['reservation'] for r in ledger['records'].values()],
        'retained_account_hold':24000000,'latest_saved_account_used':latest,
        'real_budget_inventory':expected,'files_sha256':files,'peer_receipt_audit':evidence,
        'metadata_floor':common.read(PEER_RUN/'Metadata_global_pacing.json')['last_finished_at'],
        'invoice_floor':common.read(PEER_RUN/'Invoice_query_pacing.json')['last_finished_at'],
        'metadata_interval':max(30,old['metadata_interval'],common.read(PEER_RUN/'Metadata_global_pacing.json')['interval']),
        'invoice_interval':max(150,old['invoice_interval'],common.read(PEER_RUN/'Invoice_query_pacing.json')['interval']),
        'lifetime_request_cap':300}


def check_history(directory):
    from fjsp_usage.usage_v2.registration import inventory, worktree_roots
    saved = common.read(directory/'History_binding.json')
    protocol = common.read(directory/'protocol.json')
    if common.sha(directory/'History_binding.json') != protocol['history_sha256']:
        raise BudgetStop('registered history binding changed')
    # Registration already audited every native receipt. Revalidate its pinned
    # evidence and inventory, instead of reparsing all60 histories for each GET.
    for name, sha in saved['files_sha256'].items():
        if common.sha(Path(name)) != sha:
            raise BudgetStop('registered historical evidence changed: '+name)
    if inventory(worktree_roots(ROOT),exclude=directory) != saved['real_budget_inventory']:
        raise BudgetStop('foreign caller/changed cumulative consumption')
    if saved['historical_request_slots']+20 > 300 or saved['retained_account_hold'] != 24000000:
        raise BudgetStop('registered cumulative/unknown-fee boundary changed')
    return saved


def register(directory):
    plan = pins_check(directory)
    if (directory/'protocol.json').exists():
        check_history(directory); return
    history = peer_history(directory)
    auth = common.read(directory/'User_authorization.json')
    config = Config.from_dict(common.read(directory/'config.pending.json'))
    if not auth['approved'] or auth['pending_config_sha256'] != digest(config.payload()) or auth['max_new_requests'] != 20:
        raise ValueError('current exact batch authorization binding changed')
    payload = config.payload(); payload['real_requests_authorized'] = True
    atomic_json(directory/'config.authorized.json', Config.from_dict(payload).payload())
    atomic_json(directory/'History_binding.json', history)
    atomic_json(directory/'protocol.json', {'version':VERSION,'config':payload,'plan_sha256':common.sha(directory/'Plan.json'),
        'history_sha256':common.sha(directory/'History_binding.json'),'dataset':plan['dataset'],
        'H_order':plan['H_order'],'search_engine':'unchanged BudgetedSearch/Search',
        'alpha_check':'local per-call constraint guard inside primary solve/recheck, no replay',
        'cost_notice':'guard overhead included in new times; cached times retain their original instrumentation'})
    with tarfile.open(directory/'registration-snapshot.tar.gz','w:gz') as archive:
        for name in plan['pins']:
            archive.add(ROOT/name, arcname=name)
        for name in ('Plan.json','User_authorization.json','protocol.json','config.authorized.json','History_binding.json'):
            archive.add(directory/name,arcname='registration/'+name)
    print('Registered new batch; retained history and 20 NEW request cap. No account queries or inference.')


class Ledger(BudgetLedger):
    def reserve(self, key, phase, prompt_key):
        history = check_history(self.path.parent)
        if phase != PHASE or history['historical_request_slots']+len(self.data['records']) >= 300:
            raise BudgetStop('undeclared phase/cumulative300 cap')
        return super().reserve(key,phase,prompt_key)


def grid_evaluate(directory):
    plan = pins_check(directory); check_history(directory)
    check_evaluation_runtime(plan)
    _, dataset, _, _, members, names = common.inputs()
    instances = dataset.load('train')
    for version in plan['versions']:
        if version['reused']:
            continue
        path = directory/'results'/f'{version["id"]}.json'
        started = directory/'results'/f'{version["id"]}.started.json'
        if path.exists():
            check_result(common.read(path),names); continue
        if started.exists():
            # A crash never silently grants a second complete evaluation.
            result = {'valid':False,'fitness':None,'instances':[],'total_instances':len(names),
                'error_type':'InterruptedEvaluation','error':'reserved once; no automatic rerun', 'completed_prefix_unknown':True}
        else:
            check_history(directory)
            common.write(started, {'code_key':version['candidate']['key'],'resource':common.resource_snapshot()})
            c = validate(version['candidate']['code'],version['candidate']['description'])
            result = evaluate_weight(c,members,instances,names)
        check_result(result,names); common.write(path,result,indent=None)
        print(version['id'],result['valid'],result['fitness'],flush=True)
    atomic_json(directory/'Grid_complete.json',{'references':21,'new_evaluations':16,'reused':5,'no_refinement':True})


def client(directory, config, context):
    from fjsp_usage.research_real.real_transport import JsonCandidateTransport
    from fjsp_usage.research_real.leafapi import query_status
    from fjsp_usage.research_real.quota_guard import QuotaGuardedTransport
    from fjsp_usage.usage_v2.access import WireRecorder, MetadataPacer, InvoicePacer
    from fjsp_usage.usage_v2.billing import InvoiceTransport
    from fjsp_usage.usage_v2.model_migration import check_live_tariff, risk_reservation
    history = check_history(directory)
    class WeightQuota(QuotaGuardedTransport):
        # Explicit NEW research protocol authorization of external historical
        # holds, without changing the old continuation-only guard or old config.
        def check_retained(self):
            return super().check_retained()+history['retained_account_hold']
        def reservation_for(self,prompt):
            return risk_reservation(prompt)['points']
        def dispatch(self,key,prompt,*,kind='U',on_sent=lambda:None):
            def sent():
                self.data['records'][key]['risk_basis'] = risk_reservation(prompt)
                self.save();on_sent()
            return super().dispatch(key,prompt,kind=kind,on_sent=sent)
    wire = WireRecorder(JsonCandidateTransport(config),directory/'wire_responses')
    pacer = MetadataPacer(directory/'Metadata_global_pacing.json',interval=history['metadata_interval'])
    pacer.last = max(pacer.last,history['metadata_floor'])
    quota = WeightQuota(wire,directory/'platform_quota.json',context,
        query=lambda:pacer.call('/api/usage/token/',lambda:query_status(wire.secret,quota_path='/api/usage/token/',include_models=False)),
        settlement_min_used=history['latest_saved_account_used'])
    invoice = InvoicePacer(lambda:query_group_invoices(wire.secret),directory/'Invoice_query_pacing.json',pacer,interval=history['invoice_interval'])
    invoice.last = max(invoice.last,history['invoice_floor'])
    inner = InvoiceTransport(quota,directory/'billing',query=invoice)
    class Serial:
        identity, redact = inner.identity, inner.redact
        def __init__(self):
            self.tariff_at = None
        def check_after(self):
            check_history(directory)
            if quota.data['halted']:
                raise BudgetStop(quota.data.get('stop_reason','quota halted'))
        def preflight(self,prompt):
            config.check_dispatch(); self.check_after()
            if self.tariff_at is None or time.time()-self.tariff_at >= config.platform_quota_query_interval:
                try: quota.data['latest_tariff_check'] = check_live_tariff(wire.secret,pacer)
                except Exception as exc:
                    quota.halt('new-model tariff/access unavailable; no dispatch')
                    raise BudgetStop(quota.data['stop_reason']) from exc
                quota.save(); self.tariff_at = time.time()
            inner.preflight(prompt)
        def dispatch(self,key,prompt,**kwargs):
            self.check_after()
            if not key.startswith(PHASE+'/B/g'):
                raise BudgetStop('undeclared phase or initialization dispatch')
            return inner.dispatch(key,prompt,**kwargs)
    return Serial()


def query_group_invoices(secret):
    """Same single GET/allowlist as billing.query_invoices, retaining group.

    The old parser intentionally remains byte-identical for old protocol pins.
    No account query is made during preparation or offline checks.
    """
    import http.client
    result = {'version':VERSION,'inference_requests':0,'metadata_requests':1,
        'observed_at':time.time(),'path':'/api/log/token','success':False,'records':[]}
    connection = http.client.HTTPSConnection('leafapi.cc',timeout=15)
    try:
        connection.request('GET','/api/log/token',headers={'Authorization':'Bearer '+secret,'Accept':'application/json'})
        response = connection.getresponse();result['http_status'] = response.status
        raw = response.read(524289)
        if response.status != 200 or len(raw)>524288:return result
        body = json.loads(raw);data = body.get('data',[])
        if isinstance(data,dict):data=data.get('items',data.get('data',data.get('logs',[])))
        if not isinstance(data,list) or body.get('success',body.get('code')) is not True:return result
        fields = ('id','created_at','type','model_name','quota','prompt_tokens','completion_tokens','use_time','request_id','group')
        for row in data:
            if not isinstance(row,dict):raise ValueError('invalid invoice row')
            result['records'].append({k:row[k].replace(secret,'[REDACTED]') if isinstance(row[k],str) else row[k]
                for k in fields if k in row and type(row[k]) in (str,int,float,bool)})
        result['success'] = True
    except Exception as exc:result['error_type'] = type(exc).__name__
    finally:connection.close()
    return result


def search(directory, env_file):
    plan = pins_check(directory); check_evaluation_runtime(plan); history = check_history(directory)
    if not (directory/'Grid_complete.json').exists():
        raise BudgetStop('predeclared reference grid not complete')
    from fjsp_usage.research_real.leafapi import load_local_key, KEY_ENV
    # Secret is read only here, after all offline handoff gates.
    os.environ[KEY_ENV] = load_local_key(env_file)
    config = Config.from_dict(common.read(directory/'config.authorized.json'))
    protocol = common.read(directory/'protocol.json'); context = digest(protocol)
    ledger = Ledger(directory/'budget.json',config,context)
    transport = client(directory,config,context)
    _, dataset, _, _, members, names = common.inputs(); instances = dataset.load('train')
    from fjsp_usage.research.candidates import Candidate
    contexts = common.read(directory/'H_context.json')
    members = tuple(Candidate(**row) for row in contexts)
    searcher = WeightSearch(directory/'r501/B',arm='B',config=config.u_search(501),members=members,
        evaluator=lambda c:evaluate_weight(c,members,instances,names),transport=transport,
        context=context,initial=common.read(directory/'Initial_population.json'),
        init_phase='r501/init',search_phase=PHASE,ledger=ledger,experiment=config,training_names=names)
    stop = None
    try:
        result = searcher.run()
        atomic_json(directory/'Search_status.json',result)
    except Exception as exc:
        stop = transport.redact(str(exc))[:500]
        atomic_json(directory/'Search_status.json',{**searcher.report(),'stop_reason':stop})
    finally:
        summary = ledger.summary()
        summary.update(historical_request_slots=history['historical_request_slots'],
            lifetime_request_slots=history['historical_request_slots']+len(ledger.data['records']),
            retained_historical_account_hold=history['retained_account_hold'])
        atomic_json(directory/'Budget_summary.json',summary)
        q = common.read(directory/'platform_quota.json')
        known_points = 0; unknown = []
        for key, record in ledger.data['records'].items():
            file = directory/'billing'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
            bill = common.read(file) if file.exists() else {}
            if bill.get('status') == 'invoice_account_matched':known_points += bill['actual_platform_units']
            else:unknown.append(key)
        atomic_json(directory/'Final_budget_handoff.json',{'version':VERSION,'real_caller_active':False,
            'budget_identity':ledger.identity,'budget_sha256':common.sha(directory/'budget.json'),
            'summary':summary,'registered_generation_phases_complete':searcher.state['phase']=='completed',
            'quota_halted':q['halted'],'latest_verified_used_points':q.get('observed_used',history['latest_saved_account_used']),
            'old_account_hold':history['retained_account_hold'],'known_new_points':known_points,
            'unknown_new_fee_keys':unknown,'unknown_new_fee_holds':sum(q['records'].get(k,{}).get('reserved',1000000) for k in unknown),
            'unknown_wire_keys':[k for k,r in ledger.data['records'].items() if r.get('usage') is None],
            'stop_reason':stop,'no_refill':True})
    if stop:
        print('停止新增请求：'+stop,flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('prepare','check','register','grid','search','report'))
    parser.add_argument('--run-dir',type=Path,default=DEFAULT)
    parser.add_argument('--env-file',type=Path)
    args = parser.parse_args(); directory = args.run_dir.resolve()
    if directory.parent != ROOT/'runs':
        parser.error('new directory in this worktree runs/ required')
    if args.stage == 'prepare':
        prepare(directory); return
    if args.stage == 'check':
        plan = pins_check(directory)
        status = 'ready_for_registration'
        try: peer_history(directory)
        except (BudgetStop,FileNotFoundError) as exc: status = str(exc)
        print(json.dumps({'offline_pins_valid':True,'new_model_cap':20,'new_evaluation_cap':36,
            'peer_gate':status,'network_queries':0,'training_solves':0},ensure_ascii=False,indent=2));return
    if args.stage == 'report':
        from tools.h01_weight_report import report
        report(directory);return
    with RunLock(directory):
        if args.stage == 'register': register(directory)
        elif args.stage == 'grid': grid_evaluate(directory)
        elif args.stage == 'search':
            if not args.env_file: parser.error('--env-file required; do not print credential contents')
            search(directory,args.env_file)


if __name__ == '__main__':
    main()
