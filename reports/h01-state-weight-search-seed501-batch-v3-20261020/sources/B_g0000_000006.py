def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    alpha = 0.5 + 0.25 * dispersion
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
