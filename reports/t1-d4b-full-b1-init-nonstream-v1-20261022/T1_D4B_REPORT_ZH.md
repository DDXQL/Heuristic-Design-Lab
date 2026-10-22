# T1-D4B：完整B1 INIT Prompt单次非流式真实诊断

2026-10-22，`codex/h-usage-space`。**传输及响应完整性通过；完整U回复格式失败；代码体单独静态检查通过；诊断整体未通过。** 实际1次API尝试，无重试或补发，完成后停止。

## A. 完整B1 Prompt是否取得完整响应？

**本次取得了。** 原21,250字节的完整10H INIT Prompt未经修改，通过原公共客户端的非流式HTTP JSON解析，取得完整可见正文、正确模型、stop和usage。

| 项目 | 实际记录 |
|---|---|
| 运行目录 | `runs/t1-d4-full-b1-init-nonstream-v1-20261022/` |
| 执行工程提交 | `602982db2520269d8e0947b2c96a82c5d81b5a78` |
| 协议 SHA256 | `254fc61b96a04347cc8f7ae4205a6546266e48d83791b4408d6f381f7ed352ec` |
| 历史Prompt任务 / 尝试 | `B/init/000000` / `r501/B/B/init/000000/attempt/01` |
| Prompt SHA256 | `7307e5fd4d2d781ee0c546e809c5c3f1d0d694eec2915f9c1bc688a5ab68833e` |
| 本次尝试ID | `T1-D4/B1-INIT/attempt/01` |
| 客户端完整响应ID | `T1-D4/B1-INIT/attempt/01/response` |
| JSON响应id | `resp_041eecd419ce19b8016ad9ea6a3fe48195bc95eef592d30814` |
| 模型 / endpoint | `gpt-6.1-sol` / `https://leafapi.cc/v1/chat/completions` |
| 请求流设置 | stream=false，不发送stream_options |
| 输出上限 / connect-read-total期限 | 8192 / 10-240-300秒 |
| 确认发送时间 | 2026-10-22 18:50:15.486（UTC+8），10:50:15.486 UTC |
| 结束时间 | 2026-10-22 18:50:22.389（UTC+8），10:50:22.389 UTC |
| 尝试总耗时 | 8.415秒，从预留到结束；发送确认后到结束约6.903秒 |
| HTTP / Content-Type | 200 / application/json; charset=utf-8 |
| finish_reason | stop |
| 完整可见文本 | 377个UTF-8字节，已原样保存 |
| 网关追踪号 | `202610221050158256233858268d9d6LMoI4OEf` |
| x-request-id | `871d8c6c-a28a-454b-a71f-80d38e5c27a0` |
| 输入 / 输出token | 10,104 / 105，来源为本次API响应usage |
| cached_tokens | 4,224，为输入10,104的子集，不另加 |
| 实际费用 | null，没有独立账单证据；未查询账户、价格或账单 |

发送时间是本地确认回调时间，不是精确网卡发包时间。保存的是现有公共客户端的完整规范化回复（可见文本、usage和审计字段），不是原HTTP JSON／推理原文的无损归档。

启动前复核提交、15项运行代码指纹、协议、Prompt原字节、模型与运行目录均一致，且无旧请求／活动writer。根据用户本轮明确授权创建本批批准，未借用其他批次授权。真实命令为：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/t1_d4_nonstream_init.py run \
  --run-dir runs/t1-d4-full-b1-init-nonstream-v1-20261022 \
  --env-file ../FJSP-Heuristic-Research/.env.leafapi.local
