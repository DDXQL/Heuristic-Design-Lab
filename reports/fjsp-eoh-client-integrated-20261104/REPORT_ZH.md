# FJSP EoH客户端集成交付（2026-11-04）

入口已具备正式运行条件。本轮新增模型请求0、策略求解0、正式搜索0；没有实际授权文件或正式运行目录。用户先预览，再显式批准这次1050上限后手动启动。

## 集成与离线验证

复用API专项的非流式V4，两条并发短检查2/2通过。7份共同运行依赖逐字节绑定，仅2份需要更新；技术收据和响应复制到本报告目录，SHA固定，不继承认领或财务授权。完整JSON/精确模型/stop要求保留，调用方额外强制合法非空usage。已知拒绝的完整响应另存caller_rejections，便于后续核对。

24项针对性离线检查全部通过，详见offline-tests.log及VERIFICATION.json。覆盖首次硬故障停止、临时故障连续3次暂停、正常无效H不误触发、累计预算不清零、同账本再次恢复、其他适配默认行为、原生算子/RNG、既有H0完整21例记录回放及CSV/PNG/SVG导出。未重新求解。原生EoH及base源码与52cfc1d完全一致；历史A/B Protocol与检查点SHA保持原样。纯Mock图表已明确标注工程人工评分，不用于科研结论。

## 冻结研究与成本

N5，API1/评价1，seed501；I1与E1/E2/M1/M2，原生排序抽样和生存，不设固定G。不引入局部搜索。同train21、append-only调度、未取整LB_v5、精确同分规则与T30首解/复检共享期限。完整train冠军按Fitness最高、固定ID平局冻结，不访问validation。

总物理尝试1050包含初始化；初始化HTTP最多50、原生初始化评价样本最多2N=10。每槽一次，失败/重复/未知发送均计数，不补发。演化余额1050减实际初始化。导出每个预算槽及完整有效AST唯一H评价数曲线；1023和1050节点均保留，未到节点留空。48h原窗口含暂停，恢复不重置。

历史A实际1023；B新增1000、P0来源23次和重评成本另列。H构建成本未知部分明确另列而非当0。并发、N、父代/算子/选择、表达空间及传输时段不同，只作共同任务、共同观察预算前缀下的探索性比较，不宣称严格同期、仅改变状态或端到端等成本。PARAMETER_COMPARISON.csv及BUDGET.json列出差异。

## 停止、恢复与边界

明确拒绝或完整响应协议/usage失败首次停；临时/未知传输失败连续3个完整任务暂停。安全暂停结算当前有界任务、保存检查点并释放本控制器锁。普通无效候选不当成基础设施失败。无自动重试/重启/退费/其他seed。

软暂停可由用户显式恢复；硬停持久api_stop_reason不允许普通resume，需要另行核查处理，不能删锁或清账绕过。未知在途保留证据和锁，不重发。恢复只读原冻结参数、种群/RNG、原预算与时钟，不读取后来修改的配置来改变实验。

## 启动与输出

完整可复制命令见../../docs/FJSP_EOH_NONSTREAM_RUN_20261104.md。新配置experiments/common/configs/fjsp-eoh-single.real.json默认real_requests_authorized=false；只有用户的--run --allow-api --approve-budget 1050明确启用。密钥只从LEAFAPI_API_KEY环境变量读取，预览不读取密钥值。

默认目录：/Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-single/runs/fjsp-eoh-single-nonstream-20261104-01
日志terminal.log；结果analysis/；完成后frozen_training_champion.json与champion.py。普通启动遇已有目录拒绝，完成后禁止resume。

没有剩余本地代码阻塞。启动前用户需在自己的终端提供环境变量并确认新预算。2条短检查不代表长期稳定，实际模型身份与usage只是协议报告而非独立模型鉴定或核实账单；新增EoH真实H生成成功率尚未在线验证。后续按预定停止规则处理，不追加本页诊断。
