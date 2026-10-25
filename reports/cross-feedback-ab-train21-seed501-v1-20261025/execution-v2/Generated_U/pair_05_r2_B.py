def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    ready_dispersion = machine_ready_std / (0.05 + machine_ready_mean + machine_ready_std)
    work_weight = 1.0 + work_dispersion
    efficiency_weight = 1.0 + progress + ready_dispersion
    if candidate_pair_ratio > 0.85 and remaining_work_std < 0.08 and (machine_ready_std < 0.08):
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0))
    else:
        return (1, (work_weight, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, efficiency_weight))
