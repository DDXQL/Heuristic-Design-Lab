# FJSP Heuristic Research

职责：项目身份、当前证据等级和主文档导航。范围：本仓库当前H/U研究流程；单规则基线、上游早期集合及接入试跑分别标识。证据核对日期：2026-10-11；此页为项目进度的唯一维护位置；本地测试、真实接入验收与正式实验分别登记。

研究目标是静态FJSP：Tier 1参考EoH-S生成互补启发式集合H，完整训练评价、人工行为审查后冻结；Tier 2固定H，生成并演化选择程序U。每个排程步骤，本地U选成员编号，所选h评分所有合法工序—机器动作，调度器执行最高分动作。求解期间不调用LLM，不更新H或U。

## 六份主文档

| 文件 | 职责与适用范围 |
|---|---|
| 本README | 当前进度、实现身份、证据出处 |
| [当前研究方案](docs/PRD_TIER2_REAL_EXPERIMENTS_v1.md) | 当前H构建/四组U搜索/选择冻结测试及完成条件；不批准草案配置 |
| [接口与评价契约](docs/fjsp_tier1_contract.md) | 当前h/U、动作、状态、评价；必要的冻结基线与原型差异 |
| [当前运行指南](experiments/tier2/research_real_v1/README.md) | 当前CLI、测试、合成/真实接入验收和配置差异；前置资产须真实满足 |
| [来源与数据说明](provenance/SOURCE.md) | 冻结出处、迁移映射、数据恢复、许可边界与字节差异 |
| [第三方声明](THIRD_PARTY_NOTICES.md) | 原始导出框架与LLM4AD出处/许可声明；原文及许可证材料保留，不作为算法进度说明 |

## Tier 1身份必须分开

| 身份 | 实际入口/方法 | 证据与边界 |
|---|---|---|
| 本仓库单规则EoH基线 | [run_eoh_single.py](experiments/tier1/run_eoh_single.py) → EoH.run：I1、E1/E2/M1/M2；训练均值生存；[evaluate_single_rule.py](experiments/tier1/evaluate_single_rule.py)从最终种群按validation选一条 | [三seed记录](baselines/tier1_single_rule_v1/stability_summary.json)；历史标识Tier1-Fixed-H-v1实际canonical为[seed2026092002单条规则](baselines/tier1_single_rule_v1/rules/selected_rule_seed_2026092002.py)，2003/2004仅复核，不组成H；未评价test |
| 相邻EoH-S早期集合 | [run_formal.py](../EoH-S/examples/training/fjsp_set/run_formal.py) → [run_eohs.py](../EoH-S/examples/training/fjsp_set/run_eohs.py) → EoHS.run：CS/LS/CPM | 曾有24候选、4成员的[原始集合](../EoH-S/logs/fjsp_tier1_formal/run03/final_set/final_set.json)；本机相邻仓库资产，不是当前H_frozen，不能直接替代新协议H |
| 当前正式H构建路径 | [research_real_v1/run.py](experiments/tier2/research_real_v1/run.py)：generate-h/review-h/freeze-h → Workflow → V5BudgetedSearch → Search(arm=H) | 最小互补父代/集合生存适配已实现，不是完整上游线程运行器；正式H尚需按已确认协议真实生成、审查并冻结 |

offline_v1是状态对象演示；offline_v2是七标量/手写H/U训练演示，其状态计算仍被复用；research_v1是旧提示mock演化，其搜索引擎被当前V5层复用。实际代码差异见契约，入口见指南；这些不是另几套现行研究方案。

## 当前证据等级

