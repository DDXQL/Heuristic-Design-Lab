def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    relative_work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    backlog_emphasis = (1.0 - progress) * relative_work_dispersion
    alpha = 0.25 + 0.5 * backlog_emphasis
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
