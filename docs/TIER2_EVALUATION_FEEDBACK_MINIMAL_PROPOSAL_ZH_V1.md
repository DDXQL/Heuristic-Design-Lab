# Tier 2真实评价反馈：机制核查与最小验证方案 V1

日期：2026-10-25。工作树：`FJSP-Heuristic-Research-h-usage-space`；分支：`codex/h-usage-space`；核查基点：`6d14f05c8d4c05fbe9e052c616dc592b80b0304a`。

**建议先改两父代CROSS：补充两位父代经过认证的完整train21 Fitness及差值；再以相同信息、同一次生成调用的C条件，检验显式比较反思是否有额外贡献。** 初始化和MUTATE暂不改，不增加冠军示例、长期记忆或融合算子。

本轮仅只读核查、本地文献阅读和本文编写；新增正式/toy求解、API调用均为0，没有修改程序或实际提示词。A4维持93/300停止状态，冻结候选、账本、缓存、期限及时间证据隔离均不调整。本文不是实验结果或执行授权，后续须另行实现、离线验收和批准正式预算。

## 1. 当前生成机制：有外部反馈，没有显式成绩输入

### 1.1 三条流程不能混为一谈

|流程|初始化|CROSS / MUTATE|显式评价反馈|
|---|---|---|---|
|通用配对`usage_v2`|共享SELECT P0；只有K、合法编号、七维状态及接口，没有H代码/行为；追加已接受源码去重上下文|给全部H代码/审阅行为、父代描述和代码；A仅SELECT，B允许SELECT/MIX|无父代Fitness、排名、逐实例成绩|
|B1完整10H自由流程，内部arm为`B`|给10H代码/行为；自由SELECT/MIX；无手工冠军；追加已接受代码|实际CROSS两位不同父代，MUTATE一位；均给10H语义及父代代码/描述|成绩用于外部选择，不送入数值反馈块|
|历史B2 H0/H1专用流程|**没有LLM I1提示词**；手工P0为alpha=0、0.25、0.50、0.75、1的五个固定权重程序|只给H0/H1语义；CROSS五位不同父代、MUTATE一位；H0权重alpha，H1权重1-alpha，其余8维零|任务明确说明完整Fitness仅供外部选择，模型不接收|

历史“B1完整10H实验”使用内部`B`，前半代CROSS、后半代MUTATE；不是`evolution.operator_at`里同名内部arm `B1`的E1/E2/M1/M2/M3流程。通用配对实跑配置为共享SELECT初始化、五父代CROSS及一代；B1-NS为自由初始化、两父代CROSS、计划两代。B2虽完成两代，但限定已知强组合且用手工P0，不能将成绩差异归因于单一提示词因素。

### 1.2 实际可见信息

- **H代码/行为**：交叉、变异都有；通用I1不给，B1自由I1给。审阅行为是设计上下文，不是状态级优胜标签。
- **七维状态/动作约束**：有定义、可证明取值边界、返回格式、编号、归一化及同分规则。U不接收动作列表或H评分，host枚举合法动作并调用H。
- **父代描述/代码**：parents段仅序列化`candidate.description/code`。父代行虽有`fitness/scores`，但未拼入prompt。模型描述中的自述不是经过认证的反馈。
- **Fitness/相对排名/逐实例成绩**：未显式提供。`PARENT 0...`只是位置，不承诺质量顺序。抽样受排名影响，属于间接信息；五父代且种群为五时所有个体都会进入CROSS，成绩主要影响出现顺序。
- **失败/修改经验**：格式错误、重复、超时、API错误和历史子代成绩留在外部记录，不自动送进下一次生成。初始化档案仅有已接受源码，按AST key稳定排序，完整条目字节上限131072；没有成绩/排名/失败反例。接受筛选本身带有间接信息，不能说完全没有历史上下文。
- **对话记忆**：`JsonCandidateTransport.dispatch`的chat路径每次构造一个user消息，没有自动接续旧对话或反思历史。本结论限于可审计本地请求，不推断供应商内部行为。

