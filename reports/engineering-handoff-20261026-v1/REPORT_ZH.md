# 项目工程整理与使用交接验收

日期：2026-10-26。工作区：`FJSP-Heuristic-Research-h-usage-space`；分支：`codex/h-usage-space`。整理基于`ded14d8c272465be5d0e3b0776808e2841e0fc2d`，仅本地提交，不推送。

本轮完成工程入口与交接，没有开展新的科研比较。真实生成API调用0；正式实例新增求解0。检查中的本地求解仅使用独立手写的2作业/2机器、4工序toy。

## 交付内容

用户入口是[根README](../../README.md)。[代码地图](../../docs/EXPERIMENT_CODE_MAP.md)解释函数调用和修改位置；[配置与边界](../../docs/EXPERIMENT_OPERATIONS.md)解释字段、计数和复用范围。

新增`experiments/tier2/manage.py`薄入口，内部复用现有提示构造、API客户端、尝试账本、候选准入、排名父代选择、种群保留和T30认证评价器。没有另写调度算法、评分、归一化或同分逻辑。旧源码与科研协议不修改，旧runs/reports不移动。

|新增/修改文件|目的|
|---|---|
|`README.md`|把第一次运行、真实API开关、长任务、恢复和结果路径写成可执行步骤。|
|`docs/archive/README_PRE_HANDOFF_20261026.md`|整理前README逐字节存档；历史相对链接仍以原仓库根为基准。|
|`docs/EXPERIMENT_CODE_MAP.md`|串起配置、提示、生成、检查、求解、选择、checkpoint、汇总，区分动作特征与U状态。|
|`docs/EXPERIMENT_OPERATIONS.md`|记录组件复用范围、JSON字段、内部常量和未提供能力。|
|`experiments/tier2/manage.py`|一个真实可执行CLI，自动设置项目导入路径。|
|`tools/experiment_ops.py`|配置解析、无副作用预览、新目录冻结、源码/数据/模板身份检查及命令路由。|
|`tools/experiment_ops_prompts.py`|默认逐字委托原H01/10H模板；新提示试验可用独立override文件，不改旧模板。|
|`tools/experiment_ops_run.py`|最小任务调度、原组件接入、预算、边界暂停、恢复、后台和结束回执。|
|`tools/experiment_ops_report.py`|无API的确定性摘要、候选/逐实例/搜索曲线/成本CSV；历史摘要只读。|
|`experiments/tier2/ops/`|7份可预览示例、手写toy和一个默认未启用的提示override示例。|
|`tests/test_experiment_ops.py`|入口、真实调用保护、模板、计数、Mock演化、停止恢复、未知状态的针对性验收。|
|本报告目录|验收日志、历史哈希核对、最终摘要和工程冒烟原始证据归档。|

## 第一次怎么操作

在根README指定的工作区根目录，依次执行：

```sh
.venv/bin/python -B experiments/tier2/manage.py doctor
.venv/bin/python -B experiments/tier2/manage.py check --config experiments/tier2/ops/configs/fixed-toy.json
.venv/bin/python -B experiments/tier2/manage.py plan --config experiments/tier2/ops/configs/fixed-toy.json
.venv/bin/python -B experiments/tier2/manage.py prepare --config experiments/tier2/ops/configs/fixed-toy.json --run-dir runs/my-first
.venv/bin/python -B experiments/tier2/manage.py run --run-dir runs/my-first
.venv/bin/python -B experiments/tier2/manage.py status --run-dir runs/my-first
.venv/bin/python -B experiments/tier2/manage.py summary --run-dir runs/my-first --write
```

`my-first`须为新目录。已存在时查看原目录或另取新名，不删除旧记录重开。check/plan/prepare都不求解、不调用API；只有run/resume启动任务。摘要位于`results/Summary.md`，适合直接贴回讨论；CSV保留可复核事实，不自动给出科研有效性判断。

真实生成：复制`ind-api.json`或`evo-api.json`为自己的JSON，核对数据、H、P0、提示、模型和参数、候选/尝试预算、窗口与输出目录；将`real_requests_authorized`改为true。凭据仅由`provider.api_key_env`对应环境变量传入，run/resume还须明确`--allow-api`。示例没有人民币硬上限或费用认证前置条件；不查询账户或悄悄调用分析模型。每候选最多2次尝试，失败不补员，完整响应不因质量差重新生成。

H01默认初始化/独立生成在`tools/ind_evo_h01.py::independent_prompt`，CROSS/MUTATE在`tools/h01_weight_search.py::build_prompt`；10H自由三类模板在`tools/b1_usage_prompts.py::build_prompt`。新接入统一经过`tools/experiment_ops_prompts.py::build`，优先用新模板override和新run审阅改动，保留受冻旧模板。

## 能力和范围

fixed/pair支持H01或10H合法U；rules接既有H01规则族及其子集；IND/EVO接H01和10H既有提示。H01 CROSS沿用五父代/N=5，不以改配置方式绕过。EVO必须显式提供P0，在当前声明数据上重新认证，代内父代固定、代末更新；新封装暂不自动LLM生成并补满P0。

