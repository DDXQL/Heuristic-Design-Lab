#!/usr/bin/env python3
"""R1：历史冻结10H上的固定U，完整train21真实求解；强制API=0。

修改下面参数后直接运行本脚本；不再编辑另一份JSON。
默认12个候选：恒选H0—H9，及进度0.5时H0→H1、H1→H0。
每次普通启动新建目录并重新评价；不会恢复或覆盖旧运行。
模型/端点/密钥不适用于R1。R3和B1搜索将另有明确入口。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ===== 日常只修改这里：相对路径均从项目根目录解析 =====
PARAMETERS = {
    "problem": "fjsp",
    "state_schema": "constructive-common-v1-fjsp",
    "h_file": "preparations/b1-v6-20261029/H_frozen.json",
    "data_manifest": "preparations/b1-v6-20261029/train21.manifest.json",
    "p0_file": "preparations/b1-v6-20261029/calibration-p0.json",
    "population_size": 12,          # 固定候选数，必须与P0条数一致
    "search_seed": 501,
    "solve_seed": 501,
    "window": 10,
    "enabled_groups": ["construction", "action_cost", "trajectory", "usage"],
    "evaluation_concurrency": 2,    # 候选CPU并发；单候选内实例串行
    "api_concurrency": 2,           # 仅登记；fixed模式绝不生成请求
    "instance_timeout_seconds": 30, # 首解+复检+完整行接收共享T30
    "api_mode": "fixed",           # R1强制fixed，修改为real会报错
    "evaluation_mode": "solve",
    "initialization": "import",
    "generations": 0,
    "generation_request_cap": 0,
    "api_attempt_cap": 0,
    "real_requests_authorized": False,
}
EXPECTED_H_COUNT = 10
EXPECTED_TRAIN_COUNT = 21
RUN_ROOT = ROOT / "runs"
RUN_PREFIX = "b1-v6-r1-train21"
RUN_NAME = None  # None自动生成时间戳+随机后缀；手填名称时已有目录直接拒绝
# ===== 参数区结束；下方复用既有执行器 =====

import argparse
import sys

sys.path[:0] = [str(ROOT / "code"), str(ROOT)]
from experiments.common._single_run import launch_r1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true",
                        help="只检查输入和预算，不创建运行、不求解、不请求API")
    args = parser.parse_args()
    try:
        return launch_r1(PARAMETERS, root=ROOT, run_root=RUN_ROOT,
                         prefix=RUN_PREFIX, name=RUN_NAME, entry=Path(__file__),
                         expected_h=EXPECTED_H_COUNT, expected_train=EXPECTED_TRAIN_COUNT,
                         check_only=args.check_only)
    except Exception as exc:
        print(f"R1停止：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
