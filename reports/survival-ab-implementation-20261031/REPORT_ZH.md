# 行为组代表优先survival：代码与离线交接

基线：已发布`b1-v6-n10g50-train21-20261031-v1`，提交`1ef81998823cc2a9257c232f10a3b75b1ccf1820`。独立分支`codex/behavior-first-survival`，worktree为`/Users/DDXQL/Developer/Heuristic-Design-Lab-survival-ab`。原工作区未切换、未清理或覆盖；其入口注释修改和未跟踪文件保留。

本次模型请求0、求解0、付费授权创建0；没有真实A/B运行目录、P0重评、验证集访问、自动重复、打包或历史清理。仅临时纯数据序列化测试创建了假输入的Protocol，不能写成实验验收。

## 唯一机制改动与生效位置

- `core/search.py`保留原`ranked/survive`；新增`survive_behavior_first`：原Fitness降序/固定ID升序，优先各行为组最好一名；组过多时取前N个代表，组不足时按原排名补齐，最后按原顺序排序。完整精英和N不变。
- `core/evolution_v1.py`新增`survival_policy`，默认`fitness`，显式`behavior_first`切换；仅在代末选择处分派。Protocol保存该字段及选择说明，配置与源码共同形成新身份，拒绝修改旧Protocol/目录作为恢复。
- 薄入口参数白名单接通这个字段。状态、Prompt、生成/交叉/变异、Fitness、import/LLM初始化规则、API/评价池、实例期限和预算计数没有改动。
- 完整train21 H序列的`behavior_sha256`是已有评价产物；它不是未见状态上的等价证明，也不保证不同组一定对应不同物理排程。

## 纯离线检查

`checks.log`：19项检查通过，约1秒。覆盖默认旧策略、显式切换、全局精英、组内最好、组不足补齐、单组退化为原排名、固定ID平局、输入顺序无关和不修改输入、未知配置/身份/预算拒绝。

配对检查包括真实历史P0身份审计、只允许两份selector/dispatch源码差异、P0/模型/状态/种子/期限不兼容拒绝、两臂仅policy不同、新Protocol唯一身份、关闭开关及缺新授权时不prepare/run/建目录、历史1050授权不可复用、pair指纹绑定P0/配置/预算、恢复忽略新顶部参数。网络和solver在相关检查中显式禁止。

运行测试使用现有环境的只读共享`.venv`符号链接，未安装依赖或提交虚拟环境。

## 已有候选池的一步选择审计

`tools/replay_survival_saved.py`只读取已完成运行。对每代各自使用原父代和原有效子代，独立比较A/B；**不把B的选择传播到下一代，不伪造新的50代轨迹**。

50个原始池中：原策略全部复现历史入选ID；新策略全部保留同一全局冠军，50池的入选集合均变化、保留行为组均增多。

|原始池|A行为组|B行为组|A均值Fitness|B均值Fitness|
|---|---:|---:|---:|---:|
|G14|3|10|−2.035407|−2.187922|
|G22|1|10|−2.033994|−2.169787|
|G30|1|7|−2.033994|−2.140537|
|G50|1|10|−2.033994|−2.135148|

代表优先会保留当前总体Fitness较弱的不同组，因此当代均值可能下降。这只证明选择规则产生预期差异，**不能证明新策略能产生更好的后续子代或最终结果**。表格与ID见`selection-audit/`。

## A/B入口与实际生效参数

脚本：`experiments/common/run_survival_ab.py`。顶部集中设置源工作区、P0来源、pair目录、N/G、种子、H/train21路径、模型/端点、请求/实例期限、输出上限、两种并发和预算。

本次只准备seed501这一对。A=`fitness`；B=`behavior_first`。各N10/G50，每代10 CROSS＋10独立MUTATE，API2/CPU2；LeafAPI/gpt-6.1-sol，原流式传输，10/240/300秒连接/读取/总期限、8192输出上限、T30首解复检行接收、W10。两臂配置只有`survival_policy`不同。

