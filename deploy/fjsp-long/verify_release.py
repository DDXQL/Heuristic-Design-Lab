#!/usr/bin/env python3
"""Verify the local release manifest; no credentials, requests or evaluation."""
import hashlib
import json
from pathlib import Path

root=Path(__file__).resolve().parents[2]
release=json.loads((root/'release.json').read_text())
for name,expected in release['files'].items():
    path=(root/name).resolve()
    if not path.is_relative_to(root) or (root/name).is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise SystemExit('Release file identity mismatch: '+name)
print(json.dumps({'verified':True,'commit':release['commit'],'files':len(release['files']),
                  'model_requests':0,'solves':0,'launch_authorized':False},indent=2))
