# 当前研究方案与完成条件

职责：当前H构建、四组U演化、资产门禁和正式完成条件。范围：`research_real_v1/run.py`及实际V5提示适配；描述代码和未定研究约束，不沿用旧批次授权。当前运行证据统一见[README](../README.md)，输入与评分见[契约](fjsp_tier1_contract.md)，命令及待定配置见[指南](../experiments/tier2/research_real_v1/README.md)。

## 目标与当前边界

Tier 1 构建互补启发式集合 H，完整训练评价、行为审查、冻结后供 Tier 2 使用。Tier 2 演化选择程序 U：每步根据七项状态选一个成员；h 对合法动作评分；调度器执行动作。LLM 只在外层生成候选程序，单实例求解期间不调用模型。

当前正式路径是 `experiments/tier2/research_real_v1/run.py`，不是单规则 EoH 入口，也不是早期 mock 演示。`Workflow.search_engine` 使用 `V5BudgetedSearch` 覆盖基础 `Search` 的提示构造；当前源码为 `V5-FJSP-selector-prompts-v5-state-bounds-20261011`，在v4去重归档基础上仅增加归一化状态边界说明。已冻结开发批次仍绑定v3，不能直接resume或混写版本；当前进度及迁移缺口见根README。相邻 EoH-S 的早期真实集合、已冻结的单规则基线、开发H和当前待生成正式H按不同协议分别报告。

## 从 H 到 U* 的调用链

```text
run.py main
  → Workflow.generate_h
    → V5BudgetedSearch → Search(kind=h, arm=H).run
    → H_candidates.json → Workflow.review_h → 审查包/模板
  → Workflow.freeze_h(真实人工审查文件)
    → H_frozen.json → Workflow.h_asset → load_h → Candidate成员
  → Workflow.initialize_u(seed) → 共享初始种群
  → Workflow.search_arm(seed, arm) → 四组最终种群
  → Workflow.search_all → Search_complete.json（全部声明终态）
  → Workflow.select → validation选择 U* 和固定h参照
  → Workflow.freeze → Experiment_frozen.json
  → Workflow.test → 独立test → report
```

代码依据：[Workflow](../code/fjsp_usage/research_real/workflow.py)、[当前提示](../code/fjsp_usage/research_real/prompts.py)、[代际搜索](../code/fjsp_usage/research/evolution.py)、[资产门禁](../code/fjsp_usage/research_real/assets.py)。资产名称以各方法的实际写入为准，文件名大小写遵循代码。

## Tier 1：当前 EoH-S 机制适配

I1独立初始化 h。每代前一半尝试为 E1/CS，后一半为 M1/LS。一条响应形成一个候选，解析、受限AST检查、去重后，每条有效 h 必须完整求解全部 train，保存按固定实例顺序排列的分数向量。

CS先取训练均值排名前至多5个候选，计算完整分数向量的曼哈顿距离，把候选对按距离降序排序，再以对排名的 `1/(r+1)`权重抽取一对父代；E1让模型产生新规则。LS选择一个排名加权父代，使用M1。代末 CPM 从父代和有效子代中贪心选择 K 个成员，依据逐实例最佳分数的集合包络，而不是仅取均值前 K。具体公式和同分顺序见[sets.py](../code/fjsp_usage/research/sets.py)。

这些是最小互补父代/集合生存适配，不是上游 EoHS 线程运行器的完整复现。本仓库单规则路径则是 `EoH.run → I1 → E1/E2/M1/M2`，以单候选均值更新种群，最后选择一条规则；两者不能合写成一种 Tier 1。

初始化成员不足 K、失败或重复不自动补成较小集合。H 初始化、每代尝试与请求预算必须显式登记。当前正式 K 未最终确认；示例配置的 K=10不等于研究决定，接入验收的2条 h也不等于正式H。

## H资产与人工审查

`H_candidates.json`包含候选代码、说明、code key、完整训练结果与请求凭证。`review-h`生成 `H_review_packet.md`、机器可读包和空白审查模板；自动样例只提供辅助证据，不替代人工审查。

真实冻结要求恰好 K 个成员、每条完整 train 成功、凭证与请求/账本/上下文一致、审查覆盖全部 code key。人工字段必须为 `description / reviewer / method / note`，随后重新执行行为/确定性样例。当前freeze_h先按训练均值及稳定ID排序，再分配编号0至K−1，因此编号与本批训练均值相关。接口要求将编号作为类别使用，不能据此推断逐状态或泛化质量；是否在正式协议中打乱编号仍需明确登记，当前不改变实现。`H_frozen.json`绑定来源哈希、上下文、成员、训练文件与审查结果，加载时重复核验。Tier 2 使用这些冻结成员，不在搜索过程中更新H。

