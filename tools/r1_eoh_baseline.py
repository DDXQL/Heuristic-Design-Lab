"""Frozen native EoH rule adapter over the existing task controller and T30 collector.

No generation, rule rewriting, population selection or new recovery mechanism.
"""
from dataclasses import asdict
import csv
import hashlib
import multiprocessing as mp
from pathlib import Path
import socket
from statistics import fmean
import time

from heuristic_design.core import execution, evolution_v1
from heuristic_design.core.lifecycle import collect
from heuristic_design.core.storage import read, write, sha, digest
from heuristic_design.core.terminal_ops import snapshot
from fjsp_usage.baseline_a.validation import validate_result
from fjsp_usage.research.candidates import Candidate
from fjsp_usage.offline_v2 import lower_bound_v5
from llm4ad.task.optimization.fjsp_set.instances import load_instance
from llm4ad.task.optimization.fjsp_set.scheduler import construct_schedule

ROOT = Path(__file__).resolve().parents[1]
VERSION = "R1-native-frozen-EoH-v1"
FIELDS = {"reference_run", "rule_manifest", "rule_source", "search_seed", "solve_seed",
          "instance_timeout", "window_seconds", "api_mode", "real_requests_authorized"}


def native_rule(value):
    c=Candidate(**value)
    if c.kind != "native-frozen-h" or hashlib.sha256(c.code.encode()).hexdigest()!=c.key:
        raise ValueError("native frozen rule identity mismatch")
    namespace={}
    exec(compile(c.code,"<unchanged-frozen-EoH>","exec"),namespace)
    function=namespace.get("priority")
    if not callable(function):raise ValueError("frozen rule must define priority")
    return function


def preflight(parameters):
    if not isinstance(parameters,dict) or set(parameters)!=FIELDS:
        raise ValueError("未知或缺失入口参数")
    c=dict(parameters)
    if c["api_mode"]!="disabled" or c["real_requests_authorized"] is not False:
        raise ValueError("EoH固定评价禁止API")
    if (type(c["instance_timeout"]) is not int or c["instance_timeout"]!=30
            or type(c["solve_seed"]) is not int or c["solve_seed"]!=501):
        raise ValueError("保留T30和solve_seed=501，不临时改评价协议")
    for key in ("search_seed","window_seconds"):
        if type(c[key]) is not int or c[key]<(0 if key=="search_seed" else 1):raise ValueError("非法整数参数："+key)
    if c["window_seconds"]>43200:raise ValueError("总时窗最多12小时")
    for key in ("reference_run","rule_manifest","rule_source"):
        c[key]=str((ROOT/c[key]).resolve())
        if not Path(c[key]).is_relative_to(ROOT):raise ValueError("本入口只读取当前工作区显式资产")
    reference=Path(c["reference_run"])
    if snapshot(reference,problem="fjsp")["phase"]!="completed":raise ValueError("common参照运行必须completed")
    prior=read(reference/"Protocol.json");manifest=read(c["rule_manifest"])
    pin=manifest["rules"]["canonical"]
    if sha(c["rule_source"])!=pin["sha256"] or pin["seed"]!=2026092002:
        raise ValueError("只复用与清单原始SHA完全匹配的canonical EoH规则，不重选seed")
    source=Path(c["rule_source"]).read_bytes()
    code=source.decode();candidate=Candidate("Frozen canonical EoH seed2026092002; original native source",code,pin["sha256"],"native-frozen-h")
    native_rule(asdict(candidate))  # compile only; no scheduling or scoring
    data_path=Path(prior["config"]["data_manifest"]);data=read(data_path)
    if sha(data_path)!=prior["input_provenance"]["data"]["sha256"] or data.get("split")!="train":
        raise ValueError("原train21清单身份变化")
    if len(data["instances"])!=21 or len(prior["instances"])!=21:raise ValueError("完整train21必需")
    refs={r["file"]:r["reference"] for r in prior["references"]};instances=[]
    for row,old in zip(data["instances"],prior["instances"]):
        path=(data_path.parent/row["path"]).resolve()
        if row["file"]!=old["file"] or sha(path)!=row["sha256"] or row["sha256"]!=old["source_sha256"]:
            raise ValueError("训练输入/顺序与common参照不一致")
        instance=load_instance(path);lb=lower_bound_v5(instance)
        if lb!=refs[row["file"]]:raise ValueError("未取整LB不一致")
        instances.append({"file":row["file"],"source":str(path),"sha256":row["sha256"],"LB":lb})
    provenance={"canonical_seed":pin["seed"],"original_source_sha256":pin["sha256"],
                "source_commit":manifest["source"]["commit"],"historical_experiment":manifest["experiment"],
                "notice":"Historical DeepSeek/40-candidate budget and validation-selected rule; quality reference, not fair search-cost comparison. Historical ceil-LB fitness is not reused."}
    return c,candidate,instances,provenance


