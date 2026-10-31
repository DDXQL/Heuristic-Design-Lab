# B1-V6 R1：正式train21固定策略评价交接

日期：2026-10-29，Asia/Manila。状态：输入核查和必要修补完成；正式评价尚未启动。由用户在VS Code终端执行。当前报告不包含新科研效果。

## 本轮定义和固定输入

- B1-V6复用历史冻结10H，只评价/搜索共同状态纯路由U；不重新训练Tier1，不使用旧版允许MIX的B1搜索。
- H文件：`preparations/b1-v6-20261029/H_frozen.json`，来自`docs/usage-space/v1-0-prepared-20261021/sources/H_frozen.json`的逐字节副本，SHA256为`042157b541aa6fda4dc69082a075a08ade814d3c3cc273e6c0327b6fdd189dc2`。冻结封印、10个候选key及与历史原始H候选内容一致性已核对；编号0—9不重排，不沿用旧Fitness。
- train21清单：`preparations/b1-v6-20261029/train21.manifest.json`。21份输入来自相邻Developer工作树既有`baseline-a-supplemental-T30-seed501-20261024-v1/inputs/train/`；顺序、逐文件SHA、H绑定及当前原始数据manifest均一致。仅保存这21份训练输入，没有读取validation/test内容。
- `preparations/`为Git忽略目录；这些输入目前只在本机。来源、SHA与检查证据见`ASSET_RECEIPT.json`、`input-check.json`；不宣称已上传。
- 用户已确定后续搜索按完整train21 Fitness最高选择训练冠军，平局按固定ID；冻结源码、H、配置和选择记录后才评价validation11。该集合已有历史暴露，只作补充评价，不据此重选U、追加搜索或跨种子挑最好一次。本轮R1不访问它。

## 本次common固定评价

配置：`experiments/common/configs/b1-v6-20261029/r1-calibration.fixed.json`。

运行目录：`runs/b1-v6-r1-train21-20261029-01`，须不存在；如果已存在，先核查，不能覆盖或删除。

P0：`preparations/b1-v6-20261029/calibration-p0.json`，12条预先写定的校准U：

1. 第0—9条：恒选H0、H1、……、H9。
2. 第10条：construction_progress < 0.5时选择H0，否则H1。
3. 第11条：construction_progress < 0.5时选择H1，否则H0。

这两条分段规则仅为预登记执行校准，不按训练结果调整阈值，不充当LLM生成成果。固定评价配置中的N=12是本批策略数量，与后续建议搜索N=5分开。G=0、initialization=import、api_mode=fixed、evaluation_mode=solve；不生成候选。

计划：12个完整候选评价×21实例=252条程序—实例主评价；每项首解和确定性复检两遍，最多504遍排程。非法候选/普通超时可能使实际遍数少于上限；保留失败及成功前缀证据，不补算、不计算前缀Fitness。

API并发和候选评价并发均显式登记为2；fixed模式没有生成请求，API并发不会触发发送。候选最多两个并行，单候选内21实例串行。实例层不叠加并发。

每实例完整首解、复检、结果序列化及完整行接收共享T30；第一行期限含worker启动开销。整个候选worker最后正常退出另有2秒宽限，不能用于接受迟到结果。任一主实例失败/超时，完整候选valid=false、fitness=null；基础设施终态不明则停止核查，不能清锁重跑。

Fitness为全部21实例的mean(-Cmax/LB_v5)，越大越好；LB=max(max_j w_j,sum_j w_j/M)，w_j为该作业各工序最短可选加工时间之和，负荷项不取整。与早期Tier1已取整LB历史Fitness不直接比较。

## 用户执行命令

目录：`/Users/DDXQL/Developer/Heuristic-Design-Lab`；VS Code终端A，使用项目`.venv`。依次执行；前一步报错先停止并提供错误，不继续后续步骤。

```sh
.venv/bin/python -B experiments/common/manage.py --problem fjsp preview --config experiments/common/configs/b1-v6-20261029/r1-calibration.fixed.json
.venv/bin/python -B experiments/common/manage.py --problem fjsp prepare --config experiments/common/configs/b1-v6-20261029/r1-calibration.fixed.json --run-dir runs/b1-v6-r1-train21-20261029-01
.venv/bin/python -u -B experiments/common/manage.py --problem fjsp run --run-dir runs/b1-v6-r1-train21-20261029-01
.venv/bin/python -B experiments/common/manage.py --problem fjsp status --run-dir runs/b1-v6-r1-train21-20261029-01
.venv/bin/python -B experiments/common/manage.py --problem fjsp export --run-dir runs/b1-v6-r1-train21-20261029-01
```

