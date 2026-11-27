"""Read existing experiment receipts and render the researcher status matrix."""

import argparse
import csv
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from experiments.triad import assets, post_evaluation, six_ops
from tools import r15_results


TZ = timezone(timedelta(hours=8))
CACHE = "experiment-status-snapshot.json"
REPORT = "EXPERIMENT_STATUS.md"
TRAIN = {"tsp": "train20", "fjsp": "train21", "obp": "train96"}
METHOD = {"u": "U", "eoh": "EoH", "ross": "Ross-style", "fixed": "Best Fixed H"}
PHASE = {"not_started": "未启动", "running": "运行", "paused": "暂停",
         "completed": "完成", "failed": "失败", "expired": "窗口到期",
         "prepared": "已准备", "launching": "启动中", "submitted": "已提交",
         "initialization_incomplete": "初始化未完成", "unknown": "待核验"}
TSP_BATCH = {("u", 501): "r15-tsp-u-501-503-parallel",
             ("u", 502): "r15-tsp-u-502-503-cont",
             ("u", 503): "r15-tsp-u-502-503-cont"}


def stamp(path=None):
    instant = datetime.fromtimestamp(path.stat().st_mtime, TZ) if path else datetime.now(TZ)
    return instant.isoformat(timespec="seconds")


def read(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def row(version, run_id, problem, method, seed, path):
    return dict(version=version, run_id=run_id, problem=problem, method=method, seed=seed,
                source=str(path), as_of=stamp(path), train_data=TRAIN.get(problem), fresh=True)


def read_holdout(item, manifest, run_id, identity):
    spec = post_evaluation.plan(manifest)
    if not spec:
        return
    item.update(holdout_set=Path(spec["manifest"]).name, holdout_state="not_started")
    history = post_evaluation.attempts(manifest, run_id)
    if not history:
        return
    folder = history[-1]
    receipt = read(folder / "submission.json")
    receipt_path = folder / "submission.json"
    item.update(holdout_state=receipt.get("state", "unknown"), holdout_job=receipt.get("job_id"),
                holdout_source=str(receipt_path) if receipt else None,
                holdout_as_of=stamp(receipt_path) if receipt else None)
    file = folder / "result.json"
    if not file.is_file():
        return
    result = read(file)
    complete = (identity is not None and result.get("identity") == identity
                and result.get("binding") == spec["binding"] and result.get("split") == spec["split"]
                and result.get("complete") is True and result.get("engineering_only") is False
                and len(result.get("rows", [])) == spec["binding"]["instances"]
                and number(result.get("holdout_J")) is not None)
    item.update(holdout_state="completed" if complete else "failed",
                holdout_J=result["holdout_J"] if complete else None,
                holdout_rows=len(result.get("rows", [])), holdout_source=str(file), holdout_as_of=stamp(file))
    identity_fields = [spec["binding"].get(name) for name in ("instance_rows_sha256", "reference_rows_sha256")]
    if complete and all(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
                        for value in identity_fields):
        item["holdout_identity"] = [spec["split"], *identity_fields]
    if not complete:
        item["gap"] = "外评未完成或身份不一致，核对评价回执"


def campaign_rows(path):
    manifest = read(path)
    if manifest.get("mode") != "real":
        return
    version = "R15" if manifest.get("candidate_policy") else "R13" if "r13" in str(path).lower() else None
    if not version:
        return
    for member in manifest["members"]:
        run = Path(member["run_dir"])
        problem, method = member["group"].split("-", 1)
        item = row(version, member["run_id"], problem, method, member["seed"], path)
        try:
            yield campaign_member(item, member, run, path, version)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            yield {**item, "fresh": False, "train_state": "unknown", "gap": f"运行记录无法读取 · {exc}"}


def campaign_member(item, member, run, path, version):
    cp_path = run / "checkpoint.json"
    cp = read(cp_path)
    config = read(Path(member["config"]))
    if not cp:
        return {**item, "fresh": False, "train_state": "unknown",
                "gap": "未读到断点或运行目录，待核验"}
    item.update(source=str(cp_path), as_of=stamp(cp_path))
    item["train_data"] = Path(config["data_manifest"]).name if config.get("data_manifest") else None
    summary = read(run / "exports/summary.json")
    progress = read(run / "Progress.json")
    latest = run / "latest-submission.json"
    receipt = read(latest)
    count = (cp.get("successful_evolution_responses") if version == "R15"
             else cp.get("eoh", {}).get("operator_cursor"))
    frozen = run / "exports/frozen_training_champion.json"
    item.update(count=count, target=config.get("evolution_request_cap"),
                train_state=cp.get("phase", "unknown"), train_J=number((progress or summary).get("best_J")),
                protocol_hash=cp.get("identity"),
                champion_id=(summary or progress).get("champion_id"),
                champion_state="frozen" if frozen.is_file() else "selected" if summary.get("champion_id") else "unknown",
                job=receipt.get("job_id"), job_state=receipt.get("state"),
                job_as_of=stamp(latest) if receipt else None,
                result_path=str(run / "exports") if summary else str(run),
                gap=cp.get("pause_reason"))
    identity = None
    if version == "R15" and frozen.is_file() and item["train_state"] == "completed":
        try:
            _, _, _, identity = post_evaluation.training_export(run)
            item.update(champion_state="verified", champion_hash=identity["champion_sha256"],
                        champion_id=identity["champion_id"], train_J=identity["training_J"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            item["gap"] = "冠军文件待核验 · " + str(exc)
    if version == "R15":
        try:
            read_holdout(item, path, member["run_id"], identity)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            item.update(holdout_state="unknown", gap="外评记录待核验 · " + str(exc))
    return item


def prototype_rows(root):
    checkpoints = sorted(root.glob("runs/prototype-hh/*/checkpoint.json"))
    if not checkpoints:
        return
    processes = []
    if sys.platform == "darwin":
        try:
            processes = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True,
                                       check=True, text=True, timeout=10).stdout.splitlines()
        except (OSError, subprocess.SubprocessError):
            pass
    for cp_path in checkpoints:
        run = cp_path.parent
        cp = read(cp_path)
        protocol = read(run / "Protocol.json")
        if protocol.get("engineering_only") is not False:
            continue
        problem = protocol["config"]["problem"]
        item = row("Ross-v1", run.name, problem, "ross", protocol["seed"], cp_path)
        best = min((r for r in cp["records"] if r.get("valid")),
                   key=lambda r: (r["J"], r["id"]), default={})
        frozen = run / "exports/frozen-model.json"
        model = read(frozen)
        champ = model.get("training_champion", {})
        verified = (bool(best) and champ.get("id") == best["id"] and champ.get("J") == best["J"]
                    and champ.get("candidate_key") == best["candidate_key"]
                    and model.get("source_search_protocol_sha256") == cp.get("identity") == digest(run / "Protocol.json")
                    and model.get("seed") == protocol["seed"] and model.get("binding") == protocol["binding"])
        item.update(count=cp.get("cursor"), target=protocol["search"]["population_size"] + 2 * protocol["search"]["iterations"],
                    train_state=cp.get("phase", "unknown"), train_J=number(best.get("J")),
                    protocol_hash=cp.get("identity"),
                    champion_id=best.get("id"), champion_state="verified" if verified else
                    "frozen" if model else "provisional" if best else "unknown",
                    result_path=str(frozen if model else run), champion_hash=digest(frozen) if verified else None,
                    job_state="本地断点", holdout_state="not_started")
        for line in processes:
            fields = line.split(maxsplit=1)
            if (len(fields) == 2 and fields[0].isdigit() and "prototype_hh.py train" in fields[1]
                    and f"--run-dir {run}" in fields[1] and Path(fields[1].split()[0]).name != "caffeinate"):
                item.update(job=f"PID {fields[0]}", job_state="RUNNING", job_as_of=stamp())
                break
        yield item


def tsp_confirm_rows(root):
    path = root / "reports/tsp-confirm60-nine-20261124/seed-results.csv"
    if path.is_file():
        with path.open(newline="") as stream:
            records = list(csv.DictReader(stream))
        # Existing dedicated evaluator writes these receipts only for the frozen inputs.
        for record in records:
            method, seed = record["method"], int(record["seed"])
            if method not in ("u", "eoh", "ross"):
                continue
            version = "Ross-v1" if method == "ross" else "R15"
            batch = TSP_BATCH.get((method, seed), "r15-tsp-eoh-501-503-parallel")
            run_id = f"tsp-{seed}" if method == "ross" else f"candidate-lab-{batch}-tsp-{method}-seed-{seed}"
            if record["complete"] != "True" or record["rows"] != "60":
                continue
            if not all(re.fullmatch(r"[a-f0-9]{64}", record[k]) for k in
                       ("champion_sha256", "protocol_sha256", "manifest_sha256", "reference_sha256")):
                continue
            train_j, holdout_j = (number(float(record[k])) for k in ("training_J", "confirm60_J"))
            if train_j is None or holdout_j is None:
                continue
            item = row(version, run_id, "tsp", method, seed, path)
            item.update(train_state="completed", count=1040 if method == "ross" else 1000,
                        target=1040 if method == "ross" else 1000, train_J=train_j,
                        champion_state="verified", champion_id=record["champion_id"],
                        champion_hash=record["champion_sha256"],
                        protocol_hash=record["protocol_sha256"],
                        holdout_state="completed", holdout_set="confirm60 / D06",
                        holdout_J=holdout_j, holdout_rows=60, holdout_source=str(path), holdout_as_of=stamp(path),
                        holdout_identity=["prospective-confirmation", record["manifest_sha256"], record["reference_sha256"]],
                        result_path=str(path.parent), job_state="Mac 外评回执")
            yield item


def fjsp_fixed_rows(project):
    table = project / "reports/fjsp-execution-20261112/fixed-H-reuse-v3/fixed-H-train21-J.csv"
    if not table.is_file():
        return
    evidence = assets.fixed_plan(six_ops.config("fjsp-u"))["compatible_reuse"]
    if evidence:
        item = row("固定 H", "fjsp-fixed-train21", "fjsp", "fixed", None, table)
        item.update(train_state="completed", champion_state="verified", champion_id=f"H{evidence['H_index']}",
                    train_J=evidence["J"], holdout_state="not_started", result_path=str(table),
                    job_state="复用已核验成本", gap="训练参照已核验，正式外评待安排")
        yield item


def archive_rows(path):
    _, records = r15_results.read_export(path)
    for record in records:
        problem, method = record["group"].split("-", 1)
        item = row("R15", record["run_id"], problem, method, record["seed"], path)
        item.update(train_state=record["phase"], count=record["successful_evolution"], target=record["target"],
                    train_J=record["best_training_J"], champion_id=record.get("champion_id"),
                    champion_state="selected" if record.get("champion_id") else "unknown",
                    result_path=str(path), job_state="归档回执", fresh=False)
        yield item


def blend(by_id, item):
    prefix = item["version"], item["run_id"]
    matches = [k for k in by_id if k[:2] == prefix]
    identity = item.get("protocol_hash")
    exact = next((k for k in matches if identity and k[2] == identity), None)
    compatible = [k for k in matches if not k[2] or not identity]
    key = exact or (compatible[0] if len(matches) == len(compatible) == 1 else (*prefix, identity))
    old = by_id.pop(key, {})
    # Checkpoint, export and evaluation may arrive independently. Match the
    # champion before carrying a frozen certificate or test result forward.
    same = (bool(item.get("champion_id")) and item.get("champion_id") == old.get("champion_id")
            and (not item.get("champion_hash") or not old.get("champion_hash")
                 or item["champion_hash"] == old["champion_hash"]))
    if old.get("as_of", "") > item["as_of"]:
        item, old = dict(old), item
    if item.get("train_state") == "unknown" and item.get("count") is None and old.get("count") is not None:
        item = {**old, "fresh": False, "gap": item.get("gap") or old.get("gap")}
    if same and item.get("train_state") == "completed":
        ranks = {"unknown": 0, "provisional": 1, "selected": 2, "frozen": 3, "verified": 4}
        if ranks.get(old.get("champion_state"), 0) > ranks.get(item.get("champion_state"), 0):
            item.update(champion_state=old["champion_state"], champion_hash=old.get("champion_hash"))
        if old.get("holdout_state") == "completed" and item.get("holdout_state") in (None, "not_started"):
            item.update({k: v for k, v in old.items() if k.startswith("holdout_")})
    if same and not item.get("job") and old.get("job") and not str(old["job"]).startswith("PID "):
        item.update(job=old["job"], job_state=old.get("job_state"), job_as_of=old.get("job_as_of"))
    identity = item.get("protocol_hash") or old.get("protocol_hash")
    if identity:
        item["protocol_hash"] = identity
    by_id[(*prefix, identity)] = item


def snapshot(path):
    payload = read(path)
    if payload.get("schema") != 1 or not isinstance(payload.get("records"), list):
        raise ValueError(f"无法识别状态快照 {path}")
    for record in payload["records"]:
        if (not isinstance(record, dict)
                or not all(isinstance(record.get(k), str) for k in ("version", "run_id", "problem", "method", "as_of"))
                or "seed" not in record or type(record["seed"]) not in (int, type(None))):
            raise ValueError(f"缺少可核验的实验身份或时间 {path}")
        yield dict(record, fresh=False)


def bookmark(path, project):
    if not path:
        return "—"
    value = Path(path)
    if value.is_absolute() and not value.exists():
        return "`" + path + "`"
    if not value.is_absolute():
        value = project / value
    link = os.path.relpath(value, project / "reports").replace(" ", "%20")
    return f"[{value.name}]({link})" if value.exists() else "`" + path + "`"


def render(records, warnings, project):
    lines = ["# 实验状态矩阵", "",
             "[科研实验进展汇报](RESEARCH_PROGRESS.md) · [项目首页](../README.md) · [研究人员指南](../DECISIONS.md) · [选择实验与命令](../docs/实验导航.md)",
             "", "按命令刷新。日期为 UTC+8。缓存行保留最后一次可核实的状态，标为「待确认」。"
             "训练完成看断点与预算，Slurm 退出仅代表一个作业结束。"
             "论文结果「单种子齐」要求训练达标、冠军已核验、同一冻结冠军的正式外评通过。"
             "发表前还需核对计划内所有独立种子和跨种子汇总。", ""]
    if warnings:
        lines += ["读取问题", ""] + [f"- {msg}" for msg in warnings] + [""]
    confirm = [r for r in records if r.get("holdout_set") == "confirm60 / D06"
               and r.get("holdout_state") == "completed" and r.get("holdout_source")
               and type(r.get("holdout_rows")) is int]
    if confirm:
        existing = Path(confirm[0]["holdout_source"]).parent
        lines += [f"TSP confirm60 已有 {len(confirm)} 份冠军外评回执，"
                  f"共 {sum(r.get('holdout_rows', 0) for r in confirm)} 条逐实例结果。"
                  f" {bookmark(str(existing / 'method-summary.csv'), project)} · "
                  f"{bookmark(str(existing / 'per-instance.csv'), project)}", ""]
    header = "| 问题／方法 | 协议／种子 | 训练数据与进度 | 训练 | 冠军 | 训练 J | 外评集／状态 | 外评 J | 论文结果 | 作业／回执 | 最后核实 | 当前缺口 | 结果与来源 |"
    lines += [header, "|" + "---|" * 13]
    for r in records:
        train = r.get("train_state", "unknown")
        hold = r.get("holdout_state", "unknown")
        champion = r.get("champion_state", "unknown")
        champ = {"verified": "已核验", "frozen": "已冻结", "selected": "已选出",
                 "provisional": "中途最好", "none": "未选出"}.get(champion, "待核验")
        progress = f"{r['count']}/{r['target']}" if r.get("count") is not None and r.get("target") else ""
        paper = ("单种子齐" if train == "completed" and progress and r["count"] == r["target"]
                 and champion == "verified" and hold == "completed" else "未齐")
        phase = PHASE.get(train, train)
        if train == "completed" and r["method"] != "fixed" and (not r.get("target") or r.get("count") != r["target"]):
            phase = "已结束，未核实达标"
        elif train == "completed" and r["method"] == "fixed":
            phase = "训练成本已齐"
        if not r.get("fresh") or (train == "running" and r.get("job_state") != "RUNNING"):
            phase += " · 待确认" if train not in ("completed", "not_started") else " · 历史回执"
        hold_phase = {"not_run": "未开始", "not_started": "未开始", "submitted": "已提交",
                      "running": "运行中"}.get(hold, PHASE.get(hold, hold))
        if hold in ("running", "submitted") and not r.get("fresh"):
            hold_phase += " · 待确认"
        gap = r.get("gap")
        if isinstance(gap, str) and "non_retryable_unclassified_error" in gap and r["run_id"].startswith(
                "candidate-lab-r15-fjsp-eoh-501-503-20261123"):
            gap = "HTTP 200 响应格式无法读取，待修复并续跑"
        if not gap and train == "completed" and hold != "completed":
            gap = "缺正式外评" if champion == "verified" else "待核验冻结冠军及外评"
        if paper == "单种子齐":
            gap = None
        fields = [r["problem"].upper() + " " + METHOD.get(r["method"], r["method"]),
                  f"{r['version']}／{r['seed'] if r['seed'] is not None else '无搜索种子'}",
                  " ".join(filter(None, (r.get("train_data"), progress))), phase,
                  champ + (" · " + r["champion_id"] if r.get("champion_id") else ""),
                  fmt(r.get("train_J")), "／".join(filter(None, (r.get("holdout_set"), hold_phase))),
                  fmt(r.get("holdout_J")), paper,
                  " ".join(filter(None, (str(r.get("job") or ""), r.get("job_state"),
                                         f"外评 {r['holdout_job']}" if r.get("holdout_job") else ""))),
                  "；".join(dict.fromkeys(filter(None, (r.get("as_of"), r.get("holdout_as_of"), r.get("job_as_of"),
                                                        r.get("slurm_seen_at"))))),
                  gap, " · ".join(dict.fromkeys(bookmark(r.get(k), project) for k in
                                                ("source", "result_path", "holdout_source") if r.get(k)))
                  or r.get("source_note")]
        lines.append("| " + " | ".join(str(v or "—").replace("|", r"\|").replace("\n", " ") for v in fields) + " |")
    lines += ["", "运行身份按协议和原运行 ID 保留。旧批次、同种子的续跑记录和新复做均可追溯，"
              "续跑阶段不能当作额外重复。冻结资产、预算及容错规则见 [研究人员指南](../DECISIONS.md)。", ""]
    return "\n".join(lines)


def fmt(value):
    return f"{value:.6f}" if number(value) is not None else "—"


def order(r):
    return (list(TRAIN).index(r["problem"]) if r["problem"] in TRAIN else 9,
            list(METHOD).index(r["method"]) if r["method"] in METHOD else 9,
            r["version"] not in ("R15", "Ross-v1", "固定 H"), r["seed"] or 0, r["run_id"])


def atomic_write(path, text):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        try:
            handle.write(text)
            handle.flush()
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def main(project, argv):
    parser = argparse.ArgumentParser(prog="experiment.py dashboard", description=__doc__)
    parser.add_argument("--root", action="append", type=Path, default=[], help="可读的发布目录或 hdl-deploy 父目录")
    parser.add_argument("--prototype-root", type=Path, help="Ross-style 工作树")
    parser.add_argument("--archive", action="append", type=Path, default=[], help="已导出的真实 R15 工作台 ZIP")
    parser.add_argument("--import-snapshot", action="append", type=Path, default=[], help="从其他设备取回的 dashboard JSON")
    parser.add_argument("--slurm", action="store_true", help="在集群额外只读查询本账号当前 squeue")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--refresh", action="store_true", help="只刷新 reports 下的矩阵与最近状态快照")
    args = parser.parse_args(argv)
    by_id, warnings = {}, []
    reports = project / "reports"

    def collect(source, operation, *, keep_fresh=True):
        try:
            for item in operation(source):
                item["fresh"] = keep_fresh and item.get("fresh", False)
                blend(by_id, item)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append(f"`{source}` · {exc}")

    for path in [reports / CACHE, *args.import_snapshot]:
        if path.is_file() or path in args.import_snapshot:
            collect(path, snapshot)
    manifests = set()
    for root in [project, *args.root]:
        if not root.is_dir():
            warnings.append(f"`{root}` 不可读，保留已有回执")
            continue
        manifests.update(root.glob("plans/*/Shared.json"))
        if root != project:
            manifests.update(root.glob("*/plans/*/Shared.json"))
    for path in sorted(manifests):
        collect(path, campaign_rows)
    proto = args.prototype_root or project
    if proto.is_dir():
        collect(proto, prototype_rows)
        collect(proto, tsp_confirm_rows)
    elif args.prototype_root:
        warnings.append(f"`{proto}` 不可读，保留已有回执")
    for path in args.archive:
        collect(path, archive_rows)
    collect(project, fjsp_fixed_rows)
    if args.slurm:
        try:
            queue = subprocess.run(["squeue", "-h", "-u", os.environ["USER"], "-o", "%i|%T"],
                                   capture_output=True, check=True, text=True, timeout=15)
            states = dict(line.split("|", 1) for line in queue.stdout.splitlines())
            for item in by_id.values():
                if item.get("job") in states:
                    item.update(job_state=states[item["job"]], slurm_seen_at=stamp())
                if item.get("holdout_job") in states:
                    status = states[item["holdout_job"]]
                    if item.get("holdout_state") == "submitted" and status == "RUNNING":
                        item["holdout_state"] = "running"
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            warnings.append(f"Slurm 队列不可读，保留已有回执 · {exc}")
    real_seeds = {(r["version"], r["problem"], r["method"], r["seed"]) for r in by_id.values()
                  if not r["run_id"].endswith("-planned")}
    records = sorted((r for r in by_id.values() if not r["run_id"].endswith("-planned")
                      or (r["version"], r["problem"], r["method"], r["seed"]) not in real_seeds), key=order)
    markdown = render(records, warnings, project)
    payload = {"schema": 1, "records": [{k: v for k, v in r.items() if k != "fresh"} for r in records]}
    data = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.refresh:
        atomic_write(reports / REPORT, markdown)
        atomic_write(reports / CACHE, data)
    print(data if args.format == "json" else markdown, end="")
