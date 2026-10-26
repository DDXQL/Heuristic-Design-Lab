def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    signal = 0.3 * (2.0 * remaining_work_mean - 1.0)
    signal = signal + 0.2 * remaining_work_std
    signal = signal + 0.15 * (2.0 * progress - 1.0)
    signal = signal - 0.15 * candidate_pair_ratio
    signal = signal - 0.1 * machine_ready_mean
    signal = signal - 0.05 * machine_ready_std
    if previous_heuristic == 0:
        signal = signal + 0.025
    if previous_heuristic == 1:
        signal = signal - 0.025
    alpha = min(1.0, max(0.0, 0.5 + signal))
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
