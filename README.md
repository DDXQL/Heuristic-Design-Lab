# FJSP Tier 2：实验操作与代码入口

本工作区研究固定启发式H上的利用程序U。**10H通用空间**允许SELECT或最多两成员的归一化WEIGHTED_SUM；**H0/H1受限空间**只允许alpha与1-alpha权重。两者不能混为一谈。求解时不调用LLM。

当前有冻结H0–H9及多轮探索/认证记录；不是任意研究都可一键启动的成熟平台。本次整理只接通既有组件，不改变H/U、状态、评分、归一化和认证语义。Tier1与其他分支没有在本交接中重新验收，不承诺能直接运行。

- [代码地图：从配置到结果、修改应落在哪里](docs/EXPERIMENT_CODE_MAP.md)
- [配置字段、组件复用范围、恢复和证据边界](docs/EXPERIMENT_OPERATIONS.md)
- [工程交接验收](reports/engineering-handoff-20261026-v1/REPORT_ZH.md)
- [最新冻结冠军训练外验证（已结束，不由本入口续跑）](reports/h01-champion-hurink-rdata20-seed501-20261026-v1/REPORT_ZH.md)
- [接口契约](docs/U_USAGE_CONTRACT_V2_DRAFT.md)、[来源](provenance/SOURCE.md)、[第三方声明](THIRD_PARTY_NOTICES.md)

## 环境

所有下列命令从这个工作区根目录执行：

```sh
cd '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space'
```

本机已验Python 3.12.10，依赖仍用原requirements.txt（numpy/pytz/tqdm）。已有.venv时不要重建。新环境才执行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

统一入口是真实文件`experiments/tier2/manage.py`，自动设置项目导入路径，无需再手写PYTHONPATH。先检查：

```sh
.venv/bin/python -B experiments/tier2/manage.py --help
.venv/bin/python -B experiments/tier2/manage.py doctor
.venv/bin/python -B experiments/tier2/manage.py types
```

doctor只查本地环境及凭据是否存在，不打印值、不联网、不调用模型、不求解。所有子命令均支持`--help`。

## 第一次运行：只做最小toy，不调用API

示例使用已封存真实10H，但输入是独立手写的2作业/2机器toy；其Fitness只用于工程检查，不能作科研结论。输入、策略、参数均在JSON中。以下目录须尚不存在；已有时查看status/summary，或给下一次操作换一个新名字，不删除旧目录重开。

```sh
.venv/bin/python -B experiments/tier2/manage.py check --config experiments/tier2/ops/configs/fixed-toy.json
.venv/bin/python -B experiments/tier2/manage.py plan --config experiments/tier2/ops/configs/fixed-toy.json
.venv/bin/python -B experiments/tier2/manage.py prepare --config experiments/tier2/ops/configs/fixed-toy.json --run-dir runs/my-first
.venv/bin/python -B experiments/tier2/manage.py run --run-dir runs/my-first
.venv/bin/python -B experiments/tier2/manage.py status --run-dir runs/my-first
.venv/bin/python -B experiments/tier2/manage.py summary --run-dir runs/my-first --write
```

成功判断：phase=completed、cursor=2、锁不存在、认证策略2，API尝试0；本机该toy两份策略Fitness均为−1.166666666667，物理首解/复检一致。输出在`runs/my-first/results/`，`Summary.md`可以直接复制回讨论。

check/plan不创建run、不求解；prepare只冻结文件和示例提示，也不求解。**只有run/resume会开始任务**。不要用旧usage_v2的prepare替代这里的纯预览，它会重评H。

## 常见操作

### 固定U、规则族、两份冻结U配对（不调用API）

每个例子同样先check/plan，再prepare/run；目录必须是新的。固定U的完整操作见上。规则族示例只选既有规则的tau=.5子集，共9条；完整旧族为21条，配置说明见专项文档。

```sh
.venv/bin/python -B experiments/tier2/manage.py plan --config experiments/tier2/ops/configs/rules-toy.json
.venv/bin/python -B experiments/tier2/manage.py prepare --config experiments/tier2/ops/configs/rules-toy.json --run-dir runs/my-rules
.venv/bin/python -B experiments/tier2/manage.py run --run-dir runs/my-rules
.venv/bin/python -B experiments/tier2/manage.py summary --run-dir runs/my-rules --write

.venv/bin/python -B experiments/tier2/manage.py plan --config experiments/tier2/ops/configs/pair-toy.json
.venv/bin/python -B experiments/tier2/manage.py prepare --config experiments/tier2/ops/configs/pair-toy.json --run-dir runs/my-pair
.venv/bin/python -B experiments/tier2/manage.py run --run-dir runs/my-pair
.venv/bin/python -B experiments/tier2/manage.py summary --run-dir runs/my-pair --write
```

