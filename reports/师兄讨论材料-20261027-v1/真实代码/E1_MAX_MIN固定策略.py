def fixed_policy(pair, operator, size=10):
    if (type(pair) is not tuple or len(pair) != 2 or pair[0] >= pair[1]
            or any(type(i) is not int or not 0 <= i < size for i in pair)
            or operator not in OPERATORS):
        raise ValueError('ordered distinct in-range fixed pair and fusion operator required')
    vector = tuple(.5 if i in pair else 0. for i in range(size))
    return lambda *state: (operator, vector)
