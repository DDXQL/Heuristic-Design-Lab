def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std + 1e-12)
    ready_dispersion = machine_ready_std / (machine_ready_mean + machine_ready_std + 1e-12)
    s0 = 0.15 + (1.0 - progress) * work_dispersion
    s5 = 0.45
    s9 = 0.15 + 0.7 * ready_dispersion
    if previous_heuristic == 0:
        s0 = s0 + 0.03
    if previous_heuristic == 5:
        s5 = s5 + 0.03
    if previous_heuristic == 9:
        s9 = s9 + 0.03
    return (0, (s0, -1.0, -1.0, -1.0, -1.0, s5, -1.0, -1.0, -1.0, s9))
