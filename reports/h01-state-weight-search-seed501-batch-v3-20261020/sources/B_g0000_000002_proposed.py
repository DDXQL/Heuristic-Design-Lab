def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    early_alpha = 0.5 + 0.25 * dispersion
    late_alpha = 0.25 + 0.5 * dispersion
    alpha = (1.0 - progress) * early_alpha + progress * late_alpha
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
