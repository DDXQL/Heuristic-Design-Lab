# Tier 2 V2：固定融合算子可行性协议

本协议独立于既有 `usage_v2`（历史 SELECT/MIX 接口名称中的 v2）。用户在 2026-10-23
明确授权本地实现、测试、Mock、正式 train21 求解、分析、报告、提交及推送；真实 LLM API、
收费服务和新一轮演化均不授权。本模块不导入供应商调用模块，并在正式父/子进程安装网络拒绝审计钩子。

## 数学定义与执行流程

排程状态 -> 七维 `features()` -> 可信 U 输出 `(operator, vector)` -> 合法动作枚举 ->
启用 H 对全部合法动作评分 -> 每列沿用冻结 V1 `normalize_scores` -> 融合 -> 首个最大动作 -> 提交。

- `SELECT`：vector 为 10 个有限内置数值的成员分数，可负或全零；同分取小编号。
- `WEIGHTED_SUM`：vector 为 10 个非负权重，恰有 1 或 2 个严格正项；沿用 V1 最大值缩放及归一化。
  单成员直接使用原始 H 分数；双成员为 `sum(alpha_i * normalized_h_i)`，使用原 `math.fsum`。
- `MAX` / `MIN`：恰有两个等值正支持指示项，分别取两列归一化分数的最大/最小值。
  非等值指示项直接拒绝，不静默忽略权重。后续可另增明确版本的加权 extrema，本轮不支持。
- vector 长度等于冻结 H 数；不自动 top-2，不裁剪负权重，不修复全零，不回退 H。
- U 数值沿用 V1：内置 int/float、有限、绝对值不超过 1e100，拒绝 bool、NaN/Inf；
  H 标量沿用 V1 Real->float 检查，拒绝 bool、非有限及转换错误。
- 双成员每列常量归零；单合法动作下两列均归零。同分为原枚举首项；实际为 job 顺序、
  operation 的 alternatives 顺序，不能未经输入排序核验就概括为无条件按 machine 数字排序。
- previous_heuristic：WS 取最大归一化权重成员，同权取小编号；MAX/MIN 两成员等值，取小编号。
- `SUM = normalized_h_a + normalized_h_b` 与 `.5/.5 WEIGHTED_SUM` 正比例排序等价，不单列。

可信 callable U 每次均接收原七状态，可返回不同 operator、支持集、WS 权重，预留动态扩展。
这不是 LLM AST 协议扩展，本轮没有生成程序或演化。V1 适配器显式将 mode 0/1 映射为
SELECT/WEIGHTED_SUM，原执行器、旧候选语言及历史协议均不修改。

## 预先固定的正式评价

成员对 (0,1)、(0,5)、(5,9)，算子 WEIGHTED_SUM(.5,.5)、MAX、MIN，共9策略。
冻结 H、train21 原顺序、seed501、原始合法动作和同分规则、未取整 V5 LB。
每实例从空排程完整首解与复检，结果对象、物理排程、H调用次数必须一致。
最多189项、378遍；不使用正式候选缓存。H0和H01等权引用完整身份匹配的历史结果，单独标示来源。
任一实例失败，该策略全21 Fitness=null，不用成功前缀算均值。

原父进程15秒管道等待期限覆盖首解、复检、trace序列化及回传准备，不宣称 recv 硬实时可打断。
独立V2沿用已离线验收的 collect_with_lifecycle / classify_boundary：持久化启动和进程终态、
源文件前后哈希、子进程加载字节码与源码匹配身份。明确超时必须有起始身份、父等待触发、
确认终止退出码及整套文件前后不变，才可记候选无效并继续；正常返回必须有结束身份和exit0。
身份缺失、未认证终态、结果不一致、预算越界全部停止，保留Stop.json，禁止自动重发/重评未知预留。

## 同状态诊断与证据层次

只在首解记录全物理状态、全部合法动作和两列评分；复检无轨迹；不增加完整求解或 H 调用。
正式求解后对同一矩阵离线计算三个算子，核对已执行算子可逐步复现。分来源轨迹和状态去重并集报告。
状态键包括实例、完整部分排程/ready/cursors及历史成员，不能只以七维聚合量认定同状态。
记录动作差异、顶端同分、多策略物理排程相同数量、逐实例Cmax与Fitness差值、耗时、调用数。
这是所访问状态上的局部动作能力证据；完整求解质量是另一层证据，不能互相替代。

MAX在归一化双列下总有列最大值，其稳定首个最大动作必为某成员首选，可由单成员端点选择实现。
MIN可产生任何线性加权都无法首选的折衷动作（离线人工矩阵验证）；这不等于本轮真实状态一定出现该情况。
不把与等权动作不同解释为超出所有连续WS权重，不从局部动作差异断言最终收益。

## 报告与复现

运行入口 `experiments/tier2/fusion_v2/run.py`，实现 `fjsp_usage/fusion_v2/execution.py`，
实验生命周期和分析 `tools/fusion_v2_experiment.py`，测试 `tests/test_fusion_v2.py`。
`PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v2/run.py {prepare,check,run,report} --run-dir runs/新目录`。
原始记录在独立 runs 中；CSV/JSON、压缩同状态决策表、原始结果与身份回执、中文报告在同名 reports 中。
train21为开发集，仅描述配对差值/胜负，不作确认性统计推断，不访问validation11或test28。
