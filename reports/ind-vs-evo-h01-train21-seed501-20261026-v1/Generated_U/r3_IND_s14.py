def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (1.0 + remaining_work_mean)
    machine_dispersion = machine_ready_std / (1.0 + machine_ready_mean)
    previous_signal = 0.5
    if previous_heuristic == 0:
        previous_signal = 1.0
    elif previous_heuristic == 1:
        previous_signal = 0.0
    alpha = 0.22 * progress + 0.18 * candidate_pair_ratio + 0.16 * remaining_work_mean + 0.1 * (1.0 - work_dispersion) + 0.12 * machine_ready_mean + 0.1 * (1.0 - machine_dispersion) + 0.12 * previous_signal
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
