# FJSP Tier1 单规则三种子低成本稳定性检查

## 1. 冻结协议与数据边界

本检查保留 `formal01`，新增随机种子 `2026092003` 和 `2026092004`。三次运行均使用 `max_sample_nums=40`、`max_generations=10`、`pop_size=5`、`num_samplers=1`、`num_evaluators=1`。候选仍为七特征 `priority()`；实例加载、固定调度器、合法性检查、21 个 train、11 个 validation、`-makespan/lower_bound` fitness 及 EoH 核心均冻结。每次只从该次最终 population 按 11 个 validation 实例的平均 normalized score 选择规则，平分时取较小 population index。

28 个 test 实例的内容未加载、未评价，也未用于选择或修改规则。本报告不产生新的测试结论。

冻结源码哈希审计覆盖配置中列出的 18 个文件，实际哈希与冻结值全部一致。两个新增配置与正式配置相比仅改变 `stages.formal.seed`。

| 配置 | SHA-256 |
|---|---|
| `single_rule_config.json`（2026092002） | `2ab917b041f848f5517746e3415cffaa0bf43ccec4c6b2eb782546c24186d48b` |
| `single_rule_seed_2026092003.json` | `2a7e26b912e9678a43ad71c8ab7295ac8b02ec1e1ca49de1b33958570694d0e3` |
| `single_rule_seed_2026092004.json` | `fb61acb85b631d033dd621c902f24b061dee9802341e0b8bc813f2111902c563` |
| `single_rule_stability_config.json` | `5c34a5518261dff401a999c13421d831baeadb4227a6c2218a531664e955ae48` |

以上均由实际文件重新计算，均为 64 位十六进制字符。此前文档中的正式配置值已复核为第一行所示值；先前对话里出现过的拼接错误未写入仓库文档。

## 2. 实际命令

对两个新增种子分别执行：

```bash
source config.local.sh
PYTHONPATH=code .venv/bin/python -u examples/training/fjsp_set/run_eoh_single.py --config examples/training/fjsp_set/single_rule_seed_2026092003.json --stage formal --run-dir logs/fjsp_tier1_single_rule/formal_seed_2026092003
PYTHONPATH=code .venv/bin/python examples/training/fjsp_set/evaluate_single_rule.py --config examples/training/fjsp_set/single_rule_seed_2026092003.json --run-dir logs/fjsp_tier1_single_rule/formal_seed_2026092003
PYTHONPATH=code .venv/bin/python -u examples/training/fjsp_set/run_eoh_single.py --config examples/training/fjsp_set/single_rule_seed_2026092004.json --stage formal --run-dir logs/fjsp_tier1_single_rule/formal_seed_2026092004
PYTHONPATH=code .venv/bin/python examples/training/fjsp_set/evaluate_single_rule.py --config examples/training/fjsp_set/single_rule_seed_2026092004.json --run-dir logs/fjsp_tier1_single_rule/formal_seed_2026092004
PYTHONPATH=code .venv/bin/python examples/training/fjsp_set/summarize_single_rule_stability.py
```

## 3. 每个种子的选择结果

| seed | final population index | 规则 SHA-256 | 有效/无效 | train mean score | validation mean score | 生成用时 |
|---:|---:|---|---:|---:|---:|---:|
| 2026092002 | 0 | `0991e17f833e7ab773b0ff13ea2396a0cb3ccb9d94715984fb1ef421ea89496a` | 40/0 | -2.009009 | -2.194223 | 144.20s |
| 2026092003 | 0 | `bcb91bcdd6ba6a8e915ecce8de40feee027807129724b076dc7fcd6c8fb1013f` | 40/0 | -2.049008 | -2.221950 | 165.68s |
| 2026092004 | 3 | `955e16c766fcae15254a00c5b48e2b05ac2d28847c9815c7a70f61040296c14e` | 39/1 | -2.042650 | -2.182184 | 199.48s |

种子 `2026092004` 的第 23 个候选发生 `ZeroDivisionError`，得分为 `None`，其余 119 个候选有效；总体无效率为 1/120 = 0.833%。失败候选没有进入最终 population。三个最终规则在 train 和 validation 上的可行率均为 100%。

## 4. 与四个基线的配对比较

score 差为 `selected - baseline`，越大越好；makespan 相对改善率为每个实例 `(baseline-selected)/baseline` 后取平均；胜/平/负按 makespan 配对统计。

