def select_heuristic(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    level = (progress + candidate_pair_ratio + remaining_work_mean + remaining_work_std + machine_ready_mean + machine_ready_std) / 6.0
    if level < 0.2:
        return 0
    elif level < 0.36:
        return 2
    elif level < 0.52:
        return 4
    else:
        return 7
