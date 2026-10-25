def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    if previous_heuristic == -1:
        return (1, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0))
    if machine_ready_std > 0.125:
        return (1, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0 + machine_ready_std + candidate_pair_ratio, 1.0 + progress + machine_ready_std))
    if remaining_work_std > 0.125:
        work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
        ready_dispersion = machine_ready_std / (0.05 + machine_ready_mean + machine_ready_std)
        return (1, (1.0 + work_dispersion, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0 + progress + ready_dispersion))
    if remaining_work_mean > 0.25:
        return (1, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0 + remaining_work_mean, 0.0, 0.0, 1.0 + candidate_pair_ratio + progress))
    return (1, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
