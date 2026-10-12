"""V5 prompt pack for new staged runs; research_v1 prompts stay unchanged.

Only the operator section differs between B2 and P. Evaluation results and
diagnostics never enter any prompt. Building/exporting a prompt sends nothing.
"""

from fjsp_usage.research.candidates import H_ARGS, U_ARGS
from fjsp_usage.research.prompts import OUTPUT, H_CONTRACT, FOUNDATIONAL
from fjsp_usage.research.protocol import digest

PROMPT_VERSION = 'V5-FJSP-selector-prompts-v5-state-bounds-20261011'
FRAMEWORK_URL = 'https://app.notion.com/p/3e904e0510d781eba9b5f8b9114e2e70'
V5_OUTPUT = OUTPUT + (' Every numeric literal in source code must have absolute value <=1e9 '
    '(including clipping bounds and denominators); this differs from the <=1e100 '
    'runtime intermediate limit. Do not use literals such as 1e90 or 1e100.')

U_TASK = '''Design a deterministic heuristic selector U for static FJSP, not an action priority rule h.
Before each step, the host enumerates each unfinished job's next operation and its allowed machines.
The host computes the state, calls U exactly ONCE, and uses ONLY the selected h to score ALL legal pairs.
Execute the highest-scoring action, break ties by job then machine index, and append it to the machine's end.
Continue until all operations are scheduled. Terminal states do not call U. Online scheduling never calls an LLM.
An external evaluator measures complete feasible schedules on ALL training instances, using mean(-makespan/LB).
Higher fitness is better. LB=max(longest job's shortest processing-time sum, total shortest processing-time sum/machine count).
Any failed instance invalidates the candidate; there is no partial-batch mean or fallback heuristic.
Generate only U, without changing H, the state calculator, scheduler or evaluator.
Inputs (these are STATE summaries, not h's single-action inputs):
progress=scheduled operation count / total operation count of the instance, NOT elapsed-time progress or population size.
candidate_pair_ratio=legal operation-machine pair count/C; C=sum over jobs of the maximum alternatives of any operation in that job.
remaining_work_mean/std: for each UNFINISHED job, sum shortest alternative processing times for all unscheduled operations,
including the current operation; divide by T, then take mean and population standard deviation (ddof=0).
machine_ready_mean/std: mean and population standard deviation of ALL machines' current end times divided by T,
including unused machines. These summaries do not identify a particular bottleneck machine.
T=sum of the maximum alternative processing time over ALL operations. T and C stay fixed; they are NOT extra inputs.
previous_heuristic=-1 at the first step, otherwise the previous member id; it contains no rewards or improvement history.
Use only these seven inputs, local calculations and fixed constants. Same input must yield the same output.
Do not call H, parents or evaluators; simulate schedules; access external resources; infer extra state; or retain mutable state.
Member ids are categories, not quality ranks: do not average ids or infer quality from their magnitude.
Every path returns a built-in Python int within the legal range, NEVER bool. Handle the first step and avoid division by zero.
A constant selector is legal. Do not force switching, use of every member/input, or a particular decision-tree skeleton.
Do not invent performance evidence, state-level winners, rewards or failure examples.
'''

from .state_diagnostics import BOUND_TEXT
U_TASK += BOUND_TEXT

H_CONTEXT = '''H INFORMATION FOR OFFLINE U DESIGN ONLY (do NOT generate h):
The following interface defines h's SINGLE operation-machine action inputs, all in RAW, unnormalised units.
processing_time: duration of the candidate operation on this candidate machine.
remaining_work: sum of shortest alternative durations for this job's unscheduled operations, INCLUDING the current one.
remaining_operations: number of this job's unscheduled operations, INCLUDING the current one.
job_ready_time: completion time of the job's previously scheduled operation, or zero initially.
machine_ready_time: end time of this machine's current schedule, or zero initially.
earliest_start=max(job_ready_time, machine_ready_time).
earliest_finish=earliest_start+processing_time.
h returns a finite real scalar, not bool; HIGHER scores win, with job/machine index ties.
These action features are NOT additional U inputs. The host calls the chosen h for each legal action.
Read the actual member code and reviewed behavior below. A state-to-member match is a hypothesis, not proven local superiority.
H code is design context, not permission for U to execute H, parents or a lookahead simulator.
'''

INITIAL = '''There are no parents. Create an independent deterministic selector from the given state interface.
Only member count and legal ids are known; ids do not imply quality. Do not assert that any id is better at a particular stage.
'''

