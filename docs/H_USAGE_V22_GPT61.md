# v2.2 独立训练小试：Leaf gpt-6.1-sol

DDXQL于2026-10-14明确批准本页后续实验统一迁移为Leaf `gpt-6.1-sol`，与单成员页共用模型及生成参数。该授权覆盖本次准备、满足共同条件后的登记和执行，无须再次申请同一批次。旧gpt-5.6-sol及旧40次方案继续挂起；旧503、未知用量、账户预留和累计槽位原样保留。

唯一执行者为“梳理固定 H 的策略空间”聊天页，分支 `codex/h-usage-space`，worktree `/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space`。另一页独占共同诊断及单成员生成；两页只并行准备，真实请求串行。本页入口没有诊断阶段。

## 固定登记

| 项目 | 本批安排 |
| --- | --- |
| 最新离线准备 | `preparations/v22-gpt61-select-mix-20261014-v2`；v1为较早实现快照 |
| 新配置快照 | [config.gpt61.offline.json](usage-space/gpt61-prepared/config.gpt61.offline.json)，dispatch=false；最终登记单独生成授权配置 |
| 新运行目录 | `runs/v22-gpt61-select-mix-301-20261014-v1`，尚未创建，只登记一次 |
| H | 同10条，编号0—9；来源资产SHA256 `a3527deff8bfb63b0394ea2c1f4f24339f187a331eca4b0ab8dcfff6081fed3b`；原源码、编号、审查、研究用途确认保持 |
| 模型 | `gpt-6.1-sol`，expected_response_model同名；相对原共同provider仅改变这两个字段，完整参数登记后再次与对方协议比较 |
| 参数 | stream=true，max_output_tokens=8192；temperature/reasoning_effort/thinking均未指定；其余见完整配置 |
| 初始化 | seed301，N=5；新共享SELECT候选，最多20次；不足5个完整有效且去重候选则结束 |
| A / B | A仅SELECT；B允许SELECT/MIX、最多2个正权重；各一代10次，5交叉＋5变异 |
| 上限 | 本页最多40次新增生成；失败和重复占槽位，不补发；预算/结算门禁可提前停止 |
| 评价 | 仅21train，原15秒实例期限；状态、执行器、父代选择和生存选择保持；无validation/test、新种子或新组合运算 |

[用途与阶段授权](usage-space/gpt61-prepared/User_authorization.json)单独保存。离线配置关闭dispatch不撤销已给予的授权。共同初始资产只产生一次，两组绑定同一哈希；目前本页真实P0尚未生成，手写工程例子不导入种群。

## 完整提示和组间差异

| 操作 | A | B | 差异 |
| --- | --- | --- | --- |
| 初始化首请求 | [A.I1](usage-space/gpt61-prepared/prompts/A.I1.txt) | [B.I1](usage-space/gpt61-prepared/prompts/B.I1.txt) | 完全相同 |
| 交叉 | [A.CROSS](usage-space/gpt61-prepared/prompts/A.CROSS.txt) | [B.CROSS](usage-space/gpt61-prepared/prompts/B.CROSS.txt) | [仅允许模式](usage-space/gpt61-prepared/prompts/CROSS.diff) |
| 变异 | [A.MUTATE](usage-space/gpt61-prepared/prompts/A.MUTATE.txt) | [B.MUTATE](usage-space/gpt61-prepared/prompts/B.MUTATE.txt) | [仅允许模式](usage-space/gpt61-prepared/prompts/MUTATE.diff) |

新模型版本独立封存这些完整文本及[提示清单/哈希](usage-space/gpt61-prepared/prompts/Prompt_comparison.json)。提示内容仍为v2.2策略空间语义；模型更换本身不要求改写策略任务。初始化无H行为/成绩，后续有同一H源码与原行为说明；评分单选、状态相关支持集及权重合法，不要求固定阶段、分支骨架或B使用组合。MIX权重与h动作分数、SELECT成员分数分别说明。

交叉/变异快照使用明确标注的手写预览父代，仅供检查文本，不进入种群。真实父代尚未生成，后续完整实际提示保存到请求journal。组间种群分化后父代内容可能不同，允许模式仍是本次主要制度差异。

## 迁移及预算适配

历史H是条件研究的固定资产，生成U的模型迁移不能改写H来源。本页新增显式模型迁移绑定：原provider、目标provider、确认人、原H资产SHA及共同风险策略逐一核对。未记录迁移或改变额外生成参数仍被拒绝。历史费用核对始终按每笔历史协议的原模型匹配凭证，避免新模型名称让旧结算证据失效。

本页使用单成员页保存的实际[新模型公开计费快照](usage-space/gpt61-prepared/common_preflight/pricing.json)、[平台单位说明](usage-space/gpt61-prepared/common_preflight/status.json)和[模型列表检查](usage-space/gpt61-prepared/common_preflight/models.json)。公开配置的分组为 `codex-deafult`、倍率0.5；单位换算500000，分层表达式绑定于配置。共同工程预留取输入单价保守系数5、输出15，输入包络 `max(65536, UTF8提示字节数+4096)`、输出包络32768，额外安全系数2，向上取整到1000点。每次根据实际完整提示计算；若结果超过登记的1000000点单次上限，停止，不截断预留。

