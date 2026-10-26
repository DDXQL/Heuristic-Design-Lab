def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    alpha = 0.5
    alpha = alpha + 0.16 * (0.5 - progress)
    alpha = alpha + 0.22 * (remaining_work_mean - 0.5)
    alpha = alpha + 0.18 * remaining_work_std
    alpha = alpha + 0.12 * (0.5 - candidate_pair_ratio)
    alpha = alpha - 0.12 * (machine_ready_mean - 0.5)
    alpha = alpha - 0.16 * machine_ready_std
    if previous_heuristic == 0:
        alpha = alpha + 0.03
    if previous_heuristic == 1:
        alpha = alpha - 0.03
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
