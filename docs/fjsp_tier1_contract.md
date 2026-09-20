# Tier1 第一轮 FJSP 构造式 heuristic 契约

本阶段只生成构造式优先级函数；不接入 JSPAgent MA，也不生成算子使用策略。以下约定在调用 LLM 前固定。

## 候选函数

```python
def priority(processing_time: float, remaining_work: float,
             remaining_operations: int, job_ready_time: float,
             machine_ready_time: float, earliest_start: float,
             earliest_finish: float) -> float:
    ...
```

每次调用对应一个“当前作业的下一道未排工序、该工序的一台可选机器”组合。`processing_time` 是此机器上的时长；`remaining_work` 是该作业从当前工序到末尾、逐工序取最短可选时长的和；`remaining_operations` 包括当前工序。`job_ready_time` 是前一道工序完工时间，`machine_ready_time` 是该机器上已安排工序的最后完工时间；`earliest_start=max(二者)`，`earliest_finish=earliest_start+processing_time`。候选看不到验证／测试实例，也不能直接改动调度状态。

输出必须是可转为有限 Python `float` 的标量；**分数越大，组合优先级越高**。候选按作业索引、机器索引升序枚举；精确同分时固定选择先枚举的组合。不允许随机兜底、无效值或异常被静默替换：任何候选调用失败、返回 NaN/Inf/非标量、或超出整个 batch 的评估超时，均使该候选本次 `score=None`，不进入有效训练向量。

## 固定调度器和评分

调度器仅枚举每个作业当前的下一道工序及其数据文件列出的可选机器。每选中一个组合，就在该机器当前队尾以 `earliest_start` 开工、`earliest_finish` 完工，再推进该作业的工序游标并更新作业／机器就绪时间。这是确定性的 **append-only** 构造器，不搜索机器空档。前驱工序完工前不开工，同一机器按队尾顺序安排且不重叠；每道工序恰好安排一次，机器选择只能来自该工序的可选集合。独立的日程验证器在评价时复核这些约束和 makespan；当前不需要 repair。

单实例目标 `Cmax=max(所有工序完工时间)`。该实例下界 `LB=max(每个作业的最短可选时长之和, ceil(所有工序的最短可选时长之和 / 机器数))`，分数为 `-Cmax/LB`，因此**越大越好**。训练实例按固定文件顺序处理，一个有效候选返回等长、有限的 Python `list[float]`，不汇总成一个标量。下界只用于归一化，不声称它是最优 makespan。

训练、验证、测试的文件名单固定在 `examples/training/fjsp_set/split.json`；本轮 LLM 只能使用 training。验证／测试文件仅预留，未经本轮候选评价，不能据此声称泛化。
