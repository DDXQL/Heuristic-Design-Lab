def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_fraction = remaining_work_std * remaining_work_std / (0.01 + remaining_work_mean * (1.0 - remaining_work_mean))
    ready_fraction = machine_ready_std * machine_ready_std / (0.01 + machine_ready_mean * (1.0 - machine_ready_mean))
    readiness_share = machine_ready_mean / (0.01 + machine_ready_mean + remaining_work_mean)
    dispersion_contrast = ready_fraction - work_fraction
    score4 = 0.3 + 0.15 * (1.0 - progress) + 0.1 * work_fraction
    score2 = 0.1 + 0.4 * readiness_share + 0.1 * progress - 0.15 * ready_fraction
    score7 = 0.12 + 0.35 * dispersion_contrast + 0.15 * candidate_pair_ratio + 0.1 * progress
    if previous_heuristic == 4:
        score4 = score4 + 0.04
    elif previous_heuristic == 2:
        score2 = score2 + 0.04
    elif previous_heuristic == 7:
        score7 = score7 + 0.04
    return (0, (-2.0, -2.0, score2, -2.0, score4, -2.0, -2.0, score7, -2.0, -2.0))
