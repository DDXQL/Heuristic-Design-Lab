# 固定 H 使用空间：第一阶段实现与离线验证

日期：2026-10-13。分支：`codex/h-usage-space`。共同 checkpoint：`243ad401bfd5ff64da338277112933323621de1f`。

本阶段使提示明确覆盖已有接口可表达的评分式单选和状态相关双成员组合，并用手写合法程序验证执行行为。没有调用 LLM 生成 U，因此不能声称模型已经生成、覆盖或有效利用这些策略。

## 1. 分工、版本及隔离

本 worktree 是 `FJSP-Heuristic-Research-h-usage-space`。只在这里修改 `usage_v2/prompts.py`，新增离线例子、离线导出入口、测试和设计文档。沿用既有 SELECT/MIX 执行器、七输入、语言、历史和归一化版本；不重新实现调度器。

原40次 seed301 A/B 待执行批次归原实验任务 `codex/u-single-experiments` 单独执行。本页不复制配置、不建立真实运行目录、不领取请求槽位、不发送模型请求；原任务的代码、提示及运行资产不改。若执行者需要调整，应先明确移交并核对唯一账本，而非两个聊天页分别运行。

新提示版本是 `FJSP-usage-prompts-v2.2-strategy-space-20261013`。原任务继续持有 checkpoint/v2.1 的提示和配置。v2.2 提示 fingerprint 已变化，不能带着旧绑定协议直接恢复原40次批次。未来新效果实验须使用本分支自己的新源码/提示身份、独立登记和独立授权；这里没有创建可执行实验配置。

checkpoint 没有跟踪历史 runs 或正式实例文件，本 worktree 不复制这些内容。唯一只读提取是十条 H 的说明/源码/键，保存在 [H 源码上下文](usage-space/H_context.source-only.json)，用于完整提示导出；它没有成绩、receipt、冻结或研究批准效力，不用于本阶段调度评价。

## 2. 提示检查与最小修改

原v2.1已经允许评分式单选和状态相关权重，执行器也能处理；但其任务称 U 为 selector，算子主要列举条件、映射、切换与阈值，对公式空间的提示偏弱。原“支持”结论是接口/代码能力，不是模型生成证据。

| 原文/位置 | v2.2最小修改 |
|---|---|
| `Design a deterministic heuristic selector U ...` | 只在新提示包改成 `heuristic-usage strategy U`，单成员旧提示不改 |
| SELECT/MIX仅定义输出类型 | 加入分数、支持集、权重和模式可随七输入变化；允许常量、条件、线性/非线性局部表达；不预设公式、阶段或骨架 |
| 计算形式与机制未直接说明 | 补充评分公式可含 if，条件可生成权重；代码语法不能决定使用机制 |
| MIX规定1/2正项 | 补充支持集由 U 自己计算，执行器不会自动把分数截成 top-2 |
| CROSS列举条件/映射/参数 | 加入成员评分公式、在许可模式内的支持集和权重公式；保留至少两父代思想要求 |
| MUTATE列举切换/阈值 | 加入成员评分、支持集/权重/模式规则；保留一个主要修改假设和可重写全函数 |
| 初始化novelty | 补充 SELECT 可比较状态相关成员分数，不必显式分支选编号；仍不给 H 行为与成绩 |

修改全部作用于共用段，未单独鼓励 B 组合。相同父代时 I1 A/B 全文相同，CROSS/MUTATE 仍只差 allowed_modes。成员编号仍是类别，权重与动作分数仍分开；归一化、同分、首步−1、上一实际 dominant、部分输入/成员、常量及单成员 MIX 的合法性不变。

**提示明确允许，不等于提示已被证明能稳定生成。** 本阶段只检查完整文本与指纹，不推断初始化多样性、生成成功率或公式质量。

完整 K10 提示（源码上下文与预览父代，不是实际请求）：

