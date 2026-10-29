# R1：顶部参数＋一次运行的薄入口

日期：2026-10-29。新入口：`experiments/common/run_r1.py`；薄串联：`experiments/common/_single_run.py`。只交付R1，R3和B1搜索入口后续单独交付。

打开run_r1.py，顶部集中修改PARAMETERS、EXPECTED_H_COUNT、EXPECTED_TRAIN_COUNT及运行目录命名参数。路径统一相对项目根目录，实际配置由这些参数生成，不读取另一份JSON覆盖它们。N必须等于P0条数；默认12条为恒选H0—H9和进度0.5时H0→H1、H1→H0。H封印、编号、原训练顺序、21实例源SHA、U key/来源/去重均在启动前检查，数量或参数错误直接退出。

项目根目录下的一条启动命令：

```sh
.venv/bin/python -u -B experiments/common/run_r1.py
```

脚本自动调用现有输入检查→evolution_v1.prepare→evolution_v1.run→evolution_export.export；API、候选并发、排程、检查点、暂停恢复及选择逻辑不重写。默认新目录为`runs/b1-v6-r1-train21-时间戳-随机后缀/`，打印准确路径。手填RUN_NAME已有目录则拒绝，普通启动从不resume、覆盖或删除锁。

fixed/import/solve、G=0、生成预算0、API尝试上限0、真实请求授权false均被强制校验，run显式allow_api=False；不能通过改R1参数改成真实搜索。模型、端点和密钥不适用于R1，不设置无效的模型参数、不读取凭据。候选CPU并发默认2，实例串行；API并发2只登记，fixed模式无请求。默认252条程序—实例评价、最多504遍首解/复检；T30完整行接收与候选worker最终退出另2秒的规则沿用。

每个新目录保留原Protocol/checkpoint/worker-receipts/evaluations；terminal.log实时保存协调者输出和运行错误；launch/保存入口与公共薄串联源码副本、解析后的parameters.json、包含Git/入口SHA/协议身份的receipt.json；exports/由原导出器写入。启动后修改顶部参数不会影响该运行；恢复必须使用下方现有CLI，读取原Protocol，不用新顶部参数。入口的源码副本是来源证据，不是另一份待编辑入口。

安全暂停后会导出当前证据并返回2；它不表示完整校准通过，不自动resume。completed但候选不全有效也返回2。异常保留日志、锁和原目录，先核查，不重试或清锁。

辅助操作仍使用原CLI（将RUN_DIR替换为脚本打印的准确目录）：

```sh
.venv/bin/python -B experiments/common/manage.py --problem fjsp status --run-dir RUN_DIR
.venv/bin/python -B experiments/common/manage.py --problem fjsp pause --run-dir RUN_DIR --wait
.venv/bin/python -u -B experiments/common/manage.py --problem fjsp resume --run-dir RUN_DIR
.venv/bin/python -B experiments/common/manage.py --problem fjsp export --run-dir RUN_DIR
```

resume仅限安全paused；completed不恢复。手动resume之后导出仍使用原export命令。新普通启动会重新评价，和恢复旧运行分开。

只读检查入口（不创建目录、不求解、不请求API）：

```sh
.venv/bin/python -B experiments/common/run_r1.py --check-only
```

本轮实际检查：6项入口专项检查通过，见checks.log，包含在禁止网络且禁止prepare/run的条件下核查真实10H/train21输入、非法API开关/未知参数、顶部参数贯通与P0数量不符、已完成目录拒绝覆盖、串联顺序和日志导出、异常保留锁与不重试。串联测试用函数替身，不生成或评价候选，不能作为真实实验结果。实际check-only确认12候选/21实例/252主评价/最多504遍/API0，见preflight.json.log。

原冻结81份执行源码与d58ede8的CODE_FREEZE.json逐项一致；没有重跑整套工程验收、Mock搜索或正式求解。新入口自身SHA在每次真正prepare后另行保存，不改变既有运行身份。

现场发现原`runs/b1-v6-r1-train21-20261029-01`已经completed，12任务、无记录失败、无写锁，但未导出。本轮只读检查，没有导出、修改或重复运行它；新普通启动会另建目录重新评价。本批入口只覆盖common的12条固定候选，旧入口H0及H0/H1等权仍使用已准备的兼容配置；EoH冻结规则仍待接入统一认证评价，不把它们写成完成。
