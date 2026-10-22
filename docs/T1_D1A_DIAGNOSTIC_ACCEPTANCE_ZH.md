# T1-D1A：独立接口诊断工程准备与离线验收

2026-10-22（Asia/Manila）。**工程准备通过；等待另行授权真实T1-D1。** 本轮真实API请求0、实例数据加载0、FJSP评价0、正式种群0。没有恢复、补发或读取旧B1的账本、授权及检查点。

入口：[tools/t1_d1_diagnostic.py](../tools/t1_d1_diagnostic.py)。验收：[Offline_acceptance.json](../reports/t1-d1a-stream-interface-v1-20261022/Offline_acceptance.json)、[Tests.log](../reports/t1-d1a-stream-interface-v1-20261022/Tests.log)、[冻结快照](../reports/t1-d1a-stream-interface-v1-20261022/prepared/)。

**冻结对象与当前状态**

| 对象 | 已冻结内容 |
|---|---|
| 最终独立目录 | `runs/t1-d1-stream-interface-v1-20261022-final/` |
| 版本 | `T1-D1-stream-interface-diagnostic-v1-20261022` |
| 协议SHA256 | `7907dac215ba4e5b992a1894c52f243cc872c3107e6682579fc370f3279a6c24` |
| T1基线 | `2eaabe09f4344d23199906def3152871846df8e0`；12份既有依赖代码逐项与该提交相符，另冻结新入口源码，共13项pins |
| 请求预算 | `batch-api-attempts-v2-t1`；2逻辑任务／2次API尝试／每任务1次；退避列表为空，熔断阈值1 |
| 原Prompt | B1的`r501/B/prompts/B_init_000000`，21,250字节；两个任务发送相同字节内容，不重新构造初始化任务或增加反馈 |
| Prompt SHA256 | `7307e5fd4d2d781ee0c546e809c5c3f1d0d694eec2915f9c1bc688a5ab68833e` |
| 来源协议 | B1协议`d5ec72d53583c8dd5829b6a9d8f002511956c346127aad99348e1485f8e3e898`，来源config与协议config完全一致；保留原10H顺序标识 |
| 模型及共同参数 | 原provider字典完整复制：请求和期望响应模型均`gpt-6.1-sol`、8192输出、stream=true/include_usage、温度和reasoning_effort不发送、连接10/读取240/总计300秒；输入/输出用量预留65536/32768不变 |
| 授权 | 仅有`Authorization.template.json`，`approved=false`、费用风险接受=false；不存在实际`Authorization.json` |
| 实际请求与运行状态 | 没有AttemptJournal文件、执行checkpoint、响应或诊断U；只存在零次发送的`Budget_plan.json`声明及冻结输入 |

原B1 Prompt中的排程/评价说明原样保留，但本入口不会执行这些步骤。`ExperimentConfig`仅复用provider和请求预算适配；其通用搜索默认字段不被用于生成H、创建种群或调用演化。

准备阶段只读三份旧B1文件：指定Prompt、`config.pending.json`和`Protocol.json`。三者SHA256/mtime均与本轮开始时相同。运行阶段连这三份来源文件也不再读取，只核验本独立目录的复制输入、协议和代码pins。没有调用B1/B2的prepare/check/run或资产加载器，因此不会顺带加载训练数据或读取旧账本。

本轮中间准备草稿`runs/t1-d1-stream-interface-v1-20261022/`保留未覆盖，从未授权或执行。最终补充了目录身份绑定和“复制协议不能重获预算”的测试，唯一待用目录为带`-final`的上述目录；中间草稿的入口pin已经不匹配，不能执行。没有改写旧B1或T1资产来隐藏变化。

**执行、停止与恢复边界**

