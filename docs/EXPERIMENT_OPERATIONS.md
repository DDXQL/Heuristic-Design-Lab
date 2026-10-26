# 配置、复用范围和运行边界

主操作流程见根README；代码调用关系见[代码地图](EXPERIMENT_CODE_MAP.md)。本文件解释参数，不重复维护另一套研究进度。

## 现有组件核查

|组件|可复用位置|当前边界|
|---|---|---|
|实例/清单/LB|`llm4ad/.../fjsp_set/instances.py`、`offline_v2.lower_bound_v5`、数据协议`instances`|新入口支持项目格式fjsp或已有协议所指文件；不自动下载/划分/改数据。|
|冻结H/评分|`research_real/assets.py`、`usage_v2/execution.py`|封存10H直接复用；资产seal防误改，不能替代真实行为审查。|
|10H通用U|`usage_v2`、`tools/b1_usage_prompts.py`|SELECT/MIX及自由I1/CROSS/MUTATE可复用；新封装space=ten_h。|
|H01权重控制|`tools/h01_weight_search.py`、`ind_evo_h01.independent_prompt`|alpha互补、只有H0/H1；CROSS固定5父代。|
|生成/API|`real_transport.py`、`AttemptJournal`、`WireRecorder`|新封装按候选/尝试计数，无费用认证门禁；真实网络接入本轮未试。|
|P0/遗传机制|`select_parents`、`ranked`|新封装用显式P0并在当前数据上评价；不复用Search旧类把未知评价自动记失败的恢复分支。|
|求解/认证|`cross_feedback_ab_execute.worker/certify`、T30生命周期|评分、首解复检、正常退出、源码身份保持；新控制器只安排任务。|
|控制/汇总|`experiment_ops*.py`|新run配置化、安全边界暂停与恢复；旧campaign只有只读查看。|
|历史专项|`ind_evo_h01*`、`h01_external*`、`cross_feedback_ab*`、Baseline/Fusion/A4脚本|路径/名单/窗口/源码绑定经常固定，不能只换参数重开；不移动或重写原记录。|
|暂未通用化|自动LLM生成并补满新P0、跨run历史质量缓存、账户级并行预算、任意K的H、Tier1、任意算子|如实未提供。新封装不是完整成熟实验平台。|

旧`experiments/tier2/usage_v2/run.py`的prepare会重评10H，并非纯预览；其旧INIT是SELECT-only。旧`tools/cross_feedback_ab.py`仍保留当时费用草案，新的操作入口只调用其父代审计，不调用费用门禁。旧launchd工具`tools/local_long_job.py`仍是synthetic-only；不要拿它直接启动正式FJSP。

## JSON参数

与现有项目相同使用JSON，provider直接复用`ProviderConfig`字段。薄封装增加`schema=experiment-operations-v1`声明，避免把旧专用协议当可变配置。`check`/`plan`校验和解析但不建run、不求解、不创建API客户端。`prepare`只复制/冻结文件与模板，也不求解。

|类别|字段|用途|
|---|---|---|
|实验|`type, question, space`|fixed/rules/pair/ind/evo/cross_ab；h01或ten_h。|
|数据|`dataset.files`或`dataset.protocol`，`dataset.role`|显式文件列表，或已有协议的instances；engineering/train/confirmation。列表顺序参与身份。|
|H|`H_source`|已封存10H JSON；h01可用[0,1]，ten_h可用[0..9]。|
|固定U/P0|`strategies`、`p0`|每项唯一id及alpha/member/code_file之一。H01仅接受互补权重；通用静态双成员可直接提供合法U代码文件。|
|既有规则族|`rule_filter.tau/alpha_before/alpha_after`|原21规则族的子集；tau=.25/.5/.75，alpha=0/.5/1；空filter为完整21；不扩展新规则。|
|搜索|`search_seed, candidates, population_size, generations, cross_per_generation, mutate_per_generation, cross_parents`|IND候选数；EVO显式P0规模及每代CROSS/MUTATE。h01保持N5/5交叉父代；ten_h可配置2–5交叉父代且不超过N。|
|固定父代AB|`parent_pairs, repeats`|只接受已认证的历史自由P0，两组同一对同顺序；必须完整匹配train21/H/LB，不能拿B2五静态P0冒充。|
|提示|`prompt_overrides`|可选I1/CROSS/MUTATE模板文件；恰有一个`{{BASE_PROMPT}}`。默认为空，逐字复用原模板。AB拒绝override以保持唯一反馈差异。|
|API|`api_mode, real_requests_authorized, provider`|disabled/mock/real；真实调用要求配置true和run/resume显式--allow-api；凭据只从provider.api_key_env取，不自动读另一工作树env。|
|请求规模|`api_attempt_cap, per_candidate_attempt_cap`|每逻辑候选最多2尝试；失败不补员。退避目前内部固定2秒，协议保存完整transport_config。|
|评价|`solve_seed=501, instance_timeout=30`|当前入口强制保持，不能改JSON绕过科学协议。完整首解复检、动作/归一化/正常退出规则非CLI参数。|
|窗口|`window_seconds`|最多43200秒；首次run持久化；新任务预留最坏请求+求解余量。暂停/恢复不重置。|
|工程Mock|`mock_delay_seconds`|仅mock+engineering，0–2秒，用于离线控制验收；不进入真实请求配置。|
|CLI参数|`--config, --run-dir, --allow-api, --background, summary --write`|配置/目录/明确API启动/脱离启动控制进程/本地汇总；不是科学调参开关。|

