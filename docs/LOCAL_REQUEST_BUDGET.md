# 新运行的轻量请求预算

参考 `codex/u-single-experiments` 的 `f1896578045a9d876d77352bf33abac6c558d6a8`，仅移植公共预算、配置和客户端分流的必要增量。本分支复用已有 `usage_v2.registration.inventory/worktree_roots` 与 `usage_v2.access.WireRecorder`，没有复制另一分支的目录或单成员辅助模块。

## 生效条件

只有**独立的新目录和新协议身份**显式声明以下配置，才使用新模式。以下是字段示意，不是已登记配置或新的实验授权：

```json
{
  "request_budget": {
    "version": "local-request-budget-v1",
    "lifetime_request_cap": 300,
    "history_source": {
      "directory": "/absolute/path/to/predecessor-run",
      "protocol_sha256": "<该文件的真实SHA256>",
      "budget_sha256": "<该文件的真实SHA256>"
    }
  },
  "fixed_h_source": {
    "version": "usage-frozen-H-source-v1",
    "directory": "/absolute/path/to/existing-frozen-H-run",
    "files_sha256": {
      "protocol.json": "<原协议文件的真实SHA256>",
      "H_frozen.json": "<原冻结H文件的真实SHA256>",
      "Conditional_H_reassessment.json": "<条件研究H复核文件的真实SHA256>"
    }
  },
  "usage_experiment_version": "SELECT-vs-SELECT-or-MIX-local-requests-v1",
  "platform_quota_ceiling": null,
  "platform_quota_reservation": null
}
```

`usage_experiment_version`仅适用于SELECT/MIX配置；公共`ExperimentConfig`只需`request_budget`。新模式不可同时带旧`conditional_research`或开发续跑声明；不能通过编辑历史配置来转换旧实验。省略`request_budget`时保持旧配置序列化及旧机制，`None`不会新增到历史payload。

其余科研字段继续使用新实验事先批准的原值：H、U接口、Prompt、模型参数、输出token配置、状态、评价、父代与生存选择均不由该预算开关调整。SELECT/MIX原有N5/init20、A仅SELECT/B允许SELECT或MIX、单seed一代/每组10槽及总40限制仍保留。本次未修改任何具体实验配置。

## 保留与移除

- 保留单批及阶段硬上限、累计300槽位上限。前驱账本的原生槽位与已绑定历史只计一次；后续新协议沿同一链继承，不重置累计数。
- 本地工作区账本盘点仍检测其他writer、漏计账本和同身份冲突副本。历史来源只读核对`protocol.json`和`budget.json`哈希及计数，不读取账单或账户余额来放行。
- 保留唯一的运行/账本身份、请求键、完整响应、发送确认、Token usage和检查点。已完成、失败、超时、pending及孤立预留均不自动重复发送；改变同一请求的Prompt会被拒绝。
- 未知usage和费用保持未知。汇总明确`actual_cost=null`、`account_amount_limit_enforced=false`；不会声称旧未知费用已结清或历史预留已释放。
- 新客户端只走响应记录器与原模型传输，不创建余额、价格、账单或精确费用匹配包装器。普通元数据故障因此不再是新模式的暂停来源。旧财务模块继续服务旧协议。

## 覆盖入口与边界

公共`research_real.Workflow`、`UsageWorkflow`及`RegisteredUsageWorkflow.client()`的新协议分支均已适配。SELECT/MIX通用入口新增纯本地`local-preflight`：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. \
  .venv/bin/python experiments/tier2/usage_v2/run.py local-preflight \
  --run-dir runs/全新的独立目录 --config /path/to/new-config.json
