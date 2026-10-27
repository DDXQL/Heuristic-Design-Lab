"""Problem description and unchanged CROSS/MUTATE parent-only structure."""
from .candidates import H_ARGS,U_ARGS
from heuristic_design.core.operators import CROSS,MUTATE

DESCRIPTION='''Constructive symmetric complete Euclidean TSP in [0,1]^2. Start city 0; choose an unvisited city at each step; return to city 0 after the final choice. True float64 Euclidean distances, no rounding and no local search. Higher H score wins; exact action ties choose smallest city ID. Every distance feature is divided by sqrt(2). All fields describe the current partial tour only, no optimum/future payoff is available.
H action arguments: distance_current=current-to-candidate distance; distance_start=candidate-to-origin-0 distance; mean_remaining_distance and nearest_remaining_distance measure candidate-to-OTHER unvisited cities, excluding the candidate itself (both 0 if no other city remains); progress=(visited_count-1)/(n-1) BEFORE the choice. All five in [0,1].
U state: progress as above; current_to_start=current-to-origin distance/sqrt(2); mean_distance_current and std_distance_current are mean and population std of distances/sqrt(2) from current to ALL unvisited cities; previous_heuristic is -1 initially, then previous dominant member ID, with weight ties choosing lowest ID. First four fields are in [0,1], std <=0.5. U sees no action features or H scores.
Training Fitness is minus arithmetic mean(tour_length / same-instance nearest-neighbor tour_length) over ALL 20 train instances. Nearest neighbor also starts at 0 with city-ID ties and closes to 0. Higher Fitness is better. This is NOT optimality gap or lower bound. Any invalid output/timeout/failed instance invalidates the whole candidate. Solve/recheck must match. No test or validation feedback is available.
Only numerical scalar Python is allowed: assignments, if/else, arithmetic, comparisons, abs/min/max/int/float/round; no imports, attributes, subscripts, lists, comprehensions, loops, functions, recursion, external access or randomness. All paths must end with return. Numerical constants <=1e9, intermediate magnitude <=1e100, power exponents literal integers 0..8. No type annotations needed.
Return exactly {one short description} followed by one fenced python block, nothing else.'''


def build(config,task,parents,members):
    kind=config['candidate_kind'];op=task['operator']
    text=DESCRIPTION+'\n'
    if kind=='h':
        return text+'\nDesign one new action-scoring heuristic. Exact signature: def priority('+', '.join(H_ARGS)+'):\nReturn one finite scalar, larger is preferred. Do not call U or other H.\n'
    k=len(members)
    text+='\nDesign a usage policy. Exact signature: def use_heuristics('+', '.join(U_ARGS)+'):\n'
    text+=f'''Return exactly (mode, (v0, ..., v{k-1})), with exactly {k} numeric components written explicitly. SELECT mode=0 chooses max component, smallest member ID on ties; components may be negative or zero. MIX mode=1 requires nonnegative weights with exactly one or two strictly positive components. Host normalizes positive weights; one member uses original scores; two members each min-max across ALL current legal actions, constant columns become 0, then weighted sum. No automatic top-two truncation. Never use more than two positives. You can use state-dependent SELECT, support, weights or mode; constants are also legal.\n'''
    for i,m in enumerate(members):text+=f'\nH MEMBER {i}\n{m["description"]}\n{m["code"]}'
    if op=='I1':
        if parents:raise ValueError('IND prompt must not contain parents')
        text+='\nCreate an original usage policy independently. No parent/history/fitness feedback is supplied.\n'
    else:
        instruction=CROSS if op=='CROSS' else MUTATE
        text+='\n'+instruction.replace('selection relationship','usage relationship').replace('selector','usage program').replace('complete-schedule','complete-tour')+'\n'
        for n,p in enumerate(parents):text+=f'PARENT {n}\n{p["candidate"]["description"]}\n{p["candidate"]["code"]}\n'
    return text
