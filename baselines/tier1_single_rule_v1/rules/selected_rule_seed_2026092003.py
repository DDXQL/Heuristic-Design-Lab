
import math

def priority(processing_time: float, remaining_work: float, remaining_operations: int, job_ready_time: float, machine_ready_time: float, earliest_start: float, earliest_finish: float) -> float:
    """返回当前可行的一个操作-机器对的有限优先级。

    数值越高表示该对越早被选择。固定调度器负责处理
    先后顺序、机器分配和时间表构建。
    """
    eps = 1e-9

    # 因子 1：尽快完成该操作。
    short_proc = 1.0 / (processing_time + 1.0)

    # 因子 2：优先选择每个操作剩余工作量较大的作业。
    remaining_intensity = (remaining_work + 1.0) / (remaining_operations + 1.0)

    # 因子 3：优先考虑更早可用和更早完成。
    early_start = 1.0 / (earliest_start + 1.0)
    early_finish = 1.0 / (earliest_finish + 1.0)

    # 因子 4：轻微奖励使用不会引入超出就绪状态所需的额外等待的机器/作业匹配。
    readiness = max(job_ready_time, machine_ready_time)
    idle_gap = max(0.0, earliest_start - readiness)
    alignment = 1.0 / (1.0 + idle_gap)

    # 乘积形式，与加权加法规则结构不同。
    score = (
        (short_proc + eps)
        * (remaining_intensity + eps)
        * (early_start + eps)
        * (early_finish + eps)
        * (alignment + eps)
    )

    if score != score or score in (float("inf"), float("-inf")):
        return 0.0
    return float(score)

