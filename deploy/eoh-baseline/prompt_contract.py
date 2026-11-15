"""Describe the EXISTING H validators; no parsing, repair, solver or search here."""
from heuristic_design.core.storage import digest
from fjsp_usage.research.candidates import H_ARGS as FJSP_ARGS,BUILTINS as FJSP_BUILTINS
from heuristic_design.problems.tsp.candidates import H_ARGS as TSP_ARGS,BUILTINS as TSP_BUILTINS

VERSION='closed-H-prompt-contract-v2-20261115'
SERIALIZATION='''RESPONSE SERIALIZATION (literal characters, NOT LaTeX):
Start with exactly one short sentence inside literal ASCII braces: {description}.
The description is nonempty, at most 1000 characters, with no nested braces.
Follow it with exactly ONE fenced block whose opening line is ```python.
Inside the block return exactly one complete priority function with the exact arguments below.
Close with ``` on its own line. There is no other text, no prose after the block,
no second fence, no \\boxed, no \\text, no \\( or \\[ wrappers.
Keep the entire response within 32768 UTF-8 bytes; code within 24576 bytes and 2000 AST nodes.
The example below demonstrates serialization only; it is not an evaluated rule or a parent.'''

SHARED='''CLOSED H LANGUAGE, enforced by the unchanged validator:
Use exactly one function, priority, with only the named positional arguments in the stated order.
No defaults, decorators, *args, **kwargs, keyword-only arguments, helper/nested functions,
imports, attributes, globals, external calls, recursion, files, network or randomness.
No keyword or starred arguments in builtin calls. Assign only to local names.
Local numerical assignments, arithmetic, comparisons, boolean expressions, conditional expressions
and if/else are allowed.
All control-flow paths must end with return. Never mutate the input.
Power exponents MUST be literal built-in integers 0..8, e.g. x ** 2 or x ** 0.
Fractional powers such as x ** 0.5, negative powers such as x ** -1, float exponents such as
x ** 2.0, and variable exponents are rejected. Use arithmetic division for reciprocals when safe.
Only numerical/boolean literals are allowed: no string sentinels, no float("inf"),
float('nan') or nonfinite constants. An optional first function docstring is accepted;
other strings are not. Omit type annotations for compatibility.
Do not call another H or U, inspect hidden data, or perform lookahead.'''

def signature(problem,abi=None):
    args=FJSP_ARGS if problem=='fjsp' else TSP_ARGS if problem=='tsp' else ('item_size','remaining_capacities') if abi=='obp-vector-feasible-h-v2' else ('item_size','remaining_capacity')
    if problem not in ('fjsp','tsp','obp'):raise ValueError('unknown H problem')
    return 'def priority('+', '.join(args)+'):'

def example(problem,abi=None):
    body='    return [0.0 for cap in remaining_capacities]' if problem=='obp' and abi=='obp-vector-feasible-h-v2' else '    return 0.0'
    return '{A constant priority illustrates the required response syntax only.}\n```python\n'+signature(problem,abi)+'\n'+body+'\n```'

