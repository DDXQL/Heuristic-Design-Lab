"""Paired mode ablation: only allowed-modes differs, not feedback or guidance."""
from fjsp_usage.research_real.prompts import U_TASK as LEGACY_TASK,H_CONTEXT,P_CROSS,P_MUTATE
from fjsp_usage.research.prompts import OUTPUT
from fjsp_usage.research.candidates import U_ARGS,H_ARGS
from fjsp_usage.research.protocol import digest
from . import VERSION,LANGUAGE,NORMALIZATION,HISTORY

PROMPT_VERSION='FJSP-usage-prompts-v2.2-strategy-space-20261013'
# The seven-state task/bounds stay verbatim except the three old-only statements.
TASK=LEGACY_TASK.replace('heuristic selector U', 'heuristic-usage strategy U').replace('uses ONLY the selected h to score ALL legal pairs.',
    'uses only the members selected by your output to score ALL legal pairs.').replace(
    'Every path returns a built-in Python int within the legal range, NEVER bool.',
    'Every path returns exactly (mode, (v0, ..., vK_minus_1)). Mode is a built-in int, never bool.').replace(
    'previous_heuristic=-1 at the first step, otherwise the previous member id;',
    'previous_heuristic=-1 at the first step, otherwise the largest normalized-weight member id (ties: smallest id);')
TASK+='''
Use the fixed ordered H. Vector entry i refers to member i; vector length MUST be K.
All vector entries must be built-in int or float, NEVER bool; local boolean comparisons remain legal.
Construct the two-level tuple literal directly in each return; do not store tuples in variables or use lists/indexing.
SELECT mode=0: vector entries are finite member-selection scores, allowed negative.
The host picks argmax, EXACT ties to lowest member id; all-zero scores are legal.
MIX mode=1: vector entries are finite nonnegative raw weights with exactly one or two positive entries.
The host normalizes by positive maximum then sum; all-zero or more than two positives fails, without repair.
Within the permitted modes, member scores, active members, weights and mode may depend on the seven inputs.
Scores or weights may use constants, conditions, linear or nonlinear local expressions within the allowed language;
no formula, phase partition or program skeleton is prescribed. A score formula may contain if;
a condition may produce weights. Program syntax alone does not determine the usage mechanism.
For MIX, compute the one- or two-member support yourself; the host does not select top-two scores for you.
One active member scores actions in raw units, exactly like the original single-member executor.
Two active members each score every CURRENT legal action once. The host min-max normalizes each complete action column
and takes the nonnegative weighted sum. A constant column becomes zero, without reallocating its weight.
Final action ties use job then machine id. This rule is fixed by the host, not configurable by your program.
Member-selection scores, mixture weights, raw h action scores and final combined action scores are distinct quantities.
Your program does not receive action scores/lists and must NOT call h or simulate future schedules.
The historical dominant id loses the other member and weight proportions; do not invent those inputs.
Constant SELECT and single-member MIX are legal where the mode is permitted; do not force mixtures or switching.
These rules are engineering semantics, not evidence that combinations or any members perform better.
'''
NEW_OUTPUT=OUTPUT.replace('No imports, attributes, containers, helper functions, globals, recursion,',
    'Only the terminal two-level tuple (mode, (scalar,...)) is permitted; no other containers, indexing, imports, attributes, helper functions, globals, recursion,')
NEW_OUTPUT+=' No return annotation. Numeric literals <=1e9; scalar intermediates/output fields finite with absolute value <=1e100.'
NOVELTY='''SHARED SELECT INITIALISATION NOVELTY CONTEXT
Previously accepted source CODE ONLY is below, not parents, ranked examples or performance evidence.
Create an independent SELECT strategy with different logic; formatting/renaming does not ensure diversity.
Constants and unused inputs/members are legal; no prescribed skeleton or decision-tree form.
SELECT may compare state-dependent member scores instead of explicitly branching on a member id.
Do not force switching. No H behavior or scores are given during shared initialization.
Only validated AST source keys are deduplicated; no broad equivalence or equal-fitness claims.
'''

# Extend only this versioned pack; the original single-member operators stay intact.
CROSS=P_CROSS.replace('member mappings and parameters,',
    'member mappings and parameters, member-score formulas and, where permitted, support and weight formulas,')
MUTATE=P_MUTATE.replace('hold/switch conditions or thresholds,',
    'hold/switch conditions or thresholds, member-score formulas and, where permitted, support, weight or mode rules,')


def prompt_sections(arm,operator,parents,members,*,kind='U'):
    if kind!='U' or operator not in ('I1','CROSS','MUTATE') or arm not in ('A','B','INIT','B0'):
        raise ValueError('usage experiment supports shared I1 and paired specialized CROSS/MUTATE only')
    if operator=='I1' and parents: raise ValueError('initialization has no parents')
    if operator=='CROSS' and len(parents)<2: raise ValueError('crossover requires multiple parents')
    if operator=='MUTATE' and len(parents)!=1: raise ValueError('mutation requires one parent')
    if len(members)<2: raise ValueError('fixed H must have at least two members')
    context=f'K={len(members)}; ordered member ids 0 through {len(members)-1}.\n'
    if operator!='I1':
        context+=H_CONTEXT.replace('The host calls the chosen h for each legal action.',
            'The host calls only the active members for each legal action.')
        context+='def priority('+', '.join(H_ARGS)+'):\n'
        for i,m in enumerate(members):context+=f'\nH MEMBER {i}\nBehavior: {m.description}\nCode:\n{m.code}\n'
    allowed='Permitted modes: SELECT (0) ONLY.' if operator=='I1' or arm in ('A','INIT','B0') else 'Permitted modes: SELECT (0) OR MIX (1); at most two positive MIX weights.'
    initial='There are no parents. Create an independent SELECT program; member ids do not imply quality.'
    operation=initial if operator=='I1' else (CROSS if operator=='CROSS' else MUTATE)
    # Same replacement in BOTH groups; extra guidance never targets B alone.
    operation=operation.replace('selection relationship','usage relationship').replace('selector','usage program')
    return {'task':TASK,'allowed_modes':allowed,'H_context':context,
        'parents':''.join(f'\nPARENT {i}\nDescription: {p["candidate"]["description"]}\nCode:\n{p["candidate"]["code"]}\n' for i,p in enumerate(parents)),
        'operator':operation,'output':NEW_OUTPUT+'\ndef use_heuristics('+', '.join(U_ARGS)+'):'}


def build_prompt(arm,operator,parents,members,*,kind='U'):
    return '\n'.join(prompt_sections(arm,operator,parents,members,kind=kind).values())


def prompt_manifest():
    parts={'task':TASK,'H_context':H_CONTEXT,'cross':CROSS,'mutate':MUTATE,'output':NEW_OUTPUT,'novelty':NOVELTY}
    return {'version':PROMPT_VERSION,'interface':VERSION,'language':LANGUAGE,'normalization':NORMALIZATION,
        'history':HISTORY,'template_sha256':digest(parts),'sections':{k:digest(v) for k,v in parts.items()},
        'A_B_difference':'allowed_modes section only, before parent populations diverge',
        'shared_initialization':'SELECT only, no H behavior, no training feedback','deduplication':'validated versioned AST only'}
