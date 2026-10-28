# 最新TSP成果迁移与多问题接入验收

本轮工程接入已完成。没有真实API、正式实例求解、已完成实验重评、搜索续跑、候选补生、追加预算或推送。验证仅使用只读证据、独立小型toy及Mock。历史实验结果保持原样。

## 实际来源和目标

|角色|位置与身份|
|---|---|
|最新来源|`/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-tsp-pilot`，`codex/tsp-pilot`，`c3b74b7ad5686e798e626514c7680951e7c2d943`|
|来源公共Git|`/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/.git`|
|Developer多问题基线|`864c116d46c193b4e0a5aba2ed1fe56e391337ca`，原分支`codex/multi-problem-state-v1`未改|
|独立接入分支|`codex/tsp-integration-20261028`，工作树`/Users/DDXQL/Developer/FJSP-Heuristic-Research-tsp-integration`|
|目标公共Git|`/Users/DDXQL/Developer/FJSP-Heuristic-Research/.git`|
|旧Developer TSP|仍为`7056f180a1d7f21c6b0d8d1144958c95f863b708`及原修改，未切换、清理或覆盖|

通过本地路径fetch保留来源历史，再把最新TSP和Developer多问题结构合为双父提交。最终提交号以当前分支`git log -1`及外部`/Users/DDXQL/Developer/迁移记录-TSP-20261028-v1/Final_receipt.json`为准，避免在提交自身内容中伪填提交号。导入引用为`refs/tsp-imports/latest-20261028`。来源7056f18之后4个提交及报告都进入Developer公共Git，见[历史导入记录](Git_history_import.json)。未改远端URL、仓库名称或本地主目录。

适用AGENTS核查：祖先和项目目录没有非空项目规则；`/Users/DDXQL/.codex/AGENTS.md`为空。实际独立目标可写，修改和toy输出均成功保存。初始与最终核验见[初始状态](Initial_states.json)、[最终保护核验](Final_preservation_audit.json)。

## 现场与原修改保护

来源正式v2已completed；全局账本50个逻辑任务、50次API尝试，没有未知请求、未完成评价、预留任务或活动锁，正式执行进程已结束。v1根保留当时paused状态，v2承接其累计账本；不把旧partial根覆盖成完成状态。见[归档状态](Archive_status.json)。

旧Developer TSP有7个已跟踪修改，加上未跟踪文档、校验脚本和早期日志/快照。14个实文件的比对结果是6个已包含于最新提交、6个匹配来源祖先但已由新提交替代、2个独有早期说明。`.venv`仅记录链接，不分发环境。所有原文件最终SHA仍与初始记录相同。

- [完整逐文件分类与哈希](Dirty_comparison.json)
- [原修改补丁](Developer_TSP_dirty.patch)
- 独有文档：[TSP_ADAPTER.md](Developer_unique_documents/docs/TSP_ADAPTER.md)、[TSP_EXECUTION_REVISION_V2.md](Developer_unique_documents/docs/TSP_EXECUTION_REVISION_V2.md)
- 完整定点快照：`/Users/DDXQL/Developer/迁移记录-TSP-20261028-v1/Developer_dirty_snapshot/`

没有将旧文档或旧代码反向覆盖最新TSP；Developer已有多问题分发、core、FJSP和状态门禁保持基线字节一致。三个原工作树的HEAD、分支、公共Git目录、工作区状态均保持初始值。

## 成果与资产位置

最新正式结果在[原报告](../tsp-pilot-20261028-complete/REPORT_ZH.md)，包括冻结H、静态基线、P0、最终U、IND/EVO、validation、confirmation与transfer。这里保留既有结果，不产生新科学结果。141个历史报告文件与c3b74b7字节一致。

全部TSP被忽略运行资产位于：

`/Users/DDXQL/Developer/FJSP-Heuristic-Research-tsp-integration/archives/tsp-c3b74b7-20261028-v1/workspace/runs/`

