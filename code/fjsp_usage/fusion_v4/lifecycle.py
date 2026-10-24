"""Post-result exit grace; same original 15s per-instance result wait.

Only after ALL expected rows are received may normal interpreter shutdown take
up to 2s. No new result or solve is accepted during that grace. Timeout/error
cleanup retains the old 0.05s join + terminate/kill. Exit0 and end identity remain
mandatory for successful evaluation. Original records/collector are untouched.
"""
import time
from tools.b1_timeout_boundary import classify_boundary as original_classify

EXIT_GRACE_SECONDS = 2.0
RESULT_WAIT_SECONDS = 15


def collect(context,target,candidate,members,instances,names,timeout,allowed_modes,persist,clock=time.monotonic):
    if timeout!=RESULT_WAIT_SECONDS or not names:
        raise ValueError('unchanged15s result wait and nonempty names required')
    receive,send=context.Pipe(duplex=False)
    worker=context.Process(target=target,args=(send,candidate,tuple(members),tuple(instances),tuple(names),allowed_modes))
    worker.start();send.close()
    receipt={'status':'started','pid':worker.pid,'deadline_seconds':15,'started_monotonic':clock(),
        'trigger':None,'cleanup':[],'expected_rows':len(names),'rows_received':0,
        'all_results_received':False,'exit_grace_seconds':EXIT_GRACE_SECONDS,
        'exit_grace_used':False,'results_complete_monotonic':None}
    rows=[];failure=None
    try:
        persist(dict(receipt))
        for name in names:
            started=clock()
            if not receive.poll(15):
                receipt['trigger']='parent_poll_timeout'
                row={'error_type':'Timeout','error':'whole-instance deadline exceeded'}
            else:
                try:row=receive.recv()
                except EOFError:
                    receipt['trigger']='pipe_eof';row={'error_type':'WorkerExit','error':'no final result'}
            if 'error' in row:
                failure={**row,'failed_instance':name,'parent_observed_instance_seconds':clock()-started}
                break
            if row['file']!=name:raise ValueError('worker instance order mismatch')
            rows.append(row);receipt['rows_received']=len(rows)
        receipt['all_results_received']=len(rows)==len(names) and failure is None
        if receipt['all_results_received']:
            receipt['results_complete_monotonic']=clock()
    finally:
        receive.close()
        # This phase cannot extend acceptance of an outstanding instance result.
        normal=receipt['all_results_received']
        grace=EXIT_GRACE_SECONDS if normal else .05
        receipt['exit_grace_used']=normal
        started=clock();worker.join(timeout=grace)
        receipt['exit_wait_observed_seconds']=clock()-started
        receipt['cleanup'].append('join_exit_grace_2.0' if normal else 'join_0.05')
        if worker.is_alive():
            worker.terminate();receipt['cleanup'].append('terminate');worker.join(timeout=.5)
        if worker.is_alive():
            worker.kill();receipt['cleanup'].append('kill');worker.join(timeout=.5)
        receipt.update(status='terminal',alive=worker.is_alive(),exitcode=worker.exitcode,finished_monotonic=clock())
        persist(receipt)
    return rows,failure,receipt


def classify(result,*,before,after,lifecycle,expected_identity,expected_files,start_files,end_files,worker_failure=False):
    # All old source/identity/PID/exit/timeout requirements remain authoritative.
    decision=original_classify(result,before=before,after=after,lifecycle=lifecycle,
        expected_identity=expected_identity,expected_files=expected_files,
        start_files=start_files,end_files=end_files,worker_failure=worker_failure)
    if decision['decision']=='stop':return decision
    def stop(reason):return {'decision':'stop','reason':reason,'fitness':None}
    if (lifecycle.get('deadline_seconds')!=15 or lifecycle.get('exit_grace_seconds')!=2.0
            or type(lifecycle.get('expected_rows')) is not int or lifecycle['expected_rows']<1):
        return stop('new_lifecycle_receipt_contract_missing')
    if result.get('valid') is True:
        if (lifecycle.get('trigger') is not None or lifecycle.get('all_results_received') is not True
                or lifecycle.get('exit_grace_used') is not True
                or lifecycle.get('rows_received')!=lifecycle['expected_rows']
                or len(result.get('instances',[]))!=lifecycle['expected_rows']
                or lifecycle.get('results_complete_monotonic') is None
                or lifecycle.get('cleanup')!=['join_exit_grace_2.0']):
            return stop('normal_exit_grace_or_complete_rows_not_certified')
    elif result.get('error_type')=='Timeout':
        if lifecycle.get('exit_grace_used') is not False or lifecycle.get('all_results_received') is not False:
            return stop('result_timeout_cannot_use_normal_exit_grace')
    return decision