| 等级 | 证据 | 可以确认与不能推出的结论 |
|---|---|---|
| 代码已实现 | [Workflow](code/fjsp_usage/research_real/workflow.py) | H生成/审查/冻结、共享初始化、四组、validation选择、冻结、test/报告/恢复已实现；不表示真实阶段完成 |
| 本地合成测试通过 | [S1–S6 JSON](docs/S1_S6_ACCEPTANCE_EVIDENCE.json)、[V5离线JSON](docs/V5_OFFLINE_ACCEPTANCE_20261008.json)、[历史110项测试记录](runs/leaf-handoff-acceptance-20261008-v1/continuation_summary.json)、[2026-10-09接入相关43项测试](runs/leaf-handoff-acceptance-20261008-v1/u_acceptance_summary_20261009.json)、[此前110项及命令行合成全流程](runs/formal-readiness-preparation-20261009-v1/readiness_summary.json) | [v3付费前126项本地检查](runs/leaf-framework-30pct-20261010-v3/local_checks_20261010.json)通过；此前[v4初步修复133项检查](docs/U_INITIALIZATION_REPAIR_20261010.json)及此前[139项续接检查](runs/leaf-U-continuation-v4-offline-20261010-v2/Local_checks_20261010.json)通过，含流式、来源链和用量预留回归；软件门禁、合成完整流程有运行证据；接入付费前43项通过，后续全套110项通过，版本标识修正后命令行合成两seed/四组/选择冻结测试报告完成；合成流程不使用真实holdout，不能替代真实研究结果 |
| 真实API接入验收/探索 | [DeepSeek报告](runs/deepseek-pilot-20261008-v1/report.json)、[Leaf三次汇总](runs/leaf-integration-acceptance-20261008-v4/acceptance_summary.json)、[Leaf续接](runs/leaf-handoff-acceptance-20261008-v1/continuation_summary.json)、[2026-10-09单次U验收](runs/leaf-handoff-acceptance-20261008-v1/u_acceptance_summary_20261009.json) | DeepSeek20次请求、有有效U，但用手写EFT/SPT和tiny+3train；Leaf历史3次h请求，两条合法h各完成21train后由用户确认行为审查。本次新增1次U、0次h、无补发；v3提示、15秒逐实例期限、实际响应gpt-5.6-sol，U完成21/21 train与确定性复核，fitness=-2.3637159834583583；不能替代正式H/U研究 |
| 正式实验完成 | 当前协议尚无此级别证据 | 尚无当前正式H冻结、真实四组配对重复、Tier2真实validation/test和正式结论；早期集合/单规则按各自协议报告 |

2026-10-09用户另行批准了150次上限四组小试并接受费用未知。该批[H阶段记录](runs/leaf-paired-pilot-20261009-v1/H_stage_stop_summary_20261009.json)：3次新请求中2次接口失败、1条h完成21train；第三次供应商输出用量4895超过配置/预留4096，账本自动停止，余147槽位。新增本地回归已复现输出超限并确认恢复后仍阻止下一次发送。尚未形成K=10的H，也未初始化U或执行四组/真实validation/test；不得将单条有效候选升级为集合或清除停账本标记。

单规则validation参与了规则选择；其稳定性记录不能作为未见test的泛化证据。Leaf候选原3秒失败与后来15秒成功分别保留，耗时诊断不能改写原失败结果。原始[审查包](runs/leaf-handoff-acceptance-20261008-v1/H_review_packet.md)和[空模板](runs/leaf-handoff-acceptance-20261008-v1/H_review_template.json)保留原样；2026-10-09用户明确确认记录在[人工确认](runs/leaf-handoff-acceptance-20261008-v1/human_review_confirmation_20261009.json)，已生成[接入用H](runs/leaf-handoff-acceptance-20261008-v1/Smoke_H_reviewed.json)。批准范围仅为此次接入验收，不表示正式EoH-S集合已生成或批准。

## 下一步与维护

两套禁用请求草案已通过此前源码预检，见[准备核对](runs/formal-readiness-preparation-20261009-v1/readiness_summary.json)。用户随后明确批准使用平台总额度的30%进行框架开发；新[开发授权](runs/leaf-framework-30pct-20261009-v1/human_budget_authorization_20261009.json)及[隔离配置](runs/leaf-framework-30pct-20261009-v1/config.framework.authorized.json)登记累计扣额上限30,000,000原始点（包含此前98,685点）、每请求12,000,000点保守余量检查、最多300预定尝试，H/U均10成员、各2代、seed101。请求输出8192与输出用量预留32768分开，提示v3、逐实例15秒，温度/推理参数不发送；每次请求前后查询实际额度，未知结算/中断会停止。局部守卫不是供应商强制金融上限，人民币换算仍未核实。旧停账本和请求不改写、不重放；新H必须重新由用户审查，不能沿用接入两成员的批准。当前开发进度以新运行目录的progress/budget/platform_quota为准。

完整12210次研究草案仍未批准。当前没有正式真实H；完整研究仍须登记模型/响应型号、提示版本、K/N/R、演化规模、各类期限、阶段/总预算和分析方案；随后正式H生成/真人审查冻结、真实共享初始化/四组小验收、登记重复搜索、validation选择、冻结及独立test。代码默认、旧草案和开发批次授权不能替研究决定；具体差异集中在[运行指南](experiments/tier2/research_real_v1/README.md)。

