"""Pure selection of already-completed, aligned training vectors; never solves."""
import math


def select(records,vectors,count,policy):
    unique=[];seen=set()
    for row in sorted(records,key=lambda t:t.get('semantic_id',t['id'])):
        if row['candidate']['key'] not in seen:unique.append(row);seen.add(row['candidate']['key'])
    if len(unique)<count:raise ValueError('not enough distinct valid H; no budget refill')
    lengths={len(vectors[row['id']]) for row in unique}
    if len(lengths)!=1 or not next(iter(lengths)) or any(not math.isfinite(x) for row in unique for x in vectors[row['id']]):raise ValueError('complete aligned finite training vectors required')
    chosen=[];envelope=None;trace=[];remaining=unique[:]
    if policy not in ('greedy-envelope-J-v1','individual-J-v1','complete train J ascending / ID ascending'):raise ValueError('H selection rule pending / unsupported')
    while len(chosen)<count:
        def objective(row):
            vector=vectors[row['id']]
            values=[min(a,b) for a,b in zip(envelope,vector)] if envelope is not None and policy=='greedy-envelope-J-v1' else vector
            return sum(values)/len(values)
        row=min(remaining,key=lambda t:(objective(t),t.get('semantic_id',t['id'])))
        chosen_objective=objective(row)
        vector=vectors[row['id']];previous=None if envelope is None else sum(envelope)/len(envelope)
        envelope=list(vector) if envelope is None else [min(a,b) for a,b in zip(envelope,vector)]
        chosen.append(row);remaining.remove(row)
        trace.append({'chosen_id':row.get('semantic_id',row['id']),'selection_objective':chosen_objective,'envelope_J':sum(envelope)/len(envelope),'previous_envelope_J':previous})
        # A no-improvement step still fills the predeclared count; no hidden threshold.
    return chosen,trace
