# 当前运行与验收指南

职责：当前入口、环境/测试、合成与小接入验收、分阶段操作和配置差异。范围：research_real_v1；旧单规则/原型入口只说明必要边界，不沿用历史费率或批次授权。核对日期：2026-10-09。[根README](../../../README.md)说明实现身份与证据，[研究流程](../../../docs/PRD_TIER2_REAL_EXPERIMENTS_v1.md)说明研究约束，[契约](../../../docs/fjsp_tier1_contract.md)定义h/U和评价。

以下命令均从项目根目录运行，选择新的 `runs/` 子目录。文档整理只校验入口参数与路径，没有执行这些实验、测试、准备阶段或API请求。

## 环境与测试

使用Python 3.12及项目虚拟环境。新检出可先建立环境；已有 `.venv` 时沿用：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=code .venv/bin/python -m unittest discover -s tests -v
```

本机数据不随Git分发，按[来源与数据说明](../../../provenance/SOURCE.md)恢复train后再执行真实数据命令。测试覆盖模块见下表；现有“110项通过”是历史记录，不承诺当前测试数固定。

| 范围 | 主要测试 |
|---|---|
| h/U动作、状态、批量评价 | `test_fjsp_usage.py`、`test_fjsp_usage_v2.py` |
| 解析/受限执行、代际父代/互补生存、提示 | `test_research_execution.py`、`test_research_evolution.py`、`test_v5_offline_preparation.py` |
| 工作流、预算、资产和holdout门禁 | `test_research_real_workflow.py` |
| 单次发送、超时、模型身份 | `test_openai_chat_transport.py`、`test_deepseek_pilot.py` |
| 小接入、人工审查、已有h复用 | `test_integration_smoke.py`、`test_h_review_execution.py`、`test_smoke_reuse.py` |
| Leaf配置与凭证处理 | `test_leafapi_setup.py` |

查看各入口 `--help` 不执行阶段；使用 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B SCRIPT --help`可避免生成字节码。

## 无模型的本地合成验收

```bash
.venv/bin/python experiments/tier2/research_real_v1/run.py all-synthetic \
  --run-dir runs/synthetic-doc-example
```

使用本地HTTP手写响应、独立合成数据和H，走H生成/合成审查/冻结、共享初始化、四组搜索、validation、冻结、test和报告；不使用模型或benchmark holdout。报告与账本在指定run内。合成自动审查只支持特定样例，不能用于真实H。

## 正式流程的离线准备

```bash
.venv/bin/python experiments/tier2/research_real_v1/prepare_offline.py \
  --run-dir runs/offline-preparation-doc-example \
  --provider-config experiments/tier2/research_real_v1/config.api-pilot.draft.json
.venv/bin/python experiments/tier2/research_real_v1/run.py preflight \
  --run-dir runs/preflight-doc-example \
  --config experiments/tier2/research_real_v1/config.real.example.json \
  --manifest data/fjsp_manifest.json
```

准备命令在 `artifacts/` 导出协议、提示及禁用请求的配置草案，不调用API。不加 `--calibrate-train`时不求解实例；该可选参数会实际运行train校准，因此单独决定是否执行。preflight只校验配置与数据清单，不打开实例，不创建模型客户端；成功不表示供应商连接、候选执行或预算已获准。

`config.real.example.json`有占位endpoint/model，不能直接调用模型。`config.api-pilot.draft.json`虽然是Leaf端点，仍禁用真实请求，deadline为3秒且未绑定expected_response_model。离线准备只继承其provider，不自动继承15秒deadline。当前正式规模/价格仍待确定，草案不是已批准运行配置。

## 小规模真实API接入验收

独立入口 `run_api_acceptance.py`仅允许train，最多20请求槽位的安全上限；正常计划为两条h各一次请求、审查后一个U一次请求，失败不自动补发。此流程不演化正式集合，也不做四组/validation/test。

先准备禁用请求的草案：

