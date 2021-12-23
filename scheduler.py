from collections import namedtuple
from dataclasses import dataclass, field
import threading
import time
from typing import Any, Callable, List, Dict


@dataclass
class Job:
    interval: int
    callback: Callable
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JobMeta:
    job: Job
    last_called: float = 0.0
    times_called: int = 0


class Scheduler(threading.Thread):

    _INTERVAL = 0.5

    def __init__(self, stop_event):
        super().__init__()
        self.stop_event = stop_event
        self._lock = threading.Lock()

        self._jobs = []

    def add(self, interval, callback, args=None, kwargs=None):
        job = Job(interval, callback, args, kwargs)
        self.add_job(job)
        return job

    def add_job(self, job):
        job_meta = JobMeta(job)
        with self._lock:
            self._jobs.append(job_meta)

    def remove(self, job):
        with self._lock:
            for job_meta in self._jobs:
                if job_meta.job == job:
                    self._jobs.remove(job_meta)
                    break

    def run(self):
        while not self.stop_event.is_set():
            with self._lock:
                for job_meta in self._jobs:
                    current_time = time.time()
                    if job_meta.last_called == 0.0:
                        job_meta.last_called = time.time()
                    else:
                        if current_time >= job_meta.last_called + job_meta.job.interval:
                            job_meta.times_called += 1
                            job_meta.last_called = current_time
                            self._run_job(job_meta.job)
            time.sleep(self._INTERVAL)

    def _run_job(self, job):
        try:
            job.callback(*job.args, **job.kwargs)
        except Exception:
            logger.exception(f"exception while running job : {job!r}")
