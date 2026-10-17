def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    readiness_pressure = (machine_ready_mean + machine_ready_std) / (machine_ready_mean + machine_ready_std + remaining_work_mean)
    efficiency_weight = 0.25 + 0.35 * progress + 0.25 * readiness_pressure - 0.15 * work_dispersion
    workload_weight = 1.0 - efficiency_weight
    return (1, (workload_weight, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, efficiency_weight))
