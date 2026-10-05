# Tier2-Offline-V5-Interface-v2

本版本完成静态 FJSP 的 **V5 七项状态接口与训练批量评价演示**。
H 固定为现有手写 EFT/SPT，U 为手写函数；没有生成或训练策略，输出不是研究结果。

## 依据与冲突核对

依据：[课题组学习工作 / 20260928 / 框架方案V5](https://app.notion.com/p/3e904e0510d781eba9b5f8b9114e2e70)，
2026-10-04 读取，页面最后修改时间为 `2026-09-28T15:23:03.073Z`。
具体采用 §A.3、§A.7 和 §D.1。以下定义已直接核对页面正文。

| 现有内容 | 与 V5 的差异 | 本版本处理 |
| --- | --- | --- |
| 根 README、`code/fjsp_usage/README.md` 和 `experiments/tier2/README.md` | 保留旧的七项**动作**包装接口，部分仍写着尚无 Tier2 实现 | 保留历史文档；本目录及 manifest 明确登记独立版本 |
| `offline_v1` | U 接收包含作业和机器明细的 `StateSummary` | 保留原文件；新 U 接口严格传七个标量参数 |
| 冻结 Tier1 的 `FJSPInstance.lower_bound` | 总最短工作量除以机器数后向上取整 | 新入口按 V5 原文直接除以机器数，不取整；保留冻结 LB 和评分函数 |
| 原有四个规则文件 | 任务开始时已与冻结清单 SHA-256 不一致 | 不加载为演示 H，不改规则、不更新冻结清单 |

新实现位于 `code/fjsp_usage/offline_v2.py` 和 `code/fjsp_usage/training_v2.py`。
实例 loader、排程数据类、独立可行性检查、EFT/SPT 均复用原实现；新调度循环保持
Tier1 的追加排程、七项动作输入、最高分方向、同分枚举顺序和有限实数检查。
常量 U 回归测试对比完整排程及每次 h 的七项输入，覆盖两个微型实例和 20 个固定种子合成实例。

## U 的精确定义

```python
def select_heuristic(
    progress: float,
    candidate_pair_ratio: float,
    remaining_work_mean: float,
    remaining_work_std: float,
    machine_ready_mean: float,
    machine_ready_std: float,
    previous_heuristic: int,
) -> int:
    ...
```

设工序 o 的可选机器集合为 A(o)，加工时间为 p(o,m)。实例内固定：

- `T = sum_o max_{m in A(o)} p(o,m)`：全实例每道工序的最长可选加工时间之和。
- `C = sum_j max_{o in job j} |A(o)|`：各作业内部最大可选机器数之和。
- `N` 为总工序数，`t` 为已安排工序数；这里的“完成作业”指其所有工序均已安排。

| U 输入 | 精确定义 |
| --- | --- |
| `progress` | `t/N`，不是物理时间比例 |
| `candidate_pair_ratio` | 各未完成作业的下一工序可选机器数之和除以固定 C |
| `remaining_work_mean` | 对每个**未完成**作业，累加全部未排工序的最短可选加工时间（包含当前待排工序），除以 T；再对这些值求均值 |
| `remaining_work_std` | 对上述同一组值计算总体标准差，`ddof=0`；仅剩一个作业时为 0 |
| `machine_ready_mean` | **所有机器**排程末端时间分别除以 T，再求均值；未使用机器取 0 |
| `machine_ready_std` | 对上述全部机器值计算总体标准差，`ddof=0` |
| `previous_heuristic` | 上一步实际选择的 H 编号；首步为 -1，每个实例重新初始化；不表示奖励或质量顺序 |

内部 `_SchedulingState` 保留完整排程信息，`StateFeatures` 只作内部不可变汇总。
实际调用为 `selector(*state.features())`，U 得到六个 float 和一个 int，既不接收状态对象，
也不接收 T、C、实例、候选列表、作业/机器数组或 H。终止状态不调用 U。

h 仍接收原有七项**单动作**输入，且保持原始时间量纲：
`processing_time, remaining_work, remaining_operations, job_ready_time,
machine_ready_time, earliest_start, earliest_finish`。这与 U 的七项状态输入完全不同。

每步计算摘要 → 调用 U 一次 → 校验编号 → 只有选中 h 对全部合法动作逐一评分 →
执行最高分动作并更新状态。合法动作是每个未完成作业的下一工序与其允许机器的组合；
开始时间为 `max(job_ready, machine_ready)`，同分优先作业编号再机器编号。

仅接受 `type(k) is int` 且 `0 <= k < len(H)`；bool、NumPy 整数、int 子类、浮点数和
越界值均无效。U 异常保留原因；无重试、无回退。非法 h 分数和不可行排程也导致失败。

## 批量评价与数据用途

入口只使用既有 `data/fjsp_manifest.json` 的 21 个 train 项，保持清单顺序，校验这些
文件的 SHA-256。读取 validation/test 的**文件名元数据**用于检查 split 不重叠，
不打开其数据文件；命令不提供切换到 validation/test 的参数。

每个实例先完成整个 U 的排程并通过原可行性验证器，再记录：

- 文件名、实例名、完整排程 `makespan`；
- `lower_bound = max(max_j sum_{o in j} min_m p(o,m), sum_o min_m p(o,m) / M)`；
- `score = -makespan / lower_bound`。

全部训练实例成功后，`mean_training_fitness = arithmetic_mean(score)`，越大越好。
不是平均 makespan，也不是 `-sum(makespan)/sum(LB)`。任何实例的 U/h 异常、非法返回或
不可行排程都会使整个候选 `valid=false`、`mean_training_fitness=null`；成功前缀可作为
诊断记录，但不能求子集均值。失败时命令退出码为 1。

V5 原式与冻结 Tier1 的 LB 在非整数负载项占优时不同，例如总最短工作量 3、两台机器、
最长作业最短工作量 1：v2 LB=1.5，冻结 Tier1 LB=2。新测试专门覆盖这一差异；
不同版本的归一化分数不能直接混用。本版本不声称 LB 等于最优 makespan。

数据职责保持分离：train 将来用于演化适应度；validation 将来用于最终 U* 选择；
test 只在 U*、H、接口及执行器全部固定后独立报告。本次仅评价预先手写的两个 U，
没有使用训练分数挑选最终策略，也没有验证或测试结果。

## 演示与运行

H 编号 0=EFT、1=SPT，复用 `experiments/tier1/preflight.py`。
`constant_u` 始终选择 EFT；`state_u` 在机器末端时间总体标准差大于 0 时选 EFT，
否则选 SPT。两者均只依赖给定参数和常量，不使用跨调用可变状态。
该状态规则仅用于演示接口，不预设成员在某种状态下更优。

从已有检出目录运行，无需 API 配置或安装额外依赖：

```bash
cd '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research'

# 两个手写 U，逐实例结果及平均训练适应度输出到 JSON，并打印到标准输出
.venv/bin/python experiments/tier2/offline_v2/run_training_demo.py

# 只评价其中一个 U，或指定新的结果路径
.venv/bin/python experiments/tier2/offline_v2/run_training_demo.py \
  --selector state --output runs/tier2_offline_v2/state.json

# 本版本的 14 项测试；均为合成数据，不接触 benchmark split
PYTHONPATH=code .venv/bin/python -m unittest discover -s tests -p 'test_fjsp_usage_v2.py' -v

# 全部 26 项测试，包含既有 12 项
PYTHONPATH=code .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

默认结果文件为 `runs/tier2_offline_v2/training_demo.json`，位于 Git 忽略的运行目录。
文件包含各实例指标、整批有效性、数据/源码哈希和未使用 validation/test/LLM 的标记。

2026-10-04 实际运行：两个 U 均在 21 个训练实例上完成可行排程，平均训练适应度均为
`-2.020555942170849`。例如 Behnke1：makespan=106，LB=70，score=`-1.5142857142857142`。
相同演示分数不能证明接口足够、策略互补、选择有效或具有泛化能力。

测试覆盖：T/C 和总体统计精确值、未完成作业筛选、未使用机器、单元素标准差、时间缩放
不变性、每步一次 U、仅选中 h 评分、首步/后续 previous 编号、无终止调用、非法编号与
异常、动作契约回归、平均比值、实例间重置、整批失败语义、split 分离与训练数据哈希。

## 尚未实现与保留情况

未实现正式 EoH-S H、LLM 生成 U、初始化种群、交叉/变异、父代/生存选择、演化、
验证集策略选择或独立测试。没有调用 LLM，没有模型费用。

当前仅支持受信任的手写 Python 函数。尚未实现生成代码的解析/去重、执行沙箱、外部资源
访问限制、确定性强制检查、真实超时或资源配额；抛出的 TimeoutError 可判无效，但不能
中断一个不返回的函数。七参数调用边界不是安全沙箱，不能把它当作正式生成程序评价环境。

本次只新增 v2 文件。开始前记录的 108 个已有受版本管理/未忽略文件逐项哈希复核无变化，
包括未提交的 offline_v1、原有测试及四个已修改规则。冻结清单没有改动。
四个规则的原有哈希差异仍存在，因此本次 26 项单元测试通过**不表示冻结基线验证通过**。
本次仅检查冻结文件哈希差异，没有运行会评价 validation 的完整冻结验证入口。
