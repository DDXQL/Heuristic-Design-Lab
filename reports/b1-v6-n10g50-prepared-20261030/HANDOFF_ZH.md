# B1-V6正式入口交接（待新预算授权，未启动）

入口：`experiments/common/run_b1_v6.py`。顶部`PARAMETERS`为实际参数，`RUN_ROOT`可指定外置输出目录。正式固定历史10H、完整train21；N10/G50，每代10 CROSS＋10独立MUTATE，初始化最多50、演化1000、总尝试1050，API2/CPU2。初始化失败/重复均占次数；每逻辑请求仅一次尝试，无自动重试或补发。初始化不足10个完整有效且AST不同的U时停止，不暗中扩预算。不同源码可有相同训练行为，不强制行为去重。

模型、纯路由状态、传输及期限沿用已通过R3：LeafAPI/gpt-6.1-sol，流式响应；连接10s/读取240s/总300s，输出8192 token；每实例首解与复检及行接收共享T30，正常退出另2s。代内父代固定，交叉伙伴从其他父代均匀选择，代末父子合并按Fitness降序、固定ID升序选10。仍为分批生成再分批评价，无完整流水线。仅一条独立搜索，不自动启动重复或validation。

## 当前安全预览

在项目根目录的VS Code终端：

```sh
.venv/bin/python -u -B experiments/common/run_b1_v6.py --check-only
```

只读输入/历史结果及配置检查，不创建运行，不求解，不发送API。`preview.log`显示N10/G50、1000+最多50、API2/CPU2、最多44100遍首解/复检。预检时约14.11 GiB可用，低于约定20 GiB，因此退出2；这不是代码失败。磁盘只用保守预留，不再逐文件研究体积，不沿用160 GiB门槛，也不删除历史。可自行清理已确认不需的文件，或将`RUN_ROOT`改成已挂载外置卷中的独立目录。

## 正式启动（目前会被关闭的付费开关/待批准记录拦截）

```sh
.venv/bin/python -u -B experiments/common/run_b1_v6.py
```

需先明确批准本轮1050次新范围，再登记`AUTHORIZATION.pending.json`为approved并启用顶部`real_requests_authorized`；当前两者仍为pending/False。已有R3的8次批准不适用。批准记录绑定有效参数与源码，首次启动独占认领一个运行；重复普通启动拒绝，不扩批、不恢复已完成实验。参数改变必须重新核对登记，不能只改一个值绕过冻结。密钥仅由启动终端的`LEAFAPI_API_KEY`提供，不写脚本/日志。

启动后自动预检→全新目录与参数冻结→真实初始化→50代→导出→冻结训练冠军→复用R1配对比较。没有手工prepare步骤。运行中保持相关源码不变。

## 暂停、恢复、导出

以下将`实际运行目录`替换为本次打印的路径。另开终端请求安全暂停，等当前有界批次排空；不要删除锁或强行重发。

```sh
.venv/bin/python -B experiments/common/manage.py --problem fjsp status --run-dir "实际运行目录"
.venv/bin/python -B experiments/common/manage.py --problem fjsp pause --run-dir "实际运行目录"
.venv/bin/python -u -B experiments/common/run_b1_v6.py --resume "实际运行目录"
```

恢复只接受安全paused，读取原Protocol/累计预算及冻结基线和导出实现，忽略后来编辑的顶部参数；自动完成导出和冠军冻结。completed不应resume；初始化不足、残留锁或未知在途先核查。

```sh
.venv/bin/python -B experiments/common/run_b1_v6.py --export "实际运行目录"
```

导出不请求API、不重求解，可用于已完成运行。

## 结果与检查边界

默认新目录：`runs/b1-v6-b1-时间戳-随机标识/`；`terminal.log`为终端日志，`Protocol.json`/`launch/parameters.json`为冻结参数，`checkpoint.json`为唯一恢复依据，`milestones/G010/G020/G030/G040/G050.json`为结果快照（不是预算回滚点）。

`exports/`内有候选/代际/谱系、请求usage及任务时间、逐实例结果、训练冠军源码与冻结身份，以及`train21_comparison.csv/.json/.md`和`train21_paired_instances.csv`。比较H0、最佳固定H、静态H0/H1等权、冻结EoH；基线身份和完整train21/LB/首解复检先核对，复用R1不追加求解。平均Cmax/LB相对变化为均值之比减1，负值改善；胜负平按同实例Cmax。区分实例可行率与搜索任务有效率。旧B1单列历史参照（七标量、SELECT/MIX、N5/G2、实际29次请求及历史40/60上限、T15和一小时接续窗口），不称仅改变状态的对照。EoH历史训练预算/选择分区也不相同。

精简记录保留全部Prompt/响应/候选/usage、物理排程、H选择序列、两遍一致性哈希、可行性、谱系与耗时；不保存每步全部动作、分数矩阵和状态包。首解/复检比较物理排程、分数、H选择序列和H调用数，求解与评分逻辑不变。支持时两个结果路径用硬链接共享字节，否则保存两份精简文件。冠军完整动作轨迹未自动重跑，可另按冻结程序显式导出并单列求解成本。

本次只做相关离线检查；无R3重跑、无train21重求解、无模型请求、无Notion访问。`checks.log`/`verification.json`及记录兼容收据留证；R3原协议、授权、结果不改。费用和账户倍率未在本次交接重新查询；1050是次数硬上限，不是金额封顶。
