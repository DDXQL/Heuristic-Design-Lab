# Tier2 Research Offline v1

这是独立的新研究版本，保持 Tier1 和已有 v1/v2 文件不变。
提供解析、受限执行、事件、H 适配、四组 U 演化流程及恢复；入口只使用手写模拟响应，
没有真实 LLM、正式 H、验证集选择或测试集研究结果。

## 运行

在项目根目录运行，使用现有虚拟环境：

```bash
.venv/bin/python experiments/tier2/research_v1/run_offline.py \
  --suite tiny --run-dir runs/research_tiny
.venv/bin/python experiments/tier2/research_v1/watch_progress.py runs/research_tiny
```

打开 `runs/research_tiny/replay.html` 即可逐步查看真实微型排程，不需要服务、联网或 LLM。
`report.json` 是完整结果；`events.jsonl` 是简洁阶段记录；各组目录有候选事件、
请求日志及 `checkpoint.json`。这些运行文件都在 Git 忽略的 `runs/` 内。

已有本地 train 文件时：

```bash
.venv/bin/python experiments/tier2/research_v1/run_offline.py \
  --suite train --run-dir runs/research_train
```

仅加载并核验 manifest 中的 train，validation/test 只检查 split 文件名，不打开数据文件。
每个有效候选必须完成全部 train；任一失败使整体 fitness 为 null，不能对子集求均值。

恢复原命令加 `--resume`；源文件、数据、H、预算或配置有变化时拒绝恢复，需要新运行目录。
已完成运行再恢复不会再次请求或评价候选。中断期间结果不确定的请求/评价记为无效，
保守消耗预算，不自动重试。不支持并发写同一运行目录。

## 协议

U 的七个输入来自未修改的 v2 状态摘要；每步只调用一次 U，严格拒绝 bool、非 int、
越界或异常。h 只接收原始量纲的七个单动作输入。最高分及稳定平分顺序保持原协议。
V5 LB 的总工作量项不取整；不能与冻结 Tier1 的历史归一化分数混用。

共享初始化不提供 H 代码或行为，最多 5N 次模拟请求收集 N 个代码不同的有效 U。
四组使用同一初始种群和 EFT/SPT 演示 H。B0/B1 使用 E1/E2/M1/M2/M3；B1 提供 H；
B2 提供 H 加通用交叉/变异；P 使用 V5 特化交叉/变异。
五算子依据 [EoH 原文第 3.4 节](https://arxiv.org/html/2401.02051v3)；
本版本的提示是针对 U 的迁移，并非复制原问题的完整提示。I1 是初始化。

一代父代固定；排名权重 1/(N+r)，多父代无放回；合并父代与有效子代取前 N，
同分按稳定候选 ID。失败和重复照常占用请求/尝试；不补生成。
每代尝试数要求为 10 的倍数，保证五算子各 1/5、两算子各 1/2。
开发默认 N=5、两代、每代10次，不能视为正式配置或批准的付费预算。

H 适配器重实现审计过的 EoH-S 互补生存及父代选择机制，保留完整 train 分数向量，
单独导出 `mock_H.json`，成员不足 K 则失败。它不是上游线程调度器的完整复现，
也没有产生正式 EoH-S 集合。来源 commit/工作文件哈希及差异见 `source_audit.json`。
导出的自然语言说明尚待行为审查，`behavior_reviewed=false`，不能当正式已验证说明。

## 执行限制与记录

生成代码必须通过精确接口和纯数值 AST 检查。禁止 import、属性、容器、辅助函数、
递归、globals/nonlocal、动态执行和外部资源；仅允许有限数值运算及指定内建函数。
中间数值幅度上限 1e100；无限循环由父进程实际终止。这是受限语言执行器，
不能当作任意 Python 的操作系统沙箱。真实模型提示也必须共享这一语言约束。

每个实例在子进程完成两次全排程以核对确定性；超时含这两次执行，首实例含进程启动。
调用日志的 pending 预留可能未真正发出，因此报告称“请求槽位”；真实供应商的请求和
token 尚未采集，mock token 为 null，不能以字符数冒充 token 或费用。
默认只存候选/代际摘要；三步微型实例记录全部动作。HTML 不触发模型请求，不自动刷新。

## 验证

```bash
PYTHONPATH=code .venv/bin/python -m unittest discover -s tests -v
```

测试覆盖 U 调用契约、记录开关一致性、编号、纯数值限制、无限循环、全批次失效、
同分不同代码、预算、冻结父代、无放回权重、提示边界、互补选择和中断恢复。
正式运行仍需真实 provider 适配、模型与预算、H 行为审查、规模与重复数、锁定配置。
