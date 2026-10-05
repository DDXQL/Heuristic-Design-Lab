# S1–S6 开发验收记录

日期：2026-10-05。依据 `PRD_TIER2_REAL_EXPERIMENTS_v1.md`，完成开发验收级交付。
本轮没有真实模型调用，没有打开真实 validation/test 实例，没有开展真实演化研究。
合成 H/U、合成 validation/test 和本地 HTTP token 数均不可作为正式研究产物或性能证据。

## 六项交付

| 步骤 | 已实现 | 验收证据 |
|---|---|---|
| S1 | K/N/交叉/变异参数独立；固定种子、配额、数据与运行源码/依赖协议 | 参数边界测试；全链路 K=3、N=10、cross=5、mutation=1 |
| S2 | 单次 POST、连接/读取/总期限、usage/null、全局与阶段预算、脱敏、保守恢复 | 401/429/503、畸形/截断、慢速滴流、usage 缺失；无重试与额外发送 |
| S3 | 精确 K、连续 int ID、AST 去重、真实请求出处、全 train 向量、代码绑定审查和 H 冻结 | 合成→正式、缺员、bool/缺口编号、错键、未审查、样本变化均拒绝 |
| S4 | 每种子共享初始化；四组独立搜索；代际父代固定；最终种群绑定源请求和评价 | 两个种子、八个组/重复；算子配额、父代数量和出处核对；初始化不足不补跑 |
| S5 | 最终种群 validation、全批次失效、稳定同分选择、固定 h 参照、实验冻结、无模型 test | 越阶段读取拒绝；组内全失效无替补；模型创建被禁止的 test/恢复仍成功；代码/资产/数据变化拒绝 |
| S6 | 统计、失败率、配对数/原因、请求/token/本地评价分账、时钟口径与低开销恢复 | 全部61项测试通过（既有42+新增19）；完整合成流程与恢复通过 |

为保留旧版语义，PRD 中拟放入旧 `research/` 的新增模块实际放入独立的
`code/fjsp_usage/research_real/`。入口为 `experiments/tier2/research_real_v1/run.py`。
本轮原有137个受 Git 跟踪文件逐字节保持不变；冻结 Tier1、v1/v2 和旧 mock 版本未覆盖。

## 实际完成的合成验收

新运行：`runs/s1-s6-final-20261005/`，原始记录保持 Git 忽略。
合成 train/validation/test 各2个微型实例，由新脚本独立写出，不复制 benchmark holdouts。

| 项目 | 观测结果 |
|---|---:|
| H 初始化 / H 演化本地请求 | 3 / 10 |
| 两个种子共享 U 初始化本地请求 | 20 |
| 四组 × 两种子 × 10 次演化本地请求 | 80 |
| 总预留 / 确认发送 | 113 / 113 |
| 最终 U* | 8 |
| 每组计划 / 成功重复 | 2 / 2 |
| 固定 h 参照 | validation 选一次，test 固定使用 |
| 唯一 validation/test 整批评价缓存 | 92 |
| 完成后恢复新增本地 POST | 0 |
| 真实 LLM 调用 | 0 |

这里的 U 响应是按请求序号变化的手写函数；同分候选仍按不同代码保留。
四组在这些微型合成实例上得到相同结果，因此没有“P 更优”的证据或结论。
合成自动审查仅支持单 return 表达式，并保留表达式、固定动作样本与显式 synthetic 标记。
正式 H 必须提供代码键绑定的审查文件，不能沿用合成审查。

## 新增文件与运行

- `code/fjsp_usage/research_real/`：配置/源码闭包、请求与预算、资产审查、数据门禁、评价缓存与计时、搜索适配、流程、锁、本地服务和报告。
- `experiments/tier2/research_real_v1/`：新入口、版本 manifest、默认禁止真实请求的配置示例、运行说明。
- `tests/test_research_real_transport.py` / `tests/test_research_real_workflow.py`：网络故障、预算、恢复、配对搜索、选择、冻结、数据改变与报告验证。
- 本记录及 `S1_S6_ACCEPTANCE_EVIDENCE.json`：可提交的脱敏验收摘要。

项目根目录运行：

```sh
PYTHONPATH=code .venv/bin/python experiments/tier2/research_real_v1/run.py all-synthetic --run-dir runs/my-s1-s6
PYTHONPATH=code .venv/bin/python -m unittest discover -s tests -v
```

详细分阶段用法、审查格式与网关协议见 `experiments/tier2/research_real_v1/README.md`。
过程只保存事件、检查点和 `progress.json`，不扩大可视化或全训练动作日志。
单次排程（含可行性检查）、确定性复核、进程启动/评价总耗时采用不同口径。
恢复仍核对合法阶段的数据文件哈希；缓存不能绕过数据变化检查。

## 限制与剩余工作

**S1–S6 是开发完成，S7–S11 仍未完成。**

| 后续 | 必须完成 |
|---|---|
| S7 | 确定供应商/模型、认证方式、正式 K/R、资源与真实预算；验证供应商原生协议、usage（含缓存）与价格 |
| S8 | 在获准真实预算内只用 train 试跑 H/U，人工审查 H、核对真实 response/usage/账单 |
| S9 | 冻结协议后执行正式 R 次四组搜索，保留失败与全部请求出处 |
| S10 | 只对各最终种群执行真实11个 validation，选择 U* 和固定 h，冻结完整实验 |
| S11 | 冻结后执行真实28个 test，交付配对统计、成本、负结果与复现资产 |

当前网络层支持明确定义的 `json-candidate-v1` 网关，不代表任何具体供应商 API 已接通。
token 上界没有供应商认证，金额为按配置价目估计；只有请求槽位是可保证的硬上限。
未知 usage 保留 null/预留计量，不声称零费用或供应商未计费。
使用审计过的最小 EoH-S 互补选择机制，不宣称完整复现上游框架。
哈希检查保证一致性而非特权攻击者防伪；候选 AST 限制与进程终止并非通用 OS 沙箱。

因此尚不能声称“正式 EoH-S 集合、LLM 生成 U、正式演化及真实 validation/test 实验完成”。
