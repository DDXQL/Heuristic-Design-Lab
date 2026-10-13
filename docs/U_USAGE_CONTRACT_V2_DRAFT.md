# U 使用 H 的扩展契约 V2（草案）

职责：为单成员选择、成员评分后单选、最多双成员加权组合记录接口、执行实现和验证标准。适用范围：固定 H、静态 FJSP、原七项状态、确定性追加式调度。日期：2026-10-12；核对代码提交：`130155daa8b6230205769ed22a2c08d9cb0566b0`，对应标签 `snapshot-20261012-tier2-v5`。

**状态：SELECT/MIX 接口与两组训练入口已实现，独立 toy 行为验证和旧路径回归已通过；真实新候选生成及两组效果实验未执行。** 本稿不替代现行单编号契约，不批准模型请求、实验配置或既有 H 的新研究用途。旧单编号路径见[现行契约](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/docs/fjsp_tier1_contract.md)，研究流程见[研究协议](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/docs/PRD_TIER2_REAL_EXPERIMENTS_v1.md)。

## 一页摘要

目的：扩展 U 可以怎样利用固定 H；允许常量、单选、部分输入和部分成员，不要求决策树、切换或双成员必选，不指定 U 内部计算公式。

| 项目 | 本稿推荐 |
|---|---|
| 接口 | 方案 A：`use_heuristics(原七参数) -> (mode, vector)`；模式和向量均由 U 返回 |
| SELECT，mode=0 | vector 是 K 个成员选择分数，可负；执行器取最高分成员，同分取较小编号，转换为单点权重 |
| MIX，mode=1 | vector 是 K 个非负原始权重；必须恰有 1 或 2 个正权重，由执行器归一化 |
| 原有单选 | 固定或状态选择编号 k 后，返回 SELECT 的单点分数向量；旧整数 U 仅通过显式版本适配器复核 |
| 调用 | 每次单次求解，每个非终止调度步骤调用 U 一次；所有当前合法动作共用同一选择/权重 |
| 动作评分 | 单正权重使用原 h 原始分数；双正权重逐成员在当前全部合法动作上做 min–max，再非负加权求和 |
| 历史状态 | previous_heuristic 为上一步最大归一化权重成员，精确同权重取较小编号；首步 −1 |
| 失败 | 输出、已选 h 或数值处理失败使该实例失败；无静默截断、回退、重试或局部动作删除 |
| 兼容标准 | 新单成员路径与旧路径逐动作、七状态、历史编号、最终排程、Cmax/LB/fitness 相同；耗时不要求相同 |
| 证据边界 | 独立 toy 行为验证及全套回归通过；真实两组生成/效果未执行 |

推荐 A 的原因：执行器能明确区分“比较成员选择分数”和“混合动作优先级”，统一强制成员分数同分规则，并在轨迹中保留真实模式。方案 B 只有权重，成员评分的 argmax 和同分处理要藏在 U 内部，执行器无法核对其原始选择分数。这里优先选择可审计的语义；代价是两种模式及一个嵌套返回结构。

第一版仅支持线性非负加权和。乘积、逐动作最大值、负权重、未来排程模拟、新状态输入和超过两个正权重不在此稿范围。

## 1. 旧路径事实及扩展限制（设计时核对，默认旧路径保留）

未发现适用的 AGENTS.md。已搜索现有 docs、code/fjsp_usage、experiments/tier2 中组合/权重/ensemble 等定义；没有发现动作分数多成员组合的执行接口或对应契约。现有“权重”主要用于父代抽样，与本稿的动作评分权重不同。指定文档此前不存在。

当前实际链路：`Workflow.train_eval → StagedDataset.evaluate → research_real.runtime.evaluate → _worker → research.scheduler.construct_usage_schedule`；后者复用 `offline_v2._SchedulingState`。真正的研究调度循环在 research/scheduler.py，不能仅根据 offline_v2 的演示入口推断执行行为。

