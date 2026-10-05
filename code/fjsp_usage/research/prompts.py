"""Versioned migration of EoH's five operators and V5 selector operators.

No evaluator diagnostics, instance scores, reward history or state labels enter
these prompts. Initialisation receives only member count and the U contract.
"""

from .candidates import U_ARGS, H_ARGS, BUILTINS

OUTPUT = ('Output at most three sentences inside {braces}, followed by exactly one '
          '```python code block. No extra text. Use one function with the exact argument names. '
          'Only numeric constants, local variables, arithmetic, comparisons, if/while/for, '
          'and these builtins are allowed: ' + ', '.join(BUILTINS) + '. '
          'No imports, attributes, containers, helper functions, globals, recursion, '
          'randomness or resource access. Numeric intermediates must remain finite and <=1e100; '
          'power exponents must be literal integers from 0 to 8; round ndigits must be an int in [-100,100]. '
          'End the function with return, or an if/else whose branches both end in return.')

U_CONTRACT = '''Design a deterministic FJSP heuristic selector U, invoked exactly ONCE before each scheduling step.
It chooses a member id; it does not score operation-machine actions. The selected member h alone scores all legal pairs in that step.
Inputs: progress=scheduled operations/N; candidate_pair_ratio=legal pairs/C where C is sum over jobs of maximum alternatives of any operation;
remaining_work_mean/std=population statistics over UNFINISHED jobs' shortest remaining work, current operation included, divided by T;
machine_ready_mean/std=population statistics over ALL machines' end times divided by T; T=sum of maximum alternative duration over all operations;
previous_heuristic=-1 initially, otherwise the prior member id. Time scale T and bound C stay fixed for the instance.
No call occurs at terminal states. Larger h priority wins; exact ties use job index then machine index.
The host evaluates complete feasible schedules on the whole training batch. U returns only a built-in int id.
U may be constant; there is no requirement to switch or use all members. No call to H or parents is allowed.
'''

H_CONTRACT = '''Design one FJSP operation-machine priority rule h. Higher scores win; ties use job then machine index.
Inputs are raw processing_time on this machine; remaining_work=sum shortest remaining processing times including current operation;
remaining_operations includes current; job_ready_time and machine_ready_time are previous completion times;
earliest_start=max of these two ready times; earliest_finish=earliest_start+processing_time.
Return a finite real score. The fixed host schedules and independently validates complete schedules.
'''

FOUNDATIONAL = {
    'I1': 'Create an independent strategy from scratch.',
    'E1': 'Explore an idea as different as possible from the supplied parents.',
    'E2': 'Identify the common backbone of the parents and develop a new strategy from it with different components.',
    'M1': 'Modify the supplied parent to seek better performance.',
    'M2': 'Change numerical parameter settings of the supplied parent while retaining its main structure.',
    'M3': 'Identify and remove redundant components; simplify the supplied parent.',
    'CROSS': 'Combine useful components of the supplied parents into one child.',
    'MUTATE': 'Modify one supplied parent to form one child.',
}


def build_prompt(arm, operator, parents, members, *, kind='U'):
    if arm not in ('B0', 'B1', 'B2', 'P', 'H') or operator not in FOUNDATIONAL:
        raise ValueError('unknown arm/operator')
    if operator == 'I1' and parents:
        raise ValueError('initialisation must be independent')
    if kind == 'U':
        common = U_CONTRACT + f'Legal member ids: 0 <= id < {len(members)}.\n'
        interface = 'def select_heuristic(' + ', '.join(U_ARGS) + '):'
        if operator != 'I1' and arm != 'B0':
            for index, member in enumerate(members):
                common += f'\nH MEMBER {index}\nBehavior: {member.description}\nCode:\n{member.code}'
    else:
        common = H_CONTRACT
        interface = 'def priority(' + ', '.join(H_ARGS) + '):'
    instruction = FOUNDATIONAL[operator]
    if arm == 'P' and operator == 'CROSS':
        instruction += (' Analyze parents as state-to-id decision boundaries in light of the supplied H code; '
                        'combine compatible boundaries and resolve conflicting choices using only the seven state scalars. '
                        'Do not infer state-level winners from unavailable labels, and do not force switching.')
    if arm == 'P' and operator == 'MUTATE':
        instruction += (' Use the supplied H behavior to propose a local change to state conditions, thresholds or member choices; '
                        'preserve the pure seven-scalar interface. Do not use reward feedback, hidden state or forced switching.')
    parents_text = ''.join(f'\nPARENT {i}\nDescription: {p["candidate"]["description"]}\nCode:\n{p["candidate"]["code"]}'
                           for i, p in enumerate(parents))
    return common + '\n' + instruction + parents_text + '\n' + OUTPUT + '\n' + interface
