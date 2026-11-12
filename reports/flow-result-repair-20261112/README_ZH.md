# 2026-11-12完整流程失败复核与修复接续

核查时间：2026-11-12 15:21，UTC+8。用户这次确实启动了入口，但**完整流程没有通过**：第二次启动在Mac固定H0基线返回结果时停止，尚未请求模型，也未提交集群作业。第一次启动停在SSH认证；第二次的远端包核验和check-only已通过。认证问题与本地结果封装错误分开记录。

## 实际证据与分母

原工作树 `/Users/DDXQL/Developer/Heuristic-Design-Lab-flow-check-20261112`，原源码 `d160411c72eb8f5a96824be4eebb1ac94ca5e8f8`，原计划SHA `b21f60346dcbe2e7b2d134a9e2d52fb4565ede3af1be6f70ae8d91595d4c47bd`。原运行根 `/Users/DDXQL/hdl-flow-validation/fjsp-state-a-flow-20261112/mac`。

|批次/环节|授权上限|实际预留/发送|通过/失败/未知|
|---|---|---|---|
|本轮原Mac模型请求|2次|预留0，确认发送0，未知发送0|响应通过0、失败0；usage未知0。分母为0，不能解释为API已通过|
|本轮原Mac评价|Mac最多6次求解；两端累计12次|1条评价预留，最多覆盖2次求解|完整有效0/1；本地结果封装失败1/1；1条求解用量未获完整结果确认，最多2次额度继续占用|
|本轮原集群评价|原计划6次|未提交作业，无集群评价预留记录|尚未执行，不能列入通过分母|
|修复接续阶段|仍在原累计API2、求解12内|本页实际预留0、请求0、求解0、提交0|已准备，未运行|

本轮已知模型token为0；没有请求记录，所以不是“已发送但usage缺失”。本地失败前已进入构造函数，不能把没有完整结果误写成实际求解0。保留原始未知用量，以最大2次预留计账，不退款、不伪造有效结果。前轮V5的Mac2+集群2短诊断保留其原分母4及关闭状态，不混入本轮计数。

原始证据：原工作树 `reports/flow-check-20261112/launch-20261112-123429-21478/user-launch.log`、`launch-20261112-123650-22036/user-launch.log` 和 `remote-before.log`；原运行的 `Protocol.json`、`checkpoint.json`、`Known_failure.json`、`Summary.json`、`evaluations/*/result.json`、`lifecycle.json`、`End_summary.json`、`Run_clock.json`。本目录 `AUDIT.json` 记录路径、SHA、时间、纠正后的分类及预算；原件逐字节核验未变。

## 已证原因和修复

错误原文是 `StateAResult.__init__() got multiple values for argument 'member_sequence'`。上轮接入已把H选择序列作为第六个位置参数传入，又以同名关键字传了一次；这是本页上轮引入的本地缺陷。构造过程结束后，Python在封装结果时拒绝重复参数。删去重复关键字，保留实际选择序列、可行性校验、完整结果、首解/复检及严格API验收。

原摘要把它列为 `candidate_runtime`，本轮依据实际错误和调用源码改判 `local_result_contract`。修复版增加精确分类；其它候选错误和T30超时保持各自分类。原 `Summary.json`、失败回执和停止状态不改写。

新检查直接从真实调用位置读取AST，再与数据类实际签名绑定；不运行构造器、H、求解或模型。修复前能复现同一TypeError，修复后通过。原49项离线检查没有覆盖真实结果调用位置，不能沿用其通过结论宣称实际流程已通。

没有这轮DNS/TCP/TLS、HTTP拒绝、429/5xx/524、响应读取、模型身份、usage或候选提取的失败证据，因为请求阶段根本未进入。当前本地错误有直接证据，不归因于供应商或合盖。本轮不继续诊断电源原因。之前短API检查通过、平台正在修复等信息均不证明长实验稳定。

## 接续范围和累计限额

修复放在独立工作树 `/Users/DDXQL/Developer/Heuristic-Design-Lab-flow-result-repair-20261112`，分支 `codex/flow-result-repair-20261112`。原工作树、原始失败、锁、检查点、时钟、账本和原ZIP均保留。共同V5 wire及严格调用方逐字节不变，供应商、模型、非流式配置、Prompt、超时和全部方案A字段均未改变。

原运行是stopped，原一小时窗口也已结束。修复阶段使用显式新源码身份 `fjsp-state-a-flow-20261112-r1` 和新的阶段时钟；**没有重置旧时钟、原累计预算或把旧stopped伪装成paused**。新阶段绑定原失败快照及其SHA；Mac运行前还会只读核对原件。原件变化、出现任何旧API收据或锁被移除，立即拒绝接续。旧失败worker已有退出0及接收线程退出凭证，没有把未知存活进程当作可恢复。

|累计部分|API请求最多|求解预留最多|用途|
|---|---:|---:|---|
|原失败阶段继续计入|0|2|不释放未知用量预留|
|修复阶段Mac|2|6|固定H0、一个真实H样本、一个真实U，各首解和复检|
|修复阶段集群|0|4|仅导入相同H/U，各首解和复检；不重复固定基线|
|整个接续链|**2**|**12**|零自动重试、零补员|

