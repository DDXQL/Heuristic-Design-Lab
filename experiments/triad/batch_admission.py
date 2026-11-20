"""Short-lived API permits and pacing for independent searches in one batch."""

from contextlib import contextmanager
from email.utils import parsedate_to_datetime
import fcntl
import math
import multiprocessing
from pathlib import Path
import time

from heuristic_design.core.storage import digest, read, write


WIDTHS = (1, 2, 4, 8)


class AdmissionUnavailable(RuntimeError):
    """The local rate or concurrency constraints could not be enforced."""


@contextmanager
def try_lock(path):
    with path.open('a') as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True  # close releases the lock, including on process exit


def retry_after(value, now):
    if value is None:
        return 0
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - now
        except (ValueError, TypeError, OverflowError):
            return 0
    return seconds if math.isfinite(seconds) and seconds > 0 else 0


class Permits:
    def __init__(self, folder, width, wait, interval, rpm=None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.width, self.wait, self.interval, self.rpm = width, wait, interval, rpm

    @contextmanager
    def slot(self, deadline):
        while time.monotonic() < deadline:
            usable = 0
            for index in range(self.width):
                if (self.folder / f'permit-{index}.unresolved').exists():
                    continue
                usable += 1
                with try_lock(self.folder / f'permit-{index}.lock') as owned:
                    if owned and not (self.folder / f'permit-{index}.unresolved').exists():
                        yield index
                        return
            if not usable:
                raise AdmissionUnavailable('all API permits have unresolved local network workers')
            time.sleep(.025)
        raise TimeoutError('local API permit queue timeout')

    def pace(self, deadline, cooldown=None):
        while time.monotonic() < deadline:
            with try_lock(self.folder / 'pacing.lock') as owned:
                if owned:
                    path = self.folder / 'pacing.json'
                    clock = read(path) if path.exists() else {}
                    now = time.time()
                    starts = [t for t in clock.get('starts', []) if t > now - 60]
                    next_send = clock.get('next_send', 0)
                    until = clock.get('cooldown', 0)
                    if cooldown is not None:
                        write(path, {'starts': starts, 'next_send': next_send,
                                     'cooldown': max(until, now + cooldown)})
                        return
                    if now >= max(next_send, until) and (self.rpm is None or len(starts) < self.rpm):
                        write(path, {'starts': starts + [now] if self.rpm else [],
                                     'next_send': now + self.interval, 'cooldown': until})
                        return
            time.sleep(.025)
        if cooldown is not None:
            raise AdmissionUnavailable('could not publish provider cooldown')
        raise TimeoutError('local API pacing queue timeout')


class Transport:
    def __init__(self, inner, admission, policy):
        from .configuration import request_timeout

        self.inner = inner
        self.admission = admission
        self.policy = policy
        m = admission.m
        self.permits = Permits(admission.path.parent / 'api-pacing', m['global_API_width'],
                               m['queue_wait_seconds'], m['min_request_interval_seconds'],
                               m.get('requests_per_minute'))
        c = read(admission.row['config'])
        self.run_clock = Path(admission.row['run_dir']) / 'Run_clock.json'
        self.minimum_remaining = request_timeout(c) + c['instance_timeout_seconds'] * c['instance_count'] + 5
        self.identity = digest({'transport': inner.identity, 'batch': admission.b, 'mode': 'independent-v1'})

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def dispatch(self, key, prompt, *, kind, on_sent):
        deadline = time.monotonic() + self.permits.wait
        started = False
        sent = False
        children = {p.pid for p in multiprocessing.active_children()}

        def mark_sent():
            nonlocal sent
            sent = True
            on_sent()

        try:
            with self.permits.slot(deadline) as index:
                self.permits.pace(deadline)
                self.admission.verify()
                if time.time() + self.minimum_remaining >= read(self.run_clock)['deadline']:
                    raise TimeoutError('local batch window cannot cover dispatch and evaluation')
                started = True
                try:
                    result = self.inner.dispatch(key, prompt, kind=kind, on_sent=mark_sent)
                    if any(p.pid not in children for p in multiprocessing.active_children()):
                        raise AdmissionUnavailable('network worker still alive after response')
                    return result
                except Exception as exc:
                    meta = getattr(exc, 'metadata', {}) or {}
                    if any(p.pid not in children for p in multiprocessing.active_children()):
                        write(self.permits.folder / f'permit-{index}.unresolved',
                              {'attempt': key, 'reason': 'network worker not settled'})
                    if meta.get('http_status') == 429 or meta.get('upstream_http_status') == 429:
                        delay = max(self.policy['rate_limit_backoff_seconds'],
                                    retry_after(meta.get('retry_after'), time.time()))
                        try:
                            self.permits.pace(time.monotonic() + 10, cooldown=delay)
                        except Exception as error:
                            exc.metadata = {**meta, 'caller_hard_stop': True, 'cooldown_error': type(error).__name__}
                    raise
        except Exception as error:
            meta = getattr(error, 'metadata', {}) or {}
            if not started:
                meta.update(send_status='not_sent', failure_stage='batch_admission')
                if not isinstance(error, TimeoutError):
                    meta['caller_hard_stop'] = True
            elif sent:
                meta['send_status'] = 'confirmed'
            elif not meta.get('send_status'):
                meta['send_status'] = 'unknown'
            meta.update(independent_batch=True,
                        dispatch_children_settled=not any(p.pid not in children for p in multiprocessing.active_children()))
            error.metadata = meta
            raise
