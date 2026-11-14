"""OBP preset-N candidate adapter, exactly the delivered D08 arithmetic.

Reuse the frozen public History/observe/array extension; never redefine fields.
FJSP/TSP and old OBP modules are untouched. Adoption is a separate protocol gate.
"""
import math
from heuristic_design.core import state_a_v3 as public
from .problems import legal_obp_actions
ADAPTER_ID='obp-preset-N-v1-candidate'
ACTION_POLICY='preallocated_empty_bins'


def extract(current_item,opened_used,capacity,history):
    if not isinstance(history,public.History):raise ValueError('frozen common-state-a-v3 History required')
    if type(capacity) not in (int,float) or not math.isfinite(capacity) or capacity<=0:raise ValueError('positive finite capacity required')
    used=tuple(opened_used);n=history.decisions;t=history.count
    if type(n) is not int or n<1 or len(used)!=n or not 0<=t<n:raise ValueError('public N permanent slots and nonterminal history required')
    if any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=capacity for x in used):raise ValueError('finite loads in [0,C] required; never clip')
    opened=[x for x in used if x>0]
    if len(opened)>t or (t==0)!=(len(opened)==0):raise ValueError('opened-bin count and successful-commit history differ')
    actions=legal_obp_actions(current_item,used,capacity,ACTION_POLICY)
    if not actions:raise ValueError('nonterminal preset-N domain must have a feasible empty bin')
    packet=public.observe('obp',history=history,demands=(current_item/capacity,),
      commitments=(x/capacity for x in opened),action_deltas=(int(used[i]==0) for i in actions))
    return packet,actions
