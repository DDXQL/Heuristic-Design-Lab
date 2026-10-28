# 迁移删除前验收：旧FJSP/TSP四目录

检查日期：2026-10-28（Asia/Manila）。本轮在Developer的TSP集成工作树完成，只做增量文件保存、只读核查和不求解的入口检查。没有真实API、正式求解、历史实验重评、推送或删除。原四目录、工作树注册和用户修改均未改变。

## 当前结论

**科研文件和当前Git历史的迁移缺口已补齐，可以进入旧目录的清理准备；本轮没有执行删除。** 之前“仍有4,120/4,121项未取得”的说法是此前时点的状态，不再代表本次结果。

此前缺失的源文件现在均已下载可读。增量复制3,362个源码/实验文件（779,322,486字节），独立核对目标SHA256，失败0、覆盖已有文件0。另补齐746个缺失环境文件，只写原本不存在的文件，不覆盖重建环境。

按四个旧项目实际当前文件盘点，共36,504个源码、数据、配置、报告和实验文件，合计6,553,591,265字节，全部找到内容一致的Developer保存位置，失败0。这个数量是文件覆盖数，包含嵌套归档和缓存复用材料，不是独立实验数量，也不宣称每条旧结果有效。云端占位和短读没有被当作成功；本次纳入盘点的文件云端占位数为0。

排除范围仅有：凭据（2个）、可重建环境/字节码/系统缓存、符号链接及独立处理的Git管理文件。没有擅自放弃原始响应、失败、锁、账本、checkpoint或未完成实验。

## 每个文件保存在哪里

|覆盖方式|文件数|含义|
|---|---:|---|
|对应Developer原工作树|33,713|对源/目标逐文件算SHA256，不只比文件名或大小|
|当前集成目录中的TSP源码/报告|133|内容与原TSP当前文件相同|
|既有TSP认证vault|2,646|与实际源字节、Manifest及归档校验一致|
|新增原版本/独有文件vault|12|当前Developer代码已更新的旧文档/源码等另存，不反向覆盖新版本|
|合计|36,504|全部有源路径、目标路径、SHA256和字节数|

完整索引：`逐文件保存索引.json.gz`。明文原件：`/Users/DDXQL/Developer/迁移记录-删除前验收-20261028-v1/逐文件保存索引.json`。可以用本目录的`查找已迁移文件.py`查询，不需要再访问旧iCloud路径。

新增12项位于：`archives/legacy-cleanup-audit-20261028-v1/workspace/`；对应Developer各工作树新增的3,362项留在其原相对位置；TSP历史运行vault仍在`archives/tsp-c3b74b7-20261028-v1/workspace/runs/`。这些ignored资产**只在本地，没有因为本次提交而上传GitHub**。

## Git保存与原修改保护

旧公共Git：`/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/.git`。
新公共Git：`/Users/DDXQL/Developer/FJSP-Heuristic-Research/.git`。

- 查验旧库4,004个loose对象，补齐此前16个未取得对象，剩余缺失0；源库没有pack文件需要补齐。
- 旧25个refs的确切值保存在新库`refs/legacy-preserved/20261028/…`命名空间，没有覆盖活跃分支。
- 旧87个Git管理文件（含完整reflog、index、原worktree注册）和3个工作树.git指针，逐字保存为**静态证据**。位置为`/Users/DDXQL/Developer/迁移记录-删除前验收-20261028-v1/原公共Git管理文件/`；它们不作为新库的活动配置，不改写旧绝对路径。
- 原有无引用对象另存到静态Git证据目录，避免普通Git垃圾回收影响其保存；见原无引用Git对象独立保存.json。
- 新库`git fsck --full`退出0。源/目标原有分支、HEAD、工作区状态前后一致。

因此此前16个Git对象、6份reflog和7份sample hook缺口已经补齐。保存历史Git证据不意味着复制后可直接续跑旧campaign；旧协议的源码身份、路径和截止时间仍必须尊重，不重置、不删除未知状态。

## 独立使用检查

对3个Developer Python环境只做numpy/pytz/tqdm导入检查，全部通过。TSP集成环境链接指向Developer的h-usage环境，不指向旧Documents。

另外在子进程中明确禁止网络连接，并拒绝open/listdir/scandir访问旧项目路径，执行以下5项均成功：FJSP doctor、TSP doctor、FJSP fixed-toy计划预览、TSP Mock计划预览、TSP归档verify-all。没有调用求解器或实际运行Mock campaign；归档检查只读已有文件。

当前可观察的旧项目打开文件引用为0；这是本轮时点的检查，不承诺闲置编辑器/其他聊天以后不会重新使用旧路径。清理前应关闭旧目录的编辑器/终端，后续只从Developer开展工作。部分历史脚本/文档中保留旧路径属于证据，不能据本轮入口检查宣称所有古老脚本都可无改动恢复执行。

## 逐目录清理结论

以下“可以列入清理”表示内容保存验收通过，**不是已经删除，也不构成本轮自动删除授权**。

|原iCloud目录|保存结论|清理条件|
|---|---|---|
|FJSP-Heuristic-Research-h-usage-space|已覆盖全部当前源码、独有修改、未跟踪实验文件和运行资产|关闭旧入口；明确清理时先解除其旧worktree注册。dirty状态是原样保留的，普通remove可能拒绝；不得随手强制清理|
|FJSP-Heuristic-Research-tsp-pilot|最新TSP提交、完成实验及当前目录文件已保存|同上；新开发使用tsp-integration，不再从此目录启动|
|FJSP-Heuristic-Research-u-single-experiments|当前源码、用户修改、原始运行文件均已保存|同上；原tools/report_single_fair.py修改未丢失|
|FJSP-Heuristic-Research（原主仓库）|源码、资产、Git对象、refs和管理证据已保存|**先处理下述凭据**，其余旧linked worktree解除后，最后再处理原公共Git目录|

原公共Git与旧工作树的关联不是永久保留理由；资产和必要证据已保存后，可以按正确顺序解除。不要直接只删旧主仓库而留下仍指向其.git的旧工作树。

**Developer目录不在本次清理范围。** 新集成仍依赖Developer主项目的公共.git，以及Developer h-usage的.venv；不能只保留集成文件夹而删除这些依赖。

## 仍需用户处理的两份凭据

旧主仓库的`.env.leafapi.local`、`.env.deepseek.local`只记录了文件名和字节数，未读取内容、未复制到项目、未提交。它们不属于本轮科研资产覆盖结论。若仍需使用对应账户，应由你先在安全位置保存或配置；若不再需要，应由你明确决定放弃，不能替你默认删除。

本轮没有清理任何原目录。下一次实际删除前，还应确认从本回执之后没有其他Codex或人工继续在旧目录产生新文件。技术验收完成与不可逆删除是两个步骤。

## 复核入口（不启动任何实验）

```sh
cd /Users/DDXQL/Developer/FJSP-Heuristic-Research-tsp-integration
.venv/bin/python -B reports/迁移删除前验收-20261028-v1/查找已迁移文件.py Cache_index.json
.venv/bin/python -B experiments/manage.py --problem fjsp doctor
.venv/bin/python -B experiments/manage.py --problem tsp doctor
```

本目录保存增量复制、Git保存、逐文件覆盖、旧路径隔离入口和原修改保护回执。四个迁移脚本作为本轮过程留存，包含写文件/保存ref的操作，**不是日常查询命令，不应为了查看状态重复执行**。
