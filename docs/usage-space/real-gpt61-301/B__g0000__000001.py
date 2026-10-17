def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_fraction = remaining_work_std * remaining_work_std / (0.01 + remaining_work_mean * (1.0 - remaining_work_mean))
    ready_fraction = machine_ready_std * machine_ready_std / (0.01 + machine_ready_mean * (1.0 - machine_ready_mean))
    availability = candidate_pair_ratio * (1.0 - progress)
    contrast = ready_fraction - work_fraction + 0.15 * (availability - 0.5) + 0.2 * (progress - 0.5)
    if previous_heuristic == 2:
        contrast = contrast + 0.04
    elif previous_heuristic == 7:
        contrast = contrast - 0.04
    companion_weight = 0.25 + 0.5 * progress + 0.25 * ready_fraction
    if contrast >= 0.0:
        return (1, (0.0, 0.0, companion_weight, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    else:
        return (1, (0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, companion_weight, 0.0, 0.0))
