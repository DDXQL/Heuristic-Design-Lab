def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (1.0 + remaining_work_mean)
    machine_dispersion = machine_ready_std / (1.0 + machine_ready_mean)
    alpha = 0.5 + 0.5 * (work_dispersion - machine_dispersion)
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
