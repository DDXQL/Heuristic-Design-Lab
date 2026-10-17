def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    machine_dispersion = 0.0
    machine_scale = machine_ready_mean + machine_ready_std
    if machine_scale > 0.0:
        machine_dispersion = machine_ready_std / machine_scale
    weight0 = 0.55 + 0.25 * work_dispersion - 0.2 * machine_dispersion - 0.15 * progress
    if previous_heuristic == 0:
        weight0 = weight0 + 0.03
    if previous_heuristic == 9:
        weight0 = weight0 - 0.03
    weight9 = 1.0 - weight0
    return (1, (weight0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, weight9))
