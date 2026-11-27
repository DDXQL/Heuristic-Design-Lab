"""Read audited TSP results and replay the frozen U routes on train20."""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
from hashlib import sha256
import json
import math
from pathlib import Path
from statistics import mean
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
SEEDS = (501, 502, 503)
PHASES = ("前段", "中段", "后段")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def close(a, b):
    return math.isclose(a, b, rel_tol=0, abs_tol=1e-12)


def csv_write(path, rows):
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def rows_from_zip(packet, name):
    return list(csv.DictReader(packet.read(name).decode().splitlines()))


def check_zip(path):
    require(digest(path) == path.with_suffix(".zip.sha256").read_text().split()[0], f"checksum differs: {path.name}")
    return ZipFile(path)


def fixed_comparison(outbox, packets, protocol):
    with check_zip(outbox / "tsp-best-fixed-h-confirm60-20261126.zip") as fixed, check_zip(
            outbox / "tsp-confirm60-external-results-20261126.zip") as external:
        plan = json.loads(fixed.read("evaluation-plan.json"))
        frozen = json.loads(fixed.read("frozen-fixed-h.json"))
        raw = fixed.read("training-selection/fixed-results.json")
        selection = json.loads(raw)
        require(sha256(raw).hexdigest() == frozen["training_selection_results_sha256"], "fixed train selection changed")
        library = protocol["members"]
        refs = [r["reference"] for r in protocol["references"]]
        require(selection["H_keys"] == [h["key"] for h in library]
                and selection["identity"]["references"] == protocol["references"], "different training assets for fixed H")
        fixed_by_h = [[(length - ref) / ref for length, ref in zip(costs, refs, strict=True)]
                      for costs in selection["costs"]]
        scores = [mean(v) for v in fixed_by_h]
        winner = min(range(len(scores)), key=lambda h: (scores[h], h))
        require(winner == frozen["H_index"] and library[winner] == frozen["candidate"]
                and all(close(j, v) for j, v in zip(scores, selection["J_by_H"], strict=True))
                and close(scores[winner], frozen["training_J"]), "fixed H disagrees with training-only ranking")
        seeds = rows_from_zip(external, "seed-results.csv")
        for row in seeds:
            key = (row["method"], int(row["seed"]))
            require(row["complete"] == "True" and row["manifest_sha256"] == plan["manifest_sha256"]
                    and row["reference_sha256"] == plan["reference_sha256"]
                    and row["champion_sha256"] == packets[key]["champion_sha256"], "confirm60 final identity differs")
        previous = rows_from_zip(external, "per-instance.csv")
        base = {r["instance"]: r for r in rows_from_zip(fixed, "per-instance.csv")}
        require(len(base) == 60 and len(previous) == 540, "confirm60 coverage differs")
        per_seed = defaultdict(dict)
        for row in previous:
            seedkey = (row["method"], int(row["seed"]))
            name = row["file"]
            require(name not in per_seed[seedkey] and float(row["D06_reference"]) == float(base[name]["LKH_reference"]),
                    "confirm60 reference or row uniqueness differs")
            per_seed[seedkey][name] = float(row["J"])
        fixed_mean = mean(float(row["J"]) for row in base.values())
        wins = Counter()
        for name, row in base.items():
            diff = mean(per_seed["u", s][name] for s in SEEDS) - float(row["J"])
            wins["tie" if abs(diff) <= 1e-12 else "U" if diff < 0 else "H0"] += 1
        info = {"H_index": winner, "train_J_by_H": scores, "train_J": scores[winner], "confirm60_J": fixed_mean,
                "U_minus_fixed_paired_counts": wins, "confirm60_manifest_sha256": plan["manifest_sha256"],
                "confirm60_reference_sha256": plan["reference_sha256"],
                "confirm60_method_J": {
                    m: mean(float(r["confirm60_J"]) for r in seeds if r["method"] == m) for m in ("u", "eoh", "ross")},
                "confirm60_used_for_followup_diagnosis": True, "confirm60_new_solves": 0}
    return info, fixed_by_h


