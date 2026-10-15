# v2.2真实训练执行登记（2026-10-15）

沿用DDXQL已批准的gpt-6.1-sol方案及[原登记](H_USAGE_V22_GPT61.md)：固定同10条h、七状态、21train，seed301，N5，新共享SELECT初始化最多20次；A仅SELECT，B允许SELECT/MIX且最多2个正权重；各一代10次，5交叉5变异，本页总上限40，不补发失败或重复，不使用validation/test。

唯一执行者为本页及本worktree `codex/h-usage-space`。只使用 `runs/v22-gpt61-select-mix-301-20261014-v1`，目录日期为早先确定的身份，实际执行时间记录于日志。旧模型及旧40次方案不恢复。自动续跑检查保持PAUSED，避免与本轮执行重复。

## 交接修复与证据

另一页最终文件为 `single-ID-gpt61-paired-training-20261014-v1/Final_budget_handoff.json` 及 `Search_complete_resumed.json`。旧 `Migration_final.json` 和原始账户记录保留历史状态，不能要求其全部被改写成settled。读取逻辑新增对补充凭证的兼容，但不信任汇总数替代原始证据：逐笔核对原账单哈希、原账户记录、供应商ID、模型、原请求时间窗口、用量、实际扣费、账户观测及风险预留；补充证据文件哈希亦逐项核对。未发送槽位需发送前查账失败journal、before_dispatch记录、无账户发送记录及无wire记录共同证明。

实际逐笔核验结果：48槽位、33确认发送、15证明未发送，新实际扣费125096平台点；旧24000000点未知预留保持。累计旧历史80＋该批48＝128槽位，本页若用满40则168/300；实际发送数另报，不把15个未发送槽位计为模型请求。已结算但wire token未知的记录仍保留None及原token reservation。

另一页原始记录不修改、不整体合并分支。全部只读来源在本页登记时绑定文件哈希，并再次检查无其他writer锁、调用权释放、同H/数据/状态/参数，以及实时账户余额和30%边界。

## 本页发送保护

- 完整返回文本、用量、模型及请求ID先写入 `wire_responses/`，随后才查询账户和账单；结算失败不丢掉完整回复。
- 所有只读metadata GET共用至少15秒间隔；账单GET另保持至少75秒间隔，状态跨进程保存。此为工程限速，不声称是供应商公开上限。
- 账单查询放在生成槽位预留之前；失败触发账户门禁停止，不连续耗掉后续槽位。发送后结算失败同样停止新请求。
- 已发送、pending或发送不明的请求不重放；wire记录、原journal和账本均保护请求身份。失败槽位不重构候选或补发。

必要正反例见[测试记录](usage-space/Tests.gpt61-handoff-20261015.log)：33项通过，覆盖补充凭证、篡改哈希/ID/模型/时间/金额/账户/用量、汇总与逐笔不符、未发送证明、回复先落盘、防重发及metadata限速。测试只用临时合成证据或loopback，未发真实模型请求。

## 运行与结果位置

```sh
cd '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python experiments/tier2/usage_v2/run_registered_gpt61_v22.py peer-status
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python experiments/tier2/usage_v2/run_registered_gpt61_v22.py register --directory runs/v22-gpt61-select-mix-301-20261014-v1
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python experiments/tier2/usage_v2/run_registered_gpt61_v22.py run --directory runs/v22-gpt61-select-mix-301-20261014-v1
```

实际提示和响应在各阶段journal及wire_responses；源码、逐实例成绩、种群变化和训练配对由既有results导出。手写例子不进入种群。方法形式按计算与实际使用机制描述；if/else本身不代表缺乏多样性，MIX字样或双成员出现不代表组合收益。只比较本批A/B共同条件，不用另一批冠军归因组合许可，也不声称泛化。

## 断线后的同批次恢复

首段发送5次：2个完整有效SELECT、3次API失败，5笔供应商账单均已逐笔匹配，共31587平台点。第6次的发送前账单查询HTTP429，未预留槽位、未发送；原初始化状态保留为`initialization_budget_stopped`，checkpoint游标5、有效种群2、inflight为原第6次提示。

新增`tools/resume_usage_metadata.py`只作执行恢复附件，不改变冻结源码指纹、协议或算法。它先重新独立匹配所有既有请求的原账单/账户记录，再经现有持久限速器查询实时定价、账户和账单，并重新检查另一页调用权与唯一累计账本；健康证据写入`Metadata_health_restored.*.json`后才可恢复这个已证明未发送的metadata暂停。其他预算或未结算门禁不能由此入口解除。保留原Initialization_status，现有搜索器从原checkpoint继续；失败与重复不补发，初始化20及总40上限不变。该附件自身哈希及恢复前文件哈希另存于`Execution_resume.*.json`。

离线验证：新增5项恢复正反例，加既有6项交接/访问保护，共11项通过；另对本批5笔实际记录独立验算成功，未发模型。恢复命令（仅原登记目录）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python tools/resume_usage_metadata.py --directory runs/v22-gpt61-select-mix-301-20261014-v1
```

若只读健康仍失败则保留门禁，不消耗后续生成槽位；不得删除原状态、复制目录或重置历史预留以续跑。
