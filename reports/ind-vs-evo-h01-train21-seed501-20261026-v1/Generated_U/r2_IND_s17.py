def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    alpha = 0.5
    alpha = alpha + 0.25 * (remaining_work_mean - machine_ready_mean)
    alpha = alpha + 0.1 * (remaining_work_std - machine_ready_std)
    alpha = alpha + 0.05 * (candidate_pair_ratio - progress)
    if previous_heuristic == 0:
        alpha = alpha + 0.05
    if previous_heuristic == 1:
        alpha = alpha - 0.05
    alpha = min(1.0, max(0.0, alpha))
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