```

结束后仅调用原入口的 `report` 从持久化记录导出，未再次调用模型。

## B. U是否满足格式与静态合法性？

**完整回复不满足冻结格式。** 以下为原样正文，说明文字没有按契约包在 `{description}` 中：

````text
I can’t determine member performance from the supplied information, so this uses a deterministic constant selector. It selects member 0 on every nonterminal call.
```python
def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    return (0, (1, 0, 0, 0, 0, 0, 0, 0, 0, 0))
```
````

原 `research/candidates.py::parse_response()` 先验证“一个花括号说明＋一个python代码块”，因此正式诊断记录为：

- `complete_response=true`，`public_transport_received=true`；
- `output_legal=false`，`diagnostic_pass=false`；
- `failure_stage=U_static_validation`，`failure_class=invalid_U_output`；
- `CandidateError: expected one {description} and one python block only`。

没有为通过校验补上花括号，没有改变Prompt、解析器或原回复。完整回复SHA256为 `01e7f62492ecebadd344df1678a6c657c70c893370a185b2967b941a2ae00645`。

为回答代码体是否也有语法问题，另外从已保存文本中原样提取现有围栏内代码，使用原 `usage_v2/candidates.py::validate_usage_code(member_count=10)` 做**只读AST审查**。代码体通过：函数名、七个输入、受限语法和(mode,10项向量)返回结构均满足要求。这不改变正式失败结论，不构造可接收候选，不编译或执行U。审查证据见 [Code_block_static_audit.json](Code_block_static_audit.json)，原样代码块见 [Returned_code_block.txt](Returned_code_block.txt)。

按源码可读出它恒定返回SELECT模式0，H0成员分数为1，其他成员为0；不使用输入状态，不涉及MIX权重。执行器编译／实际调用、与冻结H和合法动作的调度集成、完整排程可行性、期限及Fitness均未验证。本次诊断没有生成正式P0或新科研候选，也不提供动态性或质量收益证据。

## C. 超时、截断、usage和模型身份

本次没有超时、截断、usage缺失或锁定模型失配。HTTP JSON解析成功、finish_reason为stop、正文为字符串且无拒答／工具调用标记，原公共客户端及本批完整性检查均通过。非流式没有SSE事件，跨帧id一致性在本请求中不适用；这不等于放宽原SSE校验。

唯一失败是完整回复的外层说明格式。实际1个逻辑任务、1次确认发送、1个完整成功响应、0次重试、0个pending，API预算已用尽。账本的completed表示传输任务完成；U静态失败另行记录，不能混淆。

没有FJSP评价、Fitness计算、实例读取、种群建立或交叉变异；未修改代码、H/U、Prompt、任何旧账本或本批冻结配置。旧B1/B2和T1-D1/D2/D3六个指定目录的225个既存文件SHA256与mtime_ns均未变，无旧文件新增／删除；本批原准备文件也与D4A备份逐字节相同，详见 [Protection_check.json](Protection_check.json)。`Budget_plan.json`保留准备时声明，实际消耗依据AttemptJournal，不覆盖冻结计划。

## D. 能否支持新的B1非流式协议？

**支持把非流式路径作为新B1协议的工程方案，尚不等于正式搜索已具备全部启动条件。** 本次完整任务成功取得响应，提供了比简单Prompt诊断更直接的接口证据；格式失败同时说明“传输可用”不保证“生成合法U”。

与D2同一B1 INIT Prompt的流式失败相比，本次非流式取得完整输出，进一步支持优先研究非流式接入。但两次发生在不同窗口、非随机交错，服务路由和时段未控制；不能据此证明唯一根因或估计稳定成功率，也不能承诺后续CROSS／MUTATE均能成功。

正式B1前仍需：

1. 为新批次冻结独立身份和 `stream=false`，确认B1专用入口贯通相同模型、endpoint、8192上限及既有超时；明确旧失败B1不恢复、剩余额度不转移。
2. 对实际B1入口做相称离线Mock，确认INIT／CROSS／MUTATE共用预算与检查点、完整响应优先保存、失败恢复不重复发送、代内冻结及跨代选择保持原科研规则。
3. 保留严格输出校验：类似缺少说明花括号的响应按既定非法候选处理，不人工修复进入种群，不因该失败补发；本次诊断程序不进入新P0。
4. 独立登记正式请求／评价规模和停止规则，并取得正式B1授权。本次单次诊断没有授权额外可靠性请求、训练评价或新搜索。

单次8.42秒不能作为长期延迟上界；240秒读取、300秒总期限和费用未知风险仍保留。当前不需要追加调用来“补齐”本诊断。

## 证据与终态

使用 `ahd-experiment-copilot` 完成执行及证据分析。完整 [Diagnostic_result.json](evidence/Diagnostic_result.json)、[规范化响应](evidence/Response.json)、[原样正文](evidence/response.txt)、[请求账本](evidence/requests/attempts.json)、[授权范围](evidence/T1_D4_execution_scope.json)均已保留。机器可读摘要见 [Diagnostic_summary.json](Diagnostic_summary.json)，持久化文件哈希见 [Evidence_manifest.json](Evidence_manifest.json)。未包含API密钥或认证头。

本次已完成并停止；没有自动启动新B1协议实施、演化或任何独立测试。
