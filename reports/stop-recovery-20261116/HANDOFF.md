# R11恢复工具交付

源码冻结`ef0a130c0c5983657ff2fa54ca1fa24f7d7f7370`，工作树`/Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-stop-recovery-20261116`，分支`codex/fjsp-stop-recovery-20261116`。新协议是R9两份原搜索的已知失败审计承接，不是新种子或初始化。公共code/和run_frozen.py为原923781f字节，科学设置未改。

包`/Users/DDXQL/Developer/transfer-outbox/triad-fjsp-stop-recovery-20261116-r11.zip`，1,588,757字节（约1.52MiB），528成员，SHA-256为`178432e0aa8d7268486d5407dd0ed03401a6d671eb12b52eb3f9165aaee25cca`，同目录.sha256和.audit.json已生成。它不包含旧运行、检查点、凭据或账户占用；源证据只上传哈希，实际远端承接从原远端R9复制。

实际工具为experiments/triad/stop_recovery.py、deploy/stop-recovery/control.py及finite-manual.sh；必要旧适配改动仅runtime、shared_admission、parallel三处。一个确认HTTP522和五个确认not_sent保持失败，1167尝试不退，4个仅本地记账槽纳入新共享账本；旧STOP/ledger/失败/检查点原字节不动。手动确认后仅在所有旧作业终态和当前账户归属吻合时原子交接占用，旧租约原字节另存。未知、到期、未知writer/提交、身份变化仍拒绝，不自动清除或重放。

当前完整种群、部分下一代6/4、570/577演化游标和np_rng/rng原样保留。未来32步算子/父代/随机状态与原生对照一致；下一步分别为501的M1/父代SLOT-0000092，502的E2/父代SLOT-0000333和SLOT-0000233。不能回退P000。新共享STOP外层检查在下一候选规划/抽样/预留之前立即暂停，历史五个拒绝槽不改账。

离线导入/随机对照、请求计数和到期、旧记账移除/失败冒充成功、未知请求/提交、归属原子交接/重复调用、两个本地合成协调器暂停恢复均通过；包内527个清单文件和解压入口导入/语法通过。证据OFFLINE_CHECKS.json和EXTRACTED_CHECK.json。本轮API0、真实求解0、Slurm0、远端交接0；未上传、未完成计算节点有限继续。

最少步骤见`docs/R11已知失败审计恢复.md`：Mac先stage；集群已有登录会话cd R11后执行finite-manual.sh明确批准原2040中最多2新请求/84含复核求解并确认保留失败记账；两份终态后certify，passed才由用户手动原预算resume。累计有限边界各581/588。原截止仍2026-11-17 18:59:15（UTC+08，原小数秒保留），原排他不续期。有限完成后剩余429/422演化。任何新增失败保留，不补抽、不重试、不自动完整继续。

真正外部条件是远端字节、终态和当前占用仍与绑定相符，原窗口未过、node15和原环境资源可用，以及LeafAPI能完成用户手动的两次有界继续。离线检查不能保证生成服务健康。旧U503接续619593及Plan/失败回执不动，不能直接重提；两份EoH完成后再给新依赖。截图中同门经验仅为后续讨论，当前保持API1、三不同搜索种子、原反馈顺序，未调整到4/8或启用自动重试。

若后续Windows归档，在收到ZIP的目录运行：

```powershell
Get-FileHash .\triad-fjsp-stop-recovery-20261116-r11.zip -Algorithm SHA256
```

核对完整SHA后解压核对release.json。当前只是打包，未传Windows或确认备份，不删除任何旧证据。本包不包含原结果，不能当作结果备份。
