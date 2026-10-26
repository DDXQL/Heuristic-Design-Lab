def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    alpha = 0.25 + 0.15 * progress + 0.1 * candidate_pair_ratio + 0.1 * remaining_work_mean + 0.05 * remaining_work_std + 0.05 * machine_ready_mean + 0.05 * machine_ready_std
    if previous_heuristic == 0:
        alpha = alpha + 0.03
    if previous_heuristic == 1:
        alpha = alpha - 0.03
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
