# B1-NS-A：完整10H自由发现非流式工程验收

2026-10-22，`codex/h-usage-space`。**工程与离线验收PASS，协议已冻结；尚无正式API或训练授权。** 本阶段使用 `ahd-experiment-copilot`，真实API请求0、正式FJSP评价0、凭证读取0；所有新增搜索结果均为显式标记的Mock。

## 1. 新身份及继承关系

- 入口：`tools/b1_nonstream_local.py`。
- 运行目录：`runs/b1-ns-full-h-free-seed501-k2-v1-20261022/`。
- 协议版本：`B1-NS-full-H-free-seed501-k2-v1-20261022`。
- 协议SHA256：`94381988c5536bd19f72aa0cbcdcafc7dfc1b8a4ece7b18fcbd71ad0b4a90083`。
- 科研基线为旧B1-1C，原协议SHA256 `d5ec72d53583c8dd5829b6a9d8f002511956c346127aad99348e1485f8e3e898`。旧运行不续跑、不复制其账本或剩余额度。
- 新目录只有准备输入、Prompt预览、原H绑定、协议和未批准模板，无正式P0、请求账本、授权或运行检查点。
- 可提交备份：[prepared](../reports/b1-ns-a-engineering-v1-20261022/prepared/)、[离线验收](../reports/b1-ns-a-engineering-v1-20261022/Offline_acceptance.json)、[参数差异](../reports/b1-ns-a-engineering-v1-20261022/Parameter_diff.json)。备份绑定原绝对运行路径，不能直接另起一批。

原10H来源仍为 `runs/v22-gpt61-select-mix-301-20261014-v1/` 的原冻结资产。继续通过 `fixed_h.source_h()` 检查原来源、编号、代码键、原审查、原回执、数据与评价核心；没有生成H或伪造新技术审查。新 `H_source_binding.json` 与旧B1绑定完全相同。准备／check只读取21train文件字节做哈希和既有H数值样本审查，不加载训练实例排程；manifest中的holdout名单及哈希仅作为原身份元数据，不读取validation11/test28实例内容。

首份初始化请求完整字节仍为21,250，SHA256 `7307e5fd4d2d781ee0c546e809c5c3f1d0d694eec2915f9c1bc688a5ab68833e`。它由原Prompt函数和空种群生成后，与旧 `B/init/000000` 保存文本逐字节比对；CROSS／MUTATE预览直接复用旧字节，实际调用仍由未改的Prompt函数按当代父代构建。T1-D4B正文、代码和任何旧U均未导入P0。

## 2. 新旧参数差异

| 项目 | 旧B1-1C | 新B1-NS |
|---|---|---|
| H、七状态、U语言、SELECT/MIX | 原10H，最多两正MIX权重 | 完全继承 |
| INIT／CROSS／MUTATE语义 | 原B1自由发现，无显式Fitness反馈 | 不变，Prompt源码／原始模板哈希一致 |
| P0／父代 | 自由P0=5；CROSS=2，MUTATE=1 | 不变，无人工或诊断种子 |
| seed／代数／每代 | 501／2／5 CROSS＋5 MUTATE | 不变 |
| 初始化上限／全批逻辑任务 | 20／40 | 不变；凑齐5个完整有效且AST不同的U即结束初始化 |
| API尝试／单任务／退避 | 60／3／2、5秒 | 不变；非法、重复、评价失败不触发请求重试 |
| 模型／endpoint／输出 | gpt-6.1-sol／LeafAPI原endpoint／8192 | 不变 |
| connect-read-total | 10-240-300秒 | 不变，不自动延长 |
| stream／stream_options | true／include_usage=true | **false／省略字段** |
| 请求预算版本 | batch-api-attempts-v1 | **batch-api-attempts-v2-t1** |
| 传输协议异常熔断 | 无新版熔断 | **连续3次暂停，无自动清除／续跑** |
| 中断后发送未知 | 旧v1恢复语义 | **保守占用尝试并停止，不自动重试未知发送** |
| 响应完整性 | 原公共解析路径 | 保持公共解析，另明确非空id、锁定model、stop及有效usage |
| 请求凭证前缀 | r501/B | 新版本命名空间，账本身份和目录亦独立 |
| 数据／Fitness／评价期限 | 21train；完整平均−Cmax/LB；首次与复检共享15秒 | 完全继承，无新增观察回放 |
| 父代抽取／生存／代际更新 | 按原Fitness排名赋权无放回；代内冻结；代末父子合并取前5 | 完全继承 |

