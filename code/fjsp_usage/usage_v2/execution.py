"""Fixed current-action mixture semantics. Costs are never in semantic hashes."""
from dataclasses import dataclass,asdict
import math
import numbers
import time
from collections import Counter
from fjsp_usage.offline_v2 import _SchedulingState,InvalidSelectionError,lower_bound_v5
from llm4ad.task.optimization.fjsp_set.scheduler import Schedule,ScheduledOperation,validate_schedule
from fjsp_usage.research.protocol import digest
from . import SELECT,MIX,VERSION

class UsageOutputError(InvalidSelectionError): pass
class NormalizationError(ValueError): pass


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


@dataclass(frozen=True)
class UsageResultV2:
    schedule: Schedule
    selected_members: tuple  # compatibility view: DOMINANT ids only
    lower_bound: float
    score: float
    decisions: tuple
    member_calls: tuple


def construct_usage_schedule(instance,heuristics,usage,*,allowed_modes=(SELECT,MIX),trace=None,max_actions=1000,cost=None):
    members=tuple(heuristics)
    if not members or not all(callable(h) for h in members) or not callable(usage): raise ValueError('callable U/nonempty H required')
    if type(max_actions) is not int or max_actions<0: raise ValueError('nonnegative action trace limit required')
    if not allowed_modes or any(type(x) is not int or x not in (SELECT,MIX) for x in allowed_modes): raise ValueError('explicit legal allowed modes required')
    state=_SchedulingState(instance); decisions=[]; calls=[0]*len(members)
    for step in range(state.total_operations):
        features=state.features()
        try: output=usage(*features)
        except Exception as exc: raise UsageOutputError(f'U exception at step {step}') from exc
        started=time.perf_counter(); decoded=decode_output(output,len(members),allowed_modes)
        processing=time.perf_counter()-started
        actions=[]; inputs=[]
        for j,job in enumerate(instance.jobs):
            o=state.cursors[j]
            if o==len(job): continue
            for machine,duration in job[o].alternatives:
                start=max(state.job_ready[j],state.machine_ready[machine]);end=start+duration
                actions.append((j,o,machine,start,end))
                inputs.append((float(duration),float(state.remaining_work[j][o]),len(job)-o,
                    float(state.job_ready[j]),float(state.machine_ready[machine]),float(start),float(end)))
        if not actions: raise ValueError('no legal action')
        columns={}; scoring_started=time.perf_counter()
        for i in decoded['support']:
            values=[]
            for args in inputs:
                raw=members[i](*args);calls[i]+=1
                if isinstance(raw,bool) or not isinstance(raw,numbers.Real): raise ValueError('h must return a real scalar')
                try: value=float(raw)
                except (ValueError,TypeError,OverflowError) as exc: raise ValueError('h must return finite scalar') from exc
                if not math.isfinite(value): raise ValueError('nonfinite selected h score')
                values.append(value)
            columns[i]=tuple(values)
        scoring=time.perf_counter()-scoring_started
        started=time.perf_counter();scores,normal=combine_scores(columns,decoded['weights'],decoded['support'])
        processing+=time.perf_counter()-started
        winner=max(range(len(actions)),key=lambda a:scores[a]); chosen=actions[winner]
        j,o,machine,start,end=chosen
        state.scheduled.append(ScheduledOperation(*chosen));state.cursors[j]+=1
        state.job_ready[j]=end;state.machine_ready[machine]=end
        state.selected_members.append(decoded['dominant'])
        decision=(decoded['mode'],decoded['vector'],decoded['support'],decoded['weights'],decoded['dominant'])
        decisions.append(decision)
        if cost is not None: cost({'combination_processing_seconds':processing,'selected_h_scoring_seconds':scoring})
        if trace is not None:
            trace({'step':step,'state':dict(features._asdict()),'interface_version':VERSION,
                **decoded,'member_id':decoded['dominant'],'action_count':len(actions),
                'h_calls':{i:len(actions) for i in decoded['support']},
                'ranges':normal.get('ranges',{}),'actions_truncated':len(actions)>max_actions,
                'actions':[{'job':a[0],'operation':a[1],'machine':a[2],'start':a[3],'end':a[4],
                    'raw_scores':{i:columns[i][n] for i in decoded['support']},
                    'normalized_scores':{i:normal['normalized'][i][n] for i in decoded['support']} if normal else None,
                    'score':scores[n]} for n,a in enumerate(actions[:max_actions])],
                'chosen':dict(zip(('job','operation','machine','start','end'),chosen)),
                'chosen_score':scores[winner]})
    schedule=Schedule(tuple(state.scheduled),max(a.end for a in state.scheduled));validate_schedule(instance,schedule)
    bound=lower_bound_v5(instance)
    return UsageResultV2(schedule,tuple(state.selected_members),bound,-schedule.makespan/bound,tuple(decisions),tuple(calls))


def usage_summary(result,size):
    modes=Counter(d[0] for d in result.decisions);supports=Counter(len(d[2]) for d in result.decisions)
    return {'interface_version':VERSION,'steps':len(result.decisions),'SELECT_steps':modes[SELECT],'MIX_steps':modes[MIX],
        'dual_member_steps':supports[2],'single_member_steps':supports[1],
        'participation_counts':[sum(i in d[2] for d in result.decisions) for i in range(size)],
        'weight_mass':[math.fsum(d[3][i] for d in result.decisions) for i in range(size)],
        'dominant_counts':[result.selected_members.count(i) for i in range(size)],
        'dominant_switches':sum(a!=b for a,b in zip(result.selected_members,result.selected_members[1:])),
        'h_calls':list(result.member_calls),'notice':'dominant ids do not describe all members or weights; switching is not rewarded'}


class LegacyAdapter:
    """Trusted explicit test adapter; never a newly model-generated candidate."""
    def __init__(self,selector,size,source_key):
        self.selector,self.size=selector,size
        self.binding={'mechanism':'explicit-legacy-int-to-SELECT-one-hot-v1','source_key':source_key,
            'target_interface':VERSION,'member_count':size,'real_generation':False}
        self.identity=digest(self.binding)
    def __call__(self,*args):
        k=self.selector(*args)
        if type(k) is not int or not 0<=k<self.size: raise UsageOutputError('invalid legacy member id')
        return (SELECT,tuple(1 if i==k else 0 for i in range(self.size)))
