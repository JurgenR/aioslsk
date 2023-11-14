from unittest.mock import MagicMock, patch
import pytest
import logging

from aioslsk.transfer.model import Transfer, TransferDirection
from aioslsk.transfer.state import TransferState, QueuedState, InitializingState

logger = logging.getLogger()

@pytest.fixture
def disable_logging():
    prev_level = logger.getEffectiveLevel()
    logger.setLevel(logging.WARNING)
    yield
    logger.setLevel(prev_level)


class TestTransfer:

    @pytest.mark.parametrize(
        "start_time,complete_time,bytes_transfered,expected_result",
        [
            (None, None, 0, 0.0),
            (2.0, None, 0, 0.0),
            (2.0, None, 10, 1.0),
            (2.0, 12.0, 10, 1.0),
            # Edge case: start and complete are equal
            (2.0, 2.0, 10, 0.0)
        ]
    )
    def test_getSpeed(self, start_time, complete_time, bytes_transfered, expected_result):
        time_mock = MagicMock(return_value=12.0)

        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.start_time = start_time
        transfer.complete_time = complete_time
        transfer.bytes_transfered = bytes_transfered

        with patch('time.time', time_mock):
            assert transfer.get_speed() == expected_result

    def test_getSpeed_transferQueued_returnZero(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = QueuedState(transfer)

        assert 0.0 == transfer.get_speed()

    # WARNING: This test fails with logging enabled. The logging library will
    # make use of the time.time and take away the mocked values for its own use
    # resulting in a StopIteration error
    @pytest.mark.asyncio
    async def test_getSpeed_transferComplete_returnAverageSpeed(self, disable_logging):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = InitializingState(transfer)

        with patch('time.time', side_effect=[0.0, 2.0, ]):
            transfer.filesize = 100
            await transfer.state.start_transferring()
            transfer.bytes_transfered = 100
            await transfer.state.complete()

        assert 50.0 == transfer.get_speed()

    @pytest.mark.asyncio
    async def test_getSpeed_transferProcessing_returnAverageSpeed(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        await transfer.state.queue()
        await transfer.state.initialize()

        with patch('time.time', return_value=0.0):
            transfer.filesize = 100
            await transfer.state.start_transferring()
            transfer.bytes_transfered = 30

        with patch('time.monotonic', side_effect=[0.05, 0.05, 0.15, 0.15, 0.25, 0.25, 0.3]):
            transfer.add_speed_log_entry(5)
            transfer.add_speed_log_entry(5)
            transfer.add_speed_log_entry(5)
            transfer.add_speed_log_entry(5)
            transfer.add_speed_log_entry(5)
            transfer.add_speed_log_entry(5)

            assert 120.0 == transfer.get_speed()

    @pytest.mark.asyncio
    async def test_getSpeed_transferProcessing_noEntries_returnZero(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        await transfer.state.queue()
        await transfer.state.initialize()

        with patch('time.time', return_value=0.0):
            transfer.filesize = 100
            await transfer.state.start_transferring()
            transfer.bytes_transfered = 30

        assert 0.0 == transfer.get_speed()

    @pytest.mark.asyncio
    async def test_setState_alreadyInState_shouldDoNothing(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        await transfer.state.queue()
        await transfer.state.queue()

        assert TransferState.QUEUED == transfer.state.VALUE
