"""从工作台现有状态快照生成科研实验进展汇报。"""

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import re
from statistics import mean, stdev


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "reports/experiment-status-snapshot.json"
REPORT = ROOT / "reports/RESEARCH_PROGRESS.md"
METHODS = {"u": "U", "eoh": "EoH", "ross": "Ross-style", "fixed": "Best Fixed H"}
PROTOCOL = {"u": "R15", "eoh": "R15", "ross": "Ross-v1", "fixed": "固定 H"}
PROBLEMS = {"tsp": "TSP（旅行商）", "fjsp": "FJSP（柔性作业车间调度）", "obp": "OBP（在线装箱）"}
SEEDS = (501, 502, 503)


def training_done(row):
    return row.get("train_state") == "completed" and (
        row["method"] == "fixed" or (row.get("target") or 0) > 0 and row.get("count") == row["target"])


def assessed(row, splits):
    identity = row.get("holdout_identity") or ()
    return (training_done(row) and row.get("champion_state") == "verified"
            and row.get("holdout_state") == "completed" and len(identity) == 3 and identity[0] in splits
            and all(type(row.get(k)) in (float, int) and math.isfinite(row[k])
                    for k in ("holdout_J", "train_J")))


def formal(row):
    return assessed(row, ("test", "prospective-confirmation"))


def current_rows(records):
    groups = defaultdict(list)
    for row in records:
        method = row["method"]
        seeds = (None,) if method == "fixed" else SEEDS
        if method in PROTOCOL and row["version"] == PROTOCOL[method] and row["seed"] in seeds:
            groups[row["problem"], method, row["seed"]].append(row)
    selected = {}
    for key, rows in groups.items():
        completed = [r for r in rows if training_done(r)]
        if len(completed) > 1:
            # 等研究人员确认正式重复的身份，禁止按外评取舍。
            selected[key] = {"method": key[1], "train_state": "ambiguous"}
        else:
            selected[key] = completed[0] if completed else max(
                rows, key=lambda r: (r["as_of"], r.get("count") or 0))
    return selected


def progress(rows, method):
    if method == "fixed":
        return ("已完成训练集筛选" + ("，外评完成" if formal(rows[0]) else "，待外评")
                if training_done(rows[0]) else "暂无已核实结果")
    completed = sum(training_done(r) for r in rows)
    evaluated = sum(formal(r) for r in rows)
    validated = sum(assessed(r, ("validation",)) for r in rows)
    parts = [f"{completed}/3 个种子训练已完成"] if completed else []
    running = [str(seed) for seed, r in zip(SEEDS, rows) if r.get("train_state") in ("running", "launching")]
    if running:
        parts.append("种子 " + "、".join(running) + " 最近回执为训练中")
    if any(r.get("train_state") == "ambiguous" for r in rows):
        parts.append("有重复身份待确认")
    if not parts:
        parts.append("训练尚无完成回执")
    if completed:
        parts.append(f"正式外评 {evaluated}/3" if evaluated else "待正式外评")
    if validated:
        parts.append(f"验证 {validated}/3")
    return "；".join(parts)


def stats(rows, field):
    values = [r[field] for r in rows]
    return f"{mean(values):.6f} ± {stdev(values):.6f}"


