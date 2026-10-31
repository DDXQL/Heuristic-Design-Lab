"""Real-search thin entry: validation and receipts around unchanged common engine."""
import json
import os
from pathlib import Path
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import uuid4
from contextlib import redirect_stdout,redirect_stderr

from heuristic_design.core import evolution_v1 as engine
from heuristic_design.core.evolution_export import export
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.core.terminal_ops import inputs
from heuristic_design.problems.routing_fixtures import compile_members,precheck_instances
from fjsp_usage.research_real.assets import check_seal
from experiments.common._single_run import _Tee
from experiments.common._search_reports import protocol_state,evidence,finish
import sys

FIELDS={"problem","state_schema","api_mode","evaluation_mode","initialization","population_size","generations",
        "search_seed","solve_seed","initialization_candidate_cap","initialization_request_cap","generation_request_cap",
        "api_attempt_cap","api_concurrency","evaluation_concurrency","instance_timeout_seconds","window","enabled_groups",
        "h_file","data_manifest","p0_file","provider","real_requests_authorized"}
RECORDING_FIELDS={"recording_mode","milestone_generations","survival_policy"}
RECORDING_CHANGES={"code/heuristic_design/core/evolution_v1.py","code/heuristic_design/core/routing_evaluation.py",
                   "code/heuristic_design/problems/routing_fixtures.py","code/heuristic_design/problems/fjsp/routing.py"}
COMPAT={"problem","state_schema","api_mode","evaluation_mode","initialization","solve_seed","api_concurrency",
        "evaluation_concurrency","instance_timeout_seconds","window","enabled_groups","provider"}


