def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    previous_signal = 0.5
    if previous_heuristic == 0:
        previous_signal = 0.6
    if previous_heuristic == 1:
        previous_signal = 0.4
    alpha = 0.12 * progress + 0.12 * candidate_pair_ratio + 0.16 * remaining_work_mean + 0.12 * (1.0 - 2.0 * remaining_work_std) + 0.12 * (1.0 - machine_ready_mean) + 0.1 * (1.0 - 2.0 * machine_ready_std) + 0.26 * previous_signal
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