| seed | split | baseline | selected mean | baseline mean | mean score 差 | mean makespan 改善 | 胜/平/负 |
|---:|---|---|---:|---:|---:|---:|---:|
| 2026092002 | train | EFT | -2.009009 | -2.017346 | 0.008337 | -0.088% | 10/4/7 |
| 2026092002 | train | SPT | -2.009009 | -3.283870 | 1.274860 | 34.535% | 21/0/0 |
| 2026092002 | train | MWKR | -2.009009 | -18.638845 | 16.629836 | 86.951% | 21/0/0 |
| 2026092002 | train | EoHS_heuristic_0 | -2.009009 | -2.084727 | 0.075718 | 3.085% | 13/6/2 |
| 2026092002 | validation | EFT | -2.194223 | -2.226551 | 0.032328 | 1.309% | 8/0/3 |
| 2026092002 | validation | SPT | -2.194223 | -3.776172 | 1.581949 | 40.879% | 11/0/0 |
| 2026092002 | validation | MWKR | -2.194223 | -22.354950 | 20.160727 | 88.592% | 11/0/0 |
| 2026092002 | validation | EoHS_heuristic_0 | -2.194223 | -2.282339 | 0.088116 | 4.348% | 8/3/0 |
| 2026092003 | train | EFT | -2.049008 | -2.017346 | -0.031662 | -2.150% | 9/2/10 |
| 2026092003 | train | SPT | -2.049008 | -3.283870 | 1.234862 | 33.613% | 21/0/0 |
| 2026092003 | train | MWKR | -2.049008 | -18.638845 | 16.589837 | 86.777% | 21/0/0 |
| 2026092003 | train | EoHS_heuristic_0 | -2.049008 | -2.084727 | 0.035719 | 1.329% | 10/4/7 |
| 2026092003 | validation | EFT | -2.221950 | -2.226551 | 0.004601 | -0.967% | 7/0/4 |
| 2026092003 | validation | SPT | -2.221950 | -3.776172 | 1.554222 | 39.849% | 11/0/0 |
| 2026092003 | validation | MWKR | -2.221950 | -22.354950 | 20.133000 | 88.417% | 11/0/0 |
| 2026092003 | validation | EoHS_heuristic_0 | -2.221950 | -2.282339 | 0.060389 | 2.436% | 7/2/2 |
| 2026092004 | train | EFT | -2.042650 | -2.017346 | -0.025304 | -1.828% | 5/4/12 |
| 2026092004 | train | SPT | -2.042650 | -3.283870 | 1.241219 | 33.441% | 21/0/0 |
| 2026092004 | train | MWKR | -2.042650 | -18.638845 | 16.596195 | 86.726% | 21/0/0 |
| 2026092004 | train | EoHS_heuristic_0 | -2.042650 | -2.084727 | 0.042077 | 1.331% | 12/2/7 |
| 2026092004 | validation | EFT | -2.182184 | -2.226551 | 0.044367 | 1.819% | 8/2/1 |
| 2026092004 | validation | SPT | -2.182184 | -3.776172 | 1.593988 | 41.061% | 11/0/0 |
| 2026092004 | validation | MWKR | -2.182184 | -22.354950 | 20.172766 | 88.629% | 11/0/0 |
| 2026092004 | validation | EoHS_heuristic_0 | -2.182184 | -2.282339 | 0.100155 | 4.723% | 8/0/3 |

`2026092003` 的 validation mean score 比 EFT 高 `0.004601`，但逐实例相对 makespan 改善率均值为 `-0.967%`。这是因为 normalized score 与相对改善率使用不同的实例权重和分母；因此不能将两者视为同一个统计量。

## 5. 三种子分布

| 指标 | 均值 | 样本标准差 | 中位数 | 最小值 | 最大值 | 范围 |
|---|---:|---:|---:|---:|---:|---:|
| train mean score | -2.033556 | 0.021494 | -2.042650 | -2.049008 | -2.009009 | 0.039999 |
| validation mean score | -2.199452 | 0.020392 | -2.194223 | -2.221950 | -2.182184 | 0.039766 |
| train score 差 vs EFT | -0.016210 | 0.021494 | -0.025304 | -0.031662 | 0.008337 | 0.039999 |
| validation score 差 vs EFT | 0.027099 | 0.020392 | 0.032328 | 0.004601 | 0.044367 | 0.039766 |
| train makespan 改善 vs EFT | -1.355% | 1.109% | -1.828% | -2.150% | -0.088% | 2.062% |
| validation makespan 改善 vs EFT | 0.720% | 1.484% | 1.309% | -0.967% | 1.819% | 2.786% |