只维护上表六份文档；进度只更新本页，接口/流程/命令/出处更新各自文档。原始runs、JSON、代码、配置、数据和许可材料保留，都是证据或实现，不是新方案。runs及相邻EoH-S链接依赖本机，未必随Git检出存在。旧过程Markdown已移出工作仓库，仓库外恢复清单不作为项目导航。

只搜索现行说明可在项目根目录运行：

```bash
rg -n -g '*.md' -g '!runs/**' 'Tier 1|正式H|V5|deadline' .
```

全仓库搜索可能命中受保护的原始runs/旧JSON，它们按记录日期和mode解释，不替代此页当前等级。

2026-10-10当前开发验收：[v3隔离配置](runs/leaf-framework-30pct-20261010-v3/config.framework.authorized.json)和[H阶段汇总](runs/leaf-framework-30pct-20261010-v3/H_development_summary_20261010.json)。8条已有真实h经完整21train重评一致后复用；新22次流式请求中20条候选完整通过21train，1条格式拒绝、1条最后实例超时而整批无效。两代互补集合搜索完成并保留10条h。随后用户批准最终说明，审查人DDXQL；[逐代码键审查记录](runs/leaf-framework-30pct-20261010-v3/H_review_completed_20261010.json)、[用户确认](runs/leaf-framework-30pct-20261010-v3/human_review_confirmation_20261010.json)及[开发H冻结资产](runs/leaf-framework-30pct-20261010-v3/H_frozen.json)已存在。H阶段汇总和原空模板是此前记录，不代表当前审批状态。

共享U初始化因高重复率由用户明确暂停，见[停止汇总](runs/leaf-framework-30pct-20261010-v3/U_pause_summary_20261010.json)及[阶段状态](runs/leaf-framework-30pct-20261010-v3/progress.json)。已发35次U请求，34次形成尝试结论：6条有效代码均完整通过21train，27条重复、1条解析失败；第35次已发送后中断，响应/用量/扣额仍未知，账本保持reserved和预留，不能重发或计为免费。旧汇总的pending_budget_keys空列表只筛选了字面pending状态，不能解释为已结清。共享池未满10，四组未开始，正式validation/test读取为0。

用户暂停后仅修复本地初始化，当时源码提示版本为v4，见[此前133项修复核对](docs/U_INITIALIZATION_REPAIR_20261010.json)。新提示向共享初始化提供已接受U代码的去重上下文，不提供H行为、训练分数或父代；保留常量选择器合法性。原校验器已去除排版/注释差异，新规则仅额外合并纯整数return与int(整数)的确定等价写法；不按训练分数去重。旧6条有效代码去除已确认等价项后剩5条续接候选，其余未证明普遍语义互异；原记录不追改。后续离线绑定完成后139项本地测试通过；v4尚无真实模型多样性改善证据。

初始化暂停时可核实账户累计用量1,284,585/100,000,000原始点（1.284585%），第35次在途扣额未核实，30%累计边界不变；不换算为人民币。原先非流式HTTP524的失败供应商日志记0扣额，但原响应token仍未知。流式实测输出9967曾超过请求提示8192、未超过预先登记32768用量预留，供应商上限语义仍待确认。旧v3仍绑定网络10/240/300秒、逐实例15秒、精确响应model及288槽位（加前两批12槽位共300），不能用新源码直接resume。

当前[单组Tier 2开发验收报告](runs/leaf-tier2-single-P-acceptance-20261010-v4/Development_report.json)已实际完成，见[最终核对](runs/leaf-tier2-single-P-acceptance-20261010-v4/Final_development_audit_20261010.json)。复用原10条H（代码、编号、DDXQL审查不改）和5条完整21train有效U；N=5、交叉父代5、变异父代1、1代10槽位。实际新增10次请求：前5交叉、后5变异，7条有效、0重复、3次接口失败；全部有效子代完成21train及确定性复核。本代统一生存选择保留5成员，其中4条新子代、1条原U。没有新H或初始化请求，没有补员、重试或追加代数；四组比较未执行。

开发选择用已见的Behnke1–3评价最终5条U，选中P/g0000/000004并[单独冻结](runs/leaf-tier2-single-P-acceptance-20261010-v4/Development_frozen.json)。[开发测试](runs/leaf-tier2-single-P-acceptance-20261010-v4/Development_test_complete.json)在已见训练实例Behnke4/13/14完成3/3合法排程及确定性复核，Cmax为126/305/293；测试不调用LLM、不修改U*。正式validation/test文件未读取，训练/开发分数不支持独立泛化或正式比较结论；v4初始化多样性仍未经真实检验。

