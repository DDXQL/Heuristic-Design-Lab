"""V1-0 metadata-only preparation. Parses instances, never schedules them."""
from collections import Counter, defaultdict
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path
import shutil
from statistics import fmean, pstdev

from fjsp_usage.offline_v2 import lower_bound_v5
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from llm4ad.task.optimization.fjsp_set.instances import load_instance
from tools import h01_weight_local as original

ROOT = original.ROOT
VERSION = 'V1-H01-frozen-pair-test28-v1-20261021'
DEFAULT = ROOT/'runs/v1-h01-frozen-pair-test28-v1-20261021'
B2 = original.BATCH_DEFAULT
REPORT = ROOT/'reports'/B2.name
SOURCE = ROOT.parent/'FJSP-Heuristic-Research/data/fjsp'
PROGRAMS = {
    'dynamic': ('B/g0001/000000', 'B_g0001_000000.py', '1b14f82301314f25ecb8ff1d55b07439f6aeaf331102098cea7920d0c2e9bd52'),
    'equal': ('MANUAL/init/alpha_050', 'alpha_050.py', 'f008e876861877b7b6253ecfdc306af2313748254d938a95c8867e5c2dd83cd6')}
STATISTICS = {'primary': 'mean((Cmax_equal-Cmax_dynamic)/LB)', 'resamples': 20000,
    'seed': 1701, 'confidence': .95, 'method': 'paired-mean-BCa-midrank-linear-quantiles-v1',
    'sign_test': 'two-sided exact binomial p=.5, exclude ties',
    'failure': 'CI=null with reason on degeneracy/nonfinite/error; no alternative method or complete-case primary',
    'interpretation': 'instance-pair resampling sensitivity; assumes independent instance units; fixed benchmark is not random population sampling'}


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def csv_table(path, rows):
    with Path(path).open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def structure(path, split):
    instance = load_instance(path)  # No U/h compilation or scheduling.
    jobs = tuple(tuple(op.alternatives for op in job) for job in instance.jobs)
    alternatives = [op.alternatives for job in instance.jobs for op in job]
    loads = [0.]*instance.machine_count
    for choices in alternatives:
        for machine, duration in choices: loads[machine] += duration/len(choices)
    return {'file': path.name, 'split': split, 'jobs': len(jobs), 'machines': instance.machine_count,
        'operations': instance.operation_count, 'alternatives_mean': fmean(map(len, alternatives)),
        'flexibility': fmean(map(len, alternatives))/instance.machine_count,
        'nominal_max_load_share': max(loads)/sum(loads),
        'nominal_load_CV': pstdev(loads)/fmean(loads), 'LB': lower_bound_v5(instance),
        'byte_sha256': sha(path), 'ordered_operations_sha256': digest((instance.machine_count, jobs)),
        'job_relabel_invariant_sha256': digest((instance.machine_count, sorted(jobs)))}


def structure_audit(rows):
    duplicates = []
    for key in ('byte_sha256','ordered_operations_sha256','job_relabel_invariant_sha256'):
        groups = defaultdict(list)
        for row in rows: groups[row[key]].append(row)
        for group in groups.values():
            if len(group)>1:
                duplicates.append({'criterion': key, 'files': [r['file'] for r in group],
                    'cross_split': len({r['split'] for r in group})>1})
    summaries = {}
    for split in ('train','test'):
        group = [r for r in rows if r['split']==split]
        summaries[split] = {'n': len(group), 'machine_counts': dict(Counter(r['machines'] for r in group)),
            **{k: {'min': min(r[k] for r in group), 'max': max(r[k] for r in group),
                    'mean': fmean(r[k] for r in group)} for k in ('jobs','operations','flexibility','nominal_max_load_share','nominal_load_CV')}}
    return {'summaries': summaries, 'duplicates': duplicates,
        'blocks_execution': bool(duplicates),
        'nominal_load_definition': 'L_m=sum(p_om/number_of_alternatives_o); max share=max(L)/sum(L), CV=population_std(L)/mean(L); NOT actual scheduled load',
        'duplicate_scope': 'byte, ordered operation records, job-multiset ignoring job labels; machine relabel isomorphism/near duplicates not certified',
        'no_score_based_selection': True, 'all_original_test28_retained': True}


