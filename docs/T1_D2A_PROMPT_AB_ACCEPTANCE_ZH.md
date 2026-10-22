# T1-D2A：历史 B2/B1 Prompt 配对流诊断工程验收

日期：2026-10-22。结论：**工程准备及离线验收 PASS；真实诊断未启动，等待 T1-D2B 单独授权。**

本阶段使用 `ahd-experiment-copilot`，在 `codex/h-usage-space` 工作区完成。真实 API 请求 0，凭证读取 0，FJSP 评价 0，数据集加载 0。Mock 响应不是科研候选，没有进入任何种群。

## 1. 冻结身份与证据

- 新入口：`tools/t1_d2_prompt_ab.py`。
- 新目录：`runs/t1-d2-b2-b1-prompt-ab-v1-20261022/`。
- 协议版本：`T1-D2-B2-B1-prompt-paired-v1-20261022`。
- 协议文件 SHA256：`5a71bbb9ab4b2befcf0d04b053ccd5ff2b198bd4470de8dcdf62bd4785a0221d`。
- 预算版本：`batch-api-attempts-v2-t1`。
- 已登记为 `real_requests_authorized=false`，只有 `Authorization.template.json`，没有真实 `Authorization.json`、请求账本或运行检查点。
- 可提交备份：[prepared](../reports/t1-d2a-b2-b1-prompt-ab-v1-20261022/prepared/)、[离线验收](../reports/t1-d2a-b2-b1-prompt-ab-v1-20261022/Offline_acceptance.json)、[测试日志](../reports/t1-d2a-b2-b1-prompt-ab-v1-20261022/Tests.log)。运行身份绑定原绝对目录，备份目录不能直接作为运行目录，也不应用来覆盖已有运行状态。

协议冻结两个 Prompt 原始字节、来源凭证摘要、共同 Provider、运行路径与代码文件哈希。仅准备阶段只读访问选定历史材料；执行和恢复使用本批副本，不打开旧批次的授权、账本或检查点。

## 2. 两份真实 Prompt 的来源

选择规则在调用前固定：A 为 B2-1 第一代第一份成功 CROSS；B 为 B1-1C 第一份已发送 INIT。直接复制历史保存的完整 UTF-8 字节，不重新构造或简化。

| 项目 | A：B2-1 CROSS | B：B1-1C INIT |
|---|---|---|
| 历史目录 | `runs/h01-state-weight-search-seed501-batch-v3-20261020/` | `runs/b1-full-h-free-seed501-k2-v1-20261021/` |
| 逻辑任务 ID | `B/g0000/000000` | `B/init/000000` |
| API 尝试 ID | `r501/B/B/g0000/000000/attempt/01` | `r501/B/B/init/000000/attempt/01` |
| 原文件（相对历史目录） | `r501/B/prompts/B_g0000_000000` | `r501/B/prompts/B_init_000000` |
| SHA256 | `3f9c60c00b3b92db43f5b8ceb596b31665449776a2377c96ffe9c1212033d167` | `7307e5fd4d2d781ee0c546e809c5c3f1d0d694eec2915f9c1bc688a5ab68833e` |
| UTF-8 字节数 | 11,058 | 21,250 |
| 历史输入 / 输出 token | 2,759 / 515 | null / null |
| 历史 reasoning token | 298，为输出 515 的子集，不另加 | null |
| 来源核验 | completed、确认发送、完整 wire reply 与账本一致 | failed、确认发送、wire_failed 与任务身份一致 |

来源核对包括 Prompt 文件与账本全文、逻辑 ID、尝试 ID、Prompt key、发送凭证；A 进一步核对完整响应、usage 和 response metadata。相关源文件哈希及绝对路径见 [Source_provenance.json](../reports/t1-d2a-b2-b1-prompt-ab-v1-20261022/prepared/Source_provenance.json)。B 的原始错误帧未被保存，本次不会补造。

A 保留当时五父代 CROSS 任务和原始 H0/H1 信息，B 保留完整 10H 与无父代 INIT 任务。两者不只存在长度差异；任务类型、H 信息和父代内容同时不同。

## 3. 相同传输配置与局部修改