def render(records):
    selected = current_rows(records)
    snapshot_date = max((r["as_of"][:10] for r in records if re.match(r"\d{4}-\d{2}-\d{2}", r["as_of"])),
                        default="日期待核验")
    lines = ["# 科研实验进展汇报", "", f"数据截至 {snapshot_date} 的已核实记录。运行中的实验采用最近回执。", "",
             "[论文实验图表与统计口径](paper-figures/README.md)", "", "## 研究目标与对照方法", "",
             "研究的是根据问题状态选择启发式规则，能否在训练之外获得更好的解。"
             "**U** 用语言模型演化路由程序，在给定规则库中按状态选规则。"
             "**EoH** 同样用语言模型，直接演化一条完成构造决策的规则。"
             "**Ross-style** 用遗传搜索学习状态原型，再按最相近的原型选规则，全程无模型调用。"
             "**Best Fixed H** 从同一规则库按训练成绩选一条规则，所有状态都使用这条规则。", "",
             "各方法各自用训练表现选冠军，并固定冠军后再外评。U 与 EoH 按成功返回的候选计预算，"
             "Ross-style 按预定评价槽计预算，固定规则只做筛选。这些口径的计算成本不同。"
             "J 是每个实例相对参照成本的差距再取平均，越小越好。", "",
             "## 整体实验进度", "",
             "| 问题 | U | EoH | Ross-style | Best Fixed H |", "| --- | --- | --- | --- | --- |"]
    by_set = defaultdict(dict)
    for problem, label in PROBLEMS.items():
        cells = []
        for method in METHODS:
            seeds = (None,) if method == "fixed" else SEEDS
            rows = [selected.get((problem, method, seed), {"method": method}) for seed in seeds]
            cells.append(progress(rows, method))
            if method != "fixed" and all(formal(r) for r in rows):
                identities = {tuple(r["holdout_identity"]) for r in rows}
                if len(identities) == 1:
                    by_set[problem, next(iter(identities))][method] = rows
        lines.append("| " + " | ".join([label, *cells]) + " |")
    lines += ["", "## 已完成的正式比较", ""]
    comparisons = {k: v for k, v in by_set.items() if len(v) >= 2}
    tsp = {}
    for (problem, identity), methods in by_set.items():
        sample = next(iter(methods.values()))[0]
        dataset = sample.get("holdout_set") or "已预先指定的留出集"
        if problem == "tsp" and dataset == "confirm60 / D06":
            if len(methods) >= 2:
                tsp = methods
            dataset = "confirm60（60 个预先指定的训练外确认实例，用 LKH 参考路线计算相对差距）"
        lines += [f"**{PROBLEMS[problem]}**　{dataset}。每种方法 3 个独立种子，表中为均值 ± 样本标准差。", "",
                  "| 方法 | 训练 J | 训练外 J |", "| --- | ---: | ---: |"]
        for method, rows in methods.items():
            lines.append(f"| {METHODS[method]} | {stats(rows, 'train_J')} | {stats(rows, 'holdout_J')} |")
        fixed = selected.get((problem, "fixed", None), {"method": "fixed"})
        if formal(fixed) and tuple(fixed["holdout_identity"]) == identity:
            lines.append(f"| Best Fixed H（固定基线，无种子标准差） | {fixed['train_J']:.6f} | {fixed['holdout_J']:.6f} |")
        lines += ["", "| 方法 | 种子 | 训练 J | 训练外 J |", "| --- | --- | ---: | ---: |"]
        for method, rows in methods.items():
            for r in rows:
                lines.append(f"| {METHODS[method]} | {r['seed']} | {r['train_J']:.6f} | {r['holdout_J']:.6f} |")
        lines.append("")
    if not comparisons:
        lines += ["暂无至少两个搜索方法在同一套留出数据与参照上完成全部三种子的可比结果。", ""]
    lines += ["## 初步科学发现", ""]
    if tsp:
        averages = {m: mean(r["holdout_J"] for r in rows) for m, rows in tsp.items()}
        best = min(averages, key=averages.get)
        detail = ""
        if {"u", "eoh", "ross"} <= averages.keys():
            detail = (f"EoH 与 U 的均值相差 {abs(averages['eoh'] - averages['u']):.6f}，"
                      f"U 与 Ross-style 相差 {abs(averages['u'] - averages['ross']):.6f}。")
        lines.append(f"- **TSP**　{METHODS[best]} 的训练外平均 J 最低。{detail}"
                     "每种方法只有 3 次独立搜索，尚不能由此判断差异的统计显著性或跨问题优势。")
    else:
        lines.append("- **TSP**　正式比较需等同一套确认实例上的三种子结果齐备。")
    findings = {
        "fjsp": "test28 是 28 个 Behnke 留出测试实例，数据与参照已核对。",
        "obp": "validation32 是 32 个验证实例，数据与参照已核对。最终测试另用预先指定的测试集。",
    }
    for problem, note in findings.items():
        existing = [methods for (p, _), methods in comparisons.items() if p == problem]
        result = ("各验证集的结果见正式比较表，现有重复仍不足以判断跨问题优势。" if existing else
                  "目前只有训练结果，尚不能判断各方法的泛化差异。")
        lines.append(f"- **{problem.upper()}**　{note}{result}")
    lines += ["", "## 尚未完成的实验", ""]
    for problem in PROBLEMS:
        train, holdout = [], []
        for method, label in METHODS.items():
            seeds = (None,) if method == "fixed" else SEEDS
            rows = [selected.get((problem, method, s), {"method": method}) for s in seeds]
            if not all(training_done(r) for r in rows):
                train.append(label)
            if any(training_done(r) and not formal(r) for r in rows):
                holdout.append(label)
        gaps = []
        if train:
            gaps.append("待完成训练或基线筛选的有 " + "、".join(train))
        if holdout:
            gaps.append("已有训练结果待外评的有 " + "、".join(holdout))
        if gaps:
            lines.append(f"- **{problem.upper()}**　" + "；".join(gaps) + "。")
    lines += ["", "历史训练采用过不同的计数口径，原记录保存在工程附录。"
              "曾用于方法开发的数据只按其既定用途报告，不能作为全新独立测试。", "",
              "## 下一步科研工作", "",
              "1. 整理 TSP 的 confirm60 逐实例差异，结合三种子波动解释 EoH、U 与 Ross-style 的表现。",
              "2. 补齐 FJSP 各方法的计划训练，按预先指定的留出集评价冻结冠军。",
              "3. 完成 OBP 的 U 训练，核实最终测试集身份后，在相同实例上比较 U、EoH 和固定规则基线。", "",
              "[实验状态矩阵与原始结果索引](EXPERIMENT_STATUS.md) · [工程附录与复现入口](../PROJECT_MAP.md)", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="写入 reports/RESEARCH_PROGRESS.md")
    args = parser.parse_args()
    snapshot = json.loads(SNAPSHOT.read_text())
    if snapshot.get("schema") != 1 or not snapshot.get("records"):
        parser.error("缺少可读的状态快照，请先运行工作台 dashboard --refresh")
    report = render(snapshot["records"])
    if args.refresh:
        REPORT.write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
