def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    dispersion = remaining_work_std / (1.0 + remaining_work_mean)
    q0 = 1.0 - progress
    q1 = progress + 2.0 * dispersion * dispersion
    if previous_heuristic == 1:
        q1 = q1 + 0.05
    return (0, (q0, q1, -2))