三个种子的 validation mean score 全部超过 EFT（3/3）；三种子平均 score 优势为 0.027099，平均逐实例 makespan 改善为 0.720%。train 上只有一个种子的 mean score 超过 EFT，三种子平均差为 -0.016210。

## 6. 每个实例相对 EFT 的配对结果

单元格为 `selected makespan / EFT makespan (结果)`；结果从 selected 规则视角给出。完整的每个种子、每个实例、全部四个基线的 makespan、score、差值和相对改善率保存在机器可读汇总中。

### train

| 实例 | 规模 | seed 2002 | seed 2003 | seed 2004 | 合计胜/平/负 |
|---|---:|---:|---:|---:|---:|
| Behnke1.fjsp | 10×20 | 110/106 (负) | 109/106 (负) | 107/106 (负) | 0/0/3 |
| Behnke2.fjsp | 10×20 | 106/100 (负) | 116/100 (负) | 104/100 (负) | 0/0/3 |
| Behnke3.fjsp | 10×20 | 102/102 (平) | 102/102 (平) | 112/102 (负) | 0/2/1 |
| Behnke4.fjsp | 10×20 | 113/109 (负) | 115/109 (负) | 114/109 (负) | 0/0/3 |
| Behnke13.fjsp | 50×20 | 270/267 (负) | 286/267 (负) | 277/267 (负) | 0/0/3 |
| Behnke14.fjsp | 50×20 | 262/264 (胜) | 283/264 (负) | 265/264 (负) | 1/0/2 |
| Behnke19.fjsp | 100×20 | 445/438 (负) | 525/438 (负) | 437/438 (胜) | 1/0/2 |
| Behnke25.fjsp | 10×40 | 103/103 (平) | 103/103 (平) | 103/103 (平) | 0/3/0 |
| Behnke21.fjsp | 10×40 | 96/103 (胜) | 96/103 (胜) | 109/103 (负) | 2/0/1 |
| Behnke29.fjsp | 20×40 | 132/134 (胜) | 132/134 (胜) | 134/134 (平) | 2/1/0 |
| Behnke27.fjsp | 20×40 | 140/140 (平) | 133/140 (胜) | 143/140 (负) | 1/1/1 |
| Behnke33.fjsp | 50×40 | 244/247 (胜) | 239/247 (胜) | 249/247 (负) | 2/0/1 |
| Behnke34.fjsp | 50×40 | 241/250 (胜) | 258/250 (负) | 243/250 (胜) | 2/0/1 |
| Behnke36.fjsp | 100×40 | 416/426 (胜) | 405/426 (胜) | 415/426 (胜) | 3/0/0 |
| Behnke43.fjsp | 10×60 | 96/99 (胜) | 96/99 (胜) | 93/99 (胜) | 3/0/0 |
| Behnke44.fjsp | 10×60 | 95/95 (平) | 92/95 (胜) | 95/95 (平) | 1/2/0 |
| Behnke47.fjsp | 20×60 | 135/130 (负) | 128/130 (胜) | 133/130 (负) | 1/0/2 |
| Behnke46.fjsp | 20×60 | 129/121 (负) | 132/121 (负) | 138/121 (负) | 0/0/3 |
| Behnke51.fjsp | 50×60 | 238/245 (胜) | 242/245 (胜) | 245/245 (平) | 2/1/0 |
| Behnke53.fjsp | 50×60 | 229/233 (胜) | 239/233 (负) | 237/233 (负) | 1/0/2 |
| Behnke57.fjsp | 100×60 | 410/414 (胜) | 423/414 (负) | 413/414 (胜) | 2/0/1 |

### validation

| 实例 | 规模 | seed 2002 | seed 2003 | seed 2004 | 合计胜/平/负 |
|---|---:|---:|---:|---:|---:|
| Behnke5.fjsp | 10×20 | 108/100 (负) | 108/100 (负) | 100/100 (平) | 0/1/2 |
| Behnke11.fjsp | 50×20 | 259/260 (胜) | 288/260 (负) | 258/260 (胜) | 2/0/1 |
| Behnke20.fjsp | 100×20 | 447/443 (负) | 518/443 (负) | 433/443 (胜) | 1/0/2 |
| Behnke22.fjsp | 10×40 | 98/103 (胜) | 91/103 (胜) | 104/103 (负) | 2/0/1 |
| Behnke28.fjsp | 20×40 | 125/132 (胜) | 136/132 (负) | 126/132 (胜) | 2/0/1 |
| Behnke32.fjsp | 50×40 | 242/244 (胜) | 236/244 (胜) | 242/244 (胜) | 3/0/0 |
| Behnke39.fjsp | 100×40 | 428/427 (负) | 416/427 (胜) | 420/427 (胜) | 2/0/1 |
| Behnke41.fjsp | 10×60 | 93/96 (胜) | 93/96 (胜) | 96/96 (平) | 2/1/0 |
| Behnke48.fjsp | 20×60 | 137/143 (胜) | 140/143 (胜) | 137/143 (胜) | 3/0/0 |
| Behnke52.fjsp | 50×60 | 230/240 (胜) | 231/240 (胜) | 226/240 (胜) | 3/0/0 |
| Behnke58.fjsp | 100×60 | 432/435 (胜) | 428/435 (胜) | 431/435 (胜) | 3/0/0 |

