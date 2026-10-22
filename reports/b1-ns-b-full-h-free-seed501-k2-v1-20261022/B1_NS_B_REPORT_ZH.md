# B1-NS-B：非流式完整10H实验的中止报告

日期：2026-10-22。**本批未完成：初始化处理6槽，得到3个完整评价有效的初始成员，尚未形成N=5的P0；CROSS、MUTATE和两代演化均未启动。** 冻结源码核验在下一槽发送前报错，进程按门禁退出。未修改协议或补发请求，未自动重启。

## 1. 停止原因与证据边界

实际使用工程提交 `efe04fb84fcb024e1442297f0e1a904de2a0fb5c`，协议SHA256 `94381988c5536bd19f72aa0cbcdcafc7dfc1b8a4ece7b18fcbd71ad0b4a90083`，原运行目录 `runs/b1-ns-full-h-free-seed501-k2-v1-20261022/`。启动核验143项输入、模型／Prompt、原10H及21train身份全部通过，按本轮授权登记后执行原唯一CLI：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/b1_nonstream_local.py run \
  --run-dir runs/b1-ns-full-h-free-seed501-k2-v1-20261022 \
  --env-file ../FJSP-Heuristic-Research/.env.leafapi.local
```

第6个候选已完成并落盘后，下一次 `B1Search._prepare()` 调用 `b1_nonstream_local.check()` 时触发：

```text
ValueError: frozen input/code differs: tools/usage_mechanism_ablation.py
```

进程退出码1，无第7次发送。`run()` 的finally已保存 `Search_status.json` 和3个初始成员的 `Final_or_partial_population.json`，writer锁已释放。不是预算耗尽、传输熔断、FJSP失败或20槽初始化上限耗尽。

停止后的只读复核出现重要限制：

- 当前工具文件内容又与冻结SHA256一致：`8f46ff2420db2e4783ff36bb82c403f8b594b4ff1c7fb38f10588d4cb0f1d1e4`；Git当前没有该文件内容差异。
- 最后一个候选有效事件：11:30:29.988 UTC；异常日志最后写入：11:30:30.429 UTC；该文件当前mtime：11:30:33.788 UTC。当前mtime晚于报错，不能用它推断中间内容或变化开始时间。
- 冻结检查器只记录异常文件名，没有保存当时读到的实际哈希、文件内容或写入者。**这些证据未知，不能凭空还原，也不能归责给某个进程。** 短暂写入／内容切换是待查原因，不是已确认根因。
- 原3份评价保留原生 `valid=true`、完整21实例及确定性复检记录。它们在异常前已落盘，但没有连续的逐worker源码哈希凭证，所以报告统一标注 `run_identity_exception=true`，不声称整段执行的源码身份已完全认证。

当前只读 `check`通过只表示现在的文件一致，**不会清除本次异常或授权自动续跑**。原 `Search_status.phase`仍为initialization、原账本halt_reason仍为null；因为这次是外部冻结核验ValueError，不是BudgetStop。派生总结明确登记 `stopped_frozen_input_identity_violation`，没有把原账本或检查点改写成其他终态。

完整异常、时间和当前观察见 [Execution_B1_NS_B.log](evidence/Execution_B1_NS_B.log)、[B1_NS_B_execution_end.json](evidence/B1_NS_B_execution_end.json)、[停止后只读检查](evidence/Post_stop_readonly_check.log)。本任务没有回写、恢复或调整该源码文件。

## 2. 初始化、合法率和请求情况

| 任务 | API接收 | 原完整U格式／静态检查 | 完整train21评价 | Fitness |
|---|---|---|---|---:|
| B/init/000000 | 完整 | 失败：说明无花括号 | 未评价 | null |
| B/init/000001 | 完整 | 通过 | 有效，21实例 | −2.561149825665 |
| B/init/000002 | 完整 | 通过 | 有效，21实例 | −2.401071577675 |
| B/init/000003 | 完整 | 失败：说明无花括号 | 未评价 | null |
| B/init/000004 | 完整 | 失败：只有代码块，无规定说明 | 未评价 | null |
| B/init/000005 | 完整 | 通过 | 有效，21实例 | −2.527036305913 |

以已发送6个逻辑任务为分母，格式＋静态通过率、完整训练有效率均为3/6=50%；完整HTTP响应观察为6/6。3个格式失败均为原 `CandidateError: expected one {description} and one python block only`，未人工修复、去掉说明后重收或送入求解器。

账本记录AST重复0；格式失败在AST去重前被拒绝，因此这不代表所有原始代码片段具有不同语义。完整合法程序之间也可能排程等价，未增加语义去重。CROSS／MUTATE的任务数均0，其有效率与效果为NA，而非0%或“演化无收益”。没有正式P0／P1／P2，只有3个已接受初始成员的部分池；没有继承旧U、D4诊断程序或人工程序。

全部回复和失败原因见 [Candidate_index.csv](Candidate_index.csv)、[responses](responses/)，合法代码见 [U_sources](U_sources/)，部分池和原谱系见 [Population_and_lineage.json](Population_and_lineage.json)。

## 3. 实际SELECT/MIX行为

3份完整评价共记录11,400个主排程决策：SELECT 11,400，MIX 0，双成员0；实际启用H5、H8、H9，没有实际启用H0/H1。以下均复用已存 `usage_decisions`／`member_usage`，没有观察回放或追加评价。

| 程序 | 实际成员使用（3800步／程序） | 主导成员切换次数（21实例合计） | 说明 |
|---|---|---:|---|
| init/000001 | H8：21；H9：3779 | 21 | 每实例首步H8，之后H9；源码其他条件未使成员改变 |
| init/000002 | H5：3800 | 0 | 常量SELECT |
| init/000005 | H8：1015；H9：2785 | 399 | 状态条件实际引起成员切换；源码可返回H5/H6的分支未在这些轨迹启用 |

例如常量程序原样为：

```python
def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0))
```

init/000005按首次状态、machine_ready_std、remaining_work_std、candidate_pair_ratio及progress分支。不能按if数量判断方法好坏；这里根据实际启用和切换判定动态行为。成员切换不等于每次动作都改变，本批没有新增共同状态动作对照，也不能据切换次数推断收益。没有MIX只说明这6槽、3个有效程序的覆盖有限，不能推断完整空间或Prompt普遍不能生成MIX。

## 4. 与固定H的训练成绩比较

固定H参照直接复用本批已绑定的原冻结10H成绩，21实例身份及LB对齐，不重评固定H。最高固定成员仍为H0：Fitness **−2.111804960626**，Cmax总和4524。Fitness是21个−Cmax/LB的均值，越大越好；Cmax总和仅附列，不是该优化目标。

| 停止前完整评价程序 | Fitness | Cmax总和 | 对H0胜／负／平 | ΔFitness（U−H0） |
|---|---:|---:|---|---:|
| init/000001 | −2.561149825665 | 5512 | 1／20／0 | −0.449344865039 |
| init/000002（部分池最佳） | −2.401071577675 | 5204 | 0／21／0 | −0.289266617049 |
| init/000005 | −2.527036305913 | 5456 | 3／18／0 | −0.415231345287 |

三个程序平均成绩都未超过H0。部分池最佳为固定H5，其逐实例Cmax与缓存H5一致；init/000001的逐实例Cmax与缓存H9一致，即使首步使用过H8，也不能把它归类为源码常量程序或宣称全状态等价。init/000005虽动态切换，当前完整训练成绩仍低于H0，不能据此宣称动态性带来收益。

这只是停止前缓存的描述性结果，带本批身份异常标记，不是已完成自由发现实验的最终冠军比较，也没有独立验证。常量H5优于这两个动态程序不能识别“常量机制优于动态机制”的因果效应，因为它们实际使用的成员也不同。

完整63行逐实例结果及胜负差值见 [All_instance_results.csv](All_instance_results.csv)，10个固定成员原成绩见 [Fixed_H_cached_reference.json](Fixed_H_cached_reference.json)。没有使用validation11、test28或其他实例选优。

## 5. 实际成本与保护状态

- 已用6/40逻辑任务、6/60实际API尝试；每任务1次，重试0，pending 0；初始化仅用6/20槽。剩余上限没有因停止而重置，也没有继续使用。
- 六份响应均为HTTP200、锁定gpt-6.1-sol、stop及有效usage；未发生传输熔断、模型异常或预算耗尽。
- API响应usage输入62,605、输出2,769 token；cached_tokens合计25,344是输入的子集，不另加。无未知usage，**实际费用仍为null**，没有账单／账户／价格查询。
- 3个候选共63个实例评价、126遍首次及确定性复检，全部成功；未发生FJSP超时或复检不一致。原始完整评价墙钟合计63.576秒，其中首次求解31.176秒、复检30.958秒。
- 可认证h动作评分调用：首次4,917,820次，复检4,917,820次，合计9,835,640次。
- 六次API尝试计时合计162.808秒，含预留后的发送前验证和收存；不是纯网关延迟。来源审查、哈希核验和进程启动还消耗时间，不能把上述计时简单当作完整CPU成本。未额外采集CPU秒；旧固定H与U路径的计时口径／运行时刻不同，不作精确速度优劣结论。
- 旧B1/B2/T1及H来源八个指定目录的402个既存文件内容哈希与mtime全部保持不变；本批准备冻结文件也与NS-A归档逐字节相同。历史运行文件未变不等于本次共享工具源码全过程未变化，后者正是停止原因。核对见 [Historical_protection_check.json](Historical_protection_check.json)。

## 6. 能得出的结论与后续决策

本窗口已取得6份完整非流式响应，其中3份形成合法且完整训练可评价的利用程序；非法格式仍是生成损耗之一。3份均为SELECT，实际出现状态相关成员切换，但没有超过强固定H0。**没有形成完整P0，也没有演化数据，无法回答两代LLM演化是否改善完整10H利用。**

当前首先应只读定位共享工具文件在运行窗口的短暂失配来源，保留原源码、账本和未完成检查点；在后续决定前避免其他进程写入冻结输入。若要续跑，必须先确认身份连续性和恢复条件，再明确决定是否使用原检查点或另立身份；本阶段不擅自重启、更新哈希或开新批次。不能用新增模型调用或重评掩盖本次异常。

全部持久化证据见 [Evidence_manifest.json](Evidence_manifest.json)。大检查点以可无损解压的gzip保存，原9.4MB检查点仍在原运行目录；原源码／回复／成绩未修改，未上传密钥或认证头。`derive_results.py`只读本批记录并生成派生表，不调用模型、不执行U或排程。

本阶段已停止，报告明确为未完成实验。没有自动扩种子、增加代数、使用留出集或启动其他研究。
