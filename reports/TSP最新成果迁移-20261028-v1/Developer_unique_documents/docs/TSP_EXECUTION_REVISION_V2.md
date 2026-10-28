# TSP执行修订v2：说明文字包装兼容

2026-10-26真实H阶段的10份首个完整响应均返回“普通说明文字＋唯一python代码块”，没有说明外层花括号。v1解析器将其全部记为格式失败；原响应和失败记录保留。请求参数、提示、H代码本身没有因此重写。

修复仅放宽说明文字包装：允许普通或花括号说明，仍要求非空说明和唯一Python代码块，仍由同一数值AST/签名/输出/期限规则校验。拒绝多代码块、额外尾文和无说明输出。此为准入修订，**不能把v1和v2称为同一执行身份**。

在第一条真实U请求之前请求边界暂停，原campaign为`runs/tsp-pilot-20261026-v1`，消费10逻辑/10尝试、10完整响应、0 U请求。旧H筛选（当时只有人工后备）及所有协议、解析失败和源码快照原样保留，不覆盖。

`runs/tsp-pilot-20261026-v2`是显式执行续接，继承原请求账本的真实路径、原身份、全部旧条目和原截止时间。全程仍只有50逻辑/75尝试、每任务2次；不是第二个预算。H任务读取原账本中的首份响应，用v2解析重新准入并离线评价，不发送第二份H请求。额外的人工/生成H离线评价投入单记。

续接新协议记录request_origin、execution_revision及Inherited_budget.json；每次检查都要求原Protocol/时钟哈希和已继承条目不变。全部U路径均采用同一v2准入，H筛选仍仅train、相同质量排序；后续静态/P0/validation/confirmation/transfer规则不变。不根据性能修改科学机制。

修复通过12项检查。额外用已经完成50任务的Mock账本做全流程重放：必须不增加任何Mock尝试、沿用原响应并保持原时窗。原Mock源快照和两版验收日志保留。

本轮实际续接命令（已有目录不得重新prepare）：

```sh
.venv/bin/python -B experiments/tsp/manage.py prepare --config experiments/tsp/configs/pilot-real.json --directory runs/tsp-pilot-20261026-v2 --continue-from runs/tsp-pilot-20261026-v1
.venv/bin/python -B experiments/tsp/manage.py run --directory runs/tsp-pilot-20261026-v2 --allow-api --env-file '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/.env.leafapi.local' --background
.venv/bin/python -B experiments/tsp/manage.py status --directory runs/tsp-pilot-20261026-v2
.venv/bin/python -B experiments/tsp/manage.py summary --directory runs/tsp-pilot-20261026-v2 --write
```

安全暂停后的resume仍指向v2，不能直接恢复绑定旧源码的v1。`--continue-from`只用于有完整已知账本、无活跃writer的显式工程续接，不能消除未知状态，不能改变provider/预算/数据/原截止。本轮后不得将剩余额度用于追加研究。