| 当前事实、函数与准确行号 | 对扩展的限制 |
|---|---|
| [offline_v2.StateFeatures，第26行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/offline_v2.py:26)，[_SchedulingState.__init__，第63行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/offline_v2.py:63)，[features，第82行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/offline_v2.py:82) | 六个 float 加一个 int；T/C 固定；历史读取 selected_members 最后一项，无法保存完整权重历史 |
| [offline_v2.construct_usage_schedule，第99行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/offline_v2.py:99)，U 调用第114行、整数检查第117行、历史追加第154行 | 演示路径只接受合法 built-in int；元组、向量无法执行 |
| [research.scheduler.construct_usage_schedule，第17行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research/scheduler.py:17)，第35行调用 U、第38行检查、第41行取 H[k] | 研究路径每步一次 U，随后仅一个 h 评分全部合法动作；必须增加版本化派发，不能直接放宽类型判断 |
| [同函数动作评分，第54行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research/scheduler.py:54)，第59–66行数值检查、第72行严格大于、第78–87行提交与追踪 | h 接收七项原始动作特征，高分胜出，精确同分由作业/机器枚举顺序决定；没有分数矩阵、归一化或混合轨迹 |
| [candidates.validate_code，第47行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research/candidates.py:47)，旧分支仍检查精确函数名、返回注解与 AST 白名单 | 当前 U 函数名 select_heuristic、返回注解只接受 int；禁止 tuple/list/dict、下标和推导式；不能返回组合向量 |
| [candidates.compile_candidate，第132行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research/candidates.py:132)，旧标量 bounded/编译分支保留，新增显式接口派发 | 数值调用结果受标量 guard；新增返回容器不得使任意容器或非数值绕过限制；编译出口绑定旧函数名 |
| [research_real.prompts.U_TASK，第17行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/prompts.py:17)，第19行单 h、第38行 int；[prompt_sections，第87行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/prompts.py:87) | 实际任务和输出接口仍是单编号；INITIAL/P_CROSS/P_MUTATE 及 H 上下文必须统一新语义，不能只改输出一行 |
| [initialization.selector_signature，第27行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/initialization.py:27)，[initialization_prompt，第46行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/initialization.py:46) | 窄等价只处理纯整数 return/int(整数)；归档调用旧校验器。不能把此规则直接套到向量或把训练同分当等价 |
| [state_diagnostics.state_contract，第28行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/state_diagnostics.py:28)，[static_diagnostics，第187行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/state_diagnostics.py:187)，[Coverage，第240行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/state_diagnostics.py:241) | 先调用旧 U 校验；条件区间分析不认识新返回模式/向量合法性；previous 的数值域不变，但语义须版本化 |
| [diagnostics.member_usage，第8行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/diagnostics.py:8)，[runtime._worker，第21行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/runtime.py:21) | 使用率只统计单编号；旧 selected_members 不能代表组合成员集合、权重或贡献 |
| [assets.checked_candidate，第38行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/assets.py:38)，[check_population，第147行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/assets.py:152)，[config.protocol，第319行](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/config.py:322) | 现有资产重新按旧接口校验，协议语言/actions 也写明单编号；新语义必须进入资产上下文及缓存键 |

候选目前允许一个精确参数函数、局部数值变量、算术、比较、if/while/for，以及 abs/min/max/int/float/round/range；禁止外部名称、导入、属性、容器、辅助函数和随机性。字面量绝对值 ≤1e9，受保护数值中间值有限且幅度 ≤1e100，幂指数和 round 位数另有约束。模型响应须恰为一段说明及一块 Python 代码；这些限制不要求 U 使用决策树。

当前 h 保持原七项动作输入：加工时间、含当前工序的最短剩余工作量与剩余工序数、作业/机器就绪时间、最早开始/结束时间。合法候选是各未完成作业的下一工序及其可选机器；机器暂忙仍可成为候选。动作追加到机器尾部，不找空档。

## 2. 接口方案选择

| 方案 | 简短优点 | 简短代价 |
|---|---|---|
| A：模式及成员分数/权重（推荐） | 成员选择分数和混合权重可区分；执行器实现 argmax 同分；轨迹能直接区分两种执行语义 | 两个模式，返回结构略复杂，语言需支持有限嵌套元组 |
| B：统一非负权重向量 | 无模式字段，单选是单点向量；校验和调度入口更统一 | U 必须先自行把选择分数变成单点权重；执行器只见权重，不能核对隐藏选择分数的同分和 argmax |

以下只展开 A，不同时建立 B 的实现路线。两种接口都不意味着 U 必须调用全部 h。SELECT 输出 K 项选择分数，也只是 U 的本地数值计算，并非 K 条 h 的动作评分。

### 2.1 函数、类型和成员顺序

已实现接口版本名 `U-usage-v2-select-or-mix-20261012`，函数如下；名字变化用于防止旧整数程序被误读为新程序，不增加输入：

```python
def use_heuristics(progress, candidate_pair_ratio,
                   remaining_work_mean, remaining_work_std,
                   machine_ready_mean, machine_ready_std,
                   previous_heuristic):
    # 以下为K=3的接口示意，不是实际候选或已验证实现。
    return (0, (3.0, 2.0, 1.0))
```

返回值必须是 built-in tuple，恰有两项 `(mode, vector)`。mode 必须为 built-in int，取 0=SELECT 或 1=MIX；bool、float 模式和其他编号均非法。vector 必须是 built-in tuple，长度精确等于冻结 H 的 K；第 i 项对应 H.members 中 member_id=i 的同一代码键。K 由冻结配置确定，生成时可以知道；不作为第八个状态输入。不得通过向量重排隐式重排 H。

每个 vector 元素仅接受 built-in int/float，拒绝 bool、None、复数、字符串和外部数值类型；必须有限、绝对值 ≤1e100。数值字面量仍 ≤1e9。不要求返回注解，第一版新候选拒绝返回注解，避免为类型表达开放下标/属性语法。现行 h 和旧 U 的校验规则保留。

