# FJSP EoH单规则：离线准备交付

已核对其他页面：TSP原生EoH已完成260次，本页复用其`52cfc1d`版本的持久接入；TSP后续H池和验证不重复；API可靠性页面的客户端和证据留待最小集成。未找到已有同条件1050次的FJSP原生EoH训练入口，故只补问题适配。

## 已完成

- 独立工作区`/Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-single`；分支`codex/fjsp-eoh-single-prep-20261104`。保留所有原工作区修改和历史记录。
- 同完整train21、同未取整LB_v5、原append-only调度器与同分规则、solve_seed501、共享T30首解/复检。通过单H＋固定返回0的宿主调用原评价器，无局部搜索。
- 原生LLM4AD EoH（本地revision 2025/2/16）：N5，I1初始化，E1/E2/M1/M2循环；原生有放回父代抽样、同分/字符串重复惩罚、生存更新不改。不套用U的50代。
- 拟议总尝试1050包含初始化，初始化HTTP子上限50、原生初始化评价样本上限2N=10；失败/重复计预算，每槽一次尝试。EoH剩余演化为1050减实际初始化尝试，保存1023和1050两个节点。
- A实际23+1000=1023；B新增1000、共享P0来源23与重评成本单列；10H构建成本另列且不假设0。不宣称端到端、token或费用等成本。参数完整对照见`PARAMETER_COMPARISON.csv`，预算见`BUDGET.json`。
- 原生串行API/评价1，与A/B并发2的实现差异已披露；不报告算法耗时加速。48h持久窗口含暂停，不因恢复重置，与TSP原12h窗口明确区分。

## 验证与范围

13项不同离线检查通过：FJSP 11项、继承TSP原生存储/抽样及暂停恢复2项。另在最后强化参照模型/真实来源身份后复查2项重叠检查，不累加到15项。

Mock使用人工分数、无网络/求解；固定H0用已有R1完整21例记录验证可行性、LB、首解/复检及实际派发参数，不重新求解。检查日志和机器摘要见`offline-tests.log`、`identity-final-checks.log`、`VERIFICATION.json`。这不证明新EoH真实搜索质量或长实验稳定性。

本次实际新增API=0、策略求解=0、正式搜索=0，未创建本轮付费授权或真实运行目录。原生EoH源码逐文件SHA与TSP基线相同；原TSP工作区也未修改。唯一对既有适配的改动是独立新工作区中的默认行为不变`read_state`钩子。

## 用户入口

脚本：`experiments/common/run_fjsp_eoh_single.py`。

配置：`experiments/common/configs/fjsp-eoh-single.real.pending.json`。顶部预算/数据/方法参数集中于此，密钥不入文件。`provider=null`、`transport_binding=null`、`real_requests_authorized=false`。

先在上述工作区执行：

```sh
.venv/bin/python -B experiments/common/run_fjsp_eoh_single.py --check-only
```

会输出21实例、1050总上限/50初始化子上限、I1/E1/E2/M1/M2、API=0/求解=0及传输待绑定。正式运行和恢复命令、安全暂停、完整Mock练习见[操作说明](../../docs/FJSP_EOH_SINGLE_PREP_20261104.md)。

后续正式命令模板（当前明确拒绝，不会发送；需要先完成集成及本轮授权）：

```sh
caffeinate -i .venv/bin/python -u -B experiments/common/run_fjsp_eoh_single.py --run --run-dir runs/fjsp-eoh-single-real-20261104-01 --allow-api --approve-budget 1050
```

## 仅剩的正式启动阻塞

1. API页结论、准确客户端源码及技术证据待绑定；当前真实prepare、transport和resume门禁均关闭，不能只填provider就放行。集成后重新冻结新Protocol，不改历史Protocol。
2. 这一个EoH批次的1050次新预算尚未获得明确财务授权，不继承A/B或TSP授权。

新候选真实端到端求解按本次要求尚未执行；固定候选证据回放与参数派发已核对。无需等待网络结论再开展上述离线构建，已完成部分独立保留。
