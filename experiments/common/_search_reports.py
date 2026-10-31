"""Offline receipts for real runs; no API, solving, retries or selection changes."""
import csv
import itertools
import json
import math
from pathlib import Path
from heuristic_design.core.storage import read, write, sha


def protocol_state(directory):
    directory=Path(directory);p=read(directory/"Protocol.json");s=read(directory/"checkpoint.json")
    identity=sha(directory/"Protocol.json")
    receipt=directory/"Protocol.receipt.json"
    expected=read(receipt)["sha256"] if receipt.exists() else (directory/"Protocol.sha256").read_text().strip()
    if identity!=expected or s["identity"]!=identity:raise ValueError("运行协议身份不一致")
    checkpoint_receipt=directory/"checkpoint.receipt.json"
    if checkpoint_receipt.exists() and read(checkpoint_receipt)!={"identity":identity,"sha256":sha(directory/"checkpoint.json")}:
        raise ValueError("检查点收据不一致，保留未知状态核查")
    return p,s


def evidence(directory):
    directory=Path(directory);p,s=protocol_state(directory);requests=[];api_pairs=[];cpu_pairs=[]
    for task in s["tasks"].values():
        if "request_key" not in task:continue
        reply=read(directory/task["response_path"]) if task.get("response_path") else {}
        value=reply.get("value",{}) if reply.get("ok") else {};usage=value.get("usage");meta=value.get("metadata") or {}
        requests.append({"id":task["id"],"stage":task["stage"],"generation":task["generation"],
            "operator":task["operator"],"valid":task["valid"],"failure":task.get("failure"),
            "sent_confirmed":bool(task.get("sent_confirmed")),"http_status":meta.get("http_status"),
            "response_model":meta.get("model"),"usage_known":usage is not None,
            "input_tokens":usage.get("input_tokens") if usage else None,
            "output_tokens":usage.get("output_tokens") if usage else None,
            "task_started_at_unix":task.get("generation_timing",{}).get("started_at_unix"),
            "sent_at_unix":task.get("wire_send_confirmed_at_unix"),
            "finished_at_unix":task.get("generation_timing",{}).get("finished_at_unix")})
    by_id={r["id"]:r for r in requests}
    stable=True
    for path in sorted((directory/"batch-receipts").glob("*.json")):
        b=read(path);stable &= b["tasks"]==b["semantics_commit_order"]
        for a_id,b_id in itertools.combinations(b["tasks"],2):
            a=s["tasks"][a_id];bb=s["tasks"][b_id]
            if (a["stage"]!="evolution" or a["generation"]!=bb["generation"]
                or {a["operator"],bb["operator"]}!={"CROSS","MUTATE"}):continue
            ra=by_id.get(a_id,{});rb=by_id.get(b_id,{})
            if all(x is not None for x in (ra.get("sent_at_unix"),rb.get("sent_at_unix"),ra.get("finished_at_unix"),rb.get("finished_at_unix"))):
                overlap=min(ra["finished_at_unix"],rb["finished_at_unix"])-max(ra["sent_at_unix"],rb["sent_at_unix"])
                if overlap>0:api_pairs.append({"tasks":[a_id,b_id],"generation":a["generation"],"overlap_seconds":overlap})
            life_paths=[directory/"worker-receipts"/tid/"lifecycle.json" for tid in (a_id,b_id)]
            if all(x.exists() for x in life_paths) and a["valid"] and bb["valid"]:
                lives=[read(x) for x in life_paths]
                if all(x.get("all_results_received") and x.get("exitcode")==0 and not x.get("alive") for x in lives):
                    overlap=min(x["finished_monotonic"] for x in lives)-max(x["started_monotonic"] for x in lives)
                    if overlap>0:cpu_pairs.append({"tasks":[a_id,b_id],"generation":a["generation"],"overlap_seconds":overlap})
    parents_match=True
    for record in s["plans"].values():
        path=directory/record["path"]
        if sha(path)!=record["sha256"]:raise ValueError("冻结父代计划改变")
        plan=read(path)
        subjects={r["id"] for r in plan["population"]}
        parents_match &= len(plan["tasks"])==2*len(subjects)
        for subject in subjects:
            pair=[r for r in plan["tasks"] if r["subject"]==subject]
            parents_match &= len(pair)==2 and {r["operator"] for r in pair}=={"CROSS","MUTATE"}
        for task in plan["tasks"]:
            actual=s["tasks"][task["id"]]
            parents_match &= task["parent_keys"]==actual["parent_keys"] and task["parents"]==actual["parents"]
    unknown=sum(r["sent_confirmed"] and not r["usage_known"] for r in requests)
    transport_bad=[r["id"] for r in requests if not r["sent_confirmed"] or r["http_status"]!=200
                   or r["response_model"]!=p["config"]["provider"]["expected_response_model"]]
    passed=(s["phase"]=="completed" and s["generation"]>=1 and s["initialization_complete"]
            and bool(api_pairs) and bool(cpu_pairs) and stable and parents_match and not transport_bad and unknown==0)
    return {"passed":passed,"phase":s["phase"],"generation":s["generation"],
        "attempts_reserved":s["initialization_requests"]+s["generation_requests"],
        "sent_confirmed":sum(r["sent_confirmed"] for r in requests),
        "known_input_tokens":sum(r["input_tokens"] or 0 for r in requests),
        "known_output_tokens":sum(r["output_tokens"] or 0 for r in requests),"unknown_usage_sent":unknown,
        "transport_or_model_failures":transport_bad,"api_client_overlap":api_pairs,"cpu_worker_overlap":cpu_pairs,
        "stable_commit_order":stable,"frozen_parents_match":parents_match,"requests":requests,
        "scope":"Client in-flight overlap and live CPU-worker overlap; not provider-internal execution or a throughput limit guarantee."}


