# 固定 H 的使用策略空间

> 本文保留首轮阅读分析。后续第一阶段实现见 [v2.2设计与离线验证](H_USAGE_SPACE_PHASE1.md)，新方法研究见 [独立实验登记草案](H_USAGE_SPACE_EXPERIMENT_PLAN.md)。本分支从共同checkpoint继续，历史runs不随worktree复制；本文历史记录链接指原仓库首轮记录，不代表本分支已执行真实研究。

核对日期：2026-10-13。对象：`U-usage-v2-select-or-mix-20261012`、提示包 v2.1、`leaf-usage-v2-AB-preparation-20261012-v2`。本文件是代码阅读与方法分析，不改变实验协议。

**U 可以根据七项状态，用合法的数值程序决定怎样使用固定 H：给成员打选择分数后单选，或指定一个/两个成员及其非负组合权重。公式由 LLM 生成，外部评价器用完整排程筛选；不要求研究者预先列出全部公式。执行器决定这些输出怎样变成调度动作。**

“用 if 选一个 h”“给成员打分再单选”“组合两个 h”不能只按代码外观分类。评分公式可以含 if；if 可以返回权重；无 if 的公式也能使最高分成员随状态改变。应分别记录程序计算、实际使用机制和观察到的行为。

## 1. 已有实现与证据

本轮核对代码、六份完整提示及 A/B 差异、配置、准备记录和旧 U 兼容记录，没有重新运行训练、toy 排程、测试套件或模型请求，也没有读取验证/测试实例。

| 已知背景 | 核对结果与边界 |
|---|---|
| 接口与执行规则 | 与背景一致：七输入、`(mode, vector)`；SELECT argmax；MIX 一/两个正项；单成员原始动作分数、双成员逐列 min–max 后加权 |
| 188 项测试 | `Implementation_checks_20261013.json` 记载 188；引用日志存在，SHA256 相符，末尾为 `Ran 188 tests ... OK`。本轮未重跑 |
| 实现源码对应检查记录 | 检查记录 `file_sha256` 中列出的文件全部相符；契约早期“旧路径事实”表是设计历史，当前行为以实际 usage_v2 代码为准 |
| 固定 H 与旧 U | 准备记录为 10/10 H 在 train21 复现 makespan；兼容记录为 5/5 旧 U，各 21 实例，逐动作/状态/历史/排程及 fitness 一致。这是复现证据 |
| 新真实研究 | 检查记录中新请求、新初始 U 均为 0；最新训练报告中 INIT/A/B 都是 `not_started`。toy 的双成员步骤是手写 fixture，不能当作真实 LLM 生成 |
| 待执行安排 | K=10、seed301、N=5、共享初始化最多20次、每组一代10槽位（5 CROSS+5 MUTATE）、总计最多40次；初始化不足5不补员、不降N |
| 当前状态 | 配置 `real_requests_authorized=false`，新研究 H 冻结/范围批准尚未完成。本轮只分析，不推进这些阶段 |

主要依据：

- [契约与设计历史](U_USAGE_CONTRACT_V2_DRAFT.md)，尤其接口、状态、动作组合与证据章节。
- [候选语言](../code/fjsp_usage/usage_v2/candidates.py)、[数值语言与编译](../code/fjsp_usage/research/candidates.py)、[执行器](../code/fjsp_usage/usage_v2/execution.py)。
- [状态计算](../code/fjsp_usage/offline_v2.py)、[状态诊断](../code/fjsp_usage/research_real/state_diagnostics.py)、[完整评价](../code/fjsp_usage/research_real/runtime.py)。
- [提示生成](../code/fjsp_usage/usage_v2/prompts.py)、[完整提示导出](../code/fjsp_usage/usage_v2/exports.py)、[搜索](../code/fjsp_usage/usage_v2/search.py)、[流程与报告](../code/fjsp_usage/usage_v2/workflow.py)、[配置](../code/fjsp_usage/usage_v2/config.py)、[运行入口](../experiments/tier2/usage_v2/run.py)。
- [检查记录](../runs/leaf-usage-v2-AB-preparation-20261012-v2/Implementation_checks_20261013.json)、[待执行配置](../runs/leaf-usage-v2-AB-preparation-20261012-v2/config.pending.json)、[准备记录](../runs/leaf-usage-v2-AB-preparation-20261012-v2/Preparation.json)、[旧 U 复现](../runs/leaf-usage-v2-AB-preparation-20261012-v2/Legacy_compatibility_audit.json)、[当前报告](../runs/leaf-usage-v2-AB-preparation-20261012-v2/Usage_training_report.json)。

