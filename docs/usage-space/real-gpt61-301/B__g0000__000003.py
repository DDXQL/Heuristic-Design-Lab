def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_fraction = remaining_work_std * remaining_work_std / (0.01 + remaining_work_mean * (1.0 - remaining_work_mean))
    ready_fraction = machine_ready_std * machine_ready_std / (0.01 + machine_ready_mean * (1.0 - machine_ready_mean))
    availability = candidate_pair_ratio * (1.0 - progress)
    contrast = ready_fraction - work_fraction + 0.2 * availability - 0.1 * progress
    secondary_weight = 0.35 + 0.35 * progress + 0.25 * min(1.0, abs(contrast))
    if contrast >= 0.0:
        return (1, (0.0, 0.0, secondary_weight, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    else:
        return (1, (0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, secondary_weight, 0.0, 0.0))
