#!/usr/bin/env python3
"""Summarize existing R15 training exports without extracting or running them."""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics
from zipfile import BadZipFile, ZipFile


MATRIX_SEEDS = {501, 502, 503}
TARGET = 1000
POLICY = "successful-evolution-responses-v1"


def read_export(path):
    with ZipFile(path) as archive:
        files = set(archive.namelist())
        if "batch-status.json" not in files:
            raise ValueError(f"{path} is not an R15 workbench export")
        batch = json.loads(archive.read("batch-status.json"))
        if batch["mode"] != "real":
            raise ValueError(f"{path} is a Mock export")
        rows = []
        for member in batch["members"]:
            group, seed, run_id = member["group"], member["seed"], member["run_id"]
            name = f"{run_id}/summary.json"
            row = {
                "batch": batch["batch"], "group": group, "seed": seed, "run_id": run_id,
                "phase": member["phase"], "successful_evolution": member["successful_evolution"],
                "target": member["target"], "archive": str(path),
                "best_training_J": None, "exclusion": "summary_not_exported",
            }
            rows.append(row)
            if name not in files:
                continue
            summary = json.loads(archive.read(name))
            if summary.get("candidate_policy_version") != POLICY or summary.get("engineering_only") is not False:
                raise ValueError(f"{path}: {run_id} does not carry real R15 candidate accounting")
            if (summary["run_id"] != run_id or summary["problem"] + "-" + summary["method"] != group
                    or summary["phase"] != member["phase"]
                    or summary["successful_evolution_target"] != member["target"]):
                raise ValueError(f"{path}: summary identity or state differs for {run_id}")
            count = summary["successful_evolution_responses"]
            if type(count) is not int or not 0 <= count <= row["target"]:
                raise ValueError(f"{path}: invalid success count for {run_id}")
            best = summary["best_J"]
            if best is not None and (type(best) not in (int, float) or not math.isfinite(best)):
                raise ValueError(f"{path}: invalid training J for {run_id}")
            if seed not in MATRIX_SEEDS or row["target"] != TARGET:
                exclusion = "outside_formal_matrix"
            elif row["phase"] != "completed" or count != TARGET:
                exclusion = "search_incomplete"
            elif best is None:
                exclusion = "no_valid_training_champion"
            else:
                exclusion = None
            row.update(successful_evolution=count, best_training_J=best, exclusion=exclusion)
            for key in ("champion_id", "initialization_attempts", "evolution_attempts",
                        "valid_candidates", "failures", "duplicates", "request_reservations",
                        "confirmed_sends", "api_failed_attempts", "unknown_usage_attempts",
                        "known_tokens", "physical_passes", "actual_cost", "source_H_cost"):
                row[key] = summary.get(key)
    return batch["batch"], rows


def summarize(paths):
    by_group = defaultdict(list)
    seen_batches = set()
    for path in paths:
        batch, rows = read_export(path)
        if batch in seen_batches:
            raise ValueError(f"multiple snapshots for {batch}; select one export per batch")
        seen_batches.add(batch)
        seen_members = set()
        for row in rows:
            group_seed = row["group"], row["seed"]
            if group_seed in seen_members:
                raise ValueError(f"duplicate member in {batch}: {group_seed}")
            seen_members.add(group_seed)
            by_group[(batch, row["group"])].append(row)

    groups = []
    for (batch, group), rows in sorted(by_group.items()):
        rows.sort(key=lambda row: row["seed"])
        included = [row for row in rows if row["exclusion"] is None]
        values = [row["best_training_J"] for row in included]
        seeds = [row["seed"] for row in included]
        groups.append({
            "batch": batch, "group": group, "included_seeds": seeds,
            "missing_or_excluded_seeds": sorted(MATRIX_SEEDS - set(seeds)),
            "complete_three_seed_comparison": set(seeds) == MATRIX_SEEDS,
            "mean_training_J": statistics.mean(values) if values else None,
            "sample_std_training_J": statistics.stdev(values) if len(values) > 1 else None,
            "members": rows,
        })
    return {"score_scope": "training_only", "completion_policy": POLICY, "groups": groups}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exports", nargs="+", type=Path, help="ZIPs from experiment.py export")
    parser.add_argument("--out", type=Path, help="new JSON report file, otherwise print to stdout")
    args = parser.parse_args()
    try:
        report = json.dumps(summarize(args.exports), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.out is None:
            print(report, end="")
        else:
            with args.out.open("x", encoding="utf-8") as output:
                output.write(report)
    except (OSError, ValueError, KeyError, TypeError, BadZipFile) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
