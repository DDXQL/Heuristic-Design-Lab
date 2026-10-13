def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    r0 = 3.0 - 2.0 * progress
    r1 = 2.0 + 2.0 * progress
    return (1, (r0, r1, 0, 0, 0, 0, 0, 0, 0, 0))
