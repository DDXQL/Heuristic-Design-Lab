def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    ready_dispersion = machine_ready_std / (machine_ready_mean + machine_ready_std + remaining_work_mean)
    h1_adjustment = (1.0 - work_dispersion) * (
        0.20 * progress + 0.10 * ready_dispersion
    )
    alpha = 0.50 + 0.30 * work_dispersion - h1_adjustment
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
