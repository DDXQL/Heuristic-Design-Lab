def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    readiness_pressure = machine_ready_std / (remaining_work_mean + machine_ready_std)
    s0 = 0.5 + 0.5 * work_dispersion
    s9 = 0.25 + 0.4 * candidate_pair_ratio + 0.6 * readiness_pressure
    if previous_heuristic == 0:
        s0 = s0 + 0.03
    if previous_heuristic == 9:
        s9 = s9 + 0.03
    return (0, (s0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, s9))
