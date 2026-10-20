# B2-0.1：独立批次预算与有限重试

仅工程修改与离线Mock验收。真实LeafAPI调用、账户/价格/账单查询、新FJSP训练评价均为0；未执行16个网格点，未进入B2-1。

新身份：`H01-alpha-search-seed501-batch-retry-v3-20261020`。
新目录：`runs/h01-state-weight-search-seed501-batch-v3-20261020/`。
原B2-0、旧H01准备与其证据均不覆盖。原科研协议仍为`H01-alpha-search-seed501-v1-20261019`。

## 工程职责

| 文件 | 改动 |
|---|---|
| `research_real/attempt_budget.py` | 新版本显式启用的双层持久日志、有限重试、首份响应选择及恢复；不含HTTP客户端或历史盘点 |
| `research_real/budget.py` | 仅识别新预算声明；旧BudgetLedger拒绝误用新声明，旧模式仍不自动重试 |
| `research_real/real_transport.py` | 原单次HTTP/SSE客户端增加网络失败类型证据；客户端本身仍单次发送，生成参数和有效响应判据不变 |
| `usage_v2/access.py` | 原WireRecorder在失败记录中保留异常类型，支持崩溃后的分类恢复 |
| `usage_v2/fixed_h.py` / `research_real/conditional_research.py` | 仅新模式按固定哈希读取H及祖先资产，不再观察来源目录的旧writer锁；全部来源、审查、收据和身份核验保留，旧模式默认仍检查原锁 |
| `tools/h01_weight_local.py` | 显式新准备身份；新分支不调用历史计数、inventory、peer交接或全局调用权检查；替换请求日志，复用原WeightSearch与Search |
| `tools/h01_weight_report.py` | 分别导出逻辑候选和API尝试；关联响应、源码键、评价与存活；费用为null |
| `tests/test_h01_attempt_retries.py` | 合成响应、虚构成绩及127.0.0.1模拟服务；不使用真实模型、实例求解或种群 |

## 固定预算与状态转换

新`request_budget.version=batch-api-attempts-v1`，仅该身份启用：

```json
{
  "logical_candidate_cap": 20,
  "api_attempt_cap": 30,
  "per_candidate_attempt_cap": 3,
  "retry_backoff_seconds": [2, 5]
}
```

配置中的原`total_request_cap=20`和阶段20槽继续指**逻辑候选**，不再代表物理发送次数；真实API尝试由独立30上限约束。保留这些搜索字段是为了不改变两代各10槽的算法。旧BudgetLedger不能处理新声明，防止将两个计数混用。

逻辑候选`B/g0000/000000`对应API键`r501/B/B/g0000/000000/attempt/01`等；成功完整响应另有本地`.../response`身份，并保留供应商响应ID（若提供）。源码与评价继续使用唯一逻辑候选ID。

| 状态 | 后续动作 |
|---|---|
| 新逻辑任务 | 固定原Prompt，先检查20/30额度，持久保存逻辑任务和尝试预留 |
| 临时连接失败、超时或429/502/503/504 | 记录失败及usage；尚有本候选及本批额度时，等待2秒/5秒后以新尝试ID重试原Prompt |
| 已发送但进程中断，状态未知 | 原尝试照计；先检查已保存wire响应；无完整响应时可在剩余额度内重试，明确有重复计费风险 |
| 第一份完整响应保存成功 | 立即固定该响应，结束此逻辑任务的API流程，不比较不同响应fitness |
| 完整响应代码非法、重复、排程无效或超时 | 原搜索照常记录失败/重复，不再调用API |
| 单候选3次临时失败 | 此逻辑候选失败，继续本批其他槽位 |
| 总API尝试达到30 | 停止新增逻辑任务/发送，保留已有检查点，不补额 |
| 20个逻辑候选处理完成 | 结束，不因API预算有余而追加候选 |

明确鉴权、余额/配额、模型或参数错误不重试，并暂停后续发送以免重复消耗其他槽位；未分类错误默认不重试。未增加任何账户探测或财务结算。

尝试在发送前落盘，因此极窄的“预留后、真正发送前”崩溃也保守计一次。报告同时保留`send_confirmed`，不把所有预留都声称为已确认供应商收件。无法证明的耗时、Token和费用保持未知。

## 响应与中断恢复

同一批次的权威API日志位于`r501/B/budgeted_evolution_requests.json`：`requests`按逻辑ID索引，`api_attempts`按尝试ID索引。原WireRecorder按尝试ID保存完整归一化响应，先于解析和评价。

