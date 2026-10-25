def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    ready_dispersion = machine_ready_std / (0.05 + machine_ready_mean + machine_ready_std)
    pair_pressure = 1.0 - candidate_pair_ratio
    weight5 = 1.0 + (1.0 - progress) + pair_pressure
    weight9 = 1.0 + progress + work_dispersion + ready_dispersion
    if previous_heuristic == 5:
        weight5 = weight5 + 0.5
    if previous_heuristic == 9:
        weight9 = weight9 + 0.5
    return (1, (0.0, 0.0, 0.0, 0.0, 0.0, weight5, 0.0, 0.0, 0.0, weight9))
