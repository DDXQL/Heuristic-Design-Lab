def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    alpha = 0.5
    alpha = alpha + 0.2 * (1.0 - progress)
    alpha = alpha + 0.15 * remaining_work_mean
    alpha = alpha + 0.1 * remaining_work_std
    alpha = alpha + 0.1 * (1.0 - candidate_pair_ratio)
    alpha = alpha - 0.15 * machine_ready_mean
    alpha = alpha - 0.1 * machine_ready_std
    if previous_heuristic == 0:
        alpha = alpha + 0.03
    if previous_heuristic == 1:
        alpha = alpha - 0.03
    alpha = max(0.0, min(1.0, alpha))
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
