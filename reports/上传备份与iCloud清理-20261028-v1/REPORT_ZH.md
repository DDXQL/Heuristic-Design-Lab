# GitHub上传、独立备份与iCloud旧目录清理

日期：2026-10-28（Asia/Manila）。本轮执行用户“好的，请你执行这些任务”的授权：上传最新集成分支、核验远端、单独保存原始资产、清理已经验收的四个旧FJSP项目目录。没有真实LLM/API、正式求解、候选生成、实验续跑或科学规则修改。

## 完成状态

- 集成分支 `codex/tsp-integration-20261028` 已推送；清理前本地/远端 `5e36a6c998928f360326d2c5415a4533560aa6d2`一致。本文与收尾回执另作提交并推送；最终commit以该分支远端及本机备份区Final_receipt.json核验记录为准。
- GitHub保存集成代码、受跟踪报告和证据包，默认分支/可见性没有改变，没有强推。GitHub界面需要选择该分支，不能用默认分支旧README判断未上传。
- 四个旧目录已经从Documents/iCloud项目父目录移出，原位置均不存在；**采用可恢复移动，没有永久销毁文件，也未清空废纸篓**。
- 当前开发仍在`/Users/DDXQL/Developer/FJSP-Heuristic-Research-tsp-integration`；Developer下所有工作树的HEAD、用户修改与环境依赖在清理前后保持一致。

## 独立备份和保存范围

备份根：`/Users/DDXQL/Backups/Heuristic-Design-Lab/legacy-20261028-v1/`，仅当前用户可进入。

|文件/目录|内容与校验|
|---|---|
|legacy-scientific-workspace.tar.gz|36,504个源码/科学资产文件加迁移证据，共36,832成员；逐成员独立解包读回SHA256一致；2,340,256,730字节|
|Archive_manifest.json|每个归档成员的名称、字节数与SHA256|
|all-preserved-git-history.bundle|清理前所有保留引用的完整Git历史，136,377,332字节，git bundle verify通过|
|retired-worktrees/|四个原项目的可恢复旧副本，保留未提交修改和原始运行资产；不是今后的开发位置|
|Backup_receipt.json|归档、bundle的SHA256和范围回执|

归档SHA256：`a5b58aebf102e06032f1857fc7c32204de70ba1ab80d664da713e07ae0401cb8`。
Git bundle SHA256：`b2e504534bb2c79941ee1cf8eee36852aed39207b41d5a6eac6845ff37db4ca0`。

原无引用Git对象和旧管理文件已作为静态证据纳入资产归档，不能只用普通bundle声称保全所有旧未引用对象。错误/partial记录照原样保存，备份成功不提升其科研有效性。

**这是同一台Mac上的独立备份文件夹，不是异地/另一块硬盘备份。** ignored runs/archives没有上传GitHub。原始数据已有本机副本及独立归档，但不能宣称全部原始资产已上云。

## 四个旧目录如何清理

原父目录：`/Users/DDXQL/Documents/大学/硕士/代码/`。

|原目录名|当前旧副本位置|
|---|---|
|FJSP-Heuristic-Research|备份根/retired-worktrees/FJSP-Heuristic-Research|
|FJSP-Heuristic-Research-h-usage-space|备份根/retired-worktrees/FJSP-Heuristic-Research-h-usage-space|
|FJSP-Heuristic-Research-tsp-pilot|备份根/retired-worktrees/FJSP-Heuristic-Research-tsp-pilot|
|FJSP-Heuristic-Research-u-single-experiments|备份根/retired-worktrees/FJSP-Heuristic-Research-u-single-experiments|

清理前逐项确认没有新增/消失/修改的科学文件，旧目录没有打开文件引用、Git锁或云端占位；两份私有凭据副本与源文件一致。目标和源位于同一文件系统。

三个linked worktree通过`git worktree move`移动，保留dirty/未跟踪内容，不用force/reset/clean。原主仓库最后同盘rename，再用`git worktree repair`修复退役副本内部的公共Git关联。不是只移动一个工作树；没有让Developer依赖已消失的旧公共Git。

移动后再次读取并校验36,504个科研文件，内容全部一致；四个退役工作树的HEAD、分支与工作区状态保持原值。活动与退役两套Git均fsck通过。其他Documents目录、EoH-S、论文和非本项目文件均未处理。

旧副本仅用于恢复与历史取证。历史协议的绝对路径和期限不改，不应从备份目录直接run/resume旧campaign。旧虚拟环境及旧脚本可能仍含历史路径，不能据此把退役副本当新开发工作区。

本轮核验的是本机原路径已消失；iCloud服务端同步进度和容量释放未另行查询。

## 凭据

日常凭据仍为：

- `/Users/DDXQL/.config/heuristic-design-lab/.env.leafapi.local`
- `/Users/DDXQL/.config/heuristic-design-lab/.env.deepseek.local`

私有目录700、文件600，未显示值、未纳入tar/bundle或Git。原凭据副本随退役主仓库保留在受限备份区，文件权限收紧为600，不上传。短生命周期离线子进程验证项目现有TSP credential读取函数能加载新LeafAPI文件；只确认加载，不请求模型，不把密钥永久注入当前终端。

真实API服务、余额和费用没有在本轮验证；以后正式运行仍按配置和显式run授权使用新凭据路径。

## 新位置运行复查

移走旧目录后执行：FJSP doctor、TSP doctor、固定toy计划预览、TSP Mock计划预览、TSP归档verify-all，5项全部通过，无API、无求解。当前与退役Git检查均通过。

```sh
cd /Users/DDXQL/Developer/FJSP-Heuristic-Research-tsp-integration
.venv/bin/python -B experiments/manage.py --problem fjsp doctor
.venv/bin/python -B experiments/manage.py --problem tsp doctor
.venv/bin/python -B experiments/fjsp/manage.py plan --config experiments/fjsp/configs/fixed-toy.json
.venv/bin/python -B experiments/tsp/manage.py plan --config experiments/tsp/configs/pilot-mock.json
```

不自动启动真实API、Mock campaign或任何正式求解。历史campaign依然不能直接恢复。集成工作树依赖Developer主仓库公共Git以及Developer h-usage的.venv；不要只保留集成文件夹而删除这些依赖。

## 证据与结束

本目录提供上传扫描（路径级、无凭据正文）、初次远端核验、独立备份、清理前检查、逐步移动日志、移动后入口和Git核验。完整资产Manifest只保存在备份区，以免将数万项原始文件误当新增科学结果。过程脚本是本轮操作留证，不是可反复执行的日常命令；遇到已有journal/备份时会停止，不盲目重放。

本轮到此收尾。后续开发使用Developer集成目录，备份区只作恢复资料；没有追加研究实验。
