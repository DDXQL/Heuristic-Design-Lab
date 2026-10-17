# 本批真实证据索引

最终说明见[训练小试报告](../../H_USAGE_V22_TRAINING_RESULTS.md)。仅seed301、一代、train21；没有新增组合运算、手写种群或holdout评价。

| 文件 | 用途 |
|---|---|
| [Complete_summary.json](Complete_summary.json) | 最终阶段、有效率、种群、计费与局限；优先读取 |
| [Actual_prompts](Actual_prompts/) | 全28次实际发送的完整user提示 |
| [Actual_responses](Actual_responses/) | 24份完整响应；其中1份来自未进入候选解析的原失败槽位 |
| [Actual_prompt_pair_checks.json](Actual_prompt_pair_checks.json) | 10对提示只差模式、父代和算子一致的逐项核对 |
| [All_generated_candidates.json](All_generated_candidates.json) | 23个进入解析的真实候选及原代码文件、行为、有效性 |
| [Compact_attempts.json](Compact_attempts.json) | 全阶段尝试、算子与父代，不省略失败 |
| [All_requests.csv](All_requests.csv) | 请求状态、wire与账单token分列、逐笔认证费用 |
| [All_instance_results.csv](All_instance_results.csv) | 全483行实例数据，包括失败前缀和失败实例空成绩 |
| [Paired_best_train.csv](Paired_best_train.csv) | 完整21实例冠军训练配对，不是独立评估 |
| [Evaluation_costs.csv](Evaluation_costs.csv) | 求解/诊断时间与已认证h调用，未知失败工作单列 |
| [Final_handoff_check.json](Final_handoff_check.json) | 独立财务交接检查摘要 |
| [Final_evidence_manifest.json](Final_evidence_manifest.json) | 原run及归档文件哈希；原wire、恢复快照仍保留在本地run |

`Shared_initial_summary.json`、`A_summary.json`、`B_first_complete_mixture.json`保留各自阶段核对时的状态，不能用其“B未完成”字段覆盖最终结果。原run的原生export保留故障当时的journal费用字段；完整费用以最终逐笔认证表为准。未知wire token不会用账单token补写。所有`.py`候选均来自本批实际响应；未将失败响应恢复成子代。
