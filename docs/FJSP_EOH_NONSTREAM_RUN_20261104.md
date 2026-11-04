# FJSP EoH非流式正式入口 V2

本文件接续`e8c073b`离线准备，替代旧文档中“传输未绑定、真实入口关闭”的操作说明。此次集成新增真实API=0、策略求解=0、正式搜索=0；未创建实际运行或继承财务授权。历史A/B、TSP、API专项原始证据均保持原样。

## 客户端与调用方验收

使用API页交付的`COMMON_CLIENT_PREPARATION.json`。该页非流式并发2短检查2/2成功，wire版本`bounded-wire-reliability-v4`。本入口API1是预定原生串行条件；短检查不证明1050次长期稳定，也没有验证EoH生成H的实际质量。

与验收运行逐字节一致的共同文件中，只有`real_transport.py`和`attempt_budget.py`需要更新，其余5份共同依赖本来一致。全部7份运行源码及复制的技术收据/两条响应在`CLIENT_BINDING.json`登记SHA；当前运行只依赖本工作区的证据副本，不依赖另一页可变源码或原认领文件。未复制密钥、授权或claim正文。

底层保持完整JSON、单选择、精确模型、stop、无refusal/tool call等规则。新增统一调用方`strict_nonstream.py`强制非空完整文本及合法非空usage（两项均为非负内置整数，拒绝bool/负数/缺项）。模型必须精确为`gpt-6.1-sol`。缺usage不能进入“成功响应”；不放宽底层模型/截断检查、不接受半条JSON或SSE、不重新发送。

技术短检查的回复是U，不能证明H解析通过。本次离线独立核对七参数H的原生盒装描述、代码格式、封闭语言和四算子Prompt。固定H0验证仅复用已有21例两遍记录，没有重新求解。

## 固定研究与预算

- 原生LLM4AD EoH本地revision 2025/2/16，N5、selection_num2、I1初始化后E1/E2/M1/M2循环；原生抽样、同分惩罚、生存及计数保留。API1、评价1、实例串行，不套用U的CROSS/MUTATE、N10或50代。
- 同train21、solve_seed501、未取整LB_v5、append-only调度与精确同分规则；单H固定U=0宿主。首解/复检共享T30及既有退出宽限；无局部搜索。
- 从全部完整有效train候选按Fitness降序、固定ID升序选冠军并冻结，validation不重选；validation11已有历史暴露，当前不访问。
- **总物理尝试1050包含初始化，初始化HTTP子上限50；原生初始化评价样本上限2N=10，可能更早结束。** 演化剩余=1050−实际初始化尝试；每槽一次，失败/重复/不明确发送均占预算，不补发。保留1023与1050节点。
- 48小时持久总窗口含暂停等待，恢复不重置；时间不足则expired，不延长。最多22050个程序×实例行、44100遍首解/复检，不保证消耗完所有槽位或达到某代数。
- A实际23+1000=1023；B新增1000，P0来源23次与10程序重评另列。H构建成本另列且不假设0；不同Prompt/token/失败率不能据请求数宣称费用相等。
- 历史A/B冻结客户端不替换，因此不满足“新同期两臂同客户端”的条件。只作共同任务、共同已观察预算前缀的探索性比较，不宣称严格同期或端到端等成本。

## 故障规则（与Fitness无关，运行前固定）

|情况|处理|恢复|
|---|---|---|
|明确权限/余额/模型/参数拒绝，例如403；完整JSON/模型/结束状态/usage验收失败|首次即禁止后续请求；结算已知失败和原生算子槽，保存检查点；安全paused并释放本控制器锁，`api_stop_reason`持久保留|普通resume拒绝；先核查具体原因，再另行明确处理/迁移；不得清账、删除停机原因或冒充新预算|
|连接/读取/总期限、524等临时或未分类传输失败|每次按失败占预算；连续3个完整失败任务后安全paused，无重试；成功传输清除连续计数|用户显式resume；继承旧次数/算子/RNG/种群/原窗口，失败槽不重发。原失败计数不清零，再失败可更早暂停|
|完整响应中H代码不合法、重复、普通评价无效/超时|科研结果分别记录、占预算；不当成接口故障，也不按Fitness停机|继续预定槽位，不补员或补预算|
|SIGINT/安全pause请求|等当前有界网络和完整候选评价结算后保存paused并释放锁|原目录resume|
|未知在途、未知评价、源码变化、时钟隔离、异常强制中断|保留锁/Stop和全部证据，不自动重放|拒绝普通恢复，先核查；不提供删锁强跑路径|

