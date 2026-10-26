def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    previous_is_h0 = 0.0
    previous_is_h1 = 0.0
    if previous_heuristic == 0:
        previous_is_h0 = 1.0
    if previous_heuristic == 1:
        previous_is_h1 = 1.0
    alpha = 0.5
    alpha = alpha + 0.18 * (0.5 - progress)
    alpha = alpha + 0.12 * (candidate_pair_ratio - 0.5)
    alpha = alpha + 0.1 * (remaining_work_mean - 0.5)
    alpha = alpha - 0.08 * remaining_work_std
    alpha = alpha - 0.08 * machine_ready_mean
    alpha = alpha - 0.06 * machine_ready_std
    alpha = alpha + 0.03 * previous_is_h0
    alpha = alpha - 0.03 * previous_is_h1
    alpha = max(0.0, min(1.0, alpha))
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
