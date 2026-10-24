"""30s to receive/deserialise a COMPLETE row, followed by separate exit grace.

A daemon reader may block in recv; the controller waits only to its monotonic
deadline, then certifies worker termination and joins the reader. A reader which
does not stop is UNKNOWN, never an ordinary timeout. This is stricter than the
old poll(15)/unbounded recv; frozen historical implementations remain unchanged.
"""
import signal
import threading
import time
from fjsp_usage.research.protocol import digest

WAIT = 30
GRACE = 2.0


def receive_complete(connection, timeout, clock=time.monotonic):
    started = clock()
    box = {'started':started, 'deadline':started+timeout}
    def read():
        try:
            box['row'] = connection.recv()
        except BaseException as exc:
            box['error_type'] = type(exc).__name__
            box['error'] = str(exc)[:500]
        finally:
            box['finished'] = clock()
    reader = threading.Thread(target=read, daemon=True, name='T30-complete-result-reader')
    reader.start()
    reader.join(max(0.,box['deadline']-clock()))
    timely = not reader.is_alive() and box.get('finished',float('inf')) <= box['deadline']
    return box, reader, timely


def collect(context,target,payload,members,instances,names,timeout,allowed_modes,persist,
            clock=time.monotonic,wait_fn=receive_complete):
    if timeout!=WAIT or not names:
        raise ValueError('fixed T30/nonempty instance list required')
    receive,send=context.Pipe(duplex=False)
    worker=context.Process(target=target,args=(send,payload,tuple(members),tuple(instances),tuple(names),allowed_modes))
    worker.start();send.close()
    receipt={'status':'started','pid':worker.pid,'deadline_seconds':WAIT,'started_monotonic':clock(),
        'deadline_scope':'complete_recv_including_deserialisation','trigger':None,'cleanup':[],
        'expected_rows':len(names),'rows_received':0,'all_results_received':False,
        'exit_grace_seconds':GRACE,'exit_grace_used':False,'results_complete_monotonic':None,
        'receiver_thread_stopped':None,'instance_receives':[]}
    rows=[];failure=None;reader=None
    try:
        persist(dict(receipt))
        for name in names:
            box,reader,timely=wait_fn(receive,WAIT,clock)
            receipt['instance_receives'].append({'file':name,'started':box['started'],
                'deadline':box['deadline'],'finished':box.get('finished'),'timely':timely})
            if not timely:
                receipt['trigger']='parent_complete_result_timeout'
                row={'error_type':'Timeout','error':'complete-instance result deadline exceeded'}
            elif 'row' not in box:
                receipt['trigger']='pipe_receive_error'
                row={'error_type':'WorkerExit','error':'no complete result: '+box.get('error_type','unknown')}
            else:
                row=box['row']
            if not isinstance(row,dict):raise ValueError('non-dict worker result')
            if 'error' in row:
                failure={**row,'failed_instance':name,'parent_observed_instance_seconds':clock()-box['started']}
                break
            if row['file']!=name:raise ValueError('worker instance order mismatch')
            rows.append(row);receipt['rows_received']=len(rows)
        receipt['all_results_received']=failure is None and len(rows)==len(names)
        if receipt['all_results_received']:receipt['results_complete_monotonic']=clock()
    finally:
        normal=receipt['all_results_received'];receipt['exit_grace_used']=normal
        started=clock();worker.join(timeout=GRACE if normal else .05)
        receipt['exit_wait_observed_seconds']=clock()-started
        receipt['cleanup'].append('join_exit_grace_2.0' if normal else 'join_0.05')
        if worker.is_alive():
            worker.terminate();receipt['cleanup'].append('terminate');worker.join(timeout=.5)
        if worker.is_alive():
            worker.kill();receipt['cleanup'].append('kill');worker.join(timeout=.5)
        if reader is not None:reader.join(timeout=.5)
        receipt['receiver_thread_stopped']=reader is None or not reader.is_alive()
        receive.close()
        receipt.update(status='terminal',alive=worker.is_alive(),exitcode=worker.exitcode,finished_monotonic=clock())
        persist(receipt)
    return rows,failure,receipt


def classify(result,*,before,after,lifecycle,expected_identity,expected_files,start_files,end_files,worker_failure=False):
    def stop(reason):return {'decision':'stop','reason':reason,'fitness':None}
    if not expected_files or start_files!=expected_files or end_files!=expected_files:
        return stop('frozen_source_boundary_not_certified')
    def valid(w):
        return (isinstance(w,dict) and bool(w.get('modules'))
                and w.get('identity')==digest(w['modules'])==expected_identity)
    if not valid(before) or worker_failure:return stop('child_start_identity_or_worker_failure')
    if after is not None and (not valid(after) or after.get('pid')!=before.get('pid')):
        return stop('child_end_identity_mismatch')
    l=lifecycle
    if (not l or l.get('status')!='terminal' or l.get('alive') is not False
        or type(l.get('exitcode')) is not int or l.get('pid')!=before.get('pid')
        or l.get('receiver_thread_stopped') is not True):return stop('termination_or_receiver_unknown')
    if (l.get('deadline_seconds')!=WAIT or l.get('deadline_scope')!='complete_recv_including_deserialisation'
        or l.get('exit_grace_seconds')!=GRACE or type(l.get('expected_rows')) is not int
        or l['expected_rows']<1 or l.get('rows_received')!=len(result.get('instances',[]))):
        return stop('T30_receipt_contract_missing')
    if result.get('error_type')=='Timeout':
        if (result.get('valid') is not False or result.get('fitness') is not None
            or result.get('error')!='complete-instance result deadline exceeded'
            or not result.get('failed_instance') or l.get('trigger')!='parent_complete_result_timeout'
            or l.get('exit_grace_used') is not False or l.get('all_results_received') is not False
            or l['exitcode'] not in (-signal.SIGTERM,-signal.SIGKILL)
            or not any(x in l['cleanup'] for x in ('terminate','kill'))):
            return stop('timeout_not_confirmed_terminated')
        return {'decision':'candidate_invalid_continue','reason':'confirmed_T30_timeout_termination',
                'fitness':None,'prefix_quality_accepted':False,'end_loaded_identity':'matched' if after else 'unavailable_for_terminated_worker'}
    if not result.get('valid') or after is None or l['exitcode']!=0:
        return stop('normal_exit_complete_result_and_end_identity_required')
    if (l.get('trigger') is not None or l.get('all_results_received') is not True
        or l.get('exit_grace_used') is not True or l['rows_received']!=l['expected_rows']
        or l.get('results_complete_monotonic') is None or l['cleanup']!=['join_exit_grace_2.0']
        or len(l.get('instance_receives',[]))!=l['expected_rows']
        or any(not x['timely'] or x['finished'] is None or x['finished']>x['deadline'] for x in l['instance_receives'])):
        return stop('late_or_incomplete_normal_result')
    return {'decision':'accepted','reason':'complete_T30_identity_exit0','fitness':result['fitness']}
