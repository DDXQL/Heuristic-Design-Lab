def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    alpha = 0.5
    alpha = alpha + 0.1 * (progress - 0.5)
    alpha = alpha + 0.08 * (candidate_pair_ratio - 0.5)
    alpha = alpha - 0.12 * (remaining_work_mean - 0.5)
    alpha = alpha + 0.06 * remaining_work_std
    alpha = alpha - 0.08 * (machine_ready_mean - 0.5)
    alpha = alpha + 0.04 * machine_ready_std
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
