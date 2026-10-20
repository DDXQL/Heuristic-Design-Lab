#!/usr/bin/env python3
"""Frozen two-U validation only; no search, model client or validation selection."""
from collections import Counter
import argparse
import math
from pathlib import Path
from statistics import NormalDist, fmean
import time

import numpy as np

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import check_result, checked_candidate
from fjsp_usage.research_real.locking import RunLock
from llm4ad.task.optimization.fjsp_set.instances import load_instance
from tools import h01_v1_prepare as prep


def check(directory):
    directory=Path(directory).resolve()
    if directory.parent != prep.ROOT/'runs':raise ValueError('registered runs directory required')
    protocol=prep.read(directory/'Protocol.json');identity=prep.sha(directory/'Protocol.json')
    if identity!=(directory/'Protocol.sha256').read_text().strip():raise ValueError('protocol hash changed')
    if (protocol['version']!=prep.VERSION or protocol['mode']!='real' or protocol['statistics']!=prep.STATISTICS
            or protocol['instance_timeout']!=15 or protocol['task_cap']!=56 or protocol['solve_pass_cap']!=112):
        raise ValueError('frozen V1 contract differs')
    for name,expected in {**protocol['B2_frozen_pins'],**protocol['pins']}.items():
        if prep.sha(prep.ROOT/name)!=expected:raise ValueError('frozen file changed: '+name)
    original_plan=prep.original.pins_check(prep.B2)
    if (protocol['source_B2_run']!=str(prep.B2) or protocol['source_B2_plan_sha256']!=prep.sha(prep.B2/'Plan.json')
            or protocol['B2_frozen_pins']!=original_plan['pins'] or protocol['H_order']!=original_plan['H_order']):
        raise ValueError('B2 source/provenance binding differs')
    manifest=prep.read(protocol['original_manifest'])
    if prep.sha(protocol['original_manifest'])!=protocol['manifest_sha256']:raise ValueError('manifest changed')
    if protocol['manifest_sha256']!=original_plan['dataset']['manifest_sha256']:
        raise ValueError('V1 must retain the original B2 data manifest')
    if [r['file'] for r in protocol['instances']]!=manifest['split']['test']:raise ValueError('full original test28 required')
    if len(protocol['instances'])!=28:raise ValueError('28 fixed instances required')
    expected_tasks=[{'id':f'{i:02d}_{role}','index':i,'role':role,'file':row['file']}
        for i,row in enumerate(protocol['instances']) for role in (('dynamic','equal') if i%2==0 else ('equal','dynamic'))]
    if protocol['tasks']!=expected_tasks:raise ValueError('fixed paired order changed')
    if set(protocol['candidates'])!={'dynamic','equal'}:raise ValueError('exactly two frozen programs')
    for role,(identifier,_,expected) in prep.PROGRAMS.items():
        row=protocol['candidates'][role];c=checked_candidate(row['candidate'],'U')
        path=directory/row['relative_path']
        if row['id']!=identifier or row['file_sha256']!=expected or prep.sha(path)!=expected or path.read_text()!=c.code:
            raise ValueError('frozen U identity differs')
    for row in protocol['instances']:
        path=(directory/row['relative_path']).resolve()
        if not path.is_relative_to(directory/'inputs/test') or prep.sha(path)!=row['sha256'] or row['sha256']!=manifest['files'][row['file']]['sha256']:
            raise ValueError('held-out file identity differs')
    h=prep.read(directory/protocol['H_file'])
    if prep.sha(directory/protocol['H_file'])!=protocol['H_file_sha256'] or [r['candidate']['key'] for r in h['members']]!=protocol['H_order']:
        raise ValueError('fixed H identity/order differs')
    prep.original.old.check_evaluation_runtime(protocol)
    return protocol,identity


def require_execution(directory):
    protocol,identity=check(directory)
    if protocol['gates']['history_blocks_execution'] or protocol['gates']['duplicate_blocks_execution']:
        raise ValueError('history/duplicate evidence blocks execution; no authorization override')
    path=directory/'V1_1_authorization.json'
    if not path.exists():raise ValueError('V1-1 not authorized; V1-0 cannot evaluate test28')
    auth=prep.read(path)
    expected={'stage':'V1-1','approved':True,'person':'DDXQL','protocol_sha256':identity,
        'no_known_unrecorded_test28_use':True,'accept_reserved_test28_consumption':True}
    if auth!=expected or any(auth[k] is not True for k in ('approved','no_known_unrecorded_test28_use','accept_reserved_test28_consumption')):
        raise ValueError('V1-1 scope/independence confirmation differs')
    return protocol,identity


