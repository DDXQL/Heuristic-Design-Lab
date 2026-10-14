# v2.2 独立训练小试就绪清单（2026-10-14）

本文为当日较早的gpt-5.6-sol离线核对快照，旧启动命令已挂起。后来获批迁移gpt-6.1-sol，当前配置、共同接入证据、预算与启动条件见[新模型阶段](H_USAGE_V22_GPT61.md)。旧未知用量及预留保留。

**离线准备已就绪；真实初始化和训练尚未开始，发送门禁仍关闭。** 本页新增模型请求为0。用户此前对本批规模及原10条H条件研究用途的授权已记录，无须重复确认。最新指令要求本轮只做离线准备；不会因单成员页停止就解除共同结算或预算门禁。

## 唯一执行者与固定范围

唯一执行者为本聊天页“梳理固定 H 的策略空间”（线程 `01a133c9-e73d-77d2-94d4-2878b821d50a`），分支 `codex/h-usage-space`，worktree `/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space`。本批不交给单成员页执行，不在两页重复运行。

| 项目 | 已核对安排 |
| --- | --- |
| 新准备目录 | `preparations/v22-select-mix-20261013-v2`；v1是较早快照，不作为最新启动依据 |
| 新配置 | `config.v22.offline.json`；registration为 `registered-v22-serial-train-20261013`，提示为v2.2。旧接口版本字段保留执行语义兼容，不恢复旧40次方案 |
| H | 相同10条，编号0—9；真实资产SHA256 `a3527deff8bfb63b0394ea2c1f4f24339f187a331eca4b0ab8dcfff6081fed3b`；保留来源、源码、编号、原审查和DDXQL研究用途确认 |
| 模型及参数 | Leaf `gpt-5.6-sol`，完整provider配置与原任务、单成员页一致；stream=true，max_output_tokens=8192，temperature/reasoning_effort/thinking均未指定 |
| 种子与种群 | seed301，N=5 |
| 共享初始化 | 新SELECT候选，只生成一次，最多20次；不足5个完整有效且去重候选则停止，两组均不启动 |
| A | 仅SELECT，一代10次：5交叉、5变异 |
| B | SELECT或MIX，一代10次：5交叉、5变异；MIX最多两个正权重，不强制组合 |
| 新请求总上限 | 20＋10＋10＝40；失败、重复占槽位，不追加补发；预算或结算门禁可以提前停止 |
| 数据和评价 | 仅21个训练实例；共享七项状态、评价、父代选择算法和生存选择算法；不使用validation/test |

`real_requests_authorized=false` 是准备配置关闭真实发送的状态；此前的人工授权另存于 `User_authorization.json`。满足启动条件后由登记入口生成本批授权配置，不能手改准备配置打开发送。

## 已就绪证据

- [本次机器核对记录](usage-space/Readiness_audit_20261014.json)：当前代码及运行环境指纹与准备protocol一致；987份来源副本及原文件一致；21个训练文件哈希一致。正式validation/test物理文件未复制、未加载。
- 准备记录已复现10条H在21个训练实例上的逐实例makespan，10条全部有效。原H行为审查保持原样，没有伪造新的技术审查。
- [已有离线测试记录](usage-space/Tests.v22-registration.log)：81项通过，14.532秒，含模式规则、行为例子、共享初始化、串行门禁、结算凭证和报告导出。本次代码未变，复核该记录及实现指纹，没有重复跑完整评价。
- 本次六份完整提示重新导出，与准备目录逐字节相同。初始化A/B完全相同；交叉、变异在相同预览父代下只有 `Permitted modes` 一行不同。分数式单选及状态相关成员对/权重明确允许；不固定阶段或决策树。
- 共享初始化的**流程**已就绪；真实 `r301/Shared_initial.json` **尚未产生**。真实调用后仅用新生成、完整训练评价通过且AST去重的5个SELECT候选封存该资产，A/B引用同一哈希。手写工程例子及提示预览父代不进入种群。

完整提示快照已保存到可随分支推送的文档目录：

