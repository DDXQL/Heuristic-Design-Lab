# V1-0：冻结双策略独立配对验证工程验收

2026-10-21（Asia/Manila）。仅工程准备、数据元信息审查及Mock验收；**test28正式求解0、LeafAPI请求0，未进入V1-1。** B2-1的258个运行/报告文件逐项核对内容与mtime，全部保持不变。

## 协议与冻结对象

身份：`V1-H01-frozen-pair-test28-v1-20261021`。

独立目录：`runs/v1-h01-frozen-pair-test28-v1-20261021/`。

协议SHA256：`11e87d24f00eeec628659cddcff2e796cd9f6824c062da4323623162ff3bad60`。

|冻结对象|SHA256|
|---|---|
|动态冠军B/g0001/000000源码|`1b14f82301314f25ecb8ff1d55b07439f6aeaf331102098cea7920d0c2e9bd52`|
|原人工alpha_050源码|`f008e876861877b7b6253ecfdc306af2313748254d938a95c8867e5c2dd83cd6`|
|原B2-1 H_frozen.json副本|`042157b541aa6fda4dc69082a075a08ade814d3c3cc273e6c0327b6fdd189dc2`|
|原manifest|`45ccd4ff820b387f89fd1b4bbf4e714e8517d1f68578d7d65ac8ea720e6a42f2`|
|V1薄入口tools/h01_v1.py|`618b3de6b1638d5d95c40ca9b9d5a5327fe0c66b8cf2a53571a069789fdacff8`|
|元信息准备tools/h01_v1_prepare.py|`824f2597314193e9fac5f6e349395171d1b8fc43de1b78c5b3f63a637500d207`|
|原评价核心runtime.py|`13c60b36e7ddee45e3090dcc945d74b768daf1e35884d55f6e574ce7fa4c45e8`|
|原MIX执行器execution.py|`3d6a4c8dcbd15f2ea8955a2274e4c526b8995adc7d63314b02fbcbb2b86f8da0`|
|原状态/LB模块offline_v2.py|`caef17f0e3c7ebdb936ce109517a2585c42cf4e9541134732932ef4432b0467d`|

完整260行冻结对象清单见[验收归档/Frozen_objects.csv](usage-space/v1-0-prepared-20261021/Frozen_objects.csv)：包括协议本身、B2既有221项冻结输入及38项V1代码/数据/元信息输入。全部28个文件的原始SHA、实际来源、相对路径、LB另见[Data_identity.csv](usage-space/v1-0-prepared-20261021/Data_identity.csv)。协议中同时绑定两份U的原代码键和10条H的有序代码键，K仍为10，仅H0/H1可启用。没有生成新H、U或新技术审查。

本次新增文件仅两个工具、一个测试模块及准备/验收材料；未修改任何生产调度器、七状态、MIX归一化、历史更新、同分规则或B2-1文件。

## 数据来源、使用历史及证据边界

原manifest登记Behnke–Geiger基准的train21/validation11/test28。其旧`source_root`已不可用，本次实际读取主worktree `FJSP-Heuristic-Research/data/fjsp/` 的28个test文件，逐字节匹配原manifest后复制至新目录`inputs/test/`，未改主worktree。副本和两份U/H设为只读；哈希仍是运行身份的主要校验手段。

检查证据包括：此前Dataset_usage_audit、原H阶段总结、B2-1最终审计、10H/已有U/任务4A诊断登记，以及三个研究worktree的原生Test_complete/Selection_complete/Experiment_frozen/Development_test_complete阶段索引和历史单规则记录。共15项命名证据、39个阶段标记，路径和SHA全部保存在[Data_history_audit.json](usage-space/v1-0-prepared-20261021/Data_history_audit.json)。只读取必要元信息，不比较任何test策略成绩。

在这些范围内，正式Test_complete记录均为synthetic；唯一真实开发test明确为Behnke4/13/14，均属于train21。validation11已用于历史开发，排除作为严格独立证明。B2-1及已检查的近期诊断均以训练数据为范围，未发现test28用于当前冠军形成的记录。

**结论是“已检查项目记录未发现test28暴露”，不是“严格证明从未使用”。** 未能认证自定义/未登记文件、已删除记录、项目外脚本、人工反馈、LLM预训练或同源生成相关性。V1-1须由DDXQL确认据其所知没有未登记的test28成绩使用影响H/U，并明确接受一次性使用原保留test28。若发现实际使用或重复，不能靠授权字段覆盖门禁。

## 结构与重复检查（不含策略求解）

|指标|train21|test28|
|---|---:|---:|
|机器数20/40/60的实例数|7/7/7|10/9/9|
|作业数范围；均值|10–100；36.19|10–100；50.71|
|工序数范围；均值|50–500；180.95|50–500；253.57|
|平均可选机器数/M的均值|0.31530|0.31373|
|名义机器负荷最大份额均值|0.05608|0.05542|

