# R1最后一项准备：既有冻结EoH原生规则

日期：2026-10-30。状态：入口和针对性检查完成；正式train21 EoH评价未启动，由用户在VS Code手动运行。

## 谁做什么

助手负责来源核查、薄适配、相关小型单元验证和结果分析；不代跑正式train21、不请求API。用户负责运行下方一条命令，并返回运行目录和最后摘要。助手随后逐实例比较既有H0/静态等权/两条手写路由与EoH，保留全部退化和失败，再决定R1是否完成。R2/R3尚未因此获准付费。

```sh
.venv/bin/python -u -B experiments/common/run_r1_eoh.py
```

工作目录：`/Users/DDXQL/Developer/Heuristic-Design-Lab`，VS Code终端A。顶部参数在该脚本中；普通启动全新目录`runs/b1-v6-r1-eoh-train21-时间戳-随机后缀/`，不恢复或覆盖旧运行。自动预检、冻结输入/原始规则/预算、前台运行、保存日志/检查点、导出`results/Summary.json`和`Per_instance.csv`并打印路径。

本次仅一条已有固定规则，21条主评价、最多42遍首解/复检，API请求/token/费用0；不重新训练Tier1、不重新选择seed、不重跑已完成common或静态基线。每实例首解＋复检＋完整行接收共享T30，候选worker最后正常退出另2秒；12小时为总时窗，不是预计耗时。成功标准：phase=completed、valid=true、complete_instances=21、API_requests=0；完整Fitness要求全部21例有效，任一失败为空，不取前缀均值。

## 来源核对与必要适配

canonical规则在此前三个稳定性seed比较前已选定为seed2026092002。原始SHA为`0991e17f833e7ab773b0ff13ea2396a0cb3ccb9d94715984fb1ef421ea89496a`。当前可读文件的SHA为`35012b69a4ff6946e93ad51bbf5872e7fae8831735fb260e6071579c8bc0560c`，原因是历史提交7822eef翻译了文档字符串和注释；便携清单保持原SHA。

本轮初次严格检查因此拒绝，没有放宽SHA门禁。只读提取原始导入提交92db84f中的该文件，逐字节SHA与清单一致；当前翻译版与原版去除文档字符串后的AST完全相同。原始副本与来源回执位于`preparations/b1-v6-20261029/eoh-canonical-source/`（Git忽略、本机资产）；当前规则、清单、历史协议均未改写。报告目录provenance.json保留该核查事实。

原规则含小数幂`**0.5`，现封闭H语言会拒绝；不通过改公式、伪造封闭H或重新训练来绕过。新增`tools/r1_eoh_baseline.py`只作固定原生规则适配，复用原native construct_schedule、已有generic execution任务控制器、T30 collector和modern结果校验。执行原始源码，原函数/公式/参数不改；仅统一使用现有未取整lower_bound_v5计算本次完整mean(-Cmax/LB)，不使用历史ceil-LB Fitness。它是独立单规则基线，不替换历史10H或导入为B1路由U。

原规则历史模型deepseek-flash，pop_size=5、max_sample_nums=40、max_generations=10；原最终种群中按validation11选择规则，canonical seed预先固定。后续B1-V6拟用LeafAPI gpt-6.1-sol、N5/G20及独立初始化预算。因此这里只能统一比较固定程序质量，不能声称模型/搜索预算公平，也不能把已暴露validation11当独立新测试。不访问validation/test数据。

## 原有运行控制的复用

状态/暂停/恢复仍由共享execution.start/stop/work/ledger管理，本适配不实现新的恢复机制。由于这是原生H基线协议，使用同一脚本的薄命令分发：

```sh
.venv/bin/python -B experiments/common/run_r1_eoh.py --status RUN_DIR
.venv/bin/python -B experiments/common/run_r1_eoh.py --pause RUN_DIR
.venv/bin/python -u -B experiments/common/run_r1_eoh.py --resume RUN_DIR
.venv/bin/python -B experiments/common/run_r1_eoh.py --export RUN_DIR
```

恢复分支只读取原运行协议，不读取修改后的顶部PARAMETERS；仅安全paused可恢复，completed不恢复，锁/Stop/未知预留不清除或重发。任务边界为整个固定程序的21例批次，暂停请求须等待该有界任务完成；本次只有一个固定任务，很可能先正常completed，不要为练暂停而重跑。原common/manage不能把该native协议当纯路由协议解释。

## 本轮实际验证

5项针对性检查通过：正式输入及原始来源SHA（不求解）；非法API/未知字段/换seed/改T30拒绝；小型实例native与common恒选冻结H0的完整排程一致；同一原始EoH在小型实例经过既有T30首解/复检和modern认证；恢复忽略修改后的顶部参数且API仍false。只进行相关小型单元求解，不是正式train21结果，未重跑整套验收。日志checks.log；真实输入check-only见preflight.log。

原d58ede8冻结的81份执行源码未改；新增适配及入口在新运行单独绑定/存档。执行器的预算、API、并发、演化和恢复核心没有重写。正式评价完成前，不将本轮准备记为完整R1通过。
