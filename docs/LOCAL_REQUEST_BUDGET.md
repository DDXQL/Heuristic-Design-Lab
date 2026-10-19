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

此次没有新增冻结H的迁移/重新封装流程，也不跳过原`h_asset`及收据检查。`local-preflight`通过只说明预算入口可用，不能据此宣称固定H资产及整个新实验已经就绪。实际initialize/search仍需独立新协议下合规绑定的H及原有其他资产。旧`prepare`仍是原条件H准备流程，不接受本轻量配置。

**未迁移入口：**`run_registered_v22.py`、`run_registered_gpt61_v22.py`的历史专用登记CLI，以及`tools/h01_weight_search.py`。它们保持原登记、交接及财务门禁；本次不恢复这些入口下的任何暂停实验。`usage_v2/billing.py`已核对但无需修改：新模式不调用它，旧模式继续保留。

## 离线验证

新增`tests/test_local_request_budget.py`复用参考提交的12项测试，并增加3项SELECT/MIX客户端、科研参数/提示及CLI贯通检查，共15项通过。所有新请求测试使用手写响应和临时目录，真实网络、账户/账单包装器和旧串行财务门禁被替换为“调用即报错”。测试还逐字节及mtime核对历史夹具账本、未知预留与检查点未改。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. \
  .venv/bin/python -m unittest test_local_request_budget
```

另运行既有SELECT/MIX执行、工作流、注册、账单、响应记录、公共工作流和传输的相关离线回归测试，65项通过，与新增15项合计80项。它们使用原有单元夹具和本机HTTP服务，不连接真实LeafAPI、不使用真实训练/验证/测试集。

本次没有修改历史运行目录、账本、候选、检查点或另一工作区，没有恢复实验、查询真实账户或发送真实模型请求。