语言只新增**返回语句根部的上述二层元组构造**：mode 与 K 个元素仍是受限标量表达式；不开放 list/dict/set、下标、容器变量、推导式、任意嵌套元组或把元组传入数值 builtins。所有路径必须返回同一结构。U 内部可有任意合法数值计算和控制流，也可仅返回常量。

输出形状可做静态检查，mode 范围、负值、正权重个数及状态相关异常还必须逐调用检查；“通过 AST”不等于所有状态下都合法。新增终端结构校验与原标量 `_bounded` guard 分离，不能笼统允许任意 tuple 通过后者。

### 2.2 SELECT：选择分数不是动作分数

令 U 输出 `(0, (q0, ..., qK−1))`。qi 是 U 根据同一七状态给 h_i 的选择分数，不是 h_i 的输出，不是估计 makespan，也不自动具有概率或真实局部优越性的含义。qi 可为负；用返回的 int/float 数值按 Python 数值比较，不先转成 float 造成大整数选择分数合并。

执行器选择 `k = 最小的满足 qk=max(q) 的编号`，生成单点权重 alpha_k=1、其余为0。精确同分取较小编号，不使用近似同分容差。全零、全相同或全负分数仍合法：按上述 argmax 规则选择；SELECT 没有“全零权重”问题。

原有单选 k 可表达为 `(0, e_k)`，其中 e_k 第 k 项为1、其余为0。按状态选择 k 后，也可返回相应单点分数向量；没有规定函数必须以 if 树表示。

### 2.3 MIX：非负权重，最多两个正项

令 U 输出 `(1, (r0, ..., rK−1))`。ri 为原始组合权重，必须非负。−0.0 按0处理；依据 `ri>0` 计算支持集 S。必须满足 `1≤|S|≤2`：单成员合法，全零失败，三个及以上正项失败。执行器不得偷偷取 top-2、忽略小正值或修补负值。

理想归一化为 `alpha_i = ri / sum_j rj`，零项保持0。执行器固定数值实现：先把已检查权重转换成有限 float；以最大正权重 M 缩放，`vi=ri/M`，再按成员编号升序用 math.fsum 得到 s，计算 alpha_i=vi/s。中间量非有限、正权重下溢成0、归一化后支持集缩小或 alpha 非正均使实例失败；不加 epsilon、不设最小正权重、不改成单选。单正项直接得到精确单点权重1。

理想权重和为1；浮点核验允许绝对误差1e−15，且所有权重必须有限、非负。容差只用于数值核验，不用于成员或动作同分。保留原始权重与实际归一化结果，不能把全零自动转为等权。

### 2.4 从选择分数到组合权重

SELECT 的 qi 在执行器中通过 argmax 转成单点权重，这是“先给每个 h 打分，再选最高成员”的直接表达。

若 U 希望组合两个成员，应自行基于状态/本地选择分数决定支持集，并输出 MIX 的 ri。若按 qi 排名选 top-2，推荐用“分数降序、编号升序”处理同分；只需单选时选 top-1。执行器不接收 MIX 路径的隐藏 qi，因此无法自动认证 U 是否真的执行了这一排名；声称按 qi 选 top-2 的候选需要源码核对与定向样例，不能在报告中假定它已满足。

已选分数为正时可直接把它们作为原始权重，例如 q=(3,2,1)，选择0/1后返回 `(1,(3,2,0))`。若分数含负值，可在 U 中使用确定性非负变换，例如对选中集合用 `ri=qi−min_selected(q)+1`、其余为0，再由执行器归一化；该表达仍须满足数值语言限制。变换会影响权重比例，不与直接使用 qi 等价。这些只是表达例子，不是必须采用的公式；U 也可以直接计算合法权重。

### 2.5 异常处理与旧编号适配

非法 mode、类型、向量长度、数值、MIX 支持集，或 U 抛异常/超时，都在调用任何 h、提交任何动作之前失败。没有部分向量补零或越界编号截断。

新接口靠位置标识成员，没有单独的成员编号字段；非法成员对应表现为与 H 不符的长度/映射绑定，不能自动猜测。旧整数 U 的显式测试适配器应先检查 `type(k) is int` 且 `0≤k<K`，再转 `(0,e_k)`；负数、K、bool、float 仍失败，不能先 int() 截断。适配器不得增加 U 调用次数。

## 3. 状态与历史契约

保留六项连续状态的计算、T/C 和归一化边界。令 Q 为总工序数、t 为已排数、T 为逐工序最大可选加工时长之和、C 为逐作业最大机器可选数之和：

| 输入 | 保留的定义和非终止状态边界 |
|---|---|
| progress | t/Q，0≤值<1 |
| candidate_pair_ratio | 当前合法动作数/C，0<值≤1 |
| remaining_work_mean | 未完成作业最短剩余工作量/T 的均值；有 a 个未完成作业时 0<值≤1/a |
| remaining_work_std | 上述总体标准差；0≤值≤sqrt(a−1)/a≤0.5 |
| machine_ready_mean | 所有机器末端时间/T 的均值，包括未使用机器；0≤值≤1 |
| machine_ready_std | 上述总体标准差；0≤值≤0.5 |
| previous_heuristic | 首步−1；其后为上一已提交步骤的最大权重成员编号，同权重取较小编号 |

