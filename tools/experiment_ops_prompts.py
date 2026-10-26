"""Editable routing layer; existing frozen prompt packs remain untouched."""
from pathlib import Path
from tools import h01_weight_search as h01
from tools import ind_evo_h01 as previous
from tools import b1_usage_prompts as ten
from fjsp_usage.cross_feedback_ab import render


def build(config,task,parents,members):
    op=task['operator']
    if config['type']=='cross_ab':
        text=render(task['condition'],parents,members,
                    [p['fitness'] for p in parents] if task['condition']=='B' else None)
    elif config['space']=='h01':
        text=previous.independent_prompt(members) if op=='I1' else h01.build_prompt('B',op,parents,members)
    else:
        text=ten.build_prompt('B',op,parents,members)
    # Optional research edit is isolated in a NEW file/run, never frozen packs.
    # The single literal marker avoids Python format braces in program source.
    override=config.get('prompt_overrides',{}).get(op)
    if override:
        template=Path(override).read_text()
        if template.count('{{BASE_PROMPT}}')!=1:raise ValueError('override requires exactly one {{BASE_PROMPT}}')
        text=template.replace('{{BASE_PROMPT}}',text)
    return text