```bash
.venv/bin/python experiments/tier2/research_real_v1/run_api_acceptance.py prepare \
  --run-dir runs/api-acceptance-doc-example
.venv/bin/python experiments/tier2/research_real_v1/run_api_acceptance.py preflight \
  --run-dir runs/api-acceptance-doc-example --resume \
  --config runs/api-acceptance-doc-example/config.smoke.draft.json
```

第二条命令会记录阻止发送的状态，这是草案的预期结果。默认 `SmokeConfig.instance_timeout=3.0`，不是续接的15秒。正式发送前，由操作者形成独立且已确认的 `config.smoke.approved.json`：声明请求授权、阶段/总请求上限、deadline、精确响应型号、价格来源及CNY估算限额。价格未核实时，代码只允许显式声明至多3次的unpriced验收，且不启用金额估算门禁；不能将未知价格写成零。

以下为该配置已存在后的分阶段示例；配置或源码变化须另开新run，不能把已建立的旧上下文换配置继续：

```bash
.venv/bin/python experiments/tier2/research_real_v1/run_api_acceptance.py generate-h \
  --run-dir runs/api-approved-example --config runs/config.smoke.approved.json --prompt-key
```

进程在两条h完整train评价后停止，输出审查包和空白模板。人工逐code key填写真实行为说明、reviewer、method、note，再执行：

```bash
.venv/bin/python experiments/tier2/research_real_v1/run_api_acceptance.py review-h \
  --run-dir runs/api-approved-example --resume --config runs/config.smoke.approved.json \
  --reviews runs/api-approved-example/H_review_completed.json
.venv/bin/python experiments/tier2/research_real_v1/run_api_acceptance.py generate-u \
  --run-dir runs/api-approved-example --resume --config runs/config.smoke.approved.json --prompt-key
```

`H_review_completed.json`是人工输入文件名示例，入口不会自动创建批准。`--prompt-key`要求交互终端隐藏输入；也可使用既有进程环境 `LEAFAPI_API_KEY`，或由操作者显式指定 `--env-file`。凭证不写入文档/配置/命令行字面值。`status`会发起账户元数据网络查询，不是纯离线检查。

已有h复用必须新目录、显式两个来源：`import-h-samples --source-h RUN_DIR REQUEST_ID --source-h RUN_DIR REQUEST_ID`，每条在当前deadline重新评价全部21train，核验原响应/凭证并重新生成审查包；不自动复用旧评价、旧批准或重复发送模型请求。该机制只属于小接入验收。`generate-h-sample`一次生成一个h样例，用于单次接入，不代表正式集合生成。

## 当前正式研究阶段

正式入口 `run.py`支持下表，或用 `run_leafapi.py`转发。为每阶段提供相同的已确认 `--config`、`--manifest data/fjsp_manifest.json`、`--run-dir`；非空目录追加 `--resume`。当前没有“一键all-real”。

| stage | 前置/额外参数 | 作用与API |
|---|---|---|
| `preflight` | 新目录/显式配置 | 清单与配置校验，无模型客户端 |
| `generate-h` | train可用/发送授权 | I1、CS/LS、CPM生成候选H，调用模型 |
| `review-h` | H_candidates | 重建行为审查包，无模型 |
| `freeze-h` | `--reviews`真实人工文件 | 验证恰好K成员并冻结，无模型 |
| `initialize-u` | H_frozen、`--seed`声明seed | 共享初始U种群，调用模型 |
| `search-arm` | `--seed`、`--arm B0/B1/B2/P` | 只搜索指定组，调用模型 |
| `search` | H_frozen | 初始化/搜索所有声明seed与四组，调用模型 |
| `prepare-continuation` | 显式开发来源声明、完整哈希及真人审批凭证 | 离线绑定既有冻结H/部分U与旧预算；不创建模型客户端、不打开实例 |
| `select` | Search_complete覆盖全部声明终态 | 全最终种群validation，选择U*及固定h，无模型 |
| `freeze` | 合法选择与凭证 | 绑定实验资产，无模型 |
| `test` | Experiment_frozen | 独立test，无模型 |
| `report` | Test_complete与实验冻结一致 | 汇总最终结果及失败重复，无模型 |

