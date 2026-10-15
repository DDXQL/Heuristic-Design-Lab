# 单成员U真实训练：组会材料（2026-10-15）

本目录只整理已有真实训练结果，不发请求、不执行求解、不修改runs/。本批各组槽位处理完毕，但因实际调用不均衡而不构成有效四组方法比较。

1. [一页中文进度说明](01_进度说明.md)
2. [实验汇总、适应度与固定成员参照](02_实验汇总.md)
3. PPT用图：[请求与有效候选PNG](03_requests.png) / [SVG](03_requests.svg)；[初始与最终表现PNG](03_population.png) / [SVG](03_population.svg)
4. [真实交叉案例](04_真实交叉案例.md)（包含5父代、当次提示/响应、源码、21实例成绩和生存结果）
5. [实验材料索引及已知缺失](05_证据索引.md)
6. [约1分钟口头稿](06_口头汇报稿.md)
7. [机器可读汇总](summary_data.json)、[数据与H身份](training_identity.json)、[来源哈希](source_manifest.json)、[材料核对](verification.json)、[独立备份凭证](Backup_receipt.json)

两张图均为16:9白底、2640×1485 PNG及文字转路径SVG；只展示初始和一代终点，不绘制多代收敛曲线。B1实际请求=0、预算不一致与不可归因警示已写入图内。SVG可缩放，PNG可直接插入PPT。

## 离线重新生成

在本worktree运行（系统Python带matplotlib与中文字体，本项目.venv目前不含matplotlib）：

```sh
python3 tools/build_single_meeting_materials.py --run-dir runs/single-ID-gpt61-paired-training-20261014-v1 --out reports/20261015-single-ID-training
```

生成工具仅使用标准库和matplotlib（本机3.10.0），不导入provider或求解器；核对全部21条有效U的历史逐实例数值，不重新评价。reports/保存精简说明、图和一个案例；runs/、原始账单、数据、环境与密钥不进入Git。来源原始run完整备份和1035份绑定历史材料在仓库外，恢复位置见Backup_receipt.json。GitHub上的本地runs链接不能代替这份备份。
