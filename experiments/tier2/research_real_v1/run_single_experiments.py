#!/usr/bin/env python3
"""Original single-ID four-arm conditional research, separate from usage_v2.

prepare is offline; paid stages require new H scope and request authorization.
An immutable source snapshot plus read-only peer checks protects cumulative cost.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'code'))
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research.evolution import operator_at
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.config import ExperimentConfig, fingerprint
from fjsp_usage.research_real.conditional_research import prepare, check_origin, freeze_h
from fjsp_usage.research_real.initialization import initialization_prompt
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.preparation import preview_parents
from fjsp_usage.research_real.prompts import build_prompt, prompt_sections, prompt_manifest
from fjsp_usage.research_real.single_experiments import (VERSION, Guard, GuardedTransport,
    file_hashes, verify_sources, budget_inventory, worktree_roots, declaration_pins)
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.research_real.training_report import write_training_report
from fjsp_usage.research_real.workflow import Workflow, ARMS


class SingleWorkflow(Workflow):
    def client(self):
        if self._client is None:
            guard = Guard(self, self.read('Worktree_binding.json', 'Worktree_binding'))
            guard.check()
            inner = super().client()
            self._client = GuardedTransport(inner, guard)
        return self._client


def default_config(source_hashes):
    # Use the original four-arm proposal, never the SELECT/MIX 40-call proposal.
    path = ROOT / 'runs/conditional-paired-research-20261011-v4/config.research.pending.json'
    data = json.loads(path.read_text())
    data['conditional_research']['source_files_sha256'] = declaration_pins(source_hashes)
    assert data['real_requests_authorized'] is False
    assert data['conditional_research']['scope_approval'] is None
    return ExperimentConfig.from_dict(data)


def check_scale(config):
    if (config.mode != 'real' or config.purpose != 'research' or not config.conditional_research
            or config.seeds != (201,) or config.population_size != 5 or config.H_size != 10
            or config.cross_parents != 5 or config.mutation_parents != 1
            or config.initialization_cap != 20 or config.generations != 1
            or config.attempts_per_generation != 10 or config.total_request_cap != 60):
        raise ValueError('this registered preliminary batch requires seed201/N5/init20/four arms x10/cap60')


def export_prompts(directory, members):
    parents = preview_parents(5)  # Explicit fixtures, never a real initial pool.
    folder = directory / 'prompts'; folder.mkdir()
    records = []
    initial = initialization_prompt(build_prompt('B0', 'I1', [], members), [], 0)
    (folder / 'Shared.I1.txt').write_text(initial)
    records.append({'file':'Shared.I1.txt','sha256':hashlib.sha256(initial.encode()).hexdigest(),
                    'parents':'none; empty accepted-code archive'})
    for arm in ARMS:
        operators = ('E1','E2','M1','M2','M3') if arm in ('B0','B1') else ('CROSS','MUTATE')
        for op in operators:
            selected = parents if op in ('E1','E2','CROSS') else parents[:1]
            prompt = build_prompt(arm, op, selected, members)
            name = f'{arm}.{op}.txt'; (folder / name).write_text(prompt)
            records.append({'file':name,'sha256':hashlib.sha256(prompt.encode()).hexdigest(),
                            'parents':'HANDWRITTEN_PREVIEW_ONLY','parent_count':len(selected)})
    comparison = {}
    for op in ('CROSS','MUTATE'):
        selected = parents if op == 'CROSS' else parents[:1]
        a, b = [prompt_sections(arm, op, selected, members) for arm in ('B2','P')]
        comparison[op] = {k:a[k] == b[k] for k in a}
        assert all(v for k,v in comparison[op].items() if k != 'operator')
        assert not comparison[op]['operator']
    atomic_json(folder / 'Manifest.json', {'pack':prompt_manifest(),'records':records,
        'B2_P_section_equality':comparison,'real_parent_codes_not_yet_generated':True})
    return records


def offline_prepare(directory, origin, config_path):
    source = file_hashes(origin)
    verify_sources(ROOT, origin, source)
    inventory = budget_inventory(worktree_roots(ROOT))
    config = ExperimentConfig.from_dict(json.loads(config_path.read_text())) if config_path else default_config(source)
    check_scale(config)
    if config.conditional_research['source_files_sha256'] != declaration_pins(source):
        raise ValueError('new registration must pin every current read-only source file')
    dataset = StagedDataset(ROOT / 'data/fjsp_manifest.json', project_root=ROOT, mode='real')
    with RunLock(directory), patch('fjsp_usage.research_real.workflow.JsonCandidateTransport',
                                  side_effect=AssertionError('offline preparation cannot create a provider')):
        atomic_json(directory / 'config.single.pending.json', config.payload())
        flow = SingleWorkflow(directory, config=config, dataset=dataset, project_root=ROOT)
        binding = flow.write('Worktree_binding.json','Worktree_binding',version=VERSION,
            origin_root=str(origin), source_files_sha256=source, real_budget_inventory=inventory,
            checkpoint_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip())
        print('原单成员协议：重评10条H的全部21个训练实例；无模型请求。', flush=True)
        h = prepare(flow); _, members, _ = check_origin(ROOT, config, dataset)
        prompts = export_prompts(directory, members)
        identity = {}
        for split in dataset.names:
            identity[split] = [{'file':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                for name,path in zip(dataset.names[split], dataset.paths[split])]
            assert all(row['sha256'] == dataset.metadata['hashes'][row['file']] for row in identity[split])
        files = set(fingerprint(ROOT)['files'])
        files.update(str(p.relative_to(ROOT)) for p in (ROOT/'tests').glob('*.py'))
        files.update(str(p.relative_to(ROOT)) for p in (ROOT/'docs').glob('*.md'))
        files.update(['README.md','data/fjsp_manifest.json'])
        with tarfile.open(directory / 'code-prompts-config-snapshot.tar.gz', 'w:gz') as archive:
            for name in sorted(files): archive.add(ROOT/name, arcname=name)
            for p in [directory/'protocol.json',directory/'config.single.pending.json',
                      directory/'Worktree_binding.json',*sorted((directory/'prompts').glob('*'))]:
                archive.add(p, arcname='registration/'+str(p.relative_to(directory)))
        guard = Guard(flow, binding); guard.check()
        history = h['history']
        summary = flow.write('Single_readiness.json','Single_readiness',version=VERSION,
            status='OFFLINE_PREPARED_PENDING_H_SCOPE_AND_PAID_AUTHORIZATION',
            h_valid=sum(r['result']['valid'] for r in h['rows']),
            h_reproduced=sum(r['same_training_makespans_as_source'] for r in h['rows']),
            arms=list(ARMS), seed=201, N=5, initial_new_cap=20, generations=1, slots_per_arm=10,
            schedule={a:[operator_at(a,i,10) for i in range(10)] for a in ARMS},
            new_request_cap=60, historical_budget=history,
            maximum_lifetime_slots=history['historical_request_slots']+60,
            prompt_files=prompts, dataset_identity=identity,
            source_files_unchanged=len(source), holdouts_parsed=0, new_model_requests=0,
            archive_sha256=hashlib.sha256((directory/'code-prompts-config-snapshot.tar.gz').read_bytes()).hexdigest(),
            completion='Shared fresh N5 then all four full generations, including failures/duplicates; all train evaluations retained. No validation/test in this batch.',
            interpretation='One-seed preliminary conditional fixed-existing-H experiment; no independent generalization claim.',
            accounting='Copied ledgers deduplicated by identity; any new peer ledger, change or writer stops dispatch for reconciliation.')
        print(json.dumps({k:summary[k] for k in ('status','h_valid','h_reproduced','maximum_lifetime_slots')},ensure_ascii=False),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('prepare','preflight','freeze-h','initialize','search','training-report'))
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--origin-root',type=Path)
    parser.add_argument('--config',type=Path)
    args = parser.parse_args(); directory = args.run_dir.resolve()
    if directory.parent != ROOT/'runs': parser.error('requires own worktree runs direct child')
    if args.stage == 'prepare':
        if not args.origin_root or directory.exists():parser.error('prepare requires read-only --origin-root and new run directory')
        offline_prepare(directory,args.origin_root.resolve(),args.config)
        return
    if not args.config:parser.error('explicit same registered --config required')
    config = ExperimentConfig.from_dict(json.loads(args.config.read_text())); check_scale(config)
    dataset = StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
    with RunLock(directory):
        flow = SingleWorkflow(directory,config=config,dataset=dataset,project_root=ROOT)
        Guard(flow,flow.read('Worktree_binding.json','Worktree_binding')).check()
        if args.stage == 'preflight':
            _,members,_=check_origin(ROOT,config,dataset)
            print('来源/代码/数据清单/跨worktree账本一致；未创建模型客户端。')
        elif args.stage == 'freeze-h': freeze_h(flow)
        elif args.stage == 'initialize':
            result = flow.initialize_u(201)
            if result['status'] != 'initialized':
                raise BudgetStop('initialization incomplete: '+result['status']+'; no four-arm generation')
        elif args.stage == 'search':
            if not (directory/'r201/Shared_initial.json').exists():
                raise BudgetStop('search requires a completed shared initialization stage')
            result = flow.search_all()
            if any(row['status'] != 'completed' for row in result['entries']):
                raise BudgetStop('not all four arms completed; retain partial/failed outcomes')
        else: write_training_report(flow)


if __name__ == '__main__': main()
