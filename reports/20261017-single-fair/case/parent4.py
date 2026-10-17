def select_heuristic(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    if previous_heuristic == -1:
        if progress < 0.18:
            return 3
        if candidate_pair_ratio < 0.42:
            return 4
        return 5
    if progress < 0.5:
        if remaining_work_std > 0.11:
            return 6
        if machine_ready_std > 0.14:
            return 7
        return 3
    if candidate_pair_ratio < 0.3:
        return 8
    if remaining_work_mean + machine_ready_mean < 0.7:
        return 4
    return 9
