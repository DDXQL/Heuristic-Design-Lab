# R13安全交接卡

本轮仅实施已采用TSP参数与指定第三方候选源码的离线接入。总控指定的TSP接手页ID为`01a1e901-74a8-72b0-971e-43301f833a6a`；本页提交交接回执后停止在此树写入，不在同一树安排另一写入者并行修改。

## 身份

- 唯一交接工作树：`/Users/DDXQL/Developer/Heuristic-Design-Lab-tsp-lkh-candidate-20261117`。
- 分支：`codex/tsp-lkh-candidate-20261117`。
- 父源码冻结：`e17fef9d444d540b9fec875a260fa4ac1c104a32`（R12p2）。
- 本轮源码冻结：`c6b7958ad23b17e719b6b8d21ab20f05daedce4f`。后续仅提交PACKAGE及本交接回执，不改变包内源码；最终HEAD以交接消息和`git rev-parse HEAD`为准。
- 旧R12树的dirty文档、旧包及R11未修改；公共`code/`及`experiments/common/run_frozen.py`仍为923781f原字节。

## 实际完成

复用`six_ops.adopt_tsp`的政策3，生成TSP U5/init20/policy1与EoH10/init20/policy3，两者evo1000/cap1020、独立种子501/502/503，执行授权仍关闭。旧模板pending身份保留，新入口读取实际绑定配置。未用初始化不转演化，OBP严格有限门槛未改。

候选从`/Users/DDXQL/Downloads/LKH-official/LKH-3.0.13-github-alt.tgz`导入新`preparations/operations/lkh-candidate-3.0.13`；固定SHA与声明提交见`configurations/tsp-lkh-candidate-20261117/LKH-source.json`。完整gzip、201条目、安全路径、版本与research-use版权声明通过。未取得官方包；仓库URL未提供，Git提交同一性及官方同一性均未独立验证，回执明确保留这些限制。

新增`lkh_sources.py`负责有界源码校验、候选导入以及编译/绑定回执；`assets.py`新增候选导入分发并继续调用既有资产执行入口。编译尚未实际运行，禁止未编译绑定；未来实际构建将保留日志与二进制SHA，不自动重试。参照导入补全实例身份和完整节点覆盖检查，防止子集巡回被当作合法参照，并保留第三方来源链。D06数值和搜索机制未改。

## 离线证据

- `OFFLINE.json`：本轮定向检查通过，包括错误SHA、损坏gzip、不安全/重复路径、链接、版本、展开限额、保留旧download_reserved、构建与绑定的合成回执、构建日志篡改、不完整巡回拒绝、TSP三种子独立初始化、原生/严格门槛区分和未用初始化不转演化。
- `STATIC.json`：7个Python入口AST检查、10段手动命令语法检查、任意当前目录check-only、OBP模板与公共冻结代码不变。
- `check-only.json`：18份配置清单；TSP只剩`reference_file`和`asset:D06_LKH_reference`。其中R11身份行是历史导航，不是实时状态。
- `local-import.json`：实际本地候选导入回执。
- `PACKAGE.json`：实际ZIP逐文件哈希和解压check-only通过。

所有检查API0、真实求解0、make0、LKH0、Slurm0，无账户/STOP/锁/账本操作。编译分支仅用临时目录中的惰性合成文件验证，未执行任何二进制；这些测试文件未进入部署包。旧六组Mock和614258/614474证据复用，未重复真实验收。

## 已生成的包与状态

`/Users/DDXQL/Developer/transfer-outbox/triad-tsp-lkh-candidate-20261117-r13.zip`，6,004,858字节，691个清单文件，SHA-256：

```text
a70649d666d04c554e105f10f440191def39acb952b87dfc3eafece96b8e695a
```

同目录`.zip.sha256`和`.zip.audit.json`已生成。包内有候选源码、来源回执、已采用配置和手动指南，没有凭据、运行结果、检查点、锁或编译二进制。已准备及本地核验；未上传、未做计算节点验收、未完成参照或搜索。包内源码提交为c6b7958，证据提交不重打旧包。

## 交接归属与剩余动作

TSP接手页负责专用`lkh_sources.py`、`lkh_candidate_tests.py`、`configurations/tsp-lkh-candidate-20261117/`、本轮TSP绑定配置、TSP专用文档与回执。公共`assets.py`分发、`six_ops.py`、`six_mac.py`、`six_build.py`、`runtime.py`和`parallel.py`仍由原公共工程负责人单点集成；需要改动时先交接，不同时编辑。接手页应在总控确认本页停止写入后再开始修改，保留此冻结包与交接证据。

新树只有已采用配置、源码导入资产和离线结果，没有真实计划、租约或运行。接手页先核对HEAD、dirty和本卡，不需要重扫历史实验，也不需要重跑官方下载诊断。未跟踪的准备资产属于本次来源资产，应保留；不要清理ignored目录。

剩余真实前置：用户另外授权部署；目标Linux上实际编译和二进制/日志核验；另外批准20个D06参照进程并核验20份完整合法巡回；导入绑定共同参照；再根据最新账户状态和新排他期限，另获模型/评价/Slurm运行授权。R11故障检查与恢复属于已有API修复页，本页不处理。完整操作及副作用见`docs/TSP候选源码接入-20261117.md`；源包导入和脚本交付不能称为实验完成。
