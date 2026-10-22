# T1-D2B：B2/B1 历史 Prompt 真实流式对照诊断

日期：2026-10-22。**两组诊断观察均完成，但两组传输均失败，没有取得完整模型输出，程序合法性均为未知。**

## 1. 身份、授权及执行

- 工程提交：`b8ba4fb21abd472cac5e7f0aa25f7d69ddc5739a`，分支 `codex/h-usage-space`。
- 协议 SHA256：`5a71bbb9ab4b2befcf0d04b053ccd5ff2b198bd4470de8dcdf62bd4785a0221d`。
- 原始运行目录：`runs/t1-d2-b2-b1-prompt-ab-v1-20261022/`；本目录 `evidence/` 是结束后的持久化证据副本，不能作为另一份执行目录。
- 启动前核验当前提交、14项运行代码指纹、两份 Prompt 原文字节、运行身份、无旧请求／检查点／活动 writer，均通过。依据用户本轮明确授权创建本批 `Authorization.json`，未沿用其他批次授权。
- 同一进程内按 A→B 顺序调用；同一个 gpt-6.1-sol 客户端、endpoint、凭证配置、stream=true、include_usage=true、8192输出上限、10/240/300秒连接／读取／总超时。
- 实际命令如下。执行日志只有 `completed`；该词表示两份观察已记录，不表示传输成功。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/t1_d2_prompt_ab.py run \
  --run-dir runs/t1-d2-b2-b1-prompt-ab-v1-20261022 \
  --env-file ../FJSP-Heuristic-Research/.env.leafapi.local