def search_summary(summaries, protocols, history, champions):
    curves = defaultdict(list)
    with gzip.open(history, "rt") as file:
        for row in csv.DictReader(file):
            curves[row["method"], int(row["seed"])].append(row)
    stats, improvements = [], []
    for (method, seed), summary in summaries.items():
        key = (method, seed)
        protocol = protocols[key]
        path = curves[key]
        require([int(r["step"]) for r in path] == list(range(1, 1001))
                and all(r["protocol_sha256"] == champions[key]["protocol_sha256"] for r in path)
                and close(float(path[-1]["best_J"]), summary["best_J"]), f"curve not bound for {key}")
        prev = float(path[0]["best_J"])
        require(not path[0]["candidate_J"] or float(path[0]["candidate_J"]) > prev,
                "first candidate may already improve initialization")
        updates = []
        for r in path[1:]:
            value = float(r["best_J"])
            if value < prev:
                require(close(float(r["candidate_J"]), value), "improvement not caused by this candidate")
                updates.append({"method": method, "seed": seed, "evolution_step": int(r["step"]),
                                "previous_best_J": prev, "new_best_J": value, "gain_J": prev - value,
                                "operator": ""})
                prev = value
        if method == "u":
            evolution_source = "code/heuristic_design/core/evolution_v1.py"
            require(digest(ROOT / evolution_source) == protocol["source_files"][evolution_source],
                    "CROSS/MUTATE order differs from frozen source")
            generation, parent, operator = summary["champion_id"].split("-")
            n = protocol["config"]["population_size"]
            slot = (int(generation[1:]) - 1) * (2 * n) + 2 * int(parent) + (1 if operator == "CROSS" else 2)
            require(slot == updates[-1]["evolution_step"],
                    f"{key}: missing responses before champion prevent exact operator alignment")
            # In the pinned U plan CROSS and MUTATE alternate for each frozen parent.
            # Equal physical and successful indices at the last record imply zero exclusions before it.
            for row in updates:
                row["operator"] = "CROSS" if row["evolution_step"] % 2 else "MUTATE"
        improvements.extend(updates)
        pop_ops = Counter(r["operator"] for r in updates)
        physical = summary["physical_passes"]
        full = physical["recheck"]["completed"] // 20
        evals = summary["unique_evaluation_reservations"]
        duplicates = summary["duplicates"]
        excluded = summary["evolution_attempts"] - summary["successful_evolution_responses"]
        require(physical["recheck"]["completed"] == physical["first"]["completed"] == full * 20
                and summary["physical_passes_unsettled"] == 0 and excluded == summary["api_failed_attempts"],
                "evaluation or request totals not fully reconciled")
        # This is an accounting residual. The aggregate summaries do not
        # identify the per-candidate parser error or its subtype.
        residual = summary["cursor"] - evals - duplicates - excluded
        require(min(full, evals-full, residual) >= 0, "impossible accounting totals")
        stats.append({"method": method, "seed": seed, "evolution_successes": len(path),
                      "total_slots_include_initialization": summary["cursor"],
                      "valid_evolution_records": sum(bool(r["candidate_J"]) for r in path),
                      "valid_including_initialization": summary["valid_candidates"],
                      "AST_duplicates_including_initialization": duplicates,
                      "unique_evaluation_started": evals, "unique_full_evaluations": full,
                      "incomplete_evaluations": evals - full,
                      "reported_API_failed_attempts": summary["api_failed_attempts"],
                      "non_evaluated_residual": residual,
                      "physical_solve_starts": sum(p["started"] for p in physical.values()),
                      "strict_improvements": len(updates),
                      "CROSS_improvements": pop_ops["CROSS"] if method == "u" else "",
                      "MUTATE_improvements": pop_ops["MUTATE"] if method == "u" else "",
                      "CROSS_sum_gain_J": sum(r["gain_J"] for r in updates if r["operator"] == "CROSS") if method == "u" else "",
                      "MUTATE_sum_gain_J": sum(r["gain_J"] for r in updates if r["operator"] == "MUTATE") if method == "u" else "",
                      "best_at_evolution_start": float(path[0]["best_J"]), "final_J": summary["best_J"],
                      "champion_step": updates[-1]["evolution_step"]})
    return stats, improvements