## 2. 空间由哪些维度组成

### 2.1 U 获得什么信息

“七项状态”已经包含上一主导成员，不是七项之外再加一个历史输入。前六项是 float，第七项是 int。

| 输入 | 含义与限制 |
|---|---|
| `progress` | 已排工序数/总工序数；非终止时 `[0,1)`，不是时间进度 |
| `candidate_pair_ratio` | 当前合法工序—机器动作数/C；`(0,1]` |
| `remaining_work_mean`、`remaining_work_std` | 仅未完成作业的最短剩余加工量先除以 T，再取均值和总体标准差；包括当前工序 |
| `machine_ready_mean`、`machine_ready_std` | 所有机器末端时间先除以 T，再取均值和总体标准差；包括未使用机器 |
| `previous_heuristic` | 首步 −1，其后为上一提交步骤实际归一化权重最大的成员；精确同权重取较小编号 |

T 是所有工序的最大可选加工时长之和；C 是逐作业“单个工序最多可选机器数”之和。T/C 固定，但不是额外输入。两个 std 均不超过0.5，且 `std² <= mean*(1-mean)`；剩余工作均值还受未完成作业数量约束。均值/标准差不能定位某台瓶颈机器，也不能恢复各个动作特征。

运行时 U 只能使用七标量、常量和局部计算。它看不到动作列表、h 当前动作分数、奖励、未来排程、完整历史或可变全局状态。上一 dominant 相同不代表上一组合相同，例如 `(0.6,0.4,0,...)` 与 `(0.9,0,0.1,...)` 都记0。

离线生成时信息分阶段：共享初始化只有 K=10、编号0…9及状态/执行契约，后续初始化请求还附已接受代码的去重上下文，不附 H 行为或成绩；CROSS/MUTATE 提供十条 H 的说明和源码，以及父代说明/源码，不提供逐状态优胜标签或父代评价元数据。外部完整 fitness 影响父代选择和生存，并不自动成为 LLM 看见的反馈。

### 2.2 U 可以计算什么

当前是一种受限的确定性数值 Python：常量、局部变量、算术、比较、布尔控制、if/条件表达式、while/for，以及 `abs/min/max/int/float/round/range`。可以构造线性成员分数、比值/乘积/有限次幂等非线性指标，用条件修正分数，或直接计算非负权重。可以只用部分输入、部分成员，也可以全部不用。

函数只能是一个 `use_heuristics`，参数名和顺序固定，不写返回注解；每个 return 直接构造二层元组。不能把向量放入变量，不能使用字典、列表、下标、辅助函数、导入、属性访问、随机性或调用 h。向量元素必须为有限 built-in int/float，不能是 bool；局部布尔比较允许，但作为输出时须转成数值或用数值条件表达式。

字面量绝对值不超过1e9，受保护数值中间量和输出字段绝对值不超过1e100；幂指数只允许字面整数0…8，round 位数有界。AST 通过只说明静态结构合规，状态相关除零、溢出、非法 mode/支持集和超时仍可能在调用时失败。因此“其他表达”是这个语言内的表达，不是任意 Python。

这里允许的 `q0*q1` 或 `max(q0,q1)` 是 U 对本地标量的计算；未来所说的“h 动作分数乘积/逐动作最大值”是另一层执行机制，当前不能由 U 更换。

### 2.3 U 怎样使用 H，什么可以随状态改变

记七输入为 x，LLM 可以生成 `U(x)=(m(x),v(x))`：

| 维度 | 当前含义 | 状态可改变的内容 |
|---|---|---|
| 计算形式 | 常量、条件、综合指标、线性/非线性评分等 | 每个局部标量及其计算路径 |
| SELECT（0） | v 是 K 项成员选择分数 q；执行器单选最高者 | q 及赢家；分数变化不一定改变赢家 |
| MIX（1） | v 是 K 项非负原始权重 r；正项恰有1或2个 | 支持集（正权重成员集合）及实际权重比例 |
| 模式 | 每步输出0或1，受所在组允许模式约束 | B 可以在 SELECT/MIX 间变化；A/INIT 只能0 |
| 历史依赖 | 读取上一 dominant 类别 | 可依类别保留/切换或修正评分；不能恢复丢失的权重历史 |
| 执行规则 | 单成员/双成员如何变成动作分数 | U 不能修改归一化、同分、动作合法性或调度更新 |

