"""Versioned shared-U novelty context and conservative equivalence checks.

No fitness, H details or synthetic state labels enter the novelty archive.
Candidate keys and frozen assets are unchanged. This is not a general semantic
equivalence checker: only a pure integer return/int(integer) is additionally
normalised beyond the validator's existing AST canonicalisation.
"""

import ast

from fjsp_usage.research.candidates import validate_code

NOVELTY_VERSION = 'shared-U-novelty-v1-20261010'
ARCHIVE_MAX_BYTES = 131072
NOVELTY_INSTRUCTION = '''SHARED INITIALISATION NOVELTY CONTEXT
The archive below contains previously accepted selector CODE ONLY, without performance evidence.
These are not parents, crossover inputs, a ranking, or examples of good choices.
Create an independent selector whose state-to-member selection logic differs from archived logic.
Do not merely change names, formatting, explanation, or wrap an integer return in int().
No H behavior or state-level winner information is supplied. Do not invent such evidence.
A constant selector remains legal if its selected id is not an archived constant selection.
Do not force switching, all members, all inputs, any prescribed skeleton or thresholds.
This context is shared by all four groups; no group-specific initialization is performed.
'''


def selector_signature(code):
    """Validate first; prove only the narrowly stated constant equivalence."""
    checked = validate_code(code, kind='U')
    function = ast.parse(checked.code).body[0]
    if len(function.body) == 1 and isinstance(function.body[0], ast.Return):
        value = function.body[0].value
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id == 'int' and len(value.args) == 1
                and not value.keywords):
            value = value.args[0]
        sign = 1
        if isinstance(value, ast.UnaryOp) and isinstance(value.op, (ast.UAdd, ast.USub)):
            sign = -1 if isinstance(value.op, ast.USub) else 1
            value = value.operand
        if isinstance(value, ast.Constant) and type(value.value) is int:
            return 'constant-int:' + str(sign * value.value)
    return 'validated-ast:' + checked.key


def initialization_prompt(base, population, index, *, max_archive_bytes=ARCHIVE_MAX_BYTES):
    """Stable source-key order, complete entries only, no row metadata."""
    if type(index) is not int or index < 0:
        raise ValueError('initialization index must be a nonnegative integer')
    if type(max_archive_bytes) is not int or max_archive_bytes < 0:
        raise ValueError('archive byte limit must be a nonnegative integer')
    codes = {}
    for row in population:
        candidate = validate_code(row['candidate']['code'], kind='U')
        codes[candidate.key] = candidate.code
    entries, used, omitted = [], 0, 0
    for key, code in sorted(codes.items()):
        entry = '\nARCHIVED SELECTOR ' + key + '\n```python\n' + code + '```\n'
        size = len(entry.encode('utf-8'))
        if used + size > max_archive_bytes:
            omitted += 1
            continue
        entries.append(entry)
        used += size
    header = (f'\n{NOVELTY_INSTRUCTION}\nIndependent request index: {index}. '
              'The index is a trace identifier, not a quality rank or member mapping.\n'
              f'Archive entries included: {len(entries)}; omitted by byte limit: {omitted}.\n')
    return base + header + ''.join(entries)
