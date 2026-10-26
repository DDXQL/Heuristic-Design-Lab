def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    q = 0.3 * progress
    q = q + 0.2 * (1.0 - candidate_pair_ratio)
    q = q + 0.2 * remaining_work_mean
    q = q + 0.1 * (2.0 * remaining_work_std)
    q = q + 0.1 * machine_ready_mean
    q = q + 0.1 * (2.0 * machine_ready_std)
    alpha = 0.25 + 0.5 * q
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
