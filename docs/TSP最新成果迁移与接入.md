# TSP最新成果迁移与多问题接入（2026-10-28）

本轮仅工程迁移与接入：真实API=0，正式实例求解/搜索续跑/已完成实验重评=0。独立toy、Mock与纯离线核验已执行。没有改变TSP算法或启用共同状态草案。

## 工作位置、提交与分支

- 最新来源：`/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-tsp-pilot`，`codex/tsp-pilot`，`c3b74b7ad5686e798e626514c7680951e7c2d943`。
- Developer整理基线：`864c116d46c193b4e0a5aba2ed1fe56e391337ca`，`codex/multi-problem-state-v1`。
- 独立集成工作树：`/Users/DDXQL/Developer/FJSP-Heuristic-Research-tsp-integration`，`codex/tsp-integration-20261028`。
- 原Developer TSP树仍是`7056f18`及其原未提交内容；没有切换、清理或覆盖该工作树。

两边公共Git目录不同。通过本地路径fetch把最新引用引入Developer的`refs/tsp-imports/latest-20261028`，再在独立工作树作双父提交merge，保留原提交历史及Developer的多问题整理。没有用源码复制替代历史，没有推送或改远端URL。最新来源在7056f18之后的4个提交全部保存；Git连通性核验退出0。

旧Developer TSP的14个文件已比对、保护：6个与最新提交相同，6个已存在于祖先提交并由后续版本替代，2份独有的早期说明文档单独保存。详见[未提交内容比对](../reports/TSP最新成果迁移-20261028-v1/Dirty_comparison.json)。完整定点快照在`/Users/DDXQL/Developer/迁移记录-TSP-20261028-v1/Developer_dirty_snapshot`，没有处理其他工作树的修改。

## 最新成果与运行资产在哪里

|内容|Developer保存位置|性质|
|---|---|---|
|最新代码与提交历史|当前集成工作树及Developer公共Git|最新来源c3b74b7进入merge历史|
|完整TSP结果、H/P0/最终U、候选与证据包|`reports/tsp-pilot-20261028-complete/`|与来源提交相同，不重写旧报告|
|前期解析失败、修订与partial证据|`reports/tsp-pilot-20261026-v1/`、`reports/tsp-pilot-20261027-continuation/`|保留当时状态和原始响应|
|全部TSP忽略运行资产|`archives/tsp-c3b74b7-20261028-v1/workspace/runs/`|独立只读证据目录，不是可续跑run|
|原真实配置字节|`archives/tsp-c3b74b7-20261028-v1/Sources/experiments/tsp/configs/pilot-real.json`|SHA与旧Protocol.config_sha256相同|
|本轮清单、检验、冲突选择|`reports/TSP最新成果迁移-20261028-v1/`|新的迁移回执，不替代历史身份|

运行资产共9,491个文件、50,278,240字节，含三组Mock及真实v1/v2各阶段。6,845个复用已有Developer副本并核对SHA；2,646个从已核验的原始证据包按明确清单恢复。没有反复全量归档，没有触发云端全量恢复。本次TSP指定资产未迁入文件为0；全部文件SHA核验通过。

完整证据包SHA256：`00d618ca9f3bc759639ac484bca77cdfdc5570799c9e24201b79c0c68e05440b`。
partial包SHA256：`102082593f682e1178abb0eb2a6ba24092f24c32a95021a44e3c8176b4f1da00`。

`archives/`是本地资产，不进入Git，也不等于已上传。Git保存来源历史、重要报告和已有证据包；资产完整清单及SHA另随迁移报告提交。没有复制凭据、分发环境文件或打印密钥正文；本地`.venv`只是指向Developer已有环境的未提交链接。

## 实际目录、接口与依赖

|边界|实际实现|本轮处理|
|---|---|---|
|统一分发/状态门禁|`experiments/manage.py`、`core/state_contracts.py`|保留864c116；FJSP七输入、TSP五输入，common草案仍禁用|
|通用执行/父代/种群/记录/暂停恢复|`core/execution.py`、`search.py`、`adapter.py`及llm桥接|保留同一套core，字节与基线相同|
|TSP数据、状态、动作、H/U准入|`problems/tsp/{data,solver,candidates}.py`|与c3b74b7对应源码字节相同|
|TSP几何/MIX/T30/完整评价|`solver.py`、`evaluation.py`及共享mixing/lifecycle|与来源一致，未重新设计算法|
|TSP问题提示|`problems/tsp/prompts.py::build`|与来源字节相同；通过Adapter.build_prompt拼装|
|TSP阶段和全局账本|`campaign.py`、`operations.Adapter`|合入最新窗口/账本继承实现；只增迁移路径保护|
|当前TSP CLI|`experiments/tsp/manage.py`|合入最新续接参数；仍由同一core执行|
|只读历史查看|`experiments/tsp/inspect_archive.py`|新增清单映射/SHA核验；无模型、求解和resume入口|

