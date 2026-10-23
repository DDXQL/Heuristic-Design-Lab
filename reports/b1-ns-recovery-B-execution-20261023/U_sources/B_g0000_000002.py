def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    ready_dispersion = machine_ready_std / (0.05 + machine_ready_mean + machine_ready_std)
    work_signal = (1.0 - progress) * work_dispersion
    efficiency_signal = 0.5 * (progress + ready_dispersion)
    if work_signal > efficiency_signal:
        partner_weight = 0.25 + 0.75 * work_signal
        return (1, (partner_weight, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0))
    else:
        partner_weight = 0.25 + 0.75 * efficiency_signal
        return (1, (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, partner_weight))