```

结束后仅执行冻结入口的 `report`，从已保存记录导出 A/B 表，没有重发或重放。使用了 `ahd-experiment-copilot` 的证据与未知值口径。

## 2. A/B 观察结果

| 项目 | A：B2-1 历史 CROSS | B：B1-1C 历史 INIT |
|---|---|---|
| 历史任务 ID | `B/g0000/000000` | `B/init/000000` |
| 历史 Prompt UTF-8 字节数 | 11,058 | 21,250 |
| 新尝试 ID | `T1-D2/A/attempt/01` | `T1-D2/B/attempt/01` |
| 确认发送时间，UTC+8 | 2026-10-22 16:49:22.440 | 2026-10-22 16:50:50.091 |
| 结束时间，UTC+8 | 16:50:49.295 | 16:50:55.275 |
| 尝试耗时 | 87.604秒 | 5.964秒 |
| HTTP / Content-Type | 200 / text/event-stream | 200 / text/event-stream |
| 已解析 data 事件数 | 3 | 3 |
| 流内 id | 第3事件发生变化，44→55字节 | 第3事件发生变化，44→55字节 |
| 可见 model | 一致，匹配 gpt-6.1-sol | 一致，匹配 gpt-6.1-sol |
| 完整文本 | 未取得 | 未取得 |
| stop / usage / DONE | 均未收到 | 均未收到 |
| 失败阶段 | sse_decode | sse_decode |
| 异常 | TransportError: stream identity/model changed | 同左；具体变化字段同样是 id |
| 分类 | protocol_incompatible，非重试故障 | protocol_incompatible，非重试故障 |
| U 基本输出合法性 | null，无法检查完整程序 | null，无法检查完整程序 |
| 输入 / 输出 token | null / null | null / null |
| 实际费用 | null | null |

发送时间为本地发送确认回调时间，不是精确的网卡发包时间。耗时从尝试预留到结束，包含发送前准备，因此不等于表内两个时间之差。整个配对窗口约93.589秒，未发生中断、恢复或超窗。

网关追踪号（允许名单字段 `x-oneapi-request-id`）：

- A：`202610220849226698088548268d9d6yeCQun7d`；确认发送 UTC `08:49:22.440`，结束 UTC `08:50:49.295`。
- B：`202610220850504911789028268d9d6XIheI4U4`；确认发送 UTC `08:50:50.091`，结束 UTC `08:50:55.275`。

证据：[`AB_result.csv`](evidence/AB_result.csv)、[`AB_result.json`](evidence/AB_result.json)、[`requests/attempts.json`](evidence/requests/attempts.json)。完整历史 Prompt 来源、原始文件路径、SHA256及历史 token 见 [`Source_provenance.json`](evidence/Source_provenance.json)。历史 A 的2759/515 token不能套用于本次失败请求。

## 3. 异常证据与能定位的范围

两组均通过网络建立及 HTTP 响应阶段，失败点是客户端对已解析 SSE JSON 的身份一致性检查。不是 U 非法、AST重复或 FJSP失败；也没有发生鉴权／额度错误、锁定模型失配或发送状态未知。

| 组 | 前序 id SHA256 | 第3事件 id SHA256 |
|---|---|---|
| A | `0ccd966adbd457b21819ed9f6293ef595f29aa72fe62d53659f651c1b71168f8` | `44bbd79e532436ffacd44875b86f283616e42df9ceba807c6b4af643558be0cf` |
| B | `44aed34db46d5b5b51c67e03222bf80f83cd48ceb1a4fe904dc9714a1acf3b5b` | `1a37c638fed856333c77ef996a6e8dab0b6373c60f58b57b1225e50bceaaece8` |

两组失败帧均为JSON对象，含一个 choice 和 delta.content；保留的结构证据未显示显式上游 error 帧。异常类型文字同时提到 identity/model，但本次 `identity_change.field` 明确为 `id`；可见 model 字段哈希与锁定模型一致，不能写成“模型被换了”。

解析前缀 A/B 分别读取656/1383字节；在触发拒绝前累计接收正文均仅1字节。这些是已读取前缀，不是完整响应大小。客户端拒绝并关闭后是否还会出现 stop、usage、DONE或其他错误帧，**未知**；不能声称供应商从未生成它们，也不能还原未保存的原始 SSE 全帧。

两份 wire 失败凭证保存了字段形状、帧哈希、身份变化和允许名单 HTTP 证据：

- [A wire](evidence/wire_responses/9768143b582d21de4aa322a7a4c29cfe2b735f8db274a72ba8aefab7d34aa82d.json)
- [B wire](evidence/wire_responses/5825ff31f50929048af72d4924869b314f701188f0ca9ee8f4e0b67180b6df72.json)

## 4. 预算、停止规则与保护核验

实际2个逻辑任务、2次真实 API 尝试、2次确认发送、0次重试、0个pending，达到本批上限。A普通SSE协议失败后执行B是另一组的新任务，不是对A重试。B失败后连续协议错误达到阈值2，账本 `halt_reason=transport_protocol_circuit_open`；与此同时配对状态为 `completed`，两者不矛盾。不会有第三次请求。

两份请求均没有最终 usage；汇总中 `known_input_tokens=0` / `known_output_tokens=0` 只是空的已知用量小计。**实际总输入、总输出和总费用均为 null，不是零成本。** 未查询余额、价格或账单。冻结 `Budget_plan.json` 保留准备时的零预留声明；实际消耗以持久化 AttemptJournal 为准，未回写冻结计划。

未修改任何代码、Prompt、模型、传输参数、校验规则或预算；未加载 train21/validation11/test28；FJSP评价0、Fitness未计算、诊断程序进入科研种群0。旧B2、B1和T1-D1目录的189个既存文件 SHA256 与 mtime_ns 均未变化，也未新增／删除旧目录文件，详见 [历史保护核验](Historical_protection_check.json)。原凭证未复制、未显示、未纳入本报告。

## 5. 对研究问题的解释

**已观察事实：** 在当前同一窗口及相同传输配置下，B2历史成功 CROSS Prompt和B1 INIT Prompt都发生同一形式的第3事件 id切换，两组完整传输均为0/1。B2那份历史Prompt这次不再能完整接收，因此“只有B1初始化任务才会出现此故障”不符合本次观察。

**得到加强的排查方向：** 当前共同服务链路的流协议兼容性值得优先排查，例如网关与上游接续时是否产生不同 id。这只是有依据的机制假设，尚不能定位究竟是网关生成、上游返回、路由接续还是其他服务变化。当前证据能解释客户端为什么拒绝，但不能独立确定服务商内部根因。

**仍不能断言：** 两种Prompt的稳定失败率相同、请求内容完全无影响、Prompt长度导致／不导致故障、模型被自动替换，或B2历史成功与当前失败之间发生了哪项平台变更。每组只有一次；A/B固定顺序且执行时刻不同，网关路径未受实验控制。两份Prompt的长度、任务类型、H信息、父代内容也同时不同，不能隔离其中单个因素。耗时差不能用于性能归因。

## 6. 建议的下一步与本阶段终止

优先**联系服务商核对协议问题**：可提供以上两份网关追踪号、UTC时间、model/endpoint、stream与include_usage配置、第三事件44→55字节的id变化和脱敏帧结构，请其追溯同一HTTP流内不同id的来源，并确认能否提供id一致的标准流。此处只是建议，本轮没有发送对外消息。

在服务商未解释或修复前，不建议直接启动新B1正式搜索，也不建议放宽id检查来接收当前结果。若需评估非流式传输，应先另行授权一个独立、最小预算的接口诊断，冻结新传输身份；它会改变本诊断条件，不能悄悄替换或并入本批。只有接口路径验收后，再准备使用已验收传输版本的新B1协议；不得续跑旧失败B1或将诊断U并入科研结果。

本次授权已完成并停止，没有自动启动新接口诊断、B1搜索或独立测试。完整文件哈希见 [Evidence_manifest.json](Evidence_manifest.json)，机器可读结论见 [Diagnostic_summary.json](Diagnostic_summary.json)。
