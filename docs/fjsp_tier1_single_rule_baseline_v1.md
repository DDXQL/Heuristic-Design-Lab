# Tier1 Single-Rule Baseline v1

## 1. 目的与版本

`Tier1 Single-Rule Baseline v1` 冻结当前 FJSP“单一构造式优先级规则生成与固定使用”实现，供后续启发式使用策略研究复用。本次工作只整理、固化和重放已有结果，不生成候选，不调用 LLM，不运行演化，也不评价 test。

固定使用规则的标识是 `Tier1-Fixed-H-v1`。其来源为首次正式实验 seed `2026092002` 在三种子稳定性检查之前已经选定的：

```text
logs/fjsp_tier1_single_rule/formal01/selected_rule.py
```

选择 seed `2026092002` 是事前决定。seed `2026092003` 和 `2026092004` 仅用于复核相同低预算流程的稳定性，不能根据三次 validation 结果重新挑选表现最好的种子，也不构成第二阶段的 heuristic set。

机器可读冻结清单位于 `baselines/fjsp_tier1_single_rule_v1/manifest.json`。其中保存实际文件重新计算得到的 SHA-256、规则来源、组件、配置、划分、运行参数和结果摘要。

## 2. 冻结的候选接口

```python
def priority(
    processing_time: float,
    remaining_work: float,
    remaining_operations: int,
    job_ready_time: float,
    machine_ready_time: float,
    earliest_start: float,
    earliest_finish: float,
) -> float:
    ...
```

七个特征的定义如下：

| 特征 | 定义与约束 |
|---|---|
| `processing_time` | 当前工序在候选机器上的加工时间，正数 |
| `remaining_work` | 当前工序及其后续工序的最短可选加工时间之和，正数 |
| `remaining_operations` | 包含当前工序的剩余工序数量，正整数 |
| `job_ready_time` | 该 job 已排前序工序的完成时间，非负数 |
| `machine_ready_time` | 候选机器上最后一个已排工序的完成时间，非负数 |
| `earliest_start` | `max(job_ready_time, machine_ready_time)`，非负数 |
| `earliest_finish` | `earliest_start + processing_time`，正数 |

候选必须返回有限实数标量，不能返回 `bool`、字符串、数组、`NaN` 或无穷值。分数越高越先选择。固定调度器按照 job index、该工序可选 machine index 的稳定顺序枚举；完全同分时保留最早遇到的组合，因此同分规则为较小 job index 优先，再按较小 machine index 优先。

## 3. 冻结的调度与评价协议

固定调度器只枚举每个 job 的下一道未排工序及其合法机器。选中组合后从 `max(job_ready_time, machine_ready_time)` 开始加工，更新该 job 和机器的 ready time。这个 append-only 构造过程保证工序前后约束和机器不重叠。

独立合法性检查再次验证：

- 每道工序恰好出现一次；
- job、operation 和 machine index 合法；
- 所选机器属于该工序的可选机器；
- 加工时长与实例记录一致；
- job 前序约束成立；
- 同一机器区间不重叠；
- makespan 等于所有工序最大完成时间。

实例 lower bound 冻结为：每个 job 的最短加工时间和的最大值，与全部最短加工时间之和除以机器数向上取整，两者取最大值。单实例 normalized score 为：

```text
-makespan / lower_bound
```

因此 score 越大越好。训练 fitness 是固定 21 个 train 实例 score 的算术平均。最终 population 只在固定 11 个 validation 实例上选择，选择 validation 平均 score 最大者；平分时取较小 final-population index。EFT、SPT、MWKR 分别返回 `-earliest_finish`、`-processing_time`、`remaining_work`。

## 4. 数据边界

正式划分为 21 个 train、11 个 validation 和 28 个 test。v1 使用正式运行目录中的 21/11/28 split 作为 canonical split；早期 smoke 使用的 `examples/training/fjsp_set/split.json` 不是正式划分，不能用于 v1。

本次冻结验证只读取 train 和 validation。test 只在 split 元数据中保留文件名，没有加载实例内容、计算 makespan 或参与规则选择。三个正式运行记录的 `test_evaluated` 均为 `false`。

## 5. 已完成

- LLM 生成七特征工序–机器优先级函数；
- 固定调度器调用规则并构造合法日程；
- EoH 单规则训练、评价、validation 选择和导出；
- 三随机种子低成本稳定性检查；
- 将事前确定的 seed `2026092002` 规则固化为固定使用 baseline；
- 建立离线重放、哈希检查、接口检查、合法性检查和单元测试入口。

## 6. 固定使用策略

固定使用 baseline 形式化为：

```text
U_fixed(state) = Tier1-Fixed-H-v1
```

即在每一个调度决策状态，对固定调度器当前枚举的每个工序–机器组合调用同一个 `priority()`，并选择有限分数最高的组合。

## 7. 第二阶段扩展边界

第二阶段可以在相同调度器和评价协议外部增加一个包装层。该包装层仍需提供相同的七特征输入和有限标量输出；内部可以调用多个启发式、组合多个分数，或根据当前状态选择启发式。

第二阶段不得隐式修改以下内容以改善结果：

- train/validation/test 划分；
- 固定构造式调度器及同分规则；
- 七个特征的定义和数值语义；
- 可行性规则；
- lower bound；
- normalized score 和汇总口径；
- EFT 实现；
- test 数据及其使用状态。

需要改变上述任一内容时，应建立新的实验版本，并在配置、manifest 和报告中明确记录变化。

## 8. 一键验证

在仓库根目录运行：

```bash
.venv/bin/python verify_tier1_baseline_v1.py
```

验证入口不需要 API 配置，不调用 LLM，不重新演化。它检查 manifest 中的文件和 SHA-256、七特征接口、有限标量返回、内存微型实例合法性、三个规则的 train/validation 重放、EFT/SPT/MWKR 重放、划分边界、Python 语法和 `tests/test_fjsp_set.py`。

## 9. 结论边界

三种子稳定性结果是固定开发划分上的低成本复核。validation 参与每次规则选择，因此不能作为未见实例泛化证据。`Tier1-Fixed-H-v1` 的作用是提供不随第二阶段策略实验变化的固定启发式基线。