def replay_train(packets, protocols, fixed_by_h, path):
    from experiments.triad import problems
    from heuristic_design.core import routing_state_a_v3 as language
    from heuristic_design.problems.tsp.routing import construct_state_a_v3
    from heuristic_design.problems.tsp.solver import distances

    common = protocols["u", 501]
    library = [problems.compile_h("tsp", h) for h in common["members"]]
    instance_routes, routes, per_phase, pairs, diversity, reads = [], [], [], [], [], []
    all_agreement = Counter()
    all_count = 0
    expected_steps = 0
    with gzip.open(path / "routing-trace-train20.jsonl.gz", "wt", encoding="utf-8") as trace:
        for seed in SEEDS:
            protocol = protocols["u", seed]
            require(all(protocol[k] == common[k] for k in ("instances", "references", "members", "state_schema")),
                    "different route replay assets")
            read_counts = Counter()
            selector = language.compile_candidate(language.checked(packets["u", seed]["candidate"], 10),
                                                  10, reads=read_counts)
            chosen, phases, distinct = Counter(), defaultdict(Counter), defaultdict(Counter)
            selected_by_step = defaultdict(set)
            count = switches = comparisons = h0_matches = h0_opportunities = h0_switch_effect = 0
            tied_dominant = defaultdict(Counter)
            local_pair = Counter()
            js = []
            for index, (row, ref) in enumerate(zip(protocol["instances"], protocol["references"], strict=True)):
                filename = row["file"]
                require(row["split"] == "train" and ref["file"] == filename
                        and ref["instance_sha256"] == row["sha256"], "training reference mismatch")
                result = construct_state_a_v3(distances(row["value"]["coordinates"]), library, selector,
                                               reference=ref["reference"], trace=True)
                js.append(result.score)
                choice_steps = [s for s in result.trace if len(s["remaining"]) > 1]
                previous = None
                for step in result.trace:
                    remaining, features = step["remaining"], step["action_features"]
                    alternatives = []
                    for rule in library:
                        scores = [rule(*slot) for slot in features]
                        require(all(type(v) in (int, float) and math.isfinite(v) for v in scores), "invalid H score")
                        alternatives.append(max(zip(scores, remaining), key=lambda x: (x[0], -x[1]))[1])
                    h = step["member_id"]
                    require(alternatives[h] == step["chosen"], "recorded decision differs from official tie-break")
                    phase = PHASES[min(2, step["step"] * 3 // len(result.trace))]
                    trace.write(json.dumps({"seed": seed, "instance": filename, "phase": phase,
                                            "step": step["step"] + 1, "H": h, "chosen": step["chosen"],
                                            "num_legal": len(remaining), "counterfactual_choices": alternatives,
                                            "state": step["state"]}, ensure_ascii=False) + "\n")
                    expected_steps += 1
                    if len(remaining) < 2:
                        continue
                    chosen[h] += 1
                    selected_by_step[step["step"]].add(h)
                    chosen_city = step["chosen"]
                    diversity_count = len(set(alternatives))
                    distinct[phase][diversity_count] += 1
                    phases[phase][h] += 1
                    h0_matches += chosen_city == alternatives[0]
                    h0_opportunities += sum(city != alternatives[0] for city in alternatives) > 0
                    h0_switch_effect += h != 0 and chosen_city != alternatives[0]
                    for i, city in enumerate(alternatives):
                        for j in range(i+1, 10):
                            local_pair[i, j] += city == alternatives[j]
                        tied_dominant[i]["agreed"] += city == chosen_city
                    if previous is not None:
                        comparisons += 1
                        switches += previous != h
                    previous = h
                    count += 1
                seq = [s["member_id"] for s in choice_steps]
                instance_routes.append({"seed": seed, "instance": filename, "train_J": result.score,
                                        "fixed_H0_train_J": fixed_by_h[0][index],
                                        "oracle_fixed_H_train_J": min(v[index] for v in fixed_by_h),
                                        "distinct_used_H": len(set(seq)),
                                        "switches": sum(a != b for a, b in zip(seq, seq[1:])),
                                        "dominant_H": Counter(seq).most_common(1)[0][0]})
            require(close(mean(js), packets["u", seed]["training_J"]), f"train replay does not reproduce U {seed}")
            dominant, visits = chosen.most_common(1)[0]
            routes.append({"seed": seed, "decision_steps": count, "dominant_H": dominant,
                           "dominant_share": visits / count, "distinct_H": len(chosen), "switches": switches,
                           "switch_denominator": comparisons, "switch_share": switches / comparisons,
                           "same_city_as_H0": h0_matches / count,
                           "H0_had_alternative_share": h0_opportunities / count,
                           "non_H0_changed_city_share": h0_switch_effect / count,
                           "positions_with_different_H_across_instances": sum(len(v) > 1 for v in selected_by_step.values()),
                           "same_city_as_dominant_H": tied_dominant[dominant]["agreed"] / count,
                           "J_reproduced": mean(js)})
            for phase in PHASES:
                norm = sum(phases[phase].values())
                for h in range(10):
                    per_phase.append({"seed": seed, "phase": phase, "H": h, "count": phases[phase][h],
                                      "denominator": norm, "share": phases[phase][h] / norm})
                for k, number in sorted(distinct[phase].items()):
                    diversity.append({"seed": seed, "phase": phase, "distinct_next_cities": k,
                                      "state_count": number, "denominator": norm})
            for (i,j), agree in sorted(local_pair.items()):
                pairs.append({"trajectory_seed": seed, "H1": i, "H2": j, "states": count,
                              "same_city": agree, "same_city_share": agree / count})
            all_agreement.update(local_pair)
            all_count += count
            reads.extend({"seed": seed, "state_field": name, "reads": n} for name,n in read_counts.most_common())
    require(expected_steps == 2940, "unexpected number of route decisions")
    csv_write(path / "routing-per-instance.csv", instance_routes)
    csv_write(path / "routing-summary.csv", routes)
    csv_write(path / "routing-by-phase.csv", per_phase)
    csv_write(path / "h-decision-diversity.csv", diversity)
    csv_write(path / "h-pair-agreement.csv", pairs)
    csv_write(path / "routing-state-reads.csv", reads)
    return routes, all_agreement, all_count, diversity


def plots(path, stats, phases, pair, count):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    import numpy as np

    font = Path("/Library/Fonts/Arial Unicode.ttf")
    if font.is_file():
        font_manager.fontManager.addfont(font)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=font).get_name()
    plt.rcParams.update({"axes.spines.right": False, "axes.spines.top": False, "font.size": 10,
                         "axes.labelcolor": "#23384c", "text.color": "#23384c", "pdf.fonttype": 42,
                         "axes.unicode_minus": False, "savefig.facecolor": "white"})
    palette = plt.get_cmap("tab10").colors

    def save(fig, name):
        for ext in ("png", "pdf"):
            fig.savefig(path / f"{name}.{ext}", dpi=240, bbox_inches="tight")
        plt.close(fig)

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    names = [f"{r['method'].upper()} {r['seed']}" if r["method"] == "u" else f"EoH {r['seed']}" for r in stats]
    colors = ("#1479a5", "#d6903e", "#9c9cad", "#c57d94", "#a5bdca")
    categories = [("unique_full_evaluations", "独立完整评价"), ("AST_duplicates_including_initialization", "AST 重复"),
                  ("non_evaluated_residual", "其他未进入评价"), ("incomplete_evaluations", "评价未完整"),
                  ("reported_API_failed_attempts", "API 失败")]
    bottom = np.zeros(len(stats))
    for (key, label), color in zip(categories, colors):
        vals = np.array([r[key] for r in stats])
        ax.barh(names, vals, left=bottom, color=color, label=label, height=.66)
        bottom += vals
    ax.set(xlabel="候选数（含初始化）", title="每个种子的候选去向")
    ax.grid(axis="x", linewidth=.55, alpha=.3)
    ax.set_axisbelow(True)
    ax.invert_yaxis()
    ax.legend(loc="lower center", bbox_to_anchor=(.5,-.29), ncol=3, frameon=False, fontsize=8)
    bars = bx.barh(names, [r["physical_solve_starts"] for r in stats],
                   color=["#1479a5"]*3+["#c76522"]*3, height=.65)
    bx.bar_label(bars, fmt="%d", padding=4)
    bx.set(xlabel="实际启动的实例求解数（含复核）", title="训练求解开销", xlim=(0, 47000))
    bx.invert_yaxis()
    bx.grid(axis="x", linewidth=.55, alpha=.3)
    bx.set_axisbelow(True)
    save(fig, "01-search-efficiency")

    fig, ax = plt.subplots(figsize=(9.3,4.6), layout="constrained")
    labels = [f"{seed}  {phase}" for seed in SEEDS for phase in PHASES]
    bottom = np.zeros(len(labels))
    for h in range(10):
        vals = np.array([r["share"] for r in phases if r["H"] == h])
        ax.barh(labels, vals, left=bottom, color=palette[h], label=f"H{h}", height=.74)
        bottom += vals
    ax.invert_yaxis()
    ax.set(xlim=(0, 1), title="三个冻结 U 在训练集各阶段选择哪些规则", xlabel="所选 H 占比（每一步至少有两个可选城市）")
    ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.legend(loc="lower center", bbox_to_anchor=(.5,-.25), ncol=10, frameon=False)
    save(fig, "02-routing-by-phase")

    matrix = np.eye(10)
    for (i,j), agree in pair.items():
        matrix[i,j] = matrix[j,i] = agree/count
    fig, ax = plt.subplots(figsize=(7.4,6.3), layout="constrained")
    image = ax.imshow(matrix, cmap="Blues", vmin=0, vmax=1)
    ax.set(xticks=range(10), yticks=range(10), xticklabels=[f"H{i}" for i in range(10)],
           yticklabels=[f"H{i}" for i in range(10)], title="同一部分路径上，两个 H 选同一城市的比例")
    for i in range(10):
        for j in range(10):
            ax.text(j,i,f"{matrix[i,j]:.0%}",ha="center",va="center",fontsize=8,
                    color="white" if matrix[i,j]>.55 else "#23384c")
    fig.colorbar(image, ax=ax, shrink=.8, format=PercentFormatter(1))
    save(fig, "03-h-decision-agreement")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--outbox", type=Path, default=ROOT.parent / "transfer-outbox")
    parser.add_argument("--prototype", type=Path, default=ROOT.parent / "Heuristic-Design-Lab-prototype-hh-20261123")
    parser.add_argument("--plots-only", action="store_true", help="Render already verified metrics with Matplotlib")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.plots_only:
        result = json.loads((args.output / "metrics.json").read_text())
        with (args.output / "routing-by-phase.csv").open() as f:
            phases = [{**row, "H": int(row["H"]), "share": float(row["share"])} for row in csv.DictReader(f)]
        n = result["policy_decision_states"]
        pair = {tuple(int(k[1:]) for k in label.split("/")): round(v*n)
                for label, v in result["pooled_pair_agreement"].items()}
        plots(args.output, result["candidate_stats"], phases, pair, n)
        return
    require(sys.version_info[:2] == (3, 12), "Use Python 3.12 to validate frozen AST identities")
    sys.path[:0] = [str(args.prototype / "code"), str(args.prototype), str(args.prototype / "tools")]
    import tsp_confirm60 as confirm

    archive = args.outbox / "tsp-r15-champions-20261124.zip"
    history = ROOT / "reports/paper-figures/inputs/tsp-training-history-20261125.csv.gz"
    packets, _ = confirm.frozen_models(archive)
    stats, protocols = {}, {}
    with ZipFile(archive) as z:
        for method in ("u", "eoh"):
            for seed in SEEDS:
                key = (method, seed)
                base = f"{method}-{seed}/"
                protocols[key] = json.loads(z.read(base + "Protocol.json"))
                stats[key] = json.loads(z.read(base + "exports/summary.json"))
    fixed, fixed_by_h = fixed_comparison(args.outbox, packets, protocols["u", 501])
    search, improvements = search_summary(stats, protocols, history, packets)
    csv_write(args.output / "candidate-accounting.csv", search)
    csv_write(args.output / "strict-improvements.csv", improvements)
    routes, pairs, count, diversity = replay_train(packets, protocols, fixed_by_h, args.output)
    fixed["train_oracle_whole_instance_J"] = mean(map(min, zip(*fixed_by_h, strict=True)))
    fixed["train_oracle_H_first_tie_winners"] = Counter(
        min(range(10), key=lambda h: (fixed_by_h[h][i], h)) for i in range(20))
    d = Counter()
    for row in diversity:
        d[row["distinct_next_cities"]] += row["state_count"]
    result = {"fixed": fixed, "candidate_stats": search, "routing": routes,
              "policy_decision_states": count, "number_of_distinct_next_cities": d,
              "pooled_pair_agreement": {f"H{i}/H{j}": v/count for (i,j),v in pairs.items()},
              "input_sha256": {"champions": digest(archive), "training_history": digest(history),
                               "fixed_H": digest(args.outbox / "tsp-best-fixed-h-confirm60-20261126.zip"),
                               "confirm60": digest(args.outbox / "tsp-confirm60-external-results-20261126.zip")}}
    (args.output / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
