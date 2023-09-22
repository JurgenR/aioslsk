import os
from unittest.mock import AsyncMock, Mock, MagicMock

import pytest

from aioslsk.configuration import Configuration
from aioslsk.events import TrackUserEvent
from aioslsk.model import UserStatus
from aioslsk.transfer.model import Transfer, TransferDirection
from aioslsk.transfer.manager import TransferManager
from aioslsk.transfer.state import (
    TransferState,
    DownloadingState,
    UploadingState,
    CompleteState,
    InitializingState,
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


class TestTransferManager:

    @pytest.mark.asyncio
    async def test_whenAddTransfer_shouldAddTransferAndAddUser(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        assert transfer.state.VALUE == TransferState.VIRGIN
        assert transfer in manager.transfers
        manager._internal_event_bus.emit.assert_awaited_once_with(
            TrackUserEvent(DEFAULT_USERNAME)
        )

    @pytest.mark.asyncio
    async def test_whenQueueTransfer_shouldSetQueuedState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        await manager.queue(transfer)

        assert transfer.state.VALUE == TransferState.QUEUED

    @pytest.mark.asyncio
    async def test_whenDownloadingTransfer_shouldSetDownloadingState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        transfer.state.queue()
        transfer.state.initialize()
        await manager._downloading(transfer)

        assert transfer.state.VALUE == TransferState.DOWNLOADING

    @pytest.mark.asyncio
    async def test_whenUploadingTransfer_shouldSetUploadingState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.UPLOAD)
        await manager.add(transfer)

        transfer.state.queue()
        transfer.state.initialize()
        await manager._uploading(transfer)

        assert transfer.state.VALUE == TransferState.UPLOADING

    @pytest.mark.asyncio
    async def test_whenCompleteTransfer_shouldSetCompleteState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        transfer.state.queue()
        transfer.state.initialize()
        transfer.state.start_transferring()
        await manager._complete(transfer)

        assert transfer.state.VALUE == TransferState.COMPLETE

    @pytest.mark.asyncio
    async def test_whenIncompleteTransfer_shouldSetIncompleteState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        transfer.state.queue()
        transfer.state.initialize()
        transfer.state.start_transferring()
        await manager._incomplete(transfer)

        assert transfer.state.VALUE == TransferState.INCOMPLETE

    @pytest.mark.asyncio
    async def test_whenAbortTransfer_shouldSetAbortState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        transfer.state.queue()
        transfer.state.initialize()
        transfer.state.start_transferring()
        await manager.abort(transfer)

        assert transfer.state.VALUE == TransferState.ABORTED

    @pytest.mark.asyncio
    async def test_whenFailTransfer_shouldSetFailState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        transfer.state.queue()
        transfer.state.initialize()
        transfer.state.start_transferring()
        await manager._fail(transfer, reason="nok")

        assert transfer.state.VALUE == TransferState.FAILED
        assert transfer.fail_reason == "nok"

    # Speed calculations
    def test_whenGetUploadSpeed_returnsUploadSpeed(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = UploadingState(transfer1)
        transfer2 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer2.state = UploadingState(transfer2)
        transfer3 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer3.state = UploadingState(transfer3)
        transfer1.get_speed = MagicMock(return_value=1.0)
        transfer2.get_speed = MagicMock(return_value=2.0)
        transfer3.get_speed = MagicMock(return_value=0.0)

        manager._transfers = [transfer1, transfer2, transfer3, ]

        assert manager.get_upload_speed() == 3.0

    def test_whenGetUploadSpeedAndNothingUploading_returnsZero(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer1.state = DownloadingState(transfer1)
        transfer1.get_speed = MagicMock(return_value=1.0)

        manager._transfers = [transfer1, ]

        assert manager.get_upload_speed() == 0.0

    def test_whenGetDownloadSpeed_returnsDownloadSpeed(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer1.state = DownloadingState(transfer1)
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer2.state = DownloadingState(transfer2)
        transfer3 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer3.state = DownloadingState(transfer3)
        transfer1.get_speed = MagicMock(return_value=1.0)
        transfer2.get_speed = MagicMock(return_value=2.0)
        transfer3.get_speed = MagicMock(return_value=0.0)

        manager._transfers = [transfer1, transfer2, transfer3, ]

        assert manager.get_download_speed() == 3.0

    def test_whenGetDownloadSpeedAndNothingDownloading_returnsZero(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = UploadingState(transfer1)
        transfer1.get_speed = MagicMock(return_value=1.0)

        manager._transfers = [transfer1, ]

        assert manager.get_download_speed() == 0.0

    def test_whenGetAverageUploadSpeed_shouldReturnSpeed(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer1.state = CompleteState(transfer1)
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer2.state = DownloadingState(transfer2)
        transfer3 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer3.state = UploadingState(transfer3)
        transfer4 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer4.state = CompleteState(transfer4)
        transfer5 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer5.state = CompleteState(transfer5)
        transfer1.get_speed = MagicMock(return_value=100.0)
        transfer2.get_speed = MagicMock(return_value=100.0)
        transfer3.get_speed = MagicMock(return_value=100.0)
        transfer4.get_speed = MagicMock(return_value=10.0)
        transfer5.get_speed = MagicMock(return_value=20.0)

        manager._transfers = [transfer1, transfer2, transfer3, transfer4, transfer5, ]

        assert manager.get_average_upload_speed() == 15.0

    def test_whenGetAverageUploadSpeedNoCompleteUploads_shouldReturnZero(self, manager: TransferManager):
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = UploadingState(transfer1)
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
        transfer0.state = InitializingState(transfer0)
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = UploadingState(transfer1)
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer2.state = DownloadingState(transfer2)
        manager._transfers = [transfer0, transfer1, transfer2, ]

        assert manager.get_uploading() == [transfer0, transfer1, ]

    def test_whenGetDownloading_shouldReturnDownloading(self, manager: TransferManager):
        transfer0 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer0.state = InitializingState(transfer0)
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = UploadingState(transfer1)
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer2.state = DownloadingState(transfer2)
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

        assert manager._prioritize_uploads([transfer, transfer2]) == [transfer2, transfer]

    def test_rankingUploads_privileged_shouldSortUploads(self, manager: TransferManager):
        USER = 'user0'
        USER2 = 'user1'

        user = manager._state.get_or_create_user(USER)
        user.privileged = False
        user2 = manager._state.get_or_create_user(USER2)
        user2.privileged = True

        transfer = Transfer(USER, 'C:\\dir0', TransferDirection.UPLOAD)
        transfer2 = Transfer(USER2, 'C:\\dir0', TransferDirection.UPLOAD)

        assert manager._prioritize_uploads([transfer, transfer2]) == [transfer2, transfer]

    def test_rankingUploads_isFriend_shouldSortUploads(self, manager: TransferManager):
        USER = 'user0'
        USER2 = FRIEND

        manager._state.get_or_create_user(USER)
        manager._state.get_or_create_user(USER2)

        transfer = Transfer(USER, 'C:\\dir0', TransferDirection.UPLOAD)
        transfer2 = Transfer(USER2, 'C:\\dir0', TransferDirection.UPLOAD)

        assert manager._prioritize_uploads([transfer, transfer2]) == [transfer2, transfer]
