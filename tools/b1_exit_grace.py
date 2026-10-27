"""Independent v2 cleanup adapter: 1s exit grace AFTER result collection.

No extra solve, no change to poll(15), fitness or required exitcode=0.
The original .05s protocol and its quarantined result remain unchanged.
"""
import time

def collect_with_exit_grace(context, target, candidate, members, instances, names,
                           timeout, allowed_modes, persist, clock=time.monotonic):
    """Same poll(15)/recv result deadline; allow 1s NORMAL EXIT cleanup after result.

    persist is a mandatory durable writer, called at start and at terminal exit.
    A remaining 'started' receipt is uncertain, never permission to repeat work.
    This does NOT extend result waiting, nor strengthen recv into a hard deadline.
    """
    receive, send = context.Pipe(duplex=False)
    worker = context.Process(target=target, args=(send, candidate, tuple(members),
        tuple(instances), tuple(names), allowed_modes))
    worker.start()
    send.close()
    receipt = {'status': 'started', 'pid': worker.pid, 'deadline_seconds': timeout,
               'started_monotonic': clock(), 'started_wall_unix': time.time(), 'exit_grace_seconds': 1.0, 'trigger': None, 'cleanup': []}
    rows, failure = [], None
    try:
        persist(dict(receipt))
        for name in names:
            started = clock()
            if not receive.poll(timeout):
                receipt['trigger'] = 'parent_poll_timeout'
                row = {'error_type': 'Timeout', 'error': 'whole-instance deadline exceeded'}
            else:
                try:
                    row = receive.recv()
                except EOFError:
                    receipt['trigger'] = 'pipe_eof'
                    row = {'error_type': 'WorkerExit', 'error': 'no final result'}
            if 'error' in row:
                failure = {**row, 'failed_instance': name,
                           'parent_observed_instance_seconds': clock()-started}
                break
            if row['file'] != name:
                raise ValueError('worker instance order mismatch')
            rows.append(row)
    finally:
        receive.close()
        worker.join(timeout=1.0)
        receipt['cleanup'].append('join_1.0')
        if worker.is_alive():
            worker.terminate()
            receipt['cleanup'].append('terminate')
            worker.join(timeout=.5)
        if worker.is_alive():
            worker.kill()
            receipt['cleanup'].append('kill')
            worker.join(timeout=.5)
        receipt.update(status='terminal', alive=worker.is_alive(), exitcode=worker.exitcode,
                       finished_monotonic=clock(), finished_wall_unix=time.time())
        # Failure to write terminal evidence propagates; no certified continuation.
        persist(receipt)
    return rows, failure, receipt

