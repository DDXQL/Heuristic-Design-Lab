#!/usr/bin/env python3
"""R1：既有canonical EoH原生冻结规则，完整train21；强制API=0。"""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

# ===== 顶部参数；只复用既有冻结规则，不训练Tier1或修改公式 =====
PARAMETERS={
    "reference_run":"runs/b1-v6-r1-train21-20261029-221535-858514-d3145ddd",
    "rule_manifest":"baselines/tier1_single_rule_v1/portable_manifest.json",
    "rule_source":"preparations/b1-v6-20261029/eoh-canonical-source/selected_rule_original.py",
    "search_seed":501,
    "solve_seed":501,
    "instance_timeout":30,
    "window_seconds":43200,
    "api_mode":"disabled",
    "real_requests_authorized":False,
}
RUN_PREFIX="b1-v6-r1-eoh-train21"
# ===== 参数区结束 =====
import argparse
from contextlib import redirect_stdout,redirect_stderr
from datetime import datetime
import json
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo
sys.path[:0]=[str(ROOT/"code"),str(ROOT)]
from experiments.common._single_run import _Tee
from heuristic_design.core import execution
from tools.r1_eoh_baseline import Adapter,preflight,prepare,read


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument("--check-only",action="store_true")
    for name in ("status","pause","resume","export"):actions.add_argument("--"+name,type=Path)
    args=parser.parse_args();adapter=Adapter()
    try:
        directory=next((getattr(args,k) for k in ("status","pause","resume","export") if getattr(args,k)),None)
        if directory is not None:
            directory=(ROOT/directory).resolve();p=adapter.check_run(directory)
            if args.status:
                state=read(directory/"checkpoint.json");print(json.dumps({"phase":state["phase"],"cursor":state["cursor"],"writer_lock":(directory/".execution.lock").exists()},ensure_ascii=False,indent=2));return 0
            if args.pause:print(execution.stop(directory,adapter=adapter));return 0
            if args.export:print(json.dumps(adapter.summary(directory,write_files=True),ensure_ascii=False,indent=2));return 0
        else:
            c,candidate,instances,provenance=preflight(PARAMETERS)
            print(json.dumps({"fixed_rule":candidate.key,"instances":len(instances),"max_solve_passes":42,"API_requests":0},indent=2))
            if not isinstance(RUN_PREFIX,str) or not RUN_PREFIX or "/" in RUN_PREFIX or "\\" in RUN_PREFIX or RUN_PREFIX in (".",".."):raise ValueError("非法RUN_PREFIX")
            if args.check_only:return 0
            stamp=datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y%m%d-%H%M%S-%f")
            directory=ROOT/"runs"/f"{RUN_PREFIX}-{stamp}-{uuid4().hex[:8]}"
            prepare(directory,PARAMETERS,Path(__file__))
        try:
            with (directory/"terminal.log").open("a") as log,redirect_stdout(_Tee(sys.stdout,log)),redirect_stderr(_Tee(sys.stderr,log)):
                print(json.dumps({"run_directory":str(directory),"API_requests":0},ensure_ascii=False))
                execution.start(directory,adapter=adapter,resume=bool(args.resume),allow_api=False,background=False)
                facts=adapter.summary(directory,write_files=True)
                print(json.dumps({k:facts[k] for k in ("phase","valid","fitness","complete_instances","API_requests")},ensure_ascii=False,indent=2))
                return 0 if facts["phase"]=="completed" and facts["valid"] else 2
        finally:print(f"运行目录：{directory}\n日志：{directory/'terminal.log'}\n结果：{directory/'results'}")
    except Exception as exc:
        print(f"EoH固定评价停止：{type(exc).__name__}: {exc}",file=sys.stderr);return 2


if __name__=="__main__":raise SystemExit(main())