## 7. 按预注册精确规模分组

这是预先存在的 `jobs × machines` 分组。validation 每个精确规模只有 1 个实例，因此下表 validation 的每组统计不能当作稳定的规模效应；三条记录只是同一个实例上的三个规则。

| split | 规模 | 每种子实例数 | 三种子 mean score 差 vs EFT | mean makespan 改善 | 合计胜/平/负 |
|---|---:|---:|---:|---:|---:|
| train | 10x20 | 4 | -0.065409 | -4.759% | 0/2/10 |
| train | 10x40 | 2 | 0.017094 | 1.294% | 2/3/1 |
| train | 10x60 | 2 | 0.036765 | 2.547% | 4/2/0 |
| train | 20x40 | 2 | 0.017119 | 0.974% | 3/2/1 |
| train | 20x60 | 2 | -0.095350 | -5.728% | 1/0/5 |
| train | 50x20 | 2 | -0.051626 | -3.134% | 1/0/5 |
| train | 50x40 | 2 | 0.036575 | 1.141% | 4/0/2 |
| train | 50x60 | 2 | 0.008709 | 0.251% | 3/1/2 |
| train | 100x20 | 1 | -0.095975 | -7.078% | 1/0/2 |
| train | 100x40 | 1 | 0.092105 | 3.286% | 3/0/0 |
| train | 100x60 | 1 | -0.013468 | -0.322% | 2/0/1 |
| validation | 10x20 | 1 | -0.075117 | -5.333% | 0/1/2 |
| validation | 10x40 | 1 | 0.077295 | 5.178% | 2/0/1 |
| validation | 10x60 | 1 | 0.029412 | 2.083% | 2/1/0 |
| validation | 20x40 | 1 | 0.041096 | 2.273% | 2/0/1 |
| validation | 20x60 | 1 | 0.067568 | 3.497% | 3/0/0 |
| validation | 50x20 | 1 | -0.051125 | -3.205% | 2/0/1 |
| validation | 50x40 | 1 | 0.051948 | 1.639% | 3/0/0 |
| validation | 50x60 | 1 | 0.144737 | 4.583% | 3/0/0 |
| validation | 100x20 | 1 | -0.071429 | -5.192% | 1/0/2 |
| validation | 100x40 | 1 | 0.037037 | 1.327% | 2/0/1 |
| validation | 100x60 | 1 | 0.046667 | 1.073% | 3/0/0 |

## 8. 成本、产物与结论边界

三次生成累计 509.37 秒；生成加已记录评价累计 576.79 秒。框架记录 120 次已评价候选生成。运行中观测到 1 次网络超时重试，因此 HTTP 请求尝试至少 121 次；底层请求次数未埋点，无法事后给出严格精确值。

机器可读汇总：`logs/fjsp_tier1_single_rule/stability_3seeds/stability_summary.json`。三个冻结规则副本与校验和位于同一目录。各运行目录保留 final population、全部生成样本、运行配置、日志、选择记录和逐实例评价结果。

- `logs/fjsp_tier1_single_rule/formal01/selected_rule.py`（seed 2026092002）
- `logs/fjsp_tier1_single_rule/formal_seed_2026092003/selected_rule.py`
- `logs/fjsp_tier1_single_rule/formal_seed_2026092004/selected_rule.py`
- `logs/fjsp_tier1_single_rule/stability_3seeds/checksums.sha256`

当前“validation 平均 normalized score 略优于 EFT”的现象在三个随机种子中都重复出现。不过优势较小且有波动：validation score 差范围为 `0.004601` 到 `0.044367`；一个种子的平均相对 makespan 改善为负，train 上有两个种子低于 EFT。validation 又参与了每次最终规则选择，且每个精确规模仅一个实例。因此该结果支持低预算搜索流程在固定开发划分上的可重复性，不能作为未见实例上的泛化证据。