共9,491个文件、50,278,240字节，保存协议、数据身份/坐标、H/P0/U、提示词、请求响应、全局账本、checkpoint、认证及首解/复检结果。6,845个文件使用已核验Developer副本，2,646个按明确清单从现有原始证据包恢复；没有触发源云端文件批量下载，也没有重新全量归档。

|资产|校验|
|---|---|
|[完整原始包](../tsp-pilot-20261028-complete/Raw_evidence.tar.gz)|SHA256 `00d618ca9f3bc759639ac484bca77cdfdc5570799c9e24201b79c0c68e05440b`|
|[partial原始包](../tsp-pilot-20261026-v1/Partial_raw_evidence.tar.gz)|SHA256 `102082593f682e1178abb0eb2a6ba24092f24c32a95021a44e3c8176b4f1da00`|
|资产Manifest|SHA256 `c034e3615c49013d89e07fe40c77ea94d968d28d714f63fc22db51b3474da154`|

两原始包与来源一致，9,491个文件逐一验SHA通过；本轮指定TSP资产未迁入文件清单为`[]`。详见[迁移回执](Asset_copy_result.json)及[逐文件清单](Assets_manifest.json)。原真实配置单独保存在vault的`Sources/experiments/tsp/configs/pilot-real.json`，哈希与历史Protocol一致。当前示例仍默认禁用真实请求，见[配置身份说明](Config_preservation.json)。

`archives/`及环境链接不进入Git；资产仍是本地保存，未推送。新Git提交保存来源历史、原有报告/证据包、接入实现和迁移清单。未复制凭据、环境文件或打印密钥正文；原证据包成员名核验也未发现凭据文件。

## 目录与接口接入

|职责|位置|保证|
|---|---|---|
|问题分发、状态版本|`experiments/manage.py`、`core/state_contracts.py`|沿用Developer结构；共同状态草案禁用|
|任务、父代、种群、API/预算、checkpoint、停止恢复|`core/{adapter,execution,search}.py`及已有llm客户端|复用一套核心，未另建搜索框架|
|TSP实例、五维U状态、H特征、合法动作、输出校验|`problems/tsp/{data,solver,candidates}.py`|与最新来源一致，不变成FJSP七输入|
|游程、NN比例、完整实例、首解复检、T30|`solver.py`、`evaluation.py`及共享mixing/lifecycle|与来源科学语义一致|
|提示词|`problems/tsp/prompts.py`、`operations.Adapter.build_prompt`|保留模板，沿用Adapter拼装边界|
|阶段与累计预算|`problems/tsp/campaign.py`、`operations.py`|保留专用阶段控制器，复用通用执行；增加外部历史路径拒绝|
|历史证据阅读|`experiments/tsp/inspect_archive.py`|只读Manifest映射和SHA校验，无API、求解或resume入口|

城市0出发及闭合边、float64未取整欧氏距离、合法未访问动作、最低城市号同分、SELECT/MIX及min-max常数列0、NN参照Fitness均保留。NN不称为下界。没有修改历史协议绝对路径、重算身份或直接续跑旧campaign。

新增路径门禁拒绝把证据目录交给run/resume/stop；stop先核验身份。只读工具将旧Documents路径当作Manifest命名空间映射到本地证据文件，不访问旧绝对路径，不改写任何记录。

## 提示词核对及影响范围

[提示词审计](Prompt_audit.json)覆盖全部50份实际请求：使用原冻结H顺序和父代重建的当前模板，与checkpoint和实际发送提示逐字一致。历史提示原样冻结，模板签名、成员说明与输出约束未改。未来模板仅保留现有ProblemAdapter拼装边界，没有本轮策略优化。

发现一处候选说明解释差异：`EVO_801/000`说明称晚期偏向nearest-neighbor，代码实际返回单成员H0；冻结H0是manual_far_early，NN成员是H1。模板编号本身匹配。不能将该代码解释为精确切换NN；原响应与说明保持原样。这不改变实际执行、Fitness或选择，该候选没有通过validation成为最终U。

