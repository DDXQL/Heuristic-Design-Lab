"""Independent Borda extension; old operators delegate to frozen V2 exactly.

The scheduling loop is copied from cf05418's frozen V2 because that constructor
has no fusion injection interface. State/action/commit/LB semantics are retained.
No monkeypatch or modification of the historical executor is performed.
"""
import math
import numbers
import time

from fjsp_usage.offline_v2 import _SchedulingState, lower_bound_v5
from fjsp_usage.research.protocol import digest
from fjsp_usage.usage_v2.execution import decode_output, UsageOutputError
from fjsp_usage.fusion_v2.execution import decode_fusion, fuse_scores, FusionResult
from llm4ad.task.optimization.fjsp_set.scheduler import Schedule, ScheduledOperation, validate_schedule
from .ranking import borda_scores


def decode_rank(output, size):
    if type(output) is tuple and len(output)==2 and output[0]=='BORDA':
        decoded=decode_output((1,output[1]),size)
        support=decoded['support']
        if len(support)!=2 or output[1][support[0]]!=output[1][support[1]]:
            raise UsageOutputError('BORDA requires two equal positive support indicators')
        return dict(decoded,operator='BORDA')
    return decode_fusion(output,size)


def fuse_rank(columns, weights, support, operator):
    if operator!='BORDA':
        return fuse_scores(columns,weights,support,operator)
    # Validate vector semantics through the frozen decoder; no ignored weights.
    decoded=decode_rank(('BORDA',tuple(weights)),len(weights))
    if decoded['support']!=tuple(support):
        raise UsageOutputError('BORDA support/vector mismatch')
    points,ranks=borda_scores(columns,support)
    return points,{'borda_twice':ranks}


def fixed_borda(pair,size=10):
    if (type(pair) is not tuple or len(pair)!=2 or any(type(i) is not int or not 0<=i<size for i in pair)
            or pair[0]>=pair[1]):
        raise ValueError('ordered distinct frozen member pair required')
    vector=tuple(.5 if i in pair else 0. for i in range(size))
    return lambda *state:('BORDA',vector)


def construct_rank_schedule(instance, heuristics, usage, *, trace=None, cost=None):
    members=tuple(heuristics)
    if not members or not all(callable(h) for h in members) or not callable(usage):
        raise ValueError('nonempty callable H and callable U required')
    state=_SchedulingState(instance);calls=[0]*len(members);decisions=[]
    for step in range(state.total_operations):
        features=state.features()
        try:output=usage(*features)
        except Exception as exc:raise UsageOutputError(f'U exception at step {step}') from exc
        decoded=decode_rank(output,len(members))
        actions,inputs=[],[]
        for j,job in enumerate(instance.jobs):
            o=state.cursors[j]
            if o==len(job):continue
            for machine,duration in job[o].alternatives:
                start=max(state.job_ready[j],state.machine_ready[machine]);end=start+duration
                actions.append((j,o,machine,start,end))
                inputs.append((float(duration),float(state.remaining_work[j][o]),len(job)-o,
                    float(state.job_ready[j]),float(state.machine_ready[machine]),float(start),float(end)))
        if not actions:raise ValueError('no legal action')
        started=time.perf_counter();columns={}
        for i in decoded['support']:
            values=[]
            for args in inputs:
                raw=members[i](*args);calls[i]+=1
                if isinstance(raw,bool) or not isinstance(raw,numbers.Real):raise ValueError('h must return a real scalar')
                try:value=float(raw)
                except (ValueError,TypeError,OverflowError) as exc:raise ValueError('h must return finite scalar') from exc
                if not math.isfinite(value):raise ValueError('nonfinite selected h score')
                values.append(value)
            columns[i]=tuple(values)
        scoring_seconds=time.perf_counter()-started;started=time.perf_counter()
        scores,normal=fuse_rank(columns,decoded['weights'],decoded['support'],decoded['operator'])
        winner=max(range(len(actions)),key=lambda a:scores[a])
        fusion_seconds=time.perf_counter()-started;chosen=actions[winner]
        if trace is not None:
            snapshot={'cursors':tuple(state.cursors),'job_ready':tuple(state.job_ready),
                'machine_ready':tuple(state.machine_ready),'previous_heuristic':features.previous_heuristic,
                'scheduled':sorted((a.job,a.operation,a.machine,a.start,a.end) for a in state.scheduled)}
            trace({'step':step,'state':dict(features._asdict()),'physical_state':snapshot,
                'state_sha256':digest(snapshot),'operator':decoded['operator'],'support':decoded['support'],
                'weights':decoded['weights'],'actions':actions,'columns':columns,
                'borda_twice':normal.get('borda_twice',{}),'scores':scores,'winner':winner,'chosen':chosen})
        j,o,machine,start,end=chosen
        state.scheduled.append(ScheduledOperation(*chosen));state.cursors[j]+=1
        state.job_ready[j]=end;state.machine_ready[machine]=end;state.selected_members.append(decoded['dominant'])
        decisions.append((decoded['operator'],decoded['vector'],decoded['support'],decoded['weights'],decoded['dominant']))
        if cost is not None:cost({'h_scoring_seconds':scoring_seconds,'fusion_seconds':fusion_seconds})
    schedule=Schedule(tuple(state.scheduled),max(a.end for a in state.scheduled));validate_schedule(instance,schedule)
    bound=lower_bound_v5(instance)
    return FusionResult(schedule,tuple(state.selected_members),bound,-schedule.makespan/bound,tuple(decisions),tuple(calls))
