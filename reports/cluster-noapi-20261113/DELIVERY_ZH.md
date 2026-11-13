# 集群无API部署准备交接

公共执行代码冻结于923781f；本树只增加部署脚本。当前Mac长实验未被修改或重启，门禁、锁和检查点均未读取或复制。

完整操作与节点边界见[部署说明](../../deploy/cluster-mock/README_ZH.md)。当前阶段见[preparation-status.json](preparation-status.json)；本地Mock证据见[local-acceptance-summary.json](local-acceptance-summary.json)，隔离负向检查见[negative-isolation-check-v2.json](negative-isolation-check-v2.json)。假Slurm回执和取回模拟均已明确标记，不能作为计算节点证据。

当前已准备，尚未上传、尚未在计算节点验证。公共研究草案的未冻结拒绝是预期结果，不是环境错误。stage只做远端盘点、文件部署与轻量导入检查，不提交Slurm；正式搜索继续未授权。

下一步在Mac终端执行说明中的stage命令。脚本会在首次SSH连接处要求交互认证，并自动将返回材料写到本树reports/cluster-noapi-20261113/latest-stage.json及对应明细目录。此前非交互认证失败，本轮接续未重复尝试。
