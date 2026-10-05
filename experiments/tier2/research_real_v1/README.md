# 分阶段研究版本：S1–S6

这是 PRD 的正式流程**软件实现**，当前验收只使用本地 HTTP 服务和独立生成的合成 split。
没有调用真实 LLM，没有生成正式 EoH-S H，没有完成真实演化、真实 validation/test 或研究结论。
旧 Tier1、offline_v1/v2、research_v1 保持原样。新代码独立位于 `code/fjsp_usage/research_real/`，
避免将 mock 请求层或冻结基线改成另一种语义。

## 一条命令跑完整合成验收

在项目根目录执行：

```sh
PYTHONPATH=code .venv/bin/python experiments/tier2/research_real_v1/run.py all-synthetic --run-dir runs/my-s1-s6
```

脚本启动临时本地服务，使用手写响应，生成独立的 train/validation/test 各两个微型实例。
参数为 K=3、N=10、交叉父代5、变异父代1、G=1、每组10次尝试、种子101/102。
正常共113次本地 POST（H 3+10、共享初始化20、四组搜索80），没有模型调用/账单。
脚本按阶段显示短进度，不记录全训练动作轨迹。

相同源码、配置、数据及运行环境下恢复：

```sh
PYTHONPATH=code .venv/bin/python experiments/tier2/research_real_v1/run.py all-synthetic --run-dir runs/my-s1-s6 --resume
```

已完成运行的恢复不重发请求、不重复评价。临时服务恢复会使用原端口；端口被占用时直接失败，
不会修改协议绕过检查。源代码或配置变化必须另建运行目录。`runs/` 保持忽略，不上传原始记录。

## 结果与过程

| 文件 | 内容 |
|---|---|
| `progress.json` / `events.jsonl` | 阶段与预算摘要，无动画/全训练回放 |
| `protocol.json` | 配置、split 元数据、所有项目运行 Python/实验 JSON/依赖哈希与版本 |
| `budget.json` | 分阶段预留、确认发送、结算/未知 usage、余额 |
| `H_candidates.json` / `H_frozen.json` | 生成出处、完整 train 向量、代码绑定行为审查、精确 K |
| `r<seed>/Shared_initial.json` | 每个种子仅一次共享的 N 个有效 U |
| `r<seed>/<arm>/checkpoint.json` | 父代、算子、失败、代际与评价缓存 |
| `r<seed>/<arm>/Final_population.json` | 最终种群及 HTTP/全 train 出处 |
| `r<seed>/<arm>/U_star.json` | 全最终种群 validation 与稳定同分选择 |
| `Search_complete.json` / `Selection_complete.json` | 阶段访问凭证与所有计划重复状态 |
| `Experiment_frozen.json` | H、U*、固定 h、数据/实现/协议/分析绑定与冻结时间 |
| `Test_complete.json` | 冻结后整批测试，逐实例 makespan/LB/score/可行性/时间 |
| `report.json` / `report.md` | 全部计划重复、失败率、实际配对与原因、统计、成本和时钟口径 |

合成 mode 的资产不能被 real mode 接收。哈希用于一致性检查，不是对能改写全部代码/记录的
特权操作者的数字签名。AST 限制、数值上限和可终止进程也不是通用操作系统沙箱。

## 正式分阶段入口（S7 配置确定后）

复制 `config.real.example.json` 到本机私密运行目录，确定模型、协议、K/N、种子、资源及预算。
示例的 `real_requests_authorized=false`，地址是不可用的占位地址，不能直接请求。
只读取配置显式指定的环境变量；不要把密钥写进 JSON、提示、仓库或聊天。
本轮不替你启用真实请求。

```sh
PYTHONPATH=code .venv/bin/python experiments/tier2/research_real_v1/run.py preflight --run-dir runs/real-pilot --config runs/real-pilot-config.json --manifest data/fjsp_manifest.json
```

preflight 只检查配置与清单，不打开任何实例，不创建模型客户端。
后续使用相同配置/清单，依次执行 `generate-h`、`freeze-h --reviews <本机审查文件>`、
`search`、`select`、`freeze`、`test`、`report`；非空目录均加 `--resume`。
没有自动“全部真实阶段”命令。H 初始化不足、审查缺失或冻结缺失不能继续。
失败/预算耗尽的配对重复会原样披露，不追加种子或候选；扩大预算要登记新运行。

审查文件以每个生成候选的 AST `key` 为键，值有 `description`、`reviewer`、`method`、`note` 四个字符串。
描述须按实际代码说明高分行为；运行器核对代码键并保存三个固定动作的评分样本。
正式模式拒绝 `synthetic...` 审查方法。样本不能代替完整人工代码阅读。

## 网络协议与预算限制

当前实现 `json-candidate-v1` 网关协议，**不是供应商原生 SDK/API 已接通的声明**。
S7 指定供应商后，须根据其官方协议增加并验证适配器、usage（含缓存）及价格口径。

POST 请求字段：`model, prompt, kind, request_id, max_output_tokens, temperature`。
200 响应：`text`（单个 `{说明}` 与 Python 围栏）、可选 `usage`、可选 `finish_reason`。
`usage` 仅支持整数 `input_tokens/output_tokens`；缺失保存 null。
明确非 stop 的结束理由拒绝；成功/401/429/5xx/超时/坏响应均不会自动重试或修复。
连接、读取和总期限有限，慢速滴流也受进程总期限约束。

请求数有全局和阶段硬上限。token 预留尚未经供应商上界认证，金额是按配置价格估计，
不能声称 token/金额都是账单硬上限；观测超预留会停止后续请求。无价格则金额 null。
未知请求保守占用额度，不因没有响应就判定未扣费。合成服务 token 是固定测试数值。

## 排程与数据边界

复用 V5 七个 U 状态标量和七个 h 单动作原始特征。每步调用一次 U，严格检查 built-in int，
然后只用选中 h 给所有合法动作打分；高分优先，平分 job/machine 顺序。
复用实例读取、排程与可行性检查，评分为未取整 V5 LB 的 `-makespan/LB`，取整批均值。
任一实例失败时整批 fitness=null；缓存不会把成功前缀伪装成完整评价。

演化只加载 train；validation 需要搜索完成凭证，只检查各最终种群与固定 H 参照；
test 需要冻结，且不会创建模型客户端。缓存复用仍重新核对允许读取阶段的输入哈希。
单次排程（含可行性检查）与第二次确定性复核分别计时，进程启动和记录另算。
这里的合成计时不能当作部署性能证据。

运行全部测试：

```sh
PYTHONPATH=code .venv/bin/python -m unittest discover -s tests -v
```