plan展示最坏物理评价量，含P0。缓存只在同一个新run内按U AST和冻结上下文复用，逻辑槽位仍计数；没有自动历史缓存导入。P0不会神奇免费继承旧Fitness。数据改为train21时其P0成本和新增成本都会增加，先看plan再run。

### 环境、模板和输出快照

prepare保存`Resolved_config.json`、`Protocol.json/.sha256`、`Tasks.json`、H/Parents、输入副本、source_files/protected_files、Git提交、Python及模板示例。实际每次提示位于`prompts/`，首份完整响应位于`responses/`，每次尝试及回传位于`API_attempts.json`和`wire_responses/`。

模板示例不是随机选定的最终父代；真实提示按已记录父代现场渲染保存。IND不含P0/历史；默认CROSS/MUTATE不含成绩；只有cross_ab的B添加完整绑定成绩。新提示文件或源配置改动会导致旧run恢复被拒绝。建议先复制示例为自己的配置，之后不要改这个已绑定文件；换配置就用新目录。

## 控制与异常

`stop`请求候选边界暂停，当前生成和完整评价认证后落盘才退出。SIGINT/SIGTERM也只设置边界停止标记；不是强杀命令。确认checkpoint.phase=paused且锁已解除才resume。每次结束回执另存`end_receipts/`，旧暂停请求保留在`control/`，resume只确认已处理序号。

窗口到期是expired/partial，不能自动续期。断电、SIGKILL或未提交任务可能留下未知reservation/锁；入口明确拒绝自动清理或重复请求/求解。连续3个逻辑传输失败停止。普通已认证求解超时是候选无效，可继续其他预定候选；完整Fitness=null。

后台使用原有detach函数：独立session、文件日志、忽略SIGHUP，临时caffeinate绑定worker。工程验收验证“启动命令进程退出后继续”和暂停恢复；不承诺Mac合盖、休眠、注销、重启、App关闭时所有系统行为。电脑仍须有电且保持唤醒。无需Codex持续监控；脚本自己记录、汇总和结束。

search_seed控制EVO父代抽样；IND只记录重复身份，模型请求不传seed。不同重复编号不保证严格随机配对，改变求解seed也不是新的搜索重复。

新入口只有单run写锁，不提供多个真实API campaign的账户级并发协调或跨run费用上限。不要把启动多个独立目录理解为共享同一候选预算。真实provider服务当前是否可用本轮未请求验证；Mock不能保证服务可用或模型输出质量。

## 结果口径

- `logical_generation`：开始过的逻辑生成任务；失败占槽，不是有效代码数。
- `API_attempts`：实际尝试/保守预留次数，含重试和未知状态；不等同完整响应。
- `complete_responses`：首份完整响应，不因代码无效再生成。
- `certified_strategies`：完整实例集评价有效的任务数，缓存复用可以贡献任务数；不等同新增物理求解数。
- `Per_instance.csv`标明`complete_candidate_valid`；失败的成功前缀仅为明细，不参与正常完整Fitness。
- `new_champion`仅指新增生成子代；固定评价另有`fixed_evaluation_champion`；已见最好包含P0，不能把继承P0算新发现。
- Token已知值和未知尝试分别列；实际币种/扣点未核实则null，无价格认证前置门禁。

`summary --write`输出`results/Summary.md`（可直接贴回讨论）、JSON、Candidates/Per_instance/Best_so_far/Evaluation_costs.csv。摘要是确定性事实，不调用LLM、不替用户决定后续研究。对历史run只读已有报告，缺少标准摘要时指向原专用报告入口，不伪造通用转换。
