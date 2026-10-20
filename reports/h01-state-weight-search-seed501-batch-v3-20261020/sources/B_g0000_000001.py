def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    ready_dispersion = machine_ready_std / (machine_ready_mean + machine_ready_std + remaining_work_mean)
    alpha = 0.5 + 0.25 * (1.0 - progress) + 0.15 * work_dispersion - 0.1 * ready_dispersion
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
