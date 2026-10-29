# T09：独立终端入口验收

日期：2026-10-29；基准f703f7a；分支codex/common-state-routing-v1。
实现提交：983bd0a。文档入口：[终端独立运行实验](../../docs/终端独立运行实验.md)。
本轮实际网络API请求0；未做真实搜索或确认集调试。

## 已实现

- 复用common/manage.py：doctor、preview、prepare、run、status、pause、resume、export。
- status在运行中只读；日志逐批打印阶段、代数、候选数、已评价最优分数、独立初始化/演化预算和在途任务，另写Events.jsonl。
- 配置显式控制数据/H/P0文件、状态版本、种子、N/G、请求/评价并发和预算。路径相对配置文件；prepare验证实例SHA并冻结输入内容、来源及H顺序；以后修改源文件不改变运行快照。
- FJSP支持已有.fjsp文本和原生JSON；TSP支持现有单位正方形坐标JSON；支持显式train或合成开发清单，不接入确认集路径。划分来源仍须人工审核，程序不证明用户声明train就是未暴露数据。
- fixed模式G=0、import P0、真实首解/复检；mock生成和人工评价分别标注；real模式复用已有有界网络传输。
- real要求配置授权、CLI --allow-api、环境凭据与固定总尝试上限；请求前统一预留，每逻辑任务仅一次尝试，不自动重试。初始化和演化分别计数，总预算跨暂停恢复继承。未知在途保留锁，不自动重发。
- 用户可在VS Code终端独立执行；文档提供nohup、caffeinate与tail用法，无Codex/Notion运行依赖，不承诺合盖/断电后继续。

## 实际演示

运行根：`runs/t09-terminal-demo-final-20261029/`。
复现命令（须更换为新目录）：

```sh
.venv/bin/python -B tools/demo_terminal_operations.py --run-root runs/t09-terminal-demo-final-20261029 --report reports/t09-terminal-20261029/final-demo
```

脚本通过同一CLI子进程执行，记录24个命令的参数、stdout、stderr、退出码。Mock启动进程日志另存mock-start.log。

| 阶段 | 实际结果 |
| --- | --- |
| doctor、preview、prepare | 成功；未请求API；独立运行目录创建 |
| 前台启动、运行中status | phase=running；7候选完成；初始化5请求、演化预留4请求；看到在途任务和writer lock |
| pause --wait | 安全排空到9候选；phase=paused；在途为空、锁释放；演化预算仍4 |
| resume、status | 3代完成；35候选（初始化5＋演化30），预算未重置 |
| export | 输出候选/代际CSV、谱系和summary JSON，不重新生成或求解 |
| FJSP固定候选 | 5个手写U真实求解/复检并导出；生成请求0 |
| TSP固定候选 | 5个手写U真实求解/复检并导出；生成请求0 |
| 真实入口默认拦截 | run与run --allow-api均退出2；配置未授权，checkpoint仍prepared、评价0 |

详细记录：`final-demo/demo.json`、逐命令日志和三个exports目录；最终四份协议/源码/检查点身份核验通过。
首次同样24步演示保留于demo目录，final-demo对应983bd0a源码；没有覆盖历史T00—T08证据。

## 检查

```sh
PYTHONPATH=code:.:tests .venv/bin/python -B -m unittest test_terminal_operations test_common_state_v1 test_common_routing_v1 test_coverage_evolution_v1 test_common_execution_v1 test_state_contracts test_generic_search test_tsp_adapter test_tsp_integration test_fjsp_usage_v2 test_fjsp_usage test_problem_layout
```

73项测试通过，18.778秒，见tests.log。新增检查覆盖两个问题的train输入快照、源文件修改不改变已冻结评价、只读status、运行中预留展示、双授权/环境凭据拦截及接入真实调度路径的传输替身测试。
替身测试模拟4次发送回调，只验证控制链与预算；没有发出网络请求，不能当线上API验收。变更后旧协议的源码绑定按设计阻止直接恢复；status可读取旧运行快照，不升级其checkpoint。

## 模式、预算与尚未验证事项

1. `terminal-demo.mock.json`仅工程演示；两个fixed-development配置仅合成真实求解。正式训练评价由用户提供train清单/H/P0；格式和路径说明在中文手册中。
2. 两份real.template配置的真实授权默认false，endpoint/model为占位值，正式train清单尚待指定。接入代码已经存在，用户填写及冻结输入后仍须显式授权启动。本轮未选择真实模型、预算或上线运行。
3. 线上提供方协议/模型兼容性、实际费用、正式10H与较大train集完整评价、长时并发稳定性均未验收；先做另行授权的小预算线上检查。
4. API并发和CPU并发独立；并发不减少计划生成数或总API费用。M1 Air 8GB日常CPU建议2，4仅为固定工作量已测档位，长时验证未做。本轮复用已有1/2/4测速方法，没有因T09文档修改重复测速；合成秒数不外推train21。
5. 当前超时仍T30完整首解/复检接收＋2秒退出宽限，不是每次T15。H和U必须通过原有封闭语言校验；任意TSPLIB矩阵和旧MIX/旧U不会自动转换。
6. CSV派生报告转为LF，原运行exports保留原样；manifest记录归一化前SHA。状态日志是快照，不等于硬崩溃恢复认证；未知在途需核验，不能删锁重跑。
