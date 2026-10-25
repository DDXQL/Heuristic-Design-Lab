# 以后如何提交长任务而不持续调用模型

本轮新增code/fjsp_usage/long_jobs/local.py与tools/local_long_job.py；不修改冻结A4执行器。使用macOS用户launchd单次任务，KeepAlive=false，不自动重启；启动端提交后即可退出，任务自己记账和输出End_summary.json。当前CLI仅允许synthetic-engineering-only，无法启动正式FJSP或续用旧207查询。

已验证：独立控制会话用SIGHUP退出、控制管道关闭后，launchd子任务PPID=1且三项合成查询完成、exit0；边界暂停在一项完整落盘后生效；合成os._exit(13)保留reserved与锁，拒绝再提交；源码/预算/未知时钟/旧目录保护；模拟wall与monotonic差异时，保留当前结果、下个候选前暂停。最终收据Long_job_acceptance.json含5项测试、源码SHA、PID、exit状态和原始目录。

运行只需一次提交，后续读取一次状态/自动摘要；不需要模型定时轮询。测试脚本内为进程同步使用有限等待，不产生反复模型调用。Events.jsonl按候选事件记UTC、单调钟和CPU，Run_identity记录PID/PPID/启动身份，Launch_receipt保留提交预留，锁只由匹配token的当前进程释放；未知/崩溃锁不清理。

本轮复核命令（只有合成数据）：

```bash
PYTHONPATH=code:. .venv/bin/python -B tests/test_local_long_jobs.py
```

该命令会创建新的独立合成验收目录，并拒绝覆盖已有最终收据；如只是查已有结果，直接读Long_job_acceptance.json，不要反复运行。CLI可用toy-prepare/launch/status/pause；work由launchd调用，不手动重发。所有生产适配器必须另获授权、冻结新的源身份、读取持久期限并接入run_boundaries；本轮没有生成生产批准。

电脑睡眠会停止正常连续计算。launchd不会替用户打开盖子、延长六小时或自动重试。未测试关闭整个Codex App、退出登录/重启的行为；验证的是启动会话/控制端退出，不能扩大承诺。初次Background预检存在Python启动文件读取延迟，后来完成exit0；原因未知，最终去掉该进程类型设置并重新验收。不要靠高频模型轮询判断进度；看日志中的UTC/时钟差异和最后已认证边界。

未来若要真正在当前机器执行，预先安排机器保持清醒的时间窗；本轮未改任何全局电源设置。发生Sleep导致时钟间隙，新增边界循环会保留已完成候选并暂停下一个，不声称恢复期间继续计算。若有未知reserved或Stop，保留证据等待处理；不自动删锁、不重新prepare。

原A4期限不可编辑。追加执行必须以独立补充协议链接原冻结计划、93条账本、缓存与原停止记录；从第94项接续，明确新的追加时长和含休眠期限口径，仍受全campaign300次上限。当前合成入口不是这一正式接续实现。

查验本轮现有证据请优先使用verify_closeout.py，既不创建合成任务，也不重新扫描原始日志。
