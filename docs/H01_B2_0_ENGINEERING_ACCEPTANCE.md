# B2-0：H0/H1 两代实验轻量预算适配

本阶段仅做工程准备及离线Mock验收，真实模型请求、账户/价格/账单查询、新21train评价均为0。B2-1尚未授权，不自动进入。

新身份：`H01-alpha-search-seed501-local-requests-v2-20261020`。
新目录：`runs/h01-state-weight-search-seed501-local-v2-20261020/`。
原科研协议：`H01-alpha-search-seed501-v1-20261019`。

## 实现边界

- `tools/h01_weight_local.py`：H01专用轻量入口。复用原`WeightSearch`、Prompt构造器、语言校验器、评价和网格函数；只适配预算、交接、来源绑定及新身份。旧`tools/h01_weight_search.py`不改。
- `tools/h01_weight_report.py`：原报告的可选新协议参数；轻量模式不读账单、费用为null；增加常量/实例内观测动态分类、每代冠军来源、子代存活和跨代父代来源。
- `tests/test_h01_weight_local.py`：临时目录中的手写响应及虚构成绩，禁止真实网络、旧财务入口、数据加载和训练评价。Mock种群不写入新正式目录。

新配置逐项比较旧配置，只有协议身份、执行授权、预算及固定H来源字段可不同。以下不变：原10H和编号、七状态、H0/H1互补权重与端点、原语言、Prompt字节、gpt-6.1-sol共同参数及输出配置、21train、评分、共享15秒、seed501/N5/两代/每代5交叉5变异、20请求上限、原父代抽取和生存选择。

Prompt继续不含父代fitness。评价仅经外部父代/生存选择反馈，不能描述成LLM直接读取分数后反思。

## 原8项指纹失配

全部以**旧哈希→当前哈希**写入新`Plan.json.identity_changes`，不更新旧Plan。没有豁免其他旧冻结输入。

| 原失配文件 | 分类与处理 |
|---|---|
| `research_real/budget.py` | 工程：复用轻量累计计数与持久请求日志 |
| `research_real/config.py` | 工程：显式新预算声明，科研字段逐项核对 |
| `research_real/workflow.py` | 工程：现有客户端分流；新专用入口不走旧财务客户端 |
| `usage_v2/access.py` | 工程：复用完整响应落盘和拒绝重发 |
| `usage_v2/config.py` | 工程：已有新协议及固定H声明；不套用其一代A/B规模 |
| `usage_v2/registration.py` | 工程：复用跨worktree锁/唯一账本盘点 |
| `usage_v2/workflow.py` | 工程及报告分流：已有H绑定/报告兼容路径 |
| `experiments/tier2/usage_v2/run.py` | 工程：已有轻量CLI；本批仍用H01专用入口 |

原8项中没有排程、状态、语言、Prompt、进化核心或评价核心文件失配。此次`h01_weight_report.py`的变化另列为报告/导出变化，不冒充原8项之一。

固定H使用现有`usage_v2.fixed_h.source_h`核验原批准链、收据、审查、成员及完整成绩；不重新生成H或伪造新审查。科学/数据旧指纹严格保持。新`H_source_binding.json`为工程预绑定，执行协议建立后才生成对应上下文的`H_frozen.json`。

## 交接与计数

读取第一页原始protocol、budget、A/B请求日志、checkpoint及封口终态。允许明确停止且释放调用权的30/60，不要求补满60。逐请求核对原生状态、usage、Prompt哈希及唯一请求键，不以汇总代替原记录；存在writer、pending、孤立账本记录或不一致则拒绝。

第一页遗留的一个prepared-only inflight没有原生请求、账本或wire记录，登记为未发送的准备项，原样保留，不恢复。未知历史usage/费用及原预留均保留在来源记录，不要求结清后才能使用新轻量机制。

累计计数直接调用公共`request_history`：冻结前驱protocol/budget哈希，跨worktree核对唯一库存。准备时核对累计231槽，本批最多20槽，计划上界251/300；正式启动前再次核验，不能把该快照当永久额度。没有余额或金额边界保证，实际费用为unknown/null。

## 使用入口及启动隔离

纯离线检查：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. \
  .venv/bin/python -B tools/h01_weight_local.py check \
  --run-dir runs/h01-state-weight-search-seed501-local-v2-20261020
```

新目录`config.pending.json.real_requests_authorized=false`，没有执行授权文件、真实请求账本或搜索checkpoint。即使误调用`grid`或`search`，也必须先通过`B2_1_authorization.json`门禁，且在加载密钥、创建客户端或解析训练实例前拒绝。

未来经用户明确确认B2-1后，授权文件必须精确绑定`stage=B2-1`、`approved=true`、`person=DDXQL`、最终Plan的SHA256及`max_new_requests=20`。本阶段不创建该文件。未来执行顺序为同一专用入口的`grid`→`search`→`report`；`search`另需原有`--env-file`路径。不使用旧register/check入口恢复原准备。

恢复保持同一协议、ledger、wire和checkpoint：完成、失败、超时、pending或孤立预留均不自动重发；本地评价沿原started标记最多一次，不加时或重评。

## 验收与解释

测试命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. \
  .venv/bin/python -B -m unittest \
  test_h01_weight_local test_h01_weight_search test_local_request_budget -v
```

新检查覆盖：科研参数/Prompt不变，科学核心和数据/初始池篡改拒绝，停止30槽交接，writer/原生证据不一致拒绝，累计库存和上限，20槽中失败/重复/中断恢复，两代继承，零子代存活，以及报告费用null/初始冠军不计模型收益。旧H01检查的spawn测试使用零实例，无FJSP求解。

验收共34个不同检查通过：原求解环境33项通过，1项绘图检查在文档环境单独通过。真实H来源及新入口`prepare/check`也已离线通过；未运行网格或搜索。原准备目录42个文件的字节和mtime保持不变。

报告分别保留初始手工来源、21点网格、模型新常量、模型新观测动态、各代/最终冠军和全部未存活候选。实例内权重变化是行为记录，不是动态性因果收益；超过有限静态网格也不是超过所有常量。

B2-1预计：最多20次模型请求；复用5个已有静态点，其余16个固定点加最多20个模型候选，即最多36次完整21train评价、756个候选—实例评价，全部成功时1512遍求解。端点已有语义复用，不需额外求解。失败和重复可减少实际评价数，不增加请求或补发。

最终机器证据及测试记录见`docs/usage-space/h01-local-b20-prepared/`；原准备目录和历史原始记录保持字节及mtime不变。B2-0完成后停止，B2-1需要新的用户确认。
