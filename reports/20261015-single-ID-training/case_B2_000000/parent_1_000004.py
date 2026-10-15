def select_heuristic(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    balance = remaining_work_mean - machine_ready_mean + (remaining_work_std - machine_ready_std)
    flexibility = candidate_pair_ratio * (1.0 - progress)
    phase = progress * (1.0 - progress)
    score = balance + 0.5 * flexibility - 0.25 * phase
    if previous_heuristic == -1:
        if score < -0.2:
            return 2
        elif score < 0.0:
            return 5
        elif score < 0.2:
            return 7
        return 9
    if score < -0.15:
        return 1
    elif score < 0.05:
        return 3
    elif score < 0.25:
        return 6
    return 8