两对 mean/std 仍满足 std²≤mean(1−mean)，std/(1+mean)≤sqrt(2)/4。T/C/a 不新增为输入。

历史推荐明确为 `dominant = min argmax(alpha)`，使用执行器实际归一化后的权重比较；SELECT 或 MIX 单点权重时就是旧的成员编号。动作成功提交后才记录 dominant，下一步才能读取；每个实例、每次确定性复检都从−1重置。失败步骤不更新历史。

该单个编号会丢失：另一成员、完整权重比例、上一模式、原始选择分数、动作分数及动作身份。例如 (0.6,0.4,0) 与 (0.9,0,0.1) 的历史都是0；(0.5,0.5,0) 的历史也是0。这是第一版保留七输入的有意信息压缩，不可声称 U 看到了上一完整组合。未来若要传权重历史，必须建立新的状态接口版本。

权重以浮点归一化时，极接近的不同原始权重可能舍入为同权重；按实际 alpha 和较小编号决定历史并记录该现象，不暗用另一套原始权重规则。旧单点路径没有此问题。

## 4. 执行与动作组合评分

### 4.1 三种分数必须分开

| 名称 | 由谁产生 | 比较对象及作用 |
|---|---|---|
| qi，成员选择分数 | U，在 SELECT 中返回 | 比较 h 的编号，决定调用哪个 h；不评价具体动作 |
| bi(a)，原始动作优先级 | 已选 h_i | 对合法工序—机器动作 a 打分，高分优先 |
| F(a)，最终动作分数 | 执行器 | 单成员为 bi(a)；双成员为归一化后的非负加权和，决定实际动作 |

MIX 返回的 ri/alpha_i 是成员的组合系数，不是 bi(a) 或 F(a)。U 不获得动作列表，不执行 h；固定 H 的代码/行为可在离线提示中作为上下文，不成为运行时资源。

### 4.2 已实现执行顺序（实际代码的伪代码概括）

```text
初始化状态和空历史
对每个非终止步骤：
    读取七状态；调用 U 恰好一次
    校验 (mode, vector)，生成支持集 S 和 alpha
    固定当前合法动作 A，按 (job, machine) 升序；不得随 h 改变
    对 S 中成员按编号升序：
        对每个 a∈A 调用 h_i 恰好一次，检查原始有限分数并缓存
    若 |S|=1：以该 h 的原始分数作为 F
    否则：逐成员在完整 A 上归一化，再固定顺序求加权和 F
    取 F 最大动作，精确同分取较小 job，再较小 machine
    提交一次动作；推进作业游标和两个 ready；记录 dominant 与组合轨迹
结束：独立校验完整排程，计算 Cmax、原 V5 LB 与 score
```

同一步的 A、h 输入和权重固定；评分过程中不提交动作、不更新 ready、不重新调用 U。只有下一步重新计算状态、合法动作和组合。未选成员不进行动作评分；允许加载/编译冻结 H，这不等于在调度步骤中调用所有 h。

### 4.3 为什么不能直接相加

h 输出都只规定“越大越优先”，没有共同量纲、幅度或概率校准。一条 h 的分数乘100，其单独动作排序不变，但直接加权后可压过另一条 h。因此直接原始分数相加可能主要反映程序的尺度，而非 U 指定的相对权重。

第一版双成员推荐在**同一步的完整合法动作 A**上逐成员 min–max。它消除正比例缩放和平移的尺度差异（理想算术下），保留每条 h 当前的排序及相对位置；不会把序数偏好变成已证明可比较的“质量”。极端值和候选动作集变化仍会影响归一化，所以这是需登记并评价的工程选择，不是效果结论。

令 `li=min_a bi(a)`、`ui=max_a bi(a)`：

```text
若 ui>li： zi(a) = (bi(a)−li)/(ui−li)
若 ui=li： zi(a) = 0，所有动作相同
双成员： F(a) = sum_{i∈S} alpha_i * zi(a)
```

常量成员的归一化列为0，不重新分配它的权重；另一成员的贡献按原 alpha 缩放。两列都为0时全部动作同分，按既定动作顺序选。只有一个合法动作时两列都为0，选择该动作；仍检查实际已选 h 的输出，不能借唯一动作跳过非法分数。

### 4.4 数值规则

原 h 输出维持现行 real scalar、拒绝 bool、可转有限 float 的检查，缓存转换后的 bi(a)。任一已选 h 对任一合法动作返回非有限数或抛异常，使该实例失败；不删动作、不丢成员、不按剩余部分打分。未选 h 的潜在异常不应影响该步骤。