参数形式示例：以下配置由操作者另行准备，仓库没有替其批准。

```bash
.venv/bin/python experiments/tier2/research_real_v1/run.py search-arm \
  --config runs/config.formal.approved.json --manifest data/fjsp_manifest.json \
  --run-dir runs/formal-example --resume --seed 101 --arm P
```

逐组使用 `search-arm`后仍须运行 `search`汇总为 `Search_complete.json`，才能 `select`；已有完成组不会重复生成，缺失组会继续搜索并可能调用API。显式失败组也进入终态凭证，选择和测试保留失败，不补选。seed必须属于配置声明。不同配置/源代码/数据/H不可续跑同一目录。账本保守占用不确定请求槽位，失败/重复计入预算，没有自动网络重试或补生成。请求/token/金额估算门禁与供应商实际账单分别报告。

## 单规则基线与历史入口

`experiments/tier1/preflight.py`、同目录的 `run_eoh_single.py`、`evaluate_single_rule.py`、`prepare_single_rule.py`以及根目录 `verify_portable_baseline.py`属于单规则基线；真实生成仅在独立授权/配置下运行。当前冻结规则字节哈希不匹配，完整portable核验会被门禁阻止，不以单元测试替代。出处见[provenance](../../../provenance/SOURCE.md)。

`offline_v1/run_demo.py`为手写状态对象演示；`offline_v2/run_training_demo.py`会实际求解train；`research_v1/run_offline.py`用mock响应演化，train模式会评价train。这些入口不替代当前正式H/U流程。

DeepSeek旧小试入口 `run_deepseek_pilot.py check`会自动读取既有本机密钥文件，属于凭证检查，不能视为纯文件元数据检查；`run`会调用模型。Leaf `run_leafapi.py check`不联网，只有显式凭证参数才读本机文件；`status`联网查询元数据。旧试跑来源见[原始报告](../../../runs/deepseek-pilot-20261008-v1/report.json)，不照搬旧resume命令。

## 真实接口与计费核对

原生Chat适配支持openai-chat-v1与deepseek-chat-v1，另有json-candidate-v1网关；协议/endpoint、供应商模型别名、响应model、参数和usage随运行记录。返回model匹配只核验标识，不能证明底层官方快照固定。正式四组应统一供应商/渠道、完整型号、temperature（null为不发送）、reasoning_effort、输出限制和并发，不能隐式切模型或fallback。

openai-chat-v1发送单user消息、stream=false、n=1、max_completion_tokens；缓存/推理明细已是输入/输出总量的子集，不再重复相加。小接入SmokeJournal遇到请求失败或缺usage会停止后续发送。正式Workflow使用BudgetJournal：截断、型号不符或接口故障使该尝试失败，随后可按原计划进入不同候选的下一槽位；缺usage时保留token预留，不自动终止整批。硬请求/阶段预算及预留预算不足会阻止新发送，观察到用量超出预留会停账本。两种入口都不重发已有请求、不修复候选或追加补员；正式批次是否需更严格的全局失败停止规则，须预先决定。实际响应/账本才是接入证据，check或模型列表不是生成验收。

金额字段是根据已登记单价和保守token预留的估算，平台点、展示货币、实际人民币充值/账单分别保存。需确认账号分组、额度单位/换算、输入/输出/缓存/推理/分档收费及价格日期；不执行供应商价格表达式，不把未知费用填零。历史[公开快照](../../../docs/LEAFAPI_PUBLIC_BILLING_20261008.json)、[三次扣额/usage汇总](../../../runs/leaf-integration-acceptance-20261008-v4/acceptance_summary.json)和[账单元数据](../../../runs/leaf-billing-verification-20261008-v2/provider_billing_metadata.json)不构成当前人民币报价。

