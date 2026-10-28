#!/usr/bin/env python3
"""Read historical TSP evidence through a verified manifest, with no execution.

Original absolute paths are interpreted only as names under the source root.
They are never opened or rewritten. This tool has no API/solver/resume imports.
"""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(1024*1024):h.update(block)
    return h.hexdigest()


class EvidenceVault:
    def __init__(self,receipt,vault=None):
        receipt=json.loads(Path(receipt).read_text())
        self.root=Path(vault or receipt['vault']).resolve()
        path=self.root/'Manifest.json'
        if sha(path)!=receipt['manifest_sha256']:raise ValueError('migration manifest hash mismatch')
        self.manifest=json.loads(path.read_text());self.source=Path(self.manifest['source_root'])
        if self.manifest['workspace']!='workspace':raise ValueError('unexpected archive layout')
        self.workspace=(self.root/'workspace').resolve()
        if not self.workspace.is_relative_to(self.root):raise ValueError('archive workspace escapes vault')

    def relative(self,value):
        p=Path(value)
        if p.is_absolute():
            try:p=p.relative_to(self.source)
            except ValueError as exc:raise ValueError('foreign historical path') from exc
        if '..' in p.parts or str(p) not in self.manifest['files']:raise ValueError('path not in preserved manifest')
        return str(p)

    def path(self,value):
        relative=self.relative(value);p=(self.workspace/relative).resolve()
        if not p.is_relative_to(self.workspace):raise ValueError('archive path escapes workspace')
        if sha(p)!=self.manifest['files'][relative]['sha256']:raise ValueError('preserved file changed: '+relative)
        return p

    def read(self,value):return json.loads(self.path(value).read_text())

    def verify_all(self):
        for name in self.manifest['files']:self.path(name)
        return {'files':len(self.manifest['files']),'bytes':sum(r['bytes'] for r in self.manifest['files'].values())}

    def status(self,name):
        base=Path('runs')/name;protocol=self.read(base/'Protocol.json');state=self.read(base/'Campaign_state.json')
        origin=protocol.get('request_origin',{}).get('directory',str(base))
        journal=self.read(Path(origin)/'API_attempts.json')
        prefix=str(base)+'--';stages=[]
        for filename in sorted(self.manifest['files']):
            p=Path(filename)
            if str(p.parent).startswith(prefix) and p.name=='checkpoint.json':
                checkpoint=self.read(filename)
                stages.append({'stage':p.parent.name[len(name)+2:],'phase':checkpoint['phase'],'cursor':checkpoint['cursor'],
                    'unknown_evaluations':sum(e['status']!='completed' for e in checkpoint.get('evaluations',{}).values()),
                    'uncommitted_tasks':sum(t.get('status')!='completed' for t in checkpoint.get('tasks',{}).values()),
                    'writer_lock_in_snapshot':str(p.parent/'.execution.lock') in self.manifest['files']})
        attempts=list(journal['api_attempts'].values())
        return {'view':'historical-evidence-only; not rebound to current execution identity','source_commit':self.manifest['source_commit'],
            'source_root':str(self.source),'vault':str(self.root),'campaign':name,'phase':state['phase'],
            'historical_protocol_sha256':self.manifest['files'][str(base/'Protocol.json')]['sha256'],
            'logical_tasks':len(journal['requests']),'API_attempts':len(attempts),
            'unknown_API_attempts':sum(r['status'] not in ('completed','failed') for r in attempts),'stages':stages,
            'H_order':self.read(base/'H_frozen.json')['selected_ids'] if str(base/'H_frozen.json') in self.manifest['files'] else None,
            'original_absolute_paths_unchanged':True,'API_calls':0,'solves':0,'resume_supported':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receipt',required=True);p.add_argument('--vault');p.add_argument('--campaign',default='tsp-pilot-20261026-v2');p.add_argument('--verify-all',action='store_true')
    a=p.parse_args();vault=EvidenceVault(a.receipt,a.vault);result=vault.status(a.campaign)
    if a.verify_all:result['verified_assets']=vault.verify_all()
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
