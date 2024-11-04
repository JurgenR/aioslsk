import asyncio
from collections.abc import Callable, Coroutine
import logging
from typing import Any, Optional, Union


logger = logging.getLogger(__name__)


Interval = Union[float, Callable[[], float]]
TaskCoroutine = Union[
    Callable[[], Coroutine[None, None, Optional[float]]],
    Callable[[Any], Coroutine[None, None, Optional[float]]]
]


class BackgroundTask:
    """Wrapper class for a background task

    :ivar interval: interval at which the task should run
    :ivar task_coro: coroutine function that should be run at the provided
        interval
    :ivar preempt_wait: whether to perform an initial wait before running the
        coroutine for the first time
    :ivar name: optional task name
    :ivar context: optional context to pass to the coroutine
    """

    def __init__(
            self, interval: Interval, task_coro: TaskCoroutine,
            preempt_wait: bool = False, name: str = 'background-task',
            context: Optional[Any] = None):

        self.interval: Interval = interval
        self.preempt_wait: bool = preempt_wait
        self.task_coro: TaskCoroutine = task_coro
        self.name: str = name
        self.context: Optional[Any] = context
        self._task: Optional[asyncio.Task] = None

    def resolve_interval(self) -> float:
        if callable(self.interval):
            return self.interval()

        return self.interval

    def start(self):
        if not self._task:
            logger.info("starting task : %s", self.name)
            self._task = asyncio.create_task(self.runner(), name=self.name)

    def cancel(self) -> Optional[asyncio.Task]:
        if not self._task:
            return None

        logger.info("cancelling task : %s", self.name)
        task = self._task
        self._task = None
        task.cancel()
        return task

    def is_running(self) -> bool:
        return bool(self._task)

    async def runner(self):
        if self.preempt_wait:
            await asyncio.sleep(self.resolve_interval())

        while True:
            coro = self.task_coro(self.context) if self.context else self.task_coro()  # type: ignore[call-arg]
            job_ival = await coro

            next_ival = self.resolve_interval() if job_ival is None else job_ival

            await asyncio.sleep(next_ival)


class Timer:
    """Re-schedulable timer which runs a callback after completion"""

    def __init__(self, timeout: float, callback: TaskCoroutine):
        self.timeout: float = timeout
        self.callback: TaskCoroutine = callback
        self._task: Optional[asyncio.Task] = None

    def start(self):
        self._task = asyncio.create_task(self.runner())
        self._task.add_done_callback(self._unset_task)

    def cancel(self) -> Optional[asyncio.Task]:
        if self._task is None:
            return None

        task = self._task
        self._task.cancel()
        self._task = None
        return task

    async def runner(self):
        await asyncio.sleep(self.timeout)
        await self.callback()  # type: ignore[call-arg]

    def reschedule(self, timeout: Optional[float] = None):
        self.timeout = self.timeout if timeout is None else timeout

        self.cancel()
        self.start()

    def _unset_task(self, task: asyncio.Future):
        self._task = None
