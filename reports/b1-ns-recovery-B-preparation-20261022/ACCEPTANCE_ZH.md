# B1-NS 方案 B：恢复准备与离线验收

2026-10-22。**工程准备 PASS；正式复核和 API 续跑均未授权、未执行。**

恢复目录：`runs/b1-ns-recovery-B-v1-20261022/`。

协议 SHA256：`565537b020173b30a6bd41d316228691892c500c8bcecb3266491d70193bcd72`。

来源仍为原 B1-NS-B：协议 `94381988c5536bd19f72aa0cbcdcafc7dfc1b8a4ece7b18fcbd71ad0b4a90083`，六次 INIT 请求、三份合法 U（`000001`、`000002`、`000005`）。这是同一搜索进度的受控恢复，不是新的独立重复实验。

## 改动和保护

- 新增 `tools/b1_ns_recovery.py`：准备／校验、独立授权门禁、来源迁移、三候选复核和有条件续跑；复用原 NSSearch、AttemptJournal、原 worker 与调度器。
- 新增 `tests/test_b1_ns_recovery.py`：恢复、预算、身份与异常停止 Mock。
- 本目录 `verify_preparation.py`：隔离进程内的纯准备检查；不加载 FJSP 实例、不调用 API。H 来源仍由原审查校验器核对，包括既有固定评分样例。
- 没有修改原 B1/B2/T1 代码、协议、H、Prompt、执行器或历史结果；原47个运行文件与上轮核对的 SHA256、mtime 全部一致。
- 原143项冻结文件完整保留，包含 `tools/usage_mechanism_ablation.py`。新快照总共冻结181个文件，额外覆盖工具依赖及 train21 文件；保持原运行环境指纹。
- `source_snapshot/` 和 `inherited/` 文件及目录设为只读；快照只含21个训练实例文件，不复制 validation/test 实例。执行门禁要求从该快照导入运行入口及原适配器。只读权限用于减少误写；哈希和加载身份核验仍持续有效。

## 复核和迁移规则

1. `inherited/` 保存原47项证据的逐字节副本，包括旧响应、账本、checkpoint、Fitness 和旧授权；旧授权仅是归档，不作为新运行许可。
2. 三个 U 按固定顺序各复核一次完整 train21，沿用首次求解＋复检共享15秒的原规则；不生成或修复 U。每个子进程在求解前、最后结果发送前记录自身导入文件 SHA256，并将已加载函数／显式方法的递归代码身份与冻结源码重新编译结果比较。保留原 worker 和执行器观测绑定，调度语义不变。
3. 严格逐实例比较 Cmax、LB、score、可行性、完整排程结果摘要、物理排程／复检／提交顺序哈希及 captured_solves；完整 Fitness 必须精确相同。计时不要求相同。原评价器返回的结果或失败前缀先存入 `evaluation_receipts/`，即使后续身份检查失败也保留，但不据此接受 Fitness。新旧逐实例对照写入 `Revalidation_comparisons/`，通过验收的新结果写入 `Revalidation.json`，旧结果不覆盖。
4. 任一不一致、失败、缺失或改变的子进程身份证据立即停止；已保存失败或 pending 的复核不自动重做。部分成功不能开放续跑。
5. 仅三份复核全部 matched 且来源身份仍有效，才建立新活动检查点。原六个请求／尝试／响应编号、所有记录、init_cursor=6、RNG、seen 和尝试历史保留；只显式绑定新协议／账本身份，并在新检查点替换三份经匹配的评价缓存。旧账本 identity 和 SHA256 保留在迁移来源中。
6. 使用单个持久化迁移 bundle 完成两文件落盘；中断后只补齐尚未写入且相符的文件。迁移完成后不重新覆盖已向前推进的检查点。请求 phase 继续保留原编号命名空间，以满足原 AttemptJournal 的编号校验；新运行身份由恢复协议、路径及新 journal identity 绑定。

**预算仍是全程40逻辑／60 API尝试／每任务3次。** 继承已用6／6，剩余至多34／54；初始化上限20，尚余至多14个 INIT。三份旧响应不会重新请求，格式失败也不补发。原有限重试、熔断、未知发送保守停止、单进程 RunLock 保持。费用未知保持 null，不查账户或账单。

## 验收与当前状态

- **24项 Mock 通过**（21项恢复检查＋3项复用的完整两代／Prompt／科研配置检查），失败0、错误0。覆盖重新评价门禁、六次消耗计入40／60及每任务3次、旧响应不重发、缓存和 worker 留证恢复、复核异常停止、迁移中断与再次启动不回滚。
- 隔离进程导入检查通过：16个关键模块、136个函数／方法与快照源码对应，前后身份一致。正式 worker 包装流程仅用合成结果做 Mock，尚无真实 train21 复核结果。
- 原 H 来源、编号顺序、Prompt 和科研配置一致；21train 仅做文件哈希核对。没有新的真实请求、正式 FJSP 评价或正式种群写入。
- 当前只有 `revalidate.Authorization.template.json`、`continue.Authorization.template.json`，均 approved=false；没有活动授权、活动请求账本、复核结果或可自动推进的检查点。
- 身份观测增加少量墙钟开销，不延长15秒期限；原求解／复检计时字段照常保留，不把新旧墙钟差异直接解释为策略速度变化。

证据：`Mock_acceptance.json`、`Isolated_import_check.json`、`prepared/Protocol.json` 及两个未批准授权模板。旧原始响应和大 checkpoint 不再次提交归档，继续引用既有证据；本地恢复目录保留不可写副本。

## 额外规模和待授权命令

正式复核需要 **3×21=63个程序—实例评价，成功时126遍首次／复检求解；API请求0次**。逐实例期限合计最多945秒，另有准备、文件校验和进程清理开销；任一异常提前停止，不加时、不重跑。未新增观察回放。

以下命令须在收到新的明确授权、按对应模板登记 approved=true 并绑定上述协议后执行；命令本身不创建授权。

```sh
cd '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/runs/b1-ns-recovery-B-v1-20261022/source_snapshot'

# 仅核对，可离线执行
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/.venv/bin/python' -B -m tools.b1_ns_recovery check --run-dir ..

# 待授权：仅复核三个 U，不调用 API
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/.venv/bin/python' -B -m tools.b1_ns_recovery revalidate --run-dir ..

# 再有续跑授权且三份复核全部匹配后：继续 P0 及原两代演化
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/.venv/bin/python' -B -m tools.b1_ns_recovery continue --run-dir .. --env-file '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/.env.leafapi.local'
```

目前具备申请正式三候选复核的工程条件。是否允许后续真实 API 续跑须另有明确授权；三候选出现任何不一致时停止报告，不自动放宽标准或改用新成绩推进。
