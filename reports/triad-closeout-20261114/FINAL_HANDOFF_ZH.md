# 离线收尾最终交付

r4p1／closeout-v1.1已完成；代码冻结2e93b8767fc51dc77c493dc69ec2799c7a92a275。原r3不变；实际501样例由e926be8生成，其运行版本为19a86bf及102份实际源码哈希。后续严格J门禁补丁不改样例。

入口experiments/triad/closeout.py，支持check-only、build和batch-report。README及docs/实验结束与归档.md包含操作和输出解释。可选绘图依赖独立，不改原portable执行环境。

- 样例精简目录：/Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/results/fjsp-u501-closeout-20261114-v1
- 完整证据：/Users/DDXQL/Developer/transfer-outbox/fjsp-u501-closeout-20261114-v1-full.zip；SHA 2c4fd40cb5669f004d5e2d6608f7223dc3f47ed74e78e202bb05ac1a36f6d9b2；87617447 bytes
- 精简ZIP：/Users/DDXQL/Developer/transfer-outbox/fjsp-u501-closeout-20261114-v1-slim.zip；SHA 4bf5340f022fdaeb74ddd8995b14284a7e99f2504abb6717397d739f27a0d06f；991571 bytes
- 新代码包：/Users/DDXQL/Developer/transfer-outbox/triad-six-groups-prepared-20261114-r4p1.zip；SHA 3a304b44609cddc17d99af2e9064be773a6d7e37f435a5824e5fcf0a5ff17ce4；810827 bytes

已生成7类图的PNG/SVG/PDF、CSV、完整父子关系和局部冠军图、配置/源码/原文件哈希、报告、完整ZIP及待推送清单。1008次尝试全部保留，初始化8、演化1000；H选择按member_sequence计数。完整包5280成员逐一核验，原运行5117文件未改变，运行源码与绑定输入齐全，未发现模式匹配的秘密。图面已人工检查。

本轮没有API、H/U执行、求解、测试集访问或Slurm；未修改Mac原运行、锁或账户门禁。完整/精简ZIP均只在本地，Windows未核验；不删原件。

工具代码已本地提交；精简成果40文件暂未入Git。GITHUB_PUSH_PENDING.json列出目标仓库、分支、代码提交、运行及后处理身份、逐文件SHA、排除项和待审阅命令。没有push、Release上传、标签创建或强推；远端差异未查询，推送前必须审阅全部将出站的提交。

缺口：真实多种子及其他问题的实际成果尚不存在；批次展示已用合成汇总验收。单次样例只有train21，不含测试或未经兼容复核的固定H叠加。费用、真实求解总数和归一化运行/暂停/排队耗时不凭候选数推算，原回执已留存，未知继续未知。缺少记录不重跑补图。秘密扫描有模式边界，公开发布前仍需隐私与数据许可审阅；依赖锁未由后处理猜造。

下一条在Mac终端执行（纯只读）：

```bash
/opt/homebrew/opt/python@3.13/bin/python3.13 -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/closeout.py check-only --run-dir /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-mac-20261112/runs/fjsp-u1000-20261112-mac-seed-501
```

直接阅读成果可打开精简目录REPORT_ZH.md。再次build必须选新输出和ZIP名，不覆盖v1。
