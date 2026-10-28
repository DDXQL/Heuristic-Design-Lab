# Heuristic-Design-Lab本地工作树更名验收

日期：2026-10-28（Asia/Manila）。本轮仅项目名称、活动路径和文档整理，没有修改算法、H/U、状态、模板或实验协议，没有真实生成API、正式搜索或求解。GitHub只进行3次只读元数据查询；未执行远端更名或推送。

## 更名完成

- 原集成位置：`/Users/DDXQL/Developer/FJSP-Heuristic-Research-tsp-integration`。
- 新开发位置：**`/Users/DDXQL/Developer/Heuristic-Design-Lab`**。
- 方式：`git worktree move`，退出0。不是仅在Finder修改文件夹名，不建立旧路径隐式软链接。
- 移动前分支`codex/tsp-integration-20261028`、HEAD `e7acc749abef9d3f8af1ffe1144e982e39a03ae3`保持不变。当前README/指南与本报告另作本地提交，最终commit见git log和外部Final_receipt.json，不伪填到提交自身。
- 公共Git宿主仍为`/Users/DDXQL/Developer/FJSP-Heuristic-Research/.git`。其它4个工作树、各自分支/HEAD/原修改未变。
- 集成环境仍链接`/Users/DDXQL/Developer/FJSP-Heuristic-Research-h-usage-space/.venv`。Git管理目录保留旧内部ID正常；其gitdir反向路径由Git更新，未手改.git或搬公共Git。

## 开始前写入检查

工作区干净，未发现实验运行器或Git锁。首次保守检查发现另一个工作树里有Code Helper打开迁移说明；进一步核对fd访问方式为r、路径不在移动树，确认只是只读文档后继续。未终止编辑器或其它任务。原始和分类结果都保留，没有把读取句柄说成运行实验。

## 文档与历史保护

更新当前README、项目使用说明、实验操作指南、代码地图及结构导航的活动路径。TSP接入文档保留当时来源段落，更新当前cd命令并添加更名提示。

更名前12,195个已有code/tools/experiments/tests/data/reports/runs/archives文件全部逐SHA核对，更名后287,279,170字节内容一致。旧Protocol、checkpoint、请求响应、H/U、评分内核、状态、Prompt和原始证据均未改写。新报告目录是本轮新增，不在旧证据中追写。

冻结TSP迁移回执的vault仍是旧绝对路径，因此现有查看器使用其已有`--vault archives/tsp-c3b74b7-20261028-v1`显式映射参数；原回执及manifest SHA不改，全部9,491个资产仍校验。`docs/本地路径映射-20261028.json`是明确映射记录，不是自动加载的补丁，不重绑定旧缓存或checkpoint。没有改代码来兜底访问旧目录。

历史报告内的旧绝对链接保持来源含义，需要按当前根映射阅读。旧campaign不能因为更名而直接resume或延长期限；新实验另建run身份。

## 验证

15项实际入口检查通过：统一/两问题help、FJSP/TSP doctor、配置检查与计划预览、两个legacy状态版本、共同草案禁用、跨问题schema拒绝、未知schema拒绝、TSP显式vault全部核验。预期拒绝的退出2属于通过，不算运行失败。

检查在子进程中禁止网络、禁止FJSP/TSP构造求解器、禁止打开旧集成路径及旧Documents项目路径；没有调用run或prepare。7项既有状态契约纯单元测试通过。FJSP仍七输入，TSP仍五输入，common-v0-draft仍禁用；没有新状态上线或新质量证据。

相关文件：CLI_checks.json、State_contract_tests.log、Protected_files_comparison.json、Final_scope_check.json。

## GitHub：下一项独立操作

当前仓库`DDXQL/fjsp-heuristic-research`，仓库ID1405626004，public，未归档，默认分支main，读取到的当前权限含admin。

目标`DDXQL/Heuristic-Design-Lab`查询返回404，未发现可访问同名仓库；owner过滤列表为空，不能据此保证看到了账户所有仓库。因此仅能报告“尚未查到占用”，不是保证更名可用或名称已保留。实际更名未尝试。

origin始终为`git@github.com:DDXQL/fjsp-heuristic-research.git`。以后另行授权更名时，应在GitHub更名成功并核验仓库ID后，再将这套公共Git的origin改为`git@github.com:DDXQL/Heuristic-Design-Lab.git`；共享该Git的Developer工作树会一起使用新origin。退役备份是独立Git，不能当成同一配置。实际更名不等于合入main或更改默认分支。

本轮只本地提交；没有推送本轮更名文档，也没有改变GitHub名称/可见性/默认分支。

## Codex界面交接

请在Codex/编辑器重新打开 `/Users/DDXQL/Developer/Heuristic-Design-Lab`，项目显示名使用Heuristic-Design-Lab。旧项目条目如仍指向tsp-integration路径，需重新选择新目录；本轮没有替你改侧栏或聊天归属。当前聊天原默认cwd仍是“论文”，本轮工具均显式使用新开发根，不能把改聊天标题当成更换工作区。

当前Python包、Git分支、公共Git宿主及其它工作树的FJSP名称保留，详见[本地工作区更名说明](../../docs/本地工作区更名说明.md)。本轮结束，不自动开展远端更名或新实验。
