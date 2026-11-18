# 按顺序运行剩余实验

本树新入口：[R14公共轻量流程离线交付](docs/R14公共轻量流程-离线交付-20261118.md)。当前旧TSP501优先使用[已冻结的R13 Mac菜单](docs/R13旧TSP501-Mac独立菜单-20261118.md)，保持旧身份；R14只用于尚未启动的新批次。未部署、未获真实请求/Slurm授权。1000个成功返回仅做[只读差异评估](docs/成功返回1000口径-只读差异评估-20261118.md)，没有实施。

**R13新增入口：[TSP候选源码接入](docs/TSP候选源码接入-20261117.md)。** 本树登记已采用的TSP参数和第三方LKH候选来源，仅完成本地源码导入与离线检查；未编译、未上传、未执行LKH或正式搜索。下列R12及更早指南保留历史身份，不向旧树覆盖新配置。

**权威入口：[六组实验按序运行](docs/六组实验按序运行.md)** · [18份运行清单](docs/六组实验18份清单.md)。此工作树用于R12后续新实验；当前R11两份EoH沿原版本完成。API压力测试暂搁置，真实启动均手动。下方旧版本入口仅保留作历史，新实验以本页顶部指南为准。

# Heuristic-Design-Lab：多问题实验与中文文档入口

**2026-11-15统一交付从[统一实验包操作指南](docs/统一实验包操作指南.md)开始。**当前建议来源为`Heuristic-Design-Lab-triad-concurrent-20261115`，修复版H提示与共享请求准入已整合；原R5p1/R6p2/r7保留历史身份，不混用命令。18份搜索中FJSP双层501/502已完成并只读登记，另16份待跑。代码准备、资产实算、计算节点验收、完整搜索分别记录。参见[验收清单](docs/一次性交付实验包验收清单.md)和[中文实验名](docs/实验名称与当前进度.md)。真实动作仍由用户在终端执行。

本工作树新增入口：[两个独立种子同时运行（R6）](experiments/triad/parallel/README_ZH.md)。两个搜索共享API总并发1的请求路径已接入并通过本地Mock；当前仅CODE_READY，尚未上传或取得集群／真实API验收。旧R5p1部署与616362保持原样。原`batch.py`及`serial_queue.py`仍属于串行方案，不能作为R6并发入口。

## 本轮实验：从这里开始

先读[三问题实验运行入门](docs/三问题实验运行入门.md)：用通俗中文说明实验、真实命令和终端输出。更详细的参数与实现见[六组实验包说明](experiments/triad/README_ZH.md)。

本轮在FJSP、TSP、OBP上比较两种搜索：双层方法先固定H集合，再搜索选择规则U；EoH直接搜索一条H。每组每个独立种子运行1000次演化尝试，初始化和H构建另计。最佳固定H作为额外评价参照，不另开一组模型搜索。U读取14项共同状态，每步只选一个H，求解时不调用大模型。

六组编号为fjsp-u、fjsp-eoh、tsp-u、tsp-eoh、obp-u、obp-eoh。多个种子各自从头搜索；暂停恢复仍是同一次运行。具体重复数和未批准参数按确认配置执行。

在本项目根目录执行下面这条命令，可以先看六组缺什么，不请求模型、不求解、不读密钥：

~~~bash
bash experiments/triad/mac.sh plan
~~~

看到pending或null，表示还有输入或批准条件待补，不代表实验已经启动。脚本准备、离线检查、真实运行及算法结果分别记录；当前不能因为有六组脚本就认定六组均可正式启动。

| 常见输出 | 通俗含义 |
| --- | --- |
| pending | 还缺配置、资产或批准条件，先补缺项 |
| evolution_attempts | 已占用多少次演化尝试，长实验目标是1000 |
| confirmed_sends | 已确认实际发送的模型请求数，不等于有效程序数 |
| best_J | 当前最好训练成绩，越小越好；中途结果不是最终泛化结论 |
| paused | 已暂停，按原运行恢复，不新开一份搜索 |
| completed | 该份搜索结束；还需核对是否完整、是否有有效冠军 |
| result_hashes_verified | 下载文件核对一致，不等于实验成功或方法更好 |

指南包括：Mac与集群的启动、查询、暂停、恢复、取回、汇总；best_J、尝试数、实际发送、失败、重复、未知用量、Slurm作业状态的含义；以及如何查看已有Mac U501而不重开一份运行。正式请求、求解和Slurm提交由用户手动执行。

## 当前集群首份：FJSP EoH优先

