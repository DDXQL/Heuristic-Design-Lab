#!/usr/bin/env python3
"""R1剩余兼容批次：旧入口恒选H0与H0/H1静态等权；API=0。

仅运行这两个外部基线，不重跑已完成的12条common候选。
旧评价器保留候选串行执行；R3/B1的API2/CPU2配置不受影响。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# ===== 本批实际参数；路径相对项目根 =====
PARAMETERS = {
    "H_source": "preparations/b1-v6-20261029/H_frozen.json",
    "train_manifest": "preparations/b1-v6-20261029/train21.manifest.json",
    "reference_run": "runs/b1-v6-r1-train21-20261029-221535-858514-d3145ddd",
    "strategies": [{"id":"H0_SELECT", "member":0}, {"id":"H0_H1_EQUAL", "alpha":0.5}],
    "search_seed": 501,
    "solve_seed": 501,
    "instance_timeout": 30,      # 完整首解/复检行接收T30，正常退出另2秒
    "window_seconds": 43200,    # 原评价器总时窗12小时，不表示预计耗时
    "api_mode": "disabled",    # 本入口禁止更改为生成模式
    "real_requests_authorized": False,
}
RUN_PREFIX = "b1-v6-r1-legacy-train21"
# ===== 参数区结束；以下仅串联既有组件 =====

import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
import json
import sys
import tempfile
from uuid import uuid4
from zoneinfo import ZoneInfo

sys.path[:0] = [str(ROOT/"code"), str(ROOT)]
from experiments.common._single_run import _Tee
from heuristic_design.core.storage import read, sha, write
from heuristic_design.core.terminal_ops import snapshot
from tools import experiment_ops as ops
from tools.experiment_ops_run import start
from tools.experiment_ops_report import summary

FIELDS = {"H_source", "train_manifest", "reference_run", "strategies", "search_seed",
          "solve_seed", "instance_timeout", "window_seconds", "api_mode", "real_requests_authorized"}


def config(parameters):
    if not isinstance(parameters, dict) or set(parameters) != FIELDS:
        raise ValueError("PARAMETERS存在未知或缺失字段")
    if parameters["api_mode"] != "disabled" or parameters["real_requests_authorized"] is not False:
        raise ValueError("R1兼容批次强制禁止API")
    reference = ROOT/parameters["reference_run"]
    if snapshot(reference, problem="fjsp")["phase"] != "completed":
        raise ValueError("先完成作为对照的common固定评价")
    original = read(reference/"Protocol.json")
    manifest_path = ROOT/parameters["train_manifest"]
    manifest = read(manifest_path)
    if (manifest.get("problem") != "fjsp" or manifest.get("split") != "train"
            or sha(manifest_path) != original["input_provenance"]["data"]["sha256"]
            or sha(ROOT/parameters["H_source"]) != original["input_provenance"]["H"]["sha256"]):
        raise ValueError("H或训练清单与已完成common对照身份不一致")
    paths=[]
    for row, old in zip(manifest["instances"], original["instances"]):
        path=(manifest_path.parent/row["path"]).resolve()
        if row["file"] != old["file"] or sha(path) != row["sha256"] or row["sha256"] != old["source_sha256"]:
            raise ValueError("训练文件顺序/内容与common对照不一致")
        paths.append(str(path.relative_to(ROOT)))
    if len(paths) != 21 or len(manifest["instances"]) != 21 or len(original["instances"]) != 21:
        raise ValueError("必须是同一完整train21")
    return {k:v for k,v in parameters.items() if k not in ("train_manifest", "reference_run")} | {
        "schema":"experiment-operations-v1", "type":"fixed", "space":"ten_h",
        "question":"R1 compatibility: H0 parity and static H0/H1 equal on identical train21",
        "dataset":{"role":"train", "files":paths}}


def check(path):
    d=ops.describe(path)
    reference=read(ROOT/PARAMETERS["reference_run"]/"Protocol.json")
    if [(r["file"],r["LB"]) for r in d["instances"]] != [(r["file"],r["reference"]) for r in reference["references"]]:
        raise ValueError("common/legacy实例顺序或LB不一致")
    if d["budgets"]["logical_generation"] != 0 or d["budgets"]["API_attempts"] != 0:
        raise ValueError("本批不得有生成/API预算")
    return d


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="只核查输入/计划，不求解")
    args=parser.parse_args()
    try:
        c=config(PARAMETERS)
        if not isinstance(RUN_PREFIX,str) or not RUN_PREFIX or "/" in RUN_PREFIX or "\\" in RUN_PREFIX or RUN_PREFIX in (".",".."):
            raise ValueError("RUN_PREFIX必须是单个目录名称")
        if args.check_only:
            with tempfile.TemporaryDirectory(prefix="r1-legacy-check-", dir=ROOT/"preparations") as temp:
                path=Path(temp)/"config.json";write(path,c);d=check(path)
            print(json.dumps({"checked":True,"budgets":d["budgets"],"solves":0,"API_calls":0},ensure_ascii=False,indent=2))
            return 0
        stamp=datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y%m%d-%H%M%S-%f")
        name=f"{RUN_PREFIX}-{stamp}-{uuid4().hex[:8]}"
        preparation=ROOT/"preparations"/name;preparation.mkdir()
        path=preparation/"config.json";write(path,c);d=check(path)
        directory=ROOT/"runs"/name
        ops.prepare(path,directory)  # 原prepare只接受全新runs直接子目录
        (preparation/"entry.py").write_bytes(Path(__file__).read_bytes())
        write(preparation/"entry-receipt.json", {"source_sha256":sha(Path(__file__)),"reference_run":PARAMETERS["reference_run"]})
        try:
            with (directory/"terminal.log").open("x") as log, redirect_stdout(_Tee(sys.stdout,log)), redirect_stderr(_Tee(sys.stderr,log)):
                print(json.dumps({"run_directory":str(directory),"budgets":d["budgets"],"API_calls":0},ensure_ascii=False,indent=2))
                try:
                    start(directory,allow_api=False,background=False)
                    facts=summary(directory,write_files=True)
                    print(json.dumps({k:facts[k] for k in ("phase","used","strategy_results","API_usage")},ensure_ascii=False,indent=2))
                    return 0 if facts["complete"] and facts["used"]["certified_strategies"]==len(c["strategies"]) else 2
                except BaseException as exc:
                    print(f"运行停止：{type(exc).__name__}: {exc}；保留锁和证据。",file=sys.stderr)
                    raise
        finally:
            print(f"运行目录：{directory}\n日志：{directory/'terminal.log'}\n结果：{directory/'results'}")
    except Exception as exc:
        print(f"R1兼容批次停止：{type(exc).__name__}: {exc}",file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
