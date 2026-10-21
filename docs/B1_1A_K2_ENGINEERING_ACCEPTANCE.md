# B1-1A：二父代交叉工程验收

本阶段只做独立B1入口、准备身份和离线Mock。真实LeafAPI请求0、正式训练评价0、test28新使用0；没有B1-1正式执行授权或真实P0。公共演化、调度器、旧Prompt以及B2/V1成果未修改。

## 冻结协议

- 目录：`runs/b1-full-h-free-seed501-k2-v1-20261021/`。
- 协议身份：`B1-full-H-free-search-batch-v1-20261021`。
- SHA256：`d5ec72d53583c8dd5829b6a9d8f002511956c346127aad99348e1485f8e3e898`。
- H：原10H、有序编号/源码/原审查及来源不变；七状态与SELECT/MIX、最多两正权重、归一化、历史更新、动作同分规则均不变。
- N=5，**cross_parents=2**，mutation_parents=1，seed501；两代，每代5 CROSS＋5 MUTATE。每个CROSS请求产生一份响应，最多接受一个子代。
- 自由初始化：完整10H源码/审查说明；SELECT/MIX均可；没有人工U/已知成员对植入；最多20个逻辑任务取得5个完整有效、AST不同的U。
- 全批共享最多40逻辑任务、60次API尝试、每任务最多3尝试；初始化和演化不各领一份预算。沿用现有临时故障分类及2/5秒退避、首份成功响应、持久化恢复；未知费用保持null，无账户或账单查询。
- 原21train、完整平均−Cmax/LB、首次及确定性复检共享15秒；无第三遍观察回放。模型/生成参数严格对齐B2来源，输出上限8192。
- 完整冻结对象、输入、模型配置、Prompt预览及身份见[准备归档](usage-space/b1-k2-prepared-20261021/)。预览父代明确是占位文本，不是真实父代、种群或可发送候选；未来实际请求会按真实父代保存完整提示。

这些是准备参数，不是付费/训练授权。没有为了cross_parents=2改变预算、子代数、评价或CROSS任务语义。

## 修改范围

仅新增：

|文件|职责|
|---|---|
|`tools/b1_usage_local.py`|B1独立配置、固定H来源绑定、共享批次账本、UsageSearch薄适配、代际记录、授权/恢复门禁及报告|
|`tools/b1_usage_prompts.py`|B1自由初始化上下文；复用原TASK、CROSS、MUTATE和输出语言，不加数值Fitness|
|`tests/test_b1_usage_local.py`|合成程序、响应、Fitness及本地Mock验收|
|本报告及准备归档|协议、哈希、Mock谱系、历史保护与验收日志|

没有改`select_parents()`、`Search.run()`、`operator_at()`或生产执行器。科研阶段名B1与旧内部arm B1区分：本入口使用内部arm B，防止误用旧E1/E2/M1/M2/M3算子。

相对B1-0建议，交叉父代数由5改成2。B1新初始化本身需要新版本提示；这是已讨论的B1空间适配，并非二父代要求额外改变CROSS指令。原“AT LEAST TWO parents”与两个父代兼容；“Return one complete new U”保留。

## 抽样及代际机制

现有`research/evolution.py:select_parents()`先按原`ranked()`排序，以零起始rank r赋权`1/(N+r)`，每次抽取后移除该行及其原始权重，余者不重新排名赋权。原池不修改。因此N=5/k=2时，Fitness排名影响入选集合和顺序；k=5时集合包含全部五个成员。并非按Fitness数值大小直接比例抽样。

配置保留k=2/3/5；独立prepare会绑定新的配置/协议/检查点哈希。不能在已有准备目录改k继续；未来k=3/5真实消融必须另行登记授权。本次只冻结k=2。

每代父代池固定；新子代不在代中成为父代。原代末以完整Fitness对父子合并取前5，同分按原ID规则处理。P0/P1/P2、每次父代、实际配置k、操作、候选来源及评价记录均保留。第二代只能从P1继续，不能回到P0。

## 离线验收结果

**41项检查通过**：18项新B1 Mock＋23项既有限定重试回归检查。既有本地HTTP假服务测试不是LeafAPI；所有响应和Fitness均为合成数据，真实API、调度求解和数据加载调用被禁止。

- 精确检查原排名权重、无放回移除及不重算排名；确认公共函数无修改。
- 完整Mock：5个初始化＋20个演化任务，10 CROSS、10 MUTATE；CROSS各2个不同父代，MUTATE各1个父代，每任务最多1子代。第一代5次CROSS抽到5种不同的无序父代对，第二代为4种；这是U父代对，不是H成员对。
- 在人为设定第一代子代优于初始成员的合成分数下，P1选择第一代子代，第二代实际引用它们；无代中引用。不能把这当成真实搜索改进证据。
- 中断后父代序列与不中断参考逐项一致；已保存响应不重发，已完成评价不重评；缺失账本或孤立检查点拒绝重新获得配额。
- k=3/5配置、实际Mock请求及哈希区分通过；改变k后不能恢复原检查点。
- 非法/重复不重试；失败结果不进入种群；初始化不足5停止；40逻辑、60总尝试和单任务3尝试均受限，重启不重置。
- 4类模拟冻结SHA故障均被拒绝，实际文件未改；缺少授权的真实CLI在创建运行检查点、加载训练实例和构建客户端前被拒绝。
- B2的cross_parents仍为5；历史B2/V1受保护文件逐项核对未改，公共及旧跟踪代码diff为空。详见[History_unchanged.json](usage-space/b1-k2-prepared-20261021/History_unchanged.json)。

历史核验按内容SHA确认，共359项一致。另与较早V1-0的mtime快照比较时，B2报告的`sources/alpha_000.py`有112ns差异，源码SHA一致；出现时间和原因未知，未改写文件或恢复时间戳，不声称全部历史mtime均与旧快照一致。此项不影响冻结科研内容身份。

Mock谱系和日志见[Full_mock_lineage.json](usage-space/b1-k2-prepared-20261021/Full_mock_lineage.json)及[离线日志](usage-space/b1-k2-prepared-20261021/Offline_mock_tests.log)。Mock仅在临时目录执行，归档只保留明确synthetic的证据，不进入正式实验目录。

## 入口与启动状态

已执行的工程命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python -B -m unittest test_b1_usage_local test_h01_attempt_retries -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python -B tools/b1_usage_local.py prepare --run-dir runs/b1-full-h-free-seed501-k2-v1-20261021 --cross-parents 2
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python -B tools/b1_usage_local.py check --run-dir runs/b1-full-h-free-seed501-k2-v1-20261021
```

prepare只做来源/合法性及元信息核验、train文件哈希、提示预览和冻结，不求解正式实例。check不构建供应商客户端或加载实例求解。report只读已保存结果。run在正式B1-1授权前拒绝。

未来唯一运行/恢复入口为同一目录的`tools/b1_usage_local.py run --run-dir ... --env-file <本机既有凭证路径>`，只能在明确授权后使用。需独立`B1_1_authorization.json`绑定stage、DDXQL、协议SHA、k=2及40/60/3上限；本阶段未创建。使用已有单目录RunLock，顺序执行，不增加全局锁，不支持多进程共同处理同一批。

**本次二父代工程验收通过，准备协议已冻结；尚未授权正式B1-1。** B1与B2同时存在H空间、初始化和交叉父代数差异，性能差不能单独归因于10H或二父代交叉。未来单因素消融需共同P0和相同其他条件，独立登记，不能复用已消费test28作为未见选优证据。本阶段到此停止。
