
import math

def priority(processing_time: float, remaining_work: float, remaining_operations: int, job_ready_time: float, machine_ready_time: float, earliest_start: float, earliest_finish: float) -> float:
    """Return a finite priority for one currently eligible operation-machine pair.

    Higher means this pair is chosen earlier. The fixed scheduler handles
    precedence, machine assignment and schedule construction.
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

