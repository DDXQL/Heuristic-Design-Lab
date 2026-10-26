def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    alpha = 0.5
    alpha = alpha + 0.28 * remaining_work_mean
    alpha = alpha + 0.1 * progress
    alpha = alpha + 0.12 * remaining_work_std / (1.0 + remaining_work_mean)
    alpha = alpha - 0.2 * machine_ready_mean
    alpha = alpha - 0.1 * machine_ready_std / (1.0 + machine_ready_mean)
    alpha = alpha - 0.08 * candidate_pair_ratio
    if previous_heuristic == 0:
        alpha = alpha + 0.04
    if previous_heuristic == 1:
        alpha = alpha - 0.04
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