- 初始化：[A.I1](usage-space/offline-v2.2/prompts/A.I1.txt)、[B.I1](usage-space/offline-v2.2/prompts/B.I1.txt)。
- 交叉：[A.CROSS](usage-space/offline-v2.2/prompts/A.CROSS.txt)、[B.CROSS](usage-space/offline-v2.2/prompts/B.CROSS.txt)。
- 变异：[A.MUTATE](usage-space/offline-v2.2/prompts/A.MUTATE.txt)、[B.MUTATE](usage-space/offline-v2.2/prompts/B.MUTATE.txt)。
- [完整比较/提示指纹](usage-space/offline-v2.2/prompts/Prompt_comparison.json)。

预览父代保持原导出器的手写版本，不能把它们当真实种群。实际后续初始化会追加已接受代码，实际演化会绑定真实父代；这些都没有发生。教学公式也没有注入生成提示。

## 3. 当前已支持能力和边界

| 能力 | 接口/执行状态 | 本阶段证据 |
|---|---|---|
| 固定成员、按条件选成员 | 既有 SELECT 可用 | 完整toy、旧路径回归 |
| 线性/非线性成员评分后argmax单选 | 既有数值语言和SELECT可用 | 手写非线性评分+if修正；赢家变化、精确同分、与独立旧选择器逐步等价 |
| 固定双成员权重 | 既有 MIX 可用 | 三动作独立矩阵/分数手算及完整排程 |
| 固定成员对、状态相关权重 | 既有 MIX 可用 | 完整toy三个步骤支持集不变、实际权重有三个不同值 |
| 状态相关成员对及SELECT/MIX模式 | 既有 B 可用 | 完整toy实际执行 `[SELECT,MIX,MIX]`，支持集依次 `{2}`、`{0,1}`、`{1,2}` |
| 上一步 dominant 类别依赖 | 原七输入第七项，非新历史输入 | 下一输入与上一实际 dominant 一致，首步−1 |
| 任意数学函数/调用h/逐动作设权重 | 不支持 | 候选语言及运行输入限制 |
| h分数乘积、逐动作最大值、多于两成员、完整权重历史 | 还未实现 | 后续语义设计见第5节；当前解码器仍拒绝这些输出 |

本阶段“支持”是语言/执行器及工程行为结论。真实生成和新方法效果证据仍为零。评分式单选的执行结果仍是一个 h；程序表示变化可能影响搜索，但不能直接说扩展了单步动作能力。

## 4. 本地例子与验证

[策略例子代码](../code/fjsp_usage/usage_v2/strategy_examples.py)构造五种合法候选，每个只定义一个精确七参数函数，直接返回终端元组；没有字典、辅助函数、容器变量或外部资源进入候选。宿主导出代码使用容器，不意味着候选语言开放容器。

| 例子 | U计算与返回 | 执行器/已观察行为 |
|---|---|---|
| constant-select | SELECT中第2项为1，其余0 | 固定h2；toy首动作C |
| score-select | `q0=1-progress`，`q1=progress+2*(std/(1+mean))²`；上一成员为1时q1加0.05 | SELECT argmax；包含if仍是评分单选；toy首动作A；另有明确的赢家/同分探针 |
| fixed-dual | MIX权重 `(3,2,0)` | alpha=0.6/0.4；双列min–max后首动作B；手算F为0.60、0.68、0.40 |
| state-weights | MIX权重 `(3-2*progress,2+2*progress,0)` | 合法非终止进度下两项始终正；同一成员对的alpha随步骤变化 |
| state-support-mode | 首步SELECT h2；以后按进度条件切换成员对，按机器离散度计算权重 | 完整toy达到模式、支持集、权重变化；不是固定一种阶段骨架的要求 |

实例、H和候选全部手写、独立toy。完整排程使用K3的三条toy h；额外导出K10候选，仅代表源码/接口形状，没有用真实H排程。K10另有本地toy测试，未选第3…9成员放置抛异常哨兵，证实没有执行它们。

