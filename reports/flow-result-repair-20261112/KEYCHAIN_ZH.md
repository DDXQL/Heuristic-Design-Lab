# Mac一次保存API密钥

2026-11-12增量说明。此前的冻结启动脚本只把隐藏输入保留在本次进程，结束后丢弃，因此新终端启动会再次要求输入。用户本次要求保存一次、后续自动读取；新增Mac凭据包装入口，复用原启动脚本，没有修改冻结客户端、实验源码、原部署包、参数、账本或累计上限。

## 一次保存

在Mac交互终端执行：

```sh
cd /Users/DDXQL/Developer/Heuristic-Design-Lab-flow-result-repair-20261112
bash deploy/flow-check/start-with-keychain.sh --setup-only
```

系统会隐藏询问LeafAPI密钥，保存到默认Mac钥匙串。保存条目的service为 `org.heuristic-design-lab.leafapi`，account为 `LEAFAPI_API_KEY`。`--setup-only` 仅保存/检查凭据，不请求模型、不求解、不提交作业；重复执行是明确更新这个专用条目。

密钥不写入项目、日志、shell历史、命令参数、临时文件、ZIP或集群。保存用的是系统 `security add-generic-password` 的原生隐藏提示：`-w` 放在末尾且不传密码参数。没有设置允许任意应用访问的 `-A`。读取时只把系统工具的输出收进包装进程内存，然后通过环境交给原启动进程，不把密钥打印到屏幕。

## 后续启动

以后使用以下入口，自动读取同一个钥匙串条目；不再用只保留本次输入的原start作为首选入口：

```sh
cd /Users/DDXQL/Developer/Heuristic-Design-Lab-flow-result-repair-20261112
bash deploy/flow-check/start-with-keychain.sh --allow-api --approve-api 2 --allow-evaluation --approve-solves 12
```

此命令会启动原来声明的有限验证：累计模型请求最多2次；原失败占用2次求解继续计账，新增Mac最多6次、集群最多4次，累计最多12次。Mac成功后可能提交一个集群回放作业。没有因为保存密钥而获得新预算、自动重试、补发或重新开始的权限，原启动器仍检查已有目录、终态、暂停、锁、预算和源码身份。

已安全暂停的修复阶段，才可在上述参数前加 `--resume`；并不是用凭据设置恢复已失败的旧批次。Mac已经完成时继续使用原传输/提交入口，不再次运行Mac。取回仍使用 `bash deploy/flow-check/fetch.sh`，不读取钥匙串、不请求模型、不求解、不提交作业。

明确提供的合法 `LEAFAPI_API_KEY` 环境变量可临时覆盖钥匙串，但不会自动保存。钥匙串不存在、锁定、权限拒绝或密钥格式不合法时直接停止，不改写已有条目，也不重试模型。密钥失效或更换时重新执行一次 `--setup-only`。Mac可能要求首次允许钥匙串访问，锁定时仍需系统解锁；这与重复输入API key不同。跳板机/集群SSH认证没有修改。

## 已实现与实际状态

新增 `deploy/flow-check/start-with-keychain.sh`，是Mac本地薄包装，不放入集群部署包。默认无参数或 `--check-only` 不访问钥匙串、不请求模型、不求解。集群仍无模型请求，也不会读取Mac钥匙串。

9项测试使用本地替身，未访问真实钥匙串、真实启动器、SSH、API或求解器；覆盖原生隐藏保存方式、默认无访问、自动读取、临时环境覆盖、拒绝/格式错误停止、参数保持、接续和退出码传递。日志见 `keychain-tests.log`。脚本语法检查通过；原冻结计划SHA仍为 `e27c85117bd45af097d535954b90b3c5f54cae9612b16a1208ab6d26c5b996ab`。

本页没有读取、输入或保存真实密钥；是否已经保存不能由离线测试得出，需用户执行一次保存命令。此次凭据便利改动未新增任何真实请求、求解或作业提交，也不改变已有完整流程尚待验收的结论。
