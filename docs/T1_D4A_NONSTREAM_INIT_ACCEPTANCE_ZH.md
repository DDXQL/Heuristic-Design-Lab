# T1-D4A：完整 B1 初始化 Prompt 非流式诊断工程验收

2026-10-22，`codex/h-usage-space`。**工程准备与离线验收 PASS；真实请求0，等待另行授权 T1-D4B。** 本阶段使用 `ahd-experiment-copilot`，未读取凭证，未加载数据集，未执行U、FJSP排程或Fitness评价。

## 1. 冻结对象

- 新入口：`tools/t1_d4_nonstream_init.py`。
- 独立运行目录：`runs/t1-d4-full-b1-init-nonstream-v1-20261022/`。
- 协议版本：`T1-D4-full-B1-INIT-nonstream-v1-20261022`。
- 协议 SHA256：`254fc61b96a04347cc8f7ae4205a6546266e48d83791b4408d6f381f7ed352ec`。
- 准备时工程基点：`118b71379a3b7a55e0206f2020df1dbfe43a1cfb`。新协议另以15项文件哈希绑定实际入口、公共实现及复用辅助函数，未改写旧批次代码指纹。
- 当前 `real_requests_authorized=false`；只有未批准模板 `Authorization.template.json`，没有真实授权、请求账本、wire或检查点。
- 可审计备份：[prepared](../reports/t1-d4a-full-b1-init-nonstream-v1-20261022/prepared/)、[离线验收](../reports/t1-d4a-full-b1-init-nonstream-v1-20261022/Offline_acceptance.json)、[测试日志](../reports/t1-d4a-full-b1-init-nonstream-v1-20261022/Tests.log)。备份绑定原运行路径，不是第二个可运行批次。

完整Prompt逐字节来自旧B1，未重新拼接、压缩或调整H信息：

| 项目 | 冻结值 |
|---|---|
| 来源目录 | `runs/b1-full-h-free-seed501-k2-v1-20261021/` |
| 源文件（相对来源目录） | `r501/B/prompts/B_init_000000` |
| 历史逻辑任务 | `B/init/000000` |
| 历史真实尝试 | `r501/B/B/init/000000/attempt/01` |
| UTF-8 字节数 | 21,250 |
| Prompt SHA256 | `7307e5fd4d2d781ee0c546e809c5c3f1d0d694eec2915f9c1bc688a5ab68833e` |
| 旧B1协议 SHA256 | `d5ec72d53583c8dd5829b6a9d8f002511956c346127aad99348e1485f8e3e898` |
| 历史usage | null，不能用字节数冒充token数 |

准备阶段只读这份B1的Prompt、Protocol、config、batch_requests及对应wire五个来源文件，核对原协议／配置一致、Prompt文件与账本全文、Prompt key、任务／尝试身份、确认发送和失败wire。完整路径及哈希在 [Source_provenance.json](../reports/t1-d4a-full-b1-init-nonstream-v1-20261022/prepared/Source_provenance.json)。执行和恢复只使用本批副本，不读取旧账本／授权／检查点。

## 2. 请求设置与代码职责

| 参数 | 本批设置 |
|---|---|
| model / expected_response_model | `gpt-6.1-sol` / `gpt-6.1-sol` |
| endpoint / protocol | `https://leafapi.cc/v1/chat/completions` / `openai-chat-v1` |
| stream | false |
| stream_options | 不发送该字段 |
| max_completion_tokens | 8192 |
| temperature / reasoning_effort / thinking | 沿原共同配置为null，不向请求增加这些参数 |
| connect / read / total timeout | 10 / 240 / 300秒 |
| 凭证来源 | `../FJSP-Heuristic-Research/.env.leafapi.local`，`LEAFAPI_API_KEY`；冻结路径，不记录内容或凭证哈希 |
| 逻辑任务 / 尝试 / 每任务尝试 | 1 / 1 / 1 |
| 自动重试、补发 | 均禁止 |

与旧B1 Provider相比仅 `stream_response: true→false`；既有公共客户端据此生成 `stream=false` 且省略 `stream_options`。Mock通过真实payload构建及 `_wire_worker` 的假HTTP连接核对，不只比较配置字段。

新增 `tools/t1_d4_nonstream_init.py` 负责来源、冻结身份、单任务、授权、结果分层、检查点与报告。复用 `AttemptJournal`、`JsonCandidateTransport` 及其调用的公共 `decode_chat()`、`WireRecorder`、D2的发送时间辅助器及D1的U静态解析辅助器。**没有修改公共传输、生产调度、合法语言、H/U、Prompt、评价及演化代码**。新增测试在 `tests/test_t1_d4_nonstream_init.py`。

公共非流式解析仍严格要求单个文本完成、`finish_reason=stop`、锁定模型，拒绝工具调用／拒答／截断；已有token合法性与子集规则保留。本入口另要求非空响应id和有效usage才认定完整响应，之后才用已有解析器检查说明、代码围栏、七输入和10项返回向量等静态契约。不执行U，所以静态通过不证明所有输入下数值权重／mode都合法，也不代表排程有效。

