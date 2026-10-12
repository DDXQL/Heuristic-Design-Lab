# FJSP：H、U、调度与评价契约

职责：h/U输入输出、合法动作、调度、候选执行和评价口径。范围：当前research_real运行时，以及理解其继承所必需的冻结单规则/原型差异；不陈述实验进度或批准配置。项目身份与证据见[README](../README.md)，流程见[研究方案](PRD_TIER2_REAL_EXPERIMENTS_v1.md)，命令见[指南](../experiments/tier2/research_real_v1/README.md)。

## 实例和共同动作语义

[load_instance](../code/llm4ad/task/optimization/fjsp_set/instances.py)读取带 `JOB_SECTION` 的FJSP文本，生成 `FJSPInstance.jobs[j][o].alternatives`。机器内部编号从0开始，可选项按机器编号排序，加工时间为正整数；每个作业至少一项工序。下一工序游标、作业ready、机器ready初始为0。

合法动作是每个未排完作业的下一工序及其允许机器；不是只枚举某个物理时刻已空闲的机器。开始时间为 `max(job_ready, machine_ready)`，完成时间为开始时间加加工时长。动作追加到机器尾部，不搜索空档。动作执行后推进对应作业游标并更新作业/机器ready。

调度器按作业、机器编号枚举，仅当 `score > best_score` 才替换动作；因此精确同分优先较小作业编号，再较小机器编号。[construct_schedule / validate_schedule](../code/llm4ad/task/optimization/fjsp_set/scheduler.py)独立检查工序完整性、合法机器、时长、前后约束、不重叠和makespan。

## h：单动作评分程序

```python
def priority(processing_time, remaining_work, remaining_operations,
             job_ready_time, machine_ready_time, earliest_start, earliest_finish):
    ...
```

| 输入 | 含义 |
|---|---|
| processing_time | 当前动作在当前机器上的时长 |
| remaining_work | 当前作业未排工序逐项取最短可选时长后求和，含当前工序 |
| remaining_operations | 当前作业未排工序数，含当前工序 |
| job_ready_time | 本作业前序工序完成时间，初始0 |
| machine_ready_time | 本机器当前排程末端时间，初始0 |
| earliest_start | 两个ready时间的最大值 |
| earliest_finish | earliest_start + processing_time |

全部时间保持原始量纲。输出须为有限实数标量，拒绝bool及非有限值；高分先排。h不返回动作，不改调度状态，不选择另一条h。

## U：每步选择H成员

```python
def select_heuristic(progress, candidate_pair_ratio,
                     remaining_work_mean, remaining_work_std,
                     machine_ready_mean, machine_ready_std,
                     previous_heuristic):
    ...
```

当前定义来自 [offline_v2._SchedulingState](../code/fjsp_usage/offline_v2.py)，供 [research.scheduler.construct_usage_schedule](../code/fjsp_usage/research/scheduler.py)复用。令 `Q` 为全实例工序数，`t`为已安排工序数；`T=sum_o max_m p(o,m)`；`C=sum_j max_{o in j} |A(o)|`。T/C固定，不是额外U输入。

| 输入 | 精确定义 |
|---|---|
| progress | t/Q；不是物理时间比例或种群N |
| candidate_pair_ratio | 各未完成作业下一工序的可选机器数之和 / C |
| remaining_work_mean/std | 各未完成作业的remaining_work / T，再求均值/总体标准差；含当前工序 |
| machine_ready_mean/std | 全部机器的末端时间 / T，再求均值/总体标准差；含未使用机器 |
| previous_heuristic | 首步−1，之后为上一步实际成员编号；每个实例重置 |

令a为未完成作业数，m为某项均值，d为对应总体标准差。合法非终止状态满足：

