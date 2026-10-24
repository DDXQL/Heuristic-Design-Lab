"""Bounded read-only provenance audit; never starts an evaluator or supplier."""
from pathlib import Path
import platform
from importlib.metadata import version as package_version
from fjsp_usage.research_real.assets import check_seal
from fjsp_usage.research.protocol import digest
from fjsp_usage.baseline_a.policies import specs
from fjsp_usage.baseline_a.validation import validate_result
from tools import fusion_v4_experiment as old

v2=old.v2;ROOT=old.ROOT
H_SOURCE=ROOT/'runs/v22-gpt61-select-mix-301-20261014-v1'
GRID=ROOT/'reports/usage-fixed-pair-weight-grid-20261018-v1'
B1=ROOT/'runs/b1-ns-recovery-B-v1-20261022'
# These files are NOT in the local native_worker -> scheduler call chain. Their
# changes prevent resuming old searches, but do not change recorded static scores.
NONEXEC_DRIFT={
    'code/fjsp_usage/research_real/budget.py','code/fjsp_usage/research_real/conditional_research.py',
    'code/fjsp_usage/research_real/config.py','code/fjsp_usage/research_real/real_transport.py',
    'code/fjsp_usage/research_real/workflow.py','code/fjsp_usage/usage_v2/access.py',
    'code/fjsp_usage/usage_v2/config.py','code/fjsp_usage/usage_v2/registration.py',
    'code/fjsp_usage/usage_v2/workflow.py','experiments/tier2/usage_v2/run.py'}


def extract(document,selector):
    for key in selector:document=document[key]
    return document


