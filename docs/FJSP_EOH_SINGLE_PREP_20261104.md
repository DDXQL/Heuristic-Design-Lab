# FJSP当前条件下的单规则EoH：离线构建

本轮只完成离线接入；真实API=0、新增策略求解=0、正式搜索=0。独立工作区为`/Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-single`，源自TSP已提交版本`52cfc1d`。原工作区用户修改、TSP其他页的未提交准备材料、历史FJSP A/B及网络排查记录均保留。

## 已了解的其他页面进度

- TSP原生EoH入口`run_tsp_eoh_single.py`已在260次预算内完成；其原生组件、账本和持久执行器可复用。此次不重做TSP。
- TSP后续新H池、冻结评价/阶段验证有独立准备材料，本次不修改，也不将TSP成绩作为FJSP证据。
- FJSP已有canonical历史EoH规则的R1重评，Fitness=-2.012187450378091；这是旧规则的质量参照，不是本轮同模型1050次新训练。
- API可靠性由`Heuristic-Design-Lab-api-reliability-next`负责。本入口不复制该页未完成的传输验收，不发送诊断。接入时须绑定其实际验收客户端源码和证据，不能只把provider JSON填上就称验收通过。快照见`reports/fjsp-eoh-single-prepared-20261104/RELATED_PROGRESS.json`。

## 复用范围与所选方法版本

原生代码来自`code/llm4ad/method/eoh/`，本地`eoh.py`标注Last Revision 2025/2/16；文件和许可证不改。沿用已完成TSP对照的适配：原生EoHPrompt、描述解析、Population.selection/register_function/survival，外层由既有`core.execution`提供持久请求账本、单次尝试、暂停和恢复。

FJSP仅增加问题适配层；原TSP持久适配只新增默认行为不变的`read_state`钩子，供FJSP读取自己的Protocol。没有复制搜索循环，也没有重新实现EoH种群、API或求解器。

- 原生N=5、selection_num=2；I1初始化，然后E1→E2→M1→M2循环。本地版本没有M3。
- E1/E2按原生逆排名权重有放回抽两次，M1/M2抽一次；原生允许同一个父代被重复抽到，不强改为U的“其他父代”规则。
- 每累计N个登记程序触发原生生存，稳定按score排序；代码字符串相同或均值同分在原生种群里惩罚为负无穷。物理Fitness仍按真实评价保存，不能把重复惩罚当作求解分数。
- AST重复仍占HTTP预算，复用本轮已保存评价；不重求解补预算。原生评价样本数、HTTP次数、原生generation和实际演化survival次数分开导出。
- 初始化最多50次HTTP；原生进入评价样本上限2N=10，且可能在自动survival后更早结束。保留原生显式post-init survival。种群不足2或无有限分父代则结束为initialization_incomplete；不导入10H或手写规则补员。
- 不设U式固定50代；按总尝试预算停止。此为“本地LLM4AD EoH＋统一封闭H语言/HTTP上限适配版”，不冒称未经约束的完整论文复现。

## 统一评价入口

实际新候选评价继续走现有`routing_evaluation.evaluate_task`：H作为唯一成员，合法纯路由宿主固定返回0，调用原FJSP构造器。H接口是：

```python
def priority(processing_time, remaining_work, remaining_operations,
             job_ready_time, machine_ready_time, earliest_start, earliest_finish):
    ...
```

输入为原物理值，采用原封闭数值语言；最大有限raw priority胜出，精确同分保留既有job/machine动作顺序的第一项。构造器为append-only，无局部搜索，无事后改进。统一完整train21、solve_seed501，`LB=max(max_j sum(min processing times), sum_all(min processing times)/M)`不取整，Fitness为完整21例`mean(-Cmax/LB)`。

同一已有worker按每实例首解/复检共享T30执行，并沿用2秒正常退出宽限；完整可行、语义复检相同才是有效候选，部分成功前缀不给Fitness。缓存结果验证包含可行排程、LB/分数、首解/复检/实际语义摘要及源码前后相同证据。

已核对A/B共有的17份物理评价源码逐文件相同。现有`core.routing.py`相对历史A只多TSP提示分支；去除`build_prompt`后完整模块AST一致，单H常量U宿主不调用提示生成。该兼容桥显式记录，不伪造完全相同的文件哈希。

最终从全部完整有效train21候选按Fitness降序、固定任务ID升序选冠军，先冻结单H源码、配置、数据/参考与源码身份，再做预定补充验证。validation11已有历史暴露，不用于重选；本轮没有读取留出数据。初始化/失败/重复/退化和全部谱系保留。

## 预算与公平性口径

拟议总尝试上限1050，包含初始化；初始化子上限50。每逻辑槽只允许一次尝试，失败、重复及发送状态不明都占预算，不自动重试或清零。若初始化实际用i次，则剩余演化最多1050−i，不强行变成U的1000次演化。最高22050个程序×实例行、44100遍首解/复检；无效/重复通常降低实际求解量。