| 状态 | 可证明边界 |
|---|---|
| progress | 0≤progress<1 |
| candidate_pair_ratio | 0<candidate_pair_ratio≤1 |
| remaining_work_mean | 0<mean≤1/a≤1 |
| remaining_work_std | 0≤std≤sqrt(a−1)/a≤0.5；a=1时为0 |
| machine_ready_mean | 0≤mean≤1 |
| machine_ready_std | 0≤std≤0.5 |
| previous_heuristic | 首步−1，之后为0…K−1的类别编号 |

证明：任一已提交结束时间不超过已提交加工时长之和，后者不超过T；所有归一化机器末端值在[0,1]。未完成作业最短剩余工作量之和不超过T，各项归一化值在[0,1]且和≤1。对[0,1]中的值，总体方差≤m(1−m)≤1/4；因此d/(1+m)≤sqrt(2)/4≈0.353554。边界描述实数运算，浮点轨迹核对采用1e−12余量。a/T/C不是额外U输入。

当前v5提示明确提供这些边界，v4去重归档/指令及窄等价规则保持不变；这次只改变状态尺度说明，不能归因于新的去重算法。静态区间诊断区分always_false/always_true/not_proven；最后一种不代表可达。训练诊断另作第三次观察排程，保留每步七状态、实际编号、选中动作、自然求值谓词真/假计数，核对排程与未插桩执行完全一致。未被求值、本次未取真与理论永假分别记录；冗余分支不拒绝、有限行为相同不合并程序。单次求解、确定性复检、诊断重放分别计时，主评价保持两次排程共用原instance_timeout；诊断另有同样长度的逐实例观察期限与状态，诊断超时不改变主评价valid/fitness。观察排程哈希须与主排程一致。

U得到六个float和一个int。它不接收完整实例、动作列表、机器数组、H或评价结果。返回必须满足 `type(k) is int` 与 `0 <= k < K`；bool、浮点数、越界或异常使求解失败，无重试/回退。成员编号作为类别使用；常量U合法。当前freeze_h实际上按训练均值/稳定ID排序后编号，所以较小编号与本批训练均值相关，但不是逐状态或泛化能力保证。提示要求不据编号推断质量与该分配相关性须分别理解；正式编号策略尚待决定。

```text
每步：state.features → U一次 → 校验k
    → H[k]给所有合法动作评分 → 选最高分动作 → 执行并更新state
终止：不调用U → 完整可行性检查 → Cmax/LB/score
```

H在一次求解及四组实验内固定；U在一次求解内固定。在线没有LLM调用，没有奖励更新或程序自修改。H代码及审查说明只在部分组的离线生成提示中作为设计上下文，运行U不能据此调用H。

## 评价口径不能跨版本混用

令 `w_j=sum_{o in j} min_m p(o,m)`，`W=sum_j w_j`，机器数M。

| 协议 | LB | 适用代码 |
|---|---|---|
| 冻结单规则Tier1 / offline_v1 | max(max_j w_j, ceil(W/M)) | [FJSPInstance.lower_bound](../code/llm4ad/task/optimization/fjsp_set/instances.py)、[FJSPSetEvaluation](../code/llm4ad/task/optimization/fjsp_set/evaluation.py) |
| 当前H/U研究 / offline_v2 | max(max_j w_j, W/M)，不取整 | [lower_bound_v5](../code/fjsp_usage/offline_v2.py)、[research_real.runtime](../code/fjsp_usage/research_real/runtime.py) |

单实例 `score=-Cmax/LB`，越大越好；批次fitness为完整实例score的算术平均，不是平均makespan，也不是总Cmax/总LB。即使调用原Tier1调度器执行h，当前研究runtime仍用V5 LB重新评分。不能直接拼接历史单规则fitness；若做新协议对照，统一重算并注明。

冻结单规则评价器返回训练向量，EoH再取均值；异常使候选无效。当前研究runtime在同一批次子进程中逐实例完整求解两遍，核对确定性，分别记录单次求解和复核时间；期限也涉及两次执行及首实例启动开销。任一实例失败/超时使整批 `valid=false, fitness=null`，成功前缀只留诊断。

## 实际调用链

