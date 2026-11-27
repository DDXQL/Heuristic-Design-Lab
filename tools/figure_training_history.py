"""Export ordered, settled training scores from deployed real runs (read-only)."""

import argparse
import csv
from hashlib import sha256
import json
import math
from pathlib import Path
import sys


COLUMNS = ("problem", "method", "seed", "run_id", "protocol_sha256", "phase", "count_basis", "target",
           "step", "candidate_J", "best_J", "source")


def checkpoint_series(run):
    protocol = (run / "Protocol.json").read_bytes()
    frozen = json.loads(protocol)
    config = frozen["config"]
    if config.get("api_mode") != "real" or config.get("evaluation_mode") != "solve" or not config.get("candidate_policy"):
        return []
    identity = sha256(protocol).hexdigest()
    state = json.loads((run / "checkpoint.json").read_bytes())
    if state["identity"] != identity or frozen["run_id"] != run.name:
        raise ValueError("checkpoint and protocol identity differ")
    tasks = state["tasks"]
    count, best, rows = 0, None, []
    meta = dict(problem=config["problem"], method=config["method"], seed=config["search_seed"], run_id=run.name,
                protocol_sha256=identity, phase=state["phase"], count_basis="successful_responses",
                target=config["evolution_request_cap"], source=str(run / "checkpoint.json"))
    for index in range(state["cursor"]):
        task = tasks[f"SLOT-{index:07d}"]
        if task["status"] != "completed":
            raise ValueError("settled candidate order is incomplete")
        score = task.get("J") if task.get("valid") else None
        if score is not None:
            if not math.isfinite(score):
                raise ValueError("non-finite training score")
            best = score if best is None else min(best, score)
        if task.get("successful_evolution_response"):
            count += 1
            rows.append({**meta, "step": count, "candidate_J": score, "best_J": best})
    if count != state.get("successful_evolution_responses", 0):
        raise ValueError("successful-response counter disagrees with settled candidate history")
    return rows


def collect(roots):
    seen = set()
    for root in roots:
        for pattern in ("plans/*/Shared.json", "*/plans/*/Shared.json"):
            for manifest in sorted(root.glob(pattern)):
                doc = json.loads(manifest.read_bytes())
                if doc.get("mode") != "real" or not doc.get("candidate_policy"):
                    continue
                for item in doc["members"]:
                    run = Path(item["run_dir"])
                    if run in seen or not (run / "checkpoint.json").is_file():
                        continue
                    seen.add(run)
                    try:
                        yield from checkpoint_series(run)
                    except (OSError, KeyError, ValueError) as exc:
                        print(f"{run.name}: {exc}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="+")
    args = parser.parse_args()
    writer = csv.DictWriter(sys.stdout, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(collect(args.root))


if __name__ == "__main__":
    main()
