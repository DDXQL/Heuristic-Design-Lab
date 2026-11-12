# Heuristic-Design-Lab：多问题实验与中文文档入口

- **本工作树：FJSP结果封装修复与有限接续（2026-11-12）**：[实际失败、累计限额、启动与取回](reports/flow-result-repair-20261112/README_ZH.md)。原运行在固定基线封装时报本地错误，API0；修复阶段保留失败占用2次，Mac最多6次、集群H/U复检最多4次求解，累计仍不超过原12次，API仍最多2次。默认 `tools/flow_check.py check-only`；真实请求、构造求解及Slurm提交均由用户启动。旧准备报告和下方历史入口不能代替本次真实验收。

- **TSP专用10H一条命令构建与离线汇报**：[协议V1](docs/TSP_H10_BUILD_PROTOCOL_V1.md)、[正式/工程命令与预算](reports/tsp-h10-build-prepared-20261101/REPORT_ZH.md)。默认真实请求关闭；H构建建议40次、恒选0次API、U预算另计，由用户终端分别启动。

- **EoH正式对照与TSP新版准备（2026-11-01）**：[方案、参数、check-only与小试命令](reports/eoh-tsp-prep-20261101/REPORT_ZH.md)。独立工作树准备；TSP compact离线验证完成，正式搜索未启动，EoH公平训练协议待定。
- **本工作树的方案A交付（2026-11-11）**：[冻结字段与计算口径](docs/state-a-v2/共同状态定义.md)、[FJSP/TSP接入和OBP准备说明](docs/state-a-v2/接入与交付说明.md)。接口 `common-state-a-v2`，10项＋辅助信息；方案B停止开发。仅执行 `python3 tools/check_state_a.py --check-only` 做离线检查。下方旧13项及旧负分搜索入口保留为历史兼容，不代表已经切换到方案A。

- **VS Code终端独立运行**：[中文操作手册](docs/终端独立运行实验.md)。Mock、固定候选/训练集评价、默认拦截的真实搜索；含启动/status/暂停/恢复/导出命令。
- **第一次使用**：[项目使用说明](项目使用说明.md)。
- **自己配置和运行实验**：[实验操作指南](docs/实验操作指南.md)。包含参数、真实API、训练集、启动、查看、安全暂停、恢复和汇总的完整命令。
- **阅读和修改代码**：[实验代码地图](docs/实验代码地图.md)。

正文已使用中文文件名。保留本文件作为GitHub及编辑器的标准首页；旧英文文档路径仅保留导航，避免历史链接失效。命令、配置字段和代码标识保持原名。

- **当前开发位置**：`/Users/DDXQL/Developer/Heuristic-Design-Lab`。旧Documents副本已退役到本机备份区；当前只在此目录开发。
- **多问题入口与旧路径映射**：[多问题结构与迁移说明](docs/多问题结构与迁移说明.md)。FJSP旧入口兼容，TSP复用独立工作树当前实现；未宣称跨问题质量已验证。
- **冻结与保存范围**：[Developer迁移说明](reports/迁移至Developer-20261027-v1/迁移说明.md)。早期缺口已由下方2026-10-28验收补齐；Git上传仍不代表原始runs全部上传。

- **新版共同状态与纯路由原型**：[使用与定义](docs/COMMON_ROUTING_V1.md)、[本轮验收报告](reports/common-routing-v1-20261029/REPORT_ZH.md)。13项数值＋历史/可用性已接入两问题；Mock多代与恢复、真实合成求解和并发已验收。尚无新算法质量结论。
- **旧版通用状态设计记录**：[通用状态接口设计V1](docs/通用状态接口设计V1.md)。保留七输入/五输入legacy；其中common-v0草案仍禁用，新接口使用独立common-v1版本。


## 已完成的TSP成果与本次集成

- [最新真实TSP小试](reports/tsp-pilot-20261028-complete/REPORT_ZH.md)：50逻辑任务/50尝试，validation最终选择静态U；不是演化稳定收益的证据。
- [TSP最新成果迁移与接入](docs/TSP最新成果迁移与接入.md)：来源c3b74b7、Developer整理版864c116、独立集成分支、历史资产保存与只读核验。
- [TSP问题定义与既有入口](docs/TSP_ADAPTER.md)：保留五输入、几何游程、SELECT/MIX和相对NN指标；共同状态草案仍禁用。

当前集成工作树为`/Users/DDXQL/Developer/Heuristic-Design-Lab`。原Developer整理分支和旧TSP树保持原样，历史运行禁止直接从迁移位置续跑；新示例真实请求仍默认未授权。本轮无API或正式求解。

## 2026-10-28：旧目录删除前验收

此前缺失的科研文件与旧Git对象已补齐：四个原目录36,504个源码/数据/实验文件均有内容一致的Developer保存位置。当前结论与查找工具见[删除前验收报告](reports/迁移删除前验收-20261028-v1/REPORT_ZH.md)。本轮没有删除原目录、没有推送；两份凭据由用户另行安全保存/决定处理。早期报告中的缺失清单是当时快照，不代表本次尚有同样缺口。

后续开发使用本集成目录；Developer主项目公共Git和h-usage虚拟环境仍是其依赖，不要仅保留集成文件夹。

## 2026-10-28：已上传并移出旧iCloud项目

最新集成分支`codex/tsp-integration-20261028`已上传GitHub。四个旧Documents项目已可恢复地移到`/Users/DDXQL/Backups/Heuristic-Design-Lab/legacy-20261028-v1/retired-worktrees/`；原始资产另有逐成员校验的独立归档及Git bundle。这些ignored原始资产仅本机保存，并非已上传GitHub。

[上传、备份与清理报告](reports/上传备份与iCloud清理-20261028-v1/REPORT_ZH.md)给出范围、SHA和复查结果。后续使用本集成目录；私有凭据在`/Users/DDXQL/.config/heuristic-design-lab/`。Developer主仓库公共Git及h-usage环境依赖继续保留。

## 本地工作区更名

当前目录为`/Users/DDXQL/Developer/Heuristic-Design-Lab`，由Git工作树移动完成；分支仍为`codex/tsp-integration-20261028`。见[更名与路径说明](docs/本地工作区更名说明.md)。

2026-10-29已核验GitHub更名为[DDXQL/Heuristic-Design-Lab](https://github.com/DDXQL/Heuristic-Design-Lab)，默认分支为`codex/tsp-integration-20261028`，首页展示最新集成版本；原`main`和历史标签保留，没有合并或改写历史分支。更名提交`a86cfd5`已推送。

Developer下五个关联工作树共享的`origin`现为`git@github.com:DDXQL/Heuristic-Design-Lab.git`。仓库ID和公开可见性未变；历史报告中的旧仓库名和路径保留为当时记录。本地备份及未跟踪资产不因仓库更名而自动上传。