常量单选和“打分后单选”最终都属于单成员使用。后者不自动增加执行器的动作能力：在足够的程序长度/预算下，两者都能描述状态到成员编号的映射；有限语言、长度、提示与搜索预算会让不同表示更容易或更难被生成。其搜索价值仍需实测。

条件分支同样可以生成 MIX 的支持集/权重，因此“有 if”与“评分式”不是互斥类别。分析候选时，宜记录“有条件修正的成员评分 + SELECT”等组合描述，并用轨迹确认实际使用。

## 3. 已支持与未支持能力

标记①=当前接口/执行器已支持且有工程检查；②=当前可表达，但尚无真实新生成或效果验证；③=须修改接口、候选语言或执行器。①与②可以同时成立；实现能力不等于研究效果。

| 能力 | 标记 | 当前边界 |
|---|---|---|
| 固定单选、按状态单选、评分 argmax 单选 | ①② | SELECT 已实现；旧 U 适配复现和 toy 检查不等于新评分策略证据 |
| 固定双成员非负加权和 | ①② | 双列当前动作 min–max 固定；toy 已执行，真实组合收益未测 |
| 非线性成员分数、条件修正分数、综合指标 | ② | 合法数值语言内可表达，不需加接口；尚无真实新候选覆盖证据 |
| 状态相关成员对/权重、从本地评分确定 top-2 后返回权重 | ② | 必须在标量代码中自行算出并返回合法稀疏向量；执行器不会自动 top-2 |
| B 随状态改变 SELECT/MIX、使用上一 dominant | ①② | mode 解码/历史已实现；真实自适应策略尚未验证 |
| MIX 单正项、常量/无切换/不用所有输入 | ①② | 都合法；不能为追求复杂度而剔除 |
| 三个及以上成员、负组合权重 | ③ | 当前输出检查直接拒绝 |
| h 动作分数乘积、逐动作取最大值、改用其他动作归一化 | ③ | 当前只有固定双列 min–max 后非负加权和 |
| U 根据每个动作或当前 h 分数设置不同权重 | ③ | 没有动作级输入；同一步全部动作共用一次 U 输出 |
| 完整权重/模式/动作历史、在线奖励、未来排程模拟 | ③ | 需要新信息接口/运行机制；完整日志存在也不意味着 U 可读取 |

后三类只是未来可能性，本轮不设计实现或修改协议。

## 4. 哪些规则由执行器固定

每个非终止步骤调用 U 一次。SELECT 输出 q 后，选 `min argmax(q)`，转换成单点权重；q 可负、可全零，全零选0。q 不是 h 输出，不是概率，也不是已知局部优越性或 makespan 估计。

MIX 输出 r 后，检查非负、有限且只有一/两个正项，再由执行器归一化。理想公式是 `alpha_i=r_i/sum(r)`，实际先按最大正权重缩放再用 `fsum` 求和；不加 epsilon，不丢小正项，不自动截 top-2。全零、三个正项或归一化丢失正支持都失败。

令当前合法动作集合为 A，`b_i(a)=h_i(a)`：

```text
只有一个成员：F(a)=该 h 的原始动作分数
有两个成员：
    各自对全部当前合法动作评分一次
    z_i(a)=(b_i(a)-min_A b_i)/(max_A b_i-min_A b_i)
    该列全相同时 z_i(a)=0
    F(a)=alpha_i*z_i(a)+alpha_j*z_j(a)
选 F 最高动作；精确同分按 job、machine 编号升序
```

这是概念公式；实际 min–max 先缩放端点避免数值溢出。常量列变0，不重新分配它的权重。单成员 MIX 与 SELECT 都使用原始 h 分数，不做 min–max，以保留旧单选行为。动作评分尺度由此与成员权重区分，但 min–max 本身不是质量校准。

