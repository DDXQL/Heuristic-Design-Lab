# Tier 2 Baseline-A 数据集

55项固定策略全部结算：10单H有效，45对等权WS中39有效、6超时。最佳有效单H为H0（−2.111804960626），最佳有效等权对为H0/H1（−1.983144294915）；6个null成员对无完整质量排名。

- [完整中文报告及10H/45对排序](REPORT_ZH.md)
- [科研决策、成本、缓存边界与后续建议](DECISION_ZH.md)
- [单H排序](Single_ranking.csv) / [45对排序](Pair_ranking_45.csv) / [对称Fitness矩阵](Fitness_matrix.csv)
- [全部1155行实例结果](All_instances_1155.csv) / [逐实例对照胜负平](Comparisons.csv)
- [Oracle及全部10H逐实例Cmax](Oracle_instances.csv) / [Oracle复核](Oracle.json)
- [逐对互补性](Pair_complementarity.csv) / [逐实例认证调用成本](Certified_instance_call_costs.csv)
- [源清单](Source_manifest.json) / [原始缓存审计](Cache_audit.json) / [补充语义别名审阅](Additional_cache_review.json)
- [便携数据清单](Dataset_manifest.json) / [55项结果目录](certified_results/) / [只读加载器](load_dataset.py)
- [进程证据](process_evidence/) / [最终独立审计](Final_audit.json) / [协议](Protocol.json) / [复现命令](Commands.md)

旧缓存按原生两遍证据认证，不追溯伪造现代进程终态。新评价保持15秒实例结果等待、正常exit0要求及普通超时分类；无真实LLM请求、演化或holdout访问。本数据集支持已评价完整有效策略的比较，不能证明全45对或整个U空间质量最优。