[开发配置](runs/leaf-tier2-single-P-acceptance-20261010-v4/config.development.authorized.json)显式绑定缩小参数及逐段来源，原v3全部27文件未改。v1–v4目录是同一P组同一代的续接，不是四组或四轮新实验；3次失败通过供应商扣额凭证登记续接，不改写旧响应/用量/记录。000034不重发，usage仍null，65536输入/32768输出token及12,000,000点预留保持原样；其他失败的未知wire usage也不填零。通用预算保护仍生效，只有显式开发P组可带原未知预留逐次发送；新未知结算先停止，取得匹配凭证后在新目录绑定续接。累计本开发授权池79已用/预留槽位、78次确认发送，上限300；账户最新累计1,557,783/100,000,000原始点（1.557783%），30,000,000边界不变，不换算人民币。[148项本地检查](runs/leaf-tier2-single-P-acceptance-20261010-v4/Local_checks_20261010.json)通过；旧离线目录仅保留此前核对证据，不作为当前源码执行入口。

## 2026-10-11当前研究准备

[最终离线核对](runs/conditional-paired-research-20261011-v4/Final_offline_audit.json)及[准备结论](runs/conditional-paired-research-20261011-v4/Research_readiness.json)：168项本地测试通过；10条旧H、13条真实来源旧U在新协议下全部重新完成21train，逐实例makespan均复现。13条U的独立观察排程全部完成，轨迹重建通过可行性核验；816份原始运行文件哈希不变。旧U只作审计，不导入新初始种群，旧代码/fitness不改；本次新增模型请求0，真实四组研究尚未执行。

提示升级为v5-state-bounds，只修改U任务段的状态边界说明，保留v4初始化去重机制及四组算子正文。工作/机器标准差均不超过0.5，std/(mean+1)均不超过sqrt(2)/4。旧开发U*存在7个尺度相关永假判断，另有7个合法有限输入下永假的NaN保护；训练未触发但未证明不可达的条件另记。两条常量初始化U具有相同完整训练行为，这不证明其他有限样例行为相同的程序普遍等价。当前仍无v4/v5真实初始化多样性改善证据。

候选诊断不拒绝常量、不强迫切换或使用全部H、不进入提示和生存选择。原两次求解仍共享15秒实例期限，观察排程另用15秒期限，失败不能改变原fitness/有效性；单次求解、确定性复检、诊断及供应商生成分别计时。一次中间离线准备曾因观察排程挤占原期限使常量U超时，记录保留在v3准备目录；最终隔离后13/13通过，不覆盖该中间失败。

[待批准配置](runs/conditional-paired-research-20261011-v4/config.research.pending.json)提出固定既有H条件实验：seed201、N5，新共享初始化最多20次，B0/B1/B2/P各1代10槽位，最多60次新增请求；历史79加本批最多60为139/300。原H的开发行为审查不等于研究范围批准，新批准必须绑定原H哈希及按编号的10个代码键；配置当前real_requests_authorized=false、scope_approval=null，未冻结研究H。所有未知token、INIT/000034账户12,000,000点预留继续保留；最新保存用量1,557,783点，发送前必须刷新，不能据此保证60次均有余额或换算人民币。

[数据使用核对](runs/conditional-paired-research-20261011-v4/Dataset_usage_audit.json)确认train21/validation11/test28名单、顺序和实际字节哈希一致；validation11已由历史单规则和相邻EoH-S真实评价使用，应披露为项目已暴露数据。扫描未发现正式test28数值结果，不能认证未知外部使用。本次holdout只哈希字节、未解析求解。首批仅做训练配对小试；规模与分析协议固定后再用validation选择U*/固定h参照，冻结后执行test，不能提前用test调试。


## U使用方式扩展：当前状态（2026-10-13完成，版本按2026-10-12启动日命名）

旧单编号入口保留；新 [usage_v2入口](experiments/tier2/usage_v2/run.py) 实现 `use_heuristics(七输入) -> (mode, vector)`。A仅SELECT，B允许SELECT/MIX；混合最多两个正权重，单成员用原始h分数、双成员在当前全部合法动作上逐成员min–max后加权，历史记录最大实际权重成员。语法只新增终端返回元组，未开放任意Python。接口和落实依据见[扩展契约](docs/U_USAGE_CONTRACT_V2_DRAFT.md)，命令见[指南](experiments/tier2/research_real_v1/README.md)。