def history_audit():
    """Bounded stage/protocol metadata and named evidence, no raw result search."""
    evidence = []
    def note(path, facts):
        evidence.append({'path': str(path), 'sha256': sha(path), 'facts': facts})
    old = ROOT/'runs/conditional-paired-research-20261011-v4/Dataset_usage_audit.json'
    data = read(old); note(old, data)
    named = [REPORT/'Execution_audit.json',
        ROOT/'runs/leaf-framework-30pct-20261010-v3/H_development_summary_20261010.json',
        ROOT/'reports/h10-decision-diversity-v1-20261020/Plan.json',
        ROOT/'reports/task4a-state-information-v1-20261020/Plan.json',
        ROOT/'reports/u-state-behavior-v1-20261020/Evidence_index.json']
    for path in named:
        d = read(path)
        facts = {k:d[k] for k in ('no_validation_test_instance_load','training_only','train_only',
            'H_each_train_instances','validation_or_test_stages_run','training_instance_files') if k in d}
        note(path, facts or {'evidence_index_only': True, 'no_inference_from_absent_flags': True})
    markers = []
    real_tests = []
    roots = [ROOT, ROOT.parent/'FJSP-Heuristic-Research', ROOT.parent/'FJSP-Heuristic-Research-u-single-experiments']
    for root in roots:
        for filename in ('Test_complete.json','Selection_complete.json','Experiment_frozen.json','Development_test_complete.json'):
            for path in sorted((root/'runs').glob('*/'+filename)):
                d = read(path)
                row = {'path':str(path),'sha256':sha(path),'mode':d.get('mode'),'kind':d.get('kind')}
                if d.get('mode')!='synthetic' and filename=='Test_complete.json': real_tests.append(row)
                if d.get('mode')=='real' and filename=='Development_test_complete.json':
                    # This known development test is explicitly on Behnke4/13/14, not official test28.
                    row['classification'] = 'development test; inspect registered protocol, not evidence of official test28 use'
                markers.append(row)
        for path in sorted((root/'baselines/tier1_single_rule_v1/records').glob('*/evaluation_result.json')):
            d=read(path);note(path,{'test_evaluated':d.get('test_evaluated'), 'classification':'historical train/validation selection; missing flag remains unknown'})
    source_checks = []
    for entry in data['sources']:
        path = Path(entry['path'])
        source_checks.append({'path':str(path),'exists':path.is_file(),
            'matches_historical_sha256':sha(path)==entry['sha256'] if path.is_file() else None})
    return {'checked_project_roots':[{'path':str(root),'available':root.exists()} for root in roots],
        'checked_evidence': evidence,'bounded_stage_index':markers,'historical_audit_source_checks':source_checks,
        'validation11_known_development_exposure': True,'real_official_test_markers_found':real_tests,
        'blocks_execution': bool(real_tests),
        'conclusion':'No official test28 evaluation found in checked project stage records; this is not a proof of global non-use.',
        'unconfirmed':['unregistered/custom result filenames','deleted or inaccessible histories','external scripts and manual feedback','LLM pretraining exposure','whether related benchmark instances share a generator parent'],
        'future_confirmation_required':'DDXQL confirms no known unrecorded test28 performance use influencing H/U or manual choices, and accepts one-time reserved-test consumption'}


