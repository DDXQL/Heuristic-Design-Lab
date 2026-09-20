# FJSP Heuristic Research

这是从 EoH-S 的冻结版本 `fjsp-tier1-single-rule-v1` 导出的独立研究项目。当前基线为单一构造式工序–机器优先级规则 `Tier1-Fixed-H-v1`，后续研究可以在不改变 Tier1 调度与评价协议的前提下开发启发式使用策略。

## 冻结来源

- 源仓库：`/Users/DDXQL/Documents/大学/硕士/代码/EoH-S`
- 源 commit：`b3b67d6522466e66baba5eb57990d3fb2bfeca23`
- 源 tag：`fjsp-tier1-single-rule-v1`
- 源 manifest SHA-256：`0869517771bbac44db814655e1f20f55ea7291b9b4c80b5949aff92047cbc3af`
- Canonical 规则：`baselines/tier1_single_rule_v1/rules/selected_rule_seed_2026092002.py`
- Canonical SHA-256：`0991e17f833e7ab773b0ff13ea2396a0cb3ccb9d94715984fb1ef421ea89496a`

Seed `2026092002` 在补做三种子稳定性检查前已经确定。Seed `2026092003` 和 `2026092004` 只作为复核规则保存，不构成 Tier2 heuristic set。

## 目录

```text
code/llm4ad/                         上游运行依赖的最小闭包
code/fjsp_usage/                     Tier2 包装层预留接口
experiments/tier1/                   portable 训练、预检、评价与配置
experiments/tier2/                   Tier2 研究边界说明
baselines/tier1_single_rule_v1/      三个冻结规则及三种子记录
 data/fjsp/                           本地实例，因许可状态未确认而不提交
 data/fjsp_manifest.json              数据文件哈希和固定 split
 docs/                                接口、实验和研究对齐文档
 provenance/                          原始配置、manifest、入口和迁移映射
 tests/                               FJSP 调度与评价契约测试
 verify_portable_baseline.py          独立离线验证入口
```

`code/llm4ad/base`、`code/llm4ad/method/eoh` 和 `code/llm4ad/tools` 来自冻结的 EoH-S/LLM4AD 框架。`code/llm4ad/task/optimization/fjsp_set`、FJSP 实验入口、验证脚本和研究文档是本研究新增内容。未导出 EoH-S、OBP、TSP、CVRP 或其他搜索方法。

## 安装

推荐 Python 3.12：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

虚拟环境、API 配置和运行日志均被 `.gitignore` 排除。

## 验证冻结基线

```bash
.venv/bin/python verify_portable_baseline.py
```

该命令不调用 LLM、不运行演化、不通过 FJSP loader 打开 test 实例。它验证 portable manifest、规则接口、微型实例、21 个 train、11 个 validation、三个规则、EFT/SPT/MWKR 和单元测试。

## 后续运行 Tier1

训练入口仍可用于未来显式创建的新实验版本：

```bash
export EOHS_API_HOST='<host>'
export EOHS_API_KEY='<key>'
export EOHS_MODEL='deepseek-flash'
.venv/bin/python experiments/tier1/run_eoh_single.py \
  --config experiments/tier1/configs/portable_single_rule_config.json \
  --stage formal --run-dir runs/example
```

不要提交 API 密钥。本次导出没有执行该命令，也没有生成候选。

## 数据

本机已将固定 split 的 60 个实例和 `sample.fjsp` 复制到 `data/fjsp/`。文件没有纳入 Git，因为当前再分发许可尚未确认。缺少本地数据时，按 `data/README.md` 和 `data/fjsp_manifest.json` 恢复并核验。

## Tier2 边界

Tier2 可在 `code/fjsp_usage/` 增加满足同一七特征输入与有限标量输出的包装层。实例加载器、七特征、固定调度器、可行性检查、lower bound、score 和 EFT 必须继续复用。详见 `docs/fjsp_tier1_single_rule_baseline_v1.md`。
