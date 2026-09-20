
import math

def priority(processing_time: float, remaining_work: float, remaining_operations: int, job_ready_time: float, machine_ready_time: float, earliest_start: float, earliest_finish: float) -> float:
    """Return a finite priority for one currently eligible operation-machine pair.

    Higher means this pair is chosen earlier. The fixed scheduler handles
    precedence, machine assignment and schedule construction.
    """
    eps = 1e-9

    # Factor 1: quickly finish this operation.
    short_proc = 1.0 / (processing_time + 1.0)

    # Factor 2: prefer jobs with substantial remaining workload per operation.
    remaining_intensity = (remaining_work + 1.0) / (remaining_operations + 1.0)

    # Factor 3: prefer earlier availability and completion.
    early_start = 1.0 / (earliest_start + 1.0)
    early_finish = 1.0 / (earliest_finish + 1.0)

    # Factor 4: mild reward for using a machine/job alignment that does not
    # introduce unnecessary waiting beyond readiness.
    readiness = max(job_ready_time, machine_ready_time)
    idle_gap = max(0.0, earliest_start - readiness)
    alignment = 1.0 / (1.0 + idle_gap)

    # Multiplicative form, structurally different from weighted additive rules.
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

