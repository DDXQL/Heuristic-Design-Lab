def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    alpha = 0.1
    alpha = alpha + 0.35 * remaining_work_mean
    alpha = alpha + 0.2 * (1.0 - progress)
    alpha = alpha + 0.15 * (1.0 - machine_ready_mean)
    alpha = alpha + 0.2 * remaining_work_std
    if alpha < 0.0:
        alpha = 0.0
    if alpha > 1.0:
        alpha = 1.0
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