Leaf接入的[原始审查包](../runs/leaf-handoff-acceptance-20261008-v1/H_review_packet.md)和[模板](../runs/leaf-handoff-acceptance-20261008-v1/H_review_template.json)只属于接入验收；草稿/自动样例不得标为真人批准，也不得直接复制为正式H。

## Tier 2：四组外层演化

每个声明seed生成同一个大小N的初始U种群，四组共享。初始化知道状态契约、成员数和合法编号，不提供H代码/行为或父代。v4额外提供已接受U代码的去重归档，没有训练分数、排名或局部胜者；归档不是演化父代。常量U仍合法。初始化请求上限显式配置；原AST代码键去重之外，共享INIT保守合并纯整数return与int(整数)写法，不进行普遍语义等价判断，也不按同分去重。达到上限后有效去重候选不足N则停止，不自动补员。H和四组搜索阶段的提示正文及去重策略沿用原实现。

| 组 | 搜索阶段给模型的H信息 | 算子安排 |
|---|---|---|
| B0 | 不提供成员代码/行为；知道合法编号与状态接口 | E1/E2/M1/M2/M3，各占每代尝试数1/5 |
| B1 | 提供实际H代码、已审查行为和h动作接口 | 同B0五算子 |
| B2 | 同B1 | 通用CROSS/MUTATE，各占1/2 |
| P | 同B1 | 特化CROSS/MUTATE，各占1/2 |

B2/P的任务、H信息、父代内容与输出约束一致，仅算子段不同。P交叉要求结合至少两个父代的状态—成员决策思路并解释继承；P变异围绕一个主要修改假设，可以重写全函数。它不要求固定模块拼接、局部改一行或强制切换成员。训练分数、失败诊断、逐状态胜者和奖励不进入提示。

非互补父代按原代排名权重 `1/(N+r)`无放回抽取；交叉使用配置数量，变异一个父代。一代内父代池固定，所有尝试结束后才合并父代/有效子代并保留均值前N，同分按稳定ID。交叉和变异独立取父代，不串联。每条候选一次模型调用；失败/重复照常消耗尝试，不增加补生成或修复请求。每代尝试数为10的倍数，保证上述组内比例。

候选需精确七参数接口、受限数值AST、内置int编号、合法范围与有限评分；每个实例在受控子进程求解两次核对确定性。当前提示限制数值字面量绝对值≤1e9，运行时中间量上限≤1e100。这是受限语言执行器；手写原型不具备同一执行限制。

## 训练、验证、冻结和测试

固定数据划分为train21、validation11、test28，顺序/哈希来自[data manifest](../data/fjsp_manifest.json)。搜索仅使用train；任一实例失败使整条候选无效、fitness为null，不对子集取均值。当前H与U统一使用未取整V5下界，不能直接与冻结单规则的旧归一化分数比较。

`search`形成覆盖全部声明seed与四组的 `Search_complete.json`，终态可为completed或显式初始化/预算失败。`select`核验该凭证，只对成功组的最终种群全部U做完整validation；按均值及稳定ID选择各组U*。搜索失败或无有效validation候选时记录失败，不生成U*。固定h参照在同一H的所有成员中通过validation选一次，共享给各组；无有效成员时记录参照缺失。`freeze`绑定H、数据、源码/配置上下文、搜索完成凭证、选择结果、分析方案、seed和时间。`test`只允许读取冻结选择，完整评价真实test；没有U*的失败组保留空结果，不另行补选。它不会创建模型客户端或继续搜索。`report`要求 `Test_complete.json`与冻结一致，报告成功/失败重复数和实际配对数；不能在只有preflight或H候选时当作通用进度报告运行。

中断恢复依赖上下文指纹、检查点和缓存，不凭目录名判断可续跑。配置、源码、数据、H或共享初始化变化会拒绝恢复；结果不确定的请求/评价保守记为失效，不自动重发。目录锁防止并行写同一run。请求槽位、确认发送、真实usage和费用估算分别记录，不能把估算当供应商账单。

## 报告与预算边界