可查看 [例子与全轨迹](usage-space/offline-v2.2/examples/Summary.json)、[K10合法函数](usage-space/offline-v2.2/examples/K10/score-select.py)和[总凭证](usage-space/offline-v2.2/Manifest.json)。toy makespan即使更小，也不构成研究效果；完整排程在这里用于可行性和行为验证。

验证覆盖独立分数矩阵与Fraction参考、动态权重比例、模式/支持集、精确同分、历史更新、实际h调用数、未选h不调用、完整可行排程和确定性复检；评分单选与独立旧整数选择器逐动作、七状态、历史、排程和fitness完全相同。原SELECT/MIX失败、单raw/双min–max、数值、输出和语言约束回归保留。

验证命令与通过数量以 [验证记录](usage-space/Verification.json)为准。未运行依赖原正式资产/实例的测试，不以缺少runs为理由复制原资产；历史188通过仍是checkpoint历史证据，不冒充本分支重跑188。

离线导出可在本worktree重现（output须为不存在的新目录，不能是runs/data或另一worktree）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python experiments/tier2/usage_v2/offline_strategy_space.py --output docs/usage-space/reproduction-v2.2 --h-context docs/usage-space/H_context.source-only.json
```

使用项目Python3.12环境（`.venv`安装requirements）。Python minor版本会影响AST身份键，带checkpoint H源码上下文的入口拒绝其他minor版本，不重写旧键。此入口只生成源码例子、完整toy轨迹和完整提示，未导入搜索流程、模型客户端或正式数据集；已有同名目录会拒绝覆盖。原prepare/initialize/search入口本阶段不调用。

## 5. 进一步组合运算：先固定语义再逐项实现

当前不增加新组合运算。先完成既有空间的提示与行为证据，避免同时改变归一化、算子、历史和状态后无法解释比较。下面是下一阶段待确认的具体语义提案，尚未成为候选接口。

| 后续项 | 建议先登记的语义 | 必须先验证的差异 |
|---|---|---|
| 加权乘积 | 两正成员沿用逐列当前动作min–max，`F=z_i**alpha_i * z_j**alpha_j`；正支持内指数均正，任一z=0则F=0；无epsilon | 与线性和的选择差异、零分列、下溢；若两个因子都正但结果下溢为0，建议明确失败而非静默制造同分 |
| 加权逐动作最大值 | 同样归一化，`F=max(alpha_i*z_i, alpha_j*z_j)`；明确是加权最大值，不是原始h分数最大值 | 它可保留单成员极端偏好，与和/乘积不同；同分/常量列/精确权重必须登记 |
| 多于两个成员 | 先单独登记新支持上限及更高调用成本；不与新运算一起放开 | 边际收益/成本、冗余和退化；不要求全成员 |
| 完整权重历史 | 新状态版本明确上一mode/支持集/实际alpha及重置规则 | 信息增加的效果与组合运算效果分开比较 |

新组合运算应有新的接口/aggregation字段与版本，不能重新解释旧mode=0/1或旧结果。SELECT固定单选；单正成员仍走原始h评分以保留兼容；动作合法性、精确同分、提交规则与dominant规则尽可能保持。旧候选不应因为新增组合操作被重新解释。

例如在toy三动作列 `(10,6,0)`、`(0,80,100)`、alpha=0.6/0.4下：线性和选B；加权最大值选A；加权乘积只有B为正。这只说明语义能产生差异，不能说明新运算更好。下一项实现前应冻结具体数值与故障规则，新增独立矩阵/完整toy/资产版本隔离测试，再登记效果实验。

## 6. 后续研究交付

新方法效果研究方案见 [独立实验登记草案](H_USAGE_SPACE_EXPERIMENT_PLAN.md)及 [机器可读草案](usage-space/Experiment_registration.draft.json)。它们不具有执行授权，不复制seed301/40次配置。当前最值得回答的仍是：模型能否实际生成并保留这些机制；实际双成员是否在一致对照下改善完整排程且成本可接受。