合法动作来自各未完成作业的下一工序及其可选机器；机器当前忙也可选，开始时间取作业/机器 ready 的最大值。同一步的状态、合法集合及权重不在评分中途改变。最高分动作追加到机器末尾，不找空档；随后推进游标、ready 和 dominant 历史。已选 h 评分失败使实例失败，不删除动作或回退。

旧 `selected_members` 视图仅保存 dominant；`decisions` 保存 mode、原始向量、支持集、权重和 dominant。完整评价为所有训练实例可行排程的 `mean(-Cmax/LB)`，越高越好；任一失败则候选 fitness 为 null，不取成功前缀均值。主评价包含求解与确定性复检，诊断另做一次独立观察，诊断不改变 fitness。

## 5. 四个合法教学例子

以下全部 **K=10，位置0…9对应当前 H 编号0…9**。h0/h1/h2 的选择只是教学取值，没有质量含义。每个代码块是独立函数，不应合并为一个候选。它们不是伪代码；使用当前语法，可通过候选校验。只检查源码与独立手写输入的返回/解码，没有进行完整排程效果测试，不注入真实种群。

### 5.1 常量单选

```python
def use_heuristics(progress, candidate_pair_ratio,
                   remaining_work_mean, remaining_work_std,
                   machine_ready_mean, machine_ready_std,
                   previous_heuristic):
    return (0, (0, 0, 1, 0, 0, 0, 0, 0, 0, 0))
```

输入仍是七状态，但全部忽略。返回 SELECT，第2项最高，所以每步只调用 h2；全部动作以 h2 原始分数比较，下一历史为2。A/B/共享初始化都允许。

### 5.2 成员评分后单选：含非线性指标和 if

```python
def use_heuristics(progress, candidate_pair_ratio,
                   remaining_work_mean, remaining_work_std,
                   machine_ready_mean, machine_ready_std,
                   previous_heuristic):
    dispersion = remaining_work_std / (1.0 + remaining_work_mean)
    q0 = 1.0 - progress
    q1 = progress + 2.0 * dispersion * dispersion
    if previous_heuristic == 1:
        q1 = q1 + 0.05
    return (0, (q0, q1, -2, -2, -2, -2, -2, -2, -2, -2))
```

输入使用进度、工作量均值/标准差和上一 dominant。独立教学输入 `progress=0.4, mean=0.2, std=0.1, previous=0` 时，q0=0.6、q1约0.413889，选 h0；若进度为0.8，其余相同，则选 h1。精确同分选 h0。其余成员分数 −2，不能胜出。执行器只调用赢家，不调用十条 h 来获得这些 q。if 是评分的一部分；机制仍是 SELECT。A/B/初始化允许，公式和0.05没有效果依据。

### 5.3 固定双成员权重

```python
def use_heuristics(progress, candidate_pair_ratio,
                   remaining_work_mean, remaining_work_std,
                   machine_ready_mean, machine_ready_std,
                   previous_heuristic):
    return (1, (3, 2, 0, 0, 0, 0, 0, 0, 0, 0))
```

输入全部忽略。MIX 支持集为 `{0,1}`，实际权重0.6/0.4，dominant=0。执行器分别运行 h0/h1 对当前全部合法动作评分，再逐列 min–max，计算 `0.6*z0+0.4*z1`。它没有先选一个成员。只允许 B 演化阶段；A/共享初始化会拒绝 mode=1。

### 5.4 随状态改变模式、成员对和权重

```python
def use_heuristics(progress, candidate_pair_ratio,
                   remaining_work_mean, remaining_work_std,
                   machine_ready_mean, machine_ready_std,
                   previous_heuristic):
    if previous_heuristic == -1:
        return (0, (1, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    spread = machine_ready_std / (1.0 + machine_ready_mean)
    if candidate_pair_ratio < 0.5:
        return (1, (1.0 + spread, 1.0 - spread, 0, 0, 0, 0, 0, 0, 0, 0))
    return (1, (0, 1.0 + spread, 1.0 - spread, 0, 0, 0, 0, 0, 0, 0))
```

首步返回 SELECT，选 h0。以后候选比例小于0.5用 h0/h1，否则用 h1/h2；机器离散度改变两者权重。合法状态中 spread 不超过约0.353554，两个权重始终正，归一化后为 `(1+spread)/2` 和 `(1-spread)/2`。例如机器 mean=0.25、std=0.125，spread=0.1，权重0.55/0.45；比例0.4时 dominant=0，比例0.7时 dominant=1。只允许 B 演化阶段。0.5阈值和这套规则只是解释接口，不是建议固定这种阶段/决策骨架。