P_CROSS = '''Compare how the supplied parents map available state information to H members, using H's actual behavior.
Try to combine the decision ideas of AT LEAST TWO parents into a new selection relationship.
You may change state conditions, relations between conditions, member mappings and parameters, or rewrite the WHOLE function.
Do not require fixed modules, literal code splicing, or a particular program skeleton.
Resolve conflicting choices using the available state and H behavior, not simply parent order.
Different parents do not prove complementarity; whole-instance results do not establish state-level winners.
In the common at-most-three-sentence explanation, identify which parental decision ideas were inherited and how they were combined.
Return one complete new U. Its benefit is a hypothesis to be tested by external complete-schedule evaluation.
'''

P_MUTATE = '''Identify the single parent's main selection logic and organise the change around ONE MAIN MODIFICATION HYPOTHESIS.
Ground the reason in the parent's actual logic, the available state or H's actual behavior.
You may change feature roles, condition relationships, state-to-member mappings, hold/switch conditions or thresholds,
or remove redundant decisions. One hypothesis does not mean one changed line or only a local replacement:
you may rewrite the WHOLE function and related logic as needed.
Changing only names, formatting or explanation is not a meaningful strategy modification.
Without evaluation evidence, do not claim the parent chose wrongly or invent failures, rewards or improvements.
Keep selection logic that still has a reason to remain; do not force more members or more switches.
In the common at-most-three-sentence explanation, state the main change and its rationale. Return one complete new U.
'''


def prompt_sections(arm, operator, parents, members, *, kind='U'):
    if arm not in ('B0', 'B1', 'B2', 'P', 'H') or operator not in FOUNDATIONAL:
        raise ValueError('unknown arm/operator')
    if kind not in ('U', 'h') or (kind == 'h') != (arm == 'H'):
        raise ValueError('H prompts require h kind; selector prompts require U kind')
    if operator == 'I1' and parents:
        raise ValueError('initialisation must be independent')
    if kind == 'U':
        if len(members) < 2:
            raise ValueError('selector prompt requires at least two members')
        common = U_TASK + f'Legal member ids: 0 <= id < {len(members)}.\n'
        interface = 'def select_heuristic(' + ', '.join(U_ARGS) + '):'
        if operator != 'I1' and arm != 'B0':
            common += H_CONTEXT + 'def priority(' + ', '.join(H_ARGS) + '):\n'
            for index, member in enumerate(members):
                common += f'\nH MEMBER {index}\nBehavior: {member.description}\nCode:\n{member.code}\n'
    else:
        common = H_CONTRACT
        interface = 'def priority(' + ', '.join(H_ARGS) + '):'
    instruction = INITIAL if operator == 'I1' and kind == 'U' else FOUNDATIONAL[operator]
    if arm == 'P' and operator in ('CROSS', 'MUTATE'):
        if ((operator == 'CROSS' and len(parents) < 2)
                or (operator == 'MUTATE' and len(parents) != 1)):
            raise ValueError('P crossover requires multiple parents; mutation exactly one')
        instruction = P_CROSS if operator == 'CROSS' else P_MUTATE
    parent_text = ''.join(f'\nPARENT {i}\nDescription: {p["candidate"]["description"]}\nCode:\n{p["candidate"]["code"]}\n'
                          for i, p in enumerate(parents))
    return {'task_and_H': common, 'parents': parent_text, 'operator': instruction,
            'output_and_interface': V5_OUTPUT + '\n' + interface}


def build_prompt(arm, operator, parents, members, *, kind='U'):
    return '\n'.join(prompt_sections(arm, operator, parents, members, kind=kind).values())


def prompt_manifest():
    from .initialization import NOVELTY_VERSION, NOVELTY_INSTRUCTION, ARCHIVE_MAX_BYTES
    templates = {'U_task': U_TASK, 'H_context': H_CONTEXT, 'H_generation': H_CONTRACT,
                 'initial': INITIAL, 'P_cross': P_CROSS, 'P_mutate': P_MUTATE,
                 'generic_operators': FOUNDATIONAL, 'output': V5_OUTPUT,
                 'shared_initial_novelty': NOVELTY_INSTRUCTION}
    return {'version': PROMPT_VERSION, 'framework': FRAMEWORK_URL,
            'template_sha256': digest(templates), 'sections': {k: digest(v) for k, v in templates.items()},
            'B2_P_difference': 'operator section only', 'initial_H_details': False,
            'B0_H_details': False, 'model_calls_per_candidate': 1,
            'shared_initial_novelty': {'version': NOVELTY_VERSION,
                'archive_max_bytes': ARCHIVE_MAX_BYTES, 'content': 'accepted U code only',
                'fitness_or_H_details': False,
                'deduplication': 'validated AST plus pure integer return/int(integer)'}}