def description(problem,abi=None,host_contract=None):
    if problem=='fjsp':
        domain='''Design ONE FJSP ready-operation/machine action priority H. Minimize makespan.
Inputs are unnormalized physical values: processing_time is this operation on this machine;
remaining_work sums minimum alternative durations from this operation to the job end;
remaining_operations includes this operation; job_ready_time and machine_ready_time are current
ready times; earliest_start=max(job_ready_time,machine_ready_time);
earliest_finish=earliest_start+processing_time.
Largest finite real priority wins; exact ties retain the first legal action in ascending job
order and original eligible-machine enumeration order. The append-only constructor commits
the action; there is no local search or postprocessing.
Complete train21 J=mean((Cmax-LB_v5)/LB_v5), MINIMIZED. Native rank machinery uses -J internally.
LB_v5=max(max_j sum_over_job_ops min_duration, sum_all_ops min_duration/M), without rounding.
Validation/test are never supplied.'''
        language=('Scalar H: return one finite built-in real score. No containers: tuples, lists, dicts, sets, '
          'subscripts or comprehensions are rejected. for/while/break/continue and range are admitted by '
          'the existing FJSP language; finite evaluation is still subject to the unchanged T30 limit. '
          'Allowed builtins: '+', '.join(FJSP_BUILTINS)+'. Numeric literal absolute value <=1e9; '
          'numerical intermediates must stay finite with absolute value <=1e100. '
          'round ndigits must be a built-in int in [-100,100].')
    elif problem=='tsp':
        domain='''Design ONE symmetric complete Euclidean TSP next-city priority H.
Start at city0, select an unvisited city, and close to city0 after the last choice.
distance_current is current-to-candidate distance; distance_start is candidate-to-city0 distance.
mean_remaining_distance and nearest_remaining_distance are candidate-to-OTHER-unvisited-city
statistics excluding the candidate, both zero if none remain. All distances are divided by sqrt(2).
progress=(visited_count-1)/(n-1), before this choice. All five inputs are in [0,1].
Largest finite real priority wins, exact ties choose smallest city ID. No local search.
Minimize complete train J=mean((tour_length-reference)/reference); reference is the externally
frozen same-instance LKH reference, never nearest neighbor. Internal native score is -J.
No test/validation or future payoff is supplied.'''
        language=('Scalar H: return one finite built-in real score. No tuples/containers, subscripts, '
          'comprehensions, for/while loops, augmented assignments or helper functions. '
          'Allowed builtins: '+', '.join(sorted(TSP_BUILTINS))+'. Numeric literal absolute value <=1e9; '
          'intermediates finite with absolute value <=1e100; round ndigits built-in int in [-100,100].')
    elif problem=='obp':
        domain='''Design ONE online bin-packing priority H. Only the current item and current feasible
bin capacities are visible; never future arrivals. Capacities are residual capacities BEFORE
placing the item. The bound/action/reference policy is the explicitly bound host contract below.
Larger finite score wins; exact ties choose the smallest feasible permanent bin ID.
Minimize complete train J=mean((bin_count-reference)/reference); internal native score is -J.'''
        if abi=='obp-vector-feasible-h-v2':
            language='''Vector H ABI: priority(item_size, remaining_capacities).
remaining_capacities is the immutable tuple of ALL feasible bin capacities in ascending permanent-ID
order, including every feasible empty bin supplied by the host. Return a list/tuple containing
exactly ONE finite built-in int/float score per input capacity in the SAME order.
Lists/tuples and capacity subscripts are admitted ONLY in this vector ABI, not the scalar ABIs.
Each list comprehension has exactly one non-async generator, no filter and no nested comprehension;
iterate ONLY over remaining_capacities or range(len(remaining_capacities)). No standalone for/while
or generator expressions; no other object may be subscripted; assignments target local names only.
Allowed builtins: abs, min, max, int, float, round, sum, len, range, tuple.
Numerical/boolean literals must be finite, absolute value <=1e6. The current vector validator does
not use the scalar 1e100 intermediate guard; the returned scores must still be finite.
The same literal integer exponent 0..8 rule applies. Do not introduce NumPy or input mutation.'''
        elif abi in (None,'obp-two-scalar-h-v1'):
            language=('Scalar engineering ABI: priority(item_size, remaining_capacity), called on one feasible bin. '
              'Return one finite real score. No tuples/containers, subscripts, comprehensions or loops. '
              'Allowed builtins: abs,min,max,int,float,round. Numeric literals absolute value <=1e9; '
              'intermediates finite and <=1e100; round ndigits built-in int in [-100,100].')
        else:raise ValueError('unsupported OBP H ABI; no silent change')
    else:raise ValueError('unknown H problem')
    host='' if host_contract is None else '\nFrozen host action/reference contract:\n'+__import__('json').dumps(host_contract,sort_keys=True)
    return '\n\n'.join([domain,signature(problem,abi),SHARED,language,host,SERIALIZATION,example(problem,abi)])

def identity(problem,abi=None,host_contract=None):
    text=description(problem,abi,host_contract)
    return {'version':VERSION,'problem':problem,'H_ABI':abi,'sha256':digest(text)}