## 6. 完整提示覆盖核对

已读取 [A.I1](../runs/leaf-usage-v2-AB-preparation-20261012-v2/prompts/A.I1.txt)、[A.CROSS](../runs/leaf-usage-v2-AB-preparation-20261012-v2/prompts/A.CROSS.txt)、[A.MUTATE](../runs/leaf-usage-v2-AB-preparation-20261012-v2/prompts/A.MUTATE.txt) 的完整任务、状态界、H上下文、父代、算子、输出段；并逐全文比较对应 [B.I1](../runs/leaf-usage-v2-AB-preparation-20261012-v2/prompts/B.I1.txt)、[B.CROSS](../runs/leaf-usage-v2-AB-preparation-20261012-v2/prompts/B.CROSS.txt)、[B.MUTATE](../runs/leaf-usage-v2-AB-preparation-20261012-v2/prompts/B.MUTATE.txt)。

| 检查问题 | 结论 |
|---|---|
| 评分式单选 | 明确说明 SELECT 向量是成员选择分数，允许负值，host argmax；算术/非线性表达可用。覆盖，但算子文字偏条件选择 |
| 状态相关权重/支持集/模式 | 七输入局部计算、每步调用与 MIX 权重契约允许这些变化；没有说权重必须固定。覆盖属隐含许可，缺少直接列举 |
| 固定阶段或决策树 | 明说不要求特定 decision-tree skeleton，允许重写 WHOLE function；没有预设早/中/晚阶段。算子措辞有条件偏向，未构成强制骨架 |
| 四种量是否区分 | 明确区分 member-selection scores、mixture weights、raw h action scores、final combined action scores |
| 编号是否被当质量 | 明说类别而非质量排序，不平均编号、不由大小推质量；初始化再次提醒 |
| 状态/归一化/历史 | 定义、上下界、首步−1、最大实际权重历史、历史丢失信息、单raw/双min–max、常量列0均正确 |
| A/B 信息公平 | I1 全文完全一致；CROSS/MUTATE 把 allowed_modes 行替换后全文一致；H 与预览父代相同，非只依赖已有 comparison 断言 |
| 是否存在真实父代 | 导出的 CROSS/MUTATE 父代明确是 `HANDWRITTEN_PREVIEW`。其分数都是共同 progress 加固定偏移，赢家不随 progress 变化；不能把它们当真实初始化多样性证据 |

导出 I1 是第0次、空 archive 的完整预览；实际后续初始化由代码按已接受源码追加归档上下文。真实演化尚未开始，没有可读的真实请求提示；运行后父代分化会使 A/B 提示全文不同，此时“唯一差异”指模板、信息规则和模式许可，而非承诺不同父代源码也相同。

### 6.1 原文、问题与最小修改建议（仅建议，未应用）

下面都是已有提示允许但不够醒目的内容。建议如果未来采用，统一改 A/B 共用段并建立新版本；不只给 B 增加鼓励组合的说明，不改本批已冻结/待执行提示。

| 位置与具体原文 | 问题 | 最小建议 |
|---|---|---|
| 任务首句：`Design a deterministic heuristic selector U for static FJSP, not an action priority rule h.` | selector 容易把整体目标理解为只能选一个，虽然后文 MIX 已解除限制 | 把 `heuristic selector U` 改为 `heuristic-usage strategy U`，其余职责保留 |
| 共用任务：`SELECT mode=0: vector entries are finite member-selection scores, allowed negative.`；`MIX mode=1: vector entries are finite nonnegative raw weights with exactly one or two positive entries.` | 规则正确，但没有直接点出计算空间与状态变化范围 | 后面补：`Within the permitted modes, member scores, active members, weights and mode may depend on the seven inputs. Scores or weights may use constants, conditions, linear or nonlinear local expressions; no formula or program skeleton is prescribed.` |
| CROSS：`You may change state conditions, relations between conditions, member mappings and parameters, or rewrite the WHOLE function.` | 罗列条件/映射，评分与权重公式只通过“全部重写”隐含开放 | 在 parameters 后加 `, member-score formulas and, where permitted, support and weight formulas`；保留至少两父代思想的交叉要求 |
| MUTATE：`You may change feature roles, condition relationships, state-to-member mappings, hold/switch conditions or thresholds,` | 容易把“一个假设”落实为阈值/切换修改，评分或组合机制的改变不醒目 | 列表补 `member-score formulas and, where permitted, support, weight or mode rules`；保留一个主要修改假设及可重写整个函数 |

