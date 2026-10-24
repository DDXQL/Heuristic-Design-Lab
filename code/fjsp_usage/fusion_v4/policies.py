"""Exactly six predeclared policies; no new operator or weight search."""
THRESHOLDS = (.25, .50, .75)
DIRECTIONS = (('WEIGHTED_SUM', 'BORDA'), ('BORDA', 'WEIGHTED_SUM'))


def specs():
    return [{'id':f'{"WS_BORDA" if first=="WEIGHTED_SUM" else "BORDA_WS"}_t{int(t*100):03d}',
             'first':first,'late':late,'threshold':t,'pair':[0,1]}
            for first,late in DIRECTIONS for t in THRESHOLDS]


def progress_policy(spec, size=10):
    if spec not in specs() or type(size) is not int or size<2:
        raise ValueError('only six frozen H01 policies allowed')
    vector=tuple(.5 if i in (0,1) else 0. for i in range(size))
    first,late,threshold=spec['first'],spec['late'],spec['threshold']
    def usage(progress,*remaining_features):
        return (first if progress<threshold else late,vector)
    return usage