H编号历史上携带单H训练排名信息，而当前任务文字要求把编号当类别而非质量秩。这是既有先验风险；未来A/B/C固定相同编号和H上下文，不单独给某组排名表，不在本方案悄悄重排。编号敏感性维持独立研究问题。

### 1.3 Fitness怎样影响外部演化

`select_parents`按Fitness降序、同分按ID排序，再用`1/(N+r)`（r从0开始）无放回抽样。选走父代后删除对应原权重，不重新排名；N=5时最好与最差初始权重之比1.8，不是只取冠军。

同代使用固定父代池；完整有效子代进入children。U代末将旧群体与有效子代合并，按同一排序留前N个，不按物理行为多样性保留。AST不同不保证行为不同，失败和重复也不等于零成本。

当前闭环是：**评价 → 外部按成绩选父代/留个体 → LLM读选中的源码**。缺少的是明确告诉模型“这些程序实际取得什么成绩、差距多大”，不是系统没有评价反馈。

## 2. 关键证据和数据可用性

以下路径相对本工作树，只列关键函数及原始证据。

|编号|位置|用途|
|---|---|---|
|E1|`code/fjsp_usage/usage_v2/prompts.py::prompt_sections/build_prompt`；`research_real/prompts.py::U_TASK/P_CROSS/P_MUTATE`|任务、H、父代、算子及输出拼接|
|E2|`code/fjsp_usage/research_real/initialization.py::initialization_prompt`；`usage_v2/search.py::UsageSearch`|已接受源码档案，不是成绩排名|
|E3|`tools/b1_usage_prompts.py::build_prompt/manifest`；`tools/b1_usage_local.py::B1Search`；`tools/b1_nonstream_local.py::Config`|10H自由I1、真实k=2与父代字段|
|E4|`code/fjsp_usage/research/evolution.py::select_parents/_prepare/_attempt/run`；`research/sets.py::ranked`|外部选择、评价、精英保留|
|E5|`tools/h01_weight_search.py::constant/build_prompt/WeightSearch`；`tools/h01_weight_local.py::BatchWeightSearch`|B2手工P0、H01限制及请求适配|
|E6|`runs/h01-state-weight-search-seed501-batch-v3-20261020/`中的`Plan.json`、`Initial_population.json`、`H_context.json`、`prompt_templates/`、`r501/B/{budgeted_evolution_requests.json,checkpoint.json,prompts/}`|封存模板与实际发送文本；没有I1请求|
|E7|`runs/b1-ns-recovery-B-v1-20261022/`中的`Protocol.json`、`Revalidation.json`、`Final_identity_checks.json`、`r501/B/checkpoint.json`、`r501/B/prompts/`|完整P0、原生评价字段及身份凭据|
|E8|`reports/b1-ns-recovery-B-execution-20261023/REPORT_ZH.md`及`Population_members.csv/Lineage.csv`|历史19份prompt重建、谱系和P2未执行；本轮对照原生记录|
|E9|`code/fjsp_usage/usage_v2/execution.py::decode_output/normalize_scores/combine_scores/construct_usage_schedule`；`research_real/real_transport.py::JsonCandidateTransport.dispatch`|host语义与消息构造|

E6 Plan SHA256：`e2b2669512ca6c97e94cbe616dbfd5a84ed24222eb38896f40a810987c51a98a`。本轮确认当前`evolution.py`、`research_real/prompts.py`、`usage_v2/prompts.py`、`h01_weight_search.py`内容均匹配其冻结pin，不外推到所有执行模块。

实际B2 `B/g0000/000000`（CROSS、五父代）prompt SHA256：`3f9c60c00b3b92db43f5b8ceb596b31665449776a2377c96ffe9c1212033d167`；`B/g0000/000005`（MUTATE、一父代）：`b9123a583f0f6c5a7e467d4676faf6caba3747d1c84f9c6f02e89dfa07b2b109`。已读父代及算子/输出段，不把导出示例模板hash当所有真实请求hash。