单规则基线：`run_eoh_single.main → FJSPSetEvaluation → EoH.run → sampler → SecureEvaluator → evaluate_program → evaluate_instance → construct_schedule`；结束后另运行 `evaluate_single_rule.main` 从最终种群按validation均分选一条。该入口没有EoH-S互补种群管理。

当前集合/U：`research_real_v1/run.main → Workflow → V5BudgetedSearch → BudgetedSearch → research.evolution.Search`。H使用I1、E1/CS、M1/LS和互补生存；U按四组安排算子。提示扩展点由 `V5BudgetedSearch._build_prompt`替换为 [research_real/prompts.py](../code/fjsp_usage/research_real/prompts.py)；旧Search默认提示仍在 [research/prompts.py](../code/fjsp_usage/research/prompts.py)。

当前共享U初始化另调用`V5BudgetedSearch._initial_prompt → initialization_prompt`加入已接受U代码的去重上下文，`_duplicate_of → selector_signature`保守合并纯整数return/int(整数)写法，均仅适用于INIT。该辅助签名不改变Candidate.key、h审查键或冻结资产，也不宣称普遍语义等价。H和四组演化沿用原提示/去重策略；旧Search的两个扩展点默认保持原行为。

完整训练评价：`Workflow.train_eval → StagedDataset.evaluate → runtime.evaluate → _worker → compile_candidate`；h分支调用原 `construct_schedule`，U分支调用 `research.scheduler.construct_usage_schedule`。两者在当前研究评价中使用同一V5评分。

## 候选限制与测试依据

[parse_response / validate_code / compile_candidate](../code/fjsp_usage/research/candidates.py)限制单函数精确参数、数值AST与内建函数；代码键按规范化AST生成，删除注释/注解/说明字符串，不证明语义等价。数值常量绝对值不超过1e9，中间值有限且幅度不超过1e100；外部资源、导入、随机性和跨调用可变状态受限制。子进程超时可以终止无限循环，这不是任意Python的通用OS沙箱。

| 测试文件 | 核对内容 |
|---|---|
| [test_fjsp_set.py](../tests/test_fjsp_set.py) | loader、动作评分、同分、排程可行性 |
| [test_fjsp_usage.py](../tests/test_fjsp_usage.py) | 历史状态对象接口，每步一次U/单成员评分 |
| [test_fjsp_usage_v2.py](../tests/test_fjsp_usage_v2.py) | 七状态、T/C、previous、V5 LB、常量U等价、整批失败 |
| [test_research_execution.py](../tests/test_research_execution.py) | 候选约束、执行期限、确定性与追踪 |
| [test_h_review_execution.py](../tests/test_h_review_execution.py) | 审查输入单独超时、冻结重载、有限样例 |
| [test_U_initialization_novelty.py](../tests/test_U_initialization_novelty.py) | 等价常量去重、相同分数保留不同代码、无H/分数泄漏、完整归档与inflight恢复 |

测试覆盖说明不是本轮测试通过声明，也不证明h/U有性能收益。数据拆分和恢复见[来源与数据](../provenance/SOURCE.md)；当前H资产与外层流程见 [研究协议](PRD_TIER2_REAL_EXPERIMENTS_v1.md)。

## 原型和审查执行边界

`offline_v1.py`给手写U不可变StateSummary，沿用取整LB；`offline_v2.py / training_v2.py`改为七标量/未取整LB，但仍是手写H/U演示。它们没有生成代码的受控执行能力；七参数边界本身不是沙箱。当前research调度器复用v2状态，候选由受限语言执行器评价。

行为审查由[review_execution.py](../code/fjsp_usage/research_real/review_execution.py)独立spawn进程执行；review_timeout覆盖启动、编译、全部固定动作样例和第二次确定性复核，超时回收进程。仅缓存准确代码键/期限的成功样例；每次仍核验人工字段、代码/资产哈希和train数据。固定样例和完整train不能替代真人对高分行为的阅读。
