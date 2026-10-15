def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_fraction = remaining_work_std * remaining_work_std / (0.01 + remaining_work_mean * (1.0 - remaining_work_mean))
    ready_fraction = machine_ready_std * machine_ready_std / (0.01 + machine_ready_mean * (1.0 - machine_ready_mean))
    ready_share = machine_ready_mean / (0.01 + machine_ready_mean + remaining_work_mean)
    availability = candidate_pair_ratio * (1.0 - progress)
    score4 = 0.45 + 0.15 * availability - 0.15 * progress
    score2 = 0.15 + 0.4 * work_fraction + 0.15 * ready_fraction + 0.15 * progress
    score9 = 0.1 + 0.35 * ready_share + 0.3 * ready_fraction + 0.2 * availability - 0.15 * work_fraction
    if previous_heuristic == 4:
        score4 = score4 + 0.04
    elif previous_heuristic == 2:
        score2 = score2 + 0.04
    elif previous_heuristic == 9:
        score9 = score9 + 0.04
    return (0, (-1.0, -1.0, score2, -1.0, score4, -1.0, -1.0, -1.0, -1.0, score9))
