def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    alpha = 0.5
    alpha = alpha + 0.14 * remaining_work_mean
    alpha = alpha + 0.08 * remaining_work_std
    alpha = alpha - 0.12 * progress
    alpha = alpha - 0.06 * candidate_pair_ratio
    alpha = alpha + 0.05 * machine_ready_std
    alpha = alpha - 0.04 * machine_ready_mean
    if previous_heuristic == 0:
        alpha = alpha + 0.02
    if previous_heuristic == 1:
        alpha = alpha - 0.02
    alpha = max(0.0, min(1.0, alpha))
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
