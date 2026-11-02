# TSP EoH单规则端到端预算对照 V1

本轮只新训练一条直接动作评分H。已有10H构建、恒选评价与U搜索不重跑，不读留出集。真实请求默认关闭，正式启动由用户在终端明确批准本轮最多260次尝试。

## 算法复用与必要适配

代码依据为本仓库`code/llm4ad/method/eoh/`，`eoh.py`标注Last Revision 2025/2/16。原文件及许可证不修改；实际源文件SHA随每次Protocol冻结。复用`EoHPrompt`、`Population.register_function/selection/survival`和原生描述提取器。

- N=5。初始化I1；随后按E1→E2→M1→M2循环。此本地版本没有M3，不新增其他算子，不冒称完整上游论文/其他版本复现。
- E1/E2按原生排名权重`1/(r+N_finite)`抽两个父代，每次有放回，因此可能选中同一条；M1/M2抽一个。父代代码与描述进入原生Prompt，不额外添加新的反馈机制。
- 原生种群每累计N个登记程序，父代与待选子代合并，按score降序稳定排序保留N。源码字符串相同或平均score完全相同会令新程序的种群分数为负无穷；这与本方法H池只做AST去重的规则不同，按原算法保留并单独统计。
- 全部AST首现候选完整评价；AST重复复用本轮已落盘评价，仍消耗请求。完整物理Fitness和原生种群分数分开保存，不把重复惩罚当作实际求解成绩。
- 原生`register_function`会自动生存更新，`EoH.run`初始化后又显式调用一次survival。本适配保留该记账行为；导出`native_generation`与实际`evolution_survival_updates`，不将其等同于U的20代。
- 仅替换原本不持久化的顶层线程循环：由已有单写者执行器调度原生组件，增加两个适配钩子；请求/故障/暂停/时钟/求解继续复用已有能力。Prompt只增加统一H语言和一个围栏代码块的序列化要求。
- 初始化沿用原生最多2N=10个进入评价的样本，另加20次HTTP上限；原生人口数量须达到selection_num=2并存在有限分父代，允许两次抽中同一有限父代。达不到即`initialization_incomplete`，不导入人工/冻结10H补员。
- 不设固定G；以HTTP预算停止。原生代数由实际进入登记的程序数决定；失败/重复均已消耗预算。每次请求后顺序推进算子，不为异常补发或复位后重试同一槽。

这是**本地LLM4AD EoH的统一受限H语言/HTTP预算适配版**。与旧FJSP历史模型、表达空间及validation选优不同；不把旧规则重评当作新训练。

## 预算转换与停止

原版`max_sample_nums`统计进入评价/登记路径的样本；传输失败、缺少描述、解析失败等可能不增加该计数，且没有可直接比较的HTTP总上限。因此本轮不将`max_sample_nums=260`等同于260次请求。

本轮主计数为持久账本预留的HTTP尝试：总上限260，每逻辑槽最多一次，不重试、不补失败/重复、不延长预算。计数先于发送落盘，未知发送也保守计费；确认发送次数、usage和原生评价样本数另外报告。原生样本数至多260，实际通常更少。

已有方法预算上限40+220=260；实际预留40+213=253（确认发送38+211=249）。比较同时列上限、实际预留、确认发送和已知token；未知usage不是零费用。EoH保存253槽检查点，分别比较截至253的训练最好值与最终≤260结果，最后7槽不隐藏。

最大5200条程序×实例行、10400遍首解/复检。T30为一条实例首解/复检完整生命周期期限，不是单遍30秒。实际无效/重复会减少评价量。

沿用12小时持久运行窗口，暂停等待也占窗口，恢复不重置。开新候选前预留网络+完整评价保守余量；不足即expired，不自动续时。认证、余额、模型/参数硬错误持久停止；连续3个临时传输失败安全暂停，需用户显式恢复。不清锁，不自动重发未知任务。未知发送/评价或强制中断后的不明确状态拒绝自动恢复。

## 统一条件与选优

