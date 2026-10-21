"""B1-only free discovery pack; legacy SELECT initialisation is untouched."""
from fjsp_usage.research.candidates import H_ARGS, U_ARGS
from fjsp_usage.research.protocol import digest
from fjsp_usage.usage_v2.prompts import TASK, NEW_OUTPUT, CROSS, MUTATE, H_CONTEXT

VERSION = 'B1-full-H-free-initialisation-prompts-v1-20261021'
NOVELTY = '''B1 FREE INITIALISATION NOVELTY CONTEXT
Previously accepted source CODE ONLY follows, without numeric fitness or ranking.
These are not parents or recommendations for members or pairs.
Create an independent SELECT or MIX program; constants and unused inputs/members are legal.
H behavior and code above are design context, not evidence of local superiority.
No fixed member pair, equal weights, switching, phase partition or skeleton is required.
Only validated AST keys are deduplicated; source diversity does not prove behavioral diversity.
'''


def build_prompt(arm, operator, parents, members, *, kind='U'):
    if arm != 'B' or kind != 'U' or len(members) != 10:
        raise ValueError('B1 uses internal B, U and ordered ten H')
    if (operator not in ('I1','CROSS','MUTATE') or
            operator == 'I1' and parents or
            operator == 'CROSS' and not 2 <= len(parents) <= 5 or
            operator == 'MUTATE' and len(parents) != 1 or
            len({p['id'] for p in parents}) != len(parents)):
        raise ValueError('distinct crossover parents or one mutation parent required')
    context = 'K=10; ordered member ids 0 through 9.\n'
    context += H_CONTEXT.replace('The host calls the chosen h for each legal action.',
                                'The host calls only the active members for each legal action.')
    context += 'def priority('+', '.join(H_ARGS)+'):\n'
    for i,m in enumerate(members):
        context += f'\nH MEMBER {i}\nBehavior: {m.description}\nCode:\n{m.code}\n'
    operation = ('There are no parents. Create an independent SELECT or MIX program; member ids do not imply quality.'
                 if operator == 'I1' else CROSS if operator == 'CROSS' else MUTATE)
    operation = operation.replace('selection relationship','usage relationship').replace('selector','usage program')
    parent_text = ''.join(f'\nPARENT {i}\nDescription: {p["candidate"]["description"]}\nCode:\n{p["candidate"]["code"]}\n'
                          for i,p in enumerate(parents))
    return '\n'.join((TASK,'Permitted modes: SELECT (0) OR MIX (1); at most two positive MIX weights.',
                      context,parent_text,operation,NEW_OUTPUT+'\ndef use_heuristics('+', '.join(U_ARGS)+'):'))


def manifest():
    return {'version':VERSION,'sections_sha256':digest((TASK,H_CONTEXT,CROSS,MUTATE,NEW_OUTPUT,NOVELTY)),
            'initialisation':'new LLM U; all H code/behavior, SELECT/MIX; no manual seed or performance guidance',
            'feedback':'parent description/source only; fitness affects external selection only',
            'crossover':'one response/child; inherit ideas of at least two parents; configurable parent count'}
