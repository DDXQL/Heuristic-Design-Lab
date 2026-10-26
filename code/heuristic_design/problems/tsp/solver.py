"""Fixed-origin constructive Euclidean tours, closed edge included."""
from dataclasses import dataclass,asdict
import math
import numpy as np
from heuristic_design.core.mixing import decode_output,combine_scores
from .candidates import H_ARGS,U_ARGS

SCALE=math.sqrt(2.)


def distances(coordinates):
    c=np.asarray(coordinates,dtype=np.float64)
    if c.ndim!=2 or c.shape[1]!=2 or len(c)<3 or not np.isfinite(c).all() or (c<0).any() or (c>1).any():raise ValueError('>=3 finite unit-square XY coordinates')
    d=c[:,None,:]-c[None,:,:]
    return np.sqrt(np.sum(d*d,axis=2,dtype=np.float64))


def tour_length(d,tour):
    n=len(d)
    if len(tour)!=n+1 or tour[0]!=0 or tour[-1]!=0 or sorted(tour[:-1])!=list(range(n)):raise ValueError('exactly once, fixed 0, closed tour required')
    value=math.fsum(float(d[a,b]) for a,b in zip(tour,tour[1:]))
    if not math.isfinite(value) or value<=0:raise ValueError('positive finite length required')
    return value


def nearest_neighbor(d):
    remaining=set(range(1,len(d)));tour=[0]
    while remaining:
        nxt=min(remaining,key=lambda i:(d[tour[-1],i],i));tour.append(nxt);remaining.remove(nxt)
    tour.append(0);return tuple(tour),tour_length(d,tour)


@dataclass(frozen=True)
class TourResult:
    tour:tuple
    length:float
    trace:tuple
    h_calls:tuple


def construct(d,heuristics,usage):
    members=tuple(heuristics);remaining=list(range(1,len(d)));tour=[0];trace=[];calls=[0]*len(members);previous=-1
    while remaining:
        current=tour[-1];progress=(len(tour)-1)/(len(d)-1)
        lengths=[float(d[current,j])/SCALE for j in remaining]
        state=(progress,float(d[current,0])/SCALE,float(np.mean(lengths)),float(np.std(lengths)),previous)
        decoded=decode_output(usage(*state),len(members));columns={};features=[]
        for city,dc in zip(remaining,lengths):
            others=[j for j in remaining if j!=city]
            ds=[float(d[city,j])/SCALE for j in others]
            features.append((dc,float(d[city,0])/SCALE,math.fsum(ds)/len(ds) if ds else 0.,min(ds) if ds else 0.,progress))
        for i in decoded['support']:
            values=[]
            for args in features:
                value=members[i](*args);calls[i]+=1
                if type(value) not in (int,float) or not math.isfinite(value) or abs(value)>1e100:raise ValueError('finite bounded scalar H required')
                values.append(float(value))
            columns[i]=tuple(values)
        scores,normal=combine_scores(columns,decoded['weights'],decoded['support'])
        index=max(range(len(remaining)),key=lambda j:(scores[j],-remaining[j]));city=remaining[index]
        trace.append({'step':len(tour)-1,'state':dict(zip(U_ARGS,state)),'remaining':remaining[:],
            'action_features':[dict(city=j,**dict(zip(H_ARGS,f))) for j,f in zip(remaining,features)],
            'mode':decoded['mode'],'support':decoded['support'],'weights':decoded['weights'],
            'raw_scores':columns,'scores':scores,'chosen':city})
        tour.append(city);remaining.pop(index);previous=decoded['dominant']
    tour.append(0);return TourResult(tuple(tour),tour_length(d,tour),tuple(trace),tuple(calls))
