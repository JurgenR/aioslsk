import asyncio
import pytest
from unittest.mock import ANY, AsyncMock, Mock, patch
from aioslsk.tasks import BackgroundTask, Timer


async def dummy_coro():
    pass


class TestBackgroundTask:

    def test_start_shouldCreateTask(self):
        task = BackgroundTask(1.0, dummy_coro)
        async_task = Mock()
        with patch('asyncio.create_task', return_value=async_task) as create_task:
            task.start()

        assert task._task == async_task
        assert task.is_running() is True
        create_task.assert_called_once_with(ANY, name='background-task')

    def test_start_alreadyStarted_shouldDoNothing(self):
        task = BackgroundTask(1.0, dummy_coro)
        async_task = Mock()
        with patch('asyncio.create_task', return_value=async_task) as create_task:
            task.start()
            task.start()

        create_task.assert_called_once_with(ANY, name='background-task')

    def test_cancel_shouldCancelTask(self):
        task = BackgroundTask(1.0, dummy_coro)
        async_task = Mock()
        with patch('asyncio.create_task', return_value=async_task):
            task.start()
            ret_value = task.cancel()

        assert ret_value == async_task
        assert task._task is None
        async_task.cancel.assert_called_once()

    def test_cancel_notStarted_shouldDoNothing(self):
        task = BackgroundTask(1.0, dummy_coro)
        ret_value = task.cancel()
        assert ret_value is None

    @pytest.mark.asyncio
    async def test_runner(self):
        interval = 0.001
        runtime = 0.1

        # Needs to explicitly return None otherwise a new AsyncMock will be
        # returned
        task_coro = AsyncMock(return_value=None)
        task = BackgroundTask(interval, task_coro)
        with patch('asyncio.sleep', wraps=asyncio.sleep) as sleep:
            task.start()
            await asyncio.sleep(runtime)
            task.cancel()

        task_coro.assert_awaited()
        sleep.assert_any_await(interval)

    @pytest.mark.asyncio
    async def test_runner_withContext(self):
        interval = 0.001
        runtime = 0.1

        context = Mock()
        # Needs to explicitly return None otherwise a new AsyncMock will be
        # returned
        task_coro = AsyncMock(return_value=None)
        task = BackgroundTask(interval, task_coro, context=context)
        with patch('asyncio.sleep', wraps=asyncio.sleep) as sleep:
            task.start()
            await asyncio.sleep(runtime)
            task.cancel()

        task_coro.assert_awaited_with(context)
        sleep.assert_any_await(interval)

    @pytest.mark.asyncio
    async def test_runner_callableInterval(self):
        interval = 0.001
        interval_func = Mock(return_value=interval)
        runtime = 0.1

        # Needs to explicitly return None otherwise a new AsyncMock will be
        # returned
        task_coro = AsyncMock(return_value=None)
        task = BackgroundTask(interval_func, task_coro)
        with patch('asyncio.sleep', wraps=asyncio.sleep) as sleep:
            task.start()
            await asyncio.sleep(runtime)
            task.cancel()

        task_coro.assert_awaited()
        interval_func.assert_called()
        sleep.assert_any_await(interval)

    @pytest.mark.asyncio
    async def test_runner_preempt_returnInterval(self):
        interval = 0.001
        interval_after_preempt = 0.002
        runtime = 0.1

        task_coro = AsyncMock(return_value=interval_after_preempt)
        task = BackgroundTask(interval, task_coro, preempt_wait=True)
        with patch('asyncio.sleep', wraps=asyncio.sleep) as sleep:
            task.start()
            await asyncio.sleep(runtime)
            task.cancel()

        task_coro.assert_awaited()
        sleep.assert_any_await(interval)
        sleep.assert_any_await(interval_after_preempt)


class TestTimer:

    def test_start_shouldCreateTask(self):
        timer = Timer(1.0, dummy_coro)
        async_task = Mock()
        with patch('asyncio.create_task', return_value=async_task) as create_task:
            timer.start()

        assert timer._task == async_task
        create_task.assert_called_once_with(ANY)

    @pytest.mark.asyncio
    async def test_cancel_shouldCancelTask(self):
        callback = AsyncMock()
        timer = Timer(1.0, callback)
        timer.start()
        await asyncio.sleep(0.5)

        timer.cancel()
        assert timer._task is None
        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_notStarted_returnsNone(self):
        timer = Timer(1.0, dummy_coro)
        result = timer.cancel()
        assert result is None

    @pytest.mark.asyncio
    async def test_reschedule(self):
        callback = AsyncMock()
        timer = Timer(1.0, callback)
        timer.start()
        await asyncio.sleep(0.5)

        timer.reschedule(timeout=2.0)
        await asyncio.sleep(1.25)
        callback.assert_not_awaited()
        await asyncio.sleep(1.0)
        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reschedule_notStarted_startsTask(self):
        callback = AsyncMock()
        timer = Timer(0.5, callback)

        timer.reschedule()
        await asyncio.sleep(0.75)
        callback.assert_awaited_once()
