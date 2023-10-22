import asyncio
import os
from unittest.mock import AsyncMock, Mock, MagicMock, patch

import pytest

from aioslsk.exceptions import ConnectionWriteError, RequestPlaceFailedError
from aioslsk.user.model import UserStatus, TrackingFlag
from aioslsk.protocol.messages import PeerPlaceInQueueRequest, PeerPlaceInQueueReply
from aioslsk.transfer.cache import TransferShelveCache
from aioslsk.transfer.model import Transfer, TransferDirection
from aioslsk.transfer.manager import TransferManager
from aioslsk.transfer.state import (
    AbortedState,
    CompleteState,
    DownloadingState,
    InitializingState,
    TransferState,
    UploadingState,
)
from aioslsk.settings import Settings
from aioslsk.user.manager import UserManager


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
def user_manager() -> UserManager:
    user_manager = UserManager(
        Settings(DEFAULT_SETTINGS),
        Mock(), # Event bus
        Mock(), # Internal event bus
        AsyncMock(), # Network
    )
    user_manager.track_user = AsyncMock()
    user_manager.untrack_user = AsyncMock()
    return user_manager


@pytest.fixture
def manager(tmpdir, user_manager: UserManager) -> TransferManager:
    network = AsyncMock()
    network.upload_rate_limiter = MagicMock()
    network.download_rate_limiter = MagicMock()
    event_bus = Mock()
    event_bus.emit = AsyncMock()
    event_bus.register = Mock()
    internal_event_bus = Mock()
    internal_event_bus.emit = AsyncMock()
    internal_event_bus.register = Mock()
    shares_manager = Mock()

    return TransferManager(
        Settings(DEFAULT_SETTINGS),
        event_bus, # event bus
        internal_event_bus, # internal event bus
        user_manager,
        shares_manager, # shares manager
        network, # network
        cache=TransferShelveCache(tmpdir)
    )


