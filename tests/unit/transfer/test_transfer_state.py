from typing import Type
from unittest.mock import MagicMock, patch

import pytest

from aioslsk.transfer.model import Transfer, TransferDirection
from aioslsk.transfer.state import (
    TransferState,
    DownloadingState,
    UploadingState,
    AbortedState,
    CompleteState,
    IncompleteState,
    InitializingState,
    QueuedState,
    FailedState,
)


class TestTransferState:

    def test_initStateFromValue(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        state = TransferState.init_from_state(TransferState.ABORTED, transfer)

        assert isinstance(state, AbortedState)

    def test_initStateFromValue_nonExisting_shouldRaise(self):
        with pytest.raises(Exception):
            TransferState.init_from_state('bogus')

    @pytest.mark.parametrize('initial_state', [
        DownloadingState,
        UploadingState,
    ])
    def test_whenTransitionToFailed_shouldSetStateAndCompleteTime(self, initial_state: Type[TransferState]):
        time_mock = MagicMock(return_value=12.0)

        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        transfer.start_time = 1.0
        with patch('time.time', time_mock):
            transfer.state.fail(reason='err')

        assert transfer.complete_time == 12.0
        assert transfer.state.VALUE == TransferState.FAILED
        assert transfer.fail_reason == 'err'

    @pytest.mark.parametrize('initial_state', [
        QueuedState,
        InitializingState,
        IncompleteState,
    ])
    def test_whenTransitionToFailed_shouldSetState(self, initial_state: Type[TransferState]):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        transfer.state.fail(reason='err')

        assert transfer.complete_time is None
        assert transfer.state.VALUE == TransferState.FAILED
        assert transfer.fail_reason == 'err'

    @pytest.mark.parametrize('initial_state', [
        DownloadingState,
        UploadingState,
    ])
    def test_whenTransitionToAborted_shouldSetStateAndCompleteTime(self, initial_state: Type[TransferState]):
        time_mock = MagicMock(return_value=12.0)

        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        transfer.start_time = 1.0
        with patch('time.time', time_mock):
            transfer.state.abort()

        assert transfer.complete_time == 12.0
        assert transfer.state.VALUE == TransferState.ABORTED

    @pytest.mark.parametrize('initial_state', [
        QueuedState,
        InitializingState,
        IncompleteState,
    ])
    def test_whenTransitionToAborted_shouldSetState(self, initial_state: Type[TransferState]):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        transfer.state.abort()

        assert transfer.complete_time is None
        assert transfer.state.VALUE == TransferState.ABORTED

    @pytest.mark.parametrize('initial_state', [
        InitializingState,
    ])
    def test_whenTransitionToQueued_shouldSetState(self, initial_state: Type[TransferState]):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        transfer.state.queue()

        assert transfer.state.VALUE == TransferState.QUEUED

    @pytest.mark.parametrize('initial_state', [
        IncompleteState,
        CompleteState,
        AbortedState,
        FailedState,
    ])
    def test_whenTransitionToQueued_shouldSetStateAndResetTimes(self, initial_state: Type[TransferState]):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = initial_state(transfer)
        transfer.start_time = 1.0
        transfer.complete_time = 2.0
        transfer.state.queue()

        assert transfer.start_time is None
        assert transfer.complete_time is None
        assert transfer.state.VALUE == TransferState.QUEUED

    def test_whenTransitionQueuedToInitializing_shouldSetState(self):
        transfer = Transfer(None, None, TransferDirection.UPLOAD)
        transfer.state = QueuedState(transfer)
        transfer.state.initialize()

        assert transfer.state.VALUE == TransferState.INITIALIZING

    def test_whenTransitionDownloadingToIncomplete_shouldSetCompleteTime(self):
        time_mock = MagicMock(return_value=12.0)

        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = DownloadingState(transfer)
        transfer.start_time = 1.0
        with patch('time.time', time_mock):
            transfer.state.incomplete()

        assert transfer.complete_time == 12.0
        assert transfer.state.VALUE == TransferState.INCOMPLETE

    def test_whenTransitionDownloadingToComplete_shouldSetCompleteTime(self):
        time_mock = MagicMock(return_value=12.0)

        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.state = DownloadingState(transfer)
        transfer.start_time = 1.0
        with patch('time.time', time_mock):
            transfer.state.complete()

        assert transfer.complete_time == 12.0
        assert transfer.state.VALUE == TransferState.COMPLETE

    def test_whenTransitionInitializingToUploading_shouldSetStartTime(self):
        time_mock = MagicMock(return_value=2.0)

        transfer = Transfer(None, None, TransferDirection.UPLOAD)
        transfer.state = InitializingState(transfer)
        with patch('time.time', time_mock):
            transfer.state.start_transfering()

        assert transfer.start_time == 2.0
        assert transfer.state.VALUE == TransferState.UPLOADING
