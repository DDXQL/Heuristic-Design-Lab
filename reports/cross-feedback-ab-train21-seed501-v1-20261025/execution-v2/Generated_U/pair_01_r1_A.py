def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    if previous_heuristic == -1:
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0))
    if machine_ready_std > 0.125:
        return (1, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0 + 8.0 * machine_ready_std, 1.0 + 4.0 * (1.0 - machine_ready_std)))
    if progress > 0.75 and machine_ready_mean > 0.25:
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
    if candidate_pair_ratio < 0.5 and remaining_work_mean < 0.25:
        return (0, (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    if remaining_work_std > 0.125:
        return (1, (0.0, 0.0, 0.0, 0.0, 1.0 + 4.0 * remaining_work_std + progress, 1.0 + 2.0 * (1.0 - progress), 0.0, 0.0, 0.0, 0.0))
    return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0))
