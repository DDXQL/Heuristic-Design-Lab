# R2/R3与B1-V6单脚本交接

日期：2026-10-30。R1三类校准已完成，见R1_COMPLETE.md。已新增真实搜索薄入口，未发送任何模型请求、未创建R3或正式搜索运行。公开价格查询为无凭据GET，不是生成请求。

## 两个入口与范围

| 入口 | N/G | 初始化上限 | 演化计划 | 总尝试上限 | 状态 |
| --- | --- | --- | --- | --- | --- |
| experiments/common/run_r3.py | 2/1 | 4候选、4请求 | 4请求 | 8 | 用户已明确授权，仅此一批，待用户启动 |
| experiments/common/run_b1_v6.py | 5/20 | 20候选、20请求 | 200请求 | 220 | 未授权；R3和存储未通过前拦截 |

两个脚本均在顶部显式设置模型/端点、H/train21、初始化及演化预算、种子、API2/CPU2、T30、W/特征组、输出目录。未知参数/Provider字段直接报错，不默认3个手写H、不导入P0。保留原冻结10H的顺序、源码和原train21。每父代独立CROSS一次、MUTATE一次；仍是分批生成再分批评价，不宣称完整流水线。只复用common engine的prepare/run/export和既有有界传输/并发/恢复，不修改81份原执行源码。

R3与正式训练的目录、种群和预算分开，R3不作为正式P0；不自动扩大初始化、补生成、重试或启动下一批。两批上限合计228请求，但本次只授权8。初始化失败或重复保留并消耗已发生预算；不足N则initialization_incomplete。每逻辑请求只有一次尝试。当前引擎会按原预算计划记录传输失败，不承诺在首个429后自动中止；R3只授权小预算，出现任何传输/模型错误会导致验收不通过，正式搜索被拦截，不能暗中补发。

## 本次明确授权

用户原话：**“授权R3最多8次，由我在终端启动”**。上下文范围：LeafAPI https://leafapi.cc/v1/chat/completions，gpt-6.1-sol，原10H/train21，N2/G1，初始化最多4、演化4、总尝试8，API2/评价2；请求总超时300秒、连接10秒、读取240秒，stream_response=true，输出上限8192 token。每实例两遍求解/完整行接收共享T30，正常退出另2秒。温度和reasoning effort未显式指定，使用提供方默认；不虚构服务端确定性种子。

授权记录在本机preparations/b1-v6-r3-20261030/authorization.json，绑定完整有效配置和原执行源码身份；不含密钥。run_r3.py的real_requests_authorized已按本次授权开启；run_b1_v6.py保持false。

本次授权只绑定一个新运行：首次真正启动前独占写authorization.claim.json。重复普通启动会拒绝并提示原目录，不会再创建一批8请求。配置/模型/预算/源码改变不匹配授权会拒绝。若prepare/启动中断，保留声明和原状态，不自动释放或重置预算；先核查。该声明不替代原协调者账本，恢复仍由原检查点继承原8次上限。

## 用户启动

项目根目录、VS Code终端A。如果当前终端未导出LEAFAPI_API_KEY，先只执行下行，输入本机密钥后回车；隐藏输入，不将值粘贴到聊天/命令字面量：

```sh
read -s 'LEAFAPI_API_KEY?LeafAPI API key: '
```

再执行：

```sh
export LEAFAPI_API_KEY
.venv/bin/python -u -B experiments/common/run_r3.py
```

已正确配置环境变量时，只需要最后一条Python命令。脚本只检查变量存在性，日志/参数只保存变量名；模型传输从环境读取，不写密钥。

自动完成输入/预算/授权/磁盘预检→全新目录prepare→前台真实初始化/一代CROSS+MUTATE及完整train评价→导出→冻结本次训练冠军→打印路径。一般正常链路为2次初始化＋4次演化=6次请求；最多8次，因为初始化有独立替换上限。最多8×21×2=336遍排程，实际无效/重复会减少求解数量。R3是线上接入验收，不是正式N5/G20效果实验。

只检查而不创建/请求/求解：`.venv/bin/python -B experiments/common/run_r3.py --check-only`。它不会消耗批次声明。尚未提供凭据时预检报告credential_present=false，真实启动会在prepare和请求前拒绝。

## 自动证据与验收