修复阶段最多新增10次求解，不能按新目录获得另一个12次额度。集群两项完成后，原失败2+Mac6+集群4总占用12。跨平台一致性只覆盖 `single_H_sample` 与 `state_A_U` 两项，不宣称固定H0也做了两端比较。API完整响应、静态合法、完整构造和跨平台一致分别验收。

仍是一个9工序合成开发实例和既有手写3H工程集合，不是正式H10、不是真正EoH演化、不访问训练/holdout、不进入正式种群、不新增状态消融。TSP仍缺冻结LKH参照的来源，继续阻止完整TSP验证。

## 已完成的纯离线检查

- 46项控制/脚本/错误回放检查通过，见 `offline-tests.log`。模型、worker和SSH/Slurm均由合成回执或本地替身替代；没有实际求解或提交。覆盖原额度继续占用、原证据变化阻断、新阶段两端串行、集群仅两项、累计12硬上限、失败停止、原期限恢复和取回。
- 11项方案A和真实结果调用签名检查通过，见 `state-a-final.json`。与46项合计57项；不把之前49项重复相加。修复前的失败检查保留在 `before-fix.json/log`，修复后初次检查保留在 `after-fix.json/log`。
- 四份shell/Slurm脚本语法检查通过；部署包文件集合、每个SHA及解压后的隔离check-only通过，见 `isolated-package-check.json`。共同wire和严格调用方SHA与已验收V5一致。
- `replay.json` 只重读封存失败材料，分类为本地结果接口错误，API0、求解0；未重放请求或重新求解。

源码和输入按 `deploy/flow-check/plan.json` 与 `plan.sha256` 冻结。索引见 `FREEZE.json`；离线通过只证明检查覆盖的接口和控制逻辑，不能替代真实求解证据。

## 用户下一次启动

只在下面的修复工作树运行，**不要再执行原工作树的start或resume**。执行明确同意原累计API2/求解12内的上述修复阶段及其新一小时阶段窗口，不是追加额度：

```sh
cd /Users/DDXQL/Developer/Heuristic-Design-Lab-flow-result-repair-20261112
bash deploy/flow-check/start.sh --allow-api --approve-api 2 --allow-evaluation --approve-solves 12
```

它会核验源码包、上传到独立的r1部署根、做远端check-only和队列检查，再启动Mac阶段；Mac通过后提交一个集群回放评价作业。真实请求由用户此终端命令启动；密钥只隐藏输入并传给本次Mac进程，不落盘、不传给SSH或求解worker。未授权开关的默认入口仍是check-only。现有队列不空时先停止，不自动取消、重投或重排。

Mac保持唤醒时，两次模型等待最多10分钟，加三项T30评价和清理约12分钟；集群两项T30评价，作业墙钟上限15分钟。认证、传输、文件系统延迟及排队另计。每端阶段窗口仍为1小时，暂停不延长。首个请求拒绝、完整验收失败、非法候选、评价失败、未知在途或时钟门禁均停止，不补发。

集群作业结束后，在同一修复工作树执行：

```sh
bash deploy/flow-check/fetch.sh
```

取回只读文件和调度状态，请求0、求解0、提交0。之后告诉本页“完成”或错误，本页直接读取修复目录下 `reports/flow-result-repair-20261112/launch-*`、`transfer-*`、`submitted-jobs.txt`、`collected-*/remote.json`，以及 `~/hdl-flow-validation/fjsp-state-a-flow-20261112-r1/mac` 的新账本、worker结果和export；集群根为个人HOME同名路径的 `cluster`。

状态、停止及离线回放命令均不请求模型、不求解、不提交作业：

```sh
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B tools/flow_check.py status --site mac
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B tools/flow_check.py stop --site mac
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B tools/flow_check.py replay-predecessor
```

停止排空当前候选，可能还要等待约300秒请求、30秒评价及清理。只有修复阶段自身安全paused、原窗口有效、前缀已结算且无Stop/残留锁/未知在途时，才用同一start命令在参数前加 `--resume` 接续，不增加额度。若Mac已completed而仅上传/队列检查中断，用 `bash deploy/flow-check/submit_cluster.sh run --allow-evaluation --approve-solves 12`：模型0、不重复Mac评价，可能提交一个集群作业；已有submission claim不重复提交。集群安全paused才可将其中run改为resume，仍由用户手动提交。失败或未知结果不走这些恢复命令，不删锁。

验收成功要求新阶段Mac三项、集群两项均完整有效且首解/复检一致，H/U两项跨平台语义哈希一致，全部预留/发送/usage可核对，累计API≤2、求解预留≤12且无新未知在途。此前那条不完整求解记录仍保留，不能因为新阶段通过就补写为成功。通过后可以继续准备研究协议中的后续验证，仍不构成长实验稳定或方法性能有效的证明。

源码ZIP已打包并本地核验：`/Users/DDXQL/Developer/transfer-outbox/fjsp-state-a-flow-20261112-r1.zip`，440094字节，附SHA文件。尚未上传或备份；原ZIP和全部旧结果保留。Windows可用PowerShell `Get-FileHash` 与旁边SHA文件核对。本包不包含以后生成的新运行结果。
