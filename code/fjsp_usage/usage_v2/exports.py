"""Complete reviewable prompt exports with explicit nonpopulation preview parents."""
from dataclasses import asdict
from pathlib import Path
import difflib
from fjsp_usage.research.candidates import U_ARGS,validate_code
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.initialization import initialization_prompt
from .prompts import prompt_sections,build_prompt,NOVELTY,prompt_manifest
from . import VERSION


def preview_parents(size):
    rows=[]
    for k in range(5):
        values=','.join('progress + '+str((i+k)%size/10) for i in range(size))
        code='def use_heuristics('+', '.join(U_ARGS)+'):\n    return (0, ('+values+'))\n'
        c=validate_code(code,description='Handwritten prompt preview only; not a real parent or population member.',kind='U',interface_version=VERSION,member_count=size)
        rows.append({'id':'HANDWRITTEN_PREVIEW_'+str(k),'candidate':asdict(c)})
    return rows


def export_prompts(directory,members,max_prompt_bytes):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    parents=preview_parents(len(members));records=[]
    for op in ('I1','CROSS','MUTATE'):
        selected=[] if op=='I1' else (parents if op=='CROSS' else parents[:1])
        texts={};sections={}
        for arm in ('A','B'):
            section=prompt_sections(arm,op,selected,members);text=build_prompt(arm,op,selected,members)
            if op=='I1':text=initialization_prompt(text,[],0,instruction=NOVELTY,interface_version=VERSION)
            if len(text.encode())>max_prompt_bytes:raise ValueError('preview prompt exceeds exact provider byte limit')
            (directory/f'{arm}.{op}.txt').write_text(text)
            sections[arm]=section;texts[arm]=text
        changed=[k for k,v in sections['A'].items() if sections['B'][k]!=v]
        assert changed==([] if op=='I1' else ['allowed_modes'])
        delta=''.join(difflib.unified_diff(texts['A'].splitlines(True),texts['B'].splitlines(True),fromfile='A',tofile='B'))
        (directory/f'{op}.diff').write_text(delta)
        records.append({'operator':op,'changed_sections':changed,'A_sha256':digest(texts['A']),'B_sha256':digest(texts['B']),
            'A_bytes':len(texts['A'].encode()),'B_bytes':len(texts['B'].encode())})
    result={'prompt_pack':prompt_manifest(),'comparison':records,'parents':parents,
        'notice':'Full first initialization prompt has empty archive. CROSS/MUTATE use same HANDWRITTEN preview parents only; never imported into real P0. Later exact prompts bind actual archived/selected source in request journals.',
        'performance_feedback':False}
    atomic_json(directory/'Prompt_comparison.json',result)
    return result
