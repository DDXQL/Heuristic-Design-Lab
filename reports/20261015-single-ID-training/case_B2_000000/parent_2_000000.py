def select_heuristic(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    if progress < 0.5:
        if candidate_pair_ratio < 0.5:
            return 3
        return 6
    if machine_ready_mean > remaining_work_mean:
        if machine_ready_std > remaining_work_std:
            return 8
        return 1
    if remaining_work_std > machine_ready_std:
        return 5
    return 9
