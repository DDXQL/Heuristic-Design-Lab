# 归档清单与本地依赖（尚未打包/传输）

当前状态：本批已完成且无writer锁；本轮仅冻结代码与分析。ZIP未生成，UU未传输，Windows未核验，本地未清理。Git推送不能替代实验备份。

## 适合单独打包本轮的内容

待传输ZIP将来统一放在`/Users/DDXQL/Developer/transfer-outbox`，不放Documents或iCloud。无需打包全部历史。

1. 本轮完整`runs/b1-v6-b1-20261030-155904-688532-7ced645e/`：Protocol及收据、checkpoint及收据、launch快照、Prompt/响应、候选源码/谱系、batch/worker/生命周期记录、全部有效和失败评价、populations、milestones、日志及exports。不要只留冠军而丢掉退化或失败。
2. 本报告目录和新基线标签对应代码快照；环境说明/依赖文件及Protocol.machine中的Python信息。不要把整个`.venv`或`.git`对象库当环境包。
3. `preparations/b1-v6-20261029/H_frozen.json`、`train21.manifest.json`及其train21原始21文件。虽然Protocol嵌入了解码实例，原始文件SHA及来源仍应保留。
4. R1/R3引用记录与必要证据作为独立依赖包列明，避免把以前归档的多个相同副本重复塞进ZIP。第一次传输时若Windows尚无这些证据，必须连同相应完整依赖目录或独立依赖ZIP一起传输，不能只写一个不存在的路径。
5. 附ZIP内文件清单、每文件SHA-256及ZIP自身SHA-256；Windows可用PowerShell `Get-FileHash -Algorithm SHA256`核对ZIP，再用`Expand-Archive`或常见ZIP软件解压并逐文件核对。打包时须正确处理硬链接：可以保存为两个普通文件以保留两处读取路径，清单注明内容重复。Windows此处用作存档，尚未验证该Mac执行环境能在Windows直接运行。

排除密钥、`.env*`、凭据文件、虚拟环境、当前授权/认领原件。原件仍在本机保护，不能因未入ZIP就删除。`launch/prerequisites.json`中的路径/摘要引用不是授权原件，保留以连接历史身份。外部账单若以后纳入，须脱敏并单列其范围和身份。

## 仍需在Mac保留的依赖

以下路径仍由当前入口、预检或分析引用，不因代码推送/待传输包完成就删除：

- 本轮运行目录及其exports中的冠军、结果表、逐实例行、冻结参数与检查点；后续验证也要引用冻结U/H。
- `runs/b1-v6-r1-train21-20261029-221535-858514-d3145ddd/`：12条固定候选及正式比较来源。
- `runs/b1-v6-r1-legacy-train21-20261030-100428-400291-dd2640cb/`：H0、静态H0/H1评价。
- `runs/b1-v6-r1-eoh-train21-20261030-111505-503272-95a4a92f/`：原生冻结EoH评价及来源。
- `runs/b1-v6-r3-20261030-134523-982946-70326e84/`：已通过的小预算接入/并发证据。
- H/train21原始资产、基线来源文件、`launch/baselines.json`，以及真实入口引用的recording-compatibility/verification等小型收据。
- 本地授权认领记录，防止普通启动把已用预算重新认领为新批次；已完成运行不应resume。

其他历史运行本次不处理，不因为本清单没有列到就视为可删除。

## 传输与清理条件

包完成后先告诉用户位置、大小、SHA和Windows核验步骤；用户通过UU手动传输。只有用户确认传输及Windows校验成功，才讨论对应本地历史文件清理。Mac长期保留精简报告、结果表、冠军程序、冻结身份及Windows真实归档位置记录；仍被当前实验引用的依赖继续保留。
