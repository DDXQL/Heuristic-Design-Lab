def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    readiness_dispersion = machine_ready_std / (machine_ready_mean + machine_ready_std + remaining_work_mean)
    workload_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    weight_8 = 0.15 + 0.55 * readiness_dispersion - 0.1 * workload_dispersion
    weight_5 = 1.0 - weight_8
    return (1, (0.0, 0.0, 0.0, 0.0, 0.0, weight_5, 0.0, 0.0, weight_8, 0.0))