配置可独立声明`provider.output_token_reservation`，不低于`max_output_tokens`；省略时沿用请求输出限制作为预留。前者只用于账本，后者才发送给模型。观察到usage超过实际预留仍停止，不能通过改写旧账本消除已记录的超限。响应诊断记录finish_reason、content类型及拒绝/工具调用标志，不保存拒绝正文或密钥。

Leaf真实开发配置可同时声明`platform_quota_ceiling`与`platform_quota_reservation`。前者是账号累计total_used边界，包含其他已发生消费；后者是每次发送前需留出的工程余量。`platform_quota.json`记录查询、实际账号扣额差及请求状态；查询不可用/不一致、发送后用量未知或扣额可能延迟、请求中断、观察到超限均阻止后续发送。它不认证供应商计费上界，也不能替代平台自身支出上限。当前12,000,000点余量会在剩余开发额度不足该数时提前停止，不追求把30%花满。额度查询只读，不是模型生成请求。`platform_quota_query_interval`默认75秒，进程内近期已验证余额供发送前检查复用；发送后强制读取并按间隔节流，守卫不重复查询模型列表。恢复进程不信任磁盘余额的时效，不重发模型请求。

`purpose=framework_development`可声明`development_h_source`，明确源run及protocol/checkpoint/budget/journal四份SHA256。仅支持已完整评价的初始化h；数据、提示、模型/生成参数、算法源码及评价期限必须一致；仅允许列明的预算/接入/报告工程文件变化，以及网络期限和流式交付模式差异。generate-h会保留原账本身份与响应，重新核对全部train排程，再将成员放入开发初始化池；新请求计数不伪称这些成员是本批重新生成。原始记录不改写，模型说明仍未人工批准。`purpose=research`拒绝该声明；开发复用H不能升级为另一正式配置。报告明确标为框架开发验收。


原[开发授权配置](../../../runs/leaf-framework-30pct-20261009-v1/config.framework.authorized.json)采用v3提示、8192请求输出、32768输出预留、H/U各2代、K/N=10、seed101，总请求最多300、账号累计30,000,000点上限。旧150次批次仍保持停止状态；开发运行不重放旧请求，不自动批准新H或升级为正式研究参数。通过同一`run_leafapi.py`分阶段入口指定新配置和新目录；收到本次H的人工确认前，停在review-h，不能执行freeze-h/initialize-u。各阶段是否已完成只看[根README](../../../README.md)和新目录实际凭证。

## 仍需决定的真实配置差异

| 项目 | 实际代码/保存配置 | 需登记的决定 |
|---|---|---|
| 提示版本 | 当前experiments manifest与prompts.py一致为v5-state-bounds；此前v4只增加初始化去重归档，已冻结开发批次按各自v3/v4记录绑定 | v3目录禁止直接用v4 resume；新批次必须显式绑定旧H/U凭证与累计预算 |
| 实例执行期限 | config.real.example和未校准offline准备默认2秒；提交Leaf草案与SmokeConfig默认3秒；Leaf新pilot_config及已保存续接为15秒 | 各正式组统一、预先声明的train/validation/test期限；15秒接入成功不自动决定正式值 |
| 审查/网络期限 | review_timeout独立于instance_timeout；provider连接/读取/总期限另设 | 分别确认，不把15秒套给所有期限 |
| 模型与参数 | 提交Leaf草案expected_response_model=null；当前provider/接入代码绑定gpt-5.6-sol；离线准备未指定provider时使用另一候选 | 正式供应商/渠道、精确请求与响应标识、是否接受版本不可锁定、温度/推理/输出/并发 |
| 规模与预算 | K/N/R/H代数/尝试及phase/global/token/金额各有草案，无正式资产证据 | 完整登记H、共享初始化、配对试跑和正式重复的配置/限额/价款，不沿用历史授权 |