def instance_rows(path):
    """Stream the engine's indented result JSON; skip large action traces."""
    fields={"file","score","captured_solves","feasible","solve_seconds","recheck_solve_seconds",
            "observation_seconds","recheck_observation_seconds","worker_peak_rss_bytes",
            "semantic_sha256","recheck_semantic_sha256"}
    active=False;row=None;solution=False
    with Path(path).open() as stream:
        for line in stream:
            if not active:
                if line=='  "instances": [\n':active=True
                continue
            if line=='  ],\n':break
            if line=='    {\n':row={}
            elif line in ('    },\n','    }\n'):
                yield row;row=None
            elif row is not None and line.startswith('      "'):
                key,value=line.strip().split(':',1);key=json.loads(key)
                if key=='solution':solution=True
                elif key in fields:row[key]=json.loads(value.rstrip(',\r\n'))
            elif solution and line.startswith('        "makespan":'):
                row['Cmax']=json.loads(line.strip().split(':',1)[1].rstrip(',\r\n'))
            elif line.startswith('      }'):solution=False


def finish(directory,summary):
    directory=Path(directory);p,s=protocol_state(directory);out=directory/"exports"
    report=evidence(directory);write(out/"acceptance.json",{k:v for k,v in report.items() if k!="requests"})
    with (out/"requests.csv").open("w",newline="") as f:
        fields=list(report["requests"][0]) if report["requests"] else ["id"]
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(report["requests"])
    timelines=[]
    for task in s["tasks"].values():
        if not task.get("evaluation_timing"):continue
        life_path=directory/"worker-receipts"/task["id"]/"lifecycle.json"
        life=read(life_path) if life_path.exists() else {}
        timelines.append({"id":task["id"],"generation":task["generation"],"operator":task["operator"],
            **task["evaluation_timing"],"worker_pid":life.get("pid"),
            "worker_started_monotonic":life.get("started_monotonic"),
            "worker_finished_monotonic":life.get("finished_monotonic")})
    if timelines:
        with (out/"evaluation_timings.csv").open("w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(timelines[0]));w.writeheader();w.writerows(timelines)
    rows=[];refs={r["file"]:r["reference"] for r in p["references"]}
    for task in s["tasks"].values():
        if task.get("duplicate_of"):continue  # A skipped duplicate is not another evaluation.
        ev=s["evaluations"].get(task.get("candidate",{}).get("key"))
        if not ev:continue
        for row in instance_rows(directory/ev["path"]):
            rows.append({"candidate":task["id"],"complete_candidate_valid":task["valid"],"LB":refs[row["file"]],**row})
    if rows:
        with (out/"per_instance.csv").open("w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for row in rows for k in row)));w.writeheader();w.writerows(rows)
    if s["phase"]=="completed" and summary["champion"]:
        champion=summary["champion"];write(out/"frozen_training_champion.json",{
            "selection":"highest complete train21 Fitness, then fixed ID; validation never reselects",
            "champion":champion,"protocol_sha256":s["identity"],"completed_generations":s["generation"],
            "H_order":[r["key"] for r in p["members"]],"config":p["config"],
            "source_files":p["source_files"],"validation_status":"not_run"})
        (out/"frozen_training_champion.py").write_text(champion["candidate"]["code"])
        if (directory/'launch/baselines.json').exists():paired_comparison(directory,champion)
    return report


def baseline_bundle(root,runs,data,members,config):
    """Validate and snapshot already certified R1 outcomes; never solve again."""
    import hashlib
    expected=[(r['file'],r['source_sha256']) for r in data]
    common,cs=protocol_state(root/runs['common']);refs={r['file']:r['reference'] for r in common['references']}
    for key in ('window','enabled_groups','solve_seed','instance_timeout_seconds'):
        if common['config'][key]!=config[key]:raise ValueError('R1 comparison protocol mismatch: '+key)
    if [r['key'] for r in common['members']]!=[r['key'] for r in members]:raise ValueError('R1 H order mismatch')
    constants=[]
    for i in range(10):
        matches=[t for t in cs['tasks'].values() if t['candidate']['code']==f'def use_heuristics(state):\n    return {i}\n']
        if len(matches)!=1:raise ValueError('R1 constant candidate missing or ambiguous')
        constants.append(matches[0])
    best=sorted(constants,key=lambda t:(-t['fitness'],t['id']))[0]
    specifications=[('H0','common',constants[0]['id']),('BEST_FIXED_H','common',best['id']),
                    ('H0_H1_EQUAL','legacy','H0_H1_EQUAL'),('EOH_FROZEN','eoh',None)]
    bundle={'instances':[{'file':r['file'],'source_sha256':r['source_sha256'],'LB':refs[r['file']]} for r in data],
            'baselines':[],'historical_only':[],'selection':'Complete train21 Fitness; fixed candidate ID ties; no validation selection'}
    cache={}
    for label,kind,tid in specifications:
        directory=root/runs[kind];p,s=protocol_state(directory)
        actual=[(r['file'],r.get('source_sha256',r.get('sha256'))) for r in p['instances']]
        if actual!=expected or s['phase']!='completed':raise ValueError('R1 baseline instance/phase mismatch')
        if kind!='common':
            if p['config']['solve_seed']!=config['solve_seed'] or p['config']['instance_timeout']!=30:
                raise ValueError('R1 legacy/EoH evaluation seed/deadline mismatch')
            if kind=='legacy' and sha(directory/'H_frozen.json')!=common['input_provenance']['H']['sha256']:
                raise ValueError('R1 static baseline H identity mismatch')
            if kind=='eoh' and sha(directory/'Frozen_native_rule.py')!=p['provenance']['original_source_sha256']:
                raise ValueError('R1 EoH frozen source identity mismatch')
        task=s['tasks'][tid] if tid else next(iter(s['tasks'].values()))
        ev=s['evaluations'][task.get('evaluation_key',task['candidate']['key'])];path=directory/ev['path']
        if str(path) not in cache:
            h=hashlib.sha256()
            with path.open('rb') as f:
                for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
            if h.hexdigest()!=ev['sha256']:raise ValueError('R1 evaluation receipt mismatch')
            rows=list(instance_rows(path)) if kind=='common' else read(path)['instances']
            normalized=[]
            for row in rows:
                name=row['file'];lb=refs[name];cmax=row.get('Cmax',row.get('makespan'))
                if (row.get('feasible') is not True or row.get('captured_solves')!=2
                    or not math.isclose(row['score'],-cmax/lb,abs_tol=1e-12,rel_tol=0)):
                    raise ValueError('R1 baseline score/feasibility/recheck mismatch')
                if kind=='common':
                    if row['semantic_sha256']!=row['recheck_semantic_sha256']:raise ValueError('R1 recheck mismatch')
                else:
                    if row['lower_bound']!=lb or row['physical_schedule_sha256']!=row['recheck_physical_schedule_sha256']:
                        raise ValueError('R1 physical recheck or LB mismatch')
                normalized.append({'file':name,'Cmax':cmax,'LB':lb,'score':row['score'],'feasible':True,'captured_solves':2})
            if [r['file'] for r in normalized]!=[r['file'] for r in data]:raise ValueError('R1 incomplete train21')
            cache[str(path)]=normalized
        rows=cache[str(path)];fitness=sum(r['score'] for r in rows)/len(rows)
        if not task['valid'] or not math.isclose(fitness,task['fitness'],abs_tol=1e-12,rel_tol=0):raise ValueError('R1 Fitness mismatch')
        bundle['baselines'].append({'name':label,'candidate_id':task['id'],'candidate_key':task['candidate']['key'],
            'fitness':fitness,'rows':rows,'valid_rate':1.,'run_directory':str(directory),
            'protocol_sha256':sha(directory/'Protocol.json'),'evaluation_sha256':ev['sha256'],
            'note':p.get('provenance',{}).get('notice','Existing R1 fixed evaluation; API=0; complete-row T30 + 2s exit grace')})
    historical=root/'reports/b1-p1-to-p2-T15-seed501-20261027-v1/REPORT_ZH.md'
    bundle['historical_only'].append({'name':'old B1','source':str(historical),
        'report_sha256':sha(historical),'state':'legacy seven scalar inputs',
        'output_space':'SELECT or two-member MIX over frozen 10H',
        'status':'Two historical generations completed via interrupted continuation; not an independent rerun',
        'fitness':-2.092337613385,'budget':'N5/G2; 29 actual logical tasks/attempts; historical caps 40 logical / 60 API attempts',
        'deadline':'T15 complete row; final continuation 1s exit grace; inherited one-hour run deadline (includes interruption)',
        'comparison_scope':'Historical reference only; state, output space, budget and deadline all differ. No new solve.'})
    return bundle


def paired_comparison(directory,champion):
    directory=Path(directory);out=directory/'exports';folder=directory/'launch'
    receipt=read(folder/'postprocess.receipt.json')
    if sha(folder/'baselines.json')!=receipt['baselines_sha256']:raise ValueError('Frozen baseline snapshot changed')
    bundle=read(folder/'baselines.json');p,s=protocol_state(directory)
    ev=s['evaluations'][champion['candidate']['key']]
    rows=list(instance_rows(directory/ev['path']));expected=bundle['instances']
    if [r['file'] for r in rows]!=[r['file'] for r in expected]:raise ValueError('Champion comparison requires complete frozen train21')
    q=[]
    for row,ref in zip(rows,expected):
        if (row['feasible'] is not True or row['captured_solves']!=2
            or row['semantic_sha256']!=row['recheck_semantic_sha256']
            or not math.isclose(row['score'],-row['Cmax']/ref['LB'],abs_tol=1e-12,rel_tol=0)):
            raise ValueError('Champion comparison evidence mismatch')
        q.append(row['Cmax']/ref['LB'])
    fitness=-sum(q)/len(q)
    if not math.isclose(fitness,champion['fitness'],abs_tol=1e-12,rel_tol=0):raise ValueError('Champion Fitness mismatch')
    comparisons=[];paired=[]
    for baseline in bundle['baselines']:
        bq=[r['Cmax']/r['LB'] for r in baseline['rows']];delta=(sum(q)/sum(bq)-1)*100
        outcomes=[]
        for row,b in zip(rows,baseline['rows']):
            outcome='win' if row['Cmax']<b['Cmax'] else 'loss' if row['Cmax']>b['Cmax'] else 'tie'
            outcomes.append(outcome);paired.append({'baseline':baseline['name'],'file':row['file'],'LB':b['LB'],
                'champion_Cmax':row['Cmax'],'baseline_Cmax':b['Cmax'],'champion_Cmax_over_LB':row['Cmax']/b['LB'],
                'baseline_Cmax_over_LB':b['Cmax']/b['LB'],'outcome':outcome})
        comparisons.append({'baseline':baseline['name'],'champion_Fitness':fitness,'baseline_Fitness':baseline['fitness'],
            'Fitness_difference':fitness-baseline['fitness'],'champion_mean_Cmax_over_LB':-fitness,
            'baseline_mean_Cmax_over_LB':-baseline['fitness'],'mean_ratio_relative_change_percent':delta,
            'wins':outcomes.count('win'),'losses':outcomes.count('loss'),'ties':outcomes.count('tie'),
            'champion_instance_valid_rate':sum(r['feasible'] and r['captured_solves']==2 for r in rows)/len(expected),
            'baseline_instance_valid_rate':baseline['valid_rate']})
    for name,table in (('train21_comparison.csv',comparisons),('train21_paired_instances.csv',paired)):
        with (out/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
    write(out/'train21_comparison.json',{'champion_id':champion['id'],'comparisons':comparisons,
        'search_task_valid_rate':sum(t['valid'] for t in s['tasks'].values())/len(s['tasks']),
        'historical_only':bundle['historical_only'],'baseline_snapshot_sha256':receipt['baselines_sha256'],
        'metric_note':'Fitness=mean(-Cmax/LB); relative change=mean(new Cmax/LB)/mean(baseline Cmax/LB)-1; negative is better. W/L/T uses same-instance Cmax.',
        'additional_API_requests':0,'additional_solves':0,'validation_status':'not_run'})
    lines=['# 同train21配对比较','',f'冠军：{champion["id"]}；完整训练Fitness={fitness:.12f}。',
           '相对变化按平均Cmax/LB之比计算，负值表示改善；有效率区分实例完整可行率与搜索任务有效率。',
           '', '| 基线 | 基线Fitness | 冠军Fitness | 平均Cmax/LB变化 | 胜/负/平 | 实例有效率（冠军/基线） |',
           '|---|---:|---:|---:|---:|---:|']
    for r in comparisons:lines.append(f'| {r["baseline"]} | {r["baseline_Fitness"]:.9f} | {fitness:.9f} | {r["mean_ratio_relative_change_percent"]:+.3f}% | {r["wins"]}/{r["losses"]}/{r["ties"]} | {r["champion_instance_valid_rate"]:.0%}/{r["baseline_instance_valid_rate"]:.0%} |')
    lines+=['','旧B1仅列历史参照：历史两代接续完成，冠军Fitness≈−2.092337613385；七标量状态、SELECT/双H MIX、N5/G2、实际29次请求（原上限40逻辑/60尝试）、T15及继承的一小时窗口；与本轮同时存在多项差异，不能归因为仅改变状态。原报告及哈希见JSON。',
            '冻结EoH历史模型/预算与选择分区不同，作为冻结规则质量参照，不比较搜索成本。复用R1结果；本表新增API请求0、求解0；未访问validation/test。']
    (out/'train21_comparison.md').write_text('\n'.join(lines)+'\n')
