"""Read only the six audited TSP histories via the normal cluster SSH login."""

import argparse
from collections import defaultdict
import csv
import io
import json
import math
from pathlib import Path
import subprocess
import tempfile
import zipfile

from figure_training_history import COLUMNS


TOOLS = Path(__file__).resolve().parent
OUTBOX = TOOLS.parents[1] / 'transfer-outbox'
ARCHIVE = OUTBOX / 'tsp-r15-champions-20261124.zip'
DESTINATION = OUTBOX / 'tsp-training-history-20261125.csv'
REMOTE_COMMAND = 'exec "$HOME/hdl-envs/portable-v2/bin/python" -I -B -'


def audited_members(archive):
    with zipfile.ZipFile(archive) as packet:
        audit = json.loads(packet.read('audit.json'))['evidence']
        members = []
        for method in ('u', 'eoh'):
            for seed in (501, 502, 503):
                key = f'{method}-{seed}'
                row = audit[key]
                summary = json.loads(packet.read(f'{key}/exports/summary.json'))
                if (row['selection_verified'] is not True or summary['engineering_only'] is not False
                        or summary['phase'] != 'completed' or summary['successful_evolution_responses'] != 1000):
                    raise ValueError(f'{key}: training closeout is incomplete')
                members.append(dict(method=method, seed=seed, run_dir=row['run_dir'],
                                    identity=row['protocol_sha256'], checkpoint=row['checkpoint_sha256'],
                                    best=summary['best_J']))
    return members


def remote_program(members):
    source = (TOOLS / 'figure_training_history.py').read_text()
    return f"""\
import csv, hashlib, math, sys
from pathlib import Path
namespace = {{'__name__': 'training_history_extract'}}
exec({source!r}, namespace)
rows = []
for member in {members!r}:
    run = Path(member['run_dir'])
    assert hashlib.sha256((run / 'checkpoint.json').read_bytes()).hexdigest() == member['checkpoint'], f'{{run.name}}: audited checkpoint differs'
    data = namespace['checkpoint_series'](run)
    assert len(data) == 1000, f'{{run.name}}: expected 1000 settled evolution returns'
    first, last = data[0], data[-1]
    assert first['protocol_sha256'] == member['identity'] and first['problem'] == 'tsp', f'{{run.name}}: protocol differs'
    assert first['method'] == member['method'] and first['seed'] == member['seed'] and first['phase'] == 'completed', f'{{run.name}}: training identity differs'
    assert math.isclose(last['best_J'], member['best'], rel_tol=0, abs_tol=1e-12), f'{{run.name}}: curve endpoint differs from champion'
    rows.extend(data)
writer = csv.DictWriter(sys.stdout, fieldnames=namespace['COLUMNS'], lineterminator='\\n')
writer.writeheader()
writer.writerows(rows)
"""


def validate(raw, members):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8')))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise ValueError('unexpected cluster response, expected the exact CSV header')
    groups = defaultdict(list)
    for row in reader:
        groups[row['method'], int(row['seed'])].append(row)
    if set(groups) != {(r['method'], r['seed']) for r in members}:
        raise ValueError('expected exactly U and EoH seeds 501–503')
    for m in members:
        data = groups[m['method'], m['seed']]
        if (tuple(int(r['step']) for r in data) != tuple(range(1, 1001))
                or not all(r['problem'] == 'tsp' and r['phase'] == 'completed'
                           and r['count_basis'] == 'successful_responses' and r['target'] == '1000'
                           and r['protocol_sha256'] == m['identity'] for r in data)
                or not math.isclose(float(data[-1]['best_J']), m['best'], rel_tol=0, abs_tol=1e-12)):
            raise ValueError(f"{m['method']} {m['seed']}: incomplete or inconsistent history")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=ARCHIVE)
    parser.add_argument('--output', type=Path, default=DESTINATION)
    parser.add_argument('--host', default='hdl-cluster', help='SSH host alias in your local SSH config')
    args = parser.parse_args()
    members = audited_members(args.archive)
    payload = remote_program(members).encode('utf-8')
    print('使用平时的集群登录方式。若有密码提示，请在终端输入，脚本不会保存密码。', flush=True)
    command = ('ssh', '-T', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=yes',
               '--', args.host, REMOTE_COMMAND)
    raw = subprocess.run(command, input=payload, stdout=subprocess.PIPE, check=True).stdout
    validate(raw, members)
    with tempfile.NamedTemporaryFile(mode='wb', dir=args.output.parent, prefix='.tsp-history-', delete=False) as temp:
        temp.write(raw)
        temporary = Path(temp.name)
    temporary.replace(args.output)
    print(f'已核验 U 和 EoH 六个种子，共 6000 条候选进度：{args.output}')


if __name__ == '__main__':
    main()
