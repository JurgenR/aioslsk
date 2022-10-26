from dataclasses import dataclass, field
import logging
import time
from typing import Any, Callable, List, Dict

logger = logging.getLogger(__name__)


@dataclass
class Job:
    interval: int
    """Interval on which to run the job in seconds"""
    callback: Callable
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    times: int = None
    """Amount of times to run the job, if C{None} run indefinitly"""


@dataclass
class JobMeta:
    job: Job
    last_called: float = field(default_factory=time.monotonic)
    times_called: int = 0


class Scheduler:
    """Class for scheduling events to run at intervals"""

    _INTERVAL = 0.25

    def __init__(self):
        super().__init__()

        self._jobs: List[JobMeta] = []

    def add(self, interval: int, callback: Callable, args=None, kwargs=None, times: int = None):
        args = [] if args is None else args
        kwargs = {} if kwargs is None else kwargs
        job = Job(interval, callback, args, kwargs, times)
        self.add_job(job)
        return job

    def add_job(self, job: Job):
        job_meta = JobMeta(job)
        self._jobs.append(job_meta)

    def remove(self, job: Job):
        for job_meta in self._jobs:
            if job_meta.job == job:
                self._jobs.remove(job_meta)
                break

    def loop(self):
        current_time = time.monotonic()
        for job_meta in self._jobs:
            # Check if the time has come to run the job and run it
            if current_time >= job_meta.last_called + job_meta.job.interval:
                job_meta.times_called += 1
                job_meta.last_called = current_time
                self._run_job(job_meta.job)

            # Remove the job from the list of jobs in case the 'times'
            # attribute is set on the job
            if job_meta.job.times is None:
                continue
            if job_meta.times_called >= job_meta.job.times:
                self.remove(job_meta.job)

    def exit(self):
        self._jobs = []

    def _run_job(self, job):
        try:
            job.callback(*job.args, **job.kwargs)
        except Exception:
            logger.exception(f"exception while running job : {job!r}")
