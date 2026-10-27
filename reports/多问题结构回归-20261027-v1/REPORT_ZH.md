# 多问题结构整理与回归验收

## 结果

FJSP旧入口保留，新problem入口委托同一实现；问题命名空间仅导出既有状态/候选/融合/求解/评价。TSP选择性复用Developer的独立工作树HEAD7056f18及本地修订，不移动、不合并、不修改来源树。共享core仅增加已有TSP可选journal与候选kind接入；FJSP默认路径不变。新真实TSP配置默认未授权。

## 实测

- FJSP：固定H0及等权U × toy/已认证Behnke1，4组，分别两次完整轨迹（8遍）和T30首解/复检（8遍）。全部状态、动作集合与评分、所选动作、解、Fitness、物理排程/复检/提交指纹与旧generic-extraction的after.json相同。Behnke1仍为106/100，toy均7。不是新的正式搜索或完整训练评价。
- TSP：四个手写坐标、两固定U各两遍，迁入前后状态、动作、打分、完整闭合游程和长度精确相同；迁入前捕获4遍，迁入后4遍，无正式数据。
- TSP离线12项、FJSP操作11项、共享选择2项、路径兼容2项通过。覆盖Mock、预览禁网/禁求解、预算、暂停/恢复、未知请求及身份保护；详细范围以各日志测试名为准。
- 7条CLI/help/doctor/plan通过。真实API=0，正式搜索=0，无留出集评价。新的run证据打包在本目录工程回归原始认证.tar.gz，见SHA回执。

## 发现并处理的问题

初次FJSP操作11项有1项错误：旧封存worker的绝对路径在Developer根下不能relative_to。live工具只增加封存Protocol.source_snapshot→新副本相对路径映射，仍核对原worker身份、原回执SHA、快照SHA；不读旧iCloud源，不改任何历史回执。修后11项通过。该改动属于父代资产定位，不改变调度内核；完整轨迹回归在此路径修复之前完成，后续没有再改任何求解/评分代码。

新增路径测试初次因macOS /var→/private/var的规范化路径断言失败，修正测试expected.resolve后2项通过；保留失败日志，不归因于科学实现。

## 保存与限制

历史标签已远端核验；本阶段开发分支只本地提交。源码变更会让旧campaign身份不匹配，不能直接resume工程回归或历史搜索；报告读取已有结果不等于恢复执行。

目录调整和toy一致性不能证明跨问题算法质量，更未实现新通用特征替换。TSP指标用NN参照，不是FJSP LB。Documents原目录及其工作树关联未改；Developer才是继续开发位置。部分历史云端资产仍缺，详见迁移清单。

复核命令（只运行离线测试）：

```sh
PYTHONPATH=code:. .venv/bin/python -B -m unittest discover -s tests -p 'test_tsp_adapter.py' -v
PYTHONPATH=code:. .venv/bin/python -B -m unittest discover -s tests -p 'test_experiment_ops.py' -v
PYTHONPATH=code:. .venv/bin/python -B -m unittest discover -s tests -p 'test_generic_search.py' -v
PYTHONPATH=code:. .venv/bin/python -B -m unittest discover -s tests -p 'test_problem_layout.py' -v
```

完整构造回归命令：`.venv/bin/python -B tools/verify_multi_problem_layout.py --report-dir reports/多问题结构回归-20261027-v1`。已运行、目标和run目录已存在，会拒绝覆盖/重跑；不是建议再次执行。输入和逐步轨迹见fjsp.config.json、fjsp.semantic.json及tsp.semantic.json。
