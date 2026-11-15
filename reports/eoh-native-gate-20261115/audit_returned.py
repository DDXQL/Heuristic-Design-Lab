"""Audit two settled R8 results only. No H execution, transport or solver."""
from collections import Counter
from pathlib import Path
import csv
import hashlib
import json
import math
import zipfile
import numpy as np
OUT=Path(__file__).resolve().parent
FETCH=OUT.parents[1]/'reports/concurrent-prompt-v2-20261115/settled-fetch-1794747980856004000'


def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def main():
    status=read(FETCH/'status.json');assert status['retrieved'];results=[];csvrows=[];sum_passes=0;all_before={}
    for member in status['members']:
        root=Path(member['result']);job=member['job_id'];archive=FETCH/(job+'.zip');assert sha(archive)==member['ZIP_sha256']
        with zipfile.ZipFile(archive) as z:
            manifest=json.loads(z.read('retrieval-manifest.json'));assert manifest['job_id']==job
            assert set(z.namelist())==set(manifest['files'])|{'retrieval-manifest.json'}
            for n,h in manifest['files'].items():
                path=(root/n).resolve();assert path.is_relative_to(root)
                assert hashlib.sha256(z.read(n)).hexdigest()==h==sha(path)
                all_before[str(path)]=h
        cps=list((root/'runs').rglob('checkpoint.json'));assert len(cps)==1;run=cps[0].parent
        p=read(run/'Protocol.json');s=read(run/'checkpoint.json');j=read(run/'API_attempts.json');q=read(run/'exports/summary.json');initial=read(run/'populations/P000_initial.json');seed=p['config']['search_seed']
        assert sha(run/'Protocol.json')==(run/'Protocol.sha256').read_text().strip()==s['identity']
        assert p['config']['initialization_policy']=='native_N_finite_or_fail' and p['config']['population_size']==10
        assert p['config']['initialization_request_cap']==20 and p['config']['api_attempt_cap']==1020 and p['config']['evolution_request_cap']==1000
        assert s['phase']=='initialization_incomplete' and s['cursor']==10 and s['eoh']['initialization_requests']==10 and s['eoh']['operator_cursor']==0
        assert s['eoh']['population']==initial['population'] and len(initial['population'])==10 and initial['stage']=='evolution'
        tasks=list(s['tasks'].values());attempts=list(j['api_attempts'].values())
        assert len(tasks)==len(attempts)==10 and all(t['valid'] and t['operator']=='I1' and t['status']=='completed' for t in tasks)
        assert all(a['status']=='completed' and a['send_confirmed'] and a['number']==1 for a in attempts) and j['halt_reason'] is None
        assert all(a['reply']['metadata']['http_status']==200 and a['reply']['metadata']['model']=='gpt-6.1-sol' and a['reply']['metadata']['finish_reason']=='stop' for a in attempts)
        source=digest(p['source_files']);refs={r['file']:r['reference'] for r in p['references']};passes=0
        for ev in s['evaluations'].values():
            file=run/ev['path'];assert sha(file)==ev['sha256'];v=read(file)
            assert v['valid'] and not v['mock'] and len(v['instances'])==21 and not v['lifecycle']['alive'] and v['lifecycle']['exitcode']==0
            for row in v['instances']:
                assert row['reference']==refs[row['file']] and row['captured_solves']==2 and row['feasible']
                assert math.isclose(row['score'],(row['raw_cost']-row['reference'])/row['reference'],abs_tol=1e-12)
                assert row['source_before_sha256']==row['source_after_sha256']==source and row['semantic_sha256']==row['recheck_semantic_sha256'];passes+=2
            assert math.isclose(v['fitness'],-sum(r['score'] for r in v['instances'])/21,abs_tol=1e-12)
        assert passes==sum(q['physical_passes'][phase]['completed'] for phase in ('first','recheck'))
        sum_passes+=passes;finite=[r for r in initial['population'] if not r['negative_infinity'] and r['score'] is not None and math.isfinite(r['score'])]
        assert len(finite)==len(s['population'])==(8 if seed==501 else 9)
        assert not initial['next_population'] and initial['native_generation']==s['eoh']['native_generation']==2
        # Pure NumPy RNG replay only: the old guard consumed two first-E1
        # parent draws before stopping. It did not reserve or send that task.
        st=initial['np_rng'];rng=np.random.RandomState();rng.set_state((st[0],np.asarray(st[1],dtype=np.uint32),st[2],st[3],st[4]))
        finite=sorted(finite,key=lambda r:r['score'],reverse=True);weights=np.asarray([1/(rank+len(finite)) for rank in range(len(finite))]);weights/=weights.sum()
        parents=[finite[int(rng.choice(len(finite),p=weights))]['id'] for _ in range(2)]
        after=rng.get_state();packed=[after[0],after[1].tolist(),int(after[2]),int(after[3]),float(after[4])]
        assert packed==s['eoh']['np_rng'] and initial['np_rng']!=s['eoh']['np_rng']
        shared=read(root/'plans/first-eoh-501-502/gate/ledger.json');assert not shared['active'] and not shared['jobs'] and len(shared['requests'])==20 and all(r['state']=='completed' for r in shared['requests'].values())
        assert Counter(r['member'] for r in shared['requests'].values())[p['run_id']]==10
        active=set();peak=0
        for event in shared['events']:
            if event['event']=='sent':active.add(event['uid']);peak=max(peak,len(active))
            elif event['event']=='settled':active.remove(event['uid'])
        assert peak==1 and not active
        locks=[str(x.relative_to(run)) for x in run.rglob('*') if x.name.endswith('.lock') or x.name=='Stop.json'];assert not locks
        result={'seed':seed,'job_id':job,'Slurm_state':member['Slurm_state'],'exit_code':member['exit_code'],'run_dir':str(run),'phase':s['phase'],'reason':s['pause_reason'],'initialization_requests':10,'evolution_requests':0,'remaining_cumulative_cap':1010,'native_population_total':10,'finite_parents':len(finite),'native_tie_or_duplicate_penalties':sum(t.get('native_population_duplicate',False) for t in tasks),'AST_duplicate_attempts':q['duplicates'],'unique_evaluations_within_seed':len(s['evaluations']),'physical_solves_including_recheck':passes,'initial_best_training_J':q['best_J'],'unknown_sends':0,'automatic_retries':0,'known_usage':q['known_usage_subtotal'],'all_actual_responses_valid_and_confirmed':True,'shared_confirmed_send_peak':peak,'locks':locks,'initial_snapshot_preserved_population':True,'pre_first_E1_RNG_snapshot_available':True,'checkpoint_has_two_unsubmitted_parent_draws':True,'pure_replay_first_E1_parent_ids':parents,'pure_replay_matches_checkpoint_rng':True,'Run_clock':read(run/'Run_clock.json'),'ZIP_sha256':member['ZIP_sha256'],'manifest_verified_files':len(manifest['files'])}
        results.append(result)
        for task in tasks:csvrows.append({'seed':seed,'task':task['id'],'J':task['J'],'candidate_key':task['candidate']['key'],'native_penalty':task['native_population_duplicate'],'native_population_score':task['native_population_score'],'evaluation_key':task['evaluation_key']})
    assert sum_passes==798 and all(sha(Path(path))==h for path,h in all_before.items())
    audit={'verified':True,'source_fetch':str(FETCH),'members':results,'total_confirmed_model_requests':20,'total_recorded_solves_including_recheck':798,'all_original_manifest_files_unchanged':True,'new_API_requests':0,'new_solves':0,'new_model_generations':0,'RNG_replay_scope':'saved numerical RNG state and rank indices only; no candidate/H/model executed','protocol_amendment_adopted':False,'continuation_implemented':False,'old_runs_modified':False,'next_decision':'strict all10 finite gate versus original native population admission; continuation needs explicit new identity/budget/RNG audit, not a phase edit'}
    (OUT/'RETURNED_AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
    with (OUT/'两份初始化候选.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(csvrows[0]));w.writeheader();w.writerows(csvrows)
    text='''# 修复版EoH两份初始化终态核验\n\n两份ZIP和全部清单成员已重新核验，读取前后原字节不变。种子501/502均确认发送10次，全部HTTP200、目标模型及stop结束、合法且评价有效，无未知发送/重试。演化次数均0。Slurm FAILED/2:0来自应用的initialization_incomplete返回码，不是传输或求解崩溃。\n\n|搜索种子|原生总种群|有限分父代|原生同分/重复惩罚|AST重复|独立候选评价|首解+复核次数|初始化最佳J|\n|---|---:|---:|---:|---:|---:|---:|---:|\n'''
    for r in results:text+='|'+ '|'.join(str(r[k]) for k in ['seed','native_population_total','finite_parents','native_tie_or_duplicate_penalties','AST_duplicate_attempts','unique_evaluations_within_seed','physical_solves_including_recheck','initial_best_training_J'])+'|\n'
    text+='''\n合计20次请求和798次物理求解已发生，均应保留，不因协议修订退款或补预算。每份原1020中已花10次，未开始1000次演化。当前J仅为初始化成绩，不能充当完整长实验结果或与U长实验作等预算结论。共享账本20条全部结算、发送至结算峰值1、无活动请求/搜索，无运行锁。共享账户租约本身不在取回包中，不假设已经释放。\n\n停止原因与冻结的native_N_finite_or_fail门槛一致。原生种群10条中允许负无穷记录，按秩有放回选择时过滤非有限成员；本版额外要求有限父代也必须10，8/9因此停止。AST重复与同分惩罚是不同计数，502的AST重复0不代表没有同分。\n\n后续不能只把phase改成paused：原适配器先抽取了首次E1的两个父代，再触发门槛停止，所以checkpoint的随机状态已经前进。保存的P000_initial.json保留同一种群及抽样前随机状态；纯NumPy离线重放两次按秩选择后，与终态随机状态逐项一致。这个证据支持后续设计显式同种子承接，但不等于已实现或已授权承接。要保留原响应、结果、预算、截止时间、同分惩罚和请求身份，并在新协议里标明父协议；不得直接改旧检查点伪装正常恢复，也不得重复请求未提交的抽样。\n\n原生门槛修订尚未采用，远端源码/配置/检查点及门禁未改。本次审计新API0、新求解0，仅重放数值随机索引，不执行任何H。具体源路径、协议和ZIP身份、时钟、计数见RETURNED_AUDIT.json。\n'''
    (OUT/'取回核验说明.md').write_text(text)
    print(json.dumps({'verified':True,'requests_already_spent':20,'solves_already_spent':798,'finite_parents':[r['finite_parents'] for r in results],'RNG_replay_matches':True,'source_unchanged':True,'new_API_requests':0,'new_solves':0},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
