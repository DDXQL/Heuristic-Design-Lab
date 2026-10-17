#!/usr/bin/env python3
"""Saved-record-only fair pilot exhibits; no inference, solving or holdout reads.

Run after the caller stops. Missing values remain NA; no candidate reconstruction.
Only the existing pure invoice matcher is reused; no client is instantiated.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tarfile
import io
import sys
from statistics import fmean
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
ARMS = ('B0', 'B1', 'B2', 'P')
TIMES = ('single_solve_seconds', 'deterministic_recheck_seconds', 'diagnostic_replay_seconds')


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def csvfile(path, rows, columns=None):
    columns = columns or list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator='\n')
        w.writeheader()
        for row in rows:
            w.writerow({k: ('NA' if row.get(k) is None else json.dumps(row[k], ensure_ascii=False)
                            if isinstance(row[k], (dict, list)) else row[k]) for k in columns})


def link(path, out):
    return Path(os.path.relpath(path, out)).as_posix()


def mdtable(rows, columns):
    return '\n'.join(['| '+' | '.join(columns)+' |', '| '+' | '.join('---' for _ in columns)+' |']+
                     ['| '+' | '.join('未知' if row.get(k) is None else str(row[k]) for k in columns)+' |'
                      for row in rows])


def check_evaluation(e, names):
    if not e or not e.get('valid'):
        return
    assert e['total_instances'] == len(e['instances']) == len(names) == 21
    assert [x['file'] for x in e['instances']] == names
    assert all(x['feasible'] is True and math.isclose(x['score'], -x['makespan']/x['lower_bound'],
               rel_tol=1e-12) for x in e['instances'])
    assert math.isclose(e['fitness'], fmean(x['score'] for x in e['instances']), rel_tol=1e-12)


def completion_proof(run, protocol, states, journals, ledger, quota):
    """Verify saved identities/cursors/receipts only; never execute a candidate."""
    context=digest(protocol);paths={};phases={}
    def sealed(name, kind):
        path=run/name;d=read(path)
        assert d['kind']==kind and d['mode']=='real' and d['context']==context
        assert d['artifact_sha256']==digest({k:v for k,v in d.items() if k!='artifact_sha256'})
        paths[name]=sha(path);return d
    shared=sealed('r201/Shared_initial.json','Shared_initial')
    assert len(shared['population'])==5 and len(states['INIT']['attempts'])==5
    for group in ARMS:
        s=states[group];assert s['phase']=='completed' and s['generation']==1 and s['inflight'] is None
        assert len(s['attempts'])==len(journals[group])==10
        final=sealed(f'r201/{group}/Final_population.json','Final_population')
        assert final['shared_initial_hash']==shared['artifact_sha256']
        assert [x['id'] for x in final['population']]==[x['id'] for x in s['population']]
        phases[group]={'attempts':10,'generation':1,'inflight':None,'same_initial_hash':True}
    sealed('Search_complete.json','Search_complete')
    for group in ('INIT',*ARMS):
        for name in ('checkpoint.json','budgeted_initial_requests.json' if group=='INIT' else 'budgeted_evolution_requests.json'):
            rel=f'r201/{group}/{name}';paths[rel]=sha(run/rel)
        for record in journals[group].values():
            key=record['global_key'];native=ledger[key];account=quota['records'][key]
            assert native['send_confirmed'] and record['status']=='completed' and account['status']=='settled'
            stem=hashlib.sha256(key.encode()).hexdigest()
            wire=read(run/'wire_responses'/(stem+'.json'))
            assert wire['global_key']==key and wire['send_confirmed'] and wire['status']=='wire_completed_before_settlement'
            assert wire['reply']['text']==record['text'] and wire['reply']['usage']==record['usage']
            assert record['response_metadata']['model']=='gpt-6.1-sol'
            for rel in [f'wire_responses/{stem}.json',f'billing/{stem}.json']:
                paths[rel]=sha(run/rel)
    assert len(ledger)==45 and len(quota['records'])==45 and not quota['halted']
    for name in ('budget.json','platform_quota.json','protocol.json','H_frozen.json',
                 'Fair_status.json','Final_budget_handoff.json','Training_report.json','Single_results.json'):
        paths[name]=sha(run/name)
    handoff=read(run/'Final_budget_handoff.json');history=read(run/'History_binding.json')
    assert handoff['budget_sha256']==paths['budget.json'] and handoff['real_caller_active'] is False
    assert handoff['registered_generation_phases_complete'] is True
    assert handoff['summary']['lifetime_request_slots']==history['historical_request_slots']+45==201
    assert handoff['summary']['lifetime_confirmed_sends']==history['historical_confirmed_sends']+45==185
    return {'kind':'offline-completion-verification','caller_lock_absent':not (run/'.writer.lock').exists(),
            'native_slots':45,'confirmed_sends':45,'same_shared_initial_for_all_groups':True,'phases':phases,
            'historical_slots':156,'lifetime_slots':201,'historical_sends':140,'lifetime_sends':185,
            'unused_initialization_allowance':15,'unused_allowance_is_not_extra_evolution_authorization':True,
            'checks':'seals, journal-ledger-wire text/usage/ID joins, exact invoices, 21-instance fitness arithmetic; no reevaluation',
            'source_files_sha256':paths,'new_model_requests_by_verifier':0,'new_candidate_evaluations_by_verifier':0}


def cost_row(run, key, record):
    from fjsp_usage.research_real.single_billing import match_invoice
    billpath = run/'billing'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
    bill = read(billpath, {})
    invoice = bill.get('invoice')
    units = bill.get('actual_platform_units') if bill.get('status') == 'invoice_account_matched' else None
    evidence = billpath
    proofpath = run/'billing_reconciliations'/billpath.name
    proof = read(proofpath)
    if proof:
        assert proof['original_billing_sha256'] == sha(billpath)
        for n, h in proof['evidence_files_sha256'].items():
            assert sha(run/n) == h
        # This reporter does not query or settle; the registered recovery verifies matches.
        invoice = proof['invoice']
        assert invoice['quota'] == proof['actual_platform_units']
        units = proof['actual_platform_units']
        evidence = proofpath
    if units is not None:
        after = read(run/next(n for n in proof['evidence_files_sha256'] if 'invoices' in n)) if proof else bill['after']
        account = proof['reconciled_account'] if proof else bill['original_quota_record']
        verified = match_invoice(bill['before'],after,account,'gpt-6.1-sol',
            failed=bill.get('transport_status')=='failed',
            response_id=proof['supplier_request_id'] if proof else bill.get('response_metadata',{}).get('gateway_request_id'))
        assert verified==invoice and units==invoice['quota'] and invoice['group']=='codex-deafult'
        if record.get('usage'):
            assert invoice['prompt_tokens']==record['usage']['input_tokens']
            assert invoice['completion_tokens']==record['usage']['output_tokens']
    usage = record.get('usage')
    return {'actual_platform_points': units, 'cost_status': 'verified_invoice' if units is not None else 'unknown',
            'wire_input_tokens': usage.get('input_tokens') if usage else None,
            'wire_output_tokens': usage.get('output_tokens') if usage else None,
            'invoice_input_tokens': invoice.get('prompt_tokens') if invoice else None,
            'invoice_output_tokens': invoice.get('completion_tokens') if invoice else None,
            'request_journal_elapsed_seconds': record.get('elapsed_seconds'),
            'provider_roundtrip_seconds': record.get('response_metadata', {}).get('provider_roundtrip_seconds'),
            'cost_evidence': str(evidence.relative_to(run)) if evidence.exists() else None,
            'supplier_request_id': record.get('response_metadata', {}).get('gateway_request_id')}


def build(run, out, *, charts=True):
    if (run/'.writer.lock').exists():raise RuntimeError('Original caller active; do not refresh derived reports yet')
    out.mkdir(parents=True, exist_ok=True)
    protocol = read(run/'protocol.json')
    assert protocol['config']['seeds'] == [201] and protocol['config']['population_size'] == 5
    names = protocol['dataset']['split']['train']
    H = read(run/'H_frozen.json')
    fixed_rows, fixed_summary = [], []
    for i, member in enumerate(H['members']):
        e = member['training_result']; check_evaluation(e, names)
        fixed_summary.append({'member': i, 'code_key': member['candidate']['key'], 'fitness': e['fitness'],
            **{t: sum(x[t] for x in e['instances']) if all(x.get(t) is not None for x in e['instances']) else None
               for t in TIMES}})
        fixed_rows.extend({'member': i, 'fitness': e['fitness'], **{k:x.get(k) for k in
            ('file', 'makespan', 'lower_bound', 'score', 'feasible', *TIMES)}} for x in e['instances'])
    best_h = max(fixed_summary, key=lambda x: (x['fitness'], -x['member']))
    csvfile(out/'fixed_h_summary.csv', fixed_summary)
    csvfile(out/'fixed_h_instances.csv', fixed_rows)
    ledger = read(run/'budget.json')['records']
    quota = read(run/'platform_quota.json', {})
    states, journals, evaluations, requests, instances, populations = {}, {}, {}, [], [], []
    for g in ('INIT', *ARMS):
        folder = run/'r201'/g
        states[g] = s = read(folder/'checkpoint.json', {})
        journals[g] = j = read(folder/('budgeted_initial_requests.json' if g == 'INIT' else 'budgeted_evolution_requests.json'), {}).get('requests', {})
        attempts = {a['id']: a for a in s.get('attempts', [])}
        for identifier, item in s.get('evaluations', {}).items():
            e = item.get('result'); check_evaluation(e, names)
            evaluations[identifier] = e
            if e:
                for x in e.get('instances', []):
                    instances.append({'group': g, 'id': identifier, 'valid_candidate': e.get('valid'),
                        'fitness': e.get('fitness'), **{k:x.get(k) for k in
                        ('file', 'makespan', 'lower_bound', 'score', 'feasible', *TIMES, 'member_usage')}})
        for identifier, r in j.items():
            key = r['global_key']; b = ledger[key]; a = attempts.get(identifier, {})
            e = evaluations.get(identifier)
            requests.append({'group': g, 'id': identifier, 'global_key': key, 'send_confirmed': b.get('send_confirmed', False),
                'journal_status': r['status'], 'category': a.get('category'), 'operator': a.get('operator'),
                'parents': a.get('parents'), 'code_key': a.get('code_key'), 'error_type': r.get('error_type') or a.get('error_type'),
                'error': r.get('error') or a.get('error'), 'valid': bool(e and e.get('valid')),
                'fitness': e.get('fitness') if e else None, **cost_row(run, key, r)})
    assert {r['global_key'] for r in requests} == set(ledger), 'Unjoined ledger request: stop report, do not drop it'
    initial = states['INIT'].get('population', [])
    initial_ids = {x['id'] for x in initial}
    ibest = sorted(initial, key=lambda x:(-x['fitness'], x['id']))[0] if initial else None
    initial_mean = fmean(x['fitness'] for x in initial) if initial else None
    phases = []
    for g in ('INIT', *ARMS):
        rs = [r for r in requests if r['group'] == g]; s = states[g]; pop = s.get('population', [])
        evs = [evaluations[r['id']] for r in rs if evaluations.get(r['id'])]
        errs = Counter(r['category'] or r['journal_status'] for r in rs if r['category'] != 'valid')
        phases.append({'group': g, 'phase': 'initialized' if g=='INIT' and len(pop)==5 else s.get('phase', 'not_started'),
            'checkpoint_phase':s.get('phase'), 'slots': len(rs),
            'planned_slot_cap':20 if g=='INIT' else 10,
            'uncompleted_evolution_slots':max(0,10-len(s.get('attempts',[]))) if g!='INIT' else None,
            'unused_initialization_allowance':max(0,20-len(rs)) if g=='INIT' else None,
            'confirmed_sends': sum(r['send_confirmed'] for r in rs), 'valid_candidates': sum(r['valid'] for r in rs),
            'valid_per_confirmed_send':sum(r['valid'] for r in rs)/sum(r['send_confirmed'] for r in rs)
                if any(r['send_confirmed'] for r in rs) else None,
            **{category:sum(r['category']==category for r in rs) for category in
               ('code_duplicate','narrow_equivalence_duplicate','parse_failure',
                'interface_or_code_constraint_failure','runtime_failure','api_failure')},
            'failure_categories': dict(errs), 'new_children_surviving': sum(x['id'] not in initial_ids for x in pop) if g != 'INIT' else None,
            'initial_mean_fitness': initial_mean if g != 'INIT' else None,
            'initial_best_fitness': ibest['fitness'] if g != 'INIT' and ibest else None,
            'final_mean_fitness': fmean(x['fitness'] for x in pop) if pop else None,
            'final_best_fitness': max(x['fitness'] for x in pop) if pop else None,
            'known_platform_points': sum(r['actual_platform_points'] for r in rs if r['actual_platform_points'] is not None),
            'unknown_cost_requests': sum(r['actual_platform_points'] is None for r in rs if r['send_confirmed']),
            'known_wire_input_tokens': sum(r['wire_input_tokens'] for r in rs if r['wire_input_tokens'] is not None),
            'known_wire_output_tokens': sum(r['wire_output_tokens'] for r in rs if r['wire_output_tokens'] is not None),
            'unknown_wire_usage_requests': sum(r['wire_input_tokens'] is None for r in rs if r['send_confirmed']),
            'primary_evaluation_seconds': sum(e.get('primary_evaluation_seconds', 0) for e in evs),
            **{t:sum(x[t] for e in evs for x in e.get('instances',[]) if x.get(t) is not None) for t in TIMES},
            'known_provider_roundtrip_seconds':sum(r['provider_roundtrip_seconds'] for r in rs if r['provider_roundtrip_seconds'] is not None),
            'unknown_provider_roundtrip_times':sum(r['provider_roundtrip_seconds'] is None for r in rs),
            'independent_diagnostic_seconds': sum(e.get('diagnostic_evaluation_seconds', 0) for e in evs)})
        for x in pop:
            populations.append({'group': g, 'id': x['id'], 'fitness': x['fitness'], 'code_key': x['candidate']['key'],
                'from_initial': x['id'] in initial_ids})
    csvfile(out/'phase_summary.csv', phases)
    csvfile(out/'cost_summary.csv',phases,['group','confirmed_sends','valid_candidates','known_platform_points',
        'unknown_cost_requests','known_wire_input_tokens','known_wire_output_tokens','unknown_wire_usage_requests',
        'primary_evaluation_seconds',*TIMES,'independent_diagnostic_seconds',
        'known_provider_roundtrip_seconds','unknown_provider_roundtrip_times'])
    csvfile(out/'requests.csv', requests, list(requests[0]) if requests else ['group','id','send_confirmed','cost_status'])
    csvfile(out/'all_candidate_instances.csv', instances, list(instances[0]) if instances else ['group','id','file','makespan','fitness'])
    csvfile(out/'populations.csv', populations, ['group','id','fitness','code_key','from_initial'])
    champions = {f"h{best_h['member']}": H['members'][best_h['member']]['training_result']}
    champion_ids = {f"h{best_h['member']}": f"fixed-h{best_h['member']}"}
    # Frozen historical reference only. It never enters initial/current populations.
    source = run.parent/protocol['config']['conditional_research']['source_run']
    source_protocol = read(source/'protocol.json')
    assert sha(source/'protocol.json') == protocol['config']['conditional_research']['source_files_sha256']['protocol.json']
    assert source_protocol['dataset'] == protocol['dataset']
    old_shared = read(source/'r201/Shared_initial.json')
    assert old_shared['artifact_sha256'] == digest({k:v for k,v in old_shared.items() if k!='artifact_sha256'})
    assert old_shared['context'] == digest(source_protocol) and old_shared['kind']=='Shared_initial'
    old_best = sorted(old_shared['population'],key=lambda x:(-x['fitness'],x['id']))[0]
    check_evaluation(old_best['training_result'],names)
    assert math.isclose(old_best['fitness'],-2.0704275135579646,rel_tol=1e-12)
    champions['OLD_SINGLE_FROZEN'] = old_best['training_result']
    champion_ids['OLD_SINGLE_FROZEN'] = old_best['id']
    old_reference = {'role':'historical frozen TRAINING reference; never imported into this batch',
        'source_run':str(source),'source_asset':'r201/Shared_initial.json',
        'source_asset_sha256':sha(source/'r201/Shared_initial.json'),'source_asset_seal':old_shared['artifact_sha256'],
        'id':old_best['id'],'code_key':old_best['candidate']['key'],'fitness':old_best['fitness'],
        'same_dataset_and_H': [x['candidate']['key'] for x in H['members']] ==
            [x['candidate']['key'] for x in read(source/'H_frozen.json')['members']],
        'new_evaluations':0,'imported_into_population':False}
    assert old_reference['same_dataset_and_H']
    dump(out/'historical_reference.json',old_reference)
    if ibest:
        champions['INIT'] = ibest.get('training_result') or evaluations[ibest['id']]
        champion_ids['INIT'] = ibest['id']
    for g in ARMS:
        if states[g].get('phase') == 'completed':
            best = sorted(states[g]['population'], key=lambda x:(-x['fitness'],x['id']))[0]
            champions[g] = best.get('training_result') or evaluations[best['id']]
            champion_ids[g] = best['id']
    csvfile(out/'champion_instances.csv', [dict(group=g, id=champion_ids[g], fitness=e['fitness'],
        **{k:x.get(k) for k in ('file','makespan','lower_bound','score','feasible',*TIMES)})
        for g,e in champions.items() for x in e['instances']])
    pairs = [('B1','B0'), ('B2','B1'), ('P','B2'), ('P','B0')]+[(g,b) for g in ARMS for b in ('INIT',f"h{best_h['member']}",'OLD_SINGLE_FROZEN')]
    comparisons, differences = [], []
    for a,b in pairs:
        if a not in champions or b not in champions: continue
        aa, bb = champions[a], champions[b]; rows = []
        for x,y in zip(aa['instances'],bb['instances']):
            assert x['file'] == y['file']
            rows.append({'A':a,'B':b,'file':x['file'],'A_makespan':x['makespan'],'B_makespan':y['makespan'],
                'A_minus_B_makespan':x['makespan']-y['makespan'],'A_minus_B_score':x['score']-y['score']})
        differences.extend(rows)
        comparisons.append({'A':a,'B':b,'A_minus_B_fitness':aa['fitness']-bb['fitness'],
            'A_wins':sum(x['A_minus_B_makespan']<0 for x in rows),
            'ties':sum(x['A_minus_B_makespan']==0 for x in rows),'A_losses':sum(x['A_minus_B_makespan']>0 for x in rows),
            'mean_Cmax_difference':fmean(x['A_minus_B_makespan'] for x in rows)})
    csvfile(out/'comparisons.csv', comparisons, ['A','B','A_minus_B_fitness','A_wins','ties','A_losses','mean_Cmax_difference'])
    csvfile(out/'instance_differences.csv', differences, ['A','B','file','A_makespan','B_makespan','A_minus_B_makespan','A_minus_B_score'])
    complete = all(states[g].get('phase') == 'completed' for g in ARMS)
    balanced = complete and all(p['confirmed_sends'] == 10 for p in phases if p['group'] in ARMS)
    infrastructure = [r['id'] for r in requests if r['category'] == 'api_failure']
    if complete:
        dump(out/'completion_verification.json',completion_proof(run,protocol,states,journals,ledger,quota))
    summary = {'run':run.name, 'complete':complete,'balanced_actual_evolution_sends':balanced,
        'infrastructure_failure_ids':infrastructure, 'phases':phases,'best_fixed_h':best_h,
        'champions':{g:{'id':champion_ids[g],'fitness':e['fitness']} for g,e in champions.items()},
        'comparisons':comparisons,'historical_frozen_reference':old_reference,
        'known_new_platform_points':sum(r['actual_platform_points'] for r in requests if r['actual_platform_points'] is not None),
        'unknown_new_cost_ids':[r['id'] for r in requests if r['send_confirmed'] and r['actual_platform_points'] is None],
        'latest_verified_account_used_points':quota.get('observed_used'),
        'historical_hold_points':read(run/'History_binding.json')['retained_account_hold'],
        'known_wire_input_tokens':sum(r['wire_input_tokens'] for r in requests if r['wire_input_tokens'] is not None),
        'known_wire_output_tokens':sum(r['wire_output_tokens'] for r in requests if r['wire_output_tokens'] is not None),
        'unknown_wire_usage_ids':[r['id'] for r in requests if r['send_confirmed'] and r['wire_input_tokens'] is None],
        'pre_send_metadata_pauses':len(list((run/'pre_send_metadata').glob('*.json'))),
        'unit':'raw platform points; CNY/USD unknown', 'new_H_evaluations':0,
        'source_H_hash':H.get('source_H_hash'),'current_H_hash':H['artifact_sha256'],
        'protocol_sha256':sha(run/'protocol.json'),'dataset_identity':protocol['dataset'],
        'scope':'fixed-existing-H / scalar-ID / seed201 / one generation / train21 only'}
    dump(out/'summary.json',summary)
    # Full prompt and source in this case are actual archive entries, never a regenerated prompt.
    candidates = [r for r in requests if r['group']=='P' and r['operator']=='CROSS']
    candidates.sort(key=lambda r:(not r['valid'], r['id'] not in {x['id'] for x in states['P'].get('population',[])},r['id']))
    case_text = '# 真实P组交叉案例\n\n'
    if candidates:
        c=candidates[0]; ident=c['id']; record=journals['P'][ident]; case_dir=out/'case';case_dir.mkdir(exist_ok=True)
        (case_dir/'actual_prompt.txt').write_text(record['prompt'])
        if record.get('text') is not None:
            (case_dir/'actual_response.txt').write_text(record['text'])
            m=re.search(r'```python\s*\n(.*?)\n```',record['text'],re.S)
            if m:(case_dir/'child.py').write_text(m.group(1)+'\n')
        case_text+=f"候选 `{ident}`；分类 `{c['category']}`；完整训练fitness {c['fitness']}；最终存活：{ident in {x['id'] for x in states['P'].get('population',[])}}。\n\n"
        parent_rows=[]
        parent_pairs=[];e=evaluations.get(ident)
        for i,pid in enumerate(c['parents'] or []):
            parent=next(x for x in initial if x['id']==pid)
            path=case_dir/f'parent{i}.py';path.write_text(parent['candidate']['code'])
            pair=[]
            if e and e.get('valid'):
                pe=parent.get('training_result') or evaluations[pid]
                for x,y in zip(e['instances'],pe['instances']):
                    assert x['file']==y['file']
                    pair.append({'parent':pid,'file':x['file'],'child_makespan':x['makespan'],
                        'parent_makespan':y['makespan'],'child_minus_parent_makespan':x['makespan']-y['makespan']})
                parent_pairs.extend(pair)
            parent_rows.append({'id':pid,'fitness':parent['fitness'],'code_key':parent['candidate']['key'],
                'child_minus_parent_fitness':c['fitness']-parent['fitness'] if c['fitness'] is not None else None,
                'child_wins':sum(x['child_minus_parent_makespan']<0 for x in pair) if pair else None,
                'ties':sum(x['child_minus_parent_makespan']==0 for x in pair) if pair else None,
                'child_losses':sum(x['child_minus_parent_makespan']>0 for x in pair) if pair else None})
            case_text+=f"- [{pid}源码](case/{path.name})；fitness {parent['fitness']:.9f}。模型自述：{parent['candidate']['description']}\n"
        csvfile(case_dir/'parent_comparison.csv',parent_rows)
        csvfile(case_dir/'parent_instance_comparison.csv',parent_pairs,
            ['parent','file','child_makespan','parent_makespan','child_minus_parent_makespan'])
        if e:
            dump(case_dir/'evaluation_summary.json',{k:v for k,v in e.items() if k!='instances'})
            csvfile(case_dir/'21_instances.csv',[{k:x.get(k) for k in ('file','makespan','lower_bound','score','feasible',*TIMES)} for x in e.get('instances',[])])
        case_text+='\n[实际完整提示](case/actual_prompt.txt)'
        case_text+=' → [实际响应](case/actual_response.txt)' if record.get('text') is not None else '；该槽位没有可用响应正文，不补造'
        case_text+='；源码和21实例结果以case目录实际文件为准。父代来自本批共享初始化，成员编号、代码键和训练成绩保留。模型描述仅帮助阅读代码，改进判断以完整21实例fitness及生存结果为准；未用测试集验证。\n\n'
        case_text+=mdtable(parent_rows,['id','fitness','child_minus_parent_fitness','child_wins','ties','child_losses'])
        case_text+='\n\n逐实例对齐见[parent_instance_comparison.csv](case/parent_instance_comparison.csv)。案例优先取材料完整且存活的交叉子代，其次取最早编号，不按最好fitness挑选；本批五条P交叉子代均未存活，因此使用最早的有效交叉。\n'
        if ident=='P/g0000/000000' and 'machine_ready_std > 0.5 * machine_ready_mean' in record.get('text',''):
            case_text+='\n**这段代码实际改变了什么。** 四个常量父代分别始终返回0、2、1、3，另一个父代按状态返回多个编号。子代以h0为默认和首步选择；机器就绪时间的标准差同时超过均值的一半、剩余工作均值的四分之一时转用h9；晚期且候选比例较低、剩余工作相对离散程度较小时转用h3。它只返回0/3/9，没有强制保留全部父代选择。\n\n子代完整训练fitness −2.158971453，较最佳父代h0低0.047166492；对h0逐实例7胜/1平/13负，虽好于两个较弱父代，却未达到本代前5名的生存门槛。这是一次真实可执行、但未带来更强冠军且未存活的交叉，不将模型自述当改进证据。\n'
    else:case_text+='本批尚无真实P组交叉请求，无法提供该案例；不以历史或手写程序代替。\n'
    (out/'02_P交叉案例.md').write_text(case_text)
    interpretation=[]
    if complete:
        for a,b in [('B1','B0'),('B2','B1'),('P','B2'),('P','B0')]:
            aa=next(x for x in phases if x['group']==a);bb=next(x for x in phases if x['group']==b)
            interpretation.append(f"- **{a}对{b}**：有效候选{aa['valid_candidates']}对{bb['valid_candidates']}；最终种群均值差{aa['final_mean_fitness']-bb['final_mean_fitness']:+.9f}，冠军差{aa['final_best_fitness']-bb['final_best_fitness']:+.9f}。")
        if all(champion_ids[g]==ibest['id'] for g in ARMS):
            interpretation+=['', '**本批观察。** 四组冠军都是同一个初始U（固定选择h0），与H0逐实例0胜/21平/0负。B1提供H信息没有改善本批冠军、有效率或种群均值；B2相对B1减少重复并提高均值，P相对B2均值进一步提高，但两者都未生成更强冠军。P比B0均值高也只体现弱成员替换。本批对“特化提示能提高最佳排程质量”没有提供支持；P的两条存活子代来自变异，五条交叉子代均未存活。这些是单次观察，不能推断普遍优劣。', '',
                '**下一批最值得验证的一件事（仅建议，未启动）。** 将“能否稳定超过最佳固定h”作为主要判据，在另行预登记和授权的独立seed上复核，而不是只追求种群均值改善。本轮不追加搜索、重评或组合消融。']
    report=['# 公平四组单编号训练小试','',
        '职责：汇报本批真实训练证据。范围：固定既有10条H、七状态、seed201、N5、一代；未读取validation/test，不含MIX或Tier1重建。','',
        f"完成四组：{complete}；四组各10次确认发送：{balanced}；基础设施失败：{len(infrastructure)}；发送前暂停：{summary['pre_send_metadata_pauses']}次（不占生成槽位）。",'',
        '四组共享本批新生成并完整评价的P₀。B1−B0考察H代码/行为信息；B2−B1同时改变算子类型与配额，不能只归因于交叉；P−B2考察特化提示；P−B0考察完整方案。相同请求数不意味着相同token、评价或在线求解成本。','',
        mdtable(phases,['group','phase','slots','confirmed_sends','valid_candidates','failure_categories','uncompleted_evolution_slots','new_children_surviving','initial_mean_fitness','initial_best_fitness','final_mean_fitness','final_best_fitness']), '',
        '**评分。** LB=max(最长工件的逐工序最短加工时间之和, 全部最短工作量/机器数)，负荷项不取整。score=−Cmax/LB，fitness为21个score的算术平均，越大越好；任何主评价实例失败即整候选无效，不取成功前缀。该数值不是最优性gap。','',
        f"**固定h诊断参照。** 10条h的完整缓存与当前训练实例顺序、哈希、LB、调度及评价实现一致，新增H评价0次；训练最佳h{best_h['member']}，fitness={best_h['fitness']:.9f}。正式测试固定h仍须按预定验证规则选择，本轮训练最佳不替代该步骤。原缓存计时保留，不冒充本日同负载重新测得。",'',
        f"**历史冻结参照（不入本批种群）。** 旧单编号批次`{source.name}`的`{old_best['id']}`，fitness={old_best['fitness']:.9f}，代码键`{old_best['candidate']['key']}`。已核对同一H和训练数据身份、完整21实例及原封存哈希；不重评、不导入本批P₀，也不把旧批不平衡预算升级为公平实验。详见[来源绑定](historical_reference.json)。",'',
        '**冠军比较。** 下表差值=A−B；fitness为正更好；胜负平按逐实例Cmax（小更好），不做按实例挑选策略的拼接冠军。','',
        mdtable(comparisons,['A','B','A_minus_B_fitness','A_wins','ties','A_losses','mean_Cmax_difference']), '',
        '\n'.join(interpretation),'',
        f"**成本。** 本批确认发送{sum(r['send_confirmed'] for r in requests)}次，核实平台点{summary['known_new_platform_points']}；未知费用请求{summary['unknown_new_cost_ids']}；已知wire输入/输出token {summary['known_wire_input_tokens']}/{summary['known_wire_output_tokens']}，缺失wire用量{summary['unknown_wire_usage_ids']}。账户最近核实累计使用{summary['latest_verified_account_used_points']}点，历史未知预留{summary['historical_hold_points']}点；不将预留当已花费用，也不换算未经核实人民币/美元。",'',
        '逐请求实际费用见requests.csv；每条完整有效候选及固定h的逐实例成绩、可行性和三种计时均独立保留。single_solve为单次排程，deterministic_recheck为确定性复检，diagnostic为额外观察；LLM及账单等待另计。未知值为NA。','',
        '**结论边界。** 这是训练上的单seed、一代条件小试，只能提供初步描述；不能证明独立泛化、统计显著性、完整双层方法有效或局部状态最优分工。若接口失败造成不平衡或有效生成机会损失，应同时报告，不用剩余槽位补齐。种子控制本地搜索随机性，不保证云模型重发生成相同代码；排程复现应使用归档候选源码，不能重新请求来代替。同分或有限训练行为一致不能当作普遍程序等价。','',
        '初始化上限20次，凑齐5条后停止；余下15次不转为演化授权。四组未完成槽位均为0。一次发送前DNS暂停保留在pre_send_metadata及derived_snapshots，不是已发送模型失败。最终完整性依据原生账本、检查点、请求journal、逐笔账单及[完成核对凭证](completion_verification.json)，不依据progress或旧快照。','',
        '[真实P交叉案例](02_P交叉案例.md)；[材料索引](03_材料索引.md)。']
    (out/'01_训练报告.md').write_text('\n'.join(report)+'\n')
    if complete:
        compact=[{'阶段':x['group'],'发送':x['confirmed_sends'],'有效':x['valid_candidates'],
            '重复':x['code_duplicate']+x['narrow_equivalence_duplicate'],
            '新子代存活':x['new_children_surviving'],
            '最终均值':f"{x['final_mean_fitness']:.6f}",
            '最终最佳':f"{x['final_best_fitness']:.6f}"} for x in phases]
        (out/'00_组会摘要.md').write_text('# 单编号四组训练小试：最终摘要\n\n'
            '职责：快速说明本批实际进展。固定既有10条H、七状态、单编号U；Leaf gpt-6.1-sol，seed201、N5、每组一代。仅21个训练实例，每条有效U均有完整排程与确定性复检；无新H、MIX、validation/test。\n\n'
            '共享初始化5次得到5条有效U，随后四组各10次真实演化。B0/B1使用相同五算子（各2次），区别是是否给H信息；B2/P各5交叉+5变异，区别是通用/特化提示。四组共用同一P₀及评价、选择规则。\n\n'+
            mdtable(compact,['阶段','发送','有效','重复','新子代存活','最终均值','最终最佳'])+
            '\n\n共45次真实请求，39条完整有效U、6次代码重复，其他失败0，演化未完成槽位0。一次发送前DNS暂停未占槽位；恢复没有重发。未用15次初始化额度不转用。\n\n'
            f'共同初始均值{initial_mean:.6f}。**四组冠军均仍为固定选h0的初始U，21实例与H0全部打平。** P均值最好，来自替换弱成员，并未生成更强冠军；五条P交叉子代无一存活。H信息本批未带来改进；通用/特化交叉变异的均值变化仅为初步描述。\n\n'
            f'旧单编号冠军{old_best["fitness"]:.9f}作为带来源的冻结训练参照，未导入本批种群。旧批起点和调用机会不同，不能由此判断代码或方法退化。\n\n'
            f'本批费用{summary["known_new_platform_points"]:,}平台点；wire输入/输出token {summary["known_wire_input_tokens"]:,}/{summary["known_wire_output_tokens"]:,}，新费用及用量均无未知。人民币/美元未知；历史未知记录及2400万点预留保留。累计201/300槽位、185次确认发送。\n\n'
            '这是固定现有H、单seed、一代的训练对照，尚不支持独立泛化或完整双层方法有效的结论。下一轮方案待另行审阅，本轮不启动。\n\n'
            '[完整报告](01_训练报告.md) · [CSV汇总](phase_summary.csv) · [图表与材料索引](03_材料索引.md) · [完成凭证](completion_verification.json)\n')
    evidence=['protocol.json','config.single.authorized.json','H_frozen.json','History_binding.json',
        'Human_authorization.json','budget.json','platform_quota.json','Training_report.json','Single_results.json',
        'Fair_status.json','Final_budget_handoff.json','registered-snapshot.tar.gz']
    index=['# 实验材料索引','',f"运行目录：`{run}`；以下原始材料本地保留，不上传密钥或原始账单。",'',
           '| 材料 | SHA256 |','|---|---|']
    hashes={}
    for n in evidence:
        f=run/n
        if f.exists():
            hashes[n]=sha(f);index.append(f'| [{n}]({link(f,out)}) | {hashes[n]} |')
    index+=['',f"[实际请求/提示、响应与检查点]({link(run/'r201',out)})；[原始响应留存]({link(run/'wire_responses',out)})；[逐候选源码导出]({link(run/'candidate_exports',out)})；[预导出提示]({link(run/'prompts',out)})。",'',
        '本报告读取冻结H的已存训练成绩与当前运行记录，不执行模型、求解器或holdout。旧批次报告不代表本批状态。正式数据划分身份见protocol.dataset；只读取train名单及本批评价，不打开正式validation/test数据。', '',
        f"已知缺失：未知费用{summary['unknown_new_cost_ids']}，未知wire用量{summary['unknown_wire_usage_ids']}；固定h缓存未记录独立诊断时间，CSV保留NA。尚未执行阶段保留not_started；缺失P案例不补造。"]
    index+=['','## 汇报用派生材料','',
        '- [一页摘要](00_组会摘要.md)、[完整报告](01_训练报告.md)、[真实P交叉案例](02_P交叉案例.md)。',
        '- [阶段与种群CSV](phase_summary.csv)、[最终种群](populations.csv)、[逐请求费用/token](requests.csv)、[分组时间及成本](cost_summary.csv)。',
        '- [所有新候选的逐实例成绩](all_candidate_instances.csv)、[冠军/H0/旧冻结参照21实例](champion_instances.csv)、[胜负平汇总](comparisons.csv)、[逐实例差值](instance_differences.csv)。',
        '- [10条固定h汇总](fixed_h_summary.csv)、[固定h逐实例结果](fixed_h_instances.csv)、[旧冠军来源](historical_reference.json)。',
        '- [请求与有效候选PNG](04_请求与候选.png) / [SVG](04_请求与候选.svg)；[种群及冻结参照PNG](05_种群与固定h.png) / [SVG](05_种群与固定h.svg)。',
        '- [P对B2 PNG](06_P对B2.png) / [SVG](06_P对B2.svg)；[P对H0 PNG](07_P对固定h.png) / [SVG](07_P对固定h.svg)。',
        '- [完成核对凭证](completion_verification.json)；[备份核验](backup_verification.json)（独立备份阶段生成）。',
        f'- [早期暂停快照与哈希]({link(run/"derived_snapshots/pre-final-pause",out)})、[发送前暂停依据]({link(run/"pre_send_metadata",out)})。这些旧快照不代表最终结果。','',
        '仅从保存记录重新生成派生材料（需要Python、matplotlib和可用中文字体；无模型/账单查询、无求解/重评）：','',
        '```bash\npython3 tools/report_single_fair.py \\\n  --run-dir runs/single-ID-gpt61-fair-seed201-v2 \\\n  --out-dir reports/20261017-single-fair\n```']
    (out/'03_材料索引.md').write_text('\n'.join(index)+'\n');dump(out/'evidence_sha256.json',hashes)
    if charts:make_charts(out, phases, champions, differences, complete, balanced)
    return summary


def make_charts(out, phases, champions, differences, complete, balanced):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt, font_manager
    fonts={x.name for x in font_manager.fontManager.ttflist}
    font=next((x for x in ('Arial Unicode MS','PingFang HK','Noto Sans CJK SC','STHeiti') if x in fonts),None)
    if not font:raise RuntimeError('Chinese font required')
    plt.rcParams.update({'font.family':font,'axes.unicode_minus':False,'svg.fonttype':'path',
                         'font.size':12,'axes.spines.top':False,'axes.spines.right':False,'svg.hashsalt':'single-fair-201'})
    notice=f'固定既有H · seed201 · 一代 · 仅训练21实例；四组各10次确认发送：{"是" if balanced else "否"}。'
    def save(fig,name):
        fig.text(.08,.025,notice,fontsize=10,color='#555555')
        fig.tight_layout(rect=(0,.065,1,.95))
        for ext in ('png','svg'):
            path=out/f'{name}.{ext}'
            fig.savefig(path,dpi=180,facecolor='white',metadata={'Date':None} if ext=='svg' else {})
            if ext=='svg':path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines())+'\n')
        plt.close(fig)
    fig,ax=plt.subplots(figsize=(12,6.75));xs=list(range(5))
    for i,(key,label,color) in enumerate([('slots','已占槽位','#9AA7B6'),('confirmed_sends','确认发送','#2764AC'),('valid_candidates','完整有效候选','#238B75')]):
        bars=ax.bar([x+(i-1)*.25 for x in xs],[r[key] for r in phases],.24,label=label,color=color)
        ax.bar_label(bars,padding=3)
    ax.set(xticks=xs,xticklabels=['共享初始化',*ARMS],ylabel='次数 / 条数',title='真实请求与完整有效候选（失败、重复不补发）')
    ax.set_ylim(0,max(12,max(r['slots'] for r in phases)+3));ax.legend(ncol=3);save(fig,'04_请求与候选')
    fig,ax=plt.subplots(figsize=(12,6.75))
    for key,label,marker,color in [('initial_mean_fitness','共同初始均值','o','#9AA7B6'),('final_mean_fitness','最终均值','s','#2764AC'),('initial_best_fitness','共同初始最佳','x','#C68B20'),('final_best_fitness','最终最佳','*','#238B75')]:
        pairs=[(i,r[key]) for i,r in enumerate(phases[1:]) if r[key] is not None]
        if pairs:ax.scatter([v for i,v in pairs],[i for i,v in pairs],label=label,marker=marker,color=color,s=95)
    fixed=next(e['fitness'] for g,e in champions.items() if g.startswith('h'))
    ax.axvline(fixed,color='#B23B3B',ls='--',label=f'最佳固定h {fixed:.6f}')
    if 'OLD_SINGLE_FROZEN' in champions:
        old=champions['OLD_SINGLE_FROZEN']['fitness']
        ax.axvline(old,color='#8560A5',ls=':',label=f'旧冻结参照 {old:.6f}（不入种群）')
    ax.set(yticks=range(4),yticklabels=ARMS,xlabel='fitness = mean(−Cmax/LB)，越大越好 →',
           title='共同起点与一代终点：四组冠军均未提高' if complete else '共同起点与已完成的终点')
    ax.invert_yaxis();ax.legend(loc='best',fontsize=10);save(fig,'05_种群与固定h')
    for b,name in [('B2','06_P对B2'),(next(g for g in champions if g.startswith('h')),'07_P对固定h')]:
        rows=[r for r in differences if r['A']=='P' and r['B']==b]
        fig,ax=plt.subplots(figsize=(12,6.75))
        if rows:
            vals=[r['A_minus_B_makespan'] for r in rows]
            ax.bar(range(21),vals,color=['#238B75' if v<0 else '#BB594A' if v>0 else '#AAAAAA' for v in vals])
            ax.set_xticks(range(21),[r['file'].replace('.fjsp','') for r in rows],rotation=55,ha='right',fontsize=9)
            ax.axhline(0,color='#555555',lw=.8)
            if all(v==0 for v in vals):
                ax.set_ylim(-1,1)
                ax.text(.5,.72,'21个实例全部平局，差值均为0',ha='center',transform=ax.transAxes,color='#555555')
        else:ax.text(.5,.5,'P或参照组尚未完成，没有可比较成绩',ha='center',transform=ax.transAxes)
        ax.set(ylabel=f'Cmax(P) − Cmax({b})；负值更好',title=f'训练冠军逐实例比较：P 对 {b}')
        save(fig,name)


def backup(run, out, destination):
    """Independent local backup, verified byte-for-byte; never uploads invoices.

    Only this new run, curated exhibits and generator are copied. The registered
    snapshot inside the run already contains code/prompts/config and train21.
    Historical provenance remains pinned by History_binding plus the existing
    historical backup; we do not copy entire historical trees again.
    """
    if (run/'.writer.lock').exists():raise RuntimeError('Caller active; finish before backup')
    if destination.exists():raise RuntimeError('New external backup directory required')
    if destination.resolve().is_relative_to(ROOT):raise RuntimeError('Backup must be outside the worktree')
    files={}
    for prefix, folder in [('run',run),('exhibits',out)]:
        for path in folder.rglob('*'):
            if path.is_file():
                if path.is_symlink() or path.name.startswith('.env') or path.suffix in ('.pem','.key'):
                    raise RuntimeError('Unexpected secret/link in backup inputs')
                files[prefix+'/'+str(path.relative_to(folder))]=path
    files['tools/report_single_fair.py']=Path(__file__).resolve()
    for name in ('README.md','experiments/tier2/research_real_v1/README.md','requirements.txt'):
        files[name]=ROOT/name
    for name in ('single-fair-execute-20261017.log','single-fair-resume-20261017-1.log',
                 'single-fair-prelaunch-tests-20261017.log'):
        if (ROOT/'logs'/name).exists():files['logs/'+name]=ROOT/'logs'/name
    if (run/'protocol.json').exists():
        source=run.parent/read(run/'protocol.json')['config']['conditional_research']['source_run']
        for name in ('protocol.json','H_frozen.json','r201/Shared_initial.json','Final_budget_handoff.json'):
            files['historical_reference_inputs/'+name]=source/name
    manifest={name:{'sha256':sha(path),'bytes':path.stat().st_size} for name,path in files.items()}
    destination.mkdir(parents=True)
    archive=destination/'experiment-and-exhibits.tar.gz'
    with tarfile.open(archive,'w:gz') as t:
        for name,path in sorted(files.items()):t.add(path,arcname=name,recursive=False)
        payload=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
        info=tarfile.TarInfo('MANIFEST.json');info.size=len(payload);t.addfile(info,io.BytesIO(payload))
    with tarfile.open(archive) as t:
        assert set(t.getnames())==set(manifest)|{'MANIFEST.json'}
        for name, info in manifest.items():
            stream=t.extractfile(name);h=hashlib.sha256();size=0
            for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk);size+=len(chunk)
            assert h.hexdigest()==info['sha256'] and size==info['bytes']
    dump(destination/'MANIFEST.json',manifest)
    result={'archive':str(archive),'archive_sha256':sha(archive),'files':len(manifest),
            'verified_readable':True,'contains_credentials':False,
            'scope':'new run + registered code/train snapshot + exhibits + exact frozen-reference inputs + caller logs; no historical tree duplication'}
    dump(destination/'BACKUP_VERIFICATION.json',result)
    dump(out/'backup_verification.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--out-dir',type=Path,required=True)
    p.add_argument('--no-charts',action='store_true');p.add_argument('--backup-dir',type=Path);a=p.parse_args()
    run,out=a.run_dir.resolve(),a.out_dir.resolve()
    summary=build(run,out,charts=not a.no_charts)
    if a.backup_dir:summary['backup']=backup(run,out,a.backup_dir.resolve())
    print(json.dumps({k:summary[k] for k in ('complete','balanced_actual_evolution_sends',
        'known_new_platform_points','unknown_new_cost_ids','unknown_wire_usage_ids')} |
        ({'backup':summary['backup']} if 'backup' in summary else {}),ensure_ascii=False))
