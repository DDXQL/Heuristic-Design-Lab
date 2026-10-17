def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std + 1e-06)
    ready_dispersion = machine_ready_std / (machine_ready_mean + machine_ready_std + 1e-06)
    work_weight = 0.65 + 0.35 * work_dispersion
    efficiency_weight = 0.35 + 0.35 * ready_dispersion + 0.3 * progress
    return (0, (work_weight, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, efficiency_weight))
