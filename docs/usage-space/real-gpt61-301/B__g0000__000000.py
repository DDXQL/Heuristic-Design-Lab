def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_fraction = remaining_work_std * remaining_work_std / (0.01 + remaining_work_mean * (1.0 - remaining_work_mean))
    ready_fraction = machine_ready_std * machine_ready_std / (0.01 + machine_ready_mean * (1.0 - machine_ready_mean))
    readiness_balance = (machine_ready_mean - remaining_work_mean) / (0.01 + machine_ready_mean + remaining_work_mean)
    weight9 = 0.3 + 0.25 * (ready_fraction - work_fraction) + 0.15 * readiness_balance + 0.15 * progress + 0.1 * (1.0 - candidate_pair_ratio)
    if previous_heuristic == 4:
        weight9 = weight9 - 0.03
    elif previous_heuristic == 9:
        weight9 = weight9 + 0.03
    weight9 = min(0.8, max(0.15, weight9))
    weight4 = 1.0 - weight9
    return (1, (0.0, 0.0, 0.0, 0.0, weight4, 0.0, 0.0, 0.0, 0.0, weight9))