E7协议SHA256：`565537b020173b30a6bd41d316228691892c500c8bcecb3266491d70193bcd72`；checkpoint SHA256：`535335536b77949a15c3f75e4649f5266e2cf19f47535a4fc6154e853c4bc535`。实际`r501/B/prompts/B_g0000_000000`（无`.txt`）SHA256：`85395f171b2bfd31e8f4f83cc703817764ef75c2f6fe2575f4cb61e095aec56a`，含10H、两个父代；`B_g0000_000005`为`536ece2ba3008185dfa68ab55dd41f475391cfc08da098fdfd9847f9ab734124`，含一个父代，均无显式数值成绩字段。

### 2.1 P0来源追到Recovery-B，不误用原始目录

最初`runs/b1-full-h-free-seed501-k2-v1-20261021/r501/B/checkpoint.json`仍在初始化，只有一个population成员，不代表后续P0/P1。有效记录沿NS → Recovery-B取证，不补写旧目录。

Recovery-B `population_snapshots.P0`的五份完整记录如下；这里只披露来源，不把这些数值混作未来新父代的反馈。

|ID|保存的完整Fitness|candidate key前12位|
|---|---:|---|
|`B/init/000006`|−2.115159624699559|`3f6963be06fb`|
|`B/init/000002`|−2.4010715776754177|`3bdfc806d913`|
|`B/init/000008`|−2.404627600830643|`8e8288d5e921`|
|`B/init/000005`|−2.5270363059129246|`5cd13170c9d7`|
|`B/init/000001`|−2.5611498256653267|`eeecea5872bd`|

原生result含`valid,total_instances,fitness,instances,worker_identity`；实例行含`file,makespan,lower_bound,score`及首解/复检hash和耗时。`Revalidation.ready=true`；`Final_identity_checks`记录完整有效候选的before/after证据。本轮未全面重新认证旧结果。历史运行因另一个候选超时后缺结束身份凭据停止，不可解锁续跑；完整P0与失败候选分别处理。

现有数据足以离线提取整体Fitness、差值及可选的21实例配对差异；未来复用仍须核对完整key、H顺序、数据/LB、seed、接口、完整性与原接受证据，不能只凭短ID或摘要表。

**缺的是状态级因果标签**：哪个分支贡献多少、同状态换H会怎样、某项权重的边际收益。轨迹频率、整体差异和逐实例输赢都不能补出这些标签，本方案不追加诊断求解。

## 3. 最小改进：信息和反思分开

问题：固定H、U空间、评价、初始化和模型后，真实反馈能否帮助LLM在有限候选预算内生成更好的U？

|条件|变化|检验目标|
|---|---|---|
|A 当前|原B1两父代CROSS、H语义、父代代码/描述；无数值成绩|现有基准，保留外部选择的间接信息|
|B 信息|A＋两父代同口径完整Fitness、差值、来源及事实边界|显式成绩信息包是否有用|
|C 信息＋比较反思|B完全相同的信息＋显式比较代码/成绩、提出一个修改假设|同信息下比较反思指令是否有增量|

先接通和审计B字段，再比较A/B/C，不预设有效。B−A包含信息包装与额外文本长度，不是纯数值bit的效果。C−B控制事实、父代、输出格式和调用数；B本来也可能自行比较，不能称“无反思”对“有反思”。隔离长度/标签效应需另立等长对照，不加进最小方案。

这检验**LLM搜索同一U空间的能力**，不直接证明动态空间优于静态；静态程序也是U的一部分。表达能力、搜索效率、最终质量、增加信息和额外反思分开讨论。“文本梯度”不能仅靠命名就成为创新或有效性结论。

### 3.1 首先CROSS，而非MUTATE

CROSS已经有两份代码，补充成绩即可建立比较；两父代与当前B1一致、长度可控。MUTATE只有一个父代，若再加冠军作参照，会同时改变源码信息和先验；单个整体分数也难指出该改哪里。故先CROSS，I1/MUTATE不变，不据此宣称交叉本身更有效。

### 3.2 反馈粒度与长度

第一步只给两个整体Fitness和差值。prompt显示小数点后12位，账本留未舍入原值，ΔF从原值计算再显示；显示同分不作末位排序解释，方向固定F0−F1、越大越好。不单给排名，因为它掩盖差距；不塞入单H榜、45对、A4/B2成绩表或挑选的失败实例。

