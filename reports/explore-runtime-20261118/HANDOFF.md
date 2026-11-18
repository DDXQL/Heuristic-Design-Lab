# 公共工程交付卡

唯一公共树：`/Users/DDXQL/Developer/Heuristic-Design-Lab-explore-runtime-20261118`；分支`codex/explore-runtime-20261118`；父提交`963499d6943bdd8bdac3f1805f8186f4561fba9e`。本轮只授权必要代码和无API离线检查，未部署、未SSH、未请求模型、未求解、未提交Slurm，也未操作R11状态。

## 当前R13首TSP501路径

薄Mac桥接与六项菜单的独立冻结提交为`0477e1059b6a7613a2b6d2a05fb156ce7bc03873`。实际脚本`experiments/triad/r13_tsp_mac.py`仍与该提交逐字节一致，不受后续R14代码修改影响；额外守卫审查只存为未采用JSON中的diff，没有写入实际菜单。

六项菜单见`docs/R13旧TSP501-Mac独立菜单-20261118.md`，离线证据`R13_BRIDGE_OFFLINE.json`、`PATH_A.json`。使用现有SSH/取回机制；固定故障页manage.py及其SHA，并要求真实verify-handoff成功字段。管理工具只读preflight通过不等于handoff，也不构成TSP请求授权。

旧`six_ops prefix-submit`字典键错误已纯渲染复现；旧`parallel.py submit --settled-prefix 1 --approve-segment-solves 80`预览通过。每成员一次原初始化机会，合计最多2请求和80首解含复核求解，仍占原2040上限。`certify`无API但写本批Acceptance；旧路径仍要求两首候选有效才能通过。验收后复用同一R13检查点resume，不重初始化、不改截止或预算。若R13批次已开始，全部阶段留在R13，不能迁移到R14。

本轮没有新现场状态，未宣称账户交接完成、计划存在或已可RUN。当前首批运行授权与操作由总控按用户决定处理，本页不代提交。

## R14离线工程

源码冻结提交`74e47d6bca38e78d87da90285599a312d7009ace`；后续仅提交包核验及本卡。实际改动集中在shared_admission、parallel、six_ops、entry；新增薄部署shim、源码包工具和定向检查。核心code/、common入口、runtime科学逻辑、evaluator、V5、状态、研究配置及Slurm外壳均未变，哈希缓存后置。

新探索manifest显式采用explore-light-v1；严格路径保留。已知终态错误/明确未发送只结算自身许可和预留、保留失败及usage、不退款不重发，覆盖acquire预留后失败；未知发送/子进程/writer及账户级错误仍隔离。执行节点读密钥前核父账户归属、自己的writer、实际资源与密钥权限，按本次分配job/pid/node自动无API握手，不复用旧fs-pass。两sbatch/API1不变。安全关闭与1000科研完成解耦，未完成仍标未完成。

OFFLINE.json覆盖已知HTTP520/522/524、401/429、not_sent、未知worker、acquire失败、严格路径不变、两本地进程API峰值1、旧预检拒绝复用、单成员新分配本地双角色探针、writer归属、无1000完成的安全关闭、三连失败暂停、同一Mock序列下父代/算子/ID/种群/J/平局/RNG一致和首候选解析失败不作为基础设施门槛。STATIC.json记录保护范围与纯预览，PACKAGE.json记录实际包核验。均为离线证据，不是Slurm/跨节点/API现场验收。

新包`/Users/DDXQL/Developer/transfer-outbox/triad-explore-runtime-20261118-r14.zip`：1,241,930字节、501个清单文件，SHA-256 `25689916c28defb701927ec30f847e176fa77d595cb235ad8c6a0acd98e9100c`，附.sha256和.audit.json。解压后的只读预览通过。新部署位置仅规划为`/public2/home/qiuqian/hdl-deploy/triad-explore-runtime-20261118-r14`，未上传；不含旧运行、锁、凭据、LKH源码/二进制或实际TSP参照。后续复用已验收R13参照的原字节与来源，不重新算train20，尚须另获部署及真实运行授权。已在R13计划/启动的同名批次拒绝在R14重建。

## 新成功返回口径

仅有`docs/成功返回1000口径-只读差异评估-20261118.md`，没有实现。当前R13/R14均是1000演化尝试、初始化≤20、累计≤1020、每槽一次。新口径需要另定“成功返回”定义、独立发送上限、有限补发次数/类别，以及失败后保留哪份operator/parents/prompt/RNG。代码无效/重复/评价失败可在未来定义中计成功返回，但未知发送不能自动补发。H401和U初始化仍原规则单列。不把旧结果重新标成1000成功返回。

可复制的当前无副作用命令：Mac运行`r13_tsp_mac.py check-only`；R14运行`six_ops.py explore-preview --batch tsp501`。本卡不授予任何实际请求、账户处理或Slurm许可。
