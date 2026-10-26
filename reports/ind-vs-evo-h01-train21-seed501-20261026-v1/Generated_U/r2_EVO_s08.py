def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    alpha = 0.4 * progress + 0.8 * remaining_work_mean + 1.2 * remaining_work_std + 0.3 * (1.0 - candidate_pair_ratio) - 0.8 * machine_ready_std
    alpha = max(0.0, min(1.0, alpha))
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
