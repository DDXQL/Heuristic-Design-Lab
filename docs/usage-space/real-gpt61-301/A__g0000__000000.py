def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_fraction = remaining_work_std * remaining_work_std / (0.01 + remaining_work_mean * (1.0 - remaining_work_mean))
    ready_fraction = machine_ready_std * machine_ready_std / (0.01 + machine_ready_mean * (1.0 - machine_ready_mean))
    score4 = 0.35
    score9 = 0.12 + 0.5 * ready_fraction - 0.2 * work_fraction + 0.18 * progress + 0.08 * progress * candidate_pair_ratio
    if previous_heuristic == 4:
        score4 = score4 + 0.025
    elif previous_heuristic == 9:
        score9 = score9 + 0.025
    return (0, (-1.0, -1.0, -1.0, -1.0, score4, -1.0, -1.0, -1.0, -1.0, score9))
