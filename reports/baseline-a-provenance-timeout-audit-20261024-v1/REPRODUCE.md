# 只读审计复现

工作区：`FJSP-Heuristic-Research-h-usage-space`，起点提交 `7fa0ff2`。

在仓库根目录运行：

```bash
.venv/bin/python -B reports/baseline-a-provenance-timeout-audit-20261024-v1/audit.py
git diff --exit-code 7fa0ff2 -- code tools experiments docs runs
```

第一条仅读取报告指定的历史记录、源码和限定路径Git历史，重写本审计目录的派生JSON/CSV。不导入评价入口，不编译或执行H，不调用排程器；原始`.fjsp`打开和网络访问均由审计钩子拒绝，写入范围限制在本审计目录。第二条只检查冻结科研路径没有被本次审计修改。中文报告和补测草案为人工整理文档，不会由脚本自动改写。

需要原工作区的未跟踪运行证据以及相邻`EoH-S`源码；单独克隆Git、没有历史runs时不能仅靠CSV重建证据。读取输入的路径、长度和SHA256见`Source_manifest.json`，脚本结尾复核读取过的输入未发生变化。`Historical_source_identity.json`单独记录未恢复的原始源码版本，不将当前源码等同于历史源码。

必须使用仓库Python **3.12.10**。原候选代码键依赖该版本的`ast.dump`格式；系统Python3.13会省略部分空字段，产生不同字符串摘要，不能据此判定H被篡改。审计脚本已显式拒绝非3.12运行环境。描述性成本分位数使用排序后线性插值，不作统计推断。

`Supplemental_protocol_DRAFT.json`没有执行命令，明确未获本轮执行授权；本目录不存在正式求解入口。

复核输出应为：10个成员、20次父代选择及两代生存选择匹配、841条新增策略成功实例成本、6项超时；本轮新增求解0、API请求0、守卫违规0。
