# 用户手动准备与启动

以下命令在Mac项目根目录执行；第一行只设置解释器。r4 ZIP已固定时，stage只上传并核验，不提交作业。登录节点做文件和环境检查，生成、完整求解及复核须在计算节点。所有正式运行命令只有在采用研究参数、绑定资产和账户安排后才可执行，本交付未执行它们。

```bash
cd /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113
HDL_TRIAD_PY=/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python
"$HDL_TRIAD_PY" -s -B experiments/triad/batch.py plan --campaign experiments/triad/campaign.recommended.draft.json
```

集中建议见REVIEW_DRAFT.md与study-review.draft.json。先复制review、OBP划分和LKH规格，再由用户编辑新文件，原草案保持未批准。采用开关只由用户填写。下列review命令会生成新的六组配置和campaign.json，保留请求授权关闭；重复执行到同一路径会拒绝覆盖。

```bash
mkdir -p configurations/manual-20261114
cp experiments/triad/study-review.draft.json configurations/manual-20261114/review.json
cp experiments/triad/recommended.draft/obp-data.json configurations/manual-20261114/obp-data.json
cp experiments/triad/lkh.pending.json configurations/manual-20261114/lkh.json
# 编辑以上三个文件；尚无的资产路径可以先保持空，准备后再绑定新一版review。
"$HDL_TRIAD_PY" -s -B experiments/triad/review.py --review configurations/manual-20261114/review.json --output configurations/reviewed-20261114
```

TSP：编辑LKH规格中的已核验二进制绝对路径、SHA、版本、整数距离比例、RUNS、MAX_TRIALS、种子、超时和距离协议，并明确approved。以下prepare只生成计划；run才执行20个有界LKH进程，RUNS和MAX_TRIALS是各进程内工作量，不是额外免费重复。遇错停止，不自动补跑。输出是这些命令执行后生成的路径，当前没有假造参照文件。

```bash
"$HDL_TRIAD_PY" -s -B experiments/triad/assets.py lkh-prepare --config experiments/triad/recommended.draft/tsp-u.json --spec configurations/manual-20261114/lkh.json --output preparations/triad/tsp/lkh-20261114
# 用户明确采用LKH预算后，手动执行：
"$HDL_TRIAD_PY" -s -B experiments/triad/assets.py lkh-run --run-dir preparations/triad/tsp/lkh-20261114 --allow-lkh --approve-lkh 20
"$HDL_TRIAD_PY" -s -B experiments/triad/assets.py lkh-import --run-dir preparations/triad/tsp/lkh-20261114 --output preparations/triad/tsp/reference-20261114.json
```

将生成的reference路径绑定到review两组TSP的reference_file，确认data_usage_receipt。LKH导入会从完整路线按原始距离重算参照，不执行求解，不用NN兜底。

OBP：采用训练96／验证32及R_code后，将obp-data.json的adopted设为true。输入须为SHA已声明的训练pickle；以下交互读取用户实际路径，没有虚构输入文件名。导入只做数值／身份／参照预检，不运行H或U，不打开测试文件。

```bash
read -r 'HDL_OBP_TRAIN?已核验训练pickle的完整路径：'
"$HDL_TRIAD_PY" -s -B experiments/triad/assets.py obp-import --source "$HDL_OBP_TRAIN" --spec configurations/manual-20261114/obp-data.json --output preparations/triad/obp/data-20261114
```

将preparations/triad/obp/data-20261114/train.manifest.json绑定到review两组OBP的data_manifest，填写data_usage_receipt，并采用候选状态。OBP U还缺H，先用OBP EoH配置进行独立H构建，避免U尚无H的依赖。重组review时选新output目录，例如configurations/reviewed-assets-20261114。H构建的窗口、搜索种子401、40次上限和10条目标都须在该配置h_build内明确。下列检查不运行：

```bash
"$HDL_TRIAD_PY" -s -B experiments/triad/entry.py check-only --kind h-build --config configurations/reviewed-assets-20261114/configs/obp-eoh.json
```