def validate_result(result, instance):
    check_result(result,(instance['file'],))
    if not result['valid']:return
    row=result['instances'][0]
    if row.get('feasible') is not True or row['lower_bound']!=instance['LB']:
        raise ValueError('result feasibility/LB differs')
    if row.get('physical_schedule_sha256')!=row.get('recheck_physical_schedule_sha256') or not row.get('physical_schedule_sha256'):
        raise ValueError('missing/mismatched deterministic physical schedule')
    if digest(row.get('physical_schedule'))!=row['physical_schedule_sha256']:
        raise ValueError('physical schedule bytes/hash differ')
    if any(type(row.get(k)) not in (int,float) or not math.isfinite(row[k]) or row[k]<0
           for k in ('single_solve_seconds','deterministic_recheck_seconds')):
        raise ValueError('certified wall timing required')
    for k in ('single_h_calls','deterministic_recheck_h_calls'):
        values=row.get(k)
        if not isinstance(values,list) or len(values)!=10 or any(type(v) is not int or v<0 for v in values) or any(values[2:]):
            raise ValueError('missing/invalid certified H0/H1 call counts')
    if row['single_h_calls']!=row['deterministic_recheck_h_calls']:
        raise ValueError('deterministic h call counts differ')


class PairRun:
    """Single writer with existing CLI RunLock; not a concurrent task queue."""
    def __init__(self,directory,protocol,identity,verify):
        self.directory=Path(directory);self.protocol=protocol;self.identity=identity;self.verify=verify
        self.path=self.directory/'checkpoint.json'
        self.state={'identity':identity,'mode':protocol['mode'],'tasks':{},'phase':'not_started'}
        if self.path.exists():self.state=prep.read(self.path)
        elif list((self.directory/'results').glob('*.json')):raise ValueError('orphan results without checkpoint; do not reset')
        if self.state['identity']!=identity or self.state['mode']!=protocol['mode']:raise ValueError('checkpoint belongs to another protocol/mode')
        allowed={t['id'] for t in protocol['tasks']}
        if len(allowed)!=len(protocol['tasks']) or len(allowed)!=protocol['task_cap']:
            raise ValueError('task list must have unique fixed IDs and exact cap')
        if not set(self.state['tasks'])<=allowed or len(self.state['tasks'])>protocol['task_cap']:raise ValueError('corrupt task cap/identity')
        if any(p.stem not in allowed for p in (self.directory/'results').glob('*.json')):raise ValueError('orphan result identity')

    def save(self):atomic_json(self.path,self.state)

    def result(self,task):
        path=self.directory/'results'/(task['id']+'.json')
        record=prep.read(path)
        if record['identity']!=self.identity or record['mode']!=self.protocol['mode'] or record['task']!=task:
            raise ValueError('task result identity differs')
        validate_result(record['result'],self.protocol['instances'][task['index']])
        return record

    def run(self,evaluator):
        for task in self.protocol['tasks']:
            self.verify()
            state=self.state['tasks'].get(task['id']);path=self.directory/'results'/(task['id']+'.json')
            if state and state['status'] in ('completed','interrupted'):
                if prep.sha(path)!=state['result_sha256']:raise ValueError('saved result changed')
                self.result(task);continue
            if state:
                if state['status']!='reserved':raise ValueError('unknown task state')
                if path.exists():record=self.result(task)  # Complete result persisted before checkpoint commit.
                else:
                    record={'identity':self.identity,'mode':self.protocol['mode'],'task':task,
                        'result':{'valid':False,'fitness':None,'instances':[],'total_instances':1,
                            'failed_instance':task['file'],'error_type':'InterruptedEvaluation',
                            'error':'reserved evaluation state unknown; never repeat','primary_evaluation_seconds':None}}
                    atomic_json(path,record)
                state.update(status='interrupted' if record['result'].get('error_type')=='InterruptedEvaluation' else 'completed',result_sha256=prep.sha(path))
                self.save();continue
            if path.exists():raise ValueError('unreserved result; no silent cache adoption')
            self.state['phase']='running'
            self.state['tasks'][task['id']]={'status':'reserved','reserved_at_unix':time.time()}
            self.save()  # Reservation is never refunded after a crash.
            result=evaluator(task)
            validate_result(result,self.protocol['instances'][task['index']])
            record={'identity':self.identity,'mode':self.protocol['mode'],'task':task,'result':result}
            atomic_json(path,record)
            self.state['tasks'][task['id']].update(status='completed',result_sha256=prep.sha(path),finished_at_unix=time.time())
            self.save()
        self.state['phase']='completed';self.save()
        return self.state


