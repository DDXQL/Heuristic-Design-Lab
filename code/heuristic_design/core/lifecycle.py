"""30s to receive/deserialise a COMPLETE row, followed by separate exit grace.

A daemon reader may block in recv; the controller waits only to its monotonic
deadline, then certifies worker termination and joins the reader. A reader which
does not stop is UNKNOWN, never an ordinary timeout. This is stricter than the
old poll(15)/unbounded recv; frozen historical implementations remain unchanged.
"""
import signal
import threading
import time


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
