"""Read-only certification/analysis of the frozen A4 campaign; never schedules.

This post-processing tool is deliberately outside the frozen evaluator source
closure. It can inspect a terminal campaign or preserve a certified completed
prefix following Stop; unresolved reservations are never accepted as results.
"""
import csv
import hashlib
import json
from pathlib import Path
import shutil
from statistics import fmean

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'runs/a4-static-rs60x5-train21-seed501-v1'
OUT = ROOT / 'reports/a4-closeout-20261025-v1'
AUDIT = ROOT / 'reports/a4-evidence-protocol-20261024-v1'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def table(name, rows):
    if not rows:
        return
    with (OUT / name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def spec(ticket):
    if ticket < 10:
        return f'H{ticket}', {ticket: 1.}
    pairs = [(i, j) for i in range(10) for j in range(i + 1, 10)]
    index, k = divmod(ticket - 10, 19)
    i, j = pairs[index]
    a = (k + 1) / 20.
    return f'H{i}({a:.2f}) + H{j}({1-a:.2f})', {i: a, j: 1. - a}


def compare(a, b):
    assert len(a) == len(b) == 21
    assert [r['file'] for r in a] == [r['file'] for r in b]
    assert [r['lower_bound'] for r in a] == [r['lower_bound'] for r in b]
    fa, fb = fmean(r['score'] for r in a), fmean(r['score'] for r in b)
    ds = [x['makespan'] - y['makespan'] for x, y in zip(a, b)]
    return {'delta_F': fa-fb, 'wins': sum(d < 0 for d in ds),
            'losses': sum(d > 0 for d in ds), 'ties': ds.count(0),
            'relative_mean_Cmax_over_LB_percent': ((-fa)/(-fb)-1)*100,
            'sum_Cmax_A': sum(r['makespan'] for r in a),
            'sum_Cmax_B': sum(r['makespan'] for r in b)}


def main():
    from fjsp_usage.baseline_a.validation import validate_result
    from fjsp_usage.baseline_supplemental.lifecycle import classify
    from fjsp_usage.research.protocol import digest
    p = read(RUN / 'Protocol.json')
    plans, state = read(RUN / 'Plans.json'), read(RUN / 'checkpoint.json')
    assert sha(RUN / 'Protocol.json') == state['protocol_sha256'] == (RUN / 'Protocol.sha256').read_text().strip()
    assert sha(RUN / 'Plans.json') == p['plans_sha256']
    assert all(all(type(t) is int and 0 <= t < 865 for t in plan) for plan in plans)
    assert len(plans) == 5 and all(len(v) == len(set(v)) == 60 for v in plans)
    assert p['search_seeds'] == list(range(2026102601, 2026102606))
    assert (p['new_evaluation_cap'], p['new_solve_pass_cap'], p['LLM_API_cap']) == (6300, 12600, 0)
    assert p['result_wait_seconds'] == 30 and p['solve_seed'] == 501
    expected = {**p['source_files'], **p['protected_files']}
    for n, h in expected.items():
        assert sha(ROOT / n) == h, n
    end_files={n:sha(ROOT/n) for n in expected}
    identity = read(RUN / 'Expected_loaded_identity.json')['identity']
    sources = {}

    def source(path, expected_hash=None):
        value = sha(path)
        if expected_hash is not None:
            assert value == expected_hash, str(path)
        sources[str(path.relative_to(ROOT))] = value
        return read(path)

    results, queries, failures, processes, starts, refs = {}, [], [], [], [], []
    flat = [(r, k, t) for r, plan in enumerate(plans) for k, t in enumerate(plan)]
    reserved = []
    for position, q in enumerate(state['queries']):
        assert (q['repeat'], q['slot'], q['ticket']) == flat[position]
        assert (q['logical_evaluations'], q['logical_passes']) == (21, 42)
        if q['status'] != 'completed':
            reserved.append(q)
            continue
        path = RUN / q['result_path']
        assert path.resolve().is_relative_to(RUN.resolve())
        result = source(path, q['result_sha256'])
        prov = source(path.parent / 'provenance.json', q['provenance_sha256'])
        for n, h in prov.get('evidence_sha256', {}).items():
            ep = path.parent / n
            assert ep.resolve().is_relative_to(path.parent.resolve())
            source(ep, h)
        if q['origin'] == 'historical_cache':
            h = prov['source']
            old = source(ROOT / h['path'], h['sha256'])
            assert old == result and result['valid']
        elif q['origin'] == 'campaign_cache':
            old = source(Path(prov['path']), prov['sha256'])
            assert old == result
        elif q['origin'] == 'new':
            folder = path.parent / 'evidence'
            before, life = read(folder / 'before.json'), read(folder / 'lifecycle.json')
            after = read(folder / 'after.json') if (folder / 'after.json').exists() else None
            boundary = classify(result, before=before, after=after, lifecycle=life,
                expected_identity=identity, expected_files=expected, start_files=expected,
                end_files=end_files, worker_failure=(folder/'worker_failure.json').exists())
            assert boundary == read(folder/'boundary.json') == result['boundary']
            assert boundary['decision'] in ('accepted', 'candidate_invalid_continue')
            validate_result(result, p['instances'], 'modern')
            processes.append({'query': position+1, 'ticket': q['ticket'], 'pid': life['pid'],
                'valid': result['valid'], 'boundary': boundary['decision'], 'reason': boundary['reason'],
                'exitcode': life['exitcode'], 'alive': life['alive'],
                'reader_stopped': life['receiver_thread_stopped'],
                'perf_elapsed_seconds': result['primary_evaluation_seconds'],
                'exit_wait_seconds': life['exit_wait_observed_seconds'],
                'rows_received': life['rows_received'], 'failed_instance': result.get('failed_instance'),
                'successful_prefix_first_seconds':sum(r['single_solve_seconds'] for r in result['instances']),
                'successful_prefix_recheck_seconds':sum(r['deterministic_recheck_seconds'] for r in result['instances']),
                'successful_prefix_CPU_seconds':sum(r.get('instance_CPU_seconds',0) for r in result['instances']),
                'h_scoring_seconds':sum(r[c]['h_scoring_seconds'] for r in result['instances'] for c in ('first_costs','recheck_costs')),
                'fusion_seconds':sum(r[c]['fusion_seconds'] for r in result['instances'] for c in ('first_costs','recheck_costs')),
                'network_guard': json.dumps(read(folder/'network_guard.json')) if (folder/'network_guard.json').exists() else 'terminated_before_final_guard'})
            for marker in sorted(folder.glob('*.progress.json')):
                m = read(marker)
                starts.append({'query': position+1, 'ticket': q['ticket'], 'file': m['file'],
                    'first_started': m['first_started'], 'recheck_started': m['recheck_started'],
                    'completed': m['completed'], 'phase': next((k for k in
                        ('result_write_end','recheck_end','recheck_start','first_end','first_start') if k in m),'unknown')})
        else:
            raise ValueError('unknown result origin')
        assert q['physical_reserved_evaluations'] == (21 if q['origin'] == 'new' else 0)
        assert q['physical_reserved_passes'] == 2*q['physical_reserved_evaluations']
        assert result['total_instances'] == 21
        for row, e in zip(result['instances'], p['instances']):
            assert row['file'] == e['file'] and row['lower_bound'] == e['LB']
            assert row['score'] == -row['makespan']/e['LB']
        if result['valid']:
            assert len(result['instances']) == 21 and result['fitness'] == fmean(r['score'] for r in result['instances'])
        else:
            assert result['fitness'] is None
            failures.append({'query': position+1, 'repeat': q['repeat']+1, 'slot': q['slot']+1,
                'ticket': q['ticket'], 'strategy': spec(q['ticket'])[0], 'origin': q['origin'],
                'error_type': result.get('error_type'), 'failed_instance': result.get('failed_instance'),
                'successful_prefix': len(result['instances']), 'fitness': None})
        results[position] = result
        queries.append({'query': position+1, 'repeat': q['repeat']+1, 'seed': p['search_seeds'][q['repeat']],
            'slot': q['slot']+1, 'ticket': q['ticket'], 'strategy': spec(q['ticket'])[0],
            'raw_weights_json': json.dumps(spec(q['ticket'])[1], sort_keys=True),
            'origin': q['origin'], 'valid': result['valid'], 'fitness': result['fitness']})

    curves, repeats, champions = [], [], {}
    for r, seed in enumerate(p['search_seeds']):
        incumbent, incumbent_position = None, None
        subset = [q for q in queries if q['repeat'] == r+1]
        for q in subset:
            if q['valid'] and (incumbent is None or q['fitness'] > incumbent):
                incumbent, incumbent_position = q['fitness'], q['query']-1
            curves.append({**q, 'best_so_far': incumbent,
                'incumbent_ticket': state['queries'][incumbent_position]['ticket'] if incumbent_position is not None else None})
        win = state['queries'][incumbent_position] if incumbent_position is not None else None
        repeats.append({'repeat': r+1, 'seed': seed, 'consumed': len(subset), 'budget_complete': len(subset) == 60,
            'valid': sum(q['valid'] for q in subset), 'invalid': sum(not q['valid'] for q in subset),
            'new': sum(q['origin']=='new' for q in subset),
            'historical_cache': sum(q['origin']=='historical_cache' for q in subset),
            'campaign_cache': sum(q['origin']=='campaign_cache' for q in subset),
            'champion_query': incumbent_position+1 if win else None,
            'champion_slot':win['slot']+1 if win else None,
            'ticket': win['ticket'] if win else None, 'strategy': spec(win['ticket'])[0] if win else None,
            'fitness': incumbent, 'sum_Cmax': sum(x['makespan'] for x in results[incumbent_position]['instances']) if win else None})
        if win:
            champions[f'repeat_{r+1}_'+('complete60' if len(subset)==60 else 'partial33')] = results[incumbent_position]
    valid_queries = [q for q in queries if q['valid']]
    best = max(valid_queries, key=lambda q:q['fitness']) if valid_queries else None
    if best:
        champions['observed_93_query_best_NOT_60_typical'] = results[best['query']-1]
    unique = {}
    for q in queries:
        unique.setdefault(q['ticket'],q)
    ranked = []
    for q in sorted(unique.values(),key=lambda q:(not q['valid'],-q['fitness'] if q['valid'] else 0,q['query'])):
        result=results[q['query']-1]
        hashes=[r.get('physical_schedule_sha256') for r in result['instances']]
        ranked.append({**q,'sum_Cmax':sum(r['makespan'] for r in result['instances']) if result['valid'] else None,
            'physical_group_sha256':digest(hashes) if result['valid'] and len(hashes)==21 and all(hashes) else None})
    summary_ref = read(AUDIT/'A1_A3_verified.json')
    for label, identifier in [('H0','H0'), ('equal_H0_H1','H0_H1_WS')]:
        row = next(v for v in summary_ref['sources'] if v['id']==identifier)
        legacy=source(ROOT/row['path'], row['sha256'])
        modern_path=ROOT/'runs/baseline-a-supplemental-T30-seed501-20261024-v1/evidence'/identifier/'result.json'
        modern=source(modern_path,expected[str(modern_path.relative_to(ROOT))])
        assert modern['fitness']==legacy['fitness']
        assert [r['makespan'] for r in modern['instances']]==[r['makespan'] for r in legacy['instances']]
        refs.append((label, modern))
    # Audited raw checkpoint (in the frozen protected closure), never a new U run.
    b2_path=ROOT/'runs/h01-state-weight-search-seed501-batch-v3-20261020/r501/B/checkpoint.json'
    b2_checkpoint=source(b2_path,expected[str(b2_path.relative_to(ROOT))])
    refs.append(('historical_B2', b2_checkpoint['evaluations']['B/g0001/000000']['result']))
    comparisons, instance_diff, schedules = [], [], []
    for label, a in champions.items():
        for ref_label, b in refs:
            comparisons.append({'method': label, 'reference': ref_label, **compare(a['instances'],b['instances'])})
            same_physical, same_commit, physical_n, commit_n = 0, 0, 0, 0
            for x,y in zip(a['instances'],b['instances']):
                instance_diff.append({'method': label, 'reference': ref_label, 'file': x['file'],
                    'LB': x['lower_bound'], 'Cmax_A': x['makespan'], 'Cmax_B': y['makespan'],
                    'delta_Cmax': x['makespan']-y['makespan'], 'score_A': x['score'],
                    'score_B': y['score'], 'delta_score': x['score']-y['score']})
                hp=x.get('physical_schedule_sha256');hq=y.get('physical_schedule_sha256')
                if hp is not None and hq is not None:
                    physical_n+=1; same_physical+=hp==hq
                hp=x.get('commit_sequence_sha256');hq=y.get('commit_sequence_sha256')
                if hp is not None and hq is not None:
                    commit_n+=1; same_commit+=hp==hq
            schedules.append({'method':label,'reference':ref_label,'physical_compared':physical_n,
                'same_physical':same_physical,'commit_compared':commit_n,'same_commit':same_commit})

    clock=read(RUN/'Run_clock.json')
    assert sha(RUN/'Run_clock.json')==state['run_clock_sha256']
    assert clock['deadline_utc_epoch']==clock['start_utc_epoch']+21600
    physical_reserved=sum(q['physical_reserved_evaluations'] for q in state['queries'])
    assert physical_reserved<=6300
    summary={'method':'固定预算的成员与静态权重联合随机搜索基线','phase':state['phase'],
        'certified_completed_queries':len(queries),'unresolved_reservations':reserved,
        'Stop':read(RUN/'Stop.json') if (RUN/'Stop.json').exists() else None,
        'planned_queries':300,'logical_slots_reserved':len(state['queries']),
        'logical_instance_evaluations_reserved':21*len(state['queries']),
        'logical_passes_reserved':42*len(state['queries']),
        'physical_instance_evaluations_reserved':physical_reserved,'physical_passes_reserved':physical_reserved*2,
        'first_starts':sum(m['first_started'] for m in starts),'recheck_starts':sum(m['recheck_started'] for m in starts),
        'completed_new_instance_pairs':sum(m['completed'] for m in starts),
        'historical_cache_queries':sum(q['origin']=='historical_cache' for q in queries),
        'campaign_cache_queries':sum(q['origin']=='campaign_cache' for q in queries),
        'new_queries':sum(q['origin']=='new' for q in queries),
        'invalid_queries':len(failures),'unique_invalid_tickets':len({q['ticket'] for q in failures}),
        'invalid_memo_queries':sum(q['origin']=='campaign_cache' for q in failures),
        'valid_queries':len(valid_queries),'distinct_queried_strategies':len({q['ticket'] for q in queries}),
        'construction_legal_rate':1 if queries else None,
        'invalid_rate':len(failures)/len(queries) if queries else None,
        'cache_query_rate':sum(q['origin']!='new' for q in queries)/len(queries) if queries else None,
        'within_repeat_duplicate_count':sum(len([q for q in queries if q['repeat']==r])-len({q['ticket'] for q in queries if q['repeat']==r}) for r in range(1,6)),
        'cross_repeat_repeated_tickets':len(queries)-len({q['ticket'] for q in queries}),
        'completed_repeats':sum(r['budget_complete'] for r in repeats),
        'distinct_valid_strategies':sum(q['valid'] for q in unique.values()),
        'physical_groups_complete_comparable':len({q['physical_group_sha256'] for q in ranked if q['physical_group_sha256']}),
        'physical_group_comparable_strategies':sum(q['physical_group_sha256'] is not None for q in ranked),
        'distinct_valid_exceed_equal_H01':sum(q['valid'] and q['fitness']>p['external_reference_fitness']['Best_Equal_Pair'] for q in ranked),
        'distinct_valid_exceed_historical_B2':sum(q['valid'] and q['fitness']>p['external_reference_fitness']['historical_B2'] for q in ranked),
        'complete_repeats_exceed_equal_H01':sum(r['budget_complete'] and r['fitness'] is not None and r['fitness']>p['external_reference_fitness']['Best_Equal_Pair'] for r in repeats),
        'complete_repeats_exceed_historical_B2':sum(r['budget_complete'] and r['fitness'] is not None and r['fitness']>p['external_reference_fitness']['historical_B2'] for r in repeats),
        'equal_H01_queries':sum(q['ticket']==19 for q in queries),
        'campaign_best':best,'repeats':repeats,
        'new_primary_perf_seconds':sum(x['perf_elapsed_seconds'] for x in processes),
        'new_exit_wait_seconds':sum(x['exit_wait_seconds'] for x in processes),
        'new_successful_prefix_CPU_seconds':sum(x['successful_prefix_CPU_seconds'] for x in processes),
        'new_h_scoring_seconds':sum(x['h_scoring_seconds'] for x in processes),
        'new_fusion_seconds':sum(x['fusion_seconds'] for x in processes),
        'valid_new_process_nonsolve_perf_seconds':sum(x['perf_elapsed_seconds']-x['successful_prefix_first_seconds']-x['successful_prefix_recheck_seconds'] for x in processes if x['valid']),
        'new_successful_prefix_first_seconds':sum(r.get('single_solve_seconds',0) for i,x in results.items() if state['queries'][i]['origin']=='new' for r in x['instances']),
        'new_successful_prefix_recheck_seconds':sum(r.get('deterministic_recheck_seconds',0) for i,x in results.items() if state['queries'][i]['origin']=='new' for r in x['instances']),
        'peak_RSS_bytes_macos':max((r.get('peak_RSS_bytes_macos',0) for i,x in results.items() if state['queries'][i]['origin']=='new' for r in x['instances']),default=None),
        'campaign_wall_seconds_checkpoint_mtime':(RUN/'checkpoint.json').stat().st_mtime-clock['start_utc_epoch'],
        'time_note':'checkpoint mtime estimates run terminal elapsed time; failed internal solve duration unknown, parent wall includes failed wait; exit wait is contained in primary wall',
        'protocol_sha256':sha(RUN/'Protocol.json'),'plans_sha256':sha(RUN/'Plans.json'),
        'API':0,'evolution':0,'holdout':0,'new_solves_from_analysis':0,
        'source_files_verified':len(expected),'accepted_new_processes':len(processes)}
    OUT.mkdir(exist_ok=True)
    for n, rows in [('Certified_queries.csv',queries),('Certified_best_so_far.csv',curves),
                    ('Champions.csv',repeats),('Failures.csv',failures),('Process_certification.csv',processes),
                    ('Actual_solve_starts.csv',starts),('Champion_comparisons.csv',comparisons),
                    ('Champion_instance_differences.csv',instance_diff),('Champion_schedule_comparisons.csv',schedules),
                    ('Unique_strategy_ranking.csv',ranked)]:
        table(n,rows)
    all_instances=[{'query':i+1,'repeat':state['queries'][i]['repeat']+1,'slot':state['queries'][i]['slot']+1,
        'ticket':state['queries'][i]['ticket'],'origin':state['queries'][i]['origin'],
        'file':r['file'],'Cmax':r['makespan'],'LB':r['lower_bound'],'score':r['score'],
        'first_seconds':r.get('single_solve_seconds'),'recheck_seconds':r.get('deterministic_recheck_seconds')}
        for i,result in results.items() for r in result['instances']]
    table('All_instances.csv',all_instances)
    table('Round1_best_so_far_60.csv',[r for r in curves if r['repeat']==1])
    table('Round2_partial_best_so_far_33.csv',[r for r in curves if r['repeat']==2])
    write(OUT/'Certified_summary.json',summary)
    write(OUT/'Certified_result_sources.json',{'files':sources,'current_source_verified':expected,
        'analysis_script_sha256':sha(Path(__file__)),'note':'Source hashes verified at analysis; original per-process start/end witnesses retained in run.'})
    for name in ('Protocol.json','Plans.json','Protocol.sha256','Run_clock.json','checkpoint.json','Expected_loaded_identity.json','H_frozen.json'):
        shutil.copyfile(RUN/name,OUT/name)
    lines=['# A4：固定预算的成员与静态权重联合随机搜索基线','',
        f"状态：{state['phase']}。已认证查询{len(queries)}/300；完整轮次{summary['completed_repeats']}/5；未认证预留{len(reserved)}。",
        '以下只分析预先冻结的五个搜索路径，固定H0–H9、train21、求解seed501、原V1 SELECT/WS。未追加候选、重试或加时；API、演化、留出访问均为0。','',
        '## 完整第一轮与第二轮partial','',
        '|搜索seed|已完成查询|有效／无效|冠军成员及静态权重|Fitness|新增／历史缓存／跨轮复用|',
        '|---|---:|---:|---|---:|---:|']
    for r in repeats:
        lines.append(f"|{r['seed']}|{r['consumed']}/60|{r['valid']}/{r['invalid']}|{r['strategy'] or '无'}|{r['fitness']}|{r['new']}/{r['historical_cache']}/{r['campaign_cache']}|")
    lines += ['', '本次只有一个完整60查询重复和一个33查询partial；不计算五轮分布、均值、IQR或独立重复稳定性。每项策略Fitness仍来自完整21实例。', '']
    if best:
        lines += [f"全campaign最佳：{best['strategy']}，Fitness {best['fitness']:.12f}，首次出现于第{best['repeat']}轮第{best['slot']}查询。它来自实际93次查询，**不是60次预算的典型表现**。",'']
    lines += ['## 与历史质量参照比较','',
        '|方法|参照|ΔFitness|逐实例胜／负／平|平均Cmax/LB相对变化%|Cmax总和A／B|',
        '|---|---|---:|---:|---:|---:|']
    for c in comparisons:
        lines.append(f"|{c['method']}|{c['reference']}|{c['delta_F']:+.12f}|{c['wins']}/{c['losses']}/{c['ties']}|{c['relative_mean_Cmax_over_LB_percent']:+.6f}|{c['sum_Cmax_A']}/{c['sum_Cmax_B']}|")
    lines += ['',f"不同有效策略中，{summary['distinct_valid_exceed_equal_H01']}个超过H0/H1等权，{summary['distinct_valid_exceed_historical_B2']}个超过历史B2；完整轮次中对应超过次数为{summary['complete_repeats_exceed_equal_H01']}/{summary['completed_repeats']}和{summary['complete_repeats_exceed_historical_B2']}/{summary['completed_repeats']}。H0/H1等权自身被实际查询{summary['equal_H01_queries']}次，没有免费加入incumbent。",
        '胜负平按相同实例Cmax；ΔFitness越大越好，平均Cmax/LB相对变化越小越好。旧B1/B2仅作质量参照：历史初始化、研发额外查询、T15/T30及非同期计时不同，不能称预算公平对照。','',
        '## 预算、缓存与失败','',
        f"逻辑预留{len(state['queries'])}槽／{21*len(state['queries'])}项／{42*len(state['queries'])}遍；新增物理预留{physical_reserved}项／{physical_reserved*2}遍。实际首解启动{summary['first_starts']}，复检启动{summary['recheck_starts']}，完成两遍的实例{summary['completed_new_instance_pairs']}。预留不等于实际启动。",
        f"历史质量缓存{summary['historical_cache_queries']}次，campaign复用{summary['campaign_cache_queries']}次；缓存也计查询。{summary['invalid_queries']}次无效查询涉及{summary['unique_invalid_tickets']}个不同策略，其中{summary['invalid_memo_queries']}次是已确认T30失败的复用。共同失败来源须计入各搜索路径，不能当独立物理超时重复。",
        f"构造合法率{summary['construction_legal_rate']}；无效率{summary['invalid_rate']}；缓存查询率{summary['cache_query_rate']}；轮内重复{summary['within_repeat_duplicate_count']}，跨轮重复ticket数{summary['cross_repeat_repeated_tickets']}。",
        f"campaign终态checkpoint落盘时间差约{summary['campaign_wall_seconds_checkpoint_mtime']:.3f}秒；新进程perf_counter区间合计{summary['new_primary_perf_seconds']:.3f}秒（不含完整休眠，不能当作真实墙钟）。成功前缀首解／复检构造合计{summary['new_successful_prefix_first_seconds']:.3f}/{summary['new_successful_prefix_recheck_seconds']:.3f}秒。退出等待{summary['new_exit_wait_seconds']:.3f}秒已包含在进程perf_counter区间中，不重复相加。失败内部构造耗时未知，不填0。",
        f"全部有效且具有共同物理指纹格式的{summary['physical_group_comparable_strategies']}个不同策略形成{summary['physical_groups_complete_comparable']}组完整排程；缺少共同格式的历史单H不强行合并。这仅是本train21上的行为证据，不是普遍程序等价。详见Unique_strategy_ranking.csv和Champion_schedule_comparisons.csv。",'',
        '## 认证与证据边界','',
        f"Protocol SHA256：`{summary['protocol_sha256']}`；Plans SHA256：`{summary['plans_sha256']}`。原始目录`runs/{RUN.name}`保留两遍结果、评分、源身份、policy向量、PID、接收期限、exit0或已认证终止、失败进度和来源摘要。认证新增进程{len(processes)}个；{len(expected)}项冻结源／证据当前SHA匹配。",
        '历史缓存只复用已核验的完整质量，不追认其现代PID/exit0认证，不把旧T15失败作为新T30失败。跨轮是独立抽样搜索路径，不是独立物理计时重复。原H编号含训练排名，但采样不读取排名或完整成绩表；整个H集合与空间设计已有研发先验。',
        '领先只说明本离散静态空间中有限查询找到更好的训练策略；不证明传统方法最强、连续权重最优、完整静态空间最优或所有动态方法无价值。落后也不能证明动态控制贡献。train21结果不是独立泛化验证。','',
        '## 复现与交付','',
        '本次按照本会话明确授权创建真实Authorization.json。首次run写入6小时期限；不重置。现有终态不得重新prepare或为补表重跑。只读复核／报告命令：','',
        '```bash','PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/a4_static/run.py check',
        'PYTHONPATH=code:. .venv/bin/python -B tools/a4_static_campaign_analysis.py','```','',
        '完整轨迹：Certified_best_so_far.csv；逐实例：All_instances.csv；各轮完成情况：Champions.csv；不同策略排名：Unique_strategy_ranking.csv；失败：Failures.csv（若有）；实际启动：Actual_solve_starts.csv；进程认证：Process_certification.csv；结果来源及SHA：Certified_result_sources.json。原始run保持本地，Git保存协议、轨迹、派生表和来源证据。']
    (OUT/'FULL_REPORT_ZH.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:summary[k] for k in ('phase','certified_completed_queries','completed_repeats','campaign_best','API')},ensure_ascii=False))


if __name__=='__main__':
    main()
