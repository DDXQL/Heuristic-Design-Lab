def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    ready_dispersion = machine_ready_std / (0.05 + machine_ready_mean + machine_ready_std)
    if candidate_pair_ratio >= 0.75 and work_dispersion <= 0.2 and (ready_dispersion <= 0.2):
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0))
    work_weight = 1.0 + work_dispersion
    efficiency_weight = 1.0 + progress + ready_dispersion
    return (1, (work_weight, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, efficiency_weight))