1. `prepare/check/status`只做本地文件操作；无账户、价格、账单或模型查询。准备不会读取凭证，也不创建空的假请求账本。
2. `run`首先验证专用T1-D1授权：协议SHA、DDXQL、2/2/1预算、未知费用风险接受及禁止科研评价范围。通过后才读取显式传入的凭证文件、构造客户端，复用原RunLock单写进程保护。
3. 逻辑ID为`D1/000000`和`D1/000001`；API尝试键为`T1-D1/D1/000000/attempt/01`等；本地完整响应另有`.../response`身份。供应商流ID/model由固定T1解析器核验。协议同时绑定绝对运行目录，复制到另一个目录或混用Mock/real记录会拒绝。
4. 使用本目录的`requests/attempts.json`（AttemptJournal）、`wire_responses/`、`responses/00.txt`等、`Diagnostic_checkpoint.json`和`Diagnostic_status.json`。完整归一化响应先于U语言解析保存，失败结构证据保存在wire及尝试记录。`Budget_plan.json`只是冻结的初始预算声明，实际计数以后述AttemptJournal为准，不能用计划中的零值重置计数。
5. 真实客户端仅在同一流中满足文本、最终usage、stop、DONE、id/model一致及锁定模型后返回成功。DONE/身份一致性的依据是冻结T1 `decode_stream()`的成功返回路径，而不是另行声称保存了原始全部SSE帧。保留完整响应文本、usage、finish_reason和允许的响应metadata。
6. 再用原`parse_response(..., interface_version=U-usage-v2-select-or-mix-20261012, member_count=10)`做受限语言/输出结构静态校验。不调用U、compile_candidate、h评分或调度器；不能将AST通过解释为所有可达状态下输出都合法，或完整排程有效。两份U允许相同AST。
7. 首次任何失败即停止，包括临时网络/服务故障、协议异常、非法文本/代码。临时错误即使被底层标为“可重试”，本诊断仍受每任务1次及首次失败停止双重限制，不重试也不启动第二个任务。
8. 协议异常达到阈值1即持久熔断。发送状态未知，或仅预留未确认发送时，T1 v2保留次数并暂停，不自动重发。没有自动清除停止状态、扩额或另建批次操作。
9. 完整wire响应已保存但账本/语言检查未完成时，恢复已有响应；已完成任务不再请求。若第一份恢复后通过，仅允许正常继续原定第二个尚未启动任务。已保存失败则保持停止。缺失账本、孤立checkpoint、Prompt/目录/协议/响应身份不符均拒绝重置或续发。

诊断输出都标为接口诊断来源，不写Fitness、不产生P0/P1/P2、不进入B1候选选择。客户端及脱敏逻辑直接使用T1原提交版本，本轮没有修改公共传输或科研执行器。

**离线验收结果**

26项新增诊断检查、35项T1回归和4项既有SSE检查，**合计65项通过，0失败**。使用临时目录、合成SSE和既有127.0.0.1假服务，未连接LeafAPI。诊断测试执行期间显式禁止真实网络、数据加载、排程评价、U编译/执行、Search创建、账户/账单查询和凭证读取。

关键覆盖：

- 原Prompt字节身份；准备只读三份允许的来源文件；check/session不读旧B1状态；不得覆盖已有准备。
- 两次相同AST通过；两个实际构造的请求共享Prompt；JSON请求字段保持gpt-6.1-sol／8192／stream/include_usage，未发送温度/推理参数，环境MODEL/OPENAI_MODEL不能覆盖它们。
- HTTP 503、流错误、身份变化、错误模型、缺usage/DONE、非法代码/字典/向量长度均失败停止；已完整收到但语言非法的响应仍保留全文。
- 2/2/1限制、已完成不重发、完整wire恢复后只发送剩余第二任务、未知发送和未确认预留不退次数不重发。
- 缺失/孤立记录、Mock转real、协议复制到新目录、路径软链接逃逸、旧目录误用、Prompt/config变化均拒绝。
- 未授权、未批准模板或错误协议SHA均在凭证读取及客户端构造前拒绝。

复现：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python -B -m unittest \
  test_t1_d1_diagnostic test_t1_stream_reliability test_chat_stream_transport -q
