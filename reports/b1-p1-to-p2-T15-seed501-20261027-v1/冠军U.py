def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    ready_dispersion = machine_ready_std / (0.05 + machine_ready_mean + machine_ready_std)
    transition = progress + 0.5 * (1.0 - candidate_pair_ratio)
    work_weight = 1.0 + work_dispersion
    efficiency_weight = 1.0 + progress + ready_dispersion
    if previous_heuristic == -1:
        return (1, (work_weight, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, efficiency_weight, 0.0))
    if candidate_pair_ratio < 0.5 and remaining_work_mean < 0.25:
        return (0, (0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    if remaining_work_std > 0.2 and machine_ready_std < 0.1:
        return (0, (0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    if progress > 0.75 and machine_ready_mean > 0.25:
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
    if transition >= 0.75:
        return (1, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, work_weight, efficiency_weight))
    if machine_ready_std > 0.1:
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0))
    return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0))
