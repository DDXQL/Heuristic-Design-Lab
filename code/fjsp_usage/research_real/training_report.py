"""All attempts/all populations, available before any holdout access or success.

No best seed filtering; finite training behavior hashes never deduplicate code.
"""
import json
from collections import Counter
from statistics import fmean
from fjsp_usage.research.events import atomic_json
from .workflow import ARMS


def attempt_categories(state):
    counts=Counter(a.get('category',{'valid':'valid','duplicate':'legacy_unspecified_duplicate',
        'invalid':'runtime_failure','failed':'api_failure','interrupted':'interrupted_request',
        'parse_or_constraint_error':'legacy_unspecified_parse_or_constraint'}.get(a['status'],a['status']))
        for a in state['attempts'])
    return dict(counts)


def write_training_report(flow):
    flow.assert_current()
    H,members=flow.h_asset()
    entries=[]; paired=[]; initial=[]
    for seed in flow.config.seeds:
        path=flow.directory/f'r{seed}/INIT/checkpoint.json'
        if path.exists():
            state=json.loads(path.read_text()); categories=attempt_categories(state)
            initial.append({'seed':seed,'phase':state['phase'],'planned_N':flow.config.population_size,
                'accepted':len(state['population']),'attempts':state['init_cursor'],
                'attempt_cap':flow.config.initialization_cap,'categories':categories,
                'attempt_records':state['attempts'], 'inflight':state['inflight'],
                'all_initial_evaluations':state['evaluations'], 'accepted_population':state['population']})
        else: initial.append({'seed':seed,'phase':'not_started'})
        seed_entries=[]
        for arm in ARMS:
            path=flow.directory/f'r{seed}/{arm}/checkpoint.json'
            if not path.exists():
                row={'seed':seed,'arm':arm,'phase':'not_started','attempts':0,'best_train_fitness':None}
            else:
                state=json.loads(path.read_text()); rows=[]
                # Retain ALL evaluated children incl. nonsurvivors/failures.
                for identifier,record in state['evaluations'].items():
                    rows.append({'id':identifier,**record})
                scores=[r['fitness'] for r in state['population']]
                row={'seed':seed,'arm':arm,'phase':state['phase'],'attempts':len(state['attempts']),
                    'categories':attempt_categories(state),'attempt_records':state['attempts'],
                    'all_child_evaluations':rows,'population':state['population'],
                    'best_train_fitness':max(scores) if scores else None,
                    'mean_population_train_fitness':fmean(scores) if scores else None,
                    'generation':state['generation'],'inflight':state['inflight']}
            entries.append(row); seed_entries.append(row)
        if all(r['phase']=='completed' for r in seed_entries):
            from itertools import combinations
            paired.extend({'seed':seed,'pair':a['arm']+'-'+b['arm'],
                'best_train_difference':a['best_train_fitness']-b['best_train_fitness'],
                'note':'descriptive training metric; not validation selection or independent test evidence'}
                for a,b in combinations(seed_entries,2))
    history=None
    if flow.config.conditional_research:
        from .conditional_research import history_summary
        history=history_summary(flow.project_root,flow.config)
    report=flow.write('Training_report.json','Training_report', entries=entries, initialization=initial,
        paired_train_differences=paired,budget=flow.ledger.summary(),historical_budget=history,
        fixed_h_train_results=H['members'],
        claim='one-seed preliminary conditional experiment' if flow.config.mode=='real' and len(flow.config.seeds)==1
            else 'all declared seeds retained; training diagnostics only',
        initialization_diversity_claim='Distinct validated AST/narrow signatures only; finite behavior or equal fitness is not program equivalence.',
        holdout_policy='No validation/test access in this entry; training results do not select final test policies.')
    return report