- 历史A：50次初始化上限，实际23次初始化＋1000次演化＝1023次。
- 当前B：新增1000次演化请求，P0来自A那23次初始化，另有10个程序的完整train21重评成本。共享来源可另列归属1023，但不能把23次再当B实际新增发送；失败首轮B、额外新A和诊断开销另列，不混入当前B的名义1000次。
- EoH同时保存1023和1050节点；对A实际预算比较必须报告截至1023的结果，最终额外27次也完整报告。共同上限或请求数相同仍不等于token/费用或计算量相同。
- 10H构建、筛选与历史评价成本为U方法上游成本，单独报告，当前不将未知成本填0。因此这是给定历史资产下的训练比较，不宣称端到端等成本。

完整逐项表见`reports/fjsp-eoh-single-prepared-20261104/PARAMETER_COMPARISON.csv`。

原生适配串行：API/候选CPU/实例并发均1，A/B为API2、候选CPU2、实例串行；这是保留现有原生接入的实现条件差异，不以墙钟宣布算法加速。固定总窗口48小时，含暂停等待，恢复不重置；沿用TSP持久时钟机制，针对1050显式改值，区别于其260次实验的12小时窗口。时间不足则expired保留证据，不自动延长。

## 配置与命令

正式待绑定配置：`experiments/common/configs/fjsp-eoh-single.real.pending.json`。`provider=null`、`transport_binding=null`、`real_requests_authorized=false`。当前正式prepare、transport和resume入口均主动拒绝，CLI批准参数也不能绕过。

在本工作区执行**check-only**（只读结构、算术LB和已有身份；API=0、策略求解=0）：

```sh
.venv/bin/python -B experiments/common/run_fjsp_eoh_single.py --check-only
```

可选手工Mock练习，生成和评价均为Mock人工分数，工程用途，API=0、策略求解=0；必须使用全新目录：

```sh
.venv/bin/python -u -B experiments/common/run_fjsp_eoh_single.py --config experiments/common/configs/fjsp-eoh-single.mock.json --run --run-dir runs/fjsp-eoh-mock-practice-01
```

辅助操作读取给定运行原冻结参数，不读取后来改动的配置：

```sh
.venv/bin/python -B experiments/common/run_fjsp_eoh_single.py --status runs/fjsp-eoh-mock-practice-01
.venv/bin/python -B experiments/common/run_fjsp_eoh_single.py --pause runs/fjsp-eoh-mock-practice-01
.venv/bin/python -u -B experiments/common/run_fjsp_eoh_single.py --resume runs/fjsp-eoh-mock-practice-01
.venv/bin/python -B experiments/common/run_fjsp_eoh_single.py --report runs/fjsp-eoh-mock-practice-01
```

pause等当前请求与完整候选评价排空后进入paused并释放锁；不要强杀或删锁。completed不得resume。未知预留/评价、源码变化、持久Stop或硬拒绝先核查，不能重发；临时传输连续3次失败由既有执行器安全暂停，用户显式恢复仍沿用旧预算/窗口。

后续由用户手动执行的**正式命令模板**（当前会明确报transport integration pending，绝不启动；不是本轮财务授权）：

```sh
caffeinate -i .venv/bin/python -u -B experiments/common/run_fjsp_eoh_single.py --run --run-dir runs/fjsp-eoh-single-real-20261104-01 --allow-api --approve-budget 1050
```

完成最小接入集成并得到本轮1050次明确授权后，正式resume沿用原目录与原总预算：

```sh
caffeinate -i .venv/bin/python -u -B experiments/common/run_fjsp_eoh_single.py --resume runs/fjsp-eoh-single-real-20261104-01 --allow-api --approve-budget 1050
```

结果为给定运行`analysis/`：Summary.json、candidates.csv、requests.csv、per_instance.csv、完成后的frozen_training_champion.json/champion.py。Mock只生成frozen_engineering_candidate.json，不能称科研冠军。原账本`API_attempts.json`、原Prompt/响应、worker首解/复检和native种群检查点保留；真实费用仍以账单为准。没有覆盖旧运行或默认误恢复已完成任务。

## 离线检查与剩余阻塞

检查覆盖参数/预算、同有序train21/LB/seed/T30、原生四算子与抽样/生存保持、错误/重复计数、初始化不足、不补员、暂停恢复RNG/父代/种群/预算相同、临时故障暂停、未知预留拒绝重发、已完成拒绝resume，以及Mock/物理分数分层。

固定候选验证复用R1的H0完整21例、两遍结果，验证排程/均值/LB/复检并检查单H常量宿主的实际派发参数；没有重新调用求解器。Mock全部是人工分数，不证明EoH搜索有效。新生成候选的真实端到端运行尚未执行。

剩余正式启动阻塞：①API页验收结论及实际客户端源码/参数绑定，完成后在本工作区最小集成并冻结新Protocol；②本轮1050次新预算未获财务授权。当前没有创建真实运行、调用模型、真实求解、导入人工初始池、启动其他种子或改历史记录。原生代码与既有TSP完成实验不受本分支改动影响。
