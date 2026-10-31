def use_heuristics(state):
    progress = 1.0
    breadth = 0.0
    mean_delta = 0.0
    spread = 0.0
    recent = 0.0
    history = 0
    if state['availability']['construction_progress']:
        progress = state['construction_progress']
    if state['availability']['action_breadth_fraction']:
        breadth = state['action_breadth_fraction']
    if state['availability']['action_delta_mean']:
        mean_delta = state['action_delta_mean']
    if state['availability']['action_delta_std']:
        spread = state['action_delta_std']
    if state['availability']['recent_delta_mean']:
        recent = state['recent_delta_mean']
    if state['availability']['has_history']:
        history = int(state['has_history'])
    if history:
        if spread > 1e-06:
            if recent > mean_delta + max(0.3 * spread, 1e-06):
                return 9
    if progress < 0.4:
        if breadth > 0.6:
            return 1
    return 1
