import copy
import os
import shutil
from unittest.mock import AsyncMock, Mock, MagicMock, patch

import pytest

from aioslsk.configuration import Configuration
from aioslsk.events import TrackUserEvent
from aioslsk.model import UserStatus
from aioslsk.transfer import (
    Transfer,
    TransferShelveCache,
    TransferDirection,
    TransferState,
    TransferManager,
)
from aioslsk.settings import Settings
from aioslsk.state import State


FRIEND = 'friend0'
DEFAULT_SETTINGS = {
    'sharing': {
        'limits': {
            'download_slots': 2,
            'upload_slots': 2
        }
    },
    'database': {
        'name': 'unittest.db'
    },
    'users': {
        'friends': [FRIEND]
    }
}
DEFAULT_FILENAME = "myfile.mp3"
DEFAULT_USERNAME = "username"
RESOURCES = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'resources')


@pytest.fixture
def configuration(tmpdir) -> Configuration:
    settings_dir = os.path.join(tmpdir, 'settings')
    data_dir = os.path.join(tmpdir, 'data')
    return Configuration(settings_dir, data_dir)


@pytest.fixture
def manager(tmpdir):
    network = AsyncMock()
    network.upload_rate_limiter = MagicMock()
    network.download_rate_limiter = MagicMock()
    event_bus = Mock()
    event_bus.emit = AsyncMock()
    event_bus.register = Mock()
    internal_event_bus = Mock()
    internal_event_bus.emit = AsyncMock()
    internal_event_bus.register = Mock()

    return TransferManager(
        State(),
        Configuration(tmpdir, tmpdir),
        Settings(DEFAULT_SETTINGS),
        event_bus, # event bus
        internal_event_bus, # internal event bus
        None, # file manager
        network # network
    )