class TestTransferManager:

    @pytest.mark.asyncio
    async def test_whenAddTransfer_shouldAddTransferAndAddUser(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        assert transfer.state.VALUE == TransferState.VIRGIN
        assert transfer in manager.transfers
        manager._user_manager.track_user.assert_awaited_once_with(
            DEFAULT_USERNAME, TrackingFlag.TRANSFER
        )

    @pytest.mark.asyncio
    async def test_whenQueueTransfer_shouldSetQueuedState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        await manager.add(transfer)

        await manager.queue(transfer)

        assert transfer.state.VALUE == TransferState.QUEUED

    @pytest.mark.asyncio
    async def test_whenAbortTransfer_download_shouldSetAbortStateAndDeleteFile(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        transfer.local_path = '/some/path.mp3'
        await manager.add(transfer)

        await transfer.state.queue()
        await transfer.state.initialize()
        await transfer.state.start_transferring()
        with patch('aiofiles.os.path.exists', return_value=True):
            with patch('aiofiles.os.remove', return_value=None) as patched_remove:
                await manager.abort(transfer)

        assert transfer.state.VALUE == TransferState.ABORTED
        patched_remove.assert_awaited_once_with(transfer.local_path)

    @pytest.mark.asyncio
    async def test_whenAbortTransfer_upload_shouldSetAbortState(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.UPLOAD)
        transfer.local_path = '/some/path.mp3'
        await manager.add(transfer)

        await transfer.state.queue()
        await transfer.state.initialize()
        await transfer.state.start_transferring()
        with patch('aiofiles.os.path.exists', return_value=True):
            with patch('aiofiles.os.remove', return_value=None) as patched_remove:
                await manager.abort(transfer)

        assert transfer.state.VALUE == TransferState.ABORTED
        patched_remove.assert_not_awaited()

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

        with pytest.raises(ValueError):
            manager.get_transfer("myuser", "myfile", TransferDirection.DOWNLOAD)

        with pytest.raises(ValueError):
            manager.get_transfer("myuser", "mynonfile", TransferDirection.UPLOAD)

        with pytest.raises(ValueError):
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

        user = manager._user_manager.get_or_create_user(USER)
        user.status = UserStatus.UNKNOWN
        user2 = manager._user_manager.get_or_create_user(USER2)
        user2.status = UserStatus.ONLINE

        transfer = Transfer(USER, 'C:\\dir0', TransferDirection.UPLOAD)
        transfer2 = Transfer(USER2, 'C:\\dir0', TransferDirection.UPLOAD)

        assert manager._prioritize_uploads([transfer, transfer2]) == [transfer2, transfer]

    def test_rankingUploads_privileged_shouldSortUploads(self, manager: TransferManager):
        USER = 'user0'
        USER2 = 'user1'

        user = manager._user_manager.get_or_create_user(USER)
        user.privileged = False
        user2 = manager._user_manager.get_or_create_user(USER2)
        user2.privileged = True

        transfer = Transfer(USER, 'C:\\dir0', TransferDirection.UPLOAD)
        transfer2 = Transfer(USER2, 'C:\\dir0', TransferDirection.UPLOAD)

        assert manager._prioritize_uploads([transfer, transfer2]) == [transfer2, transfer]

    def test_rankingUploads_isFriend_shouldSortUploads(self, manager: TransferManager):
        USER = 'user0'
        USER2 = FRIEND

        manager._user_manager.get_or_create_user(USER)
        manager._user_manager.get_or_create_user(USER2)

        transfer = Transfer(USER, 'C:\\dir0', TransferDirection.UPLOAD)
        transfer2 = Transfer(USER2, 'C:\\dir0', TransferDirection.UPLOAD)

        assert manager._prioritize_uploads([transfer, transfer2]) == [transfer2, transfer]

    @pytest.mark.asyncio
    async def test_manageUserTracking_shouldTrackIfUnfinished(self, manager: TransferManager):
        transfer0 = Transfer('user0', 'file0-0.mp3', TransferDirection.DOWNLOAD)
        transfer0.state = DownloadingState(transfer0)
        transfer1 = Transfer('user0', 'file0-1.mp3', TransferDirection.DOWNLOAD)
        transfer1.state = CompleteState(transfer1)
        manager._transfers = [transfer0, transfer1]

        await manager.manage_user_tracking()

        manager._user_manager.track_user.assert_awaited_once_with(
            'user0', TrackingFlag.TRANSFER
        )

    @pytest.mark.asyncio
    async def test_manageUserTracking_shouldUntrackIfAllFinished(self, manager: TransferManager):
        transfer0 = Transfer('user0', 'file0-0.mp3', TransferDirection.DOWNLOAD)
        transfer0.state = AbortedState(transfer0)
        transfer1 = Transfer('user0', 'file0-1.mp3', TransferDirection.DOWNLOAD)
        transfer1.state = CompleteState(transfer1)
        manager._transfers = [transfer0, transfer1]

        await manager.manage_user_tracking()

        manager._user_manager.untrack_user.assert_awaited_once_with(
            'user0', TrackingFlag.TRANSFER
        )

    @pytest.mark.asyncio
    async def test_requestPlaceInQueue(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)
        expected_place = 10

        response = PeerPlaceInQueueReply.Request(DEFAULT_FILENAME, expected_place)
        manager._network.create_peer_response_future = AsyncMock(
            return_value=(None, response))

        place = await manager.request_place_in_queue(transfer)

        manager._network.send_peer_messages.assert_awaited_once_with(
            DEFAULT_USERNAME,
            PeerPlaceInQueueRequest.Request(DEFAULT_FILENAME)
        )
        assert transfer.place_in_queue == expected_place
        assert place == expected_place

    @pytest.mark.asyncio
    async def test_requestPlaceInQueue_failSendingRequest(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)

        manager._network.send_peer_messages = AsyncMock(
            side_effect=ConnectionWriteError('write error'))

        with pytest.raises(RequestPlaceFailedError):
            await manager.request_place_in_queue(transfer)

        manager._network.send_peer_messages.assert_awaited_once_with(
            DEFAULT_USERNAME,
            PeerPlaceInQueueRequest.Request(DEFAULT_FILENAME)
        )

    @pytest.mark.asyncio
    async def test_requestPlaceInQueue_timeoutWaitingForResponse(self, manager: TransferManager):
        transfer = Transfer(DEFAULT_USERNAME, DEFAULT_FILENAME, TransferDirection.DOWNLOAD)

        with pytest.raises(RequestPlaceFailedError):
            with patch('asyncio.wait_for', side_effect=asyncio.TimeoutError()):
                await manager.request_place_in_queue(transfer)

        manager._network.send_peer_messages.assert_awaited_once_with(
            DEFAULT_USERNAME,
            PeerPlaceInQueueRequest.Request(DEFAULT_FILENAME)
        )
