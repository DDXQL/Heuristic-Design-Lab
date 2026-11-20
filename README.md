# Heuristic Design Lab

[选问题和方法](docs/实验导航.md) · [查代码和结果](PROJECT_MAP.md) · [查协议和参数依据](DECISIONS.md)

```text
JSON 或终端菜单 → tools/experiment.py → 每个种子一个 Slurm 作业
                                        ├─ 同批 API 并发与节奏
                                        └─ 独立检查点与结果 → status / export
```

| 问题 | 常用配置与缺项 |
| --- | --- |
| [TSP](docs/实验导航.md#tsp) | [U／EoH](configurations/experiments/tsp-502.json)。需要已核验的 D06 train20 参照 |
| [FJSP](docs/实验导航.md#fjsp) | [EoH](configurations/experiments/fjsp-503.json)。R15 尚未接入冻结版 U |
| [OBP](docs/实验导航.md#obp) | [U／EoH](configurations/experiments/obp-501.json)。U 缺 H401 冻结集 |

方法、固定 H 入口和待接入的传统 HH 见[能力矩阵](docs/实验导航.md#能力矩阵)。开发主线提供三种子独立执行。本页的新命令需要已包含该提交的新部署，现有 R15p3 仍按[原操作手册](docs/研究人员实验操作手册.md)运行。

## 路线一 · Mac IDE 改 JSON，集群提交

在 Mac 的项目根目录打开 VS Code 或 Cursor，复制一份模板并换 `name`。在 `research.runs` 写 1～3 个独立的方法／种子组合。设置训练清单、冻结 H 和参照路径。相对路径从项目根解析。API 并发、超时和请求上限在 `execution.api`，CPU 和时限在 `execution.slurm`。

Mac 本地已有环境可直接预检。若需要新环境，在项目根运行 `python3.12 -m venv "$HOME/.venvs/hdl-r15"` 和 `"$HOME/.venvs/hdl-r15/bin/python" -m pip install -r requirements.txt`。

```bash
P=/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python
CFG=configurations/experiments/tsp-502.json
"$P" -s -B tools/experiment.py prepare "$CFG"
```

本地可编辑、预检和运行离线 Mock。正式搜索交给集群计算节点。上校园网后用 SSH 登录，配置可用 `scp` 传到新发布目录。

## 路线二 · 在家用 UU，进入实验室 Windows 的 CMD

Windows 只用来登录和传文件，无需安装项目 Python。

```cmd
ssh -J custom@222.201.144.188:22 qiuqian@110.1.2.1
```

Mac 在校园网使用同一条登录命令。在出现 `[qiuqian@master ~]$` 后，进入已部署的发布根目录。以下命令在集群 Linux 终端执行。

```bash
P=/public2/home/qiuqian/hdl-envs/portable-v2/bin/python
"$P" -s -B tools/experiment.py configure --platform cluster
```

菜单只保存真实 JSON，显示资产、预算、源码和对应命令。也可以直接用已有 JSON。

## 预检、启动、查询和取回

```bash
CFG=configurations/experiments/tsp-502.json
"$P" -s -B tools/experiment.py prepare "$CFG"
"$P" -s -B tools/experiment.py run "$CFG" --approve
"$P" -s -B tools/experiment.py status "$CFG"
"$P" -s -B tools/experiment.py export "$CFG" --out "$HOME/tsp-502-results.zip"
```

`pending: []` 表示资产预检通过。真实运行使用已验收的发布版本和已授权的并发。提交收到作业号后可关闭电脑。申请暂停用 `pause`，等 `status` 显示 `operator_paused` 后用 `resume`。正常时限接续由 Slurm 自行处理。12 小时后看应用状态，候选还没达标时可查已完成数量及原因。

从实验室电脑 **本地 CMD** 取回 ZIP，再用 UU 传回 Mac。

```cmd
scp -J custom@222.201.144.188:22 qiuqian@110.1.2.1:/public2/home/qiuqian/tsp-502-results.zip "G:\Experiment\transfer-outbox\tsp-502-results.zip"
```

[现场验收与版本状态](DECISIONS.md#验收与回退) · [历史 R13、R15p3 入口](docs/实验导航.md#历史版本)