class DummyListener:
    def on_transfer_state_changed(self, transfer: Transfer, state: TransferState):
        pass


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

    @pytest.mark.parametrize(
        "state",
        [TransferState.COMPLETE, TransferState.INCOMPLETE],
    )
    def test_whenSetStateCompleted_shouldSetCompleteTime(self, state: TransferState):
        time_mock = MagicMock(return_value=12.0)

        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        with patch('time.time', time_mock):
            transfer.set_state(state)

        assert transfer.complete_time == 12.0
        assert transfer.state == state

    @pytest.mark.parametrize(
        "state",
        [TransferState.DOWNLOADING, TransferState.UPLOADING],
    )
    def test_whenSetStateTransferProgressing_shouldSetStartTime(self, state: TransferState):
        time_mock = MagicMock(return_value=2.0)

        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        with patch('time.time', time_mock):
            transfer.set_state(state)

        assert transfer.start_time == 2.0
        assert transfer.state == state

    def test_getSpeed_transferQueued_returnZero(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.set_state(TransferState.QUEUED)

        assert 0.0 == transfer.get_speed()

    def test_getSpeed_transferComplete_returnAverageSpeed(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.set_state(TransferState.QUEUED)

        with patch('time.time', side_effect=[0.0, 2.0, ]):
            transfer.filesize = 100
            transfer.set_state(TransferState.DOWNLOADING)
            transfer.bytes_transfered = 100
            transfer.set_state(TransferState.COMPLETE)

        assert 50.0 == transfer.get_speed()

    def test_getSpeed_transferProcessing_returnAverageSpeed(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.set_state(TransferState.QUEUED)

        with patch('time.time', return_value=0.0):
            transfer.filesize = 100
            transfer.set_state(TransferState.DOWNLOADING)
            transfer.bytes_transfered = 30

        with patch('time.monotonic', side_effect=[0.05, 0.05, 0.15, 0.15, 0.25, 0.25, 0.3]):
            transfer.add_speed_log_entry(5)
            transfer.add_speed_log_entry(5)
            transfer.add_speed_log_entry(5)
            transfer.add_speed_log_entry(5)
            transfer.add_speed_log_entry(5)
            transfer.add_speed_log_entry(5)

            assert 120.0 == transfer.get_speed()

    def test_getSpeed_transferProcessing_noEntries_returnZero(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.set_state(TransferState.QUEUED)

        with patch('time.time', return_value=0.0):
            transfer.filesize = 100
            transfer.set_state(TransferState.DOWNLOADING)
            transfer.bytes_transfered = 30

        assert 0.0 == transfer.get_speed()

    def test_setState_alreadyInState_shouldDoNothing(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer.set_state(TransferState.QUEUED)
        transfer.set_state(TransferState.QUEUED)

        assert TransferState.QUEUED == transfer.state


class TestTransferManager:

    @pytest.mark.asyncio
    async def test_whenAddTransfer_shouldAddTransferAndAddUser(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        assert transfer.state == TransferState.VIRGIN
        assert transfer in manager.transfers
        manager._internal_event_bus.emit.assert_awaited_once_with(
            TrackUserEvent(DEFAULT_USERNAME)
        )

    @pytest.mark.asyncio
    async def test_whenQueueTransfer_shouldSetQueuedState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        await manager.queue(transfer)

        assert transfer.state == TransferState.QUEUED

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'state',
        [TransferState.DOWNLOADING, TransferState.UPLOADING, TransferState.INITIALIZING]
    )
    async def test_whenQueueTransferForced_shouldSetQueuedState(self, manager: TransferManager, state: TransferState):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        transfer.set_state(state)
        await manager.queue(transfer, force=True)

        assert transfer.state == TransferState.QUEUED

    @pytest.mark.asyncio
    async def test_whenDownloadingTransfer_shouldSetDownloadingState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        transfer.set_state(TransferState.QUEUED)
        await manager.downloading(transfer)

        assert transfer.state == TransferState.DOWNLOADING

    @pytest.mark.asyncio
    async def test_whenUploadingTransfer_shouldSetUploadingState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        transfer.set_state(TransferState.QUEUED)
        await manager.uploading(transfer)

        assert transfer.state == TransferState.UPLOADING

    @pytest.mark.asyncio
    async def test_whenCompleteTransfer_shouldSetCompleteState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        transfer.set_state(TransferState.QUEUED)
        transfer.set_state(TransferState.DOWNLOADING)
        await manager.complete(transfer)

        assert transfer.state == TransferState.COMPLETE

    @pytest.mark.asyncio
    async def test_whenIncompleteTransfer_shouldSetIncompleteState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        transfer.set_state(TransferState.QUEUED)
        transfer.set_state(TransferState.DOWNLOADING)
        await manager.incomplete(transfer)

        assert transfer.state == TransferState.INCOMPLETE

    @pytest.mark.asyncio
    async def test_whenAbortTransfer_shouldSetAbortState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        transfer.set_state(TransferState.QUEUED)
        transfer.set_state(TransferState.DOWNLOADING)
        await manager.abort(transfer)

        assert transfer.state == TransferState.ABORTED

    @pytest.mark.asyncio
    async def test_whenFailTransfer_shouldSetFailState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        transfer.set_state(TransferState.QUEUED)
        transfer.set_state(TransferState.DOWNLOADING)
        await manager.fail(transfer, reason="nok")

        assert transfer.state == TransferState.FAILED
        assert transfer.fail_reason == "nok"

    # Speed calculations
    def test_whenGetUploadSpeed_returnsUploadSpeed(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = TransferState.UPLOADING
        transfer2 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer2.state = TransferState.UPLOADING
        transfer3 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer3.state = TransferState.UPLOADING
        transfer1.get_speed = MagicMock(return_value=1.0)
        transfer2.get_speed = MagicMock(return_value=2.0)
        transfer3.get_speed = MagicMock(return_value=0.0)

        manager._transfers = [transfer1, transfer2, transfer3, ]

        assert manager.get_upload_speed() == 3.0

    def test_whenGetUploadSpeedAndNothingUploading_returnsZero(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer1.state = TransferState.DOWNLOADING
        transfer1.get_speed = MagicMock(return_value=1.0)

        manager._transfers = [transfer1, ]

        assert manager.get_upload_speed() == 0.0

    def test_whenGetDownloadSpeed_returnsDownloadSpeed(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer1.state = TransferState.DOWNLOADING
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer2.state = TransferState.DOWNLOADING
        transfer3 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer3.state = TransferState.DOWNLOADING
        transfer1.get_speed = MagicMock(return_value=1.0)
        transfer2.get_speed = MagicMock(return_value=2.0)
        transfer3.get_speed = MagicMock(return_value=0.0)

        manager._transfers = [transfer1, transfer2, transfer3, ]

        assert manager.get_download_speed() == 3.0

    def test_whenGetDownloadSpeedAndNothingDownloading_returnsZero(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = TransferState.UPLOADING
        transfer1.get_speed = MagicMock(return_value=1.0)

        manager._transfers = [transfer1, ]

        assert manager.get_download_speed() == 0.0

    def test_whenGetAverageUploadSpeed_shouldReturnSpeed(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer1.state = TransferState.COMPLETE
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer2.state = TransferState.DOWNLOADING
        transfer3 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer3.state = TransferState.UPLOADING
        transfer4 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer4.state = TransferState.COMPLETE
        transfer5 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer5.state = TransferState.COMPLETE
        transfer1.get_speed = MagicMock(return_value=100.0)
        transfer2.get_speed = MagicMock(return_value=100.0)
        transfer3.get_speed = MagicMock(return_value=100.0)
        transfer4.get_speed = MagicMock(return_value=10.0)
        transfer5.get_speed = MagicMock(return_value=20.0)

        manager._transfers = [transfer1, transfer2, transfer3, transfer4, transfer5, ]

        assert manager.get_average_upload_speed() == 15.0

    def test_whenGetAverageUploadSpeedNoCompleteUploads_shouldReturnZero(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = TransferState.UPLOADING
        transfer1.get_speed = MagicMock(return_value=100.0)

        manager._transfers = [transfer1, ]

        assert manager.get_average_upload_speed() == 0.0

    # Retrieval of single transfer
    def test_whenGetTransferExists_shouldReturnTransfer(self, manager: TransferManager):
        transfer = Transfer("myuser", "myfile", TransferDirection.UPLOAD)
        manager._transfers = [transfer, ]

        assert manager.get_transfer("myuser", "myfile", TransferDirection.UPLOAD) == transfer

    def test_whenGetTransferNotExists_shouldRaiseException(self, manager: TransferManager):
        transfer = Transfer("myuser", "myfile", TransferDirection.UPLOAD)
        manager._transfers = [transfer, ]

        with pytest.raises(LookupError):
            manager.get_transfer("myuser", "myfile", TransferDirection.DOWNLOAD)

        with pytest.raises(LookupError):
            manager.get_transfer("myuser", "mynonfile", TransferDirection.UPLOAD)

        with pytest.raises(LookupError):
            manager.get_transfer("mynonuser", "myfile", TransferDirection.UPLOAD)

    # Retrieval of multiple transfers

    def test_whenGetUploading_shouldReturnUploading(self, manager: TransferManager):
        transfer0 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer0.state = TransferState.INITIALIZING
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = TransferState.UPLOADING
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer2.state = TransferState.DOWNLOADING
        manager._transfers = [transfer0, transfer1, transfer2, ]

        assert manager.get_uploading() == [transfer0, transfer1, ]

    def test_whenGetDownloading_shouldReturnDownloading(self, manager: TransferManager):
        transfer0 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer0.state = TransferState.INITIALIZING
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = TransferState.UPLOADING
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer2.state = TransferState.DOWNLOADING
        manager._transfers = [transfer0, transfer1, transfer2, ]

        assert manager.get_downloading() == [transfer0, transfer2, ]

    def test_whenGetUploads_shouldReturnUploads(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer3 = Transfer(None, None, TransferDirection.UPLOAD)
        manager._transfers = [transfer1, transfer2, transfer3, ]

        assert manager.get_uploads() == [transfer1, transfer3]

    def test_whenGetDownloads_shouldReturnDownloads(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer3 = Transfer(None, None, TransferDirection.UPLOAD)
        manager._transfers = [transfer1, transfer2, transfer3, ]

        assert manager.get_downloads() == [transfer2, ]

    def test_rankingUploads_userOnline_shouldSortUploads(self, manager: TransferManager):
        USER = 'user0'
        USER2 = 'user1'

        user = manager._state.get_or_create_user(USER)
        user.status = UserStatus.UNKNOWN
        user2 = manager._state.get_or_create_user(USER2)
        user2.status = UserStatus.ONLINE

        transfer = Transfer(USER, 'C:\\dir0', TransferDirection.UPLOAD)
        transfer2 = Transfer(USER2, 'C:\\dir0', TransferDirection.UPLOAD)

        assert manager._rank_queued_uploads([transfer, transfer2]) == [transfer2, transfer]

    def test_rankingUploads_privileged_shouldSortUploads(self, manager: TransferManager):
        USER = 'user0'
        USER2 = 'user1'

        user = manager._state.get_or_create_user(USER)
        user.privileged = False
        user2 = manager._state.get_or_create_user(USER2)
        user2.privileged = True

        transfer = Transfer(USER, 'C:\\dir0', TransferDirection.UPLOAD)
        transfer2 = Transfer(USER2, 'C:\\dir0', TransferDirection.UPLOAD)

        assert manager._rank_queued_uploads([transfer, transfer2]) == [transfer2, transfer]

    def test_rankingUploads_isFriend_shouldSortUploads(self, manager: TransferManager):
        USER = 'user0'
        USER2 = FRIEND

        manager._state.get_or_create_user(USER)
        manager._state.get_or_create_user(USER2)

        transfer = Transfer(USER, 'C:\\dir0', TransferDirection.UPLOAD)
        transfer2 = Transfer(USER2, 'C:\\dir0', TransferDirection.UPLOAD)

        assert manager._rank_queued_uploads([transfer, transfer2]) == [transfer2, transfer]


class TestTransferShelveCache:
    TRANSFERS = [
        Transfer('user0', '@abcdef\\file.mp3', TransferDirection.DOWNLOAD),
        Transfer('user1', '@abcdef\\file.flac', TransferDirection.UPLOAD)
    ]

    def test_read(self, configuration: Configuration):
        shutil.copytree(os.path.join(RESOURCES, 'data'), configuration.data_directory, dirs_exist_ok=True)
        cache = TransferShelveCache(configuration.data_directory)
        transfers = cache.read()
        assert 2 == len(transfers)
        assert self.TRANSFERS == transfers

    def test_write(self, configuration: Configuration):
        cache = TransferShelveCache(configuration.data_directory)
        cache.write(self.TRANSFERS)

    def test_write_withDeletedEntries_shouldRemove(self, configuration: Configuration):
        cache = TransferShelveCache(configuration.data_directory)
        cache.write(self.TRANSFERS)

        transfers_with_deleted = copy.deepcopy(self.TRANSFERS)
        transfers_with_deleted.pop()
        cache.write(transfers_with_deleted)

        transfers = cache.read()
        assert transfers_with_deleted == transfers