无需修改编号类别、历史、归一化和同分段。无需加入指定公式或阶段例子；教学代码也不建议塞进真实提示作为固定模板。当前虽然 A/INIT 的共用任务含 MIX 定义，但紧接的 `Permitted modes: SELECT (0) ONLY.` 明确限制，执行器也强制此限制；这不是 A 偷偷获得 MIX 能力。

### 6.2 共享 SELECT 初始化研究什么

当前比较是：**在相同固定 H、相同新 SELECT 起点和相同请求槽位下，演化阶段允许 SELECT/MIX 是否改变探索、得到的策略及训练表现。** B 不必须组合，也可一直 SELECT；共同起点有助于减少初始种群差异。

限制包括：初始化没有 MIX，组合必须在一代内从 SELECT 父代产生并被保留；初始化也没有 H 行为信息，因此共同起点并非基于 H 源码设计。这个小试不能直接回答“带 MIX 初始化的空间是否更好”“组合策略充分搜索后能达到什么水平”。B 没用 MIX 也不能说明 MIX 没价值，可能是尚未被生成、未合法执行或未被保留。组间相同请求数不等于相同计算成本。

## 7. 怎样判断这个空间有价值

### 7.1 能运行与有收益分别需要什么

能运行需要候选语法/输出合法、完整实例排程可行、数值处理正确、可确定性复检、失败规则/预算/隔离符合契约。现有测试、toy 与旧路径复现支持这些工程事实；新真实候选仍须完成完整训练评价。

有收益需要在一致 H/调度器/评价规则下比较完整排程表现与成本。评价对象是整条 U 在其造成的状态轨迹上的效果，不能把完整排程 fitness 当成某一步选 h 的正确标签。一步选法会影响后续状态和动作；“在某条轨迹上用了 h0 且最终好”不能证明此状态 h0 局部最优。

### 7.2 确认 B 是否真的组合

同时区分生成、成功评价、进入最终种群三层，而不是只查看获胜候选或整个组的总数：

1. 源码中存在可达的 MIX 返回；只出现 mode=1 文字还不够。
2. 有完整训练有效候选，其 `dual_member_steps>0`。`MIX_steps>0` 可能全是单正项，不能当双成员组合。
3. 汇报双成员步骤/全部步骤比例、涉及实例数、成员对、实际权重与权重变化，并分开报所有有效候选与最终种群。
4. 双成员执行后，收益仍需比较完整排程。两列一致、其中一列恒定、极小第二权重或相同最终动作都可能使组合没有观察到额外作用。

当前 `usage_summary` 已有 SELECT/MIX/dual/single 步数、participation_counts、weight_mass、dominant_counts、dominant_switches、h_calls；`usage_decisions` 可恢复成员对和权重序列。`dominant_switches=0` 不能证明支持集或权重不变。默认独立诊断 `max_actions=0` 不保存逐动作分数列表，故仅凭默认汇总不能认定“另一成员改变了动作”；需要未来单独设计的对照证据，本轮不新增重放。

### 7.3 如实记录常量、单选及退化

| 观察 | 应如何描述 |
|---|---|
| 所有步骤单选同一成员 | “本训练轨迹固定单成员”；如源码明显恒定可另记“源码常量策略”。有限轨迹不能证明全空间恒定 |
| q 随状态变化但赢家不变 | “分数变化、选择未变”；不能只因使用全部输入就说策略自适应有效 |
| MIX 始终一个正项 | “合法单成员 MIX”；不计作双成员组合 |
| 两正项但恒定列/相同偏好等 | 记录真实两成员使用及观察到的无额外作用，不在评价前判无效或偷偷换单选 |
| 同样动作/排程，不同 q、支持集或权重 | 分层报告行为相似性，不直接声称程序普遍等价 |
| 条件在本次训练没触发 | “本轨迹未观察到”；静态证明不可能触发与训练没覆盖要分开 |