为避免有限端点的 `ui−li` 因相反大数而溢出，双成员执行器建议固定稳定实现：先以缓存分数判断精确 `ui==li`；不相同时取 `B=max(abs(li),abs(ui))>0`，再计算 `L=li/B`、`V=ui/B`、`X=bi(a)/B`，用 `(X−L)/(V−L)` 得到 zi。若原端点不同但缩放后的极差为0、归一化结果非有限或不在[0,1]，记录数值归一化失败；不改判为常量、不加 epsilon 或静默截断。

按成员编号升序计算非负乘积，并用执行器的 math.fsum 求 F；浮点范围核验可容许1e−15的权重和/最终范围余量，但不修改 F，不做近似同分。固定 Python/运行平台及数值实现哈希；不宣称跨任意平台位级一致。极端有限输入、很小正权重和非常窄分数范围须纳入 toy 验证。

归一化及求和都是执行器职责；生成 U 无权选择另一归一化、增加 epsilon、改用乘积或逐动作最大值。U 只能改变模式和合法成员分数/权重。

### 4.5 单选严格兼容及计算成本

理论上单成员 min–max 不改变排序，但浮点运算可能把不同原始分数舍入为同分。因此所有只有一个正权重的路径——SELECT 以及 MIX 单点——**直接沿用原始 bi(a) 的比较**，不做 min–max。这样能够提出并验证严格的旧单选等价标准；不能只以 makespan 相同替代逐步等价。

每步有 A 个动作、s=|S|：旧路径 A 次 h 调用；新单选仍 A 次，双成员为2A次，U 始终一次。min/max 与混合增加 O(sA) 算术，缓存原始分数与当前动作需要 O(sA) 内存；不能为求 min/max 再调用一次 h。评分缓存仅属于本步骤，不跨状态复用。规范推荐按成员编号、再按动作顺序计算；与旧路径的单 h 动作顺序相同。

单选兼容指成功求解的数值与动作语义，不承诺耗时或临近超时门槛的结果相同；新增主机开销须实测、如实计入期限和失败记录，不能为了复现而隐藏成本。

这些分数只使用当前合法动作及现有 ready/remaining 信息，不构造未来排程、不做 lookahead；h/U 在单次求解中固定、无学习或自修改。外层 LLM 生成成本与求解成本分开。未来主评价仍保留两次确定性求解和独立观察期限，计入全部组合成本，不能隐藏第二条 h 或诊断成本。

## 5. 同一教学数据的三个结果

仅为独立工程教学数据，不对应真实训练/验证/测试实例，也不构成完整排程或效果证据。三动作均设为当前合法动作，稳定顺序 A<B<C：A=(job0,op0,machine0)，B=(job0,op0,machine1)，C=(job1,op0,machine0)。共有 h0、h1、h2。

| 动作 | h0原始分数 | h1原始分数 | h2原始分数 |
|---|---:|---:|---:|
| A | 10 | 0 | 2 |
| B | 6 | 80 | 0 |
| C | 0 | 100 | 20 |

U 的成员选择分数设为 q=(3,2,1)。保持这份分数矩阵不变，比较三种用法：

1. **固定 h2：**返回 SELECT 单点分数 `(0,(0,0,1))`，权重为(0,0,1)。最终原始动作分数(2,0,20)，选 **C**。
2. **按 q 选最高成员：**返回 `(0,(3,2,1))`。q0最高，执行器得到(1,0,0)，最终原始动作分数(10,6,0)，选 **A**。与固定 h2 的差异发生在成员选择。
3. **按 q 选两个正分成员并组合：**U 明确选择 h0/h1，返回 `(1,(3,2,0))`；alpha=(3/5,2/5,0)。h0在三动作上 min=0、max=10，归一化为(1,3/5,0)；h1 min=0、max=100，归一化为(0,4/5,1)。h2不被调用，其表列只是便于同一教学数据比较。

| 动作 | z0 | z1 | F=(3/5)z0+(2/5)z1 |
|---|---:|---:|---:|
| A | 1 | 0 | 3/5=0.60 |
| B | 3/5 | 4/5 | 9/25+8/25=17/25=0.68 |
| C | 0 | 1 | 2/5=0.40 |

故双成员归一化组合选 **B**，历史 dominant 为0。它可以选择一个并非 h0 或 h1 各自最高分的动作：不同成员的相对偏好共同作用。

如果仅为说明尺度问题而对同一矩阵直接算原始加权和，会得到(6,35.6,40)，选 C；这是对照算术，不是本稿允许的双成员执行规则。选择 B 与这个结果的差异来自归一化；选择 B 与按 q 单选 A 的差异来自双成员组合。三个正式教学结果依次为 **C、A、B**。

本轮用独立 Python Fraction 小计算核对 3/5、2/5 及三动作加权结果；只证明这些数值算对，不证明接口、排程或方法有效。

## 6. 原修改清单与本轮实现映射

下表保留设计时的模块职责清单。实际采用独立 usage_v2 模块及旧组件的显式版本扩展点，offline_v2 和旧 research/scheduler 没有改写。具体实现映射和验证凭证见第9节。