def _physical(schedule):
    return {"makespan":schedule.makespan,"operations":sorted(
        [[o.job,o.operation,o.machine,o.start,o.end] for o in schedule.operations])}


def worker(pipe,payload,members,instances,names,allowed_modes):
    network={"network_attempted":False}
    def deny(*args,**kwargs):
        network["network_attempted"]=True
        raise PermissionError("offline frozen-rule worker network forbidden")
    socket.socket.connect=deny;socket.create_connection=deny
    expected=payload["files"]
    def attest():
        if any(sha(path)!=value for path,value in expected.items()):raise RuntimeError("frozen source/input changed")
    try:
        attest();rule=native_rule(payload["candidate"])
        for name,instance in zip(names,instances):
            calls=[0]
            def counted(*args):calls[0]+=1;return rule(*args)
            started=time.perf_counter();first=construct_schedule(instance,counted);first_seconds=time.perf_counter()-started
            first_calls=calls[0];calls[0]=0
            started=time.perf_counter();second=construct_schedule(instance,counted);second_seconds=time.perf_counter()-started
            if first!=second or first_calls!=calls[0]:raise ValueError("full native solve/recheck mismatch")
            physical=_physical(first);attest();lb=lower_bound_v5(instance)
            pipe.send({"file":name,"makespan":first.makespan,"lower_bound":lb,"score":-first.makespan/lb,
                       "feasible":True,"captured_solves":2,"single_solve_seconds":first_seconds,
                       "deterministic_recheck_seconds":second_seconds,"single_h_calls":[first_calls],
                       "recheck_h_calls":[calls[0]],"physical_schedule":physical,
                       "physical_schedule_sha256":digest(physical),"recheck_physical_schedule_sha256":digest(_physical(second)),
                       "commit_sequence_sha256":digest(asdict(first)),"network_guard":dict(network)})
    except BaseException as exc:pipe.send({"error_type":type(exc).__name__,"error":str(exc)[:500]})
    finally:pipe.close()


