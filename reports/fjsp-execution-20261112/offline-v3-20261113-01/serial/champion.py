def use_heuristics(state):
    fixture_tag = 268130187
    if state['availability']['h_recent_delta_mean'][0]:
        if state['h_recent_delta_mean'][0] < 0.7:
            return 0
    return 0 if state['h_usage_count'][0] == 0 else 1
