"""Offline-accepted building block for a NEW recovery protocol; NOT installed.

No CLI, API, data loading or scheduler changes. The existing frozen collector and
Recovery-B entry remain untouched. A future adapter must persist every receipt,
verify the full frozen manifest before/after, and bind the expected child identity.
"""
import signal
import time

from fjsp_usage.research.protocol import digest


def collect_with_lifecycle(context, target, candidate, members, instances, names,
                           timeout, allowed_modes, persist, clock=time.monotonic):
    """Same poll/recv and cleanup deadlines as runtime._collect; add evidence.

    persist is a mandatory durable writer, called at start and at terminal exit.
    A remaining 'started' receipt is uncertain, never permission to repeat work.
    This does NOT strengthen poll(timeout) into a hard deadline on recv().
    """
    receive, send = context.Pipe(duplex=False)
    worker = context.Process(target=target, args=(send, candidate, tuple(members),
        tuple(instances), tuple(names), allowed_modes))
    worker.start()
    send.close()
    receipt = {'status': 'started', 'pid': worker.pid, 'deadline_seconds': timeout,
               'started_monotonic': clock(), 'trigger': None, 'cleanup': []}
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
        worker.join(timeout=.05)
        receipt['cleanup'].append('join_0.05')
        if worker.is_alive():
            worker.terminate()
            receipt['cleanup'].append('terminate')
            worker.join(timeout=.5)
        if worker.is_alive():
            worker.kill()
            receipt['cleanup'].append('kill')
            worker.join(timeout=.5)
        receipt.update(status='terminal', alive=worker.is_alive(), exitcode=worker.exitcode,
                       finished_monotonic=clock())
        # Failure to write terminal evidence propagates; no certified continuation.
        persist(receipt)
    return rows, failure, receipt


def classify_boundary(result, *, before, after, lifecycle, expected_identity,
                      expected_files, start_files, end_files, worker_failure=False):
    """Fail closed; timeout acceptance certifies INVALIDITY, never prefix quality.

    expected_identity is a protocol-bound loaded-code identity. File maps must
    cover the ENTIRE frozen set, including the independent ablation tool. This
    function cannot itself collect or retroactively reconstruct that evidence.
    """
    def stop(reason):
        return {'decision': 'stop', 'reason': reason, 'fitness': None}

    if not expected_files or start_files != expected_files or end_files != expected_files:
        return stop('frozen_source_boundary_not_certified')
    def valid(witness):
        return (isinstance(witness, dict) and bool(witness.get('modules'))
                and witness.get('identity') == digest(witness['modules']) == expected_identity)
    if not valid(before) or worker_failure:
        return stop('child_start_identity_or_worker_failure')
    if after is not None and (not valid(after) or after.get('pid') != before.get('pid')):
        return stop('child_end_identity_mismatch')
    if (not lifecycle or lifecycle.get('status') != 'terminal'
            or lifecycle.get('alive') is not False or type(lifecycle.get('exitcode')) is not int
            or lifecycle.get('pid') != before.get('pid')):
        return stop('termination_unknown')
    if result.get('error_type') == 'Timeout':
        if (result.get('valid') is not False or result.get('fitness') is not None
                or result.get('error') != 'whole-instance deadline exceeded'
                or lifecycle.get('trigger') != 'parent_poll_timeout'
                or lifecycle.get('deadline_seconds') != 15
                or not result.get('failed_instance')
                or not any(x in lifecycle.get('cleanup', []) for x in ('terminate', 'kill'))
                or lifecycle['exitcode'] not in (-signal.SIGTERM, -signal.SIGKILL)):
            return stop('timeout_not_confirmed_terminated')
        return {'decision': 'candidate_invalid_continue', 'reason': 'confirmed_timeout_termination',
                'fitness': None, 'prefix_quality_accepted': False,
                'end_loaded_identity': 'matched' if after is not None else 'unavailable_for_terminated_worker'}
    if after is None:
        return stop('normal_or_unknown_exit_requires_end_identity')
    if lifecycle['exitcode'] != 0:
        return stop('unexpected_worker_exit')
    if result.get('error_type') == 'WorkerExit':
        return stop('pipe_eof_not_a_confirmed_timeout')
    return {'decision': 'original_result_checks_required', 'fitness': result.get('fitness')}