未来若需逐实例信息，先按预定口径对全部21实例汇总胜负平，不挑故事；依然不能归因到状态分支。失败只用可认证错误分类，不从低分推测超时或非法动作。

反馈放在**父代代码后、原CROSS指令前**。B块上限2048 UTF-8字节，C额外指令上限1024字节，含字段值；超限发送前停止，不截断H/父代。全prompt仍守锁定供应商字节上限；字节不是Token，真实Token和费用另记。

不加额外调用：同一次调用完成比较和生成，保留“≤3句描述＋一个Python块”，不要求长推理过程、不加长期记忆。整体差距只能指导待检验假设，不能变成某个分支的已知奖励。

## 4. 推荐B条件的完整提示词草案

以下为**文档模板，非实际prompt文件或实现**。任务、状态界限、H接口说明、CROSS及输出段沿用当前源码；只在父代后增加`EVALUATION FACTS`。`${...}`都是占位符，没有虚构成绩。

`${ORDERED_H_BLOCKS_H0_TO_H9}`须展开完整十段`H MEMBER i / Behavior: <审阅描述> / Code: <原代码>`，i严格0至9，格式与`b1_usage_prompts.build_prompt`一致，不取前几名、不加排名。父代描述和代码来自实际选中记录，位置与反馈一致。来源为E1/E3；新字段来源见4.1。仍只发一个user消息，不增system角色或历史聊天。