49个文件在三种口径下均未发现重复：原字节、忽略文件头的有序工序记录、忽略作业编号的作业记录多重集；包括跨train/test检查。未进行完整机器重编号同构或近重复认证。没有依据策略成绩筛选或替换任何实例，仍保留全部原28个test。

名义负荷定义为`L_m=Σ_o p_om/|A_o|`，不是实际排程负荷。test平均规模偏大，可能改变质量和超时分布；因此这是同一基准族中的留出比较，不代表跨基准族或工业分布泛化。具体逐实例元信息见[结构表](usage-space/v1-0-prepared-20261021/Structure_train21_test28.csv)。

## 评价、恢复与结果字段

唯一入口为`tools/h01_v1.py`，阶段为prepare/check/run/report，没有搜索或validation选优阶段。prepare只做来源核验、数据解析/结构统计及复制，不调用评价器；check只做身份核验。

正式run只复用原`h01_weight_search.evaluate_weight`，每个实例分别运行两个原U。顺序按原test名单交替：偶数序号dynamic→equal，奇数equal→dynamic。每程序—实例首次求解与确定性复检共享15秒，允许模式仅MIX；不新增观察回放。

固定56个任务，成功时112遍求解。使用现有单目录RunLock，不新增全局调用锁。检查点保存协议身份和已预留任务；结果先落盘再提交检查点。已完成结果不重评；已保存结果但未提交检查点可恢复；预留后中断且结果未知记无效、不退款或重跑。孤立结果、错误协议、文件损坏或冻结输入变化均拒绝继续。底层PairRun不提供绕过CLI后的并发安全。

单实例评价失败不加时、不修U、不重评，其他已登记任务继续。任何程序有一例失败则该程序完整Fitness与Cmax总和为null，主配对统计也为null；成功子集只能逐行展示，不替代完整对照。工程异常会停止当前调用，保留预留；恢复亦遵循不重评未知任务的规则。

Paired_results.csv输出两侧Cmax、LB、Cmax/LB、配对差值、胜负平、可行/失败状态、复检一致性、墙钟时间、h调用及物理排程哈希；完整原始结果另存逐任务JSON。V1_report.json输出完整Fitness、总makespan（非优化目标）、已认证成本、失败/未知范围及统计结果。墙钟秒不冒充CPU进程秒，失败h调用未知不填0。

## 冻结统计

主指标`ΔF=mean((Cmax_equal-Cmax_dynamic)/LB)`，正值表示动态程序较好。LB由原`lower_bound_v5`计算，负载项不取整，不使用未核实BKS。

配对均值BCa固定20,000次、NumPy随机种子1701、95%区间；重抽样差值向量等价于对齐实例对重抽样。当前环境没有SciPy，使用NumPy与标准库的均值专用BCa：偏差z0采用平局中秩，逐对删除jackknife加速度，线性分位数；实现及NumPy/Python版本已冻结。退化、非有限或计算错误时CI=null并保留原因，不切换方法。精确符号检验为剔除平局后的双侧Binomial(n,.5)，全平时标记无试验而非编造p值。

只有全部28对完整有效时计算主统计。统计单位是实例对，不是112遍求解；区间和符号检验需披露独立性假设、同源相关性及样本小的限制。固定冠军，不根据V1结果选择检验、扩大样本或更换程序。

## 离线验收

- 20项单元Mock检查全部通过，网络、真实评价器及通用Workflow.select均被禁止调用；只使用临时合成响应/计时/调用数与少量合成实例文件。
- 完整28实例/56任务Mock完成；第二次运行新增评价0。
- 动态U、等权U、H、test输入、评价核心五类模拟SHA失配均被拒绝，实际文件未修改。
- 真实CLI在缺少V1-1授权时拒绝，未创建checkpoint/results，未加载test进行求解。
- B2-1全部258个运行及报告文件内容和mtime保持不变。

验收记录及原始日志见[准备归档](usage-space/v1-0-prepared-20261021/)。Mock数值全部明确标记，不属于V1科研结果。

## 启动条件与命令

**工程准备已就绪；正式执行仍未授权。** 没有创建`V1_1_authorization.json`。未来授权需绑定本协议SHA，包含：`stage=V1-1, approved=true, person=DDXQL, no_known_unrecorded_test28_use=true, accept_reserved_test28_consumption=true`。这两项确认是具体数据独立性和保留集用途声明，不是新的H审查。

已执行的安全核验：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python -B \
  tools/h01_v1.py check --run-dir runs/v1-h01-frozen-pair-test28-v1-20261021
```

仅供V1-1再次明确授权后执行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python -B \
  tools/h01_v1.py run --run-dir runs/v1-h01-frozen-pair-test28-v1-20261021
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python -B \
  tools/h01_v1.py report --run-dir runs/v1-h01-frozen-pair-test28-v1-20261021
```

恢复使用同一个run命令和目录，不重建配额。最多56个程序—实例评价／112遍成功求解，期限窗口合计最多840秒（14分钟），另有加载、编译、进程启动和报告开销。没有API、费用查询或新种群。

V1-0到此停止。独立性确认、一次性消费test28和V1-1正式执行仍需用户明确授权。
