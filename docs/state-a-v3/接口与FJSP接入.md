# 方案A逐H历史接口与FJSP接入清单

本轮依据[共同状态笔记](https://app.notion.com/p/41204e0510d781f3a328c11ed393a1b1)选定的四类逐H信息实现，不增加候选或离线完整成绩先验。操作工作树仍为 `/Users/DDXQL/Developer/Heuristic-Design-Lab-state-a-v2`，分支 `codex/state-a-v2`，基线提交 `dd28326e6340fd3c6de75c4b3ada4ed58851bb94`。修改前工作树干净。

## 版本与字段

状态版本 `common-state-a-v3`，U接口 `pure-routing-state-a-v3`。三个问题分别使用后缀 `-fjsp`、`-tsp`、`-obp` 的schema；字段相同。机器定义见[contract.json](contract.json)。原10项数值及辅助信息的含义、尺度、窗口均保持[旧定义](../state-a-v2/共同状态定义.md)。新增以下四个长度为K的不可变数组，K为当前冻结H数，数组顺序就是H编号顺序。

| 字段 | 含义与范围 | 无记录时 |
|---|---|---|
| `h_usage_count` | 各H在当前实例中控制的成功提交次数，非负整数 | 0，可用 |
| `h_recent_usage_count` | 最近至多10次全局提交中各H的使用次数，0—10；也是增量均值的样本数 | 0，可用 |
| `h_last_use_gap_fraction` | (当前已提交次数t−该H最后提交序号ℓ)／总决策数D；[0,1)，刚用过为0 | 从未使用为None，该下标不可用 |
| `h_recent_delta_mean` | 同一全局10步窗口内，该H控制动作的归一化实际增量均值；[0,1] | 近期次数为0时None，该下标不可用；真实均值0可用 |

FJSP中D为总工序数，实际增量为部分makespan增加量／Pmax；TSP中D=n−1，增量为实际选边长／dmax，不含强制闭环；OBP中D为开始公开的总物品数，增量为新增箱数0或1。OBP只读当前物品、已开箱和到达历史，不接受未来物品序列。

每个实例、每个候选U求解都重新创建History；每个决策点先观察，U选择一条H，只有该H给合法动作评分，提交动作后再更新历史。使用次数按提交计，不按该H为多少个候选动作评分计。间隔是归一化步数，不能解释为秒。增量是描述性执行后果，不是H的收益或最终质量贡献；没有近期样本的H仍可被U选择。

新增历史更新O(1)，汇总／输出O(K＋10)，存储O(K＋10)，不额外执行H或续解；这是计算量口径，没有做求解耗时测量。

## U读取与提示

U签名保持 `def use_heuristics(state):`，返回内置int编号。原有标量和标量可用性读取不变；新增数组及其掩码只能用范围内的整数常量下标，不能用变量下标、负下标、数组别名、整个数组、循环、属性或外部调用。

```python
def use_heuristics(state):
    if state["availability"]["h_recent_delta_mean"][0]:
        if state["h_recent_delta_mean"][0] < 0.1:
            return 0
    return 1
```

这只是K至少为2时的语法示例，不是推荐选择规则。掩码也是逐H的：`state["availability"]["h_recent_delta_mean"][0]`。次数数组中的0对应true；缺失均值和间隔对应false。记录用missing_reason区分never_used和no_recent_samples，U不直接读取原因或schema元数据。

公共U模块为 `heuristic_design.core.routing_state_a_v3`，提供 `validate`、`parse`、`checked`、`compile_candidate`、`build_prompt`、`inspect_reads`。编译可传 `reads=Counter()`，记录如 `h_usage_count[2]` 与 `availability.h_recent_delta_mean[0]` 的实际读取。新Prompt沿用v2任务、H动作与评分说明，仅扩展数组读取、逐项掩码和历史定义，并使用新ABI与指纹。

## 给FJSP页的最小接入清单

1. 接入本轮交付提交及其基线，不在工程页重写状态公式。H代码、成员顺序、数据和既有动作／并列规则不因本交付改变。
2. U生成Prompt、解析、校验和编译统一使用 `core.routing_state_a_v3`；成员数传入实际K。旧v2候选的ABI和key不能改标签冒充v3，必须按新接口重新生成或显式验证为新候选。
3. 评价调用 `heuristic_design.problems.fjsp.routing.construct_state_a_v3(instance, heuristics, usage, trace=...)`。它在内部创建新的v3 History，无须工程页自行更新计数。旧 `construct_state_a` 仍返回v2状态。
4. 返回原始成本 `result.schedule.makespan`、参照 `result.reference`、相对差距 `result.score`、`result.score_direction='min'` 和v3 `result.state_schema`。沿用LB_v5及全部实例成功后才平均的规则；不得接入旧负Fitness最大化选优。
5. 新批次绑定 `state_schema=state_a_v3.schema_id('fjsp')`、`u_interface=routing_state_a_v3.ABI`、`normalization=state_a_v3.SPEC_SHA256`、`objective='relative-gap-min'`；同时绑定H顺序、训练数据、参考值、评价器、种子和动作规则。新schema不能续跑旧协议或读取旧缓存冒充已评价结果。
6. 工程页按已授权范围完成执行层接线及配置检查。本交付没有设置种群、初始化预算、模型或并发默认值，没有创建1000次正式运行。1000次演化的初始化是否另计等参数继续由本轮协议约束，不能因接口已实现而自动启动。

## TSP与OBP

TSP提供 `tsp.routing.construct_state_a_v3(..., reference=已冻结LKH长度)`，缺少参考值不会补跑LKH或NN。OBP提供 `obp.state_a_v3.extract` 和 `OnlineSession` 单步入口；数据集、H构建、完整流式求解驱动和正式评价器仍未接入。两问题适配已用手工部分状态检查，未运行构造求解。

## 离线证据与旧接口兼容

```bash
cd /Users/DDXQL/Developer/Heuristic-Design-Lab-state-a-v2
/Users/DDXQL/Developer/Heuristic-Design-Lab/.venv/bin/python tools/check_state_a_v3.py --check-only
```

该命令同时运行原10项与新增历史的离线检查；只计算手工状态、更新手工历史、执行本地U和检查源码。网络、子进程、构造求解、OBP step及模型／评价入口均被拦截。没有执行H、训练求解、正式评价或mock演化。检查原入口仍可单独运行：`tools/check_state_a.py --check-only`。

原 `state_a.py`、`routing_state_a.py`、三个v2传感器、旧机器定义、旧测试与检查脚本保持原文件。共享AST校验器只新增由v3显式开启的数组掩码规则；v1/v2默认读取边界、Prompt、指纹和key算法不变。FJSP/TSP旧构造入口默认行为不变，仅增加显式v3入口与schema选择。旧验收JSON是原提交的证据，不能当作新源码验收回执；新检查另存，不覆盖旧证据。

19项离线检查已通过，其中10项为原接口检查。完整求解一致性、部署和正式搜索由相应页面在用户授权范围内接续，不能把本轮源码与算术检查写成已经跑通1000次搜索。
