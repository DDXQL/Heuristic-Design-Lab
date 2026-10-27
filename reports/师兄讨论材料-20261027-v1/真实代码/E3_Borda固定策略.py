def fixed_borda(pair,size=10):
    if (type(pair) is not tuple or len(pair)!=2 or any(type(i) is not int or not 0<=i<size for i in pair)
            or pair[0]>=pair[1]):
        raise ValueError('ordered distinct frozen member pair required')
    vector=tuple(.5 if i in pair else 0. for i in range(size))
    return lambda *state:('BORDA',vector)