两份历史 Provider 字典完全相同，直接冻结为本批共同配置。两个组使用同一个客户端实例：`JsonCandidateTransport` → `TimedRecorder(WireRecorder)` → `AttemptJournal`，顺序 A→B。

| 设置 | 两组共同值 |
|---|---|
| endpoint / 协议 | `https://leafapi.cc/v1/chat/completions` / `openai-chat-v1` |
| model / 预期返回 model | `gpt-6.1-sol` / `gpt-6.1-sol` |
| stream / include_usage | true / true |
| max_tokens | 8192 |
| temperature / reasoning_effort / thinking | null；均沿原规则不向 payload 增加相应参数 |
| 连接 / 读取 / 总超时 | 10 / 240 / 300 秒 |
| 鉴权 | 同一个显式指定的本地凭证文件及 `LEAFAPI_API_KEY`；未读取凭证内容 |

新文件 `tools/t1_d2_prompt_ab.py` 负责独立身份、来源核验、双组顺序、授权、失败分流、恢复与 A/B 结果导出；复用已有预算、传输、wire 保存及 U 静态解析，不创建 API 客户端或演化框架。

公共文件 `code/fjsp_usage/research_real/real_transport.py` 仅增加观测：允许名单内的 HTTP Content-Type、已解析 data 事件数、stop/usage/DONE、完整文本标志及 id/model 校验状态。失败记录仍保存脱敏结构与身份变化哈希；不保存认证头或全部原始网络帧，不伪称取得失败后的完整流。事件数包含 DONE，不计 SSE 注释；失败时仅代表已解析前缀。

`TimedRecorder` 记录发送确认回调时间，结束时间及耗时来自尝试记录；发送确认时间不是精确的网卡发包时间。中断恢复后无法认证的时间保留 null。网关追踪号只从现有允许名单提取。

观测版本为 `paired-stream-observation-d2-v1`，纳入新客户端身份和协议。流内 `id/model` 严格一致性、stop、usage、DONE 和原有限制均保留。对照原 T1 提交 `2eaabe09` 的解码器，在正常、id/model 改变、错误帧、截断和非 JSON 样例上的接受／拒绝及异常消息一致。新增元数据不改变请求生成参数。

旧 B1/B2/D1 的冻结代码哈希不会被改成新值；其协议在当前新代码上拒绝身份失配是预期保护，复现应使用其原提交。本轮未修改旧入口、科研评价、Prompt、H/U 或冻结文件。

配置复用 `ExperimentConfig` 的序列化结构，其中未被本入口调用的种群、代数等默认字段不构成实际任务。本入口只执行 A/B 两个逻辑任务，不加载搜索或求解流程。

## 4. 预算、失败与恢复规则

最多 2 个逻辑任务、2 次尝试、每任务 1 次，退避列表为空。A、B 的请求 ID 不同，均只有 `attempt/01`。同一组非法 U、失败或缺少响应都不会补发。

| 情况 | 后续处理 |
|---|---|
| 已确认发送并已持久化的普通 HTTP200 SSE 解析／协议失败，包括流内 id 改变 | 保留该组失败，执行另一个尚未发送组；严格拒绝错误流，不吞错误帧 |
| 明确 HTTP429/502/503/504 最终失败 | 保留失败，允许另一组；不重试本组 |
| 完整响应但 U 静态输出不合法 | 传输成功、输出不合法分开记录，允许另一组；不重试 |
| 鉴权、明确额度／模型／参数错误 | 全局停止，不发送另一组 |
| 明确返回 model 与锁定模型不符、Prompt／代码／协议身份失配 | 全局停止 |
| pending、发送状态未知、未确认发送或未分类安全异常 | 保守全局停止，占用已预留尝试，不退还额度 |
| 两组均已观察完毕 | completed；不代表传输或程序通过 |

普通失败后执行另一组是取得另一份配对观察，**不是失败任务重试**。新版预算熔断阈值在本新协议设为 2，使第一份普通 SSE 失败不提前阻断对照；第二份连续失败可打开熔断，但此时两组已完成观察。不修改、清除或追溯应用旧 D1 的阈值 1。

