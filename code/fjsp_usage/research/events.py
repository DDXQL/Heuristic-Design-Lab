"""Small append-only event stream; full action traces are opt-in."""

import json
import time
from pathlib import Path


class Events:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, kind: str, **fields):
        record = {'time_unix': time.time(), 'kind': kind, **fields}
        with self.path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')


def atomic_json(path: str | Path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + '.tmp')
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
                       + '\n', encoding='utf-8')
    pending.replace(path)