非流式只有一份JSON，不存在SSE跨帧id一致性问题；没有通过忽略错误流、放宽模型匹配来获得通过。用户提供的D3观察与本地D3摘要一致，但简单Prompt的非流式成功不能替代本批完整Prompt的真实验收。

## 3. 保存、恢复与结果口径

唯一逻辑任务为 `B1-INIT`，唯一API尝试ID为 `T1-D4/B1-INIT/attempt/01`。预算版本 `batch-api-attempts-v2-t1`，退避列表为空，熔断阈值1。

- 使用独立 `Authorization.json`，必须是 `stage=T1-D4B`、person=DDXQL、本协议SHA、1任务／1尝试、无重试并接受未知费用风险；旧B1/B2/D1/D2/D3授权无效。当前不创建真实批准。
- 先持久化运行身份和预算预留，再调用。已保存的完整wire恢复时直接接受，不重发；已有最终结果不再次请求。未知发送、发送前预留后中断均保守占用唯一尝试，恢复不退还、不补发。
- 缺失／孤立账本、孤立wire、路径副本、越界软链接、Mock冒充真实运行及冻结身份变化均拒绝自动继续。不创建全局或跨批次锁；CLI复用既有本目录 `RunLock`，只支持单执行进程。
- 先由公共 `WireRecorder` 保存完整规范化响应，再做静态检查。成功接收的正文另存 `response.txt`，规范化完整对象另存 `Response.json`；账本保存usage、身份、metadata，`send_times/`保存发送确认回调时间。结束时间及耗时来自尝试记录，恢复无法认证的时间保留null。
- 响应保存遵循现有公共客户端：完整可见正文、usage、stop和审计字段，不是原HTTP JSON／推理原文的无损归档。失败保存脱敏异常与允许名单证据，不补造未收到的响应或usage，不输出认证头。
- `Diagnostic_result.json` 区分 `public_transport_received`、`complete_response`、`output_legal` 和 `diagnostic_pass`。完整响应但非法U为输出失败，不触发重试；模型失配、截断、超时／网络、HTTP、协议／未知异常及未知发送分别留证。
- `phase=completed`只表示单次观察已处理，不保证诊断通过。完整性不足时U合法性为null，不冒称非法U。费用始终null，除非另有独立可信费用证据；本入口不查询余额、价格或账单。

序列化配置沿用公共类型，未使用的种群／代数默认字段不会被调用。本入口不建立种群或接入通用选优流程，所有Mock和未来诊断程序均不属于B1科研候选。

## 4. 离线验收

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python -B -m unittest \
  test_t1_d4_nonstream_init test_t1_stream_reliability test_chat_stream_transport \
  test_t1_d2_prompt_ab test_t1_d3b_api_diagnostic -q
```

**98项通过**：D4专项22、T1公共可靠性35、流传输4、D2专项27、D3专项10。覆盖完整正常响应、非法说明／代码／返回结构、缺失id／usage／stop、模型失配、length截断、被截断的HTTP JSON、工具调用拒绝、模拟总期限错误（不实际等待300秒）、未知发送、预留未确认发送、完整wire已存未接受、结果恢复、唯一预算、旧授权拒绝、历史读取隔离及真实payload的非流式参数。

测试使用合成正文、内存Mock及本机合成服务；禁止真实网络、凭证、账户／账单、数据加载、U执行与搜索。D4成功fixture标记为Synthetic，未写入正式准备目录的请求账本。旧B1/B2与T1-D1（两份准备身份）／D2／D3六个指定目录共225个既存文件的SHA256及mtime_ns均未变，无新增／删除旧文件；证据在 [Historical_immutability.json](../reports/t1-d4a-full-b1-init-nonstream-v1-20261022/Historical_immutability.json)。

## 5. 真实执行前提、命令与风险

尚需用户明确授权一次真实T1-D4B，并绑定上述协议SHA256及费用风险，随后据实登记批准。现在没有授权，不可启动。

仓库根目录的离线核验命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/t1_d4_nonstream_init.py check \
  --run-dir runs/t1-d4-full-b1-init-nonstream-v1-20261022
```

以下会真实调用，仅获授权后执行；**本轮未执行**：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/t1_d4_nonstream_init.py run \
  --run-dir runs/t1-d4-full-b1-init-nonstream-v1-20261022 \
  --env-file ../FJSP-Heuristic-Research/.env.leafapi.local
```

同一命令用于保守恢复，不产生第二次尝试；无法安全恢复时停止。`status`仅检查本批文件，`report`仅从本批持久化结果导出，不联网、不求解。

非流式长推理可能在读取阶段240秒内没有完整响应，或达到300秒总期限；不自动延长期限。8192是生成输出上限，不是货币上限，且受公共客户端32KiB正文及512KiB响应体限制。请求超时或接收失败时，供应商可能已生成并计费，费用仍未知；不以失败代替零费用，也不凭旧价格估算扣费。

一次真实成功最多证明当前窗口、完整Prompt及该非流式路径取得可静态校验的输出，不证明稳定可靠性、候选排程质量或LLM搜索能力。真实失败也不自动支持追加预算或调整Prompt。完成本阶段后停止，未启动新B1或任何正式训练。