```text
Design a deterministic heuristic-usage strategy U for static FJSP, not an action priority rule h.
Before each step, the host enumerates each unfinished job's next operation and its allowed machines.
The host computes the state, calls U exactly ONCE, and uses only the members selected by your output to score ALL legal pairs.
Execute the highest-scoring action, break ties by job then machine index, and append it to the machine's end.
Continue until all operations are scheduled. Terminal states do not call U. Online scheduling never calls an LLM.
An external evaluator measures complete feasible schedules on ALL training instances, using mean(-makespan/LB).
Higher fitness is better. LB=max(longest job's shortest processing-time sum, total shortest processing-time sum/machine count).
Any failed instance invalidates the candidate; there is no partial-batch mean or fallback heuristic.
Generate only U, without changing H, the state calculator, scheduler or evaluator.
Inputs (these are STATE summaries, not h's single-action inputs):
progress=scheduled operation count / total operation count of the instance, NOT elapsed-time progress or population size.
candidate_pair_ratio=legal operation-machine pair count/C; C=sum over jobs of the maximum alternatives of any operation in that job.
remaining_work_mean/std: for each UNFINISHED job, sum shortest alternative processing times for all unscheduled operations,
including the current operation; divide by T, then take mean and population standard deviation (ddof=0).
machine_ready_mean/std: mean and population standard deviation of ALL machines' current end times divided by T,
including unused machines. These summaries do not identify a particular bottleneck machine.
T=sum of the maximum alternative processing time over ALL operations. T and C stay fixed; they are NOT extra inputs.
previous_heuristic=-1 at the first step, otherwise the largest normalized-weight member id (ties: smallest id); it contains no rewards or improvement history.
Use only these seven inputs, local calculations and fixed constants. Same input must yield the same output.
Do not call H, parents or evaluators; simulate schedules; access external resources; infer extra state; or retain mutable state.
Member ids are categories, not quality ranks: do not average ids or infer quality from their magnitude.
Every path returns exactly (mode, (v0, ..., vK_minus_1)). Mode is a built-in int, never bool. Handle the first step and avoid division by zero.
A constant selector is legal. Do not force switching, use of every member/input, or a particular decision-tree skeleton.
Do not invent performance evidence, state-level winners, rewards or failure examples.
Provable bounds in nonterminal legal states (positive processing times):
0 <= progress < 1; 0 < candidate_pair_ratio <= 1.
0 < remaining_work_mean <= 1; 0 <= remaining_work_std <= 0.5.
0 <= machine_ready_mean <= 1; 0 <= machine_ready_std <= 0.5.
previous_heuristic is -1 only at the first step, otherwise a categorical id in [0,K).
All normalized remaining-work values and machine end times lie in [0,1].
Remaining-work values are restricted to unfinished jobs and their sum is <=1:
with a active jobs, mean <=1/a and std <=sqrt(a-1)/a (a=1 gives std=0).
For either pair mean=m, std=s, s*s <= m*(1-m).
Thus s/(1+m) <=sqrt(2)/4 (approximately 0.353554), not an unnormalized dispersion.
These are conservative global bounds, not typical training ranges or state-level winners.
A condition outside these bounds cannot fire. A condition inside may still never fire in training.
Use thresholds/relations compatible with the actual normalized scale; constant selectors remain legal.

Use the fixed ordered H. Vector entry i refers to member i; vector length MUST be K.
All vector entries must be built-in int or float, NEVER bool; local boolean comparisons remain legal.
Construct the two-level tuple literal directly in each return; do not store tuples in variables or use lists/indexing.
SELECT mode=0: vector entries are finite member-selection scores, allowed negative.
The host picks argmax, EXACT ties to lowest member id; all-zero scores are legal.
MIX mode=1: vector entries are finite nonnegative raw weights with exactly one or two positive entries.
The host normalizes by positive maximum then sum; all-zero or more than two positives fails, without repair.
Within the permitted modes, member scores, active members, weights and mode may depend on the seven inputs.
Scores or weights may use constants, conditions, linear or nonlinear local expressions within the allowed language;
no formula, phase partition or program skeleton is prescribed. A score formula may contain if;
a condition may produce weights. Program syntax alone does not determine the usage mechanism.
For MIX, compute the one- or two-member support yourself; the host does not select top-two scores for you.
One active member scores actions in raw units, exactly like the original single-member executor.
Two active members each score every CURRENT legal action once. The host min-max normalizes each complete action column
and takes the nonnegative weighted sum. A constant column becomes zero, without reallocating its weight.
Final action ties use job then machine id. This rule is fixed by the host, not configurable by your program.
Member-selection scores, mixture weights, raw h action scores and final combined action scores are distinct quantities.
Your program does not receive action scores/lists and must NOT call h or simulate future schedules.
The historical dominant id loses the other member and weight proportions; do not invent those inputs.
Constant SELECT and single-member MIX are legal where the mode is permitted; do not force mixtures or switching.
These rules are engineering semantics, not evidence that combinations or any members perform better.

Permitted modes: SELECT (0) OR MIX (1); at most two positive MIX weights.
K=10; ordered member ids 0 through 9.
H INFORMATION FOR OFFLINE U DESIGN ONLY (do NOT generate h):
The following interface defines h's SINGLE operation-machine action inputs, all in RAW, unnormalised units.
processing_time: duration of the candidate operation on this candidate machine.
remaining_work: sum of shortest alternative durations for this job's unscheduled operations, INCLUDING the current one.
remaining_operations: number of this job's unscheduled operations, INCLUDING the current one.
job_ready_time: completion time of the job's previously scheduled operation, or zero initially.
machine_ready_time: end time of this machine's current schedule, or zero initially.
earliest_start=max(job_ready_time, machine_ready_time).
earliest_finish=earliest_start+processing_time.
h returns a finite real scalar, not bool; HIGHER scores win, with job/machine index ties.
These action features are NOT additional U inputs. The host calls only the active members for each legal action.
Read the actual member code and reviewed behavior below. A state-to-member match is a hypothesis, not proven local superiority.
H code is design context, not permission for U to execute H, parents or a lookahead simulator.

def priority(processing_time, remaining_work, remaining_operations, job_ready_time, machine_ready_time, earliest_start, earliest_finish):
${ORDERED_H_BLOCKS_H0_TO_H9}

PARENT 0
Description: ${P0_DESCRIPTION}
Code:
${P0_SOURCE}

PARENT 1
Description: ${P1_DESCRIPTION}
Code:
${P1_SOURCE}

EVALUATION FACTS — complete schedules, NOT state-action labels
Protocol: ${FROZEN_SCIENTIFIC_ID}; ordered-H: ${ORDERED_H_SHA256}; dataset/LB: ${DATA_LB_SHA256}.
train21; solver seed=501; Fitness=mean(-Cmax/LB); higher is better.
PARENT 0: key=${P0_KEY}; valid=true; complete_instances=21; Fitness=${F0}.
PARENT 1: key=${P1_KEY}; valid=true; complete_instances=21; Fitness=${F1}.
Delta_Fitness(PARENT 0 minus PARENT 1)=${F0_MINUS_F1}.
Both results passed the same declared result-acceptance checks; neither uses a successful-prefix mean.
These facts compare whole programs on training instances only. They do not identify which state,
branch, member or weight caused a difference; a small difference is not proof of statistical robustness.
If you cite a supplied fact, mark it Observed; mark an explanation Untested and a proposed change Hypothesis.
Do not invent failure causes, state-level rewards, counterfactual scores or unreported measurements.

Compare how the supplied parents map available state information to H members, using H's actual behavior.
Try to combine the decision ideas of AT LEAST TWO parents into a new usage relationship.
You may change state conditions, relations between conditions, member mappings and parameters, member-score formulas and, where permitted, support and weight formulas, or rewrite the WHOLE function.
Do not require fixed modules, literal code splicing, or a particular program skeleton.
Resolve conflicting choices using the available state and H behavior, not simply parent order.
Different parents do not prove complementarity; whole-instance results do not establish state-level winners.
In the common at-most-three-sentence explanation, identify which parental decision ideas were inherited and how they were combined.
Return one complete new U. Its benefit is a hypothesis to be tested by external complete-schedule evaluation.

Output at most three sentences inside {braces}, followed by exactly one ```python code block. No extra text. Use one function with the exact argument names. Only numeric constants, local variables, arithmetic, comparisons, if/while/for, and these builtins are allowed: abs, min, max, int, float, round, range. Only the terminal two-level tuple (mode, (scalar,...)) is permitted; no other containers, indexing, imports, attributes, helper functions, globals, recursion, randomness or resource access. Numeric intermediates must remain finite and <=1e100; power exponents must be literal integers from 0 to 8; round ndigits must be an int in [-100,100]. End the function with return, or an if/else whose branches both end in return. No return annotation. Numeric literals <=1e9; scalar intermediates/output fields finite with absolute value <=1e100.
def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
```

### 4.1 新字段从哪里来

|字段|读取与认证|禁止替代|
|---|---|---|
|H块/顺序摘要|本次协议绑定的有序H key、代码及审阅描述；E7 `Protocol.H_order`和冻结源码快照可追溯|按编号猜语义、重排H|
|父代代码/描述/key|所选population行`candidate.code/description/key`，绑定本次parents位置|偷偷换成历史冠军|
|F0/F1|对应`checkpoint.evaluations[id].result.fitness`，核对key、valid和完整21项；E7可作P0来源|A4/B2冠军、成功前缀均值、模型自述|
|完整数目/接受声明|`total_instances`、文件唯一集合/顺序、首解复检一致、身份及正常终态凭据，按来源协议验收|只看数组长度或摘要中的“有效”|
|ΔF|认证后从未舍入F0−F1计算|用Cmax总和差冒充Fitness差|
|科学ID、数据/LB摘要|未来独立科学manifest，包含H、数据哈希、LB算法/值、seed、指标、U/host语义；缓存来源和资源协议另记|把目录名当科学身份|

未来manifest和反馈导出器**本轮不实现**；已有JSON足以提供原始值。T15/T30和结果接受条件另行披露；有身份缺口不纳入该父代，不补造字段、不改旧账本。

host仍以E9为准：MIX恰1或2个严格正权重，负数/全零/多成员不修复；单成员用原始评分，双成员对当前全部合法动作各自独立min-max，常量列为零、不再分配权重。没有近零裁剪；缩放下溢丢失正支持集会失败，不事后当单H追认。动作同分按job、machine，成员同分按小编号。草案不开放MAX/MIN/Borda。

### 4.2 C只增加以下指令

放在B反馈块后、原CROSS前，其余字段和输出格式相同：

```text
COMPARATIVE REFLECTION IN THIS SAME GENERATION CALL
Compare the supplied whole-program Fitness facts with the two actual code implementations.
Choose one main modification hypothesis that combines ideas from at least two parents;
you may retain logic from either parent, including the worse-scoring one, without claiming local superiority.
In the existing explanation of at most three sentences, state one Observed supplied fact,
one Untested explanation of what might account for the difference (or explicitly say it is unknown),
and the Hypothesis this child is intended to test, including which parental ideas are combined.
Do not treat correlation, parent rank, a code branch or a state threshold as an identified cause of the Fitness gap.
Do not invent per-instance, per-state or counterfactual evidence. Then output the complete U in the unchanged format.
```

B要求别混淆事实、解释和假设，但不额外强制逐项比较；C增加显式比较要求，复用原3句封装。A保留当前谨慎措辞，不人为削弱对照。三组都须遵守原“至少两父代思想”要求，文字自述不保证实质继承。

### 4.3 初始化单独控制

“给H语义”“给已知冠军/手工P0”“给父代真实评价”是不同干预。推荐第一步复用E7五个完整自由P0作为三组共同起点，不额外植入H0/H1冠军。这是使用研发期已见资产的条件化验证，不是从零搜索。

三组外部选父代都可使用相同五份成绩，只有B/C将选中两位的数值送入模型。缓存免物理求解不等于先验免费，原获取成本和逻辑待遇要披露；若以后更换/新建P0，三组同步且初始化成本一致，不混用通用SELECT、自由P0和手工强组合。

## 5. 后续最小验证建议：不执行

### 5.1 先固定上下文，再验证完整演化

建议**3个独立生成重复 × 每重复4个CROSS候选槽 × A/B/C＝最多36次生成调用**。只检验单代、相同父代上下文，不直接开启多代U演化。

每个重复从同一冻结P0出发，用现有`select_parents`产生4个有序两父代任务；三组共享任务、顺序、位置及H上下文。不同槽可重复同一对，不为覆盖不足补抽。探针内不更新父代池、不把刚生成子代放入后续输入，避免父代轨迹差异混入B−A/C−B。

任何生成前冻结任务和发送顺序，对组别顺序作平衡，避免A全先、C全后与供应商时段变化混淆。建议任务种子2026102701、2026102702、2026102703；本轮未抽样。求解seed固定501。模型若不支持生成seed，记录限制，以独立请求作生成重复；不能改求解seed冒充搜索重复。

三组固定模型/供应商版本、温度、推理力度、输出上限、初始程序、去重和评价规则。下一协议批准前锁定模型，不假定未来供应商与历史完全一致。三次小重复只能发现实现问题和较大趋势，不能证明普遍优势。

### 5.2 建议预算与计账

|项目|建议上限/规则|
|---|---|
|共同先验|5份完整P0；每组每重复按5个先验质量查询槽披露，即使复用相同物理缓存|
|新生成|每组每重复4槽，共36；每槽一个候选，不修复调用、不补员|
|逻辑分配|每组每重复最多9槽＝5先验＋4子代；9个组×重复单元共81槽**分配上限**，不是81次新增评价；先验查询、生成尝试、实际质量查询和完整评价分别记录|
|新增物理评价|最多36×21＝756项程序—实例、1512遍首解/复检；P0不重求解|
|无效/重试|建议自动API重试0；格式、语言失败、AST重复、超时占槽；发送状态未知Stop，不重发|
|反思成本|B/C均无额外调用；C附加输入及实际输出/推理/缓存Token、时延、账单单列；两调用方案需另立条件|

缓存仅免物理成本，不免逻辑槽；跨组/跨重复命中及共同失败来源分开披露，不得将cache成绩泄漏到A。逻辑查询不能改称完整有效候选数。AST重复与物理排程相同分别统计，后者不证明普遍程序等价。

未来新评价建议统一用既有安全T30正常退出/身份框架，train21、LB、Fitness、动作与归一化不变；T30是单实例结果等待期限，不是仅调度函数耗时，清理和终态认证仍按其协议。它与历史B1 T15资源协议有差异；P0在T15完整通过，可按身份和原接受证据申请缓存复用，不改写成同期T30。跨历史缓存不构成墙钟公平。

以上**不属于现有授权**。下一轮先做离线Mock，冻结反馈导出、源码身份、任务、预算、持久化期限、正常退出和未知reservation Stop，再申请正式生成/求解权限。普通已认证超时记null，不补评、不用前缀；身份、复检、进程终态或预算未知立即停止相关执行，不反馈不可信成绩。

### 5.3 搜索过程和最终冠军分别观察

**过程指标**：按全部分配槽报告API完成率、格式/语言合法率、完整评价率、AST重复率、物理排程组数，以及每槽严格超过该任务较好父代的比例。无效槽保留在成功率分母，不虚构惩罚Fitness。有效子代计算`F_child−max(F_parent0,F_parent1)`；只对有效者算均值时须同报全槽成功率，不能掩盖失败。

**冠军指标**：每组每重复从共同P0与至多4子代取最好有效结果，报4槽best-so-far、冠军、相对P0/静态参照差值。全部子代失败则保留P0冠军并列明失败。以重复为单位展示配对差异和范围，n=3不作强显著性结论；共用P0、重复父代上下文不是独立问题样本。

B胜A支持这个信息包在测试上下文中有用；C胜B支持显式比较指令有增量。无改善也有信息，但不能断言反馈永无价值。关于分支改善的自然语言解释仍是假设。

若小验证可行，再另立共同预算的多代A/B/C；届时允许父代轨迹自然分化，检验完整搜索闭环，不能再称输入上下文完全相同。训练外确认应在配置/冠军冻结后，另授权取得此前未暴露的新实例集合。本轮及该训练探针不访问validation11/test28，不把已看test28当新确认性证据。

## 6. 本地文献：原文方法与迁移建议分开

原文路径：`/Users/DDXQL/Documents/大学/硕士/论文/AHD/JSPAgent.pdf`。定向阅读PDF第5—7页与第13—14页补充提示词（PDF页码含前置页），未开展互联网检索。

已核实：第6—7页描述启发式GA的交叉、TG-Prompt和精英变异；第7页用交叉子代与elite表现差距构造自然语言建议、用于后续交叉；第13页Fig. S-3展示worse code、better code及TG-Prompt占位块。可迁移的是“代码比较＋可追溯表现信息”，但论文还涉及跨阶段反馈，**本文单调用B/C不是原文复现**。

该文研究JSP算子发现及MA内优化，本项目研究固定H上的FJSP利用程序，两者对象/条件不同。反向传播类比不提供本项目的状态级因果标签。补充页未展示完整TG-Prompt生成模板或逐次反馈日志，不能补写其具体调用/成本。

ReEvo仅见于JSPAgent正文/参考文献，本轮未找到可直接读取的独立原文或补充提示词，不把二手转述写成ReEvo已核实机制，不补写短期/长期反思操作细节。

## 7. 实现前的少数决策与完成范围

建议默认范围已经明确：完整10H、原SELECT/WS、两父代CROSS、整体Fitness信息、一次调用，I1/MUTATE不变。路径和字段适配由后续工程解决，无需逐项让用户转交诊断。

仍需下一轮决定/批准：是否接受固定历史P0的条件化探针；正式生成/评价/时间/费用硬上限和届时可用模型；何时另建未暴露训练外确认集。如果要直接验证多代或从零初始化，应重新界定问题，不暗中扩大本探针。

**已完成**：源码和实际封存prompt核查、P0来源追溯、字段可用性、B完整草案/C差量、最小对照和预算设计。**未实施**：导出器、实际提示词改动、Mock/toy/正式求解、API及U演化；未动A4和历史记录。只新增本文并本地提交，不推送。

文档核验记录：只读断言确认B草案保留当前TASK、H说明、CROSS和NEW_OUTPUT原段、七参数签名及两个文本草案块；以64位摘要与12位小数占位检查，反馈块1216字节、C块861字节，均在建议上限内。五个P0的保存Fitness与21实例score均值一致，实例唯一且首解/复检物理hash一致，ID均在完整候选身份索引中；checkpoint哈希未变。此核验不是执行器Mock，不替代未来完整来源验收，未启动任何求解。
