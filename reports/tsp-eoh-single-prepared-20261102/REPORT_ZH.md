# TSP EoH单规则基线：本地交付

状态：代码、配置、比较模板及针对性离线检查已完成；**未启动真实EoH训练，未发送模型请求**。正式实验由用户终端启动。

工作树：`/Users/DDXQL/Developer/Heuristic-Design-Lab-tsp-eoh-single`，分支`codex/tsp-eoh-single-20261102`。基于9997ecd另建Git worktree；既有H/U及FJSP各工作区没有修改。共享现有Python环境，仅建立.venv符号链接，不安装/升级依赖。

## 协议与预算

- 直接演化一条TSP H，复用本地LLM4AD EoH（eoh.py标注2025/2/16）的原生Prompt、种群、父代抽样与生存选择；未修改原生源码，SHA见EOH_SOURCE_AUDIT.json。
- N=5；I1初始化，E1/E2/M1/M2顺序循环；本版本没有M3。原生有放回排名抽样、源码/平均分重复惩罚均保留，不替换为U的CROSS/MUTATE或CPM。
- 原版max_sample_nums与HTTP单位不同。本次以持久HTTP预约账本为主：最多260次、每槽1次、失败/重复计入、不补发。初始化原生2N=10评价样本封顶，另加20次HTTP封顶，全部计入260。G不预设，原生代数/实际生存更新分别导出。
- 严格复用原train20、模型gpt-6.1-sol及provider全部参数、五参数H接口、封闭语言、seed501、T30、NN目标及完整首解/复检。构造与物理评价源码逐文件SHA一致。无局部搜索，不读留出集，训练冠军按完整Fitness降序/ID升序选择。
- 端到端上限：既有H40+U220=260；实际40+213=253。确认发送38+211=249另列。EoH同时导出第253槽及≤260最终结果、已知token/未知usage；不把同上限写成相同实际费用。
- 最坏5200条程序×实例行、10400遍求解。依上一轮成功请求为数秒、部分请求约126秒超时的经验，可按约2–4小时粗估串行运行；这不是当晚服务测速或完成承诺。12小时持久窗口含暂停，不自动延期。连续3次传输失败安全暂停，认证/额度/型号硬错误停止，未知发送不自动重发。

## 已验证

10项针对性检查通过：原生登记/抽样一致性；HTTP错误、解析失败、AST重复占用预算；四算子调度；暂停恢复的父代与随机状态一致；连续失败暂停；未知预约/计划篡改拒绝；初始化不足；同分有放回父代；既有真实结果上的配对公式。共享执行器3项回归通过。

另有固定Mock候选的真实求解：smoke2上12条候选（24实例行、48遍）；完整train20上2条候选（40实例行、80遍），首解/复检全部一致。它们是**Mock生成＋真实求解的工程资产，不是LLM科研成绩**。日志与VERIFICATION.json保留路径和源码身份；较早小试与首次测试路径错误的记录也保留，不冒称正式训练结果。

比较模板`comparison-preview/`已生成中文报告、CSV、3组PNG/可编辑SVG；只画既有U的真实曲线，EoH结果和逐实例比较保留空白。没有使用历史FJSP或旧5H填数。

## 直接操作

先进入上述工作树。默认无动作等同check-only，参数文件为`experiments/common/configs/tsp-eoh-single.real.pending.json`；不需要改运行脚本。

**check-only（API=0，策略求解=0）：**

```bash
.venv/bin/python -B experiments/common/run_tsp_eoh_single.py --check-only
```

**正式训练（用户启动，本轮至多260次）：**

```bash
.venv/bin/python -u -B experiments/common/run_tsp_eoh_single.py --run --allow-api --approve-budget 260
```

**进度，只读：**

```bash
.venv/bin/python -B experiments/common/run_tsp_eoh_single.py --status runs/tsp-eoh-single-real-20261102-01
```

**安全暂停：**

```bash
.venv/bin/python -B experiments/common/run_tsp_eoh_single.py --pause runs/tsp-eoh-single-real-20261102-01
```

等待phase=paused、writer_lock=false后，**按原预算恢复**：

```bash
.venv/bin/python -u -B experiments/common/run_tsp_eoh_single.py --resume runs/tsp-eoh-single-real-20261102-01 --allow-api --approve-budget 260
```

**离线比较/阶段汇总（API=0，求解=0）：**

```bash
.venv/bin/python -B experiments/common/summarize_tsp_eoh.py --run-dir runs/tsp-eoh-single-real-20261102-01
```

正式输出：`/Users/DDXQL/Developer/Heuristic-Design-Lab-tsp-eoh-single/runs/tsp-eoh-single-real-20261102-01/analysis/`。结束/安全暂停后自动汇总；失败不损坏原结果，可独立重做报告。包括请求/失败/重复/usage、逐实例、种群/谱系/冠军、固定预算节点、执行段/暂停时间、上限与实际量对照，以及01_budget_fitness、02_final_comparison、03_instance_comparison的PNG/SVG。

完整方法与限制见`docs/TSP_EOH_SINGLE_COMPARISON_V1.md`。没有未解决的本地工程阻塞；外部前提是用户启动终端具备原有LEAFAPI_API_KEY，端点可用性/真实成功率/真实EoH效果尚未在线验证。本轮不创建财务授权，不自动追加实验。两个工作树仍有数据/结果引用关系，暂不移动或删除历史证据。