def preflight(parameters,*,root,stage,run_root,min_free_gib,r1_runs,pilot_run,authorization_file=None,r3_compatibility_file=None):
    if not isinstance(parameters,dict) or not FIELDS<=set(parameters) or set(parameters)-FIELDS-RECORDING_FIELDS:
        raise ValueError("真实入口参数存在未知或缺失字段")
    if stage not in ("r3","b1"):raise ValueError("未知阶段")
    c=dict(parameters)
    if (c["problem"]!="fjsp" or c["api_mode"]!="real" or c["evaluation_mode"]!="solve"
        or c["initialization"]!="llm" or c["p0_file"] is not None):raise ValueError("本入口要求真实LLM初始化/纯路由演化及真实求解")
    for key in ("h_file","data_manifest"):
        if not isinstance(c[key],(str,Path)) or not str(c[key]):raise ValueError("必须显式指定正式输入")
        c[key]=str((root/c[key]).resolve())
    c=engine.config(c)
    if c["generations"]<1 or min(c["initialization_candidate_cap"],c["initialization_request_cap"])<c["population_size"]:
        raise ValueError("必须有演化代及足够初始化上限")
    h=check_seal(read(c["h_file"]),kind="H_frozen",mode="real");members,data,origin=inputs(c)
    if (len(members)!=10 or len(data)!=21 or [r.get("member_id") for r in h["members"]]!=list(range(10))
        or h["training_files"]!=[r["file"] for r in data] or any(r["split"]!="train" for r in data)):
        raise ValueError("必须使用原顺序冻结10H和完整train21")
    compile_members("fjsp",members);precheck_instances("fjsp",data)
    receipts={};sizes=[]
    for kind,count in (("common",12),("legacy",2),("eoh",1)):
        directory=(root/r1_runs[kind]).resolve();p,s=protocol_state(directory)
        if s["phase"]!="completed" or len(s["tasks"])!=count or not all(r["valid"] for r in s["tasks"].values()):
            raise ValueError("R1尚未完整有效："+kind)
        expected=[(r["file"],r["source_sha256"]) for r in data]
        actual=[(r["file"],r.get("source_sha256",r.get("sha256"))) for r in p["instances"]]
        if actual!=expected:raise ValueError("R1与新搜索数据身份不同")
        if kind=="common" and p["input_provenance"]["H"]["sha256"]!=origin["H"]["sha256"]:
            raise ValueError("R1与搜索H身份不同")
        if kind=="common":
            for task in s["tasks"].values():
                ev=s["evaluations"].get(task.get("candidate",{}).get("key"))
                if ev:
                    paths=[directory/ev["path"],directory/"worker-receipts"/task["id"]/"result.json"]
                    sizes.append(sum(x.stat().st_size for x in paths if x.exists())/2**30)
        receipts[kind]={"directory":str(directory),"protocol_sha256":sha(directory/"Protocol.json"),"checkpoint_sha256":sha(directory/"checkpoint.json")}
    if min_free_gib is not None and (type(min_free_gib) not in (int,float) or min_free_gib<=0):
        raise ValueError("磁盘保留量必须为正数或None（仅观察）")
    run_root=(root/run_root).resolve();parent=run_root
    while not parent.exists():parent=parent.parent
    free=shutil.disk_usage(parent).free/2**30;blocking=[]
    eval_cap=min(c["initialization_candidate_cap"],c["initialization_request_cap"])+2*c["population_size"]*c["generations"]
    compact=c['recording_mode']=='compact'
    estimate=10 if compact else sum(sizes)/len(sizes)*eval_cap
    required=None if min_free_gib is None else (min_free_gib if compact else max(min_free_gib,max(sizes)*eval_cap+5))
    if required is not None and free<required:blocking.append(f"磁盘可用{free:.2f} GiB，本次预留要求{required:.2f} GiB；可清理自行确认的文件或修改RUN_ROOT为外置目录")
    if stage=="b1":
        if not pilot_run:blocking.append("先指定通过线上验收的R3_RUN_DIR")
        else:
            directory=(root/pilot_run).resolve();p,s=protocol_state(directory);proof=evidence(directory)
            if not proof["passed"]:blocking.append("R3尚未通过真实并发/传输验收")
            compatible=p['source_files']==engine.source_identity()
            if not compatible and r3_compatibility_file:
                path=(root/r3_compatibility_file).resolve();bridge=read(path)
                changed={k for k in p['source_files'].keys()|engine.source_identity().keys()
                         if p['source_files'].get(k)!=engine.source_identity().get(k)}
                proof_path=root/bridge['verification_path']
                compatible=(bridge['r3_protocol_sha256']==sha(directory/'Protocol.json')
                    and bridge['before']==p['source_files'] and bridge['after']==engine.source_identity()
                    and set(bridge['changed_paths'])==changed and changed<=RECORDING_CHANGES
                    and sha(proof_path)==bridge['verification_sha256'] and read(proof_path)['passed'] is True)
                receipts['recording_compatibility']={'path':str(path),'sha256':sha(path),'compatible':compatible}
            if any(p["config"][key]!=c[key] for key in COMPAT) or not compatible:
                blocking.append("R3与正式搜索的模型/协议/并发/状态/源码身份不兼容")
            if (p["input_provenance"]["H"]["sha256"]!=origin["H"]["sha256"]
                or p["input_provenance"]["data"]["sha256"]!=origin["data"]["sha256"]):blocking.append("R3与正式输入身份不同")
            receipts["r3"]={"directory":str(directory),"protocol_sha256":sha(directory/"Protocol.json")}
        from experiments.common._search_reports import baseline_bundle
        receipts['baselines']=baseline_bundle(root,r1_runs,data,members,c)
    authorization=None
    if c["real_requests_authorized"]:
        if not authorization_file:blocking.append("尚无本批明确授权记录")
        else:
            path=(root/authorization_file).resolve();authorization=read(path)
            if (authorization.get("stage")!=stage or authorization.get("config_sha256")!=digest(c)
                or authorization.get("max_attempts")!=c["api_attempt_cap"]
                or authorization.get("source_files")!=engine.source_identity()):
                raise PermissionError("当前参数不在已授权批次范围内")
            if stage=='b1' and authorization.get('status')!='approved':blocking.append('1050次正式预算尚未明确批准')
            claim=path.with_suffix(".claim.json")
            if claim.exists():blocking.append("该授权已绑定运行，先status核查，勿普通启动另一批："+str(read(claim)["run_directory"]))
            receipts["authorization"]={"path":str(path),"sha256":sha(path),"claim_path":str(claim)}
    plan={"stage":stage,"N":c["population_size"],"G":c["generations"],"H":10,"train_instances":21,
        "initialization_attempt_cap":c["initialization_request_cap"],"planned_evolution_requests":2*c["population_size"]*c["generations"],
        "evolution_request_cap":c["generation_request_cap"],"total_attempt_cap":c["api_attempt_cap"],
        "max_solve_passes":2*21*(min(c["initialization_candidate_cap"],c["initialization_request_cap"])+2*c["population_size"]*c["generations"]),
        "model":c["provider"]["model"],"endpoint":c["provider"]["endpoint"],
        "api_concurrency":c["api_concurrency"],"evaluation_concurrency":c["evaluation_concurrency"],
        "credential_env":c["provider"]["api_key_env"],"credential_present":c["provider"]["api_key_env"] in os.environ,
        "real_requests_authorized":c["real_requests_authorized"],"free_GiB":free,"minimum_free_GiB":min_free_gib,
        "storage_allowance_GiB":estimate,"required_free_GiB":required,"disk_space_gate_enabled":required is not None,"recording_mode":c['recording_mode'],
        "storage_note":"compact: conservative 10 GiB experiment allowance, not measured final size" if compact else "full: extrapolated R1 size",
        "milestone_generations":c['milestone_generations'],
        "paid_start_blockers":([] if c['real_requests_authorized'] else [f"真实请求开关关闭；本轮{c['api_attempt_cap']}次预算待批准"])
            +([] if c['provider']['api_key_env'] in os.environ else ['运行终端须提供凭据环境变量']),
        "authorized_config_sha256":digest({**c,'real_requests_authorized':True}),
        "blocking":blocking,"network_requests_sent":0,"solves":0,"mode":"bounded generation batch, then bounded evaluation batch"}
    return c,plan,receipts