```

**模型配置来源只读追溯**

机器可读证据：[Model_configuration_provenance.json](../reports/t1-d1a-stream-interface-v1-20261022/Model_configuration_provenance.json)。范围为本地可用Git refs中的`code/tools/experiments/docs`相关记录及指定历史配置，不读取密钥、查询供应商或修改另一分支。以下时间均为+08:00，与Asia/Manila相同。

| 标识与证据 | 最早定位的记录 | 可以证明／不能证明 |
|---|---|---|
| gpt-5.6-sol，带日期文档 | `docs/API_PUBLIC_PRICING_20261007.json`标记2026-10-07；由`130155d…`保留 | 是公共目录中的模型提及，不能证明当日发送过推理请求 |
| gpt-5.6-sol，准备配置 | `docs/FORMAL_FLOW_READINESS_20261008.json`标记2026-10-08，requested_model为该值、inference_requests=0 | 证明准备时选择该标识；明确不是实际推理证据 |
| gpt-5.6-sol，最早保留代码/配置变更 | `130155daa8b6230205769ed22a2c08d9cb0566b0`，2026-10-12 14:09:09；`research_real/leafapi.py:MODEL/provider()`及`config.api-pilot.draft.json` | 可定位的Git代码/草案绑定；提交时间不等于文件最初编写或首次真实调用时间 |
| gpt-6.1-sol，全部本地refs最早代码变更 | `d71fd1f07ff1bb162c0c29a5045ef67944c2b4a1`，2026-10-14 21:12:10；`research_real/model_migration.py` | 单成员研究历史中的显式迁移；不是当前分支HEAD祖先，只通过Git对象只读查看 |
| gpt-6.1-sol，当前分支祖先中最早代码变更 | `a9794f1f8d81f9c988655ec30cb50b04b97b5acc`，2026-10-14 21:34:47；`usage_v2/model_migration.py:MODEL/check_provider_migration/MigratedUsageConfig` | 明确批准的固定H生成器迁移，限定source model为5.6、target/expected response model为6.1；不是自动fallback |
| 当前B1与本诊断 | 原B1冻结provider字典，两项model字段均6.1 | 本诊断继承同一字典，不调用仍默认5.6的`leafapi.provider()`工厂 |

`.env.leafapi.local`内容本轮未读取。依据已保留的`load_local_key()`代码，该文件仅接受一项`LEAFAPI_API_KEY`，不是模型配置入口；真实POST的model字段来自冻结`provider.model`。Codex聊天自身的模型选择与Leaf研究请求是不同配置面，不能混为一谈。

结论：可证明本地发生过显式代码/协议迁移，不能证明供应商后台路由、实际权重版本或所有外部历史未变。没有从上述记录确定两种标识的全项目首次真实请求时刻，不猜测平台自动替换模型；响应同名也不等于后台权重一致的证明。

复核Git证据的本地命令：

```bash
git log --all --reverse -S 'gpt-5.6-sol' -- code tools experiments docs
git log --all --reverse -S 'gpt-6.1-sol' -- code tools experiments docs
git log HEAD --reverse -S 'gpt-6.1-sol' -- code tools experiments docs
git show a9794f1:code/fjsp_usage/usage_v2/model_migration.py
```

**真实调用前仍需的授权与费用风险**

工程上已就绪，但尚不允许真实发送。需要用户明确授权本协议SHA对应的T1-D1，接受最多2次尝试及失败/未知状态可能计费的风险。收到授权后才据实将模板填成`Authorization.json`；本轮不生成该批准文件，也不检查实际密钥内容。

名义风险预算建议仍为不超过人民币5元，但没有确认当前静态单价，不估算实际费用、不保证5元够用或形成硬限额。8192输出上限与65536/32768用量预留不能证明供应商最大实际扣费；usage缺失时费用保持unknown/null。若用户要求货币硬上限，需先确认供应商侧独立限额，否则不能声称客户端能保证。无需也不会重新引入实时余额、价格或逐请求账单查询。

最多两次顺序调用，总网络期限名义上不超过2×300秒，另有本地校验开销；首次失败则不再调用第二次。不会产生FJSP求解开销。两次通过只证明基本接通，不能证明长期服务稳定、旧线上根因已消除或新U有科研价值。

在仓库根目录可执行的只读核验：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/t1_d1_diagnostic.py check \
  --run-dir runs/t1-d1-stream-interface-v1-20261022-final
```

以下是真实启动/安全恢复命令，**本轮没有执行；只有另行授权并登记Authorization.json后才能使用**。沿用已有凭证文件路径，不复制密钥：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/t1_d1_diagnostic.py run \
  --run-dir runs/t1-d1-stream-interface-v1-20261022-final \
  --env-file ../FJSP-Heuristic-Research/.env.leafapi.local
```

同一命令不会重置预算；停止终态保持停止，未知发送不补发，已有完整响应按上述恢复规则处理。不要重新prepare同一目录，不复制协议到新目录，也不将诊断结果并入旧B1。
