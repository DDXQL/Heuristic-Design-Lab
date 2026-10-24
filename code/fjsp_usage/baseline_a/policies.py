"""Complete, quality-independent static strategy enumeration."""
from itertools import combinations


def specs():
    return ([{'id':f'H{i}','category':'A1','members':[i]} for i in range(10)] +
            [{'id':f'H{i}_H{j}_WS','category':'A2','members':[i,j]} for i,j in combinations(range(10),2)])


def policy(spec):
    if spec not in specs():raise ValueError('strategy outside fixed 10+45 suite')
    selected=spec['members'];single=len(selected)==1
    vector=tuple((1. if single else .5) if i in selected else 0. for i in range(10))
    def usage(*state):return ('SELECT' if single else 'WEIGHTED_SUM',vector)
    return usage