当前导出的初始化/交叉/变异提示均得到410000点的工程预留。该包络不是供应商硬上限或实际账单；运行时复查当前模型/分组/费率及账户，实际扣费超过预留或账户边界立即停止。未知token reservation另行保留，不把它改成已知usage。

旧两笔未知请求共24000000点账户占用不重新定价、不清零。基数为历史80槽位，共同诊断≤1、单成员正式生成≤60、本页≤40，总计划上界181/300；真实累计按不重叠历史批次与新模型唯一账本核对。单成员页的诊断和生成在同一个cap61账本，本页历史只加入该账本一次，不能额外再加诊断一次。复制账本仅为只读证据，不恢复额度。

## 当前证据与启动条件

共同诊断已成功且独立核对：响应模型 `gpt-6.1-sol`，输入14、输出5 token，实际扣费20平台点；供应商请求ID与账单及账户差值匹配，响应是OK，candidate=false。本页没有重复诊断；该证据不证明候选合法性或方法收益。

单成员页新批次为 `single-ID-gpt61-paired-training-20261014-v1`，现已STOPPED并释放运行锁，最终账本7槽位（1诊断＋6初始化请求），未完成共享初始化。其最后账户门禁仍为halted=true，原因 `supplier billing metadata unavailable; no settlement inferred`。这属于共同结算阻碍，不能用诊断成功或“初始化不足”绕过。本页新增请求仍为0、真实运行目录未创建。当前唯一累计为80＋7＝87/300；新模型失败请求中的未知usage以及原2400万点占用均保留。

新入口[run_registered_gpt61_v22.py](../experiments/tier2/usage_v2/run_registered_gpt61_v22.py)直接读取对方原生 `Diagnostic_verified.json`、`Migration_final.json`、`Exclusive_call_handoff.json`、原始ledger和billing凭证，无须用户再提交一份审批。对方仍运行时不登记、不发送。只有终止/释放锁、共同模型接入与结算可靠、相同H/数据/状态及生成参数、实时账户和累计预算允许时才执行。若对方仅初始化不足且共同条件有效，可继续；共同接入、结算或全局预算停止则本页也停止。

本页曾建立附着当前聊天的串行续跑检查 `v2-2-gpt61`，只跟进这个已授权批次；发现上述实际共同结算阻碍后已设为PAUSED，不继续轮询或发送。现有实验授权保留，后续仅当共同结算确已解决、唯一账本与实时预算重新核对通过时才可恢复本批。以下为条件满足后的唯一运行命令；本轮未执行register/run，也未另开诊断或模型。

```sh
cd '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python experiments/tier2/usage_v2/run_registered_gpt61_v22.py peer-status
# 仅共同门禁通过后，登记一次：
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python experiments/tier2/usage_v2/run_registered_gpt61_v22.py register --directory runs/v22-gpt61-select-mix-301-20261014-v1
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python experiments/tier2/usage_v2/run_registered_gpt61_v22.py run --directory runs/v22-gpt61-select-mix-301-20261014-v1
```

入口会复查当前代码、原始资产和所有worktree账本；最终登记纳入原单成员503及新模型cap61批次，保持未知预留。新共享初始化不足5个则终止，A预算停止不启动B。即使已有目录，也不能重放旧请求或创建第二份补发。

## 离线验证及后续交付

[迁移/门禁/历史/导出测试](usage-space/Tests.gpt61-migration.log)33项通过；[传输/配额/SELECT-MIX及提示兼容测试](usage-space/Tests.gpt61-compatibility.log)49项通过，其中导出测试两套均执行一次。测试使用临时合成数据和loopback，不发送真实模型请求。新入口已实际完成离线prepare，导出配置与六份完整提示，provider迁移与模型专用风险策略经过类型及行为核对。

[离线准备记录](usage-space/gpt61-prepared/Gpt61_offline_readiness.json)绑定987份原来源文件、原H及训练文件。原10×21完整H评价按已封存证据复用；核对求解器、runtime、parser及数据未变，变化只在生成模型、网络审计及预算/登记策略。保留原技术审查，不重复搭建SELECT/MIX执行器，也不再重复全部H求解。当前正式validation/test物理文件未复制或加载。

本页真实运行结束后导出全部候选及失败、合法率/重复率、实际评分单选与组合源码、SELECT/MIX/单正项与真实双成员、逐实例成绩、种群变化和本批A/B训练配对、token、认证扣费、求解/复检/诊断时间及h调用数。未发生的实验结果与未知费用不记为0。只在本批共同条件内解释允许组合的影响；组合出现不代表收益，不能拿单成员页冠军直接证明组合更好，也不能给出独立泛化结论。
