def select_heuristic(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    if previous_heuristic == -1:
        return 0

    if machine_ready_std > 0.5 * machine_ready_mean:
        if machine_ready_std > 0.25 * remaining_work_mean:
            return 9

    if progress >= 0.7:
        if candidate_pair_ratio < 0.35:
            if remaining_work_std <= 0.35 * remaining_work_mean:
                return 3

    return 0