所有其他配置字段严格与冻结B1相等；更换H、模型、输出上限、期限、seed、父代数或代数均被拒绝。预算／中断保护为显式工程版本变化，可能提前停止故障批次并减少实际调用，不能将其影响归因于搜索空间。原外部Fitness、合法程序集及执行器没有变化。

## 3. 代码范围与新预算安全

| 文件 | 职责 |
|---|---|
| `tools/b1_nonstream_local.py`（新增） | 严格继承配置、原来源核验、新冻结身份／授权、非流式完整性证据薄适配、共享账本、训练评价边界和报告 |
| `tools/b1_usage_local.py`（仅3行diff） | 将原固定请求前缀暴露为类属性；旧默认仍是r501/B，新NS子类覆写；不改变抽样、Prompt、评价或生存 |
| `tests/test_b1_nonstream_local.py`（新增） | 合成响应／21行Mock成绩、真实入口依赖注入、预算和恢复等验收 |
| 本报告及派生目录 | 冻结准备副本、差异、测试、Mock谱系和历史保护证据 |

没有修改公共API客户端、预算实现、调度器或评价器。与旧B1的230项冻结输入相比，先前T1已更新的4项文件为 `attempt_budget.py`、`budget.py`、`real_transport.py`、`usage_v2/access.py`；本次另有B1薄适配器前缀变化，共5项工程重绑定，逐项旧／新SHA见 [Engineering_rebind.json](../reports/b1-ns-a-engineering-v1-20261022/prepared/Engineering_rebind.json)。其他旧冻结输入严格核对，未为通过检查修改旧哈希。旧入口在当前代码上出现冻结哈希不符应拒绝；其原版本复现使用原提交。

仍由公共 `JsonCandidateTransport` 发HTTP，NS薄适配不构建第二套HTTP客户端。完整规范化回复优先存 `received_responses/`，之后才检查id/model/stop/usage；`WireRecorder`保存成功／失败／未知wire。Prompt、尝试ID、usage、时间、错误、源码及谱系随共享 `r501/B/batch_requests.json`、checkpoint、原始回复和事件日志持久化。

非流式响应是一个JSON，不使用SSE DONE或跨帧id规则。模型不符在当前候选失败检查点持久化后立即停止。HTTP200下的明确JSON／完整性协议错误不重试，累计至3次熔断；复用v2-T1计数器，其历史字段名仍为 `stream_protocol_anomaly`，同时记录 `protocol_kind=nonstream_json`，不能据该旧字段名报告发生了SSE事件。已有明确临时／永久错误类别保留，不吞上游错误；临时连接／超时或允许的服务错误仍仅在3／60上限内重试。

未知费用不构成虚假的零费用或可用余额；不查询账户、价格或账单，不依赖旧全局300槽位或跨工作区调用锁。唯一尝试账本贯通初始化与两代，重启不能重置。CLI沿用单目录RunLock及账本版本冲突保护；不支持绕过CLI的并发多写者，也不声称供应商侧exactly-once。

## 4. 离线验收及历史保护

**123项检查通过**：NS专项22、原B1专项18、原有限重试23、T1公共可靠性35、D4非流式22，以及3项纯向量SELECT／MIX计分检查。所有新U和Fitness均来自Mock，原重试报告测试打印的“网格冠军”等字段也是合成结果。

重点覆盖：

