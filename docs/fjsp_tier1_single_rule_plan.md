# Tier1 FJSP 单一通用构造规则实验计划

日期：2026-09-20。生成对象保持为现有 `priority()`：输入当前可选工序–机器组合的七个状态特征，输出有限数值；固定调度器选择最大值。本实验不引入 Swap、Insertion 或其他局部搜索算子。

## 入口检查

仓库已有通用单规则 EoH 实现 `code/llm4ad/method/eoh/`，官方调用示例为 `examples/training/obp_set/run_eoh.py`。`EoH._sample_evaluate_register()` 在 Evaluation 返回逐实例 list 时，自动用 `np.mean(score)` 作为单规则 fitness，并把原向量保存在 `score_list`。因此本实验直接复用现有 `FJSPSetEvaluation`、实例加载器、模板、固定调度器和合法性检查，不修改 EoH 核心。

## 固定流程

1. 每个候选在原有 21 个 train 实例上按固定顺序评价，EoH fitness 是21个 `-makespan/lower_bound` 的算术平均值。
2. EoH population 只按该标量 training fitness 演化。
3. 演化结束后仅评价 final population 的11实例 validation 向量；以 validation 平均分最高者作为唯一最终规则，平分取较小 population index。
4. 最终规则仅在 train 和 validation 上与 EFT、SPT、MWKR、正式 EoH-S `heuristic_0` 比较。
5. 固定的28实例 test split 不参与本轮生成、选择、比较或修改。

## 预算

| 阶段 | seed | samples | generations | population | sampler/evaluator |
| --- | ---: | ---: | ---: | ---: | ---: |
| smoke | 2026092001 | 6 | 5 | 2 | 1/1 |
| formal | 2026092002 | 40 | 10 | 5 | 1/1 |

两个阶段都使用 `deepseek-flash`，单候选训练批次 timeout 为180秒。宿主 Python 和 NumPy seed 固定；API 没有可确认的服务端 seed，因此源码生成不保证可逐字重放。

## 预先确定的报告指标

- train/validation 的平均与中位 normalized score、makespan、可行率和运行时间；
- 最终规则分别相对 EFT、SPT、MWKR、EoH-S `heuristic_0` 的逐实例胜/平/负和 score 差；
- 原有 `jobs × machines`、jobs、machines 分组；
- 最终规则平均 score 最低的精确规模组，以及相对 EFT 平均 score gap 最低的精确规模组；
- 已评价候选中的无效数量、无效率、生成时间、预算和 seed。

先运行 smoke 并检查候选生成、21维 score vector、均值聚合、final population 导出、validation 选择和基线比较。检查通过后，使用独立的新日志目录运行 formal，不从 smoke 结果改变预算、选择规则或分组。
