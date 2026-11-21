#!/usr/bin/env python3
"""Prepare, launch and inspect an independent R15 experiment from one JSON file."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "code"), str(ROOT)]

from heuristic_design.core import state_a_v3
from heuristic_design.core.storage import digest, read, sha, write
from experiments.triad import campaign, candidate_policy, configuration, parallel, shared_admission, six_ops
from experiments.triad.concurrency_probe import claim
from experiments.triad.batch_admission import WIDTHS


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, low, high, name):
    require(type(value) is int and low <= value <= high, f"{name} 需要 {low} 到 {high} 的整数")


def fields(value, expected, name, optional=""):
    require(isinstance(value, dict), f"{name} 需要 JSON 对象")
    unknown = set(value) - set(expected.split()) - set(optional.split())
    missing = set(expected.split()) - set(value)
    require(not unknown and not missing, f"{name} 缺少 {sorted(missing)}，额外字段 {sorted(unknown)}")


def load_document(path):
    doc = read(path)
    fields(doc, "version name research execution", "配置")
    integer(doc["version"], 1, 1, "version")
    name = doc["name"]
    require(isinstance(name, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", name),
            "name 需要 1 到 40 个小写字母、数字或连字符，首位须为字母或数字")
    return doc, ROOT / "plans" / ("candidate-lab-" + name)


def settings(doc):
    research, execution = doc["research"], doc["execution"]
    fields(research, "problem runs training_manifest frozen_h reference state evaluation champion holdout budget decision", "research")
    fields(execution, "mode slurm api window_hours max_segments", "execution", "exclusive_hours release_account_when_done")
    slurm, api, budget = execution["slurm"], execution["api"], research["budget"]
    fields(slurm, "partition account qos cpus memory_mib wall_seconds", "execution.slurm", "evaluation_concurrency")
    fields(api, "global_concurrency min_interval_seconds queue_wait_seconds timeout_seconds evolution_reservation_cap retry_delays_seconds consecutive_failed_slots cooldown_429_seconds", "execution.api", "requests_per_minute model retry_explicit_429")
    fields(budget, "count target empty truncated", "research.budget")
    problem = research["problem"]
    require(problem in ("fjsp", "tsp", "obp"), "problem 可选 fjsp、tsp、obp")
    require(execution["mode"] in ("real", "mock"), "mode 可选 real、mock")
    real = execution["mode"] == "real"
    require(budget["count"] == "successful_responses",
            "R15 使用成功返回口径。历史尝试口径请使用对应冻结版本")
    integer(budget["target"], 1000 if real else 1, 1000, "research.budget.target")
    require(research["state"] == state_a_v3.VERSION and research["evaluation"] == "train_J_min_T30"
            and research["champion"] == "best_valid_training_J_then_id" and research["holdout"] == "not_run",
            "研究入口目前支持共同状态 A v3、训练 J/T30、有效候选按 J 与 ID 选优，训练外评价独立进行")
    require(not real or isinstance(research["decision"], str) and research["decision"].strip(),
            "真实搜索需要填写 research.decision，记录本批采用的研究协议")
    runs = research["runs"]
    require(isinstance(runs, list) and 1 <= len(runs) <= 3, "每批填写 1 到 3 个方法和种子的组合")
    seen = set()
    for row in runs:
        fields(row, "method seed initialization_attempts", "research.runs")
        require(row["method"] in ("u", "eoh"),
                "搜索入口支持 u、eoh。固定 H 参照使用 assets.py，其他基准的接入状态见 PROJECT_MAP.md")
        integer(row["seed"], 0, 2**32 - 1, "seed")
        integer(row["initialization_attempts"], 2, 1000, "initialization_attempts")
        identity = (row["method"], row["seed"])
        require(identity not in seen, "每个方法和种子的组合必须唯一")
        seen.add(identity)
    for key in ("partition", "account", "qos"):
        value = slurm[key]
        require(key != "partition" and value is None or isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_-]+", value),
                f"Slurm {key} 需要有效名称")
    integer(slurm["cpus"], 2, 128, "Slurm cpus")
    integer(slurm["memory_mib"], 128, 2**20, "Slurm memory_mib")
    integer(slurm["wall_seconds"], 60, 604800, "Slurm wall_seconds")
    integer(execution["window_hours"], 1, 144, "window_hours")
    integer(execution["max_segments"], 1, campaign.MAX_SEGMENTS, "max_segments")
    require(type(api["global_concurrency"]) is int and api["global_concurrency"] in WIDTHS, "API 总并发可选 1、2、4、8")
    if api.get("requests_per_minute") is not None:
        integer(api["requests_per_minute"], 1, 100000, "requests_per_minute")
    require(slurm.get("evaluation_concurrency", 1) == 1, "当前 R15 适配器保留每个种子串行 CPU 评价")
    require(api.get("retry_explicit_429", False) is False, "新批次的 429 退避后开新槽，原槽不重试")
    integer(api["min_interval_seconds"], 0, 60, "API 发送间隔")
    integer(api["queue_wait_seconds"], 1, 600, "API 排队等待")
    require(isinstance(api["retry_delays_seconds"], list), "retry_delays_seconds 需要数组")
    policy = {"version": candidate_policy.VERSION, "adoption": "adopted" if real else "draft",
              "research_record": research["decision"], "empty": budget["empty"], "truncated": budget["truncated"],
              "evolution_attempt_cap": api["evolution_reservation_cap"],
              "per_slot_attempt_cap": 1 + len(api["retry_delays_seconds"]),
              "backoff_seconds": api["retry_delays_seconds"], "failure_streak_limit": api["consecutive_failed_slots"],
              "retry_explicit_429": api.get("retry_explicit_429", False), "rate_limit_backoff_seconds": api["cooldown_429_seconds"]}
    candidate_policy.validate(policy, budget["target"], real=real)
    return policy


def asset(path):
    if path is None:
        return None
    require(isinstance(path, str) and path.strip(), "资产需要文件路径或 null")
    return str((ROOT / path).resolve())


def member(doc, item, policy):
    research, rules = doc["research"], doc["execution"]
    group = research["problem"] + "-" + item["method"]
    c = six_ops.config(group)
    require(rules["api"].get("model", c["provider"]["model"]) == c["provider"]["model"],
            "模型身份与冻结配置不符。当前入口只使用资产绑定的模型")
    pending = []
    if c["freeze_status"] == "pending":
        pending.append("缺少该组已采用的原始研究配置")
    c.update(mode=rules["mode"], repeat_count=1, search_seed=item["seed"], search_seeds=[item["seed"]],
             candidate_policy=policy, initialization_request_cap=item["initialization_attempts"],
             evolution_request_cap=research["budget"]["target"],
             api_attempt_cap=item["initialization_attempts"] + policy["evolution_attempt_cap"],
             per_candidate_attempt_cap=policy["per_slot_attempt_cap"], window_seconds=rules["window_hours"] * 3600)
    if c["mode"] == "mock":
        c.update(freeze_status="engineering_only", credential_file=None)
    for key, name in (("data_manifest", "training_manifest"), ("reference_file", "reference"), ("h_file", "frozen_h")):
        if research[name] is not None:
            c[key] = asset(research[name])
    if c["problem"] == "tsp" and c["reference_file"] is None:
        reference = ROOT / "preparations/operations/tsp-reference-r15.json"
        if reference.is_file():
            c["reference_file"] = str(reference)
    if c["method"] != "u":
        c["h_file"] = None
    c["evaluation_concurrency"] = 1
    if c["data_manifest"] and Path(c["data_manifest"]).is_file():
        c["instance_count"] = len(read(c["data_manifest"])["instances"])
    r, slurm, api = c["resources"], rules["slurm"], rules["api"]
    r.update({k: slurm[k] for k in ("partition", "account", "qos", "cpus", "memory_mib")})
    integer(api["timeout_seconds"], c["provider"]["connect_timeout"], c["provider"]["total_timeout"], "API timeout_seconds")
    r.update(segment_seconds=slurm["wall_seconds"], http_timeout_seconds=api["timeout_seconds"],
             request_queue_seconds=api["queue_wait_seconds"])
    r["drain_seconds"] = max(r["drain_seconds"], configuration.candidate_drain(c, api["queue_wait_seconds"]))
    require(min(c["window_seconds"], r["segment_seconds"]) > r["drain_seconds"],
            f"{group} 时限必须大于 {r['drain_seconds']} 秒的安全收尾时间")
    require(c["population_size"] is None or item["initialization_attempts"] >= c["population_size"],
            f"{group} 初始化上限小于种群大小 {c['population_size']}")
    pending.extend(k for k in configuration.gaps(c) if k not in ("account_exclusion", "credential_file"))
    assets = {}
    for key in ("data_manifest", "reference_file", "h_file"):
        if path := c[key]:
            if Path(path).is_file():
                assets[key] = {"path": path, "sha256": sha(path)}
            else:
                pending.append("文件不存在 " + path)
    if c["problem"] == "tsp" and not c["reference_file"]:
        pending.append("需要已核验的 LKH train20 参照，可在 research.reference 指定")
    if c["problem"] == "obp" and c["method"] == "u" and not c["h_file"]:
        pending.append("需要真实 H401 筛选并冻结的 10H 文件")
    if not pending:
        _, _, members = six_ops.runtime.problems.load_inputs(c)
        if c["mode"] == "real" and c["method"] == "u":
            require(len(members) == 10, "本研究的冻结 H 集合需要 10 条成员")
        if c["mode"] == "real" and c["problem"] == "tsp":
            ref = read(c["reference_file"])
            d06 = read(ROOT / "experiments/triad/lkh.pending.json")
            require(ref["lkh_identity"]["version"] == d06["version"]
                    and ref["parameters"] == {k: d06[k] for k in ("runs", "max_trials", "seed", "integer_scale")},
                    "TSP 参照版本或参数与 D06 不符")
    return c, {"group": group, "seed": item["seed"], "pending": sorted(set(pending)),
               "budget": configuration.budget(c), "drain_seconds": r["drain_seconds"], "assets": assets}


def fixed_plan(doc, output):
    from experiments.triad import assets

    require(doc["execution"]["mode"] == "real", "正式固定 H 需要核验后冻结的资产")
    policy = settings(doc)
    c, info = member(doc, {"method": "u", "seed": doc["research"]["runs"][0]["seed"],
                           "initialization_attempts": 20}, policy)
    if info["pending"]:
        return {"problem": c["problem"], "pending": info["pending"], "API_requests": 0, "actual_solves": 0}
    result = assets.fixed_plan(c)
    if c["problem"] == "fjsp" and result["compatible_reuse"] is None:
        result["pending"] = ["需要已核验的 FJSP 10H×train21 固定 H 原始成本及兼容回执"]
    else:
        result["pending"] = []
    if output is not None:
        claim(output, c)
        result["asset_config"] = str(output.resolve())
    return result


def prepare(doc):
    policy = settings(doc)
    members = [member(doc, item, policy) for item in doc["research"]["runs"]]
    rows = [row for _, row in members]
    return members, {"name": doc["name"], "mode": doc["execution"]["mode"], "members": rows,
                     "execution": doc["execution"],
                     "ready_for_submission_checks": all(not row["pending"] for row in rows),
                     "total_request_reservation_cap": sum(row["budget"]["request_cap_per_seed"] for row in rows),
                     "global_API_width": doc["execution"]["api"]["global_concurrency"],
                     "effective_max_requests": min(len(rows), doc["execution"]["api"]["global_concurrency"]),
                     "submitted": False, "API_requests": 0, "actual_solves": 0}


def run(doc, folder, approve):
    members, preview = prepare(doc)
    if not approve:
        return {**preview, "next": "核对配置及上限后在集群上运行 run --approve"}
    require(preview["ready_for_submission_checks"], "还有未满足的研究配置或资产，请先查看 prepare")
    require(all(shutil.which(command) for command in ("sbatch", "sacct", "squeue", "srun", "scontrol")),
            "请在 Slurm 集群终端启动。Mac 可编辑配置和执行 prepare")
    require(not folder.exists(), "批次名称已使用，请运行 status。新批次使用新的 name")
    rules = doc["execution"]
    gate = folder / shared_admission.BATCH_GATE_DIR
    first = members[0][0]
    if rules["mode"] == "real":
        credential = Path(first["credential_file"])
        require(credential.is_file(), "集群凭据文件缺失，请先配置已有账户的本地凭据")
        meta = credential.lstat()
        require(stat.S_ISREG(meta.st_mode) and stat.S_IMODE(meta.st_mode) == 0o600 and meta.st_uid == os.getuid(),
                "已有凭据须由当前用户拥有、权限 0600，且为普通文件")
    inputs = folder.parent / (folder.name + "-inputs")
    # Exclusive batch-name claim before writing any plan inputs. Failed/unknown
    # submissions keep their original identity and receipts for status.
    claim(inputs / "request.json", {"config_digest": digest(doc), "config": doc, "preview": preview})
    rows = []
    for index, (config, row) in enumerate(members):
        config_path = inputs / f"member-{index}.json"
        write(config_path, config)
        rows.append({"group": row["group"], "seed": row["seed"], "config": str(config_path)})
    spec = inputs / "spec.json"
    write(spec, {"batch_id": folder.name, "mode": rules["mode"], "members": rows,
                 "runtime_policy": shared_admission.INDEPENDENT, "candidate_policy": first["candidate_policy"],
                 "global_API_width": rules["api"]["global_concurrency"],
                 "requests_per_minute": rules["api"].get("requests_per_minute"),
                 "account_gate": str(gate), "min_request_interval_seconds": rules["api"]["min_interval_seconds"],
                 "queue_wait_seconds": rules["api"]["queue_wait_seconds"], "window_seconds": first["window_seconds"],
                 "segment_seconds": rules["slurm"]["wall_seconds"]})
    plan = parallel.plan(spec, folder)
    path = Path(plan["manifest"])
    submitted = campaign.launch(path, rules["max_segments"], True)
    return {"name": doc["name"], "mode": rules["mode"], "manifest": str(path), "submitted": True,
            "total_request_reservation_cap": preview["total_request_reservation_cap"],
            "jobs": [row["job_id"] for row in submitted["initial"]["receipts"]],
            "first_review_job": submitted["continuation"]["job_id"]}


REASONS = {
    "scientific_complete": "全部成员达到目标，结果已导出",
    "operator_paused": "受控暂停已经结算，可用 resume 继续原预算",
    "ended_incomplete": "批次结束，有成员未达到目标，查看各组停止原因",
    "authorized_limits_reached": "原授权时限或分段数已用尽，部分进度已保存",
    "needs_review": "原作业、锁或账本状态需要核实，保留现有记录",
    candidate_policy.BUDGET_PAUSE: "演化请求预留上限已用尽，剩余候选未获得",
    candidate_policy.STREAK_PAUSE: "该种子连续失败达到配置阈值，停止该种子",
    candidate_policy.TIME_PAUSE: "已保存检查点，等待 Slurm 审核并接续",
}


def status(path):
    m = shared_admission.load(path)
    raw = parallel.inspect(path)
    control = path.parent / "campaign-control"
    latest = sorted(control.glob("review-*.json"))
    review = read(latest[-1]) if latest else {}
    result = path.parent / "Campaign_result.json"
    outcome = read(result) if result.is_file() else {}
    if outcome.get("segments", 0) < review.get("segment", 0):
        outcome = {}
    error = control / f"error-{review.get('segment', 1):02d}.json"
    stop = read(path.parent / "gate/STOP.json") if raw["STOP"] else None
    if stop:
        message = "共享账户已暂停。核对 STOP 与请求账本，保留未知发送和锁"
    elif error.is_file() or review.get("state") == "submission_reserved":
        message = "Slurm 审核或提交异常。先核对回执，避免重复提交"
    else:
        message = REASONS.get(outcome.get("reason"), "队列中或运行中，按下面的作业 ID 查看")
    members = []
    for row, info in zip(m["members"], raw["members"]):
        metrics = info.get("reported_metrics", {})
        d = Path(row["run_dir"])
        final = d / "exports/summary.json"
        latest_job = d / "latest-submission.json"
        job = read(latest_job).get("job_id") if latest_job.is_file() else None
        reason = info.get("pause_reason")
        group = row["group"]
        run_id = row["run_id"]
        members.append({"group": group, "seed": row["seed"], "phase": info["phase"], "run_id": run_id,
                        "job": job, "checkpoint_updated_at": info.get("checkpoint_updated_at"),
                        "logs": {ext: str(ROOT / "logs" / f"{run_id}-{job}.{ext}") for ext in ("out", "err")} if job else None,
                        "successful_evolution": info.get("successful_evolution_responses", 0),
                        "target": read(row["config"])["evolution_request_cap"],
                        "initialization": info.get("initialization_requests", 0), "best_training_J": metrics.get("best_J"),
                        "request_reservations": metrics.get("reservations_by_stage"),
                        "confirmed_sends": metrics.get("confirmed_sends"),
                        "mock_sends": metrics.get("physical_sends_confirmed") if m["mode"] == "mock" else None,
                        "api_failed_attempts": metrics.get("api_failed_attempts"),
                        "valid_candidates": metrics.get("valid_candidates"),
                        "candidate_failures": metrics.get("failures"),
                        "unknown_sends": metrics.get("physical_sends_unknown"),
                        "unresolved_wire_outcomes": metrics.get("unresolved_wire_outcomes"),
                        "reason": reason, "detail": REASONS.get(reason),
                        "summary_file": str(final) if final.is_file() else None})
    return {"batch": m["batch_id"], "mode": m["mode"], "message": message, "members": members,
            "review_job": review.get("job_id"), "review_state": review.get("state"), "segments": review.get("segment", 0),
            "total_request_reservation_cap": m["total_request_cap"], "STOP": stop,
            "shared_attempts": (raw["shared"] or {}).get("states"), "outcome": outcome.get("reason"),
            "account_closed": (path.parent / "Closed.json").is_file(),
            "effective_max_requests": min(len(m["members"]), m["global_API_width"]),
            "configured_API_width": m["global_API_width"],
            "member_assessment": outcome.get("assessment", {}).get("members"),
            "review_error": read(error) if error.is_file() else None}


def export(path, output):
    info = status(path)
    rows = shared_admission.load(path)["members"]
    ready = []
    for member_info, row in zip(info["members"], rows):
        if not member_info["summary_file"] or member_info["phase"] not in ("completed", "paused", "initialization_incomplete", "expired", "stopped"):
            continue
        if member_info["phase"] == "paused" and not (info["outcome"] or info["STOP"]):
            continue  # A time pause may be followed immediately by another worker segment.
        summary_path = Path(member_info["summary_file"])
        summary = read(summary_path)
        checkpoint = read(Path(row["run_dir"]) / "checkpoint.json")
        if summary["phase"] == checkpoint["phase"] and summary["cursor"] == checkpoint["cursor"]:
            ready.append((row["run_id"], summary_path.parent))
    require(ready, "暂无已导出的稳定结果，请稍后查看 status")
    require(not output.exists(), "目标 ZIP 已存在，请使用新的输出文件名")
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("batch-status.json", json.dumps(info, ensure_ascii=False, indent=2) + "\n")
        for name, folder in ready:
            for file in sorted(folder.iterdir()):
                if file.is_file() and not file.is_symlink() and file.suffix in (".csv", ".json", ".svg", ".md"):
                    archive.write(file, name + "/" + file.name)
    return {"archive": str(output), "members_exported": [name for name, _ in ready],
            "sha256": sha(output), "status": info["message"]}


def pause(path):
    m = shared_admission.load(path)
    rows = []
    for row in m["members"]:
        d = Path(row["run_dir"])
        checkpoint = read(d / "checkpoint.json")
        if checkpoint["phase"] == "running":
            rows.append(row)
        else:
            require(checkpoint["phase"] in ("completed", "initialization_incomplete", "expired", "paused", "stopped"),
                    "请在所有尚未完成的作业开始运行后再请求暂停")
    require(rows, "当前没有运行中的作业")
    for row in rows:
        subprocess.run(parallel.argv(row, "pause", path), check=True, capture_output=True, text=True)
    return {"pause_requested": [row["run_id"] for row in rows],
            "next": "等 status 显示 operator_paused 后用 resume 继续"}


def configure(output, platform):
    """Generate the same JSON consumed by prepare and run."""
    import shlex

    problem = input("问题 [tsp/fjsp/obp，默认 tsp] ").strip().lower() or "tsp"
    templates = {"tsp": "tsp-502.json", "fjsp": "fjsp-503.json", "obp": "obp-501.json"}
    require(problem in templates, "请选择 tsp、fjsp 或 obp")
    path = ROOT / "configurations/experiments" / templates[problem]
    doc = read(path)
    initial_method = "eoh" if problem == "fjsp" else "u"
    method = input(f"方法 [u/eoh/fixed-h/hh，默认 {initial_method}] ").strip().lower() or initial_method
    if method in ("fixed-h", "hh"):
        require(method != "hh", "传统 HH 尚未接入，参见 PROJECT_MAP.md")
        template = path.relative_to(ROOT)
        python = shlex.quote(sys.executable) if platform == "local" else '"/public2/home/qiuqian/hdl-envs/portable-v2/bin/python"'
        print("固定 H 复用同一训练集、参照和冻结 H。先检查资产及求解上限。")
        print(f"{python} -s -B tools/experiment.py fixed-plan {template}")
        return
    require(method in ("u", "eoh"), "请输入 u 或 eoh")
    doc["name"] = input(f"批次名 [默认 {problem}-{method}-study] ").strip() or f"{problem}-{method}-study"
    default_seeds = "502" if problem == "tsp" else "503" if problem == "fjsp" else "501"
    seeds = input(f"逗号分隔的种子，例如 501,502,503 [默认 {default_seeds}] ").strip() or default_seeds
    init = int(input("每种子初始化预留上限 [20] ").strip() or "20")
    doc["research"]["runs"] = [{"method": method, "seed": int(seed.strip()), "initialization_attempts": init}
                               for seed in seeds.split(",")]
    prompt = "训练清单路径 [Enter 使用模板] "
    if training := input(prompt).strip():
        doc["research"]["training_manifest"] = training
    if method == "u" and (h_file := input("冻结 H 路径 [Enter 使用模板] ").strip()):
        doc["research"]["frozen_h"] = h_file
    if problem == "tsp":
        reference = input("D06 参照路径 [Enter 自动查找现场包] ").strip()
        imported = ROOT / "preparations/operations/tsp-reference-r15.json"
        if reference or imported.is_file():
            doc["research"]["reference"] = reference or str(imported.relative_to(ROOT))
    api, slurm = doc["execution"]["api"], doc["execution"]["slurm"]
    api["global_concurrency"] = int(input("同批 API 并发上限 [1/2/4/8，默认 1] ").strip() or "1")
    api["timeout_seconds"] = int(input(f"HTTP 超时秒数 [{api['timeout_seconds']}] ").strip() or api["timeout_seconds"])
    api["evolution_reservation_cap"] = int(input("每种子演化请求预留上限 [1100] ").strip() or "1100")
    if rpm := input("服务商已知的 RPM 上限 [Enter 留空] ").strip():
        api["requests_per_minute"] = int(rpm)
    slurm["cpus"] = int(input("每种子 Slurm CPU 数 [2] ").strip() or "2")
    slurm["memory_mib"] = int(input("每种子内存 MiB [2048] ").strip() or "2048")
    slurm["wall_seconds"] = int(input("单段 Slurm 小时 [12] ").strip() or "12") * 3600
    members, preview = prepare(doc)
    output = output or ROOT / "configurations/experiments" / (doc["name"] + ".json")
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", doc["name"]), "批次名格式无效")
    claim(output, doc)
    print(json.dumps({"配置": str(output), "研究参数": doc["research"], "预检": preview,
                      "模型": members[0][0]["provider"]["model"],
                      "算法": "code/heuristic_design/core/evolution_v1.py" if method == "u"
                      else "deploy/eoh-baseline/eoh_gap.py",
                      "问题适配": f"code/heuristic_design/problems/{problem} · experiments/triad/problems.py",
                      "入口": "tools/experiment.py"}, indent=2, ensure_ascii=False))
    relative = output.resolve().relative_to(ROOT) if output.resolve().is_relative_to(ROOT) else output.resolve()
    python = shlex.quote(sys.executable) if platform == "local" else '"/public2/home/qiuqian/hdl-envs/portable-v2/bin/python"'
    quote = shlex.quote(str(relative))
    print(f"{python} -s -B tools/experiment.py prepare {quote}")
    if platform == "local":
        print("本地可编辑及预检。通过 SSH 登录集群后，在对应发布目录生成 cluster 命令。")
        return
    if preview["ready_for_submission_checks"]:
        if api["global_concurrency"] > 1:
            print("这一并发需先获得对应账户的真实试验授权及验收。")
        print(f"{python} -s -B tools/experiment.py run {quote} --approve")
    else:
        print("补齐 pending 后重新预检。")
    for action in ("status", "pause", "resume", "export"):
        print(f"{python} -s -B tools/experiment.py {action} {quote}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="从一份 JSON 预检、提交、查询和导出 R15 实验",
                                     epilog="配置样例在 configurations/experiments/，参数说明和现场验收见 README.md")
    parser.add_argument("action", choices=("configure", "prepare", "run", "status", "pause", "resume", "export", "fixed-plan"))
    parser.add_argument("config", type=Path, nargs="?")
    parser.add_argument("--platform", choices=("local", "cluster"), default="cluster" if ROOT.is_relative_to("/public2") else "local")
    parser.add_argument("--approve", action="store_true", help="run 提交本批，在原预算内允许 API 与训练评价")
    parser.add_argument("--out", type=Path, help="export 的新 ZIP 路径")
    args = parser.parse_args(argv)
    require(not args.approve or args.action == "run", "--approve 仅用于启动新批次")
    require(args.out is None or args.action in ("export", "configure", "fixed-plan"), "--out 仅用于 export、configure 或 fixed-plan")
    if args.action == "configure":
        require(args.config is None, "configure 用 --out 指定新配置")
        return configure(args.out, args.platform)
    require(args.config is not None, "本命令需要配置文件")
    doc, folder = load_document(args.config)
    path = folder / "Shared.json"
    request = folder.parent / (folder.name + "-inputs") / "request.json"
    if args.action == "prepare":
        result = prepare(doc)[1]
    elif args.action == "fixed-plan":
        result = fixed_plan(doc, args.out)
    elif args.action == "run":
        result = run(doc, folder, args.approve)
    elif args.action == "status" and not path.is_file():
        state = "pending_plan" if request.exists() else "not_started"
        research = doc["research"]
        result = {"name": doc["name"], "state": state,
                  "members": [{"group": research["problem"] + "-" + item["method"], "seed": item["seed"],
                               "phase": state, "successful_evolution": 0, "target": research["budget"]["target"]}
                              for item in research["runs"]],
                  "request_receipt": str(request) if request.exists() else None,
                  "next": "启动中断留下计划回执，请保留记录并核对原启动输出" if request.exists()
                  else "运行 prepare 核对资产，然后在集群用 run --approve 启动"}
    else:
        require(path.is_file(), "还没有完整的批次计划，请先运行 prepare。若启动报错请保留已有回执")
        original = read(request)
        require(digest(doc) == original["config_digest"], "配置已变更，请用原 JSON 查询或恢复。新配置须使用新 name")
        if args.action == "status":
            result = status(path)
        elif args.action == "pause":
            result = pause(path)
        elif args.action == "resume":
            result = campaign.resume_operator(path)
        else:
            result = export(path, (args.out or Path(doc["name"] + "-results.zip")).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, EOFError, subprocess.SubprocessError) as error:
        info = getattr(error, "stderr", None)
        print(json.dumps({"error": str(error), "detail": info[:1000] if info else None}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