保留城市0出发/返回、每次选未访问城市、未取整float64欧氏距离、动作同分最低城市号。SELECT和最多双成员MIX、单成员原分数/双成员min-max、常数列0、权重及同分规则不变。保留`-mean(length/NN_length)`、完整实例结果、首解复检、T30、源身份和预算保护。NN是最近邻参照，不是下界。没有把TSP改成FJSP七输入，没有新状态计算器或第二套搜索框架。

当前未来真实示例仍`real_requests_authorized=false`。原历史真实配置保持true并存于证据目录和原Git历史，不把当前示例开关改动追写到历史协议。

## 历史身份与当前入口

原Protocol、请求/响应、checkpoint、数据引用中的Documents绝对路径全部不变。只读查看器将这些字符串作为源命名空间中的文件名映射到证据清单，逐文件验SHA，**不访问旧绝对位置、不改写历史路径、不伪造当前执行身份**。

当前执行入口只接受当前工作树`runs/`的运行，并拒绝外国配置绝对路径；暂停请求也先通过此门禁。归档不能直接run/resume/stop，不能因搬家重置账本/截止或继续已结束campaign。新路径保护只约束I/O和身份，不修改问题状态、动作、评分、候选语言或提示。

```sh
cd '/Users/DDXQL/Developer/FJSP-Heuristic-Research-tsp-integration'
.venv/bin/python -B experiments/manage.py --problem tsp --help
.venv/bin/python -B experiments/manage.py --problem tsp doctor
.venv/bin/python -B experiments/manage.py --problem tsp check --config experiments/tsp/configs/pilot-real.json
.venv/bin/python -B experiments/manage.py --problem tsp plan --config experiments/tsp/configs/pilot-mock.json

# 历史结果只读查看和全部迁入文件核验：无API、无求解
.venv/bin/python -B experiments/tsp/inspect_archive.py \
  --receipt reports/TSP最新成果迁移-20261028-v1/Asset_copy_result.json --verify-all
```

TSP直接旧入口的help/check/plan同样保留；FJSP仍通过`experiments/fjsp/manage.py`或原`experiments/tier2/manage.py`调用原组件。新旧CLI预览共10条实际入口检查，在网络、模型客户端和两问题求解器被禁止的条件下通过。上述命令没有启动新实验。

## 提示词与自然语言说明核对

1. 历史实际提示：50份全部按原始SHA保存。
2. 当前TSP模板：按原有序H和原父代渲染后，50份逐字等于实际发送内容。问题说明、五参数、成员块和输出约束没有改写。
3. 未来通用接口：继续使用ProblemAdapter.build_prompt这个拼装边界；本轮没有引入新版共同模板/状态。

具体解释边界见[提示核对](../reports/TSP最新成果迁移-20261028-v1/Prompt_audit.json)：`EVO_801/000`原说明写“favor nearest-neighbor late”，实际晚期返回单成员H0；冻结H0为manual_far_early，标为NN的是H1。不能将这段代码解释为精确切换至NN成员。当前模板H成员块与实际冻结编号匹配，没有发现模板编号错配。这是候选说明的解释差异，未影响原执行/Fitness/选择；该候选未被validation选中。原响应和说明均未修正。

## 验证范围

- 9,491个运行文件完整性核验、两个原始证据包SHA相同；历史batch为completed、50任务/50尝试，无未知请求/评价或活动锁。
- 源码关键组件字节比较：core未改，TSP状态、候选、数据、游程、MIX/T30、模板和评价与来源一致。
- 同一Python3.12.10/numpy2.5.4运行时，在独立3/4/7城市toy上比较4种策略，共12组。新旧所有状态、合法动作/分数、权重、选城、闭合游程、NN比例、H调用和首解/复检完全相同。不是重评原60个正式实例。
- 21项接口/状态门禁/Mock/保护检查通过。Mock用假评价，不调用真实求解器；候选边界暂停、恢复后原时钟/预算/首份响应不变，未知预留与身份变化拒绝。
- FJSP最小toy2份策略/4遍，Cmax7、LB6、Fitness−1.166666666667及排程哈希与原认证toy一致。没有重新求解Behnke或其他正式实例。

初次测试夹具由系统Python3.13生成键、比较进程为3.12，两边均正确拒绝不匹配键；已保留失败夹具并在共同3.12下创建工程夹具。历史候选键没改、保护没放宽。完整回执见[迁移报告](../reports/TSP最新成果迁移-20261028-v1/REPORT_ZH.md)。

## 仍应保留的旧位置

- Documents主仓库及原FJSP相关工作树：其他历史被忽略资产、旧Git对象/日志等尚未全部取得。本次仅恢复TSP明确清单，不宣称旧库全量备份。具体旧清单在迁移报告的Earlier_unretrieved_assets_reference.json（4,121项旧清单，非本次重新审计的当前总数）。
- Documents TSP目录：本批代码和资产已保存，但本轮仍完整保留其原工作树注册及公共Git关系，不执行删除。旧库清理需另作全库闭环和显式操作。
- Developer旧TSP目录：其7056f18、原7处未提交修改、独有早期文档仍保留；当前权威集成成果在新工作树，不以旧副本覆盖最新成果。

本轮结束后不自动安排研究、生成、正式求解或搜索续跑。