原Protocol/checkpoint/Events、逐请求响应、失败/重复、worker收据、全解/复检/轨迹均保留；日志terminal.log；launch保存本次参数、入口源码、R1前提、授权及计划身份。原candidates/generations CSV、lineage/summary继续导出，另外生成：

- requests.csv：阶段/算子、发送确认、HTTP/model、已知token、未知usage、请求任务开始/发送确认/结束时间。
- evaluation_timings.csv：候选任务起止及CPU worker PID/单调时钟区间。
- acceptance.json：同代CROSS/MUTATE的真实客户端在途区间重叠、有效候选worker重叠、固定父代和稳定提交检查。
- per_instance.csv：只流式提取逐实例Cmax/LB/score、首解/复检耗时、观察耗时、峰值内存；跳过大trace、不重评。跳过的重复任务不虚构第二次评价。
- frozen_training_champion.json/.py：只在completed后冻结训练冠军、H顺序、配置/源码/协议身份；选择规则为完整train21 Fitness最高、固定ID平局。验证状态明确not_run。

R3通过要求：完整初始化并完成至少一代、同代CROSS/MUTATE至少一对已发送请求区间重叠、至少一对有效候选CPU worker重叠、固定父代/稳定提交匹配、传输HTTP/model无错误、已发送请求usage已知。候选失败/重复如实报告，不额外补齐；若无法形成所需有效并发，验收不通过。这里证明客户端在途与本机worker重叠，不证明提供方内部同时计算或更高限流能力；未遇429不等于无任何限流。

正式脚本要求指定一个通过上述真实验收且模型/协议/状态/并发/超时/输入/执行源码匹配的R3_RUN_DIR，不能填Mock或R1。即使R3通过，也不自动授权220次或自动启动正式搜索。

## 费用估计依据和限制

2026-10-30公开GET见public-pricing.json、public-status.json。公示gpt-6.1-sol低档计价表达式输入2、输出10（每百万token，USD显示口径）；codex-deafult倍率0.5。缓存计价另有表达式，本估计不预支缓存收益。账户token组、充值换算/优惠和真实扣费未查询或核实。

按每请求输入10000—20000、输出2000—4000 token情景估算：R3最多8次，未乘组倍率约0.32—0.64美元；若确实适用0.5组则0.16—0.32美元。正式220次同情景未折扣约8.8—17.6美元，0.5组约4.4—8.8美元；这里只作后续准备，不等于授权。

实际输出上限8192，可高于估算情景；输入只设字节上限262144，不把旧input_token_reservation当硬token门禁。费用估算不是费用封顶；硬限制是逻辑尝试数和输出参数。超时/usage未知不当免费或零token。R3返回后按实际usage和账单依据更新正式预算，不以预估替代账单。

## 空间与“全流程”的边界

指定R1 common运行的evaluations与worker-receipts各2.2448 GiB，合计4.4896 GiB；当时盘余约13.8 GiB。按平均候选归档量估计，R3上限约2.99 GiB、正式上限约82.31 GiB；真实U可不同，不是容量保证。另按已测最大候选加5 GiB余量动态预检；R3最低10 GiB、正式最低160 GiB。当前R3空间检查通过，正式被拦截。用户已选择先做R3，正式存储以后处理；不删除任何旧证据，不虚构外接盘/服务器路径。

一条脚本可自动完成真实初始化→多代演化→冻结训练冠军→导出训练结果。R0—R7所有科研决策和冻结后验证不混在一次未经审核的调用里：R3小试和正式搜索分开，validation11的同协议固定评价仍需后续编排，当前不会自动访问，更不会据它重选冠军或跨seed挑最好一次。

暂停/恢复使用原common/manage.py status、pause --wait、resume --allow-api、export，读取原run配置，不读取新顶部参数。正常启动不恢复completed；异常/未知在途不删锁重发。脚本前台运行，电脑休眠/断电不保证持续运行。正式当前仍被授权、R3及磁盘三项门禁拦截。

本轮检查仅针对入口/报告/门禁，见checks.log和两份preview.log：没有Mock搜索、正式求解、模型请求或全套工程验收。并发验收单元测试使用明确标记UNIT_TEST_ONLY的虚拟元数据，不当线上证据。真实并发只在用户启动R3后判定。
