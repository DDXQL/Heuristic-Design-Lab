"""Bounded h behavior samples, including compilation and deterministic recheck."""

from functools import lru_cache
import math
import multiprocessing as mp
import time

from fjsp_usage.research.candidates import compile_candidate

ACTION_SAMPLES = ((2., 5., 2, 0., 3., 3., 5.), (4., 4., 1, 5., 1., 5., 9.),
                  (1., 12., 4, 0., 0., 0., 1.))


class ReviewExecutionError(ValueError):
    pass


def _worker(pipe, candidate):
    try:
        function = compile_candidate(candidate)
        scores = []
        for values in ACTION_SAMPLES:
            first, second = function(*values), function(*values)
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (first, second)):
                raise ValueError('finite scalar required')
            if first != second:
                raise ValueError('deterministic samples required')
            scores.append(float(first))
        pipe.send({'scores': scores})
    except BaseException as exc:
        pipe.send({'error_type': type(exc).__name__})
    finally:
        pipe.close()


@lru_cache(maxsize=128)
def _checked_scores(candidate, timeout):
    # Cache only successful execution of the exact immutable code/key/deadline.
    # Review metadata and asset hashes are still checked on every load.
    context = mp.get_context('spawn')
    receive, send = context.Pipe(duplex=False)
    worker = context.Process(target=_worker, args=(send, candidate))
    started = time.monotonic()
    try:
        worker.start()
        send.close()
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0 or not receive.poll(remaining):
            raise ReviewExecutionError('H review samples timed out; no review or freeze recorded')
        try:
            result = receive.recv()
        except EOFError as exc:
            raise ReviewExecutionError('H review worker exited; no review or freeze recorded') from exc
        if 'error_type' in result:
            raise ReviewExecutionError('H review samples failed: ' + result['error_type'])
        return tuple(result['scores'])
    finally:
        receive.close()
        send.close()
        if worker.pid is not None:
            worker.join(timeout=.05)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=.5)
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=.5)
            worker.close()


def score_samples(candidate, *, timeout=3):
    if candidate.kind != 'h':
        raise ValueError('H review requires h, not U')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('finite positive H review deadline required')
    scores = _checked_scores(candidate, timeout)
    return [{'inputs': list(values), 'score': score}
            for values, score in zip(ACTION_SAMPLES, scores)]
