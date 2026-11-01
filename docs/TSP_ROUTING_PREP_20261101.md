# TSP新版接入精简方案

## 现有链路与真实缺口

|环节|核查结果|本轮处理|
|---|---|---|
|共同状态|`tsp/common_state.py`已提取13项数值及历史/可用性；D=n-1，B=n·Dmax，C=n-1；回起点边不观察、不调用U|保留定义，验证第一步、单动作、终点和窗口边界|
|纯路由|`tsp/routing.py`已有`use_heuristics(state) -> int`；只调用选中H，最大raw score，城市编号破同分|保留构造与评分，旧SELECT/MIX结果不作新版质量结论|
|H来源|通用fixture是3个人工示例，不是旧实验5H；历史`reports/tsp-pilot-20261028-complete/H_frozen.json`的入选5H全为人工，10个LLM候选无一入选|使用历史5H原顺序、原key，记录来源；不是重新做EoH-S，也不把H0解释为NN（NN为H1）|
|数据|real模板指向不存在的`data/common/tsp-train-manifest.json`；旧数据由PCG64生成，train20×50城，其他集合有历史使用|准备只含旧train20的独立输入快照，按归档SHA逐文件核验；小试只用train前2例。不给旧validation/confirmation/transfer贴“未见测试集”标签|
|Prompt|通用build_prompt仅FJSP有任务定义；TSP只有Problem标签|补TSP目标、闭合边、五个H输入的sqrt(2)归一化、NN分母、状态尺度、同分及纯路由约束|
|精简记录|config禁止TSP compact；TSP结果无member_sequence；fixtures只为FJSP输出该字段|补TSP序列，支持compact；验证full/compact游程、分数、H调用数、行为序列一致|
|复检与导出|通用worker已做两遍、哈希和T30生命周期认证；export只有候选/代际/血缘摘要，缺逐实例可读游程和冠军源码|沿用认证/恢复，补统一逐实例CSV和冠军代码，保留原恢复文件|
|终端操作|已有manage的doctor/prepare/run/status/pause/resume/export|提供薄入口及check-only，复用执行器；默认离线固定评价，Mock搜索与真实生成明确区分|

## 执行范围

只在独立worktree开发，不修改B及主项目现有文件。本轮验证使用小型合成实例和train前2例的离线固定候选求解；不跑train20正式搜索，不请求API。交付fixed小试、Mock生成+真实求解的小规模配置，以及默认未授权的real模板。正式协议仍需决定H是否重新生成、种群/代数/重复次数与预算、训练外数据和选优；不能只改problem启动B入口。

历史5H可用于“给定H”的新版路由试验；不能据此宣称LLM生成集合有效。新版路由每次只选择一个H，旧静态等权不再是其最贴近的结构消融。测试重点是接口与记录正确性，离线通过不代表质量改善。

参数、命令、工作量与实际验收结果在`reports/eoh-tsp-prep-20261101/REPORT_ZH.md`更新。未到归档清理阶段，不打包全历史、不删除输入；未来ZIP仅放Developer/transfer-outbox，传输和Windows核验尚未发生。
