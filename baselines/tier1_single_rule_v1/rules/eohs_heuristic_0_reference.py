
import math

def priority(processing_time: float, remaining_work: float, remaining_operations: int, job_ready_time: float, machine_ready_time: float, earliest_start: float, earliest_finish: float) -> float:
    """返回当前可行的一个操作-机器对的有限优先级。

    数值越高表示该对越早被选择。固定调度器负责处理
    先后顺序、机器分配和时间表构建。
    """
    eps = 1e-9

    ops = max(1.0, float(remaining_operations))
    rem = max(0.0, float(remaining_work))
    pt = max(0.0, float(processing_time))

    avg_remaining = rem / ops

    # 紧急程度：剩余平均工作量越大，作业优先级越高，
    # 但会平滑放缩，避免极大作业绝对占优。
    urgency = (avg_remaining + pt) / (1.0 + avg_remaining + pt)

    # 时间紧凑性：优先选择最早开始和最早完成时间接近
    # 所需资源就绪时刻的候选对，从而减少可避免的空闲。
    resource_gap = abs(job_ready_time - machine_ready_time)
    start_delay = max(0.0, earliest_start - max(job_ready_time, machine_ready_time))
    finish_horizon = max(0.0, earliest_finish)

    # 机器时钟匹配：惩罚相对于作业而言非常晚的机器，
    # 并惩罚将一个已就绪机器延迟给一个晚到作业的情况。
    machine_fit = 1.0 / (1.0 + machine_ready_time + resource_gap)
    job_fit = 1.0 / (1.0 + job_ready_time + resource_gap)

    # 瓶颈缓解：在当前可用资源上处理更短时间是有利的，
    # 但前提是不留下过多的后续剩余工作。
    bottleneck_relief = 1.0 / (1.0 + pt + start_delay)
    tail_balance = (remaining_work - pt) / (remaining_work + eps)
    tail_balance = max(0.0, min(1.0, tail_balance))

    # 采用几何式组合，通过非负因子的乘积进行权衡。
    # 这会产生与加法规则不同的乘法式折中。
    factor_a = 1.0 + urgency
    factor_b = 1.0 + machine_fit + job_fit
    factor_c = 1.0 + bottleneck_relief + tail_balance
    timing_penalty = 1.0 + start_delay + finish_horizon

    score = (factor_a * factor_b * factor_c) / timing_penalty

    # 一个小的加性同分决胜因子，偏向更早完成而不改变主排序。
    score += 0.01 / (1.0 + finish_horizon)

    if score != score or score in (float("inf"), float("-inf")):
        return 0.0
    return float(score)

