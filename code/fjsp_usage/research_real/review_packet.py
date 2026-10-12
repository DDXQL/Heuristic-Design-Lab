"""Export code and full train evidence; human review fields always start blank."""

import json
from pathlib import Path

from fjsp_usage.research.events import atomic_json
from .assets import checked_candidate, check_result, check_receipt, seal
from .review_execution import score_samples, ReviewExecutionError


def write_review_packet(directory, rows, names, *, mode, context, source_hash, timeout=3):
    directory = Path(directory)
    packet_rows = []
    for row in rows:
        candidate = checked_candidate(row['candidate'], 'h')
        check_result(row['training_result'], names)
        if not row['training_result']['valid']:
            raise ValueError('review packet requires complete valid train evaluation')
        check_receipt(row['receipt'], candidate, mode)
        try:
            samples = {'valid': True, 'samples': score_samples(candidate, timeout=timeout)}
        except ReviewExecutionError as exc:
            samples = {'valid': False, 'error': str(exc)}
        packet_rows.append({'id': row['id'], 'candidate': row['candidate'],
            'training_result': row['training_result'], 'receipt': row['receipt'],
            'automatic_samples': samples, 'human_review_status': 'pending'})
    packet = seal({'kind': 'H_review_packet', 'mode': mode, 'context': context,
        'source_hash': source_hash, 'training_files': list(names), 'rows': packet_rows,
        'notice': 'Automatic samples are NOT human behavior approval. Read actual code and complete the separate review file.'})
    atomic_json(directory/'H_review_packet.json', packet)
    template = directory/'H_review_template.json'
    blanks = {r['candidate']['key']: dict.fromkeys(('description','reviewer','method','note'), '')
              for r in rows}
    if not template.exists():
        atomic_json(template, blanks)
    elif set(json.loads(template.read_text())) != set(blanks):
        raise ValueError('existing review template belongs to different candidates; not overwritten')
    lines = ['# H 人工行为审查材料', '', packet['notice'], '',
        f'来源摘要：{source_hash}', f'训练实例数：{len(names)}', '',
        '请另存并填写 H_review_template.json 的四个字段；描述实际代码的高分偏好，记录审查人、方法与备注。',
        '评分样例和训练成绩不能代替人工阅读。空字段或失败样例不能通过冻结。', '']
    for row in packet_rows:
        lines += [f'## {row["id"]}', '', f'代码键：{row["candidate"]["key"]}',
            f'完整训练 fitness：{row["training_result"]["fitness"]}', '',
            '模型生成说明（尚未人工确认）：'+row['candidate']['description'], '',
            '```python', row['candidate']['code'].rstrip(), '```', '',
            '自动样例：'+json.dumps(row['automatic_samples'], ensure_ascii=False), '']
    (directory/'H_review_packet.md').write_text('\n'.join(lines)+'\n')
    return packet