def audit_inputs():
    original=old.check(old.DEFAULT);frozen=check_seal(v2.read(old.DEFAULT/'H_frozen.json'),kind='H_frozen',mode='real')
    plan=v2.read(v2.B2/'Plan.json');manifest=v2.read(ROOT/'data/fjsp_manifest.json')
    instances=original['instances'];names=[r['file'] for r in instances];keys=original['H_order']
    if names!=manifest['split']['train'] or names!=plan['names'] or keys!=plan['H_order']:
        raise ValueError('train/H order mismatch')
    if len(keys)!=10 or len(set(keys))!=10:raise ValueError('ten distinct H required')
    protected={};cache={};references={};drift=[]
    def bind(path):
        path=Path(path);relative=str(path.relative_to(ROOT));protected[relative]=v2.sha(path)
        return relative
    def read(path):bind(path);return v2.read(path)
    def execution_pins(pins):
        changes=[]
        for name,h in pins.items():
            path=ROOT/name
            if not path.is_file():raise ValueError('missing historical pin: '+name)
            if v2.sha(path)!=h:
                if name not in NONEXEC_DRIFT:raise ValueError('unexplained cache execution/evidence drift: '+name)
                changes.append(name)
            bind(path)
        return changes
    def add(identifier,path,selector,level):
        result=extract(read(path),selector)
        validate_result(result,instances,level)
        if not result['valid']:raise ValueError('invalid result cannot be a complete static cache')
        cache[identifier]={'source_file':str(path.relative_to(ROOT)),'source_sha256':v2.sha(path),
            'selector':selector,'level':level,'fitness':result['fitness'],
            'process_evidence':'modern terminal exit0' if level=='modern' else
                'legacy accepted native two-solve record; no retained terminal process receipt',
            'seed_note':'fixed closed-numeric H and constant U, deterministic scheduler; generation seed is not evaluation randomness'}
    # Follow only the selected H/cache chain, not the 1252-file API ancestry.
    source_protocol=read(H_SOURCE/'protocol.json')
    environment={'python':platform.python_version(),'platform':platform.platform(),
        'dependencies':{n:package_version(n) for n in source_protocol['implementation']['dependencies']}}
    if any(environment[k]!=source_protocol['implementation'][k] for k in environment):
        raise ValueError('cached result Python/platform/dependency environment mismatch')
    if source_protocol['dataset']!=plan['dataset'] or source_protocol['config']['instance_timeout']!=15:
        raise ValueError('cached H data/deadline mismatch')
    drift.append({'source':'H native cache','nonexecution_changes':execution_pins(source_protocol['implementation']['files'])})
    source_h=check_seal(read(H_SOURCE/'H_frozen.json'),kind='H_frozen',mode='real')
    reassessment=check_seal(read(H_SOURCE/'Conditional_H_reassessment.json'),kind='Conditional_H_reassessment',mode='real',context=source_h['context'])
    reused=reassessment['reused_evaluation_evidence'];prior=Path(reused['path'])
    if v2.sha(prior)!=reused['sha256']:raise ValueError('H cache original reassessment hash mismatch')
    prior_document=check_seal(read(prior),kind='Conditional_H_reassessment',mode='real')
    if source_h['members']!=frozen['members'] or len(reassessment['rows'])!=10 or len(prior_document['rows'])!=10:
        raise ValueError('frozen member/cache chain mismatch')
    for i,(member,row,prior_row) in enumerate(zip(frozen['members'],reassessment['rows'],prior_document['rows'])):
        candidate=v2.checked_candidate(member['candidate'],'h')
        if (candidate.key!=keys[i] or row['source_row']['candidate']!=member['candidate']
            or row['result']!=member['training_result'] or prior_row['result']!=row['result']
            or member['fitness']!=row['result']['fitness']):raise ValueError('H cache code/result binding differs')
        add(f'H{i}',H_SOURCE/'Conditional_H_reassessment.json',['rows',i,'result'],'legacy_single')
    # Strong modern H01 baseline; independently verify all21 against legacy grid.
    vp=v2.check(v2.DEFAULT);checkpoint=read(v2.DEFAULT/'checkpoint.json')
    cached=checkpoint['strategies']['H0_H1_WEIGHTED_SUM'];path=v2.DEFAULT/cached['result_path']
    if not cached['valid'] or cached['status']!='completed' or v2.sha(path)!=cached['result_sha256']:
        raise ValueError('modern H01 cache checkpoint mismatch')
    folder=path.parent;before=read(folder/'before.json');after=read(folder/'after.json');life=read(folder/'lifecycle.json')
    from tools.b1_timeout_boundary import classify_boundary
    expected={**vp['source_files'],**vp['protected_files']};actual={n:v2.sha(ROOT/n) for n in expected}
    boundary=classify_boundary(v2.read(path),before=before,after=after,lifecycle=life,
        expected_identity=read(v2.DEFAULT/'Expected_loaded_identity.json')['identity'],expected_files=expected,start_files=actual,end_files=actual)
    if boundary['decision']!='original_result_checks_required':raise ValueError('H01 terminal certification failed')
    add('H0_H1_WS',path,[],'modern')
    grid=read(GRID/'Plan.json');complete=read(GRID/'Evaluation_complete.json')
    if grid['names']!=names or grid['H_order']!=keys or grid['timeout_seconds']!=15 or complete['original_pins_unchanged'] is not True:
        raise ValueError('legacy pair grid contract mismatch')
    drift.append({'source':'four-pair static grid','nonexecution_changes':execution_pins(grid['pins'])})
    for version in grid['versions']:
        if version['weights']!=[.5,.5]:continue
        candidate=v2.checked_candidate(version['candidate'],'U');fn=v2.compile_candidate(candidate)
        vector=tuple(.5 if i in version['pair'] else 0. for i in range(10))
        if fn(*([0.]*6+[-1]))!=(1,vector):raise ValueError('legacy fixed pair definition mismatch')
        source=GRID/'sources'/(version['id']+'.py')
        if v2.sha(source)!=version['source_sha256'] or candidate.code!=source.read_text():raise ValueError('legacy static source mismatch')
        bind(source);pair_path=GRID/'results'/(version['id']+'.json');result=read(pair_path)
        validate_result(result,instances,'legacy_pair')
        identifier=f"H{version['pair'][0]}_H{version['pair'][1]}_WS"
        if identifier=='H0_H1_WS':
            modern=extract(v2.read(ROOT/cache[identifier]['source_file']),[])
            if [(r['makespan'],r['score'],r['physical_schedule_sha256']) for r in result['instances']]!=[
                (r['makespan'],r['score'],r['physical_schedule_sha256']) for r in modern['instances']]:
                raise ValueError('H01 historical per-instance mismatch')
        else:add(identifier,pair_path,[],'legacy_pair')
    # B1 and B2 are comparison references only, never cache members or search starts.
    for label,folder,protocol_name in (('B1',B1,'Protocol.json'),('B2',v2.B2,'Plan.json')):
        protocol=read(folder/protocol_name);cp=read(folder/'r501/B/checkpoint.json')
        if protocol['H_order']!=keys or protocol['dataset']!=plan['dataset']:raise ValueError('LLM reference H/data mismatch')
        winner=max(cp['population'],key=lambda r:r['fitness']);candidate=v2.checked_candidate(winner['candidate'],'U')
        result=cp['evaluations'][winner['id']]['result'];validate_result(result,instances,'legacy_pair')
        if not result['valid'] or result['fitness']!=winner['fitness']:raise ValueError('LLM reference result mismatch')
        if label=='B1':
            start=read(folder/'worker_evidence'/(candidate.key+'.before.json'));end=read(folder/'worker_evidence'/(candidate.key+'.after.json'))
            if start['pid']!=end['pid'] or start['identity']!=end['identity'] or digest(start['modules'])!=start['identity']:
                raise ValueError('B1 reference end identity mismatch')
            for module in start['modules'].values():
                if v2.sha(Path(module['file']))!=module['source_sha256']:raise ValueError('B1 witness source differs')
                bind(Path(module['file']))
            terminal=read(folder/'Execution_terminal.json')
            if terminal['generations_completed']!=1 or terminal['second_generation_requests']!=0:
                raise ValueError('B1 completion reference changed')
        fields=('file','makespan','lower_bound','score','single_solve_seconds','deterministic_recheck_seconds','physical_schedule_sha256')
        references[label]={'id':winner['id'],'candidate_key':candidate.key,'fitness':result['fitness'],
            'instances':[{k:r.get(k) for k in fields} for r in result['instances']],
            'source_checkpoint':str((folder/'r501/B/checkpoint.json').relative_to(ROOT)),
            'source_checkpoint_sha256':v2.sha(folder/'r501/B/checkpoint.json'),
            'generations_completed':1 if label=='B1' else cp['generation'],
            'phase':cp['phase'],'logical_attempts':len(cp['attempts']),
            'complete_valid_new_candidates':sum(e['result']['valid'] for e in cp['evaluations'].values()),
            'not_budget_matched':True,'terminal_receipt':'not reconstructed; historical accepted result'}
    missing=[s for s in specs() if s['id'] not in cache]
    if len(cache)!=14 or len(missing)!=41:raise ValueError('audited cache coverage changed; review before freezing')
    return {'cache':cache,'missing_strategies':missing,'protected_files':protected,'references':references,'environment':environment,
        'execution_drift_audit':drift,'H_order':keys,'instances':instances,
        'summary':{'single_cached':10,'pair_cached':4,'new_strategies':41,'new_evaluation_cap':861,'new_solve_pass_cap':1722,
            'deducted_cached_evaluations':294,'deducted_cached_passes':588,'LLM_requests':0},
        'excluded_sources':[
            {'source':'Fixed_H_summary.csv','reason':'summary alone insufficient; native sealed per-instance results used instead'},
            {'source':'V2 H0/H5 and H5/H9 WS invalid results','reason':'no complete21 fitness; retained as historical timeouts, new lean Baseline-A evaluation predeclared once'},
            {'source':'V3 H0/H5 Borda quarantine and all MAX/MIN/Borda/V4 switching','reason':'wrong operator/policy or quarantined; never adopted'},
            {'source':'old interrupted B1 initialization','reason':'historical unfinished inflight not resumed; certified Recovery-B reference used'}],
        'cache_evidence_limit':'Legacy caches satisfy their native accepted two-solve source/data contract; no retroactive claim of modern terminal PID/exit0 receipts. New solves require V4 lifecycle.'}