从已完成U的Protocol直接核对模型与provider全部设置：gpt-6.1-sol、相同端点、non-stream、输出上限8192、温度/推理参数未覆盖。H/U与EoH使用完全相同有序train20（每例50城）、NN参考、seed501、T30、共同构造器和封闭H语言。求解器、H校验器、状态与动作物理源码逐文件SHA须一致。EoH原生串行，原U并发2；不据墙钟宣称算法加速。

H五参数为`priority(distance_current,distance_start,mean_remaining_distance,nearest_remaining_distance,progress)`，距离输入除sqrt(2)，最大raw score选择城市，同分取较小城市ID；0起止、闭合边计入长度，无局部搜索。通过现有单H＋恒定U宿主评价，与H池构建相同。

F=mean(−L/L_NN)，完整20例有效才有Fitness。最终从所有完整有效train候选按F降序/任务ID升序选一条；与现有U报告选优一致。种群内部仍保留原生稳定排序及同分惩罚。不访问validation/test选冠军，不在结果后更改协议。

比较预定：ΔF=F_EoH−F_双层；相对变化=100×ΔF/abs(F_双层)。逐实例长度降低另算100×(L_双层−L_EoH)/L_双层；绝对长度容差1e−12统计胜负平。均为单轮训练描述，不宣称泛化/统计显著性。

## 本地命令

工作目录：`/Users/DDXQL/Developer/Heuristic-Design-Lab-tsp-eoh-single`。配置参数位于`experiments/common/configs/tsp-eoh-single.real.pending.json`；不能只改一处预算，candidate_cap与api_attempt_cap必须一致且≤260。对照数据/模型修改会被兼容检查拒绝。本次无需修改入口脚本。

**check-only，API=0、策略求解=0**（仅计算NN参考和核对已落盘身份）：

```bash
.venv/bin/python -B experiments/common/run_tsp_eoh_single.py --check-only
```

**正式训练，仅由用户启动，最多260次新尝试**；凭据从既有`LEAFAPI_API_KEY`环境变量读取，程序不创建或沿用财务授权：

```bash
.venv/bin/python -u -B experiments/common/run_tsp_eoh_single.py --run --allow-api --approve-budget 260
```

**查看进度，只读**：

```bash
.venv/bin/python -B experiments/common/run_tsp_eoh_single.py --status runs/tsp-eoh-single-real-20261102-01
```

**请求安全暂停**（等待当前网络与完整候选评价结束，确认phase=paused且writer_lock=false）：

```bash
.venv/bin/python -B experiments/common/run_tsp_eoh_single.py --pause runs/tsp-eoh-single-real-20261102-01
```

**恢复正式训练**（原260总预算、原12小时窗口，不是再给260次）：

```bash
.venv/bin/python -u -B experiments/common/run_tsp_eoh_single.py --resume runs/tsp-eoh-single-real-20261102-01 --allow-api --approve-budget 260
```

**离线比较/阶段汇总，API=0、求解=0**，运行中只读取已提交结果：

```bash
.venv/bin/python -B experiments/common/summarize_tsp_eoh.py --run-dir runs/tsp-eoh-single-real-20261102-01
```

普通结束、安全暂停及已持久化故障结束后自动尝试报告。输出为`runs/tsp-eoh-single-real-20261102-01/analysis/`：REPORT_ZH.md、comparison_summary.csv、comparison_per_instance.csv、候选/请求/逐实例/种群/谱系/预算节点/时间记录、champion.py/json，以及3组PNG/可编辑SVG。报告失败不损坏原始结果，以上命令可独立重跑。

## 离线验证与真正限制

`tools/check_tsp_eoh_single.py`覆盖原生种群/抽样一致性、错误/重复预算、四算子、暂停恢复随机状态及父代一致性、初始化不足、未知预约拒绝重发、同分有放回父代、配对公式；`test_common_execution_v1.py`核对共享执行回归。Mock调度测试使用人工合成分数，单独的工程小试使用固定Mock候选真实求解，两者都不是LLM科研成绩。

本轮未做真实网络探测、未读凭据值、未发模型请求。外部端点可用性、真实调用成功率及真实EoH性能仍未知；没有本地工程阻塞时由用户按预算启动即可。旧H/U证据与FJSP工作区均不修改。
