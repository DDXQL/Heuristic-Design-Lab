# Heuristic-Design-Lab：多问题实验与中文文档入口

- **第一次使用**：[项目使用说明](项目使用说明.md)。
- **自己配置和运行实验**：[实验操作指南](docs/实验操作指南.md)。包含参数、真实API、训练集、启动、查看、安全暂停、恢复和汇总的完整命令。
- **阅读和修改代码**：[实验代码地图](docs/实验代码地图.md)。

正文已使用中文文件名。保留本文件作为GitHub及编辑器的标准首页；旧英文文档路径仅保留导航，避免历史链接失效。命令、配置字段和代码标识保持原名。

- **当前开发位置**：`/Users/DDXQL/Developer/FJSP-Heuristic-Research-h-usage-space`。Documents副本只保留来源，不在两个副本同时开发。
- **多问题入口与旧路径映射**：[多问题结构与迁移说明](docs/多问题结构与迁移说明.md)。FJSP旧入口兼容，TSP复用独立工作树当前实现；未宣称跨问题质量已验证。
- **冻结与保存范围**：[Developer迁移说明](reports/迁移至Developer-20261027-v1/迁移说明.md)。有尚未下载资产，Git上传不代表原始runs全部上传。

- **通用状态设计**：[通用状态接口设计V1](docs/通用状态接口设计V1.md)。保留七输入/五输入legacy；共同状态是禁用草案，不是已验证新算法。


## 已完成的TSP成果与本次集成

- [最新真实TSP小试](reports/tsp-pilot-20261028-complete/REPORT_ZH.md)：50逻辑任务/50尝试，validation最终选择静态U；不是演化稳定收益的证据。
- [TSP最新成果迁移与接入](docs/TSP最新成果迁移与接入.md)：来源c3b74b7、Developer整理版864c116、独立集成分支、历史资产保存与只读核验。
- [TSP问题定义与既有入口](docs/TSP_ADAPTER.md)：保留五输入、几何游程、SELECT/MIX和相对NN指标；共同状态草案仍禁用。

当前集成工作树为`/Users/DDXQL/Developer/FJSP-Heuristic-Research-tsp-integration`。原Developer整理分支和旧TSP树保持原样，历史运行禁止直接从迁移位置续跑；新示例真实请求仍默认未授权。本轮无API或正式求解。