def paired_statistics(differences):
    """BCa specialized to the paired MEAN; no SciPy dependency or method fallback.

    Efron BCa: midrank bias z0, leave-one-pair-out acceleration, NumPy linear
    quantiles. Resampling differences is identical to resampling aligned pairs.
    """
    d=np.asarray(differences,dtype=float)
    if d.ndim!=1 or len(d)<2 or not np.all(np.isfinite(d)):raise ValueError('finite complete pairs required')
    estimate=float(np.mean(d));wins=int(np.sum(d>0));losses=int(np.sum(d<0));nonzero=wins+losses
    sign_p=min(1.,2*sum(math.comb(nonzero,k) for k in range(min(wins,losses)+1))/2**nonzero) if nonzero else None
    result={'n':len(d),'delta_fitness':estimate,'wins':wins,'losses':losses,'ties':len(d)-nonzero,
        'sign_test_p_two_sided':sign_p,'sign_test_status':'ok' if nonzero else 'all_ties_no_binomial_trials',
        'BCa_95_CI':None,'BCa_status':None,'statistics_policy':prep.STATISTICS}
    try:
        jack=(np.sum(d)-d)/(len(d)-1);delta=np.mean(jack)-jack;ss=float(np.sum(delta**2))
        if ss==0:raise ArithmeticError('degenerate_jackknife')
        acceleration=float(np.sum(delta**3))/(6*ss**1.5)
        rng=np.random.default_rng(prep.STATISTICS['seed'])
        boot=np.mean(d[rng.integers(0,len(d),size=(prep.STATISTICS['resamples'],len(d)))],axis=1)
        percentile=float((np.sum(boot<estimate)+np.sum(boot<=estimate))/(2*len(boot)))
        if not 0<percentile<1:raise ArithmeticError('degenerate_bias_probability')
        normal=NormalDist();z0=normal.inv_cdf(percentile);probabilities=[]
        for q in (.025,.975):
            z=normal.inv_cdf(q);denominator=1-acceleration*(z0+z)
            if denominator<=0:raise ArithmeticError('BCa_transform_singular')
            probabilities.append(normal.cdf(z0+(z0+z)/denominator))
        if not 0<=probabilities[0]<=probabilities[1]<=1:raise ArithmeticError('BCa_quantile_order')
        interval=np.quantile(boot,probabilities,method='linear')
        if not np.all(np.isfinite(interval)):raise ArithmeticError('nonfinite_CI')
        result.update(BCa_95_CI=interval.tolist(),BCa_status='ok',acceleration=acceleration,bias_z0=z0)
    except Exception as exc:
        result['BCa_status']='undefined:'+type(exc).__name__+':'+str(exc)[:200]
    return result


