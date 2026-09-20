
import math

def priority(processing_time: float, remaining_work: float, remaining_operations: int, job_ready_time: float, machine_ready_time: float, earliest_start: float, earliest_finish: float) -> float:
    """Return a finite priority for one currently eligible operation-machine pair.

    Higher means this pair is chosen earlier. The fixed scheduler handles
    precedence, machine assignment and schedule construction.
    """
    eps = 1e-9

    ops = max(1.0, float(remaining_operations))
    rem = max(0.0, float(remaining_work))
    pt = max(0.0, float(processing_time))

    avg_remaining = rem / ops

    # Urgency pressure: job with more remaining average work gets higher priority,
    # but scaled smoothly and tempered so huge jobs do not dominate absolutely.
    urgency = (avg_remaining + pt) / (1.0 + avg_remaining + pt)

    # Timing compactness: prefer pairs whose earliest start and finish are close
    # to the moment the necessary resources become ready, reducing avoidable slack.
    resource_gap = abs(job_ready_time - machine_ready_time)
    start_delay = max(0.0, earliest_start - max(job_ready_time, machine_ready_time))
    finish_horizon = max(0.0, earliest_finish)

    # Machine-clock fit: penalize using a machine that is very late relative to the job,
    # and penalize delaying an already-ready machine with a late job.
    machine_fit = 1.0 / (1.0 + machine_ready_time + resource_gap)
    job_fit = 1.0 / (1.0 + job_ready_time + resource_gap)

    # Bottleneck relief: shorter processing on currently available resources is good,
    # but only when it does not leave excessive downstream remaining work.
    bottleneck_relief = 1.0 / (1.0 + pt + start_delay)
    tail_balance = (remaining_work - pt) / (remaining_work + eps)
    tail_balance = max(0.0, min(1.0, tail_balance))

    # Geometric-style combination via products of nonnegative factors.
    # This creates multiplicative trade-offs unlike the additive rules above.
    factor_a = 1.0 + urgency
    factor_b = 1.0 + machine_fit + job_fit
    factor_c = 1.0 + bottleneck_relief + tail_balance
    timing_penalty = 1.0 + start_delay + finish_horizon

    score = (factor_a * factor_b * factor_c) / timing_penalty

    # Small additive tie-breaker favoring earlier finish without changing main ordering.
    score += 0.01 / (1.0 + finish_horizon)

    if score != score or score in (float("inf"), float("-inf")):
        return 0.0
    return float(score)