- 完整wire响应已保存、但逻辑日志未提交：恢复首份完整响应，不发送第二次。
- 响应已接受：以后只解析/恢复评价，API不重发。
- 评价结果已保存、但候选尚未提交：复用评价缓存，不重评。
- 评价本身中断且结果未知：保持原规则记无效，不额外重评。
- 失败及不确定尝试均跨重启计数；源ID、Prompt哈希或批次身份不一致拒绝恢复。
- 尝试记录损坏、孤立、重复或超限时拒绝，不清空日志重新计数。

旧协议仍使用原单发日志；新重试不会追溯应用到旧实验。供应商幂等去重未启用，超时后的重试可能重复计费，费用仍为unknown/null。

## 历史和并行边界

新模式无`history_source`或`lifetime_request_cap`，不检查旧300槽、不盘点其他worktree调用权、不要求旧30/60批次完成或结算。旧历史文件和财务预留不删除、不释放；H来源审计仍核验原合法收据及冻结资产，不把其历史费用作为新发送门禁。

原H读取器中历史资产来源目录的writer判断也只在新协议关闭；各文件仍必须逐字节匹配预先固定的哈希，因此来源锁存在不阻断读取，任何被改写、缺失或不合法的资产仍拒绝。没有为省略锁而省略H合法性审查。

保留的是B2-0**已有的本运行目录**`RunLock`，没有新增锁、全局锁或跨实验锁。通过正式CLI，同一目录的第二进程会被原O_EXCL写入保护拒绝；其他运行目录的锁不参与本批放行。

底层日志另能识别已观察到的旧revision写入，但这不是原子并发协议。绕过CLI/RunLock直接并发操作Search或AttemptJournal，仍可能发生竞争；不保证安全，不支持多人/多进程并行处理同一实验。不同批次日志独立绑定目录和协议。

## 科研冻结与执行门禁

H、编号、七状态、H0/H1互补权重、语言、min–max和历史规则、21train、完整fitness、共享15秒、手工五初始U、seed501/N5/两代及算子、父代与生存选择、模型参数和原Prompt均保持不变。Prompt逐字节核对，无父代fitness反馈。

只有`BatchWeightSearch`的请求日志替换；跨代更新、解析、去重和评价继续调用原实现。重试不会占据新的交叉/变异槽位，也不从多个响应中择优。

纯离线准备/检查（本阶段已执行）：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. \
  .venv/bin/python -B tools/h01_weight_local.py prepare --batch-retries
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. \
  .venv/bin/python -B tools/h01_weight_local.py check \
  --run-dir runs/h01-state-weight-search-seed501-batch-v3-20261020
```

`prepare`不得对已有目录重复执行；没有自动迁移或恢复旧准备。`check`只读本地科学身份与缓存，不请求API或求解FJSP。

新配置仍为`real_requests_authorized=false`。未来只有用户明确确认B2-1后，才登记绑定最终Plan SHA的`B2_1_authorization.json`，字段为`stage=B2-1, approved=true, person=DDXQL, logical_candidate_cap=20, api_attempt_cap=30, per_candidate_attempt_cap=3`及`plan_sha256`。本阶段不创建该文件。

授权后才允许同一专用入口`grid`→`search`→`report`；`search`需要既有凭证路径。复用5个固定点，其余16个静态点及最多20个模型候选评价保持原上限36次完整21train。API重试不增加可评价候选数。本阶段不执行这些阶段。

## 离线证据

`docs/usage-space/h01-b201-prepared/`保存新配置、Plan、原Prompt快照、测试记录和历史不可变证据。所有Mock候选与虚构成绩只存临时目录，测试日志明确标记，不属于科研结果。

本次测试涵盖首次成功、超时后成功、三次失败、HTTP临时故障、永久错误、非法/重复代码、评价失败、20/30/3上限、未知发送/孤立预留/完整wire响应恢复、已完成评价复用、两代继承、批次隔离、旧入口仍单发及全局门禁不被调用。

共72项不同检查通过：主环境71项通过、1项绘图依赖跳过；该绘图项在文档运行环境单独通过。其中新增重试检查23项。旧H01、B2-0准备及B2-0归档的87个文件逐项核对SHA256与修改时间，均未改变。最终CLI核验为`engineering ready; B2-1 remains unauthorized`。新目录仍只有复用的5个静态评价结果，没有请求日志、执行checkpoint、网格完成标记或B2-1授权文件。

完成B2-0.1后停止，等待B2-1正式执行授权。
