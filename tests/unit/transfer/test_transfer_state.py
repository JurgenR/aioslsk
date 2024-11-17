from unittest.mock import MagicMock, patch

import pytest

from aioslsk.transfer.model import Transfer, TransferDirection
from aioslsk.transfer.state import (
    TransferState,
    AbortedState,
    CompleteState,
    DownloadingState,
    FailedState,
    IncompleteState,
    InitializingState,
    PausedState,
    QueuedState,
    UploadingState,
    VirginState,
)


class TestTransferState:

    def test_initStateFromValue(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        state = TransferState.init_from_state(TransferState.ABORTED, transfer)

        assert isinstance(state, AbortedState)

    def test_initStateFromValue_nonExisting_shouldRaise(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        with pytest.raises(Exception):
            TransferState.init_from_state('bogus', transfer)

    @pytest.mark.asyncio
    async def test_whenTransitionVirginToQueued_shouldResetRemotelyQueued(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.remotely_queued = True

        await transfer.state.queue()

        assert transfer.remotely_queued is False
        assert transfer.state.VALUE == TransferState.QUEUED

    @pytest.mark.parametrize('initial_state', [
        DownloadingState,
        UploadingState,
    ])
    @pytest.mark.asyncio
    async def test_whenTransitionToFailed_shouldSetStateAndCompleteTime(self, initial_state: type[TransferState]):
        time_mock = MagicMock(return_value=12.0)

        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        transfer.start_time = 1.0
        with patch('time.time', time_mock):
            await transfer.state.fail(reason='err')

        assert transfer.complete_time == 12.0
        assert transfer.state.VALUE == TransferState.FAILED
        assert transfer.fail_reason == 'err'

    @pytest.mark.parametrize('initial_state', [
        QueuedState,
        InitializingState,
        IncompleteState,
        PausedState,
    ])
    @pytest.mark.asyncio
    async def test_whenTransitionToFailed_shouldSetState(self, initial_state: type[TransferState]):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        await transfer.state.fail(reason='err')

        assert transfer.complete_time is None
        assert transfer.state.VALUE == TransferState.FAILED
        assert transfer.fail_reason == 'err'

    @pytest.mark.parametrize('initial_state', [
        DownloadingState,
        UploadingState,
    ])
    @pytest.mark.asyncio
    async def test_whenTransitionToPaused_shouldSetStateAndCompleteTime(self, initial_state: type[TransferState]):
        time_mock = MagicMock(return_value=12.0)

        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        transfer.start_time = 1.0
        with patch('time.time', time_mock):
            await transfer.state.pause()

        assert transfer.complete_time == 12.0
        assert transfer.state.VALUE == TransferState.PAUSED

    @pytest.mark.parametrize('initial_state', [
        VirginState,
        QueuedState,
        InitializingState,
        IncompleteState,
    ])
    @pytest.mark.asyncio
    async def test_whenTransitionToPaused_shouldSetState(self, initial_state: type[TransferState]):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        await transfer.state.pause()

        assert transfer.complete_time is None
        assert transfer.state.VALUE == TransferState.PAUSED

    @pytest.mark.parametrize('initial_state', [
        InitializingState,
    ])
    @pytest.mark.asyncio
    async def test_whenTransitionToQueued_shouldSetState(self, initial_state: type[TransferState]):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        await transfer.state.queue()

        assert transfer.state.VALUE == TransferState.QUEUED

    @pytest.mark.parametrize('initial_state', [
        DownloadingState,
        UploadingState,
    ])
    @pytest.mark.asyncio
    async def test_whenTransitionToAborted_shouldSetStateAndCompleteTime(self, initial_state: type[TransferState]):
        time_mock = MagicMock(return_value=12.0)

        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        transfer.start_time = 1.0
        with patch('time.time', time_mock):
            await transfer.state.abort()

        assert transfer.complete_time == 12.0
        assert transfer.state.VALUE == TransferState.ABORTED

    @pytest.mark.parametrize('initial_state', [
        QueuedState,
        InitializingState,
        IncompleteState,
        PausedState,
    ])
    @pytest.mark.asyncio
    async def test_whenTransitionToAborted_shouldSetState(self, initial_state: type[TransferState]):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        await transfer.state.abort()

        assert transfer.complete_time is None
        assert transfer.state.VALUE == TransferState.ABORTED

    @pytest.mark.parametrize('initial_state', [
        InitializingState,
    ])
    @pytest.mark.asyncio
    async def test_whenTransitionToQueued_shouldSetState(self, initial_state: type[TransferState]):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        await transfer.state.queue()

        assert transfer.state.VALUE == TransferState.QUEUED

    @pytest.mark.parametrize('initial_state', [
        IncompleteState,
        CompleteState,
        AbortedState,
        FailedState,
    ])
    @pytest.mark.asyncio
    async def test_whenTransitionToQueued_shouldSetStateAndResetTimes(self, initial_state: type[TransferState]):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        transfer.start_time = 1.0
        transfer.complete_time = 2.0
        await transfer.state.queue()

        assert transfer.start_time is None
        assert transfer.complete_time is None
        assert transfer.state.VALUE == TransferState.QUEUED

    @pytest.mark.asyncio
    async def test_whenTransitionQueuedToInitializing_shouldSetState(self):
        transfer = Transfer(None, None, TransferDirection.UPLOAD)
        transfer.state = QueuedState(transfer)
        await transfer.state.initialize()

        assert transfer.state.VALUE == TransferState.INITIALIZING

    @pytest.mark.asyncio
    async def test_whenTransitionDownloadingToIncomplete_shouldSetCompleteTime(self):
        time_mock = MagicMock(return_value=12.0)

        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = DownloadingState(transfer)
        transfer.start_time = 1.0
        with patch('time.time', time_mock):
            await transfer.state.incomplete()

        assert transfer.complete_time == 12.0
        assert transfer.state.VALUE == TransferState.INCOMPLETE

    @pytest.mark.asyncio
    async def test_whenTransitionDownloadingToComplete_shouldSetCompleteTime(self):
        time_mock = MagicMock(return_value=12.0)

        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = DownloadingState(transfer)
        transfer.start_time = 1.0
        with patch('time.time', time_mock):
            await transfer.state.complete()

        assert transfer.complete_time == 12.0
        assert transfer.state.VALUE == TransferState.COMPLETE

    @pytest.mark.asyncio
    async def test_whenTransitionInitializingToUploading_shouldSetStartTime(self):
        time_mock = MagicMock(return_value=2.0)

        transfer = Transfer(None, None, TransferDirection.UPLOAD)
        transfer.state = InitializingState(transfer)
        transfer.remotely_queued = True
        with patch('time.time', time_mock):
            await transfer.state.start_transferring()

        assert transfer.remotely_queued == False
        assert transfer.start_time == 2.0
        assert transfer.state.VALUE == TransferState.UPLOADING

    @pytest.mark.asyncio
    async def test_whenTransitionInitializingToDownloading_shouldSetStartTime(self):
        time_mock = MagicMock(return_value=2.0)

        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = InitializingState(transfer)
        transfer.remotely_queued = True
        with patch('time.time', time_mock):
            await transfer.state.start_transferring()

        assert transfer.remotely_queued == False
        assert transfer.start_time == 2.0
        assert transfer.state.VALUE == TransferState.DOWNLOADING
