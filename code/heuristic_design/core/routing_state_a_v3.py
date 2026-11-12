"""Versioned literal per-H array reads on the existing closed pure-selector language."""
import ast
import json
from collections import Counter

from . import routing as language, routing_state_a as v2
from . import state_a_v3 as state

ABI = state.U_ABI
CandidateError = language.CandidateError
_CONTRACT = dict(_fields=state.FIELDS, _abi=ABI, _spec=state.SPEC_SHA256,
                 _vector_fields=state.H_FIELDS, _vector_masks=True)


def validate(code, description='', member_count=10):
    return language.validate(code, description, member_count, **_CONTRACT)


def checked(row, members):
    return language.checked(row, members, **_CONTRACT)


def parse(text, members):
    return language.parse(text, members, **_CONTRACT)


class _Tracked:
    def __init__(self, data, counts, path=''):
        self.data, self.counts, self.path = data, counts, path

    def __getitem__(self, key):
        value = self.data[key]
        path = f'{self.path}[{key}]' if isinstance(self.data, (tuple, list)) else self.path + str(key)
        if isinstance(value, (tuple, list)):
            return _Tracked(value, self.counts, path)
        if key == 'availability' and not self.path:
            return _Tracked(value, self.counts, 'availability.')
        self.counts[path] += 1
        return value


def compile_candidate(candidate, members, *, reads=None):
    fn = language.compile_candidate(candidate, members, **_CONTRACT)
    if reads is not None and not isinstance(reads, Counter):
        raise ValueError('reads must be a Counter or None')

    def route(packet):
        state.validate_packet(packet, members)
        return fn(_Tracked(packet, reads) if reads is not None else packet)
    return route


def inspect_reads(code, member_count=10):
    candidate = validate(code, member_count=member_count)
    tree = ast.parse(candidate.code)
    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    paths = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        parent = parents.get(id(node))
        if isinstance(parent, ast.Subscript) and parent.value is node:
            continue
        keys, value = [], node
        while isinstance(value, ast.Subscript):
            keys.append(value.slice.value)
            value = value.value
        keys.reverse()
        paths.add(('availability.' + keys[1] if keys[0] == 'availability' else keys[0])
                  + (f'[{keys[-1]}]' if type(keys[-1]) is int else ''))
    return {'abi': ABI, 'spec_sha256': state.SPEC_SHA256, 'code_key': candidate.key, 'read_paths': sorted(paths)}


def _replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('frozen v2 prompt anchor changed; inspect before using v3')
    return text.replace(old, new, 1)


def build_prompt(problem, task, parents, members, *, window=state.WINDOW):
    for row in parents:
        checked(row['candidate'], len(members))
    # Reuse frozen task/H/score language verbatim, replacing only the versioned
    # state boundary and original-parent payload. No v2 file or prompt changes.
    text = v2.build_prompt(problem, task, [], members, window=window)
    text = _replace_once(text, v2.ABI, ABI)
    text = _replace_once(text, v2.SPEC_SHA256, state.SPEC_SHA256)
    text = _replace_once(text,
        'Read only literal state["field"] and state["availability"]["field"]. Host metadata is not readable.',
        'Read old scalar fields with state["field"] and state["availability"]["field"]. '
        f'Four additional H arrays each have K={len(members)} items in frozen H order. '
        'Read state["h_usage_count"][0] or another literal member index; per-item masks are '
        'state["availability"]["h_recent_delta_mean"][0]. Whole-array reads and aliases are forbidden. '
        'Guard missing entries by their per-item availability. Host metadata is not readable.')
    text = _replace_once(text, 'None means no statistical object: first history or OBP no opened bins.',
        'None means no statistical object: first history, OBP no opened bins, never-used H gap, '
        'or H with no sample in the current global ten-commit window.')
    text = _replace_once(text, 'Original parents:\n[]', 'Original parents:\n' + json.dumps(
        [{'id': p['id'], 'candidate': p['candidate']} for p in parents], ensure_ascii=False, sort_keys=True))
    return text + '\nPer-H fields:\n' + json.dumps(state.H_DEFINITIONS, ensure_ascii=False, sort_keys=True) + (
        '\nCounts are successful action commits, not per-action H scoring calls. '
        'All H records reset for each instance and candidate. Update only after a real commit. '
        'The window is the last ten GLOBAL commits, not the last ten uses of each H. '
        'A zero count is available; an absent per-H mean or gap is None, never zero-filled. '
        'These actual costs are not H rewards, counterfactual values or quality ranks. '
        'Do not add offline complete-solve priors, H previews or online model requests.')
