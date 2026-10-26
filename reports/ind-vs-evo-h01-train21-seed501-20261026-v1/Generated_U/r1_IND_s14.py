def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    remaining_dispersion = remaining_work_std / (1.0 + remaining_work_mean)
    machine_dispersion = machine_ready_std / (1.0 + machine_ready_mean)
    alpha = 0.5
    alpha = alpha + 0.18 * remaining_work_mean
    alpha = alpha + 0.12 * remaining_dispersion
    alpha = alpha + 0.1 * progress
    alpha = alpha + 0.06 * candidate_pair_ratio
    alpha = alpha - 0.18 * machine_ready_mean
    alpha = alpha - 0.1 * machine_dispersion
    if previous_heuristic == 0:
        alpha = alpha + 0.04
    if previous_heuristic == 1:
        alpha = alpha - 0.04
    alpha = max(0.0, min(1.0, alpha))
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
