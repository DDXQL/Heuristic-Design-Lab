# 本轮必要文件与验收

全部为独立新增文件；旧H、U、调度器、报告、协议和账本没有修改。

|文件|必要作用|
|---|---|
|`code/fjsp_usage/a4_static/__init__.py`|固定版本、60×5、搜索seed和硬上限|
|`code/fjsp_usage/a4_static/model.py`|865空间、整数规范声明、端点／重复、固定浮点向量|
|`code/fjsp_usage/a4_static/engine.py`|盲采样、冻结计划、逻辑与物理预留、cache结果来源及checksum、恢复与预算停止|
|`code/fjsp_usage/a4_static/authorization.py`|拒绝当前／历史通用批准，要求未来A4明确范围|
|`tools/a4_static_audit.py`|仅从既有网格／B2／A1–A3原始记录派生证据；禁止raw .fjsp与网络|
|`tools/a4_static_experiment.py`|独立正式入口、固定T30收集器、两遍worker、加载身份及policy留证；当前只运行合成验收|
|`tools/a4_static_report.py`|存档生成查询、逐实例、重复、best-so-far、成本和外部参照表|
|`experiments/tier2/a4_static/run.py`|阶段式CLI入口|
|`tests/test_a4_static.py`|隔离toy空间／合成结果／内存toy排程验收|
|`docs/TIER2_A4_STATIC_SEARCH_PROTOCOL_V1.md`|主协议、预算、停止与分析计划|
|`docs/STATIC_BASELINE_SCOPE_ADDENDUM_V2.md`|新增V2范围说明，保留旧55回放草案原文|
|本报告目录|原始来源索引、21点/逐实例表、A1–A3核验、成本估计、未批准模板、一页说明|

合成验收覆盖10个测试方法：固定空间声明与非法值；浮点方向和近零不裁剪；V1／冻结Fusion toy一致性；仅7索引toy空间盲采样；中断恢复和completed不重评；缓存计账；无效前缀禁止Fitness；未知reservation和checksum停止；墙钟预算不可重置；假授权不能抽正式计划；真实子进程运行合成H／内存toy的两遍一致性与身份。若一项方法包含多个断言，不把断言数量伪称独立实验重复。

验收结果和源码SHA见最终`Synthetic_acceptance.json`。前期验收收据单独保留，后续加固账本／审计后重新验收；未来prepare只认可最终收据与当前逐文件SHA一致。没有创建正式A4 run目录、865空间随机计划、真实H评价或API调用。

尚未通过正式数据验证的部分：完整真实prepare→300查询的端到端运行及其实际耗时。这被本轮授权明确禁止；只完成接口、状态机、toy worker和模板准备，不把它描述为正式A4实验或正式结果。未来运行若触发来源／进程／数据／账本门禁仍须停止。
