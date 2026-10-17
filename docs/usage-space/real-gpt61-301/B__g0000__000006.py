def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    ready_dispersion = machine_ready_std / (remaining_work_mean + machine_ready_mean + machine_ready_std)
    criticality_weight = 0.65 - 0.35 * progress + 0.2 * work_dispersion - 0.15 * ready_dispersion
    efficiency_weight = 1.0 - criticality_weight
    return (1, (criticality_weight, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, efficiency_weight))
