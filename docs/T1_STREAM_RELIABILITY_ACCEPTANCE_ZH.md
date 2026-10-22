# T1：真实 LLM 流响应故障的离线修复与验收

日期：2026-10-22（Asia/Manila）。范围：公共传输、脱敏留证、故障分类、未来新协议的熔断及离线测试。真实 API 请求新增 **0**，正式 FJSP 评价新增 **0**。旧 B1-1C 不恢复、不补发，不修改其授权、协议、响应、账本或检查点。

验收证据：[Offline_acceptance.json](../reports/t1-stream-reliability-v1-20261022/Offline_acceptance.json)、[Tests.log](../reports/t1-stream-reliability-v1-20261022/Tests.log)。Mock 的程序、响应和 Fitness 均不是科研结果。

**A. 已知故障与尚未证明的根因**

原批次 `runs/b1-full-h-free-seed501-k2-v1-20261021/` 的权威文件为 `r501/B/batch_requests.json`、`wire_responses/`、`r501/B/checkpoint.json` 及 `Execution_B1_1C.log`。

| 原记录 | 可证明事实 | 仍未知 |
|---|---|---|
| 10次 `invalid/error stream chunk` | HTTP 200之后，JSON帧非对象或含非空error，旧解析器拒绝 | 具体错误码、消息、是否临时服务错误；旧帧未保存 |
| 5次 `stream identity/model changed` | 流内至少一个id/model字段与前帧不同 | 究竟哪个字段改变、是否网关重路由或标识兼容问题 |
| 3份完整响应 | 格式错误1、完整有效U 1、AST重复1；没有FJSP评价失败 | 不能用这些结果诊断整个10H搜索能力 |
| 最后一项pending | 预算已预留，未确认发送；中断栈位于发送前资产校验，无wire文件 | 不据此退回预算，不推定任何实际扣费 |

原批共19项逻辑/尝试预留，18次确认发送；费用仍为null。已知输入30441、输出967 tokens，另16项usage未知。两个演化代均未开始。

最有证据支持的故障机制是：HTTP成功建立后，流内容触发公共SSE契约校验；旧留证丢失触发帧及变化字段，使重试器只能判为未分类错误。上游错误帧、网关不稳定或兼容性问题是待核实解释，不能将其直接认定为网络超时、SDK故障、模型切换或B1连接实现错误。B1与B2冻结的传输、记录、重试及客户端构造代码哈希一致，provider参数也一致；B2曾20/20完整接收不保证后续服务状态相同。

本轮没有也不能还原旧批未保存的原始帧。新增测试使用合成帧复现拒绝路径，不冒充历史线上原帧。

**B. 实现与逐路径处理**

| 文件与函数 | 修改及必要性 |
|---|---|
| `code/fjsp_usage/research_real/real_transport.py`：`sse_lines`、`decode_stream` | 修复SSE封装兼容：起始UTF-8 BOM、LF/CRLF/CR及跨读取块边界、多行data、大小写不敏感媒体类型、标准要求忽略的未知SSE字段；保持内容和身份校验严格 |
| 同文件：`field_evidence`、`frame_evidence`、`upstream_error_evidence` | 记录类型、数量、受控字段结构、帧摘要、事件序号、字节计数、身份变化字段及变化前后哈希；只保留允许列表内的错误码/类型/状态及固定消息标记 |
| 同文件：`_wire_worker`、`JsonCandidateTransport` | 保留connect/http_send/http_receive/sse_decode阶段；将嵌套脱敏信息传到父进程；transport identity加入`bounded-sse-evidence-t1-v1`，拒绝将新客户端无声接到旧账本 |
| `code/fjsp_usage/usage_v2/access.py`：`WireRecorder` | 失败和中断留证；记录和继续上抛的异常使用相同脱敏metadata；已原子保存完整响应后发生中断，保留完成状态，禁止降级后重发 |
| `code/fjsp_usage/research_real/attempt_budget.py`：`failure_policy` | 区分明确临时、永久、协议不兼容、未知；识别HTTP 200内部结构化临时错误；永久鉴权/额度/参数错误优先于临时信号 |
| 同文件：`AttemptJournal` | 新版显式选择熔断阈值；检查逻辑/尝试/Prompt关联；按持久结果恢复连续异常计数，保留预算和检查点；新版未知发送状态暂停而非自动重试 |
| `code/fjsp_usage/research_real/budget.py`：`validate_request_budget` | 仅增加对新显式版本的公共参数校验，不迁移或改写旧实验 |
| `tests/test_t1_stream_reliability.py` | 合成流、错误证据、重试/熔断、恢复及B1搜索安全检查点集成测试 |

接收边界如下：