| 模块及入口 | 设计职责（实际映射见第9节） |
|---|---|
| [research/candidates.py：validate_code / compile_candidate](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research/candidates.py:47) | 增加明确的 U 接口/语言版本；新函数名、精确返回元组位置和终端形状检查、字段数值 guard；旧 int U 与 h 规则不变；版本进入候选身份，避免共用旧校验/缓存 |
| [research/scheduler.py：construct_usage_schedule](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research/scheduler.py:17) | 新版本执行入口及纯主机输出解码、SELECT argmax、MIX检查/归一化、选中成员矩阵、单选原始比较、双选min–max/加权和；旧入口保持；所有检查后才提交 |
| [offline_v2.py：StateFeatures / _SchedulingState / UsageResult](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/offline_v2.py:26) | 复用前六输入及调度更新；新状态包装明确 dominant 历史；建立独立 UsageResultV2，保存组合步骤和dominant序列，不改旧演示结果的含义 |
| [research_real/prompts.py：U_TASK / INITIAL / P_CROSS / P_MUTATE / prompt_sections](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/prompts.py:17)，[research/prompts.py：OUTPUT](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research/prompts.py:9) | 新提示包与新输出语言约束，给出模式、K顺序、历史含义、故障规则、执行器归一化、成员分数与动作分数区别；不得改旧提示常量来覆盖旧记录；四组信息差与算子差另行保持一致 |
| [initialization.py：selector_signature / initialization_prompt](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/initialization.py:27)，[research_real/search.py：V5BudgetedSearch](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/search.py:50) | 用新校验器归档；新版本首先使用 AST 去重，不自动推断 SELECT 平移、MIX同比缩放或跨模式普遍等价；保留旧窄整数规则及版本；预算内如实统计失败/重复 |
| [state_diagnostics.py：state_contract / static_diagnostics / Coverage](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/state_diagnostics.py:28) | 新 previous 语义、合法输出诊断和tuple节点遍历；保留保守条件边界与自然分支覆盖；不得把无切换/单选/常量判无效 |
| [runtime.py：_worker / _diagnostic_worker / evaluate](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/runtime.py:21)，[staged_evaluation.py：evaluate](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/staged_evaluation.py:80) | 按声明版本编译/派发；复检完整组合输出与排程；独立诊断不改fitness；保留逐实例可行性/Cmax/LB/score及求解、复检、组合处理、诊断时间 |
| [diagnostics.py：member_usage](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/diagnostics.py:8)，[training_report.py：write_training_report](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/training_report.py:20)，report.py | 分开报告成员参与次数、归一化权重质量和、dominant转换、模式占比与h调用次数；dominant未变不代表组合未变；完整训练行为哈希应包含mode/支持集/权重/动作 |
| [config.py：ExperimentConfig / protocol / fingerprint](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/config.py:97)，[assets.py：checked_candidate / check_population](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/assets.py:38)，evaluation_cache.py | 配置、资产和缓存绑定 U 接口/语言/归一化/历史/轨迹版本、max_active_members=2、H顺序代码键、执行源码与数据身份；完整重新评价新/适配候选 |
| [workflow.py：train_eval / search_engine / stage_eval](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/code/fjsp_usage/research_real/workflow.py:94)，run.py、fixtures.py、preparation.py及后续独立配置 | 新版本可运行入口和toy fixture；原冻结/开发恢复拒绝新上下文；不重写历史配置、H/U、receipt或已用额度，不在本稿开启真实生成 |

建议新的配置语义字段为 `u_interface_version`、`candidate_language_version`、`usage_modes`、`max_active_members=2`、`action_score_normalization`、`history_rule`、`numeric_rule_version`；具体已实现字段以 UsageConfig 和导出的 config.pending.json 为准；不把旧四组 CLI 当成新入口。现有模型渠道、期限、请求上限及额度沿用各自已授权边界，不能因接口扩展重置。

必要轨迹：调用前七状态；U原始(mode,vector)；解码后支持集/实际alpha/dominant；SELECT原始选择分数；完整动作数与稳定顺序；每个已选成员的原始分数/min/max/归一化值；最终F与chosen；下一历史；各段耗时和失败位置。普通轨迹可限量保存动作明细，但归一化永远使用全部合法动作，且必须记录明细是否截断；极值和最终动作不能因日志限量改变。诊断重放使用相同规则并核对输出、权重及动作，不为了日志再次调用主求解的 U/h。

确定性比较/行为哈希只包含语义字段，不包含时间戳、求解耗时或日志截断上限；成本独立记录，否则两次合法求解也会因耗时不同被误判为不确定。

H编号、代码、原审查与来源保留；既有范围是否覆盖新研究须由资产门禁核验，本稿不填写批准。旧整数 U 不自动变成新真实候选：适配需保留原代码/键/receipt、显式适配器版本与哈希，并在新协议完整重评；不得拿适配代码去匹配旧真实响应，或把适配当新增真实生成。旧 fitness、训练行为哈希及真实请求计数不改写。