| 操作 | A完整提示 | B完整提示 | 差异 |
| --- | --- | --- | --- |
| 初始化首请求 | [A.I1](usage-space/v22-prepared-prompts/A.I1.txt) | [B.I1](usage-space/v22-prepared-prompts/B.I1.txt) | [无差异](usage-space/v22-prepared-prompts/I1.diff) |
| 交叉 | [A.CROSS](usage-space/v22-prepared-prompts/A.CROSS.txt) | [B.CROSS](usage-space/v22-prepared-prompts/B.CROSS.txt) | [仅允许模式](usage-space/v22-prepared-prompts/CROSS.diff) |
| 变异 | [A.MUTATE](usage-space/v22-prepared-prompts/A.MUTATE.txt) | [B.MUTATE](usage-space/v22-prepared-prompts/B.MUTATE.txt) | [仅允许模式](usage-space/v22-prepared-prompts/MUTATE.diff) |

[提示对照与哈希](usage-space/v22-prepared-prompts/Prompt_comparison.json)注明：初始化首请求archive为空；交叉/变异使用明确标注的手写预览父代。实际后续初始化会加入已接受候选源码，演化使用真实父代，完整实际提示将随请求journal保存。目前不能导出尚未生成的真实父代。两组后续种群可能分化，父代内容随之不同；共享的是选择算法与初始资产，而非强求后续所有父代相同。

## 仍缺什么

| 条件 | 当前状态 |
| --- | --- |
| 单成员页完成或有明确停止证据 | 已有 `initialization_budget_stopped` 记录；已无writer锁 |
| 单成员页失败请求最终结算 | **未满足**。已发送1次HTTP503请求，usage未知；未找到唯一匹配新请求/模型/时间窗口的供应商凭证，account halt仍为true |
| 全局预算可继续发送 | **未满足**。未知预留继续保留；需结算后按唯一账本与实时账户状态重新检查，不能只看另一页停止 |
| 本批最终登记 | 尚未执行；等待以上门禁通过，绑定对方最终账本、结算证据及全worktree账本清单 |
| 新共享P0及A/B结果 | 等允许真实发送后生成；不属于可在本轮离线造出的证据 |

本次 `peer-status` 返回 `ready=false`，原因：`peer account settlement halt unresolved: no unique supplier receipt matching new request/model/window`。本轮未查询平台或发送推理请求，也未修改另一任务的代码、配置、账本、运行目录或锁。

槽位按三个已登记的不重叠祖先批次79，加单成员页新账本1，加本页0，当前为 **80/300**；不能把全部恢复快照直接求和。若单成员页保持停止且本页最终用满40，则120；原两批都用满的计划上界179并不代表已发送数。

已保存的账户数据为观测用量1,557,783点，原历史未知预留12,000,000点，此次单成员页未知预留12,000,000点，下一请求预留12,000,000点；保守合计37,557,783点，高于原30,000,000点边界。此为保存记录的算术，不是实时扣费认证。账户差值0不能证明供应商扣费0。只有独立、唯一匹配的凭证可解除相应账户预留；未知wire usage及token reservation仍须如实保留。

## 命令与启动条件

当前可执行的只读核对命令（已执行，不发送模型请求）：

```sh
cd '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python experiments/tier2/usage_v2/run_registered_v22.py peer-status
```

后续启动必须同时满足：对方完成或记录停止、无任何运行writer锁；HTTP503及全局结算有可靠证据且门禁已解除；绑定唯一最终账本且累计不超过300；实时账户加所有保留预留及下一请求预留不越30%边界；H、数据、实现、完整提示与复核版本一致。无需再次询问本批授权，但当前不执行下列命令，也没有自动发送任务。

条件满足后的唯一新运行目录拟定为 `runs/v22-select-mix-301-20261014-v1`（当前不存在）；只登记一次，不并行创建第二份：

```sh
cd '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python experiments/tier2/usage_v2/run_registered_v22.py register --directory runs/v22-select-mix-301-20261014-v1
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python experiments/tier2/usage_v2/run_registered_v22.py run --directory runs/v22-select-mix-301-20261014-v1
```

`register` 先核对对方终止及结算凭证，`run` 在创建客户端及每次发送前再次检查来源、外部账本和预算。普通候选失败继续占槽位；实际预算、结算或资产门禁停止后，不开新目录补发，不自动重置累计预算。报告包含全部训练逐实例成绩、种群变化、生成率/重复/失败、实际SELECT/MIX及双成员行为、token、可认证扣费、求解时间和h调用数；未生成的结果与未知费用不写成0。

本轮只新增核对记录、清单和已有完整提示的文档副本；执行器、提示源文件、实验配置和冻结资产均未改动。没有新增乘积、最大值等组合运算。训练小试仍只能检验本批候选和训练表现，不能证明泛化或组合收益。
