"""Single-writer run lock with conservative stale-local-process recovery."""

import json
import os
from pathlib import Path
import socket


class RunLock:
    def __init__(self, directory):
        self.path = Path(directory) / '.writer.lock'
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    json.dump({'pid': os.getpid(), 'host': socket.gethostname()}, stream)
                return self
            except FileExistsError:
                try:
                    owner = json.loads(self.path.read_text())
                    if owner['host'] != socket.gethostname():
                        raise RuntimeError('run directory is locked by another host')
                    os.kill(owner['pid'], 0)
                except ProcessLookupError:
                    self.path.unlink()
                    continue
                raise RuntimeError('run directory already has an active writer')
        raise RuntimeError('cannot acquire run lock')

    def __exit__(self, *args):
        self.path.unlink()
