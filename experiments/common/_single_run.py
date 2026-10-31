"""Thin R1 orchestration. Existing engine owns solving, pools and recovery."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

from heuristic_design.core import evolution_v1 as engine
from heuristic_design.core.evolution_export import export
from heuristic_design.core.routing import checked
from heuristic_design.core.storage import read, sha, write
from heuristic_design.core.terminal_ops import inputs
from heuristic_design.problems.routing_fixtures import compile_members, precheck_instances
from fjsp_usage.research_real.assets import check_seal

FIELDS = {
    "problem", "state_schema", "h_file", "data_manifest", "p0_file", "population_size",
    "search_seed", "solve_seed", "window", "enabled_groups", "evaluation_concurrency",
    "api_concurrency", "instance_timeout_seconds", "api_mode", "evaluation_mode",
    "initialization", "generations", "generation_request_cap", "api_attempt_cap",
    "real_requests_authorized",
}
FORCED = {"problem":"fjsp", "state_schema":"constructive-common-v1-fjsp",
          "api_mode":"fixed", "evaluation_mode":"solve", "initialization":"import",
          "generations":0, "generation_request_cap":0, "api_attempt_cap":0,
          "real_requests_authorized":False}


def preflight(parameters, root, expected_h, expected_train):
    if not isinstance(parameters, dict) or set(parameters) != FIELDS:
        raise ValueError(f"参数键必须完整匹配；未知={set(parameters)-FIELDS if isinstance(parameters,dict) else '?'}；"
                         f"缺少={FIELDS-set(parameters) if isinstance(parameters,dict) else '?'}")
    for key, value in FORCED.items():
        if type(parameters[key]) is not type(value) or parameters[key] != value:
            raise ValueError(f"R1强制 {key}={value!r}，不允许模型生成或API预算")
    for value in (expected_h, expected_train):
        if type(value) is not int or value < 1:
            raise ValueError("预期H数量和训练实例数必须是正整数")
    c = dict(parameters)
    for key in ("h_file", "data_manifest", "p0_file"):
        if not isinstance(c[key], (str, Path)) or not str(c[key]):
            raise ValueError(f"{key}必须指定显式输入文件，不能回退到默认fixture")
        c[key] = str((Path(root) / c[key]).resolve())
    # Import mode does not send initialization requests; its item bound equals N.
    c = engine.config({**c, "initialization_candidate_cap":c["population_size"],
                       "initialization_request_cap":c["population_size"]})
    h = check_seal(read(c["h_file"]), kind="H_frozen", mode="real")
    members, data, _ = inputs(c)
    if len(members) != expected_h or len(data) != expected_train:
        raise ValueError("H/训练实例数量与顶部预期不一致")
    if ([r.get("member_id") for r in h["members"]] != list(range(expected_h))
            or h.get("training_files") != [r["file"] for r in data]
            or any(r["split"] != "train" for r in data)):
        raise ValueError("必须保持冻结H编号、原训练顺序和train用途，不能换成开发/留出数据")
    compile_members(c["problem"], members)
    precheck_instances(c["problem"], data)
    p0 = read(c["p0_file"])
    if not isinstance(p0, list) or len(p0) != c["population_size"]:
        raise ValueError("P0必须是恰好population_size条固定候选的列表")
    for row in p0:
        if not isinstance(row, dict) or not isinstance(row.get("source"), str) or not row["source"].strip():
            raise ValueError("每个固定候选必须有非空source")
    keys = [checked(row["candidate"], len(members)).key for row in p0]
    if len(set(keys)) != len(keys):
        raise ValueError("固定P0存在重复AST，拒绝启动")
    count = len(p0) * len(data)
    plan = {"mode":"R1_FIXED_TRAIN_REAL_SOLVES", "candidates":len(p0), "H_count":len(members),
            "train_instances":len(data), "planned_program_instances":count,
            "max_solve_passes":2*count, "API_requests":0, "API_cost":0,
            "evaluation_concurrency":c["evaluation_concurrency"],
            "api_concurrency_registered":c["api_concurrency"],
            "timeout":"T30 complete solve/recheck row; candidate worker exit grace 2s"}
    return c, plan


class _Tee:
    def __init__(self, console, log):
        self.console, self.log = console, log

    def write(self, text):
        self.console.write(text)
        self.log.write(text)
        self.flush()
        return len(text)

    def flush(self):
        self.console.flush()
        self.log.flush()


def launch_r1(parameters, *, root, run_root, prefix, name, entry,
              expected_h=10, expected_train=21, check_only=False):
    c, plan = preflight(parameters, root, expected_h, expected_train)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    for value in (prefix, name):
        if value is not None and (not isinstance(value, str) or not value
                                  or value in (".", "..") or "/" in value or "\\" in value):
            raise ValueError("RUN_PREFIX/RUN_NAME必须是单个目录名称")
    if prefix is None:
        raise ValueError("RUN_PREFIX不能为空")
    run_root = (Path(root) / run_root).resolve()
    if name is not None and (run_root / name).exists():
        raise FileExistsError("已有运行目录，普通启动不会覆盖或恢复："+str(run_root/name))
    if check_only:
        print("检查通过：未创建运行、未求解、未请求API。")
        return 0
    stamp = datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y%m%d-%H%M%S-%f")
    directory = run_root / (name if name is not None else f"{prefix}-{stamp}-{uuid4().hex[:8]}")
    # prepare exclusively creates a new directory. No resume or lock handling here.
    prepared = engine.prepare(directory, c)
    launch = directory / "launch"
    launch.mkdir()
    entry = Path(entry).resolve()
    for source in (entry, Path(__file__).resolve()):
        (launch/source.name).write_bytes(source.read_bytes())
    write(launch/"parameters.json", c)
    write(launch/"receipt.json", {"git_commit":subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "entry_sha256":sha(entry), "shared_entry_sha256":sha(Path(__file__)),
        "parameters_sha256":sha(launch/"parameters.json"), "protocol_sha256":prepared["protocol"],
        "plan":plan, "notice":"恢复使用原Protocol.json和现有CLI，不读取修改后的入口参数"})
    log_path = directory / "terminal.log"
    try:
        with log_path.open("x") as log, redirect_stdout(_Tee(sys.stdout, log)), \
                redirect_stderr(_Tee(sys.stderr, log)):
            print(json.dumps({"plan":plan, "prepared":prepared}, ensure_ascii=False, indent=2))
            try:
                result = engine.run(directory, allow_api=False)
                if result["phase"] not in ("completed", "paused", "initialization_incomplete"):
                    raise RuntimeError("运行未安全收尾，先核查status和锁，不自动导出/恢复")
                summary = export(directory)
                print(json.dumps({"phase":summary["phase"],
                    "valid_candidates":summary["valid_unique_evaluations"],
                    "failed_or_duplicate_tasks":summary["failed_or_duplicate_tasks"],
                    "real_API_calls":summary["real_API_calls"]}, ensure_ascii=False, indent=2))
                return 0 if (summary["phase"] == "completed"
                    and summary["valid_unique_evaluations"] == c["population_size"]
                    and summary["failed_or_duplicate_tasks"] == 0) else 2
            except BaseException as exc:
                print(f"运行停止：{type(exc).__name__}: {exc}；保留原目录、日志和锁，使用现有status核查。", file=sys.stderr)
                raise
    finally:
        print(f"运行目录：{directory}\n日志：{log_path}\n结果：{directory/'exports'}")