def launch(parameters,*,root,stage,run_root,prefix,min_free_gib,r1_runs,pilot_run,entry,check_only=False,authorization_file=None,r3_compatibility_file=None):
    c,plan,receipts=preflight(parameters,root=root,stage=stage,run_root=run_root,min_free_gib=min_free_gib,r1_runs=r1_runs,pilot_run=pilot_run,authorization_file=authorization_file,r3_compatibility_file=r3_compatibility_file)
    if not isinstance(prefix,str) or not prefix or "/" in prefix or "\\" in prefix or prefix in (".",".."):raise ValueError("非法运行目录前缀")
    print(json.dumps(plan,ensure_ascii=False,indent=2))
    if check_only:return 2 if plan["blocking"] else 0
    if plan["blocking"]:raise ValueError("；".join(plan["blocking"]))
    if not c["real_requests_authorized"]:raise PermissionError("真实请求仍关闭；需明确预算授权后再启用顶部开关")
    if not plan["credential_present"]:raise ValueError("凭据环境变量不存在："+plan["credential_env"])
    stamp=datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y%m%d-%H%M%S-%f")
    directory=(root/run_root).resolve()/f"{prefix}-{stamp}-{uuid4().hex[:8]}"
    claim=Path(receipts["authorization"]["claim_path"])
    with claim.open("x") as stream:
        json.dump({"run_directory":str(directory),"config_sha256":digest(c),"max_attempts":c["api_attempt_cap"],
                   "notice":"single approved batch; no automatic release, rerun or budget reset"},stream,ensure_ascii=False,indent=2)
    prepared=engine.prepare(directory,c);folder=directory/"launch";folder.mkdir()
    for path in (Path(entry).resolve(),Path(__file__).resolve(),Path(__file__).with_name("_search_reports.py")):
        (folder/path.name).write_bytes(path.read_bytes())
    write(folder/"parameters.json",c);write(folder/"prerequisites.json",receipts);write(folder/"plan.json",plan)
    if stage=='b1':
        write(folder/'baselines.json',receipts['baselines'])
        write(folder/'postprocess.receipt.json',{'baselines_sha256':sha(folder/'baselines.json'),
              'helper_sha256':sha(folder/'_search_reports.py')})
    try:
        with (directory/"terminal.log").open("x") as log,redirect_stdout(_Tee(sys.stdout,log)),redirect_stderr(_Tee(sys.stderr,log)):
            print(json.dumps({"prepared":prepared,"plan":plan},ensure_ascii=False,indent=2))
            try:
                result=engine.run(directory,allow_api=True)
                if result["phase"] not in ("completed","paused","initialization_incomplete"):raise RuntimeError("未知/异常运行状态，保留锁核查")
                summary=export(directory);proof=finish(directory,summary)
                print(json.dumps({"phase":summary["phase"],"completed_generations":summary["generation"],
                    "valid_candidates":summary["valid_unique_evaluations"],"failed_or_duplicate":summary["failed_or_duplicate_tasks"],
                    "requests_sent_confirmed":proof["sent_confirmed"],"input_tokens_known":proof["known_input_tokens"],
                    "output_tokens_known":proof["known_output_tokens"],"unknown_usage_sent":proof["unknown_usage_sent"],
                    "online_acceptance_passed":proof["passed"],"validation_status":"not_run"},ensure_ascii=False,indent=2))
                return 0 if summary["phase"]=="completed" and (stage!="r3" or proof["passed"]) else 2
            except BaseException as exc:
                print(f"运行停止：{type(exc).__name__}: {exc}；保留原目录/锁/预算，不重试。",file=sys.stderr);raise
    finally:print(f"运行目录：{directory}\n日志：{directory/'terminal.log'}\n结果：{directory/'exports'}")


def existing(directory,*,root,resume=False,before_evolution=None):
    """Auxiliary resume/export: use frozen run parameters and archived reporter."""
    import importlib.util
    directory=(root/directory).resolve();p,s=engine.check(directory)
    folder=directory/'launch';receipt=read(folder/'postprocess.receipt.json')
    helper=folder/'_search_reports.py'
    if sha(helper)!=receipt['helper_sha256']:raise ValueError('冻结导出实现身份改变')
    if sha(folder/'baselines.json')!=receipt['baselines_sha256']:raise ValueError('冻结基线结果改变')
    spec=importlib.util.spec_from_file_location('_frozen_b1_reports',helper)
    reporter=importlib.util.module_from_spec(spec);spec.loader.exec_module(reporter)
    with (directory/'terminal.log').open('a') as log,redirect_stdout(_Tee(sys.stdout,log)),redirect_stderr(_Tee(sys.stderr,log)):
        if resume:
            if s['phase']!='paused':raise ValueError('只有安全paused可恢复；completed不得resume；未知锁/在途先核查')
            result=engine.run(directory,allow_api=True,before_evolution=before_evolution)
            if result['phase']=='blocked':
                print(json.dumps({'phase':'blocked','generation':result['generation'],
                                  'notice':'Stopped; inspect checkpoint and pre-evolution gate receipt. No automatic retry.'}))
                return 2
        summary=export(directory);reporter.finish(directory,summary)
        print(json.dumps({'phase':summary['phase'],'completed_generations':summary['generation'],
                          'result_directory':str(directory/'exports')},ensure_ascii=False,indent=2))
    return 0 if not resume or summary['phase']=='completed' else 2
