"""Offline receipts for real runs; no API, solving, retries or selection changes."""
import csv
import itertools
import json
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
            "observation_seconds","recheck_observation_seconds","worker_peak_rss_bytes"}
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
    return report