[report.py](../code/fjsp_usage/research_real/report.py)按全部预登记重复报告组均值、总体标准差、失败种子、实际配对数和固定h差值，不用最好seed代替全部重复。单次排程含可行性检查；确定性复核、进程启动/整批评价及模型请求分别计时。不能把合成计时当部署性能。

[diagnostics.py](../code/fjsp_usage/research_real/diagnostics.py)保留H完整train矩阵、最佳固定成员、整实例包络收益和成员移除损失；包络不是状态标签或U性能上界，零贡献保留。训练曲线横轴包括失败/重复槽位，共享初始化成本另记；成员使用/切换来自已完成排程，不额外调用U/h，不进入提示或选择规则。

请求预算通式为：H初始化上限＋H代数×H每代尝试＋R×（共享U初始化上限＋4×U代数×U每代尝试）。同时明确阶段和全局上限，失败/重复不增加补生成。相同请求数不等于相同token/计算成本；token与金额受供应商上界/价格可信度限制，不能将估算当账单硬限额。

H_frozen绑定生成上下文、真实请求凭证、数据和审查。常规正式H生成仍不接受跨协议复制；另有下述显式固定既有H条件研究通道，需要来源/预算绑定、完整train重评和新的研究范围批准。接入验收的import-h-samples只复用两条响应，不支持升级为正式资产。

框架开发另有显式`purpose=framework_development`的初始化候选复用通道：固定来源四份哈希，核验原响应/账本和未变的算法、提示、数据契约，再重核完整train；仅允许接入预算代码/网络期限变化，保留原来源而不冒称新发送。该通道不批准h行为、不升级正式H，不作为正式研究流程或参数决定。

## 正式完成条件

代码存在、本地合成通过、真实API接入和正式实验完成是不同等级；证据状态只在[README](../README.md)维护。正式执行须先登记模型/响应型号及供应渠道、提示、K/N/父代数/代数/尝试、R和seed、执行/审查/网络期限、预算及分析；实际生成并真人冻结H，在同一H上完成真实共享初始化/四组配对小验收，再执行登记重复、validation选择、冻结和独立test，报告失败与负结果。

不同入口的提示/deadline/响应型号差异尚需研究者确认，见[指南](../experiments/tier2/research_real_v1/README.md)。本文不把任何旧参考规模、供应商报价、温度或模型默认升级为正式配置。

## 固定既有H的条件研究路径（2026-10-11）

[prepare_paired_research.py](../experiments/tier2/research_real_v1/prepare_paired_research.py)创建新协议/目录；条件问题是“给定这10条开发来源H，比较四组U搜索”，不评价正式EoH-S H生成的效果。原H编号、代码、DDXQL行为审查和真实请求出处保持原样；所有成员在当前协议下重新完整21train评价，结果写Conditional_H_reassessment，而不是改旧fitness。新增研究范围批准须明确绑定原H哈希及10个代码键，缺少批准不能生成研究H_frozen。不能只改purpose绕过门禁；旧U仅做原代码训练轨迹审计，不作为新种群的旧适应度。

当前首批具体提案为seed201、N5、交叉5父代/变异1父代，共享新初始化最多20次、四组各1代10槽位，共最多60次新请求。初始化不足N如实终止，各组失败/重复照常占槽位；不降N、补员或手写子代。总计历史79槽位加本批最多60为139，不重置累计300/账户30%上限。仅保存余额可核对，发送前必须刷新；保留原未知账户预留及全部未知token预留，新未知请求仍先停止。该旧提案后获批准但gpt-5.6-sol首请求503中止；2026-10-14新gpt-6.1-sol迁移批次及原H研究范围已由DDXQL明确批准，状态与新61槽位（诊断1+生成60）见根README。扩展种子/代数需登记后续协议与增量预算，不能自动扩展。

固定成员参照报告全部10条train结果，validation对全部10条评价后按均分/稳定成员编号选一条最终参照；test不挑选成员。所有U最终种群均进入validation，而非只看训练最好者。历史单规则已使用validation11，应披露为项目已暴露的验证数据；没有发现本仓库真实test28求解记录不代表可认证所有外部操作。准备阶段可核对holdout字节哈希，禁止解析/求解；实现测试用独立toy数据。

训练报告入口不打开holdout、不创建模型客户端，保留全部初始化/演化尝试、有效及无效评价、幸存及未幸存子代和分阶段成本。一个seed只能称初步配对实验。正式validation/test仍沿用Search_complete→Selection_complete→Experiment_frozen的绑定与门禁，不依据test改提示、阈值、H/U、预算或选择。
