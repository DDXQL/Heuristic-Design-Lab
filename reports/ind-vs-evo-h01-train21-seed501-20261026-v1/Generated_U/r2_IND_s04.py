def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    alpha = 0.42 + 0.26 * (1.0 - progress) + 0.16 * remaining_work_mean + 0.08 * remaining_work_std - 0.08 * machine_ready_mean - 0.04 * machine_ready_std - 0.04 * candidate_pair_ratio
    if previous_heuristic == 0:
        alpha = alpha + 0.03
    if previous_heuristic == 1:
        alpha = alpha - 0.03
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
