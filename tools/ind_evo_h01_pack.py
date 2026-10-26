"""Archive original primary evidence, avoiding redundant per-instance row copies.

Full result/raw_result files already contain every successful original row with
its schedules/costs. Redundant Behnke*.result.json remain intact in the local run.
"""
import hashlib
import json
from pathlib import Path
import tarfile
from tools import ind_evo_h01 as x


def main():
    files=[];duplicate=[]
    for p in sorted(x.RUN.rglob('*')):
        if not p.is_file():continue
        if p.parent.parent.name=='evaluations' and p.name.startswith('Behnke') and p.name.endswith('.result.json'):
            duplicate.append(str(p.relative_to(x.ROOT)));continue
        files.append(p)
    manifest={str(p.relative_to(x.ROOT)):{'sha256':x.sha(p),'bytes':p.stat().st_size} for p in files}
    archive=x.REPORT/'Raw_primary_evidence.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for p in files:tar.add(p,arcname=str(p.relative_to(x.ROOT)),recursive=False)
    with tarfile.open(archive,'r:gz') as tar:
        for entry in tar:
            data=tar.extractfile(entry).read()
            if hashlib.sha256(data).hexdigest()!=manifest[entry.name]['sha256']:raise ValueError('archive roundtrip mismatch')
    if any(x.sha(x.ROOT/name)!=r['sha256'] for name,r in manifest.items()):raise ValueError('input changed during archiving')
    x.write(x.REPORT/'Raw_primary_manifest.json',{'archive':archive.name,'archive_sha256':x.sha(archive),
        'files':manifest,'duplicate_row_files_left_in_local_run':duplicate,
        'packing_notice':'Only redundant per-instance result copies omitted; identical row data included in original full result/raw_result JSON. No local raw record deleted.',
        'archive_roundtrip_verified':True,'input_unchanged':True})
    print({'primary_files':len(files),'redundant_row_copies_not_packed':len(duplicate),'archive_bytes':archive.stat().st_size})


if __name__=='__main__':main()