## 7. 行为验证与通过标准

以下核心断言已在 test_U_usage_v2.py 和 test_usage_v2_workflow.py 的独立 toy/手写 fixture 验证中执行，通过。原168项旧路径测试同样通过。未读取真实 validation/test 调试，离线通过不是效果证据。

| 验证项 | 预期结果/通过标准 |
|---|---|
| 常量/状态相关旧 U 的单选适配 | 旧执行器、新SELECT单点、新MIX单点逐步骤动作、七状态、历史、完整排程、Cmax/LB/fitness完全相同；包括精确同分、负h分数和极接近有限分数；不要求耗时相同 |
| 教学混合矩阵 | alpha=(0.6,0.4,0)，归一化列及F与3/5、17/25、2/5手算一致，最终B；浮点数值比较可用1e−12，动作断言必须精确 |
| SELECT同分与全零 | q=(2,2,1)选h0；q全零选h0；q全负仍取最高；高位大整数比较不因先float化合并；只调用赢家 |
| 成员历史同权重 | MIX (1,1,0)的dominant为0；0.6/0.4与0.9/0/0.1都写0，但轨迹保留不同组合；每实例重置−1 |
| 最终动作精确同分 | 选较小job，再较小machine；支持集输入大小或成员计算顺序不得改变规则；不把仅相近的分数当同分 |
| 常量列/唯一动作 | 一列相同→全0且不重新分配权重；两列相同→稳定选最先动作；唯一动作合法分数可选，非有限分数仍失败 |
| 输出形状/类型 | 裸int、list、外层非两项、向量长度K±1、bool/float/未知mode、bool分数、字符串/None/NaN/Inf均分类失败，尚未调用h和提交动作 |
| MIX非法权重 | 全零、负权重、三个正项、正项下溢均准确失败；不截top-2、不加epsilon、不回退为单选；单正项合法 |
| 旧适配器非法编号 | −1、K、True、1.0失败，不截断；有效k只调用原U一次，映射第k成员 |
| U调用次数 | 在每一次成功求解中U调用数恰好Q，终止后0；复检与诊断是另外完整求解，各自计数，不混称整个评价只调用Q次 |
| h调用次数 | 每步骤单选A次、双选2A次，未选h为0；未选h设置抛异常哨兵不影响该步；已选h故障必须失败；归一化不能多调用h |
| 数值稳定性 | 相反大有限分数不因直接相减溢出；缩放极差消失或不合法中间量有明确失败；普通范围与直接公式/精确Fraction参考一致；正比例缩放和平移不变性在可表示toy范围核对 |
| 无状态中途更新 | 同一步各h收到相同动作特征；计算完整矩阵后才提交；U无法接触H、动作列表、未来排程或可变全局状态 |
| 排程与确定性 | 多步toy完整排程独立 validate_schedule 通过；同环境重复运行的模式、原始输出、权重、动作、历史和最终排程一致；失败实例使整批fitness=null，不取成功前缀均值 |
| 追踪与资产隔离 | 开/关诊断排程一致；截断日志不截断归一化动作；新旧接口/归一化/H顺序变更触发上下文或缓存拒绝，旧记录不改 |

对应已有测试框架可扩展 test_research_execution.py、test_fjsp_usage_v2.py、test_state_scale_diagnostics.py、test_U_initialization_novelty.py、test_research_real_workflow.py；新增组合单元测试应优先覆盖上表的独立行为断言，不只复述实现代码。

## 8. 后续参照与尚待登记的研究决策

建议参照条件：固定单成员全部 K 条（新协议重评，验证单选兼容）；固定等权双成员 `(1, e_i+e_j)`（建议完整报告全部无序对，K=10时45对，若小试只选子集须预登记）；状态相关单选；状态相关组合权重。固定双成员与状态相关权重统一使用本稿同一归一化、动作同分、历史和评价器。是否保留所有结果或用验证集选最终参照，在测试前登记，绝不能用测试挑成员/对。

状态相关组合还应区分“固定成员对、仅权重变化”和“成员对与权重都变化”，以免把成员选择变化的收益全归因于权重。单纯成员评分后argmax仍是单成员选择，执行能力与旧U同属状态到编号的映射；它改变程序表示/搜索方式，不直接增加动作组合能力。不同模式可表达相同策略，代码形式不同不作为性能收益证据。

下一次真实比较需要分别固定或登记：H来源与新研究使用范围、候选允许模式（仅SELECT/允许MIX）、各组提示信息和算子安排、共享初始化及预算、完整评价期限、归一化/语言版本、种子数量与代数、固定参照选择方式及数据使用边界。旧B0/B1/B2/P的含义不由本稿改写。单选与组合耗时可能不同，应同时报告真实请求、token、有效/重复/失败候选及完整评价成本，不能只按请求数宣称计算预算相同。

