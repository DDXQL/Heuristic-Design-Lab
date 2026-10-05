
import math

def priority(processing_time: float, remaining_work: float, remaining_operations: int, job_ready_time: float, machine_ready_time: float, earliest_start: float, earliest_finish: float) -> float:
    """返回当前可行的一个操作-机器对的有限优先级。

    数值越高表示该对越早被选择。固定调度器负责处理
    先后顺序、机器分配和时间表构建。
    """
    eps = 1e-9

    work_ratio = remaining_work / (remaining_work + processing_time + eps)
    ops_ratio = remaining_operations / (remaining_operations + 2.0)
    machine_ratio = 1.0 / (1.0 + machine_ready_time + eps)
    ready_ratio = 1.0 / (1.0 + job_ready_time + eps)

    urgency = (
        1.00 * work_ratio
        + 1.10 * ops_ratio
        + 0.45 * machine_ratio
        + 0.65 * ready_ratio
    )

    time_penalty = (
        1.35 * earliest_finish
        + 0.85 * earliest_start
        + 0.20 * processing_time
    )

    return float(urgency - time_penalty)

