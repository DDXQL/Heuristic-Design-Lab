def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    signal = 0.5
    signal = signal + 0.9 * remaining_work_mean
    signal = signal + 0.2 * remaining_work_std
    signal = signal + 0.1 * candidate_pair_ratio
    signal = signal - 0.6 * progress
    signal = signal - 0.5 * machine_ready_mean
    signal = signal - 0.1 * machine_ready_std
    signal = min(1.0, max(0.0, signal))
    alpha = 0.25 + 0.5 * signal
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