def prepare(directory):
    directory = Path(directory).resolve()
    if directory.parent != ROOT/'runs' or directory.exists():
        raise ValueError('new independent direct child of runs required; never overwrite preparations')
    plan,config,members = original.check(B2)  # Original provenance audit, no FJSP evaluation/API.
    frozen = read(B2/'H_frozen.json')
    assert [m.key for m in members]==plan['H_order']==[r['candidate']['key'] for r in frozen['members']]
    manifest = read(ROOT/'data/fjsp_manifest.json')
    assert len(manifest['split']['train'])==21 and len(manifest['split']['test'])==28
    history = history_audit()
    rows=[]; instances=[]
    for split, folder in (('train',ROOT/'data/fjsp'),('test',SOURCE)):
        for name in manifest['split'][split]:
            path=folder/name
            if sha(path)!=manifest['files'][name]['sha256']: raise ValueError('source identity mismatch: '+name)
            row=structure(path,split);rows.append(row)
            if split=='test': instances.append({'file':name,'relative_path':'inputs/test/'+name,
                'sha256':sha(path),'source_path':str(path),'source_relative_path':'data/fjsp/'+name,
                'original_partition':'test','LB':row['LB']})
    audit=structure_audit(rows)
    directory.mkdir(parents=True)
    (directory/'inputs/test').mkdir(parents=True);(directory/'sources').mkdir()
    for row in instances:
        shutil.copyfile(row['source_path'],directory/row['relative_path'])
    candidates={}
    for role,(identifier,name,expected) in PROGRAMS.items():
        path=REPORT/'sources'/name
        if sha(path)!=expected:raise ValueError('frozen U bytes changed')
        source=path.read_text();c=original.old.validate(source)
        candidates[role]={'id':identifier,'relative_path':'sources/'+name,'file_sha256':expected,'candidate':asdict(c)}
        shutil.copyfile(path,directory/'sources'/name)
    shutil.copyfile(B2/'H_frozen.json',directory/'sources/H_frozen.json')
    atomic_json(directory/'Data_history_audit.json',history)
    atomic_json(directory/'Structure_and_duplicates.json',audit)
    csv_table(directory/'Structure_train21_test28.csv',rows)
    csv_table(directory/'Data_identity.csv',instances)
    tasks=[{'id':f'{i:02d}_{role}','index':i,'role':role,'file':row['file']}
        for i,row in enumerate(instances) for role in (('dynamic','equal') if i%2==0 else ('equal','dynamic'))]
    protocol={'version':VERSION,'mode':'real','stage':'V1-0 frozen preparation; execution requires V1-1 authorization',
        'selection_basis':'B2-1 train champion fixed before any V1 result; no validation re-selection',
        'candidates':candidates,'source_B2_run':str(B2),'source_B2_plan_sha256':sha(B2/'Plan.json'),
        'H_file':'sources/H_frozen.json','H_file_sha256':sha(B2/'H_frozen.json'),'H_order':plan['H_order'],
        'original_manifest':str(ROOT/'data/fjsp_manifest.json'),'manifest_sha256':sha(ROOT/'data/fjsp_manifest.json'),
        'instances':instances,'tasks':tasks,'task_cap':56,'solve_pass_cap':112,
        'instance_timeout':15,'evaluation_runtime':original.old.evaluation_runtime(),
        'LB':'lower_bound_v5: max(max_j sum_o min_m p_jom, sum_jo min_m p_jom/M), no rounding',
        'execution':'original H01 evaluate_weight, MIX only, K10/H0H1 only; original append, minmax, ties, history and feasibility/recheck',
        'failure':'one evaluation reservation per task; incomplete/interrupted becomes invalid, never rerun; continue other fixed tasks; any failure makes full-program fitness and paired primary null',
        'checkpoint':'save reservation before evaluation; save complete task result before checkpoint commit; recover saved result, never refund an uncertain task',
        'statistics':STATISTICS,'gates':{'history_blocks_execution':history['blocks_execution'],
            'duplicate_blocks_execution':audit['blocks_execution'],'external_use_confirmation_pending':True},
        'API_requests':0,'extra_diagnostic_replays':0,'U_search_or_selection':False,
        'B2_frozen_pins':plan['pins']}
    paths = [Path(__file__),ROOT/'tools/h01_v1.py',ROOT/'tests/test_h01_v1.py']
    paths += [p for p in directory.rglob('*') if p.is_file()]
    protocol['pins']={str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}
    atomic_json(directory/'Protocol.json',protocol)
    (directory/'Protocol.sha256').write_text(sha(directory/'Protocol.json')+'\n')
    atomic_json(directory/'V1_0_readiness.json',{'stage':'V1-0 only','test28_parsed_for_metadata':28,
        'test28_solve_count':0,'LLM_requests':0,'real_execution_authorized':False,
        'protocol_sha256':sha(directory/'Protocol.json'),'history_gate':history['blocks_execution'],
        'duplicate_gate':audit['blocks_execution'],'external_history_confirmation_required':True})
    return protocol