当前证据等级及人工审查状态只在[根README](../../../README.md)维护。Leaf续接的[审查包](../../../runs/leaf-handoff-acceptance-20261008-v1/H_review_packet.md)、[空模板](../../../runs/leaf-handoff-acceptance-20261008-v1/H_review_template.json)、[完整train/续接凭证](../../../runs/leaf-handoff-acceptance-20261008-v1/continuation_summary.json)保留；仓库外移走的人工说明草稿不是批准；本次用户确认见[人工确认](../../../runs/leaf-handoff-acceptance-20261008-v1/human_review_confirmation_20261009.json)，后续单次U完整train结果见[验收汇总](../../../runs/leaf-handoff-acceptance-20261008-v1/u_acceptance_summary_20261009.json)。原3秒失败及后来诊断不覆盖，正式H也不由接入两成员直接升级。

冻结单规则哈希不匹配仍由原门禁阻止，详见[出处](../../../provenance/SOURCE.md)。原始runs/JSON保留旧日期、参数和路径引用，不改写它们来消除当前配置差异；旧Markdown可从仓库外快照恢复。

2026-10-10已运行批次使用[开发v3配置](../../../runs/leaf-framework-30pct-20261010-v3/config.framework.authorized.json)，目前因共享初始化重复而由用户暂停。当时源码改为v4，当前另为v5-state-bounds，不能将该旧配置当成当前可执行续接命令。原development_h_source仍仅支持初始化h复用并要求提示一致；新开发专用development_continuation_source用于已冻结H/部分共享U的显式跨版本绑定，两者不可同时声明，research模式禁止使用。来源run每份文件必须完整哈希绑定；默认严格继承搜索参数。当前缩小开发方案另用search_change精确登记原/新N、代数、每代槽位及阶段上限；只允许N减少、1代10槽位、复用池恰好N条及尚未启动的四组阶段上限各10，父代数、H、数据、模型、期限、seed及总预算保持原样。只允许声明的初始化/续接工程源码差异，评分、状态、排程、候选语言等变化会拒绝迁移；H/任务/演化算子提示段哈希必须一致。

当前[单组开发配置](../../../runs/leaf-tier2-single-P-acceptance-20261010-v4/config.development.authorized.json)已执行P组1代10槽位，实际结果见[报告](../../../runs/leaf-tier2-single-P-acceptance-20261010-v4/Development_report.json)。保留冻结H和5条初始U来源及全部train结果；N=5，交叉父代5、变异父代1。development_acceptance明确限定P组最多10次；其他组及正式search/select/freeze/test入口均拒绝。INIT游标35、000034不可重发，全部未知token预留和历史槽位保留。原未知账户预留12,000,000点加入每次新余额检查；新请求未知结算仍先停止，必须有匹配的供应商最终扣额凭证，再通过search_resume_source在新目录继承已消耗槽位、未发送槽位、RNG、暂存子代及原凭证，不改写旧账本或释放未知token预留。本轮v1–v4是连续一代的来源链，不是额外实验。

以下是该开发批次当时的报告命令，无密钥、无模型请求；须使用其protocol绑定的源码版本。当前v5源码会拒绝旧目录resume，直接查阅Development_report.json，不以此命令作为当前可执行示例：

```bash
.venv/bin/python -B experiments/tier2/research_real_v1/run.py development-report \
  --run-dir runs/leaf-tier2-single-P-acceptance-20261010-v4 --resume \
  --config runs/leaf-tier2-single-P-acceptance-20261010-v4/config.development.authorized.json \
  --manifest data/fjsp_manifest.json
```

单组后续阶段为development-select、development-freeze、development-test、development-report，使用独立Development_*凭证，不创建其他三组终态或正式实验冻结。开发选择预先声明已用train中的Behnke1–3，评价最终5条U；开发测试用Behnke4/13/14，不调用LLM，也不以结果修改U*。仅检验代码链路，不支持独立泛化结论。已完成的同目录重读凭证不会新增请求；修改配置、源码或数据仍要求新协议/目录。[最终核对](../../../runs/leaf-tier2-single-P-acceptance-20261010-v4/Final_development_audit_20261010.json)及148项本地测试保留。

