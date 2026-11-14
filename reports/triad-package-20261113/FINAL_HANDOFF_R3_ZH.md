# r3最终工程交付

本地CODE_READY=true，六组RUN_READY=false。工程包已生成并解压核验，尚未上传，未在计算节点运行新版真实搜索。

- 源冻结：6effcf95f222e72a06758fc84675e9a5e0022d81；公共code保持923781f。
- ZIP：/Users/DDXQL/Developer/transfer-outbox/triad-six-groups-prepared-20261113-r3.zip
- SHA-256：bbecedc5b53810a1bd28da9455e0a090c71243da2e917e9297cec2bf93974429
- 大小：784564 bytes；314成员。旧r1/r2保留，OBP使用r3。
- 根README、docs/三问题实验运行入门.md、experiments/triad/README_ZH.md、PREPARATION_ZH.md及delivery/证据已入包。

六组配置：experiments/triad/configs/{fjsp-u,fjsp-eoh,tsp-u,tsp-eoh,obp-u,obp-eoh}.json。独立入口entry.py，批次batch.py／mac.sh，单作业slurm.py／cluster.sbatch，上传／准备／查询／取回cluster.py，H／数据／参照assets.py。唯一公共执行器未重写。

集中建议见study-review.draft.json、REVIEW_DRAFT.md、recommended.draft/；所有建议未批准、saved request authorization=false。每种子1000次演化已确定，初始化和H另计。建议R3、501/502/503、U5/EoH10、初始化20、累计1020；真实资源、时间窗口、账户排他安排、TSP LKH、OBP正式数据与H仍待采用／准备。FJSP210成本走兼容导入，不重跑420次。

原Mac501由总规划报告已完成；本轮未读或修改其运行。新入口禁止重开501，只有明确采用后才可只读登记摘要／曲线，不复制checkpoint。

验收：六组有限Mock、OBP合法输入反例／部分状态、参考类型、草案组装、合成501登记及拒绝重开、合成训练pickle导入、输入上传哈希与冲突保留、公共102源码身份、CLI、AST、shell和解压后四项检查通过。证据见package-r3-verification/result.json。所有新API、实际求解和LKH计数均0，不重做614258／614474。

下一条在Mac终端执行（只读建议计划）：

```bash
bash /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/mac.sh plan --campaign /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/campaign.recommended.draft.json
```

上传（不提交作业）为Mac终端的cluster.py stage，正式输入准备和后续提交命令集中见PREPARATION_ZH.md。资源只读检查、上传与无API任务不因其他设备请求模型而被协议性阻止。正式生成仍须全设备同账户仅一个任务；Array及跨设备共享限流未验收。