固定策略支持`alpha`、10H SELECT的`member`或`code_file`。配对差值明确为“第二份−第一份Fitness”，胜负统计也以第二份为对象；不会根据成绩交换顺序。更换数据时编辑自己的JSON，不修改历史数据清单；确认数据不可进入生成/演化。

### 独立生成与演化：先Mock

以下Mock没有模型请求，原始响应明确标注MOCK，不可当真实LLM候选。它仍经原准入、T30执行和计账，是工程流程验收。

```sh
.venv/bin/python -B experiments/tier2/manage.py plan --config experiments/tier2/ops/configs/ind-mock.json
.venv/bin/python -B experiments/tier2/manage.py prepare --config experiments/tier2/ops/configs/ind-mock.json --run-dir runs/my-mock
.venv/bin/python -B experiments/tier2/manage.py run --run-dir runs/my-mock --background
.venv/bin/python -B experiments/tier2/manage.py status --run-dir runs/my-mock
.venv/bin/python -B experiments/tier2/manage.py summary --run-dir runs/my-mock --write
```

### 真实API：必须由你明确启动

本轮整理**没有发送真实API**。服务可用性、实际费用和候选质量未由Mock保证。真实示例默认只2个新增逻辑候选、最多3次API尝试，最多每候选2次；toy评价不是正式科研。EVO另有5个显式静态P0的评价投入，不能称从零只花2次查询。

先复制配置，修改副本；不要在绑定后继续编辑同一文件。两份示例的`api_mode=real`但`real_requests_authorized=false`，因此直接run会拒绝。你准备实际请求时将副本中的该字段改为true，并核对provider模型、endpoint、生成参数、预算和数据。

```sh
cp experiments/tier2/ops/configs/ind-api.json experiments/tier2/ops/my-ind.json
cp experiments/tier2/ops/configs/evo-api.json experiments/tier2/ops/my-evo.json
```

凭据只通过环境变量，不写入JSON，不把值放在命令历史中；在当前终端静默输入后导出：

```sh
read -s LEAFAPI_API_KEY
export LEAFAPI_API_KEY
```

修改完成后，下面的run会真实调用模型。没有人民币硬上限、价格/汇率/账户费用认证前置门禁；保留候选、API尝试、重试、身份、未知状态和期限保护。不会另调模型生成分析。

```sh
.venv/bin/python -B experiments/tier2/manage.py check --config experiments/tier2/ops/my-ind.json
.venv/bin/python -B experiments/tier2/manage.py plan --config experiments/tier2/ops/my-ind.json
.venv/bin/python -B experiments/tier2/manage.py prepare --config experiments/tier2/ops/my-ind.json --run-dir runs/my-ind
.venv/bin/python -B experiments/tier2/manage.py run --run-dir runs/my-ind --allow-api --background

.venv/bin/python -B experiments/tier2/manage.py check --config experiments/tier2/ops/my-evo.json
.venv/bin/python -B experiments/tier2/manage.py plan --config experiments/tier2/ops/my-evo.json
.venv/bin/python -B experiments/tier2/manage.py prepare --config experiments/tier2/ops/my-evo.json --run-dir runs/my-evo
.venv/bin/python -B experiments/tier2/manage.py run --run-dir runs/my-evo --allow-api --background
```

不要同时启动多个真实run来绕过单次预算。独立生成不含父代/历史/成绩；EVO从配置P0开始，代内父代不更新，代末保留N个。`space=ten_h`接10H自由提示；H01示例不代表项目全部能力。新入口暂不自动生成并补满新P0。

固定父代CROSS A/B的配置是`cross-ab-api.json`，计划2个逻辑子代（A/B各1）。它**需要本机原历史自由P0及完整train21认证源**，不匹配就拒绝，不补算父代；Git检出没有这些忽略资产时不可直接运行。先check/plan，确认后复制配置、开启真实授权，再按同一prepare/run流程执行；它不是B2静态P0，也不是泛化实验。

## 长任务：查看、安全停止与恢复

前台默认run；`--background`使用原来验证过的detach方式，脚本自己记录日志、checkpoint和结束摘要，不需要Codex持续轮询。

