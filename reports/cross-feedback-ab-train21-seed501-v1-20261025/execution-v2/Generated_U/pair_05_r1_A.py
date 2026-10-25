def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    ready_dispersion = machine_ready_std / (0.05 + machine_ready_mean + machine_ready_std)
    instability = work_dispersion + ready_dispersion
    if progress < 0.2 and candidate_pair_ratio > 0.75 and (instability < 0.35):
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0))
    work_weight = 1.0 + work_dispersion
    efficiency_weight = 1.0 + progress + ready_dispersion
    if previous_heuristic == 0:
        work_weight = work_weight + 0.1
    if previous_heuristic == 9:
        efficiency_weight = efficiency_weight + 0.1
    return (1, (work_weight, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, efficiency_weight))
