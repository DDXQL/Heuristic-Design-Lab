def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    flexibility = candidate_pair_ratio * (1.0 - progress)
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std + 1e-09)
    ready_dispersion = machine_ready_std / (machine_ready_mean + machine_ready_std + 1e-09)
    readiness_share = machine_ready_mean / (remaining_work_mean + machine_ready_mean + 1e-09)
    weight0 = 0.8 + 0.6 * work_dispersion + 0.3 * flexibility
    weight9 = 0.5 + 0.5 * progress + 0.4 * readiness_share + 0.3 * ready_dispersion
    return (1, (weight0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, weight9))
