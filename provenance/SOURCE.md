# 来源、数据与冻结边界

职责：框架/基线出处、portable映射、数据来源与恢复、许可边界和已知字节差异。范围：原始单规则导出及当前复用的数据/冻结资产；迁移记录不等于当前程序一律未变。当前进度见[README](../README.md)，接口见[契约](../docs/fjsp_tier1_contract.md)，操作见[指南](../experiments/tier2/research_real_v1/README.md)。

## 冻结来源与映射

本项目最初从相邻EoH-S的不可变单规则基线导出，来源：

```text
/Users/DDXQL/Documents/大学/硕士/代码/EoH-S
commit b3b67d6522466e66baba5eb57990d3fb2bfeca23
tag    fjsp-tier1-single-rule-v1
```

导出时以git show读取tag，不复制来源工作区未提交文件。Tier1-Fixed-H-v1的canonical是seed2026092002单条规则，2003/2004是稳定性复核，不能当当前正式集合H。[原清单](original_baseline_manifest.json)保持原字节，SHA-256为 `0869517771bbac44db814655e1f20f55ea7291b9b4c80b5949aff92047cbc3af`。

[file_mapping.json](file_mapping.json)记录原/目标路径、双方哈希、字节一致或portable转换；新脚手架标portable_generated。它只记录迁移时状态。[原入口](original_entrypoints/)与[原配置](original_configs/)保留；工作入口转换项目/配置路径，使用相对data/fjsp，method.__init__仅导入EoH。原始闭包含base、EoH、HTTPS适配/profiler、fjsp_set及单规则运行/规则/记录/测试，不含上游完整EoHS运行器。当前H适配及Tier2是后续实现，不据此宣称全量上游复现。

[基线记录](../baselines/tier1_single_rule_v1/records/)、[稳定性JSON](../baselines/tier1_single_rule_v1/stability_summary.json)、[portable manifest](../baselines/tier1_single_rule_v1/portable_manifest.json)为必要证据。单规则最终种群按11个validation选一条，test未评价；具体结果保留JSON，不复制大表作当前研究结论。

## 数据来源、划分与恢复

本机60个固定split实例及sample.fjsp从以下目录按字节迁移，共61文件：

```text
/Users/DDXQL/Documents/大学/硕士/代码/2.4.4/_pdata/fjsp
```

冻结元数据将其标为Behnke and Geiger (2012)本地重排格式；已有出处核对记录比较过SchedulingLab commit `ac4c3402312bfbeafcf4472d78be567d4e6b46ab`的工序记录，并处理机器编号约定。本次文档整理未重新取得上游数据或做实验。

[fjsp_manifest.json](../data/fjsp_manifest.json)记录train21、validation11、test28的固定顺序、文件名和SHA-256。恢复有权使用的本机副本到data/fjsp/，逐项匹配manifest；不要为适配另一批数据改清单。sample.fjsp为sanity输入，合成tiny fixtures独立于benchmark。

原迁移对全部61文件核对字节哈希，test28只复制/校验、未解析求解；这是迁移当时用途，不是所有后续流程的永久声明。当前研究搜索完整评价train；validation由Search_complete登记的最终种群/H授权，test由Experiment_frozen授权；详见契约和方案。

2026-10-11的[数据使用审计](../runs/conditional-paired-research-20261011-v4/Dataset_usage_audit.json)另确认：相邻EoH-S的[validation_evaluation.json](../../EoH-S/logs/fjsp_tier1_formal/run03/validation_evaluation.json)已实际评价相同11个validation实例，不能用更早run_result里的未评价标记覆盖该证据。新准备只核对60份实例的字节身份、仅解析求解train；现有记录扫描未发现真实test28结果，但不能证明未知外部使用不存在。

数据再分发许可尚未确认，data/fjsp/*.fjsp继续被Git忽略；哈希元数据跟踪，实例不随公共检出分发。文档合并不表示许可确认。目录/哈希恢复不需要API，也不能拿test调试生成程序。

## 冻结核验与当前字节差异

[verify_portable_baseline.py](../verify_portable_baseline.py)校验冻结哈希/七参数，运行微型实例及记录中的train/validation重放、EFT/SPT/MWKR与规则可行性和本地测试；不调用LLM/演化。对test仅检查路径/记录字节大小，不解析求解。它不是纯元数据命令，也不是新H验收入口。

2026-10-09核对canonical规则SHA-256为 `35012b69a4ff6946e93ad51bbf5872e7fae8831735fb260e6071579c8bc0560c`，原单规则选择/冻结记录为 `0991e17f833e7ab773b0ff13ea2396a0cb3ccb9d94715984fb1ef421ea89496a`，参考规则也有差异。因此verified_config及完整portable核验不能宣称通过。旧记录解释为说明翻译，本次未验证AST等价，不绕过门禁或更新冻结清单。

文档快照不是研究冻结资产；已删除的旧Markdown在仓库外按原路径/哈希完整保存，包括未提交内容。原始JSON/runs里的历史文件路径仍原样留存，不能当当前CLI或当前文档导航。

## 第三方材料

迁移时EoH-S README声明MIT但冻结树缺所链接LICENSE，根LICENSE来自相关EoH；LLM4AD声明与旧文件内研究用途声明的关系见[第三方声明](../THIRD_PARTY_NOTICES.md)。该声明、根LICENSE与LICENSES内许可原文保持不动；本次不重新查询或解释上游条款。
