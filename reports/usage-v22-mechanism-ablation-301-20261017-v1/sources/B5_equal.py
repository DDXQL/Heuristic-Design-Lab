def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std + 1e-06)
    ready_dispersion = machine_ready_std / (machine_ready_mean + machine_ready_std + 1e-06)
    work_weight = 0.65 + 0.35 * work_dispersion
    efficiency_weight = 0.35 + 0.35 * ready_dispersion + 0.3 * progress
    ablationWeight0 = work_weight
    ablationWeight1 = 0.0
    ablationWeight2 = 0.0
    ablationWeight3 = 0.0
    ablationWeight4 = 0.0
    ablationWeight5 = 0.0
    ablationWeight6 = 0.0
    ablationWeight7 = 0.0
    ablationWeight8 = 0.0
    ablationWeight9 = efficiency_weight
    return (1, (1.0 if ablationWeight0 > 0.0 else 0.0, 1.0 if ablationWeight1 > 0.0 else 0.0, 1.0 if ablationWeight2 > 0.0 else 0.0, 1.0 if ablationWeight3 > 0.0 else 0.0, 1.0 if ablationWeight4 > 0.0 else 0.0, 1.0 if ablationWeight5 > 0.0 else 0.0, 1.0 if ablationWeight6 > 0.0 else 0.0, 1.0 if ablationWeight7 > 0.0 else 0.0, 1.0 if ablationWeight8 > 0.0 else 0.0, 1.0 if ablationWeight9 > 0.0 else 0.0))
