def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    gap = remaining_work_mean - machine_ready_mean
    spread = remaining_work_std + machine_ready_std
    flexibility = candidate_pair_ratio * (1.0 - progress)
    phase = progress * candidate_pair_ratio
    s0 = 0.31 + gap - spread + flexibility - phase
    s1 = 0.27 - gap + spread - flexibility + phase
    s2 = 0.22 + gap + spread - 0.5 * flexibility - phase
    s3 = 0.19 - gap - spread + 0.5 * flexibility + phase
    s4 = 0.16 + 0.5 * gap - 0.5 * spread + flexibility + phase
    s5 = 0.14 - 0.5 * gap + 0.5 * spread - flexibility - phase
    s6 = 0.12 + gap - 0.5 * spread + 0.5 * flexibility - phase
    s7 = 0.1 - gap + 0.5 * spread + 0.5 * flexibility + phase
    s8 = 0.08 + 0.5 * gap + spread - 0.5 * flexibility - phase
    s9 = 0.06 - 0.5 * gap - spread + 0.5 * flexibility + phase
    if previous_heuristic == 0:
        s0 = s0 + 0.025
    if previous_heuristic == 1:
        s1 = s1 + 0.025
    if previous_heuristic == 2:
        s2 = s2 + 0.025
    if previous_heuristic == 3:
        s3 = s3 + 0.025
    if previous_heuristic == 4:
        s4 = s4 + 0.025
    if previous_heuristic == 5:
        s5 = s5 + 0.025
    if previous_heuristic == 6:
        s6 = s6 + 0.025
    if previous_heuristic == 7:
        s7 = s7 + 0.025
    if previous_heuristic == 8:
        s8 = s8 + 0.025
    if previous_heuristic == 9:
        s9 = s9 + 0.025
    return (0, (s0, s1, s2, s3, s4, s5, s6, s7, s8, s9))
