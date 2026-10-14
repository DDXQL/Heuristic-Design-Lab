# v2.2 独立训练小试：授权、串行准备与报告

**历史gpt-5.6-sol阶段，现已挂起。** 2026-10-14获批统一迁移Leaf gpt-6.1-sol后，以[新模型登记与串行续跑说明](H_USAGE_V22_GPT61.md)为当前阶段；本页旧模型入口的register/run已禁止。以下保留历史授权和协议说明，不作为当前运行命令。

2026-10-13，DDXQL在“梳理固定 H 的策略空间”聊天页明确授权本批及原10条H的SELECT/SELECT-MIX条件研究用途。此授权覆盖准备、登记及满足串行条件后的执行，不需要再次询问同一批次；原技术审查不改写。

2026-10-14最新阶段指令：本轮仅完成离线准备，不发送真实请求。当前执行者、最新准备目录、完整提示快照、账本/结算阻碍及未来唯一运行命令以[就绪清单](H_USAGE_V22_READINESS_20261014.md)为准；单成员页停止不能替代全局结算与预算门禁解除。下列入口顺序说明保留协议流程，不代表现在可以启动。

固定规模：seed301、N5、共享新SELECT初始化最多20请求，A仅SELECT、B允许SELECT/MIX（1或2正项），各一代10请求（5交叉+5变异），最多40新请求。Leaf gpt-5.6-sol、共同生成参数、状态、数据、主评价/复检/诊断期限、父代选择、生存选择沿用共同实现。失败/重复占槽位，不补发；初始化不足5则结束，无手写补员。仅训练，正式验证/测试文件不复制、不加载。

## 准备与真实发送分开

新入口：[run_registered_v22.py](../experiments/tier2/usage_v2/run_registered_v22.py)。它复用已有执行器和搜索，通过[串行保护](../code/fjsp_usage/usage_v2/registration.py)和[结果导出](../code/fjsp_usage/usage_v2/training_export.py)建立新v2.2配置与目录，不恢复旧40次方案。

离线准备存放在 `preparations/`，不使用runs中的writer锁，因此不会因本页离线重评H而阻止单成员页执行。保存真实来源副本、训练文件、用途授权、H重新评价、六份完整提示和组间差异。准备配置关闭dispatch，代表串行条件尚未满足，不代表用户授权被撤销。

最终登记必须等单成员页的授权60次批次终止并解决结算。仅“聊天中断”或“没有锁”不算结束；检查封存的Search_complete/初始化失败或预算停止凭证、ledger及platform_quota。存在对方writer锁、pending reservation、未解决account halt时不发送。发送用量未知时仅接受已绑定且独立核对的唯一model/window/debit供应商失败凭证，保留未知token预留，不伪造响应usage。对方已完成的批次文件和实际新槽位随后绑定进本页history，保持祖先79槽位和原1,200万账户点预留，不因worktree重置。

历史ledger inventory用于查变更和相同identity副本一致性，不能把全部历史恢复快照简单求和：不同恢复上下文中保留了相同祖先请求。已登记的三份不重叠祖先history为79槽位；最终加入单成员页本批新ledger及本页新ledger。两个批次上限为179/300，实际按封存账本算。实时账户30%边界与单请求保守预留仍由原QuotaGuard执行。

只在当前worktree创建新文件，不修改对方代码、配置、账本或运行锁。完整提示两组在相同父代下仍仅allowed_modes不同；共同初始化无H行为/成绩，后续有H源码/说明。B不必须组合；不增加乘积或最大值。

## 入口顺序

使用本worktree的Python3.12环境。所有目录参数均为不存在的新目录，只有run/report使用已登记目录。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python experiments/tier2/usage_v2/run_registered_v22.py offline-prepare --directory preparations/v22-select-mix-YYYYMMDD-new
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python experiments/tier2/usage_v2/run_registered_v22.py peer-status
```

最新离线准备已存在于 `preparations/v22-select-mix-20261013-v2`，不用再次创建或覆盖。peer-status确认终止/结算就绪且全局预算允许发送之后，在当前已有授权内登记并执行：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python experiments/tier2/usage_v2/run_registered_v22.py register --directory runs/v22-select-mix-301-20261014-v1
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python experiments/tier2/usage_v2/run_registered_v22.py run --directory runs/v22-select-mix-301-20261014-v1
```

凭证只在串行门禁通过后由已有环境变量或原`.env.leafapi.local`加载，不复制到配置/快照，不打印。每次preflight和dispatch复查真实来源、对方终止文件、所有worktree账本和锁；任何外部账本变化需要核对，不能自动重新绑定并继续花费。实际预算/结算门禁停止后不自动开新目录或补发。

## 结果含义

完整原始响应及每次实际提示保存在既有journal；checkpoint保存父代和种群变化；`Usage_training_report.json`保留全部候选结果；新`results/`导出所有逐实例成绩JSON/CSV、实际合法生成代码、逐组合法率/完整有效率/重复及失败分类、实际SELECT/MIX行为、最终最优候选的逐实例训练配对、token及已记录成本。

语法合法率与完整21train有效率分别报告。MIX单正项不是双成员；成员分数变化与赢家变化分开，成员对变化与权重变化分开。双成员恒定列记录为观察到的组合退化，其他“与单选效果相同”需要对照，不能从MIX字样推断收益。缺失的失败求解时间/h调用数保持unknown，不写0。

账户扣费同时报告实际观测raw quota delta与唯一供应商扣费凭证的platform units；未核实的点数到货币换算保持空值，不冒充人民币账单。使用本worktree独立的供应商发前/发后记录与模型/窗口/扣费匹配；无法匹配或实际门禁触发即停止。外部账户请求可能影响账户差值，worktree串行检查不能认证所有外部程序；同时保存逐请求用量、配额窗口和结算证据。

本批只有一个训练种子，B出现组合代码不是收益证据；训练最优候选配对也不是独立泛化证据。当前授权不含validation/test、更多种子、更多代或新组合运算。
