# Tier2-Offline-Prototype-v1

这是最小离线**接口验证原型**。H 是临时固定演示集合，直接复用
`experiments/tier1/preflight.py` 中的 EFT 和 SPT：编号 0 为 EFT，编号 1 为 SPT。
它不是正式 EoH-S 集合，也没有完成 Tier1 集合生成。两个 U 均为手写确定性示例：

- `constant_u(state)` 始终返回 0（EFT）。
- `state_u(state)` 在机器 ready time 不一致时返回 0，否则返回 1（SPT）。
  这只用于展示状态选择，不声称策略质量或泛化能力。

## 为什么单独版本化

上级 README 和冻结基线文档中的 Tier2 七特征包装层是旧边界。
逐动作 `priority(...)` 无法直接提供“每个排程步骤仅调用一次 U”的生命周期。
本目录的 `manifest.json` 明确登记新实验版本；实现位于
`code/fjsp_usage/offline_v1.py`。这里增加独立的调度入口，不修改或替换
`fjsp_set`、Tier1 规则、原清单、原始 README 或冻结评价协议。

原调度器没有逐步扩展接口，因此新循环显式沿用其 append-only 更新方式、七特征定义、
最高分选择、同分枚举顺序和有限标量检查。实例读取、EFT/SPT 实现、Schedule 类型、
独立可行性检查、lower bound 和 `FJSPSetEvaluation.score_makespan` 直接复用原代码。
回归测试逐项比较新旧循环的动作输入、完整排程和分数，防止语义漂移。

## 两层接口

`U(StateSummary) -> int`：每步开始时构造不可变快照，然后调用 U **一次**。
快照包含已排工序数 `step`、总工序数、各作业剩余工序数、各作业剩余最短加工时间和、
作业及机器 ready time，以及合法动作数量。完成的作业保留在元组中，剩余值为零。
U 不接收单个动作的七特征，也不接收可变调度数组。

仅接受 `type(id) is int` 且 `0 <= id < len(H)`；bool、NumPy 整数、int 子类、
浮点数和越界编号均拒绝。U 的异常包装为 `InvalidSelectionError` 并保留异常原因；
不重试、不回退、不静默替换。此原型用于受信任的手写函数，不是生成代码沙箱。

`h(processing_time, remaining_work, remaining_operations, job_ready_time,
machine_ready_time, earliest_start, earliest_finish) -> finite real scalar`：
U 返回编号后绑定唯一的 h，然后才枚举所有合法“下一工序—机器”动作。
每个动作只用该 h 评分，最高分动作被执行一次，再进入下一步。
这里没有把选择逻辑放进逐动作 priority 回调。

最终使用原验证器检查完整排程，并计算 makespan 和 `-makespan / lower_bound`
（越大越好）。结果同时保留每步选中的成员编号。

## 运行

在仓库根目录运行（使用现有虚拟环境和 requirements.txt）：

```bash
.venv/bin/python experiments/tier2/offline_v1/run_demo.py
.venv/bin/python experiments/tier2/offline_v1/run_demo.py --selector state
PYTHONPATH=code .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

默认读取本目录可提交的 `tiny.fjsp`，与既有测试中的两作业、两机器、三工序微型实例一致，
不依赖未提交的 benchmark 数据。也可显式传入 `--instance /path/to/example.fjsp`。
默认结果：lower bound = 4；常量 U 选择 `[0, 0, 0]`，状态 U 选择 `[1, 0, 1]`；
两者均可行，makespan = 4，score = -1.0。固定 SPT 的对照为 makespan = 6、score = -1.5。

测试覆盖每步一次 U、先选后评分、同一步只使用选定 h、状态快照及输入隔离、非法编号
和异常拒绝、后续步骤的非法选择、规则分数校验、同分行为，以及固定 U 对两个原始
单规则调度器的完整排程/七特征/评分一致性（微型实例加 20 个固定种子合成实例）。

## 完成边界

已跑通的是实例读取 → 状态摘要 → 手写 U → 固定演示 H → 完整排程 → 可行性 → 归一化评分。
没有调用 LLM，没有实现交叉、变异、正式 EoH-S 集合生成、LLM 生成 U、训练或演化实验。
默认演示和测试只使用合成实例，没有评价 train/validation/test 划分。

冻结验证入口 `verify_portable_baseline.py` 会校验规则文件哈希。开发此原型前，四个规则文件
已有未提交改动，与冻结清单不匹配；这些改动和清单均保留。因此不能将当前工作区宣称为
已通过完整冻结哈希验证，单元测试结果与该验证分开报告。
