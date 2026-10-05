# Current project versions and maintenance

本仓库保存冻结的 Tier1 单规则基线及两个独立版本的 Tier2 离线原型。
根目录 README 和旧包装层说明来自冻结导出；当前开发状态以本文及各版本 README 为准。

| Component | Version | Location | Status |
| --- | --- | --- | --- |
| Tier1 baseline | Tier1-Fixed-H-v1 | `baselines/tier1_single_rule_v1/`, `experiments/tier1/` | 冻结单规则基线；canonical seed = 2026092002 |
| Tier2 interface demo | Tier2-Offline-Prototype-v1 | `code/fjsp_usage/offline_v1.py`, `experiments/tier2/offline_v1/` | 状态对象接口、微型实例演示 |
| Tier2 V5 interface demo | Tier2-Offline-V5-Interface-v2 | `code/fjsp_usage/offline_v2.py`, `code/fjsp_usage/training_v2.py`, `experiments/tier2/offline_v2/` | 七项状态接口、训练批量评价演示；当前开发起点 |

Tier1 的三个 seed 是同一协议下的独立实验运行，不是三个 Tier1 版本。
2026092003 和 2026092004 仅用于稳定性复核；历史参考规则也不替代 canonical。
Tier2 的 H 仍是固定手写 EFT/SPT 演示集合，U 是手写示例。
尚未实现正式 EoH-S 集合生成、LLM 生成 U 或 U 演化实验。

## Quick start

在仓库根目录创建 Python 3.12 虚拟环境并安装 `requirements.txt`：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 不需要 benchmark 数据，不调用 LLM
.venv/bin/python experiments/tier2/offline_v1/run_demo.py
PYTHONPATH=code .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v

# 需要按 data/README.md 恢复本地训练数据；仅评价预先手写 U
.venv/bin/python experiments/tier2/offline_v2/run_training_demo.py
```

截至 2026-10-05，本地全部 26 项单元测试通过。
v2 已保存的演示报告中，两个 U 均完成 21 个 train 实例；未评价 validation/test。
运行结果位于被忽略的 `runs/` 目录，新检出仓库需要重新运行才能得到报告。

## Frozen provenance and comment translations

原始导出提交及标签 `fjsp-tier1-baseline-v1` 保留。
当前四个 Tier1 规则包含中文注释/函数说明翻译；去除说明字符串后，其程序 AST 与
原始提交一致。翻译单独提交，保留文件内容和原有冻结清单。

冻结清单记录的是原始文件 SHA-256，注释翻译也会改变文件哈希。
因此当前主分支运行 `verify_portable_baseline.py` 会因规则文件字节差异而失败；
不能把 26 项单元测试通过解释为完整冻结验证通过，也不能仅为消除差异而重写清单。
需要原始字节时可通过冻结标签查看或在另外的检出目录复现，避免覆盖当前开发文件。

## Separate updates in one repository

- `main` 保存可运行的项目快照；每个实验版本保留独立模块、入口、manifest、说明和测试。
- 未来修改先创建工作分支，例如 `codex/tier2-v2-update`，测试后合并回 `main`。
- 更新 v2 时优先修改 v2 文件；保留 v1 用作历史对照和回归检查。
- 若改动接口、下界或评价协议，建立新实验版本并记录差异。v2 的 LB 不取整，
  与冻结 Tier1/v1 的分数不能直接混用。
- 基线改动、v1 改动和 v2 改动分别提交，方便独立审阅及回溯。

现有 `.gitignore` 排除虚拟环境、密钥配置、日志、运行结果及许可未确认的 benchmark 数据。
`experiments/tier2/offline_v1/tiny.fjsp` 为可提交的合成微型实例。