已有P0来自原N10/G50运行的`populations/P000.json`。审计其Protocol/checkpoint、首代冻结父代计划、H/data顺序与原始SHA、10个AST不同候选、完整21实例双遍/源码/行为收据。当前81份执行源码中只允许`search.py`与`evolution_v1.py`发生本次选择改动；其他评价、状态与传输源码必须逐字节相同。模型传输及评价配置也必须匹配。

共享的是同一冻结程序集合和顺序，**不是把历史Fitness直接写进新账本**。未来启动各臂时，按既有import机制各自重评10个U；若初始化不足N，原引擎停止，不补借程序。完成后另存`p0-recheck.json`核对实际重评Fitness/H序列；不匹配时不能把结果作为可比配对。此处没有实施P0重评。

首次实际获新授权启动时冻结`Pair.json`，A/B分别在其子目录生成独立Protocol、源码身份、检查点、日志和exports。后续启动B/恢复读取原Pair，不采用后来编辑的顶部参数；源码或指纹变化拒绝。每臂沿用原engine及导出实现，不重写API、演化、并发或恢复。

## 可复制命令

在新worktree根目录。现在可执行的安全预览：

```sh
.venv/bin/python -u -B experiments/common/run_survival_ab.py --check-only
```

只读审计与预览，无API/求解/运行目录创建。`preview.json`和`A.config.preview.json`、`B.config.preview.json`是本次预览快照，**不是已启动实验的Protocol**。

以下为未来单独授权并登记后，依次由用户执行的A/B命令；**目前开关False、AUTHORIZATION_FILE=None，会在创建运行和请求之前拒绝**：

```sh
.venv/bin/python -u -B experiments/common/run_survival_ab.py --arm A
.venv/bin/python -u -B experiments/common/run_survival_ab.py --arm B
```

不要同时启动两臂，避免叠加为API4/CPU4。两条命令必须使用同一pair目录（默认`runs/survival-ab-seed501-01`）；普通启动拒绝已有arm目录，completed不能resume。

```sh
.venv/bin/python -B experiments/common/manage.py --problem fjsp status --run-dir runs/survival-ab-seed501-01/A
.venv/bin/python -B experiments/common/manage.py --problem fjsp pause --run-dir runs/survival-ab-seed501-01/A
.venv/bin/python -u -B experiments/common/run_survival_ab.py --resume A
.venv/bin/python -B experiments/common/run_survival_ab.py --export A
```

B相应替换arm/路径。暂停排空现有批次；未知锁/在途保留核查。恢复与导出读取冻结配置，不能扩大预算或暗中重用历史授权。

## 预算与阻塞

|项|本次准备的单对预算/成本|
|---|---:|
|源P0历史LLM初始化|实际23次尝试，上限50；已发生，不重计为本次新请求|
|源P0已知输入/输出|116550 / 9403 token；8份usage未知，实际货币成本未核实|
|本次复用P0的新生成请求|0|
|未来A演化|最多1000次尝试，每逻辑请求一次，无自动重试|
|未来B演化|最多1000次尝试，每逻辑请求一次，无自动重试|
|未来这对新API上限|2000次，不是2050或6150|
|未来P0重评CPU|每臂10个程序，合计20个×21实例×2遍＝840遍|
|未来单对最坏总求解遍数|84840遍；失败/重复会减少实际求解|

实际未解决事项：新的2000次配对付费授权尚无、开关仍关闭，用户执行终端将来需提供环境变量密钥；本实现没有线上A/B结果或新策略效果结论。其他种子没有对应P0声明，不自动运行三次。若未来改为新生成P0，应另行准备、授权并单列初始化成本，本入口不偷偷生成。

当前P0、H/train21及基线来源仍通过绝对路径读取原工作区，必须保留；新worktree不是这些未跟踪运行资产的完整副本。按AGENTS另行处理Windows归档；本次没有打包或清理。
