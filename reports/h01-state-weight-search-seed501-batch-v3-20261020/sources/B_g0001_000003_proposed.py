def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    ready_dispersion = machine_ready_std / (machine_ready_mean + machine_ready_std + remaining_work_mean)
    h1_shift = (0.2 * progress + 0.1 * ready_dispersion) * (1.0 - work_dispersion)
    alpha = 0.5 + 0.3 * work_dispersion - h1_shift
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
