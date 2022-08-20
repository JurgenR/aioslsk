from unittest.mock import MagicMock, Mock, patch

from pyslsk.scheduler import Job, Scheduler


def happy_callback():
    pass


class TestScheduler:

    def test_whenAddJob_shouldAddJob(self):
        scheduler = Scheduler()
        return_val = scheduler.add(
            interval=10,
            callback=happy_callback,
            times=5,
            args=[1],
            kwargs={'k': 'v'}
        )
        expected = Job(
            interval=10,
            callback=happy_callback,
            times=5,
            args=[1],
            kwargs={'k': 'v'}
        )
        assert len(scheduler._jobs) == 1
        job_meta = scheduler._jobs[0]
        assert expected == job_meta.job
        assert return_val is not None

    def test_whenAddJobObject_shouldAddJobObject(self):
        scheduler = Scheduler()
        job = Job(
            interval=10,
            callback=happy_callback,
            times=5,
            args=[1],
            kwargs={'k': 'v'}
        )
        scheduler.add_job(job)
        assert len(scheduler._jobs) == 1
        job_meta = scheduler._jobs[0]
        assert job == job_meta.job

    def test_whenRemoveJobObject_shouldRemoveJobObject(self):
        scheduler = Scheduler()
        job = Job(
            interval=10,
            callback=happy_callback
        )
        scheduler.add_job(job)
        scheduler.remove(job)
        assert len(scheduler._jobs) == 0

    def test_whenCallExit_shouldClearJobs(self):
        scheduler = Scheduler()
        scheduler.add(interval=10, callback=happy_callback)

        scheduler.exit()
        assert len(scheduler._jobs) == 0


class TestSchedulerLoop:
    INIT_TIME = 1.0

    def _setup(self, times=None):
        callback = MagicMock()
        scheduler = Scheduler()
        job = Job(
            interval=10,
            callback=callback,
            args=[1, ],
            kwargs={'k': 'v'},
            times=times
        )
        scheduler.add_job(job)
        scheduler._jobs[0].last_called = self.INIT_TIME

        return scheduler, job, callback

    def test_whenLoopNotTimeToRunJob_shouldNotRunJob(self):
        scheduler, _, callback = self._setup()

        current_time = 10.9
        current_time_mock = MagicMock(return_value=current_time)
        with patch('time.monotonic', current_time_mock):
            scheduler.loop()

        callback.assert_not_called()
        job_meta = scheduler._jobs[0]
        assert job_meta.times_called == 0
        assert job_meta.last_called == self.INIT_TIME

    def test_whenLoopTimeToRunJob_shouldRunJob(self):
        scheduler, _, callback = self._setup()

        current_time = 11.0
        current_time_mock = MagicMock(return_value=current_time)
        with patch('time.monotonic', current_time_mock):
            scheduler.loop()

        # Callback is called
        callback.assert_called_once_with(1, k='v')
        # Job meta is updated
        job_meta = scheduler._jobs[0]
        assert job_meta.times_called == 1
        assert job_meta.last_called == current_time

    def test_whenCallbackRaisesException_shouldContinue(self):
        scheduler = Scheduler()

        # Setup jobs
        happy_callback = MagicMock()
        exception_callback = MagicMock(side_effect=Exception('dummy exception'))
        scheduler.add(interval=10, callback=exception_callback)
        scheduler.add(interval=10, callback=happy_callback)

        for job_meta in scheduler._jobs:
            job_meta.last_called = self.INIT_TIME

        current_time = 11.0
        current_time_mock = MagicMock(return_value=current_time)
        with patch('time.monotonic', current_time_mock):
            scheduler.loop()

        # Callback is called
        happy_callback.assert_called_once()
        exception_callback.assert_called_once()
        # All jobs have their meta data updated
        for job_meta in scheduler._jobs:
            assert job_meta.times_called == 1
            assert job_meta.last_called == current_time

    def test_whenHasTimesAndNotExceeded_shouldRunJob(self):
        scheduler, _, callback = self._setup(times=2)

        current_time = 11.0
        current_time_mock = MagicMock(return_value=current_time)
        with patch('time.monotonic', current_time_mock):
            scheduler.loop()

        # Callback is called
        callback.assert_called_once_with(1, k='v')
        job_meta = scheduler._jobs[0]
        assert job_meta.times_called == 1
        assert job_meta.last_called == current_time

    def test_whenHasTimesAndReached_shouldRunJobAndRemoveJob(self):
        scheduler, _, callback = self._setup(times=2)

        scheduler._jobs[0].times_called = 1

        current_time = 11.0
        current_time_mock = MagicMock(return_value=current_time)
        with patch('time.monotonic', current_time_mock):
            scheduler.loop()

        # Callback is called
        callback.assert_called_once_with(1, k='v')
        assert len(scheduler._jobs) == 0
