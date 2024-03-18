import asyncio
import os
from typing import Optional
from unittest.mock import AsyncMock, Mock, MagicMock, patch

import pytest

from aioslsk.exceptions import (
    ConnectionWriteError,
    RequestPlaceFailedError,
    FileNotFoundError,
    FileNotSharedError,
)
from aioslsk.user.model import UserStatus, TrackingFlag
from aioslsk.network.connection import PeerConnection, PeerConnectionType
from aioslsk.protocol.messages import (
    PeerPlaceInQueueRequest,
    PeerPlaceInQueueReply,
    PeerTransferRequest,
    PeerTransferReply,
)
from aioslsk.transfer.cache import TransferShelveCache
from aioslsk.transfer.model import Transfer, TransferDirection
from aioslsk.transfer.manager import Reasons, TransferManager
from aioslsk.transfer.state import (
    AbortedState,
    CompleteState,
    DownloadingState,
    InitializingState,
    QueuedState,
    TransferState,
    UploadingState,
)
from aioslsk.settings import Settings
from aioslsk.shares.model import SharedDirectory, SharedItem
from aioslsk.user.manager import UserManager


FRIEND = 'friend0'
DEFAULT_SETTINGS = {
    'credentials': {'username': 'user0', 'password': 'pass0'},
    'transfers': {
        'limits': {
            'upload_slots': 2
        }
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
        Settings(**DEFAULT_SETTINGS),
        Mock(), # Event bus
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
    shares_manager = Mock()
    shares_manager = AsyncMock()

    return TransferManager(
        Settings(**DEFAULT_SETTINGS),
        event_bus, # event bus
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

    @pytest.mark.parametrize('init_state', [(InitializingState), (UploadingState)])
    def test_getQueuedTransfers_alreadyUploading_shouldNotQueue(
            self, manager: TransferManager, init_state):
        transfer1 = Transfer('user0', 'user/file1', TransferDirection.UPLOAD)
        transfer1.state = init_state(transfer1)
        transfer2 = Transfer('user0', 'user/file2', TransferDirection.UPLOAD)
        transfer2.state = QueuedState(transfer2)
        transfer3 = Transfer('user0', 'user/file3', TransferDirection.UPLOAD)
        transfer3.state = QueuedState(transfer3)
        manager._transfers = [transfer1, transfer2, transfer3]

        _, uploads = manager._get_queued_transfers()

        assert len(uploads) == 0

    def test_getQueuedTransfers_multipleQueued_shouldQueueOnlyOne(self, manager: TransferManager):
        transfer1 = Transfer('user0', None, TransferDirection.UPLOAD)
        transfer1.state = QueuedState(transfer1)
        transfer2 = Transfer('user0', None, TransferDirection.UPLOAD)
        transfer2.state = QueuedState(transfer2)

        transfer3 = Transfer('user1', None, TransferDirection.UPLOAD)
        transfer3.state = QueuedState(transfer3)

        manager._transfers = [transfer1, transfer2, transfer3, ]

        _, uploads = manager._get_queued_transfers()

        # During prioritization the transfers get ranked, the list is reversed
        # to prioritize the uploads. Because both have equal ranking they will
        # be in reversed order
        assert uploads == [transfer3, transfer1]

    def test_prioritizeUploads_userOnline_shouldSortUploads(self, manager: TransferManager):
        USER = 'user0'
        USER2 = 'user1'

        user = manager._user_manager.get_user_object(USER)
        user.status = UserStatus.UNKNOWN
        user2 = manager._user_manager.get_user_object(USER2)
        user2.status = UserStatus.ONLINE

        transfer = Transfer(USER, 'C:\\dir0', TransferDirection.UPLOAD)
        transfer2 = Transfer(USER2, 'C:\\dir0', TransferDirection.UPLOAD)

        assert manager._prioritize_uploads([transfer, transfer2]) == [transfer2, transfer]

    def test_prioritizeUploads_privileged_shouldSortUploads(self, manager: TransferManager):
        USER = 'user0'
        USER2 = 'user1'

        user = manager._user_manager.get_user_object(USER)
        user.privileged = False
        user2 = manager._user_manager.get_user_object(USER2)
        user2.privileged = True

        transfer = Transfer(USER, 'C:\\dir0', TransferDirection.UPLOAD)
        transfer2 = Transfer(USER2, 'C:\\dir0', TransferDirection.UPLOAD)

        assert manager._prioritize_uploads([transfer, transfer2]) == [transfer2, transfer]

    def test_prioritizeUploads_isFriend_shouldSortUploads(self, manager: TransferManager):
        USER = 'user0'
        USER2 = FRIEND

        manager._user_manager.get_user_object(USER)
        manager._user_manager.get_user_object(USER2)

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
            with patch('aioslsk.transfer.manager.atimeout', side_effect=asyncio.TimeoutError()):
                await manager.request_place_in_queue(transfer)

        manager._network.send_peer_messages.assert_awaited_once_with(
            DEFAULT_USERNAME,
            PeerPlaceInQueueRequest.Request(DEFAULT_FILENAME)
        )

    @pytest.mark.asyncio
    async def test_onPeerTransferRequest_nonExistingUpload_shouldQueue(self, manager: TransferManager):
        manager.on_transfer_state_changed = AsyncMock()
        username = 'downloader'
        ticket = 123

        connection = self._create_peer_connection(manager, username)

        shared_item = self._create_shared_item()
        manager._shares_manager.get_shared_item = AsyncMock(return_value=shared_item)

        message = PeerTransferRequest.Request(
            direction=TransferDirection.UPLOAD.value,
            ticket=ticket,
            filename=shared_item.get_remote_path()
        )
        await manager._on_peer_transfer_request(message, connection)

        assert len(manager.transfers) == 1
        upload = manager.transfers[0]
        assert upload.direction == TransferDirection.UPLOAD
        assert upload.local_path == os.path.join(
            shared_item.shared_directory.absolute_path,
            shared_item.subdir,
            shared_item.filename
        )
        assert upload.state.VALUE == TransferState.QUEUED

        connection.send_message.assert_awaited_once_with(
            PeerTransferReply.Request(
                ticket=message.ticket,
                allowed=False,
                reason=Reasons.QUEUED
            )
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state,expected_reason",
        [
            # Possible states with reason response
            (TransferState.ABORTED, Reasons.CANCELLED),
            (TransferState.COMPLETE, Reasons.COMPLETE),
            (TransferState.QUEUED, Reasons.QUEUED),
            # Possible states with no response
            (TransferState.INITIALIZING, None),
            (TransferState.FAILED, None),
            (TransferState.UPLOADING, None),
            # Exotic states that should not be reached
            (TransferState.VIRGIN, None),
            (TransferState.DOWNLOADING, None),
            (TransferState.INCOMPLETE, None),
        ]
    )
    async def test_onPeerTransferRequest_existingUpload_shouldDoNothing(
            self, manager: TransferManager, state: TransferState.State, expected_reason: Optional[str]):
        manager.on_transfer_state_changed = AsyncMock()
        username = 'downloader0'
        ticket = 123

        # Setup peer connection, shared item and transfer mocks
        connection = self._create_peer_connection(manager, username)

        shared_item = self._create_shared_item()
        manager._shares_manager.get_shared_item = AsyncMock(return_value=shared_item)

        self._create_upload(manager, username, state, shared_item)

        # Execute request and verify
        message = PeerTransferRequest.Request(
            direction=TransferDirection.UPLOAD.value,
            ticket=ticket,
            filename=shared_item.get_remote_path()
        )
        await manager._on_peer_transfer_request(message, connection)

        if expected_reason:
            connection.send_message.assert_awaited_once_with(
                PeerTransferReply.Request(
                    ticket=ticket,
                    allowed=False,
                    reason=expected_reason
                )
            )
        else:
            connection.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exception_type", [(FileNotSharedError, FileNotFoundError)]
    )
    async def test_onPeerTransferRequest_nonExistingUpload_fileNotSharedOrFound_shouldDoNothing(
            self, manager: TransferManager, exception_type):
        username = 'downloader0'
        ticket = 123

        # Setup peer connection, shared item and transfer mocks
        connection = self._create_peer_connection(manager, username)

        manager._shares_manager.get_shared_item = AsyncMock(side_effect=exception_type)

        # Execute request and verify
        message = PeerTransferRequest.Request(
            direction=TransferDirection.UPLOAD.value,
            ticket=ticket,
            filename=DEFAULT_FILENAME
        )
        await manager._on_peer_transfer_request(message, connection)

        connection.send_message.assert_awaited_once_with(
            PeerTransferReply.Request(
                ticket=ticket,
                allowed=False,
                reason=Reasons.FILE_NOT_SHARED
            )
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exception_type", [(FileNotSharedError, FileNotFoundError)]
    )
    async def test_onPeerTransferRequest_existingUpload_fileNotSharedOrFound_shouldFailTransfer(
            self, manager: TransferManager, exception_type):
        manager.on_transfer_state_changed = AsyncMock()
        username = 'downloader0'
        ticket = 123

        # Setup peer connection, shared item and transfer mocks
        connection = self._create_peer_connection(manager, username)

        shared_item = self._create_shared_item()
        manager._shares_manager.get_shared_item = AsyncMock(side_effect=exception_type)

        upload = self._create_upload(manager, username, TransferState.QUEUED, shared_item)

        # Execute request and verify
        message = PeerTransferRequest.Request(
            direction=TransferDirection.UPLOAD.value,
            ticket=ticket,
            filename=shared_item.get_remote_path()
        )
        await manager._on_peer_transfer_request(message, connection)

        manager.on_transfer_state_changed.assert_awaited_once_with(
            upload,
            TransferState.QUEUED,
            TransferState.FAILED
        )
        connection.send_message.assert_awaited_once_with(
            PeerTransferReply.Request(
                ticket=ticket,
                allowed=False,
                reason=Reasons.FILE_NOT_SHARED
            )
        )

    @pytest.mark.asyncio
    async def test_onPeerTransferRequest_nonExistingDownload_shouldReplyCancelled(
            self, manager: TransferManager):
        manager.on_transfer_state_changed = AsyncMock()
        username = 'uploader'
        ticket = 123

        # Setup peer connection, shared item and transfer mocks
        connection = self._create_peer_connection(manager, username)

        shared_item = self._create_shared_item()

        # Execute request and verify
        message = PeerTransferRequest.Request(
            direction=TransferDirection.DOWNLOAD.value,
            ticket=ticket,
            filename=shared_item.get_remote_path()
        )
        await manager._on_peer_transfer_request(message, connection)

        connection.send_message.assert_awaited_once_with(
            PeerTransferReply.Request(
                ticket=ticket,
                allowed=False,
                reason=Reasons.CANCELLED
            )
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state,expected_reason",
        [
            # Possible states with reason response
            (TransferState.ABORTED, Reasons.CANCELLED),
            (TransferState.COMPLETE, Reasons.COMPLETE),
            # Possible states with no response
            (TransferState.DOWNLOADING, None),
            (TransferState.INITIALIZING, None),
            # Possible states with no response
            (TransferState.INITIALIZING, None),
        ]
    )
    async def test_onPeerTransferRequest_existingDownload_shouldReply(
            self, manager: TransferManager, state: TransferState.State, expected_reason: Optional[str]):
        manager.on_transfer_state_changed = AsyncMock()
        username = 'uploader'
        ticket = 123

        # Setup peer connection, shared item and transfer mocks
        connection = self._create_peer_connection(manager, username)

        shared_item = self._create_shared_item()
        manager._shares_manager.get_shared_item = AsyncMock(return_value=shared_item)

        self._create_download(manager, username, state, shared_item)

        # Execute request and verify
        message = PeerTransferRequest.Request(
            direction=TransferDirection.DOWNLOAD.value,
            ticket=ticket,
            filename=shared_item.get_remote_path()
        )
        await manager._on_peer_transfer_request(message, connection)

        if expected_reason:
            connection.send_message.assert_awaited_once_with(
                PeerTransferReply.Request(
                    ticket=ticket,
                    allowed=False,
                    reason=expected_reason
                )
            )
        else:
            connection.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state,expected_reason",
        [
            # Possible states with reason response
            (TransferState.ABORTED, Reasons.CANCELLED),
            (TransferState.COMPLETE, Reasons.COMPLETE),
            # Possible states with no response
            (TransferState.DOWNLOADING, None),
            (TransferState.INITIALIZING, None),
            # Possible states with no response
            (TransferState.INITIALIZING, None),
        ]
    )
    async def test_onPeerTransferRequest_existingDownload_shouldReply(
            self, manager: TransferManager, state: TransferState.State, expected_reason: Optional[str]):
        manager.on_transfer_state_changed = AsyncMock()
        username = 'uploader'
        ticket = 123

        # Setup peer connection, shared item and transfer mocks
        connection = self._create_peer_connection(manager, username)

        shared_item = self._create_shared_item()
        manager._shares_manager.get_shared_item = AsyncMock(return_value=shared_item)

        self._create_download(manager, username, state, shared_item)

        # Execute request and verify
        message = PeerTransferRequest.Request(
            direction=TransferDirection.DOWNLOAD.value,
            ticket=ticket,
            filename=shared_item.get_remote_path()
        )
        await manager._on_peer_transfer_request(message, connection)

        if expected_reason:
            connection.send_message.assert_awaited_once_with(
                PeerTransferReply.Request(
                    ticket=ticket,
                    allowed=False,
                    reason=expected_reason
                )
            )
        else:
            connection.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state", [(TransferState.QUEUED), (TransferState.INCOMPLETE)]
    )
    async def test_onPeerTransferRequest_existingDownload_ready_shouldStartDownload(
            self, manager: TransferManager, state: TransferState.State):
        manager.on_transfer_state_changed = AsyncMock()
        username = 'uploader'
        ticket = 123

        # Setup peer connection, shared item and transfer mocks
        connection = self._create_peer_connection(manager, username)

        shared_item = self._create_shared_item()
        manager._shares_manager.get_shared_item = AsyncMock(return_value=shared_item)

        download = self._create_download(manager, username, state, shared_item)

        manager._initialize_download = AsyncMock()

        # Execute request and verify
        message = PeerTransferRequest.Request(
            direction=TransferDirection.DOWNLOAD.value,
            ticket=ticket,
            filename=shared_item.get_remote_path()
        )
        await manager._on_peer_transfer_request(message, connection)

        manager.on_transfer_state_changed.assert_not_awaited()
        manager._initialize_download.assert_called_once_with(
            download, connection, message
        )

    @pytest.mark.asyncio
    async def test_onPeerTransferRequest_existingDownload_fromFailedState_shouldQueueAndStartDownload(
            self, manager: TransferManager):
        manager.on_transfer_state_changed = AsyncMock()
        username = 'uploader'
        ticket = 123

        # Setup peer connection, shared item and transfer mocks
        connection = self._create_peer_connection(manager, username)

        shared_item = self._create_shared_item()
        manager._shares_manager.get_shared_item = AsyncMock(return_value=shared_item)

        download = self._create_download(manager, username, TransferState.FAILED, shared_item)

        manager._initialize_download = AsyncMock()

        # Execute request and verify
        message = PeerTransferRequest.Request(
            direction=TransferDirection.DOWNLOAD.value,
            ticket=ticket,
            filename=shared_item.get_remote_path()
        )
        await manager._on_peer_transfer_request(message, connection)

        manager.on_transfer_state_changed.assert_awaited_once_with(
            download,
            TransferState.FAILED,
            TransferState.QUEUED
        )
        manager._initialize_download.assert_called_once_with(
            download, connection, message
        )

    def _create_upload(
            self, manager: TransferManager, username: str, state: TransferState.State,
            shared_item: SharedItem) -> Transfer:
        return self._create_transfer(
            manager, username, state, shared_item, TransferDirection.UPLOAD)

    def _create_download(
            self, manager: TransferManager, username: str, state: TransferState.State,
            shared_item: SharedItem) -> Transfer:

        return self._create_transfer(
            manager, username, state, shared_item, TransferDirection.DOWNLOAD)

    def _create_transfer(
            self, manager: TransferManager, username: str, state: TransferState.State,
            shared_item: SharedItem, direction: TransferDirection) -> Transfer:
        transfer = Transfer(
            username=username,
            remote_path=shared_item.get_remote_path(),
            direction=direction
        )
        transfer.state = TransferState.init_from_state(state, transfer)
        transfer.state_listeners.append(manager)
        manager._transfers = [transfer, ]
        return transfer

    def _create_peer_connection(self, manager: TransferManager, username: str) -> PeerConnection:
        connection = PeerConnection(
            '1.2.3.4', 1234, manager._network,
            username=username, connection_type=PeerConnectionType.PEER
        )
        connection.send_message = AsyncMock()
        connection.queue_message = Mock()
        return connection

    def _create_shared_item(self) -> SharedItem:
        """Creates a dummy shared item"""
        abs_dir_path = os.path.join('testdir', 'music')
        file_subdir = 'someband'
        shared_directory = SharedDirectory(
            directory='testdir',
            absolute_path=abs_dir_path,
            alias='abcdef'
        )
        return SharedItem(
            shared_directory=shared_directory,
            subdir=file_subdir,
            filename=DEFAULT_FILENAME,
            modified=1.0
        )
