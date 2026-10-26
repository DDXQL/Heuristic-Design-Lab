# 通用组件抽取与FJSP回归

起点：codex/h-usage-space，5b2e2e96f5f927dc159810c8d1cc7532e84a1466。根目录写权限实测成功。适用AGENTS.md为空，仓库内部无额外指令。现有未跟踪实验产物保留，远端/主目录未改。

新增heuristic_design.core：任务执行、锁、检查点、原窗口、预算、暂停恢复、排名抽样和代末生存；通过ProblemAdapter取得提示、校验和评价，不包含FJSP状态/Cmax/机器语义。API传输保留legacy桥接，以兼容既有落盘/重试和未知状态保护。FJSP适配层封装原候选语言、提示及T30认证；旧manage.py入口仍可用。历史evolution/sets/求解器/认证源码未改。

before.json与after.json记录完整语义，Comparison.json全部相等：H0单选及H0/H1等权 × toy与Behnke1，共4策略实例。包括所有U状态、合法动作/分数、实际决策、排程、Fitness、首解复检、认证哈希和H调用。Behnke1已有认证：H0 Cmax106，等权100；physical哈希完全相等。toy两者Cmax7、LB6。

runs/fjsp-extraction-before-20261026-v1与runs/fjsp-extraction-after-20261026-v2为新目录，旧证据未修改。after-v1因新适配层漏导入validate_result停止，证据和锁保留；修复后建立v2重新进行工程回归，无API。After.log/After_v2.log及初始失败测试日志保留，不将失败称为成功。

Tests_v2.log：原操作入口11项+通用排名等价/结果完整性2项。含真实子进程toy首解复检、Mock生成、后台暂停恢复、原窗口/预算保护、未知状态及源身份拒绝。无真实API。

复现（新capture不能覆盖已有证据；比较只读）：

```sh
PYTHONPATH=code:. .venv/bin/python -B -m unittest tests.test_experiment_ops tests.test_generic_search -v
.venv/bin/python -B tools/verify_fjsp_extraction.py compare
```

TSP完整授权协议和事前选择规则已保存docs/TSP_PILOT_PROTOCOL_V1.md；通用化提交后才实现TSP。未推送。
