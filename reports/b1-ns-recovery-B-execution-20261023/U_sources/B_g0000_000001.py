def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (0.01 + remaining_work_mean + remaining_work_std)
    ready_dispersion = machine_ready_std / (0.01 + machine_ready_mean + machine_ready_std)
    if candidate_pair_ratio < 0.5 and remaining_work_mean < 0.25:
        finish_weight = 0.25 + 0.35 * progress * (1.0 - candidate_pair_ratio)
        return (1, (0.0, finish_weight, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0 - finish_weight))
    if ready_dispersion > work_dispersion:
        efficiency_weight = 0.35 + 0.3 * (ready_dispersion - work_dispersion)
        return (1, (0.0, 0.0, 0.0, 0.0, 0.0, 1.0 - efficiency_weight, 0.0, 0.0, efficiency_weight, 0.0))
    wait_weight = 0.2 + 0.4 * progress + 0.15 * ready_dispersion
    return (1, (0.0, 0.0, 0.0, 0.0, 0.0, 1.0 - wait_weight, 0.0, 0.0, 0.0, wait_weight))