独立初始化多样性检查仍是未执行计划。N=5共享池已完整，此开发目录initialize-u发送0次；未来最多5次v4检查需另行绑定届时最新预算及N=10部分池，不使用旧预算另开并行付费分支。旧离线缩小目录只保留先前证据，不继续执行其旧源码绑定命令。

v4只在V5BudgetedSearch的共享INIT阶段增加已接受U代码的去重上下文；无H行为、训练分数、排名或演化父代，各组共享同一初始化。保留常量U；去重在原AST代码键之外，仅新增纯整数return/int(整数)等价检测，不改变代码键或冻结资产，不把同分策略当重复。H提示和四组演化提示正文未改变；旧Search和DeepSeek适配保留原策略。提示归档按代码键稳定排列，完整条目总计最多131072字节，超过限额省略整条代码，实际发送仍检查总提示字节上限；inflight保存精确提示，恢复不重建或重发。

旧v3的`provider.stream_response=true`仅适用于openai-chat-v1，发送stream与include_usage，收齐相同id/model的单choice内容、stop、最终usage和DONE后才接纳；中断、截断、异常工具/拒绝输出不接纳、不重试。模型精确锁定gpt-5.6-sol，逐实例15秒、请求输出8192、用量预留32768、温度/推理参数不发送。开发来源链可递归验证原批次凭证、固定源码和完整训练结果；原复用守卫只允许列明工程差异，不能绕过它批准新提示的H。前两批8条h复用不产生新HTTP，v3最多288槽位，连同前两批12槽位合计不超过300。当前H审查/冻结和U阶段实际状态只见根README。

当前输出请求8192仍有实测usage9967的供应商响应；不能把max_completion_tokens当成Leaf实际收费的硬上限。正式协议需确认该别名/转发链的上限语义及响应模型，开发使用独立32768预留和实际扣额守卫。H编号当前按训练均值/稳定ID排序赋予，虽然接口与提示要求将其作为类别使用；正式协议需决定保留此相关性还是打乱编号，当前未修改编号行为。完成进度只见根README，不由配置或自动样例推断人工批准。

## 新协议离线准备与训练报告（2026-10-11）

当前提示为v5-state-bounds，旧已冻结开发目录不能直接resume。独立准备入口只读取历史资产、重新评价train、核对数据字节身份，既不读凭证也不创建真实客户端：

```bash
.venv/bin/python -B experiments/tier2/research_real_v1/prepare_paired_research.py \
  --run-dir runs/conditional-paired-research-NEW --audit-u
```

目录必须不存在。配置写config.research.pending.json，real_requests_authorized=false，conditional_research.scope_approval=null。不会冻结H或导入旧初始U。新scope批准必须来自人，包含真实reviewer、conditional-fixed-H-research范围、说明、原H哈希和按编号的代码键；新付费授权也须另行登记在新配置。修改已建立协议配置须新目录重新准备，禁止替换原protocol后resume。

`run.py prepare-research`仅做离线H来源/历史预算绑定及全train重评；`freeze-conditional-h`要求真实scope批准；之后initialize-u/search-arm/search/select/freeze/test沿用四组研究入口。当前审批前不能执行生成阶段。`training-report`在训练期间或失败后保留全部结论，不要求test完成，也不触发任何生成或holdout访问。示例（需对应已建立且合法冻结的研究目录）：

```bash
.venv/bin/python -B experiments/tier2/research_real_v1/run.py training-report \
  --run-dir runs/conditional-paired-research-APPROVED --resume \
  --config runs/conditional-paired-research-APPROVED/config.research.approved.json \
  --manifest data/fjsp_manifest.json
```

新训练诊断由training_diagnostics=true启用，第三次观察排程在独立进程单独计时、另用相同长度的实例期限；诊断失败不能改变原两次排程的有效性与适应度；static proof、自然分支覆盖和完整状态轨迹不反馈模型、不影响去重或选择。解析、代码/接口约束、API、运行失败、AST重复和窄等价重复分别计数。预算记录继承为哈希绑定历史快照，累计请求/未知token与账户预留和本批成本分别报告；不把新的局部账本0次误报为账户历史0次。

