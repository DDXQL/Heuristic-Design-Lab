"""Relocate a sealed snapshot reference without rewriting its historical receipt."""
from pathlib import Path

def relocated_snapshot_source(recorded_file, recorded_snapshot, local_snapshot):
    recorded = Path(recorded_file)
    origin = Path(recorded_snapshot)
    if not recorded.is_absolute() or not origin.is_absolute():
        raise ValueError('explicit historical absolute snapshot paths required')
    relative = recorded.relative_to(origin)
    if '..' in relative.parts:
        raise ValueError('snapshot path traversal')
    root = Path(local_snapshot).resolve()
    source = (root / relative).resolve()
    if not source.is_relative_to(root):
        raise ValueError('snapshot symlink escapes local root')
    # The caller must still match both the receipt SHA and protocol snapshot SHA.
    return source, str(relative)
