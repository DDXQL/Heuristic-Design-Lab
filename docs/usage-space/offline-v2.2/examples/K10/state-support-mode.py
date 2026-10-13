def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    if previous_heuristic == -1:
        return (0, (0, 0, 1, 0, 0, 0, 0, 0, 0, 0))
    spread = machine_ready_std / (1.0 + machine_ready_mean)
    if progress < 0.5:
        return (1, (1.0 + spread, 1.0 - spread, 0, 0, 0, 0, 0, 0, 0, 0))
    return (1, (0, 1.0 + spread, 1.0 - spread, 0, 0, 0, 0, 0, 0, 0))