硬拒绝/协议失败的“已知失败结算”仅为FJSP适配启用的既有执行器小钩子，其他适配默认行为保持。预算账本、已失败请求及未知usage不清零。此入口没有循环重启、隐藏重试、换模型、换供应商或追加seed。

## 参数、工作目录与命令

工作目录：`/Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-single`。
入口：`experiments/common/run_fjsp_eoh_single.py`。
正式配置：`experiments/common/configs/fjsp-eoh-single.real.json`。provider和证据已绑定，配置里的`real_requests_authorized=false`保持关闭；用户在启动命令中同时给出两个明确批准参数，才会为这个新运行冻结授权配置。旧`.real.pending.json`属于V1历史准备，不能用于V2启动。

**先check-only**：无模型请求、无策略求解；不读取密钥值、不创建正式运行：

```sh
cd /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-single
.venv/bin/python -B experiments/common/run_fjsp_eoh_single.py --check-only
```

预期：`admitted_common_nonstream_and_strict_caller_bound`、21实例、N5、API1/评价1、1050/50、原生四算子及固定停止规则。模型/端点/8192输出、10/240/300秒请求期限已在配置中登记；密钥只通过既有终端环境变量`LEAFAPI_API_KEY`读取。

**正式启动**，由用户查看配置后在自己的终端执行；1050是次数上限，不是金额硬封顶：

```sh
caffeinate -i .venv/bin/python -u -B experiments/common/run_fjsp_eoh_single.py --run --allow-api --approve-budget 1050
```

默认新目录：`runs/fjsp-eoh-single-nonstream-20261104-01`。已存在则报错，绝不覆盖或误恢复；已完成不能resume。启动后冻结原参数，之后修改配置文件不改变该运行的恢复设置。

第二终端在同目录只读查看状态或请求安全暂停：

```sh
.venv/bin/python -B experiments/common/run_fjsp_eoh_single.py --status runs/fjsp-eoh-single-nonstream-20261104-01
.venv/bin/python -B experiments/common/run_fjsp_eoh_single.py --pause runs/fjsp-eoh-single-nonstream-20261104-01
```

确认paused、writer_lock=false且api_stop_reason为空后显式恢复；这是原1050累计上限，**不是再增加1050**：

```sh
caffeinate -i .venv/bin/python -u -B experiments/common/run_fjsp_eoh_single.py --resume runs/fjsp-eoh-single-nonstream-20261104-01 --allow-api --approve-budget 1050
```

只导出已保存结果（无模型/求解）：

```sh
.venv/bin/python -B experiments/common/run_fjsp_eoh_single.py --report runs/fjsp-eoh-single-nonstream-20261104-01
```

## 输出及比较口径

运行根保留`terminal.log`、`Protocol.json`、源文件SHA、原Prompt/响应、`API_attempts.json`、原生种群/RNG、worker首解/复检证据。完成或安全结束后自动导出`analysis/`：

- `Summary.json`、`candidates.csv`、`requests.csv`、`per_instance.csv`；重复保留而不重复算新的唯一评价。
- `progress_curve.csv`包含每个物理预留槽，失败和未结算预留不消失；分别记录完整有效候选记录数、**完整有效AST唯一H评价数**、最好Fitness及最后槽是否提交。不能把重复结果当作新增完整评价。
- `best_fitness.png/.svg`、`full_valid_evaluations.png/.svg`；标准matplotlib绘图，不调用业务评价。缺绘图依赖则保留CSV并写Plot_status，不破坏检查点。
- `budget_nodes.csv`保存全部预定节点，包括1023和1050；未达到节点、超出历史观察域的格子留空，不外推。A列含实际初始化；B增量列将共享P0置于预算之外，另一列显式归属A的23次来源成本，不能把该列当成B新增扣费。
- 新运行内冻结的`Reference_curves.json`复用历史A/B已提交结果，避免报告依赖可变分析脚本；来源Protocol/检查点SHA保留。不重求解基线。
- 完成后输出`frozen_training_champion.json`及`champion.py`；Mock人工评分只输出`frozen_engineering_candidate.json`，图表明确标MOCK。

本阶段没有新的真实EoH结果、正式授权或运行目录；只有已完成的客户端集成和离线检查。用户可直接按上述顺序审阅、启动，无需追加线上诊断或联系供应商。
