# Baseline-A Supplemental T30 独立协议

基于df28b3d。原H排名编号保留，train21/seed501/未取整LB/Fitness/合法动作/同分/单H原始评分与双H独立minmax等权WS全部不变。无LLM/API/演化/holdout入口。

固定顺序：H0/H1、H0/H4、H4/H5、H0、H4/H6、H4/H7、H0/H3、H5/H6、H5/H7。每项21实例，首解复检各一次，189项/378遍封顶；不抵扣缓存、不重复、不加时。

草案审阅后的工程变化：旧poll/recv不是完整消息硬期限，新独立版本由reader线程执行recv，控制线程最多等30秒，包含反序列化；迟到行不接受。两次求解、记录与该实例结果交付共享期限；首项含子进程启动；最后after身份证据在发送末行前完成。接收线程超时后终止子进程并确认reader停止，未知reader/进程终态停止。OS调度及终止/留证不承诺在第30.000秒瞬间完成；未接受迟到成绩。

全部结果收齐后另等2秒exit0，期间不再收成绩。失败清理维持0.05秒join、terminate/0.5、必要时kill/0.5。成功完整21项、首解复检结构及物理排程一致、before/after加载身份匹配、源码清单不变、PID和终态正常。明确超时signal终止可记录Fitness=null并继续独立策略；其他错误、身份、历史结果差异、未知reservation或预算问题持久化Stop，禁止自动重试。

每策略启动前预留21/42；completed结果含SHA，恢复逐项复核跳过；reserved/孤立evidence不自动补记或重跑。保存阶段时刻、成本、两遍排程哈希，不增加诊断求解。全部原Baseline-A run/report及df28b3d审计文件哈希受新协议保护，不回填旧null。所有历史共同成功实例在继续下个策略之前比较Cmax/LB/score及可比指纹。

accept只运行合成消息进程、toy回归和已存H01矩阵离线重放；通过后prepare创建唯一新目录，冻结源码/数据/清单/预算及协议SHA。prepare不求解；只有run启动正式train21评价。report从存档计算，无求解。
