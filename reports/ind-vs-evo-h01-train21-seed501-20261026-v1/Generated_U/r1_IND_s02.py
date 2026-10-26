def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    alpha = 0.45
    alpha = alpha + 0.18 * remaining_work_mean
    alpha = alpha + 0.1 * remaining_work_std
    alpha = alpha - 0.12 * progress
    alpha = alpha + 0.08 * machine_ready_std
    alpha = alpha - 0.06 * machine_ready_mean
    alpha = alpha + 0.05 * candidate_pair_ratio
    if previous_heuristic == 0:
        alpha = alpha + 0.04
    if previous_heuristic == 1:
        alpha = alpha - 0.04
    alpha = min(1.0, max(0.0, alpha))
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