def report(directory,protocol,identity):
    """Saved task records only; never calls an evaluator or selects a winner."""
    run=PairRun(directory,protocol,identity,lambda:None);rows=[];differences=[];scores={r:[] for r in ('dynamic','equal')}
    for index,instance in enumerate(protocol['instances']):
        row={'file':instance['file'],'sha256':instance['sha256'],'LB':instance['LB']}
        for role in ('dynamic','equal'):
            task=next(t for t in protocol['tasks'] if t['index']==index and t['role']==role)
            saved=run.state['tasks'].get(task['id'])
            result=None
            if saved and saved['status'] in ('completed','interrupted'):
                path=Path(directory)/'results'/(task['id']+'.json')
                if prep.sha(path)!=saved['result_sha256']:raise ValueError('saved result changed')
                result=run.result(task)['result']
            valid=result is not None and result['valid'];r=result['instances'][0] if valid else {}
            row.update({role+'_valid':valid,role+'_status':saved['status'] if saved else 'not_started',
                role+'_Cmax':r.get('makespan'),role+'_Cmax_over_LB':-r['score'] if valid else None,
                role+'_single_wall_seconds':r.get('single_solve_seconds'),role+'_recheck_wall_seconds':r.get('deterministic_recheck_seconds'),
                role+'_evaluation_wall_seconds':result.get('primary_evaluation_seconds') if result else None,
                role+'_recheck_consistent':True if valid else None,
                role+'_h_calls':sum(r['single_h_calls']) if valid else None,
                role+'_recheck_h_calls':sum(r['deterministic_recheck_h_calls']) if valid else None,
                role+'_physical_schedule_sha256':r.get('physical_schedule_sha256'),
                role+'_error_type':result.get('error_type') if result else None})
            if valid:scores[role].append(r['score'])
        delta=(row['equal_Cmax']-row['dynamic_Cmax'])/instance['LB'] if row['dynamic_valid'] and row['equal_valid'] else None
        row.update(delta_fitness=delta,outcome='win' if delta is not None and delta>0 else 'loss' if delta is not None and delta<0 else 'tie' if delta==0 else 'unknown')
        if delta is not None:differences.append(delta)
        rows.append(row)
    complete=len(differences)==len(protocol['instances'])
    summary={'version':protocol['version'],'identity':identity,'mode':protocol['mode'],'phase':run.state['phase'],
        'reserved_evaluations':len(run.state['tasks']),'planned_evaluations':len(protocol['tasks']),
        'fitness':{r:fmean(values) if len(values)==len(protocol['instances']) else None for r,values in scores.items()},
        'Cmax_sum':{r:sum(row[r+'_Cmax'] for row in rows) if len(scores[r])==len(rows) else None for r in scores},
        'pair_outcomes':dict(Counter(row['outcome'] for row in rows)),
        'certified_costs':{role:{
            'single_wall_seconds':sum(row[role+'_single_wall_seconds'] for row in rows if row[role+'_valid']),
            'recheck_wall_seconds':sum(row[role+'_recheck_wall_seconds'] for row in rows if row[role+'_valid']),
            'h_calls':sum(row[role+'_h_calls'] for row in rows if row[role+'_valid']),
            'recheck_h_calls':sum(row[role+'_recheck_h_calls'] for row in rows if row[role+'_valid']),
            'unknown_or_failed_instances':sum(not row[role+'_valid'] for row in rows),
            'scope':'certified successful pairs only; failed scoring costs unknown, never zero-filled'} for role in scores},
        'statistics':paired_statistics(differences) if complete else {'status':'not_computable_incomplete_pairs','delta_fitness':None,'BCa_95_CI':None,'sign_test_p_two_sided':None},
        'complete_case_primary_forbidden':True,'CPU_seconds':None,'API_requests':0,
        'notice':'finite benchmark paired comparison; no candidate selection, extra solves or general population guarantee'}
    prep.csv_table(Path(directory)/'Paired_results.csv',rows)
    atomic_json(Path(directory)/'V1_report.json',summary)
    return summary


def real_run(directory):
    protocol,identity=require_execution(directory)  # Explicit new authorization before loading test data.
    _,_,members=prep.original.check(prep.B2)  # Existing H legality/provenance, no supplier client.
    programs={role:checked_candidate(row['candidate'],'U') for role,row in protocol['candidates'].items()}
    def evaluate(task):
        instance=protocol['instances'][task['index']];path=directory/instance['relative_path']
        if prep.sha(path)!=instance['sha256']:raise ValueError('instance changed before load')
        loaded=load_instance(path)
        if prep.sha(path)!=instance['sha256']:raise ValueError('instance changed during load')
        return prep.original.old.evaluate_weight(programs[task['role']],members,(loaded,),(instance['file'],))
    return PairRun(directory,protocol,identity,lambda:require_execution(directory)).run(evaluate)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('prepare','check','run','report'))
    parser.add_argument('--run-dir',type=Path,default=prep.DEFAULT)
    args=parser.parse_args();directory=args.run_dir.resolve()
    if args.stage=='prepare':prep.prepare(directory)
    elif args.stage=='run':
        require_execution(directory)
        with RunLock(directory):real_run(directory)
    elif args.stage=='report':
        protocol,identity=check(directory)
        with RunLock(directory):summary=report(directory,protocol,identity)
        print(summary['phase'])
    else:
        protocol,identity=check(directory)
        print({'protocol_sha256':identity,'V1_1_authorization_present':(directory/'V1_1_authorization.json').exists(),
            'history_gate':protocol['gates']['history_blocks_execution'],'duplicate_gate':protocol['gates']['duplicate_blocks_execution'],
            'formal_evaluations_started':(directory/'checkpoint.json').exists()})


if __name__=='__main__':main()
