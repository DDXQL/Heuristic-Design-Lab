#!/usr/bin/env python3
"""Non-LLM prototype baseline. Check/bind never solve; execution is explicit."""
import argparse
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "code"), str(ROOT)]
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "1"

from experiments.prototype_hh import runner


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    check = commands.add_parser("check")
    check.add_argument("config", type=Path)
    bind = commands.add_parser("bind")
    bind.add_argument("config", type=Path)
    bind.add_argument("--u-protocol", type=Path, required=True)
    bind.add_argument("--out", type=Path, required=True)
    train = commands.add_parser("train")
    train.add_argument("config", type=Path)
    train.add_argument("--seed", type=int, choices=(501, 502, 503), required=True)
    train.add_argument("--run-dir", type=Path, required=True)
    train.add_argument("--resume", action="store_true")
    train.add_argument("--execute", action="store_true", help="explicitly permit CPU training solves")
    train.add_argument("--max-candidates", type=int)
    train.add_argument("--max-seconds", type=float)
    for action in ("status", "export"):
        sub = commands.add_parser(action)
        sub.add_argument("run_dir", type=Path)
    summarize = commands.add_parser("summarize")
    summarize.add_argument("run_dirs", type=Path, nargs=3)
    held = commands.add_parser("summarize-evaluations")
    held.add_argument("run_dirs", type=Path, nargs=3)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--model", type=Path, required=True)
    evaluate.add_argument("--manifest", type=Path, required=True)
    evaluate.add_argument("--reference", type=Path)
    evaluate.add_argument("--split", choices=("validation", "test"), required=True)
    evaluate.add_argument("--run-dir", type=Path, required=True)
    evaluate.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "check":
        value = runner.check(args.config)[3]
    elif args.action == "bind":
        value = runner.bind(args.config, args.u_protocol, args.out)
    elif args.action == "train":
        if not args.execute:
            parser.error("train runs real CPU solves; explicit --execute required")
        if ((args.max_candidates is not None and args.max_candidates < 1)
                or (args.max_seconds is not None and (not math.isfinite(args.max_seconds) or args.max_seconds <= 0))):
            parser.error("chunk limits must be positive; they do not change the total budget")
        with runner.writer(args.run_dir) as directory:
            if args.resume:
                p, s = runner.load_run(directory)
                cfg = runner.load_config(args.config)
                if p["config_sha256"] != runner.digest(cfg) or p["seed"] != args.seed:
                    raise ValueError("resume config/seed differs; no budget or parameter changes")
            else:
                p, s = runner.prepare(args.config, args.seed, directory)
            value = runner.run_loop(p, s, directory, args.max_candidates, args.max_seconds)
            runner.export(directory)
    elif args.action == "status":
        p, s = runner.load_run(args.run_dir.resolve())
        value = runner.summary(p, s)
    elif args.action == "summarize":
        value = runner.summarize_runs(args.run_dirs)
    elif args.action == "summarize-evaluations":
        value = runner.summarize_evaluations(args.run_dirs)
    elif args.action == "export":
        with runner.writer(args.run_dir) as directory:
            value = runner.export(directory)
    else:
        if not args.execute:
            parser.error("evaluate runs frozen holdout solves; explicit --execute required")
        with runner.writer(args.run_dir) as directory:
            value = runner.evaluate_frozen(args.model, args.manifest, args.reference, args.split, directory)
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
