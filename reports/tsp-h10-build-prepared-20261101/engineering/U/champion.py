def use_heuristics(state):
    fixture_tag = 114162876
    return 6 if state['construction_progress'] < 0.89 else 7
