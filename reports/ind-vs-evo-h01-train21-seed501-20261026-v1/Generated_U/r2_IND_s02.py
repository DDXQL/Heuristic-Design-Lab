def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    signal = 0.4 * (progress - 0.5)
    signal = signal + 0.3 * (candidate_pair_ratio - 0.5)
    signal = signal + 0.6 * (remaining_work_mean - 0.5)
    signal = signal - 0.4 * remaining_work_std
    signal = signal + 0.3 * (machine_ready_mean - 0.5)
    signal = signal - 0.2 * machine_ready_std
    if previous_heuristic == 0:
        signal = signal + 0.05
    if previous_heuristic == 1:
        signal = signal - 0.05
    alpha = max(0.0, min(1.0, 0.5 + signal))
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
