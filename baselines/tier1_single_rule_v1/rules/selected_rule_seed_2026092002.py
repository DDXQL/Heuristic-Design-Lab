
import math

def priority(processing_time: float, remaining_work: float, remaining_operations: int, job_ready_time: float, machine_ready_time: float, earliest_start: float, earliest_finish: float) -> float:
    """返回当前可行的一个操作-机器对的有限优先级。

    数值越高表示该对越早被选择。固定调度器负责处理
    先后顺序、机器分配和时间表构建。
    """
    eps = 1e-9

    work_density = remaining_work / (remaining_operations + eps)
    speed_factor = 1.0 / (processing_time + eps)
    readiness_gain = 1.0 / (1.0 + earliest_start + job_ready_time + machine_ready_time)
    finish_penalty = 1.0 / (1.0 + earliest_finish)

    return (
        (speed_factor * work_density) ** 0.5
        + remaining_operations * readiness_gain
        + finish_penalty
        - 0.05 * earliest_finish
    )