[首批集群启动说明](experiments/triad/cluster-fjsp/README_ZH.md)集中列出已采用参数、一次交互部署、第一阶段最多4次的双作业API1验证、首份手动提交及查询／暂停／恢复／取回。模型请求和Slurm仍由用户启动；Mac合盖不会终止已提交作业。API2和自动串行队列不作为首份前置，当前不宣称两个正式搜索已经并发。

已采用每组3次、501／502／503、1000次演化及旧U501只读纳入；FJSP EoH N10、初始化HTTP最多20、累计1020及有限初始化门槛也已采用。新U预算、TSP LKH、OBP资产分别列缺，不阻塞首份EoH。当前远端状态须用新inventory核对，不能把旧验收当作今天已部署。

## 实验结束后：图表、复现与保存

[实验结束与归档](docs/实验结束与归档.md)给出离线check-only、单次收尾、批次汇总和完整备份命令。新入口`experiments/triad/closeout.py`只读已有export／summary，不导入客户端或求解器。每张图有PNG、SVG、PDF及来源CSV；包括全部演化尝试、交叉／变异、父代／子代、生存选择、失败／重复、冠军局部关系、逐实例成本和按member_sequence统计的H选择。初始化另标，内部负J只转一次，缺记录不重跑补图。

运行代码版本与后处理版本分别记录。完整原始ZIP在transfer-outbox，精简成果在独立results目录；GitHub待推送清单明确列出文件、版本、排除项和大文件。不会默认把runs入Git，不自动push或上传Release。原r3保留；r4增加离线收尾，正式搜索门禁不变。

| 版本／运行 | 身份与结果 | 保存状态 |
| --- | --- | --- |
| r3工程包 | 源冻结6effcf9；公共执行923781f | 已本地打包核验，原ZIP保留 |
| 已有Mac U501 | 运行提交19a86bf及实际源码清单；初始化8、演化1000，冠军G076-001-CROSS，训练J=1.028064685792435 | 原运行只读保留；离线成果见results/fjsp-u501-closeout-20261114-v1/REPORT_ZH.md，实际完整ZIP位置及SHA见其中archive-receipt.json |
| r4／closeout-v1 | 后处理版本见成果reproduction.json，工程版本见新ZIP release.json | 本地生成／提交与远端上传分别记录；以交付回执为准 |

## 历史入口与工程交接

以下记录保留原版本、当时状态和命令。阅读本轮三问题实验时，优先使用上面的指南；旧10项／13项、旧评分和已关闭验收不自动成为本轮协议。

- **本工作树：单次FJSP长演化工程交付**：[执行层、配置、离线证据与单作业交接](reports/fjsp-execution-20261112/HANDOFF_ZH.md)。接入v3完整状态；研究参数与真实启动许可待单独冻结，旧入口不作为本轮命令。

- **Mac API密钥保存一次（2026-11-12）**：[钥匙串设置与新启动入口](reports/flow-result-repair-20261112/KEYCHAIN_ZH.md)。本机保存一次，后续自动读取；不改冻结客户端或累计预算，集群不接收密钥。

- **本工作树：FJSP结果封装修复与有限接续（2026-11-12）**：[实际失败、累计限额、启动与取回](reports/flow-result-repair-20261112/README_ZH.md)。原运行在固定基线封装时报本地错误，API0；修复阶段保留失败占用2次，Mac最多6次、集群H/U复检最多4次求解，累计仍不超过原12次，API仍最多2次。默认 `tools/flow_check.py check-only`；真实请求、构造求解及Slurm提交均由用户启动。旧准备报告和下方历史入口不能代替本次真实验收。

- **TSP专用10H一条命令构建与离线汇报**：[协议V1](docs/TSP_H10_BUILD_PROTOCOL_V1.md)、[正式/工程命令与预算](reports/tsp-h10-build-prepared-20261101/REPORT_ZH.md)。默认真实请求关闭；H构建建议40次、恒选0次API、U预算另计，由用户终端分别启动。

- **EoH正式对照与TSP新版准备（2026-11-01）**：[方案、参数、check-only与小试命令](reports/eoh-tsp-prep-20261101/REPORT_ZH.md)。独立工作树准备；TSP compact离线验证完成，正式搜索未启动，EoH公平训练协议待定。
- **方案A逐H历史补充**：[接口与FJSP接入清单](docs/state-a-v3/接口与FJSP接入.md)。`common-state-a-v3`保留原10项并增加4个逐H数组；检查命令为 `python3 tools/check_state_a_v3.py --check-only`。旧v2接口与下方历史记录继续保留。

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
