# B1-NS-B 小范围恢复检查

2026-10-22；检查起点提交 `e6175faa68be553553febec7d8c63c31070796ec`。本轮只读原实验，未发送 API、运行 U 或求解 FJSP；不追查历史写入者。

**结论：当前内容校验通过，但不能通过删除该冻结项来修复。尚未建立或授权可执行的新续跑协议。**

## 1. 当前身份

- 原协议 SHA256 仍为 `94381988c5536bd19f72aa0cbcdcafc7dfc1b8a4ece7b18fcbd71ad0b4a90083`。
- 143 项冻结文件全部匹配，不一致清单为空；完整 implementation 指纹（含运行环境）、配置、Prompt manifest 均匹配。
- 冻结 H 绑定文件及十成员顺序匹配；仅对 train21 文件做字节哈希核对，21 项均匹配，未打开 validation/test 实例。
- `tools/usage_mechanism_ablation.py` 当前 SHA256 为 `8f46ff2420db2e4783ff36bb82c403f8b594b4ff1c7fb38f10588d4cb0f1d1e4`，与原协议及当前 Git 版本一致。
- 原 guard 比较内容 SHA256，本来就不比较 mtime；仅 mtime 改变不需要放宽规则，也不能解释之前已经发生的内容失配。

## 2. 文件是否有关

必要调用链：

`tools/b1_nonstream_local.py::training_evaluator()` → `tools/usage_mechanism_ablation.py::evaluate_with_schedules()` → `research_real.runtime.evaluate()`。

其中 `evaluate_with_schedules()` 将 worker 临时绑定为同文件的 `schedule_recording_worker()`；后者代理原 worker、记录两次排程并要求物理排程一致。它不另写 Fitness 或生存选择，但属于实际评价与结果接受路径。`research_real/runtime.py::_collect()` 使用 `spawn`，子进程需导入该 worker 所在模块。

因此，用户允许“移除经证实无关脚本”的条件不成立。**不删除该 pin，不关闭 guard，不改旧哈希、账本、授权或 checkpoint；也不为绕过此项创建新协议。** 本轮没有修改生产代码或保护规则，新增内容仅为本报告、只读核对脚本和检查结果。

## 3. 六次请求和三个候选

| 核对项 | 结果 |
|---|---|
| 逻辑任务／真实尝试／完整响应 | 6／6／6；每任务一次、均确认发送，无 pending |
| Prompt、attempt ID、response ID、wire 与接收文本、usage | 逐项一致；HTTP 200、模型匹配、stop |
| 格式失败 | `000000`、`000003`、`000004`；保持原拒绝，不修复 |
| 完整有效缓存 | `000001`：−2.5611498256653267；`000002`：−2.4010715776754177；`000005`：−2.5270363059129246 |
| 三份源码 | 从原响应重新静态解析，AST key、seen、种群记录一致；未执行 U |
| 评价缓存 | 三份均 completed；63 条按原 train21 顺序，逐项 score、完整 mean Fitness 与种群相符 |
| 记录中的物理复检 | 63 条保存排程的 digest 与首次／复检哈希一致，captured_solves=2 |
| 检查点 | initialization、init_cursor=6、generation=0、cursor=0；inflight=null、children 为空、初始池3/5、RNG 与 seed501 相符 |
| 预算 | 原上限40逻辑／60尝试／每任务3次未变；已用6／6，剩余至多34／54；初始化另余至多14任务 |
| 历史保护 | 47 个原运行文件与已提交归档的字节哈希一致；本次读取前后原目录文件集合、内容与 mtime 全部未变 |

**可以保留和绑定六份响应及三份合法源码，不应重新请求这六个任务。** 账本与缓存没有发现自相矛盾，不需要重置计数器。

**尚不能无条件认证三份旧 Fitness 的计算时源码身份。** 原记录没有各评价子进程实际导入该模块时的源码哈希；当时失配的中间内容也未保存。当前文件恢复、排程复检匹配和成绩算术一致，均不能补出这项历史证据。本次未重新验证逐工序可行性，也未复演冻结 U，不能把记录自洽等同于完整来源认证。没有证据证明旧成绩被改变，也没有依据断言当时所有 worker 源码始终未变。

## 4. 最小检查与 Mock

只读核对可复现命令：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B reports/b1-ns-recovery-scope-check-20261022/check_saved_progress.py
```

- `Read_only_checks.json`：143 项 pin、环境指纹、H 顺序、21 个训练文件、六次请求、三份源码／结果及47项原始归档核对通过。
- 复用 `tests/test_b1_nonstream_local.py` 的8项 Mock 通过：完成响应／评价恢复不重复；未知发送、已预留未确认保守计数；40／60预算持久化；非法／重复不补发；不完整评价不存活；科研配置差异受限。全部使用合成回复、假评价和临时目录。
- `Guard_mock_checks.json`：6项局部检查通过。内存模拟修改消融脚本、执行器、Prompt、H绑定、配置的 SHA，原 guard 均拒绝；临时合成文件验证 mtime-only 不改变 SHA，内容改变则改变 SHA。未改原文件。
- 无生产修复补丁，因此这里的 PASS 是检查与 Mock 通过，**不是已完成无缺口的续跑验收**。

## 5. 下一步授权边界

当前不能按“删掉无关冻结项”方案进入真实续跑。最保守的下一步是另行授权：在独立、来源绑定的恢复协议中继承六份响应及三份源码，对这三个 U 做一次受控 train21 复核，并保留旧成绩与身份异常；至多63个候选—实例任务、126遍首次／复检求解，共享15秒规则不变，不重新调用模型。新协议及入口须先验收，原6次消耗必须携带，不能重新获得40／60额度。

如果用户选择接受已披露的历史源码身份缺口并直接继承旧缓存，也需明确这一证据取舍及续跑授权，报告持续保留异常标签，不能宣称本轮已补证。两条路径本轮均未实施。真实 API、正式评价和恢复运行都仍需下一条明确授权；本轮结束后保持停止。

证据：`Read_only_checks.json`、`Guard_mock_checks.json`、`Mock_tests.json`；原始证据引用既有运行目录及上一阶段 `Evidence_manifest.json`，不再次复制响应或大 checkpoint。