| 路径 | T1处理 |
|---|---|
| 正常文本delta、可忽略reasoning delta | 只组装文本，reasoning不进入源码；usage按总量，不重复加明细 |
| 合法SSE封装差异 | 只规范封装，不改变文本或h/U算法含义。参考[WHATWG SSE解析规范](https://html.spec.whatwg.org/multipage/server-sent-events.html#parsing-an-event-stream)：BOM、三种行尾和未知字段的处理 |
| 结构化错误帧、`event:error`、`type:error` | 一律失败，不吞掉，不以错误前的部分代码当完整候选；在stop/usage之后出现错误也不能通过 |
| id/model缺失、空、类型错误、变化或模型不符 | 一律失败；不拼接不同响应，不将SSE外层id当JSON响应id。变化前后只保存长度、类型、SHA256 |
| 不同网关省略usage帧id/model，或把usage提前到未结束的流 | 可能是合法SSE，但不满足本项目冻结的Chat完成契约；本轮不放宽 |
| 非单一choice、错误index、非文本/工具/拒绝输出 | 一律失败，不挑选某个choice或工具结果 |
| 缺stop、缺最终usage、非法usage、无DONE、截断finish_reason | 不接受部分候选；已验证usage保留。明确EOF/超时可有限重试，截断finish_reason不自动重试 |
| JSON/UTF-8非法、行/流/候选文本越界 | 保守失败，保留结构证据，不接受残片 |

原有约束继续保留：每行64KiB、流8MiB、候选文本32KiB、单choice index=0、逐帧id/model一致、锁定模型、最终stop+usage+DONE。新增事件字节计数同样有界。没有SDK接管、自动重连或模型参数修改。

异常留证不存原始错误帧、任意JSON键名、服务端自由文本消息、认证头、Cookie或密钥。未知错误码和消息仅存类型/哈希/长度；可识别机器码采用固定允许列表。WireRecorder与请求账本的异常元数据均递归脱敏。记录不包含可恢复旧帧的替代原文。

**C. 新的故障与熔断状态机**

新增预算版本为`batch-api-attempts-v2-t1`，仍使用原AttemptJournal和WireRecorder，不创建第二套客户端或额度系统。新版本必须显式登记`protocol_error_circuit_threshold`，合法范围1–10；建议未来搜索预设3。示意配置只说明能力，**不是新实验授权或对旧配置的修改**：

```json
{
  "version": "batch-api-attempts-v2-t1",
  "logical_candidate_cap": 40,
  "api_attempt_cap": 60,
  "per_candidate_attempt_cap": 3,
  "retry_backoff_seconds": [2, 5],
  "protocol_error_circuit_threshold": 3
}
```

| 结果 | 请求行为与持久化 |
|---|---|
| 明确连接故障、超时、429/502/503/504或允许列表内临时服务错误 | 先保存尝试结果，在单任务/全批预算内按原退避重试；不新增逻辑候选 |
| 鉴权、模型、参数、额度等永久错误 | 不重试，停止后续发送 |
| 身份变化、schema等协议不兼容 | 不重试；计入连续协议异常 |
| 没有临时性证据的上游错误帧 | 未知错误，不重试；计入连续异常，不能凭HTTP 200当成功 |
| 连续达到登记阈值 | 在失败尝试落盘后设置`transport_protocol_circuit_open`；当前候选失败结果可提交到检查点，下一次发送前停止。不会杀死另一个在途请求，也不增加额度 |
| 完整响应 | 固定第一份持久完整响应，清零连续协议异常；随后非法代码、重复或评价失败均不再请求 |
| 明确非协议故障 | 不算连续协议异常；连续含义以API结果为单位，不是程序数量 |
| 进程中断、发送状态未知、仅有预留而无确认发送 | 新v2保留尝试数并设置`uncertain_dispatch_requires_review`，暂停发送，不把未知当超时自动重试；旧v1仍保留原已验收的未知状态有限重试语义 |
| 完整wire响应已保存而账本未接受 | 恢复该响应，不重新请求。评价已完成则沿既有缓存复用，不重评 |

熔断没有自动清除或自动续跑接口。重启重新核验已有记录和身份，不能清零阈值、预算或换Prompt。未知尝试不会抹掉此前协议异常。没有新增全局锁；同实验仍要求单写进程，原CLI锁及账本revision冲突检查不变，不能宣称支持并发多写者或供应商侧exactly-once。

**D. 验收及公平性影响**

35项新增T1检查、85项既有相关回归检查，合计**120项通过、0失败**。全部采用内存/临时目录Mock、合成程序/成绩及既有127.0.0.1 HTTP假服务，不连接LeafAPI；T1测试还显式阻断socket连接、账户/账单查询、数据加载和真实评价函数。

覆盖包括：正常流；BOM/三种行尾/跨块UTF-8；错误帧与error事件；stop/usage/DONE缺失；id与model变化/缺失；截断/非法JSON/非标准内容；临时与永久优先级；脱敏从worker到wire再到账本；有限重试与退避；任务及尝试上限；三次异常熔断；失败wire恢复时熔断；完整wire落盘后中断；发送状态未知；预留未发送；重复启动保护；B1在候选间保存检查点停止。既有回归另覆盖非法/重复/评价失败不重试、已完成评价不重复、两代更新/继承与SELECT/MIX语义。

本轮前后核对三个相关运行目录277份文件的SHA256和mtime，以及原保护清单359份历史文件（两清单可重叠），均未改变。旧协议SHA仍为`d5ec72d53583c8dd5829b6a9d8f002511956c346127aad99348e1485f8e3e898`，无writer锁。没有修改H、U接口、状态、Prompt、模型配置、排程器、Fitness、父代或生存选择。

必须披露的新旧行为差异：

1. 字段结构/哈希、阶段、脱敏、关联核验主要改善证据与恢复可靠性。
2. BOM、CR、媒体类型大小写及未知SSE字段等原可能误拒的封装现可接受；这是接收集合变化，不能声称所有接收语义完全相同。
3. `event:error`及显式error字段（包括null）不会被当成正常完成，收紧了异常接收边界；id/model一致性没有放宽。
4. 从流内结构化证据识别出明确临时错误后，可能比旧实现增加预算内重试次数；未知错误仍不重试。
5. 新v2熔断会提前停止失败批次；未知发送改为暂停，可能减少实际请求数。旧v1不自动启用熔断，也不追溯改变其未知恢复规则。
6. 完整响应提交窗口修复可能避免原本不必要的重发，但不能消除供应商已处理而本地从未收到的计费未知。

因此，修复后真实结果只能属于新的独立协议和运行身份，不能并入旧B1、补齐旧P0或将请求成功率变化解释为科研算法改进。transport版本和代码指纹变化会拒绝旧账本接入；旧实验重现应使用其原提交。不得修改旧指纹来“通过”。

入口覆盖边界：公共配置校验、AttemptJournal、WireRecorder和传输已支持新v2，并有B1Search+v2的合成集成验收；**旧B1/B2专用Config仍冻结其原v1策略**。本轮没有放宽这些入口、创建新真实运行或授权记录。未来新B1/诊断入口须另行登记科学条件、代码版本与新v2策略，不能直接拿旧B1 CLI恢复。

**E. 下一次最小真实接口诊断建议（本轮未执行）**

建议独立的`T1-D1`接入诊断：最少2份完整响应作为基本通过条件，最多2个逻辑任务、2次真实尝试、每任务1次；不自动重试，第一份不完整即停止，不为凑齐通过追加请求。熔断阈值登记为1。使用相同已登记模型、生成参数及原B1初始化Prompt快照；只验证接收、完整保存、usage及输出契约，不排程、不进入种群、不比较Fitness。诊断生成物明确为接入材料。

通过：两次均完成锁定模型、流内身份一致、文本/usage/stop/DONE校验，Prompt/响应/尝试ID关联完整，无未决发送，输出满足U受限语言；不要求两个源码不同。任何协议异常、临时故障、永久错误、未知状态、完整输出格式不合规均使该次诊断不通过并停止，保留不同失败分类。两次通过只证明基本接通，不证明长期稳定或旧线上根因已经消除。

费用建议：单独接受最多2次尝试的风险预算，建议预先设定不超过人民币5元的可承受额度，**这不是价格估计或客户端硬扣费保证**。不更改原8192输出配置；按人工确认的有效静态输入/输出单价Pi/Po（每百万tokens）核对名义预留`2×(65536×Pi+32768×Po)/10^6`是否覆盖。预留/输出参数不保证供应商严格按此计费；费率未确认或usage缺失时实际费用保持未知。若要求货币硬上限，应先由用户确认供应商侧独立限额可用，否则不声称本地能保证；不恢复账户/账单查询系统。

上述诊断还需新的专用运行登记、薄入口和用户执行授权。本轮不实施这些真实调用准备，不创建新B1批次。工程结论仅为离线机制验收通过，服务端故障修复有效性仍待独立小试验证。

复现离线验收：在本分支根目录运行（不会执行正式训练）：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python -B -m unittest \
  test_t1_stream_reliability test_chat_stream_transport test_h01_attempt_retries \
  test_b1_usage_local test_openai_chat_transport test_research_real_transport \
  test_U_usage_v2 test_research_evolution test_usage_v22_handoff_access -q
```