固定父代CROSS A/B仅接原历史自由P0和匹配的完整train21认证：A不变，B仅真实绑定成绩反馈；源资产缺失/失配直接拒绝，不补算父代。该示例依赖本机忽略的历史run，单独Git检出不保证具备资产。H01受限空间不代表全部10H研究能力。

本封装缓存仅限同run完全匹配的候选AST与冻结上下文；不自动导入跨run历史质量缓存。手动P0的投入单列，不算免费先验。没有提供账户级跨run并发预算协调；Tier1、其他分支、任意新算子和新H流程未在本轮验收。

## 安全停止、恢复和后台

`run --background`复用现有detach：独立session、文件日志、忽略SIGHUP；脚本自行记账、保存checkpoint和结束摘要，不依赖Codex持续轮询。工程验收确认启动控制进程退出后任务继续，以及候选边界暂停再恢复。

`stop --run-dir ...`只请求安全暂停；当前生成和完整评价认证、任务提交后才进入paused。phase=paused且写锁解除才能resume。首次run持久化原窗口，恢复不重置。未知锁/请求/评价、身份变化、Stop或到期不能自动清理后重跑。旧封存campaign不由本入口恢复。

临时caffeinate只绑定本runner并在结束清理。没有承诺合盖、休眠、App关闭、注销或重启期间仍可计算；电脑须有电且唤醒。旧launchd工具仍为synthetic-only，没有宣传为正式后台入口。

## 实际验收和证据

|验收项|结果/证据|
|---|---|
|CLI帮助与参数|[CLI_acceptance.json](CLI_acceptance.json)：12个帮助入口、7份示例计划均退出0；未启动API/求解。|
|11项针对性检查|[Final_tests_after_namespace_fix.log](Final_tests_after_namespace_fix.log)：11项通过，13.445秒；含无副作用预览、原模板、真实调用开关、无费用门禁、Mock演化、断点预算/时钟、未知状态。|
|最后写锁修正|[Final_report_lease_regression.log](Final_report_lease_regression.log)：后台暂停/恢复相关检查通过，7.303秒；不是又一轮正式实验。|
|最终最小求解|`runs/ops-handoff-smoke-20261026-v2`：2策略×1toy×首解/复检，4遍；全部认证，Cmax均7，LB=6，Fitness均−1.166666666667，API0，失败0。|
|最终摘要与状态|[Final_smoke_summary.json](Final_smoke_summary.json)、[Final_smoke_status.json](Final_smoke_status.json)：completed、cursor=2、源码匹配、无写锁/Stop/未知任务；结束回执记录防休眠任务已清理。状态中的剩余窗口是采集时快照。|
|旧campaign只读|[Historical_status_readonly.json](Historical_status_readonly.json)：保留IND/EVO的旧停止记录及另存收尾证据，不清理其旧锁、不恢复。|
|历史完整性|[Historical_integrity.json](Historical_integrity.json)：IND/EVO原始3438文件和后续冠军验证540文件全部匹配原SHA；两份旧归档SHA匹配。只读哈希核对，不调用旧报告重写入口。|
|工程原始记录归档|[Engineering_evidence_manifest.json](Engineering_evidence_manifest.json)、`Engineering_smoke_evidence.tar.gz`：86文件，打包回读逐文件SHA一致、打包前后原文件不变。|

最终toy两策略父进程评价时间合计约0.901秒；该数字只说明此toy，不估计正式数据成本。Mock集成验收还使用同一个手写toy，未把其输出当真实LLM结果。

验收中补上两处新控制器保护：请求ID包含run身份，避免不同run使用同名任务ID；暂停控制器在自己的报告写完后才释放写锁，避免新控制器重叠写报告。这些没有改变候选、评分或接受标准。

较早的工程冒烟`ops-handoff-smoke-20261026-v1`按当时源码已完成，原始记录保留；它的源码身份在上述新控制器修正后应拒绝恢复，不能冒充当前实现验收。对应旧driver已保存在`Before_namespace_fix/`并与其协议SHA核对，第二次修正前driver保存在`Before_report_lease_fix/`。最终v2使用当前实现完成，当前身份检查通过。归档同时保留两版工程证据，不追改v1协议。

本轮没有实跑真实服务、费用查询或正式train21新评价；真实API仅Mock接入验证。pair/rules示例通过配置/计划和相关语义检查，没有单独全跑其整个策略族；10H模板经离线检查，10H真实生成未请求。新建虚拟环境/依赖安装和真实凭据输入示例未执行，使用现有Python 3.12.10环境。

## 保留限制

本次是最小可操作交接，不是全面重构。只能安全恢复本入口创建且已paused、身份匹配、无未知状态、仍在原窗口内的run；断电/强杀证据需另行核查，不能按暂停处理。真实API可用性与模型输出质量没有由Mock证明。结果相同不表示全状态行为等价，toy检查也不提供科研收益证据。

历史报告和正式算法资产保持不变；原README已逐字节归档。其他任务的未提交文件保留，不纳入本次提交。完成本交接后，不启动新的科研实验。
