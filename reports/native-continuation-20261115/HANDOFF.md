# 原生门槛承接交付

源码冻结提交：e46d2cc91856d08d1b3231f035f220092356aa22。公共执行代码仍为923781f。实际配置、离线检查、预算和状态见同目录`DELIVERY.json`、`OFFLINE_CHECKS.json`；操作步骤见本树`docs/FJSP原生门槛承接.md`。

包：`/Users/DDXQL/Developer/transfer-outbox/triad-fjsp-native-continuation-20261115-r9.zip`，1,214,745字节（约1.16MiB），522个成员（其中521个受release清单核验，另一个为release.json）。SHA-256：`9361b94d8b3812cdef8a49f79876f9fba765cf60b2cc740307fe8bfaa0512a2f`。同目录`.zip.sha256`与`.audit.json`已经生成。解压后check-only通过；本轮API0、求解0、H执行0、Slurm0。

当前状态：本地已准备并核验；尚未上传R9、尚未完成远端承接检查、尚未提交、尚未在计算节点运行新版。旧Mock和真实验收已关闭，不重复。原R8失败及取回证据保持原样，旧源、包、检查点和账户门禁未由本轮修改。

新协议覆盖501/502/503三次重复；此次命令只承接501/502，各保留已用10请求、378/420次含复核求解。各原上限1020，剩余1000次演化不补初始化，合计最多新增2000请求、84000次含复核求解。截止仍为2026-11-17 18:59:15（UTC+08，原小数秒保留），不重置原48小时窗口。两作业各2CPU/2048MiB/12小时段，共享全账户API1；原72小时排他安排仍须有效。503未来独立从空种群开始，本轮不启动。

用户下一条在Mac终端执行文档中的`launch_native.py stage`，成功后在已有集群登录会话切换R9目录，执行`continue_native.sh`的手动提交命令。该脚本遇错即停，不整段重复执行，不删锁。只有用户发出的最后一步会提交Slurm和授权真实API/求解。

若后续传往Windows归档，在收到的ZIP所在文件夹执行：

```powershell
Get-FileHash .\triad-fjsp-native-continuation-20261115-r9.zip -Algorithm SHA256
```

核对上述完整SHA后再解压，并核对`release.json`文件清单。当前仅已打包，未传Windows、未核验Windows备份；不删除Mac或集群证据。本ZIP不包含旧运行结果和检查点，不能当作其归档备份。
