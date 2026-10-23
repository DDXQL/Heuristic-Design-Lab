def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    if previous_heuristic == -1:
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0))
    if machine_ready_std > 0.2:
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0))
    if remaining_work_std > 0.2:
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0))
    weight_9 = min(1.0, max(progress / 0.75, (1.0 - candidate_pair_ratio) / 0.65))
    weight_8 = 1.0 - weight_9
    return (1, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, weight_8, weight_9))