```sh
.venv/bin/python -B experiments/tier2/manage.py status --run-dir runs/my-mock
.venv/bin/python -B experiments/tier2/manage.py stop --run-dir runs/my-mock
.venv/bin/python -B experiments/tier2/manage.py status --run-dir runs/my-mock
.venv/bin/python -B experiments/tier2/manage.py resume --run-dir runs/my-mock --background
.venv/bin/python -B experiments/tier2/manage.py summary --run-dir runs/my-mock --write
```

stop不是强杀：当前候选生成、完整评价认证、账本提交后才到paused。短toy可能已完成，此时stop/resume拒绝是正常行为。必须看到phase=paused且锁解除才resume；真实API run的resume也需`--allow-api`。前台Ctrl-C同样请求边界暂停。

期限从首次run持久化，暂停/重启不重置。到期保留partial，不自动加时。断电或强杀可能留下未知锁/请求/评价；不要删除锁、清预留或重发，入口会停止等待证据核查。配置/模板/H/数据及已绑定执行源码的变更均拒绝恢复到不匹配的旧run。

本机验收了“启动控制进程退出后后台继续”、安全暂停及恢复。没有承诺App关闭、注销、系统重启或Mac合盖期间持续计算。临时防空闲休眠只绑定runner，结束清理；电脑仍需有电且唤醒。旧launchd接入仅synthetic，不当作通用正式后台入口。

## 结果和计数

|位置|内容|
|---|---|
|Resolved_config.json / Protocol.json / Tasks.json|完整解析配置、数据/代码身份、预算、计划|
|templates/ / prompts/|模板示例及实际每次提示|
|responses/ / wire_responses/ / API_attempts.json|首份完整响应、每次尝试/未知状态、用量|
|evaluations/<U-key>/|首解/复检结果、输入回执、源码身份、T30/退出和失败证据|
|checkpoint.json / Events.jsonl / populations/|游标、已用预算、种群、代末快照|
|control/ / end_receipts/ / Run_clock.json|暂停/恢复证据、结束回执、原截止|
|results/Summary.md、Summary.json及CSV|本地事实摘要、全部候选、逐实例、best-so-far、成本|

逻辑候选不等于API尝试，不等于完整响应，更不等于认证成功。失败不补员；完整Fitness要求全部实例。缓存只复用本run完全匹配AST/上下文结果，命中仍占逻辑候选。Token未知和失败费用不填0，真实扣点/币种无法核实时标null，不阻止正常执行。

已冻结历史run可只读查看，例如：

```sh
.venv/bin/python -B experiments/tier2/manage.py status --run-dir runs/ind-vs-evo-h01-train21-seed501-20261026-v1
.venv/bin/python -B experiments/tier2/manage.py summary --run-dir runs/ind-vs-evo-h01-train21-seed501-20261026-v1
```

该命令不重写旧报告、不恢复旧campaign；其他无标准摘要的旧类型仍使用原专项报告入口。科研解释、训练外结论和后续方向由研究者决定。

## 维护和历史

修改前先读[代码地图](docs/EXPERIMENT_CODE_MAP.md)，用`git diff -- 文件路径`审阅局部改动；不改旧协议/提示/账本/认证记录，不把别的任务文件一起提交。新run必须新目录。

[整理前README字节快照](docs/archive/README_PRE_HANDOFF_20261026.md)仅作2026-10-26前的历史材料；其中相对路径原以仓库根为基准，旧批准和旧“当前进度”不作为现在的执行授权。原始runs/reports位置不变。

## 通用化与第二问题

工程方向暂名Heuristic-Design-Lab；GitHub名、远端及本地主目录保持现状。任务执行/排名已抽取到`code/heuristic_design/core`，FJSP经问题适配层复用原求解认证，旧入口保留。[完整行为回归](reports/generic-extraction-20261026-v1/REPORT_ZH.md)比较了toy及已有认证Behnke1的动作轨迹、状态、排程和首解复检。[TSP固定预算协议](docs/TSP_PILOT_PROTOCOL_V1.md)先冻结后执行。

构造型TSP入口已接入同一执行器，使用独立H、5维动作特征和5维U状态，城市0起止、未取整欧氏距离、完整相对NN Fitness。见[TSP定义、代码地图和实际命令](docs/TSP_ADAPTER.md)。真实固定小试与工程Mock分别记录，不把Mock当LLM结果。