H构建以下为未来用户手动执行的真实请求／求解命令，40次独立记账，不属于搜索1000次。入口使用h_build.search_seed=401及独立窗口，不借用搜索种子；运行目录须全新。不得在登录节点执行build-run。集群用户在计算节点使用集群Python和部署后的同一相对路径；集群prepare会上传preparations内已绑定资产。

```bash
"$HDL_TRIAD_PY" -s -B experiments/triad/assets.py build-prepare --config configurations/reviewed-assets-20261114/configs/obp-eoh.json --run-dir runs/obp-H-build-20261114 --allow-api --approve-budget 40
"$HDL_TRIAD_PY" -s -B experiments/triad/assets.py build-run --config configurations/reviewed-assets-20261114/configs/obp-eoh.json --run-dir runs/obp-H-build-20261114 --allow-api --allow-solves --approve-budget 40
"$HDL_TRIAD_PY" -s -B experiments/triad/assets.py freeze --run-dir runs/obp-H-build-20261114 --output preparations/triad/obp/H-frozen-20261114.json
```

冻结H后绑定OBP U的h_file，再组装最终review到新目录configurations/reviewed-final-20261114。无需重新训练H来生成报告。FJSP已有210项成本，走fixed-import／fixed-plan，缺兼容包时拒绝完整重评。

正式搜索：先在本地prepare物化独立子配置；若采用旧501，按相同批次只读登记。这里均是文件准备，register会读取原完成摘要与校验回执，不启动旧运行。

```bash
"$HDL_TRIAD_PY" -s -B experiments/triad/batch.py prepare --campaign configurations/reviewed-final-20261114/campaign.json --batch plans/reviewed-final-20261114
"$HDL_TRIAD_PY" -s -B experiments/triad/batch.py register-existing --batch plans/reviewed-final-20261114 --experiment fjsp-u --seed 501 --accept-existing-completed
"$HDL_TRIAD_PY" -s -B experiments/triad/batch.py check-only --batch plans/reviewed-final-20261114 --all
```

登记回执位于该batch的registrations/，文件名由Batch.json内run_id加.json确定；不复制checkpoint。要在集群汇总501，用prepare的--existing-receipt传这份实际回执。若不采用501，从最终种子清单删除并选择新种子，不能重新跑同名501。

上传、资源只读检查与最终配置／输入准备复用已有连接；每次调用集中一次交互认证。stage固定r4；prepare对preparations中的已绑定输入逐文件核验，遇已有不同文件拒绝覆盖，不上传凭据。

```bash
"$HDL_TRIAD_PY" -s -B experiments/triad/cluster.py stage
"$HDL_TRIAD_PY" -s -B experiments/triad/cluster.py inspect
"$HDL_TRIAD_PY" -s -B experiments/triad/cluster.py prepare --campaign configurations/reviewed-final-20261114/campaign.json
```

以下示例只在最终采用了对应建议、账户许可已生效时由用户执行。使用campaign_id作为--batch-name（建议文件默认triad-reviewed-20261113）；与本地plans文件夹名无关。此处以fjsp-eoh、502和1020示范，尚未批准，当前会拒绝运行。

```bash
"$HDL_TRIAD_PY" -s -B experiments/triad/cluster.py submit --batch-name triad-reviewed-20261113 --experiment fjsp-eoh --seed 502 --submit --allow-api --allow-solves --approve-budget 1020
"$HDL_TRIAD_PY" -s -B experiments/triad/cluster.py query --batch-name triad-reviewed-20261113 --experiment fjsp-eoh --seed 502
"$HDL_TRIAD_PY" -s -B experiments/triad/cluster.py fetch --batch-name triad-reviewed-20261113 --experiment fjsp-eoh --seed 502
```

pause使用同一batch-name／experiment／seed；resume使用同样的原累计额度和授权标志，只把submit改成resume。恢复前必须已安全paused、无在途未知或writer锁、原窗口尚有效。summary使用同一batch-name取回全批统计；Slurm结束不等于应用已完成1000次。遇未知提交／发送或错误保留现场停止，不删锁、不退预算、不补跑。

六组在Mac使用mac.sh／batch.py的相同单次run、pause、resume、export入口；正常操作不需要Codex在场。未知状态、协议改变或预算追加才需重新核查。r3当前只完成本地离线验收，没有新增集群作业证据。