本机已完成的离线准备见[最终核对](../../../runs/conditional-paired-research-20261011-v4/Final_offline_audit.json)；它不是批准后可直接续写的真实运行目录。批准范围/配置改变时建立新目录与新协议，重新绑定来源、预留及重评结果。首批训练小试不调用select/test；扩大规模和最终验证/测试须先固定后续协议，不能用小试测试结果调参。


## U使用方式两组扩展：usage_v2（2026-10-12）

此入口与旧单编号/四组研究入口分开。新语义及已完成/未执行状态见 [U使用契约](../../../docs/U_USAGE_CONTRACT_V2_DRAFT.md)。A仅SELECT，B允许SELECT/MIX；初始P0共享SELECT，禁止把手写fixture导入真实初始池。旧目录不能用新源码resume，新研究H需新范围确认；请求与未知额度继承。

在项目根目录复现独立toy例子和手写两组接入（目录必须不存在，无真实模型请求）：

```bash
.venv/bin/python -B experiments/tier2/usage_v2/run.py examples \
  --run-dir runs/usage-v2-examples-NEW
.venv/bin/python -B experiments/tier2/usage_v2/run.py synthetic-acceptance \
  --run-dir runs/usage-v2-toy-acceptance-NEW
PYTHONPATH=code .venv/bin/python -B -m unittest discover -s tests -v
```

离线准备固定H训练重评、完整提示、预算与人工门禁；只读取train，配置默认禁用真实请求，目录须为新的runs直接子目录：

```bash
.venv/bin/python -B experiments/tier2/usage_v2/run.py prepare \
  --run-dir runs/leaf-usage-v2-AB-preparation-NEW
.venv/bin/python -B experiments/tier2/usage_v2/run.py compatibility \
  --run-dir runs/leaf-usage-v2-AB-preparation-NEW \
  --config runs/leaf-usage-v2-AB-preparation-NEW/config.pending.json
.venv/bin/python -B experiments/tier2/usage_v2/run.py report \
  --run-dir runs/leaf-usage-v2-AB-preparation-NEW \
  --config runs/leaf-usage-v2-AB-preparation-NEW/config.pending.json
```

prepare内的配置固定seed301、N5、初始化≤20、两组各1代×10，最多40新增请求；15秒共同期限，交叉5父代/变异1父代。初始化失败或重复占槽位，不补发。新H范围批准与新付费授权改变配置后必须用新目录prepare，不能改原protocol继续；人工scope须绑定原H哈希与按编号代码键。批准后依次freeze-h、initialize、search-arm --arm A/B或search、report，始终显式指定同一绑定配置。现行入口不提供validation/test。

prompts/A.I1.txt、B.I1.txt为相同首条完整初始化提示；CROSS/MUTATE示例使用相同明确手写预览父代，差异仅allowed_modes，不能声称未来真实父代已确定。真实每条发送提示在budgeted_*_requests.json及inflight保存，初始化追加实际已接受源码归档。成本报告区分第一次求解、确定性复检和独立诊断的h调用、处理成本及时间；相同请求数不是相同计算成本。

付费阶段仍使用原 provider.api_key_env=LEAFAPI_API_KEY；调用者需通过既有凭证方式向该进程提供环境变量。本轮prepare/examples/compatibility不加载密钥或创建真实客户端。模型、渠道、stream、输出限制、温度/推理参数均从原已授权供应商配置逐项继承，新授权只批准新批次，不隐式换模型。

## 原单成员研究 worktree（2026-10-13）

本节适用于 `codex/u-single-experiments`。入口为 [run_single_experiments.py](run_single_experiments.py)，使用原 `select_heuristic(七输入) -> int`、单个 h 的原始动作分数和七项状态；不进入 usage_v2，不允许元组/MIX。计算形式可含合法算术、条件、循环，未规定程序骨架。