class Adapter:
    ROOT=ROOT
    read=staticmethod(read);write=staticmethod(write);sha=staticmethod(sha);digest=staticmethod(digest)

    def check_run(self,directory):
        p=read(directory/"Protocol.json")
        if p.get("version")!=VERSION or sha(directory/"Protocol.json")!=(directory/"Protocol.sha256").read_text().strip():
            raise ValueError("foreign/changed EoH protocol")
        if p["config"]["api_mode"]!="disabled" or p["budgets"]["logical_generation"]!=0:raise ValueError("API禁用身份变化")
        for path,value in p["files"].items():
            if sha(path)!=value:raise ValueError("冻结源码/输入改变，先核查，不重绑旧run："+path)
        if sha(directory/"Tasks.json")!=p["tasks_sha256"]:raise ValueError("fixed task changed")
        return p

    def members(self,directory):return []  # This task IS one native H, not a routed U over H10.

    def checked_candidate(self,value):
        native_rule(value)
        return Candidate(**value)

    def validate_result(self,result,instances):validate_result(result,instances,"modern")

    def evaluate(self,directory,state,p,candidate):
        folder=directory/"evaluations"/candidate.key
        if candidate.key in state["evaluations"]:raise ValueError("已预留的固定评价不自动重复")
        folder.mkdir(parents=True);state["evaluations"][candidate.key]={"status":"reserved"}
        write(directory/"checkpoint.json",state)
        instances=[load_instance(directory/r["relative_path"]) for r in p["instances"]]
        begun=time.monotonic()
        rows,failure,life=collect(mp.get_context("spawn"),worker,{"candidate":asdict(candidate),"files":p["files"]},
            [],instances,[r["file"] for r in p["instances"]],30,(),lambda r:write(folder/"lifecycle.json",r))
        if life["alive"] or not life["receiver_thread_stopped"]:raise RuntimeError("unknown worker terminal state")
        if failure and failure.get("error_type") in ("RuntimeError","WorkerExit"):raise RuntimeError(str(failure))
        if not failure and (life["exitcode"]!=0 or life["cleanup"]!=["join_exit_grace_2.0"]):raise RuntimeError("worker exit not certified")
        self.check_run(directory)
        result={"valid":failure is None,"fitness":fmean(r["score"] for r in rows) if failure is None else None,
                "instances":rows,"total_instances":len(instances),"primary_evaluation_seconds":time.monotonic()-begun,
                "lifecycle":life,**(failure or {})}
        self.validate_result(result,p["instances"]);write(folder/"result.json",result)
        state["evaluations"][candidate.key]={"status":"completed","path":str((folder/"result.json").relative_to(directory)),"sha256":sha(folder/"result.json")}
        write(directory/"checkpoint.json",state)
        return result,False

    def summary(self,directory,write_files=False):
        p=self.check_run(directory);s=read(directory/"checkpoint.json");result=None
        for value in s["evaluations"].values():
            if value["status"]=="completed":
                if sha(directory/value["path"])!=value["sha256"]:raise ValueError("saved result hash mismatch")
                result=read(directory/value["path"]);self.validate_result(result,p["instances"])
        facts={"phase":s["phase"],"completed_tasks":s["cursor"],"valid":result["valid"] if result else False,
               "fitness":result["fitness"] if result else None,"complete_instances":len(result["instances"]) if result else 0,
               "API_requests":0,"provenance":p["provenance"],"failure":result.get("error") if result else None}
        if write_files:
            write(directory/"results"/"Summary.json",facts)
            columns=["file","makespan","lower_bound","score","feasible","captured_solves","single_solve_seconds","deterministic_recheck_seconds"]
            with (directory/"results"/"Per_instance.csv").open("w",newline="") as f:
                w=csv.DictWriter(f,fieldnames=columns,extrasaction="ignore");w.writeheader();w.writerows(result["instances"] if result else [])
        return facts


def prepare(directory,parameters,entry):
    c,candidate,instances,provenance=preflight(parameters)
    if directory.exists() or directory.parent!=ROOT/"runs":raise ValueError("需要全新runs直接子目录")
    directory.mkdir();(directory/"inputs").mkdir()
    files={str(ROOT/name):value for name,value in evolution_v1.source_identity().items()}
    files[str(Path(__file__).resolve())]=sha(Path(__file__))
    for key in ("rule_manifest","rule_source"):files[c[key]]=sha(c[key])
    ref=Path(c["reference_run"])/"Protocol.json";files[str(ref)]=sha(ref)
    for row in instances:
        target=directory/"inputs"/row["file"];target.write_bytes(Path(row["source"]).read_bytes())
        row["relative_path"]=str(target.relative_to(directory));files[str(target)]=row["sha256"]
    (directory/"Frozen_native_rule.py").write_text(candidate.code)
    (directory/"Launcher_snapshot.py").write_bytes(Path(entry).read_bytes())
    for path in (directory/"Frozen_native_rule.py",directory/"Launcher_snapshot.py"):
        files[str(path)]=sha(path)
    write(directory/"Tasks.json",[{"id":"EOH_CANONICAL_seed2026092002","stage":"fixed","candidate":asdict(candidate)}])
    p={"version":VERSION,"config":{**c,"type":"fixed"},"instances":instances,"files":files,"provenance":provenance,
       "tasks_sha256":sha(directory/"Tasks.json"),"budgets":{"logical_generation":0,"API_attempts":0,"max_program_instances":21,"max_solve_passes":42}}
    write(directory/"Protocol.json",p);(directory/"Protocol.sha256").write_text(sha(directory/"Protocol.json")+"\n")
    write(directory/"checkpoint.json",{"identity":sha(directory/"Protocol.json"),"phase":"prepared","cursor":0,
        "tasks":{},"evaluations":{},"population":[],"children":[],"seen":{},"generation":0,"pause_ack":0})
    return p