```

这条命令在未来明确授权后才使用；本次没有在实际runs目录调用。它只创建新的协议、空账本及本地缓存/日志，核对本地计数，不打开实例、不创建模型客户端、不查询LeafAPI。已有目录会被拒绝。

2026-10-20补齐固定H绑定及训练报告链路。`fixed_h_source`与计数前驱`request_budget.history_source`是不同来源：H可来自更早的合规冻结目录，计数仍必须覆盖最新累计消耗。不能用H来源时间重置预算。

新增`bind-h`（轻量模式下`freeze-h`也转到同一绑定方法）。它在原协议上下文调用现有H审计器，核对数据、期限、调度/评价源码与运行环境、完整成绩、编号、审查样本和原始生成收据，再写新上下文的绑定封装。H成员行、代码、编号、审查和旧收据逐项不变，不归属于新U请求，不生成H、不重评H完整训练成绩，也不宣称进行了新的技术审查。

- 已批准的条件研究H：按上例固定三个文件；继续沿原协议的哈希链核对生成来源、原始账本/响应和用途批准。可能校验旧证据文件的哈希，不使用其账户金额或结算状态作为新预算门禁。
- 普通原生冻结H：固定`protocol.json`、`H_frozen.json`、`H_candidates.json`、`budget.json`，以及所需的`H/budgeted_initial_requests.json`/`H/budgeted_evolution_requests.json`。原生H收据必须仍由原生H生成账本和响应支持。
- 已由本新协议绑定的H：可固定其`protocol.json`与`H_frozen.json`，继续核对封装中不可变的原来源链。
- 单纯开发/续跑H不在此自动升级用途；应使用其已经批准的条件研究冻结视图。任何不符、缺失、篡改、来源自引用或审查不合法均拒绝，不静默修复。

实际运行入口仍是`experiments/tier2/usage_v2/run.py`，配置类仍是`UsageConfig`。未来得到执行授权且所有真实SHA已填好后，在同一**新目录**依次使用：

```bash
# 以下是运行顺序说明；本轮只在临时Mock目录验证，没有执行真实实验。
.venv/bin/python experiments/tier2/usage_v2/run.py local-preflight --run-dir runs/新目录 --config /path/to/new-config.json
.venv/bin/python experiments/tier2/usage_v2/run.py bind-h          --run-dir runs/新目录 --config /path/to/new-config.json
.venv/bin/python experiments/tier2/usage_v2/run.py initialize      --run-dir runs/新目录 --config /path/to/new-config.json --seed 301
.venv/bin/python experiments/tier2/usage_v2/run.py search          --run-dir runs/新目录 --config /path/to/new-config.json
.venv/bin/python experiments/tier2/usage_v2/run.py report          --run-dir runs/新目录 --config /path/to/new-config.json
```

沿用上文的`PYTHONPATH=code:tests:.`及原求解环境。`local-preflight`只验证预算；`bind-h`核验原H和审查样本，不发模型请求。`initialize`/`search`才可能发U请求，仍遵守配置授权和请求上限。`search-arm --arm A/B`同样可用。旧`prepare`仍是原条件H准备流程，不接受本轻量配置。没有绑定H时初始化会明确报错；已保存的同一新协议检查点沿原日志恢复，不重新发送或补员。

轻量模式`training_report()`读取本地请求历史和绑定H的原有完整成绩，报告中标注`reused=true`，不再调用`conditional_research.history_summary()`；旧协议保留原报告逻辑。缺失`fixed_h_source`时不新增该字段到历史payload，旧配置序列化保持原样。

**未迁移入口：**`run_registered_v22.py`、`run_registered_gpt61_v22.py`的历史专用登记CLI，以及`tools/h01_weight_search.py`。它们保持原登记、交接及财务门禁；本次不恢复这些入口下的任何暂停实验。`usage_v2/billing.py`已核对但无需修改：新模式不调用它，旧模式继续保留。

## 离线验证

2026-10-19预算分流首轮的`tests/test_local_request_budget.py`复用参考提交的12项测试，并增加3项SELECT/MIX客户端、科研参数/提示及CLI贯通检查，共15项通过。所有新请求测试使用手写响应和临时目录，真实网络、账户/账单包装器和旧串行财务门禁被替换为“调用即报错”。测试还逐字节及mtime核对历史夹具账本、未知预留与检查点未改。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. \
  .venv/bin/python -m unittest test_local_request_budget
```

首轮另运行既有SELECT/MIX执行、工作流、注册、账单、响应记录、公共工作流和传输的相关离线回归测试，65项通过，与当时新增15项合计80项。它们使用原有单元夹具和本机HTTP服务，不连接真实LeafAPI、不使用真实训练/验证/测试集。

本次没有修改历史运行目录、账本、候选、检查点或另一工作区，没有恢复实验、查询真实账户或发送真实模型请求。

补齐链路的Mock验证见`tests/test_usage_local_fixed_h.py`：直接调用上述CLI，加载人工封装的既有H夹具，初始化5条U，A运行4槽后恢复，完成A/B并输出报告；总25次Mock U发送（含一次模拟超时），再次执行不重发。候选由原评价器在临时微型夹具上进行求解和确定性复检，全部打开记录仅为train。真实LeafAPI网络、旧账单模块及旧`history_summary`均设置为“调用即失败”。原H所有文件及mtime保持不变。另验证条件研究H的原批准链，以及已重新封口/重新固定哈希但编号、审查、收据或完整成绩不合法的拒绝情况。所有夹具均为明确标记的虚构单元资料，不是新科研结果或真实人审。

2026-10-20本次核验为新增6项端到端/资产合法性测试，加49项相关预算、SELECT/MIX执行、注册、账单及旧合成工作流回归，共55项通过。公共预算模块、Prompt、演化器、执行器和评价器未修改。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. \
  .venv/bin/python -m unittest test_usage_local_fixed_h
```