固定 A→B，同一配对窗口最多 900 秒，从首次检查点开始计算；两次 300 秒总超时正常可容纳于此窗口。窗口内恢复只处理尚未完成组，超窗停止新增请求，不另开窗口。没有创建跨批次全局锁，CLI 复用已有本目录 `RunLock`；直接绕过 CLI 的多进程并发不是受支持用法。

每次请求之前先保存 inflight 与预算预留。已完整保存 wire 的响应恢复后不重发；中断未明按 v2 保守占用尝试并停止。已落盘的全局失败不能因中断恢复丢失。缺失账本、孤立账本、Mock 冒充真实运行、路径拷贝或跨目录软链接均拒绝；没有自动重置或额度恢复。

## 5. 输出与离线验收

运行时保存 `requests/attempts.json`、`wire_responses/`、`send_times/`、完整成功响应 `responses/A.txt` / `B.txt`、checkpoint/status。导出 `AB_result.json` 和 `AB_result.csv`，逐组记录 ID、时间、HTTP／Content-Type／网关号、事件数、身份变化、完整性标志、token、费用及准确失败阶段。失败尚未获得的信息保持 null。

U 输出只做已有受限语言 AST／基本输出契约校验；不执行 U，不以此证明所有状态下运行合法，不要求两份 AST 不同。报告分别判断传输通过、完整输出取得、静态输出合法；不计算 Fitness。

测试命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python -B -m unittest \
  test_t1_d2_prompt_ab test_t1_stream_reliability test_chat_stream_transport -q
```

结果：**66 项通过**（D2 专项 27、既有 T1 35、既有流传输 4）。包括四种 A/B 成败排列、普通失败继续另一组、全局停止、上限、未知发送、wire 已存未接受的恢复、已完成不重发、两组同 AST、身份变化、窗口过期、授权隔离、配置 payload 对照和原 T1 接受集合样例对照。测试将网络、凭证、账户、账单、数据加载、评价和候选执行入口设为禁止；原流传输测试仅使用本机合成服务。

旧 B2、B1、D1 三个明确目录共 189 个既存文件逐一核对 SHA256 与 mtime_ns，全部不变；没有新增旧目录文件。索引见 [Historical_immutability.json](../reports/t1-d2a-b2-b1-prompt-ab-v1-20261022/Historical_immutability.json)。没有扫描其他历史实验或访问 train21、validation11、test28。

## 6. T1-D2B 启动条件、命令与限制

本轮只执行过 `prepare` 和 `check`。正式调用尚需用户对 **本协议 SHA256** 的新授权，并接受最多两次尝试可能产生而目前无法精确预估的费用风险。授权后据实创建本目录 `Authorization.json`，内容满足已冻结模板；旧 D1/B1 授权及剩余额度无效。不查询账户、价格或账单，费用保持 null，没有可执行的人民币硬上限；8192 是输出 token 上限，不是金额上限。

在仓库根目录，以下两条仅离线检查：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/t1_d2_prompt_ab.py check \
  --run-dir runs/t1-d2-b2-b1-prompt-ab-v1-20261022
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/t1_d2_prompt_ab.py status \
  --run-dir runs/t1-d2-b2-b1-prompt-ab-v1-20261022
```

以下命令会真实发送，仅在 T1-D2B 明确授权并登记后执行；本轮未执行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/t1_d2_prompt_ab.py run \
  --run-dir runs/t1-d2-b2-b1-prompt-ab-v1-20261022 \
  --env-file ../FJSP-Heuristic-Research/.env.leafapi.local
```

同一命令用于窗口内安全恢复，不保证可继续：终态、未知发送或超窗会停止，无额外请求。结束后 `report --run-dir` 只读取本批持久化记录并生成表格，不重放响应、不请求、不求解。

两组新请求共享当前窗口、客户端、参数和凭证，但固定顺序仍存在时间／网关路由混杂。一次一对只能提供传输成败观察，不能估计稳定成功率，不能单独证明 Prompt 长度导致故障，也不能说明不同 U 的排程质量。本阶段没有启动任何新的 B1 实验。
