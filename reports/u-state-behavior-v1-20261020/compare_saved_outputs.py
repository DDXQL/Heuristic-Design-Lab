"""Interpret two recorded outputs on the same saved action-score matrix.

Reference is fixed before comparisons: each instance's recorded first output.
No U/H invocation, weight optimization, rollout, or downstream value label.
"""
import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path
from fjsp_usage.usage_v2.execution import combine_scores

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
states={}
for line in gzip.open(ROOT/'reports/h10-decision-diversity-v1-20261020/sampled_states.jsonl.gz','rt'):
    row=json.loads(line)
    states.setdefault(row['physical_sha256'],row)
groups=defaultdict(list)
for row in csv.DictReader((OUT/'Common_state_joins.csv').open()):
    for field in ('support','weights','chosen'):row[field]=json.loads(row[field])
    row['step']=int(row['step'])
    groups[row['id'],row['file']].append(row)
records=[];summary={}
for (identifier,name),rows in groups.items():
    rows.sort(key=lambda r:r['step'])
    first=rows[0]
    assert first['step']==0
    for row in rows:
        state=states[row['physical_sha256']]
        columns=dict(enumerate(state['raw_scores']))
        held,_=combine_scores(columns,first['weights'],first['support'])
        current,_=combine_scores(columns,row['weights'],row['support'])
        held_index=max(range(len(held)),key=lambda a:held[a])
        actual_index=max(range(len(current)),key=lambda a:current[a])
        assert state['actions'][actual_index]==[row['chosen'][k] for k in ('job','operation','machine','start','end')]
        changed=row['support']!=first['support'] or row['weights']!=first['weights']
        action_changed=held_index!=actual_index
        assert changed or not action_changed
        records.append({'id':identifier,'file':name,'step':row['step'],'physical_sha256':row['physical_sha256'],
            'effective_output_differs_from_first':changed,'action_differs_from_held_first_output':action_changed,
            'first_support':json.dumps(first['support']),'first_weights':json.dumps(first['weights']),
            'actual_action':json.dumps(state['actions'][actual_index]),
            'held_first_output_action':json.dumps(state['actions'][held_index])})
        s=summary.setdefault(identifier,{'matched_states':0,'noninitial_states':0,
            'effective_output_unchanged':0,'output_changed_action_same':0,'output_changed_action_changed':0})
        s['matched_states']+=1;s['noninitial_states']+=int(row['step']>0)
        s['output_changed_action_changed' if action_changed else
          'output_changed_action_same' if changed else 'effective_output_unchanged']+=1
with (OUT/'Same_state_output_effect.csv').open('x',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=list(records[0]),lineterminator='\n')
    writer.writeheader();writer.writerows(records)
with (OUT/'Same_state_output_effect.json').open('x') as stream:
    json.dump({'reference':'Each instance first recorded U output; interpreted on current cached full legal actions, no rollout. This is not a globally fixed strategy or a complete static-policy performance comparison.',
               'candidates':summary,'U_executions':0,'H_executions':0,'new_solves':0},stream,ensure_ascii=False,indent=2)
    stream.write('\n')
print(json.dumps(summary,ensure_ascii=False))
