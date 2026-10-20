def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (
        remaining_work_mean + remaining_work_std
    )
    ready_dispersion = machine_ready_std / (
        machine_ready_mean + machine_ready_std + remaining_work_mean
    )
    h0_preference = (
        0.5
        + 0.5 * work_dispersion
        - 0.25 * ready_dispersion
        - 0.25 * progress
    )
    h0_preference = min(1.0, max(0.0, h0_preference))
    alpha = 0.25 + 0.5 * h0_preference
    return (1, (alpha, 1.0-alpha, 0, 0, 0, 0, 0, 0, 0, 0))
