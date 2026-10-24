# 本轮复核与下一次正式授权

在当前工作树根目录、仓库Python3.12.10环境中，本轮执行：

```bash
.venv/bin/python -B tools/a4_static_audit.py
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/a4_static/run.py synthetic-acceptance
```

第一条只审阅已有21网格／B2／A1–A3，输出新表，不执行H／排程器；守卫禁止任何raw `.fjsp`打开和网络。第二条仅toy空间7、合成结果、内存toy与合成H，包含真实子进程两遍toy排程，但真实train21求解0、正式A4采样0、真实API0。

若最终验收收据已存在，工具拒绝覆盖，以免混淆源码版本。纯复查可运行：

```bash
PYTHONPATH=code:. .venv/bin/python -B -m unittest tests.test_a4_static.A4Tests -v
.venv/bin/python -B reports/a4-evidence-protocol-20261024-v1/verify_preparation.py
```

不要在本轮调用正式prepare/run。下轮需要明确授权：RS主协议版本，5个指定搜索seed、每次60查询、最多300逻辑查询，新增物理上限6300项／12600遍，T30共享结果期限、2秒正常退出grace、6小时启动预算，允许严格认证的历史质量缓存，0 API／演化／留出，遇未知身份／终态／账本停止，已认证普通超时null且不重试。不是申请无限时间或自动扩展权重网格。

得到该明确授权后，另存真实批准文件（本目录模板`approved=false`不能使用；不得把旧批准当A4批准），再运行：

```bash
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/a4_static/run.py prepare --authorization-file /绝对路径/未来真实授权.json
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/a4_static/run.py check
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/a4_static/run.py run
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/a4_static/run.py report
```

prepare才生成并冻结300个正式票号，尚未查询成绩；run才执行查询／缓存／新求解。正式Protocol SHA和Plans SHA在那时生成，本轮没有正式运行协议SHA。当前主协议文档和实现身份另见Design_manifest.json。

中断恢复只用同一run的原计划／账本；已完成条目跳过。未知reservation、孤立证据或Stop不自动清理／重跑。6小时期限持久化并绑定checksum，不因重启重新计时；普通时间预算截断只报告partial，不补抽、不扩重复。

报告和验证需要本机原始历史runs及数据元证据。单独克隆Git若缺原运行资产，不能只凭摘要强行恢复缓存身份。此缺失需隔离／停止相关执行，不能访问留出或重新求解来补当前审计。