本次训练提案继承原四组协议：seed201、N=5、全新共享SELECT-ID初始化最多20请求；B0/B1各按 E1/E2/M1/M2/M3 各2槽位，B2/P各5交叉+5变异；交叉5父代、变异1父代、各1代10槽位，最多60新请求。B0无H代码/行为；B1有H信息；B2同B1但通用交叉/变异；P同B2信息但特化算子。各组共用完整21train、H、初始池、评价器和供应商配置。不导入旧U为本次P0，不生成新H。

```bash
.venv/bin/python -B experiments/tier2/research_real_v1/run_single_experiments.py prepare \
  --origin-root '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research' \
  --run-dir runs/single-ID-paired-training-NEW
.venv/bin/python -B experiments/tier2/research_real_v1/run_single_experiments.py preflight \
  --run-dir runs/single-ID-paired-training-NEW \
  --config runs/single-ID-paired-training-NEW/config.single.pending.json
PYTHONPATH=code .venv/bin/python -B -m unittest discover -s tests -v
```

prepare 离线完整重评10条H，保存代码/提示/配置快照、数据哈希、原H身份、只读来源和跨worktree账本身份。15份全文提示中的演化父代明确是手写预览，未来每条实际提示随真实请求归档。原H人工行为审查仍保留开发范围；新研究范围批准模板不自动填写。

准备配置禁用真实请求。用户明确批准原H用于固定H条件研究和本批付费范围后，在工作tree内另存批准配置（逐键原H批准、real_requests_authorized=true），使用新的 runs 目录、相同 prepare 命令加 `--config` 注册；不修改已有 protocol 或准备证据。批准配置必须保留所有来源哈希、原供应商字段、规模和累计预算。批准后在同一注册目录按 `freeze-h`、`initialize`、`search`、`training-report` 执行，每步显式使用同一 `--config`；入口不提供 validation/test。

此任务只写本worktree。原仓库runs及本地复制的987份来源文件保持只读；实际配置绑定准备时的全部来源。每次发送前再检查源码、原来源以及其他worktree实际账本，原始账本按identity去重核对。新外部消耗或writer锁会停止，不自动重新绑定/结清/放宽预算；需要联合核对两任务额度后注册新批次。付费调用须串行，其他聊天页不能同时使用同一账户进行研究生成。检查仅覆盖本Git仓库列出的worktree；供应商账户保护还会核验实际累计用量，不能认证其他外部程序完全没有请求。

失败、重复占槽位；初始化20次耗尽仍不足5则停止全部演化，不降N/补员；即使一组无有效子代仍按原规则完成该代。未结算新请求、账户边界、源码/数据/来源变更均停止。完成条件为共享池成功、四组各10槽位与生存选择实际完成、所有有效候选完整21train及确定性复检、全部失败/重复和分阶段成本保留；一个seed仅是初步条件训练实验。validation11历史已暴露，test28本批不解析/求解；后续验证/测试和扩展种子需另行预登记。

本页用户于2026-10-13明确批准第一阶段：DDXQL确认原10条H用于固定H单成员四组条件研究，seed201/N5/init≤20/四组各1代10槽位/最多60新请求，仅训练；其他40次MIX方案挂起，本页独占真实调用。授权及新注册目录独立于原准备目录。

单成员入口新增 `--env-file`：仅 initialize/search 从明确的既有凭证路径加载到当前进程，凭证不复制或归档。每请求保存 `/api/log/token` 的安全字段及额度变化；唯一新账单匹配模型、发送时间窗口、实际扣额后才认证平台成本。仅对已认证账单的普通失败恢复继续，保留原失败、未知wire usage及token预留。其他停账原因/无法匹配账单不绕过。生成参数、提示、状态、评价和选择未改变。`results` 导出全部响应/源码、失败/重复、完整逐实例训练结果、描述性配对比较和逐请求/候选平台单位；没有美元/人民币换算。