preview仅预览，不求解；prepare检查和冻结正式输入并创建文件，不做候选排程；run是前台正式数据固定策略求解，可能耗时；status只读，也可在终端B运行；export只读运行证据并写exports，不重新求解。全部API请求0、token0、API费用0。真实CPU求解耗时待本次实测，不从Mock或合成例外推。

预期正常终态为phase=completed、generation=0、target_generations=0、completed_candidates=12、initialization_requests=0、generation_requests=0、inflight=[]、writer_lock=false；score_is_mock=false、data_split=[train]。这只表示12个固定任务结束；必须另外检查12个候选是否均完整有效，每个有效者是否21/21且captured_solves=2。全部有效时有252条主评价及504遍排程。

导出路径为`runs/b1-v6-r1-train21-20261029-01/exports/`，包含candidates.csv、generations.csv、lineage.json、summary.json；G=0时没有演化曲线，代际CSV/演化谱系可为空。逐实例首解/复检与轨迹保存在evaluations和worker-receipts，不通过导出再求解。

用户返回最终status、export摘要及失败行即可；完整逐实例证据由助手从该运行目录只读分析，不要求反复粘贴完整日志。

## 兼容基线与未完成事项

| 条目 | 当前状态 | 后续要求 |
| --- | --- | --- |
| 最佳固定H | 本批恒选H0—H9将提供统一评价；尚无新成绩 | 仅从全部完整有效单H中按train21 Fitness选出，平局按H编号；不在validation重选 |
| 旧入口恒选H0 | 已准备`r1-legacy-baselines.fixed.json`，未运行 | 与本批恒选H0逐实例核对物理排程、Cmax、LB、Fitness及开销 |
| H0/H1静态等权 | 同一legacy配置已准备，未运行 | 使用原SELECT/MIX兼容评价器的独立动作列min-max及0.5/0.5权重；不转换成纯路由 |
| 既有EoH冻结单规则 | 已找到预先选定seed2026092002及原始便携来源记录；尚未接入本轮统一认证评价 | 复用源码，校准追加排程、同分、LB和T30；历史模型/预算不同，不声称公平搜索成本比较；不默认重训 |
| EoH-S集合用法 | 本轮主方法复用冻结集合，学习可部署路由；单H/等权为明确可执行参照 | 逐实例事后最优H Oracle只作诊断，不当可部署方法或上游EoH-S在线选择器复现 |

legacy两个固定策略的额外计划为2×21=42条主评价、最多84遍排程，API0。common与legacy两批合计14个策略评价、294条主评价、最多588遍排程；不包含尚未接入的EoH。等本批common结果返回后再交付legacy运行命令，不能把这份准备记录写成已完成完整R1。

## 必要代码增量和冻结

- 补齐FJSP Prompt中的目标、合法动作、H参数、状态尺度、LB/Fitness、平局及无注解签名说明；未改变U ABI、状态规范或求解算法。
- 复用原候选任务池，增加每任务开始/结束时间、单调时钟及发送确认回调时间；协调者仍按冻结任务顺序提交，父代计划和代末选择不变。时间证明范围是客户端任务重叠，不等于提供方内部算力同时执行。
- 传输失败保留脱敏HTTP诊断及已知usage；未知usage仍为null，不计成零。每逻辑任务一次尝试，无自动重试。
- 5项聚焦检查通过，见targeted-checks.log；覆盖并发时间重叠与失败、三种Prompt材料、发送失败证据、原Prompt接口和逐父代覆盖。没有运行Mock搜索、没有正式求解、没有模型请求；不重复73项工程验收。
- 输入检查通过：10H编译/封印/原候选一致，21份训练输入SHA和顺序一致，12个P0 key唯一，common/legacy LB与顺序一致。
- 本轮源码在交付前以本地提交冻结，确切提交和文件SHA写入CODE_FREEZE.json。R1启动后不再加入非阻塞源码改动；若出现阻塞缺陷，先停下核查并保留原运行，不就地改绑定身份。旧练习已完成，源码变化后仍保留全部旧证据，不再恢复旧运行。
- R2/R3草案已建立但授权false，API2/评价2仍待线上验收。价格细节与其余准备不阻塞R1。R1真实完成之前，不宣称B1-V6正式搜索已就绪或已启动。
