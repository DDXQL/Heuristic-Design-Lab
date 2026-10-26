"""Established SELECT/top-two min-max semantics, domain-independent copy.

Legacy FJSP source remains frozen; parity is checked against it.
"""
import math
SELECT=0
MIX=1
class UsageOutputError(ValueError):pass
class NormalizationError(ValueError):pass

def _number(x):
    if type(x) not in (int,float) or abs(x)>1e100 or not math.isfinite(x):
        raise UsageOutputError('usage elements must be finite bounded built-in int/float, never bool')
    return x


def decode_output(output,size,allowed_modes=(SELECT,MIX)):
    if type(output) is not tuple or len(output)!=2:
        raise UsageOutputError('usage output must be an exact two-item tuple')
    mode,vector=output
    if type(mode) is not int or mode not in (SELECT,MIX) or mode not in allowed_modes:
        raise UsageOutputError('illegal or disallowed usage mode')
    if type(vector) is not tuple or len(vector)!=size:
        raise UsageOutputError('usage vector must be a tuple of frozen H size')
    values=tuple(_number(x) for x in vector)
    if mode==SELECT:
        winner=max(range(size),key=lambda i:values[i])  # stable first max
        support=(winner,); alpha=tuple(1.0 if i==winner else 0.0 for i in range(size))
    else:
        if any(x<0 for x in values): raise UsageOutputError('negative MIX weight')
        support=tuple(i for i,x in enumerate(values) if x>0)
        if not 1<=len(support)<=2: raise UsageOutputError('MIX requires one or two strictly positive weights')
        if len(support)==1:
            alpha=tuple(1.0 if i==support[0] else 0.0 for i in range(size))
        else:
            maximum=max(values[i] for i in support)
            scaled={i:float(values[i])/maximum for i in support}
            if any(x<=0 or not math.isfinite(x) for x in scaled.values()):
                raise NormalizationError('positive weight underflow/nonfinite scaling')
            total=math.fsum(scaled.values())
            alpha=tuple(scaled[i]/total if i in scaled else 0.0 for i in range(size))
            if any(alpha[i]<=0 or not math.isfinite(alpha[i]) for i in support) or not math.isclose(math.fsum(alpha),1.0,rel_tol=0,abs_tol=1e-15):
                raise NormalizationError('normalized weights lost support or finite unit sum')
    dominant=max(range(size),key=lambda i:alpha[i])
    return {'mode':mode,'vector':values,'support':support,'weights':alpha,'dominant':dominant}


def normalize_scores(scores):
    lo,hi=min(scores),max(scores)
    if lo==hi: return tuple(0.0 for _ in scores),lo,hi
    scale=max(abs(lo),abs(hi)); left,right=lo/scale,hi/scale
    spread=right-left
    if spread<=0 or not math.isfinite(spread): raise NormalizationError('distinct scores lost positive scaled range')
    result=tuple((x/scale-left)/spread for x in scores)
    if any(not math.isfinite(x) or not 0<=x<=1 for x in result): raise NormalizationError('invalid min-max score')
    return result,lo,hi


def combine_scores(columns,weights,support):
    if len(support)==1:
        return tuple(columns[support[0]]),{}  # EXACT legacy ordering
    normalized={}; ranges={}
    for i in support:
        normalized[i],lo,hi=normalize_scores(columns[i]); ranges[i]=(lo,hi)
    scores=tuple(math.fsum(weights[i]*normalized[i][a] for i in support) for a in range(len(columns[support[0]])))
    if any(not math.isfinite(x) or not -1e-15<=x<=1+1e-15 for x in scores): raise NormalizationError('invalid combined score')
    return scores,{'normalized':normalized,'ranges':ranges}
