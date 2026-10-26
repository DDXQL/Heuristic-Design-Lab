def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    workload_dispersion = remaining_work_std / (1.0 + remaining_work_mean)
    readiness_dispersion = machine_ready_std / (1.0 + machine_ready_mean)
    alpha = max(0.0, min(1.0, 0.5 + workload_dispersion - readiness_dispersion))
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
