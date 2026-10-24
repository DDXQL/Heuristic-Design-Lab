"""No retries, no unaccounted reservations; full historic comparison before continuation."""
from . import specs
from fjsp_usage.baseline_a.validation import validate_result


def compare_historical(identifier,result,historical):
    old={r['file']:r for r in historical['instances']}
    for row in result['instances']:
        if row['file'] not in old:continue
        source=old[row['file']]
        for key in ('makespan','lower_bound','score'):
            if row[key]!=source[key]:raise ValueError('historical scientific mismatch: '+identifier+'/'+row['file']+'/'+key)
        for key in ('physical_schedule_sha256','commit_sequence_sha256'):
            if key in source and row[key]!=source[key]:raise ValueError('historical fingerprint mismatch: '+identifier+'/'+row['file']+'/'+key)
        if identifier=='H0' and row['commit_sequence_sha256']!=source['deterministic_schedule_sha256']:
            raise ValueError('native single-H schedule hash mismatch')


def ledger(state,p,read,sha,directory):
    if state['protocol_sha256']!=sha(directory/'Protocol.json'):raise ValueError('ledger protocol mismatch')
    defined=[s['id'] for s in specs()];entries=state['strategies']
    if (state['phase'] not in ('prepared','running','completed') or
        (state['phase']=='completed' and len(entries)!=9) or (state['phase']=='prepared' and entries)):
        raise ValueError('phase/coverage mismatch')
    if list(entries)!=defined[:len(entries)]:raise ValueError('out-of-order/unknown ledger entries')
    used=0
    for id,row in entries.items():
        if row.get('status')!='completed':raise ValueError('unknown reservation; cannot automatically repeat')
        if (row.get('reserved_evaluations'),row.get('reserved_solve_passes'))!=(21,42):raise ValueError('budget mismatch')
        used+=21;path=directory/row['result_path']
        if not path.resolve().is_relative_to(directory.resolve()) or sha(path)!=row['result_sha256']:
            raise ValueError('result identity/path mismatch')
        result=read(path);validate_result(result,p['instances'],'modern')
        if result['valid']!=row['valid']:raise ValueError('ledger validity mismatch')
    if used>189 or used*2>378:raise ValueError('budget cap exceeded')
    return used