这些是后续实验范围与因果比较的决定，不是阻止本稿落地的接口疑问。第一版接口、两成员上限、同分、历史、归一化和数值异常处理已有明确技术推荐；本轮已据此实现并完成toy验证；待执行配置只覆盖一个种子的训练小试，真实请求仍需另行批准。乘积/最大值、新状态和多于两成员留到后续版本。

本轮交付包括版本化运行代码、离线行为测试、toy端到端验收、训练准备及本文件状态更新；旧候选、冻结资产、历史账本不改写。没有新增真实模型请求或真实验证/测试。固定H重评和旧U兼容复现仅使用训练集，不作为新生成候选或效果结论。


## 9. 本轮实现、证据与可复现入口

实现入口为 `experiments/tier2/usage_v2/run.py`，与旧四组入口分开：prepare、freeze-h、initialize、search-arm、search、report、compatibility；examples/synthetic-acceptance 只产生明确手写的 toy 凭证。不存在真实 validation/test 阶段。

| 实际文件 | 已实现内容 |
|---|---|
| code/fjsp_usage/usage_v2/candidates.py | 新候选身份、终端元组语法，复用旧数值白名单逐标量核对 |
| code/fjsp_usage/usage_v2/execution.py | SELECT/MIX解码、同分、权重/min–max、单选兼容、dominant历史、调用计数与成本回调 |
| code/fjsp_usage/usage_v2/prompts.py、exports.py | 两组统一提示与完整导出；初始提示相同，交叉/变异只差 allowed_modes |
| code/fjsp_usage/usage_v2/config.py、search.py、workflow.py | 版本与缓存上下文、共享SELECT起点、两组预算/搜索、全部候选及成本报告、H范围门禁 |
| code/fjsp_usage/usage_v2/fixtures.py、examples.py、compatibility.py | 手写本地接入、可读源码与完整toy轨迹、真实来源旧U的显式适配训练复现 |
| research/candidates、evolution；research_real/assets、config、workflow、runtime、initialization、search、state_diagnostics | 默认旧路径保留的派发/复用扩展点，资产/响应绑定，新主评价及独立观察成本分开 |

设计落实时明确了三点：①新向量只在终端返回语法开放，其标量内容仍借旧验证器核对；②新执行器复用旧状态类，在新路径内部以 dominant 更新其历史列表，旧状态代码不改；③耗时不进入语义结果/行为哈希，避免确定性复检被真实耗时差异误判。保留设计依据，没有更改七输入、动作枚举或原单选规则。

固定H与旧U的离线训练检查以各自新凭证为准，不回填旧fitness。手写提示预览父代不进入真实P0；真实初始化后提示会绑定实际父代和已接受源码。真实初始化不足5就失败，不降N、不补员。

推荐待批准训练批次：seed301、N5、共享初始化最多20次、A/B各1代10次（5交叉+5变异），最多40次新请求。沿用Leaf gpt-5.6-sol及原生成参数/15秒实例期限；历史79槽位加本批上限为119/300，原未结算1200万点和全部未知token继续保留。配置禁用真实请求，H新研究用途没有伪造批准。旧60次四组提案不是本批授权。

复现命令、最终测试记录、准备配置、完整提示及实例成本以运行指南的新usage_v2章节和最新离线凭证为准。固定参照结果是训练证据；真实双成员收益、初始化多样性和独立泛化尚未检验。

提示2.1修订仅把已实现的“向量元素禁止bool”和“仅终端元组字面量”说明补齐，接口、算法与去重未变；修订同时作用于A/B，组间仍只差allowed_modes。此前2.0本地准备保留为离线记录，新协议使用新目录；不存在真实重复率改善或效果归因。


### 最终离线凭证（2026-10-13完成）

- [最新准备与待批准配置](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/runs/leaf-usage-v2-AB-preparation-20261012-v2/Preparation.json)：10/10 H均通过完整21train并复现makespan；真实请求0，两组未开始。
- [真实来源旧U兼容复现](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/runs/leaf-usage-v2-AB-preparation-20261012-v2/Legacy_compatibility_audit.json)：5/5 U各21实例，动作/状态/历史/排程一致；不成为新P0。
- [完整提示与差异](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/runs/leaf-usage-v2-AB-preparation-20261012-v2/prompts/Prompt_comparison.json)：初始相同，交叉/变异仅允许模式段不同；预览父代明确手写。
- [最新toy全链路验收](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/runs/usage-v2-toy-acceptance-20261012-v3/Synthetic_acceptance.json)：共同5初始U、两组各10槽位、生存选择和完整成本记录；包括重复/接口失败/运行失败/解析失败，不补发。
- [完整toy例子](/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/runs/usage-v2-examples-20261012-v1/Examples_summary.json)：第一动作C/A/B，完整排程Cmax=11/11/12；后者明确不是组合优于单选的证据。

全套188项测试通过；其中新增20项覆盖接口、兼容性、组合、调用次数和两组门禁。尚未执行：真实新共享初始化、A/B真实演化、真实混合策略有效性/重复率测量、验证选择及独立测试。固定H和旧U训练复现仅支持工程兼容性，不支持研究收益。