## 验证结果与边界

|验证|结果与证据|
|---|---|
|来源历史、资产及原工作树|通过；Git连通性退出0、全部TSP资产SHA通过、原工作区未变|
|新旧状态/动作/游程/评分/首解复检|独立3/4/7城市toy × 4策略，共12组完全一致；[比较](Toy_comparison.json)、[来源轨迹](Source_toy.json)、[接入轨迹](Integrated_toy.json)|
|接口、MIX、状态、语言、预算、Mock与恢复|21项通过；[日志](Tests.log)|
|help/doctor/check/plan实际入口|10条通过，在网络、API客户端和两问题求解器被禁止条件下执行；[记录](CLI_preview_checks.json)|
|停止与恢复|Mock候选边界暂停/恢复，原时钟、账本、首响应不变，锁释放；未知状态、篡改身份拒绝|
|最小FJSP回归|2策略/4遍toy，Cmax7、LB6、Fitness−1.166666666667及排程哈希与旧认证toy相同；[对比](FJSP_toy_comparison.json)|
|正式实验/API|本轮均为0；未复测正式60实例、未启动正式Mock campaign或改研究协议|

比较统一使用Developer Python3.12.10/numpy2.5.4。初次工程夹具误用系统3.13生成canonical键，两边均被身份保护正确拒绝；失败夹具和日志保留，之后仅在共同3.12环境重建工程夹具。历史候选键未改，保护未放宽。另一初始Mock测试夹具修改协议后未同步checkpoint身份，也被正确拒绝，已修正测试夹具并保留首次失败日志。

工程及文档的diff空白核验通过。原修改补丁有9行标准unified-diff空白上下文标记，按原始证据逐字节保留，没有为消除空白提示改写证据，见[检查回执](Diff_check.json)。

最小复核命令（均不调用真实API）：

```sh
cd '/Users/DDXQL/Developer/FJSP-Heuristic-Research-tsp-integration'
.venv/bin/python -B experiments/manage.py --problem tsp --help
.venv/bin/python -B experiments/manage.py --problem tsp check --config experiments/tsp/configs/pilot-real.json
.venv/bin/python -B experiments/manage.py --problem tsp plan --config experiments/tsp/configs/pilot-mock.json
.venv/bin/python -B experiments/tsp/inspect_archive.py --receipt reports/TSP最新成果迁移-20261028-v1/Asset_copy_result.json --verify-all
PYTHONPATH=code:. .venv/bin/python -B -m unittest tests.test_tsp_integration -v
```

当前使用入口、接口文件和完整命令边界见[接入说明](../../docs/TSP最新成果迁移与接入.md)。旧报告和协议中的Documents命令保留为历史记录，不代表现在允许续跑。

## 尚未迁入及旧目录保留

本任务TSP范围内未迁入文件为0。其他FJSP历史资产没有借本轮扩大恢复：保留[此前具体路径清单](Earlier_unretrieved_assets_reference.json)，共4,121个旧记录（主树505、h-usage-space 2,648、u-single-experiments 968）；该数字是2026-10-27旧清单，不能当作本次重新全量审计后的当前缺失总数。此前还有未完整取得的源Git旧对象/日志；本次Git连通性通过只证明已保留引用可达历史完整，不宣称全库字节备份。

以下目录仍不能在本轮删除：

- Documents原主仓库及其公共`.git`、FJSP相关工作树：尚有其他历史资产及旧Git证据未完整闭环，其他工作树仍依赖公共Git。
- Documents原TSP：本批成果虽已保存，仍按授权保留原工作树注册和源关系；删除需单独清理决策，不能牵连未取得的旧库资产。
- Developer旧TSP：原7处修改、早期独有文档与原工作树完整保留，集成成果已放入独立新目录，未擅自处理旧工作树。

工程接入到此结束，不自动安排新研究。