`state_diagnostics` 是保守且不完整的区间证明及分支覆盖：`not_proven` 不等于可达，零覆盖不证明普遍等价。它对评分赢家或权重贡献也不是完整语义分析。

### 7.4 A/B 该比较哪些量

| 项目 | 建议报告方式 | 已有记录/限制 |
|---|---|---|
| 完整训练效果 | 共享 P0 最优值、最终最优/种群均值、逐实例 Cmax 与 Cmax/LB；配对报告 A/B 差及胜/平/负，不只报告冠军 | fitness 是均值负比值，越高越好；当前没新结果 |
| 固定成员参照 | 与已重评十条 H 的完整训练结果比较；固定最优 h 的训练值是训练参照 | 不由此声称泛化或局部优越性；额外固定组合参照需未来登记 |
| 请求与失败 | 每组槽位、实际请求、解析/接口/运行/API失败、重复及完整有效候选数；有效数/请求数和失败数都保留 | `all_requests`、`all_evaluations`、`categories`、attempts；失败/重复不补发 |
| 重复/多样性 | AST 重复率与有效候选中训练行为/动作/排程重复分别记录；列出各自分母和观察范围 | 当前去重仅版本化 AST。变量改名、共同分数平移、MIX 同比缩放可能留下不同键；不会自动语义去重 |
| 重复的语义层次 | 分开 raw vector、解码后的支持集/权重、动作序列、最终排程 | 现有训练行为 hash 包含原始 vector，因此共同平移也会改 hash；同 fitness 更不能直接视为重复 |
| 实际 MIX 使用 | 所有成功候选、最终种群分别统计双成员占比及成员对/权重 | 同时保留全部失败记录，不能用成功前缀冒充有效完整候选 |
| 计算成本 | 请求/token/服务时间，主求解、确定性复检、独立诊断，h 调用数和组合处理；每组总量及有效候选单位成本 | 每步动作数 n 时单成员 n 次 h，双成员2n次；轨迹改变也改变后续 n；未知失败成本不能写0 |

相同40上限/每组10槽位只控制生成机会。不能说算力相同，也不能因为 B 多算了一条 h 就认定收益或损失。诊断可缺失但主评价有效，此时行为统计应报告诊断缺失范围；部分成功行的成本总数是已认证部分，不能当失败请求完整成本。

### 7.5 单批能支持什么

seed301、N5、一代的训练小试可说明：这一次生成了哪些合法机制，是否出现真正双成员使用，有多少重复/失败，以及该批训练表现和已记录成本。若 B 优于 A，只能说该批“开放 MIX 的搜索条件下”取得了更好训练结果；若 B 的赢家仍 SELECT，不能把提升归功于实际组合。

稳定收益、提示多样性改善和搜索成功概率需要多种子重复；跨实例泛化需要预先固定选择规则后做独立验证/测试，测试不能用于挑公式、成员对或调参。A/B 整体差异也不能自动证明动态权重优于固定权重、或某一成员对互补；这些需要独立对照。更多分支、更多切换或更多成员都不是质量标准。

## 8. 下一步最值得验证的两个问题

1. **在共享 SELECT 起点与这一代预算下，B 能否生成并保留真正的双成员策略？** 区分“未生成”“输出非法”“完整有效但未保留”“保留且实际双成员”四种情况；同时检查 A/B 的 AST 与训练行为重复、有效率和成本。这先检验当前可表达空间是否实际被搜索触及。
2. **实际双成员使用是否带来超过单选参照的完整排程收益，且成本值得？** 当前批次先看 B/A 与固定 H 的训练结果，并确认领先候选确实双成员。若出现值得追踪的候选，后续另行登记固定权重/状态权重等对照，多种子重复和独立数据验证；避免把本批冠军、复杂代码或 MIX 占比直接当成方法成功。

这两个问题不要求先手工写完全部 U 公式，也不要求先读大量文献。当前实现已经把可计算空间、执行语义和评价对象分开，足以开展下一步证据收集；本轮无需引入外部论文。

首轮交付范围：当时仅新增本文件，代码、既有提示、冻结资产与待执行配置保持原样；未启动实验、发送模型请求或使用验证/测试集调试。后续本分支v2.2实现及其范围见文首链接。