- 空P0自由生成，合法性／AST去重后才评价；缺说明标记的类似D4响应失败，不修复、不种入P0。
- 完整Mock 5初始化＋20演化，10次二父代CROSS、10次单父代MUTATE；每请求一子代，代内父代冻结，P1和P2更新，第二代实际继承第一代Mock子代。
- 非法／重复／完整评价失败不补请求；初始化20槽不足5则终止，失败前缀不当完整Fitness；不完整、非有限或不匹配结果不能入种群。
- 40逻辑／60实际尝试／单任务3次，2/5秒退避；协议异常熔断、锁定模型失配停止、已知usage保留和未知费用null。
- 已保存响应恢复不重发、已完成评价不重评、未知发送与预留未确认中断占用预算并停止；旧授权拒绝，跨批次签名恢复拒绝。
- 实际NS `run`／`report`入口采用假客户端、假凭证、假train21对象与假成绩贯通；严格传递train、21个有序名称、15秒、allowed_modes=(0,1)、diagnostics=false及原结果校验函数。
- 真正运行数据加载、求解、LeafAPI／账户和凭证读取在测试中禁止；生产SELECT/MIX未改，三项回归仅计算给定向量，不排程。

独立来源预检和正式prepare/check确认原10H顺序／代码／描述／审查绑定、21train身份及首份Prompt原字节，`dataset.opened=[]`，正式求解0。未批准的真实CLI也已验证在构建客户端、读取凭证和加载实例前拒绝。

受保护旧B1、B2、T1-D1（两份身份）、D2、D3、D4及H来源八个指定目录，共402个既存文件SHA256与mtime_ns全部不变，无新增／删除；详见 [Historical_immutability.json](../reports/b1-ns-a-engineering-v1-20261022/Historical_immutability.json)。没有将旧失败批次改成新运行或将D4静态代码变成合法候选。

完整日志、测试命令、Mock谱系见 [Offline_acceptance.json](../reports/b1-ns-a-engineering-v1-20261022/Offline_acceptance.json)、[Tests.log](../reports/b1-ns-a-engineering-v1-20261022/Tests.log)、[Full_mock_lineage.json](../reports/b1-ns-a-engineering-v1-20261022/Full_mock_lineage.json)。Mock只在临时目录运行，未写入正式P0。

## 5. 预算、风险与后续授权

未来真实运行最多40个逻辑候选任务、60次API尝试，每任务3次。若初始化最早5次即全部有效，完整两代为25个逻辑任务；失败与重复占槽，不能追加。最多40个合法去重候选完整训练评价，即840个候选—实例任务，成功时最多1680遍首次／复检求解；每对共享15秒，无额外全量回放。实际失败可提前结束该候选。

API总期限的名义累计上界60×300秒约5小时；受限评价部分840×15秒约3.5小时，另有有限退避、进程、审查与系统开销。这是资源边界，不是预计完成时间。实际token和费用事前未知，8192并非金额硬上限；超时也可能计费。非流式一次真实接收成功不能保证整个批次稳定，CROSS／MUTATE及较长上下文仍可能失败。

停止条件包括：初始化不足5、逻辑／尝试预算用尽、鉴权／额度／参数等永久门禁、模型身份不符、连续3次协议异常、未知发送、冻结身份不匹配及不可恢复本地错误。保留失败、检查点和预算，不自动换Prompt、加时、补员、扩额、清除熔断或开启新批次。完整响应之后的格式、代码、重复或评价失败沿原规则占逻辑槽，不是传输重试理由。

科研范围保持train21训练探索。validation11为开发暴露数据，已消费test28不能再当独立选优证据；本入口不加载这两组。未来泛化结论需要另行冻结的新独立验证。B1与B2的H空间、初始化及父代数仍有多项差异，不能单因素归因。

当前唯一未满足的启动前提是用户对本协议的新正式API＋训练授权；本次只创建 `Authorization.template.json`，没有 `B1_NS_authorization.json`。未来应先复核运行身份／独占执行进程，再据新授权登记，不从历史批准取得许可。

仅离线核验命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/b1_nonstream_local.py check \
  --run-dir runs/b1-ns-full-h-free-seed501-k2-v1-20261022
```

以下是**未来授权后**的唯一真实运行／安全恢复入口，本轮未获准执行；当前调用只会因缺授权被拒绝：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/b1_nonstream_local.py run \
  --run-dir runs/b1-ns-full-h-free-seed501-k2-v1-20261022 \
  --env-file ../FJSP-Heuristic-Research/.env.leafapi.local
```

`report --run-dir ...`仅从本批保存材料生成报告并复核输入，不请求、不求解。恢复是否允许由原账本与停止原因决定，不重置未知发送或熔断。本阶段完成后停止，未启动正式B1-NS。
