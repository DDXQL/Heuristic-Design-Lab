"""Finite canonical static policies. Integer declarations precede float creation.

Never round an arbitrary host weight vector into this space. Endpoints are raw
single-H SELECT, interior k/20 is the lower-ID member's weight; its partner is
EXACT Python 1.0-alpha, preserving the archived H01 grid's float convention.
"""
from itertools import combinations
from math import isfinite

PAIRS=tuple(combinations(range(10),2))


def canonical(members,ticks):
    if (type(members) is not tuple or type(ticks) is not tuple or len(members)!=len(ticks)
        or len(members) not in (1,2) or any(type(i) is not int or not 0<=i<10 for i in members)
        or any(type(t) is not int or t<0 for t in ticks) or sum(ticks)!=20):
        raise ValueError('one/two valid integer member/tick declarations with total20 required')
    merged={}
    for i,t in zip(members,ticks):merged[i]=merged.get(i,0)+t
    active=sorted(i for i,t in merged.items() if t>0)
    if len(active)==1:return {'kind':'single','member':active[0]}
    return {'kind':'pair','i':active[0],'j':active[1],'k':merged[active[0]]}


def validate(spec):
    if type(spec) is not dict:raise ValueError('exact dictionary required')
    if set(spec)=={'kind','member'} and spec['kind']=='single':
        if type(spec['member']) is int and 0<=spec['member']<10:return dict(spec)
    if set(spec)=={'kind','i','j','k'} and spec['kind']=='pair':
        if all(type(spec[x]) is int for x in ('i','j','k')) and 0<=spec['i']<spec['j']<10 and 1<=spec['k']<=19:return dict(spec)
    raise ValueError('policy outside canonical finite space')


def ticket(spec):
    spec=validate(spec)
    return spec['member'] if spec['kind']=='single' else 10+19*PAIRS.index((spec['i'],spec['j']))+spec['k']-1


def decode(index):
    if type(index) is not int or not 0<=index<865:raise ValueError('ticket outside [0,865)')
    if index<10:return {'kind':'single','member':index}
    pair,k=divmod(index-10,19);i,j=PAIRS[pair]
    return {'kind':'pair','i':i,'j':j,'k':k+1}


def output(spec):
    spec=validate(spec);values=[0.]*10
    if spec['kind']=='single':values[spec['member']]=1.;mode=0
    else:
        alpha=spec['k']/20.;values[spec['i']]=alpha;values[spec['j']]=1.-alpha;mode=1
    return mode,tuple(values)


def policy(spec):
    result=output(spec)
    def usage(*state):return result
    return usage