188项全套本地测试通过；[最终手写两组toy验收](runs/usage-v2-toy-acceptance-20261012-v3/Synthetic_acceptance.json)完成共享5个初始SELECT、A/B各一代10槽位。26次均为本地手写fixture HTTP，不是真实模型：初始5有效/1重复，A有8有效/1接口失败/1运行失败，B有9有效/1解析失败；不补发，所有有效候选完整评价独立toy训练集。h调用按求解/复检/诊断分别报告，不将相同请求数解释成相同计算成本。[可读例子与轨迹](runs/usage-v2-examples-20261012-v1/Examples_summary.json)首动作依次C/A/B；完整toy排程Cmax为11/11/12，不能作为组合有收益的证据。

[最新离线准备](runs/leaf-usage-v2-AB-preparation-20261012-v2/Preparation.json)的10条原H均完整通过21train且makespan复现；[旧U兼容审计](runs/leaf-usage-v2-AB-preparation-20261012-v2/Legacy_compatibility_audit.json)的5条原U均在21train逐动作/状态/历史及排程一致，原训练makespan也复现。它们仅审计，不导入新P0；旧代码、冻结资产、历史账本未改。提示2.1补齐输出类型与元组语法的准确说明，初始A/B提示相同，交叉/变异仅allowed_modes不同；完整[提示差异凭证](runs/leaf-usage-v2-AB-preparation-20261012-v2/prompts/Prompt_comparison.json)使用明确手写预览父代，真实发送时必须换成实际共享初始化的父代。

[待执行配置](runs/leaf-usage-v2-AB-preparation-20261012-v2/config.pending.json)：固定原H、seed301、N5、共享新初始化≤20、A/B各1代×10（5交叉/5变异），最多40新请求；沿用Leaf gpt-5.6-sol、原生成参数和共同15秒实例期限。真实新生成0、两组真实进度未开始、没有读取正式validation/test；新H研究范围及请求均未批准。原300槽位预算池79已占用，加本批最多119/300；账户累计30%边界、INIT/000034的1200万点预留及全部未知token保留。保存用量1,557,783点只能说明保存时下一份保守预留可容纳，不能保证40次均可执行或换算费用。

此前2.0版离线准备与toy目录保留为本轮过程证据，不能用2.1源码resume；当前以v2准备/v3toy凭证为准。没有当前两组真实研究效果或独立泛化结论。

## 本分支：原单成员研究任务（2026-10-13）

`codex/u-single-experiments` 从 checkpoint `243ad401bfd5ff64da338277112933323621de1f` 建立独立worktree，仅推进原单编号四组研究。新 [单成员入口](experiments/tier2/research_real_v1/run_single_experiments.py) 保持原运行/提示语义并增加只读来源与跨worktree账本检查；[具体配置与执行指南](experiments/tier2/research_real_v1/README.md#原单成员研究-worktree2026-10-13)提出 seed201/N5/共享新初始化≤20/四组各1代10槽位，最多60新请求。usage_v2的40次SELECT/MIX提案不适用于本任务。旧P组开发验收及旧候选重评仍为历史/工程证据；本次第一阶段付费与旧H研究范围已由用户明确批准；实际执行状态见下方2026-10-13记录。

本页第一阶段已于2026-10-13由用户批准：原H研究用途确认人DDXQL、本页独占单成员真实调用、最多60新请求、仅训练；旧40次MIX批次挂起。新增账单核对不改变实验语义，原12,000,000点未知预留保留。实际进度与全量结果写本worktree新授权目录，未完成阶段不标成功。

本任务当前真实结果：[阶段汇总](runs/single-ID-paired-training-20261013-authorized-v1/Stage_summary.md)、[全量结果](runs/single-ID-paired-training-20261013-authorized-v1/Single_results.json)。10条H研究范围确认/冻结及新协议10×21train重评已完成，makespan全部复现；新增1次INIT请求返回HTTP503，wire token/实际费用未知，供应商账单无匹配记录，额度前后均1557783点。0有效U/0重复，四组未开始；没有重发、MIX或validation/test。累计80/300占用槽位、79次确认发送；原1200万点和本次1200万点预留保留，下一次保守预留总额37557783>30000000而停止。该数是预留计算，不是已花费。授权剩59槽位，需可核实本次结算后继承计数恢复，不重新申请或重置批次。
