
import math

def priority(processing_time: float, remaining_work: float, remaining_operations: int, job_ready_time: float, machine_ready_time: float, earliest_start: float, earliest_finish: float) -> float:
    """Return a finite priority for one currently eligible operation-machine pair.

    Higher means this pair is chosen earlier. The fixed scheduler handles
    precedence, machine assignment and schedule construction.
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

