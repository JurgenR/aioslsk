from unittest.mock import MagicMock, Mock, patch

import pytest

from pyslsk.transfer import Transfer, TransferDirection, TransferState, TransferManager
from pyslsk.state import State


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

    def test_whenListenerSet_shouldCallListener(self):
        transfer = Transfer(None, None, TransferDirection.DOWNLOAD)
        listener1 = DummyListener()
        listener2 = DummyListener()
        listener1.on_transfer_state_changed = MagicMock()
        listener2.on_transfer_state_changed = MagicMock()
        transfer.listeners = [listener1, listener2, ]

        new_state = TransferState.FAILED
        transfer.set_state(new_state)

        assert transfer.state == new_state
        listener1.on_transfer_state_changed.assert_called_once_with(transfer, new_state)
        listener2.on_transfer_state_changed.assert_called_once_with(transfer, new_state)


class TestTransferManager:
    DEFAULT_SETTINGS = {
        'sharing': {
            'limits': {
                'download_slots': 2,
                'upload_slots': 2
            }
        },
        'database': {
            'name': 'unittest.db'
        }
    }
    DEFAULT_FILENAME = "myfile.mp3"
    DEFAULT_USERNAME = "username"

    def _create_transfer_manager(self) -> TransferManager:
        return TransferManager(State(), self.DEFAULT_SETTINGS, Mock(), None, Mock())

    def test_whenQueueTransfer_shouldAddTransferAndSetState(self):
        manager = self._create_transfer_manager()

        manager.on_transfer_state_changed = Mock()

        transfer = Transfer(self.DEFAULT_FILENAME, self.DEFAULT_USERNAME, TransferDirection.DOWNLOAD)
        transfer.state = TransferState.VIRGIN

        manager.queue_transfer(transfer)

        assert manager in transfer.listeners
        assert transfer in manager.transfers
        assert transfer.state == TransferState.QUEUED
        manager.on_transfer_state_changed.assert_called_once_with(transfer, TransferState.QUEUED)

    # Speed calculations
    def test_whenGetUploadSpeed_returnsUploadSpeed(self):
        manager = self._create_transfer_manager()

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

    def test_whenGetUploadSpeedAndNothingUploading_returnsZero(self):
        manager = self._create_transfer_manager()

        transfer1 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer1.state = TransferState.DOWNLOADING
        transfer1.get_speed = MagicMock(return_value=1.0)

        manager._transfers = [transfer1, ]

        assert manager.get_upload_speed() == 0.0

    def test_whenGetDownloadSpeed_returnsDownloadSpeed(self):
        manager = self._create_transfer_manager()

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

    def test_whenGetDownloadSpeedAndNothingDownloading_returnsZero(self):
        manager = self._create_transfer_manager()

        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = TransferState.UPLOADING
        transfer1.get_speed = MagicMock(return_value=1.0)

        manager._transfers = [transfer1, ]

        assert manager.get_download_speed() == 0.0

    def test_whenGetAverageUploadSpeed_shouldReturnSpeed(self):
        manager = self._create_transfer_manager()

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

    def test_whenGetAverageUploadSpeedNoCompleteUploads_shouldReturnZero(self):
        manager = self._create_transfer_manager()

        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = TransferState.UPLOADING
        transfer1.get_speed = MagicMock(return_value=100.0)

        manager._transfers = [transfer1, ]

        assert manager.get_average_upload_speed() == 0.0

    # Retrieval of single transfer
    def test_whenGetTransferExists_shouldReturnTransfer(self):
        manager = self._create_transfer_manager()
        transfer = Transfer("myuser", "myfile", TransferDirection.UPLOAD)
        manager._transfers = [transfer, ]

        assert manager.get_transfer("myuser", "myfile", TransferDirection.UPLOAD) == transfer

    def test_whenGetTransferNotExists_shouldRaiseException(self):
        manager = self._create_transfer_manager()
        transfer = Transfer("myuser", "myfile", TransferDirection.UPLOAD)
        manager._transfers = [transfer, ]

        with pytest.raises(LookupError):
            manager.get_transfer("myuser", "myfile", TransferDirection.DOWNLOAD)

        with pytest.raises(LookupError):
            manager.get_transfer("myuser", "mynonfile", TransferDirection.UPLOAD)

        with pytest.raises(LookupError):
            manager.get_transfer("mynonuser", "myfile", TransferDirection.UPLOAD)

    def test_whenGetTransferByTicketExists_shouldReturnTransfer(self):
        ticket = 1
        manager = self._create_transfer_manager()
        transfer = Transfer(None, None, TransferDirection.UPLOAD, ticket=ticket)
        manager._transfers = [transfer, ]

        assert manager.get_transfer_by_ticket(ticket) == transfer

    def test_whenGetTransferByTicketNotExists_shouldRaiseException(self):
        ticket = 1
        manager = self._create_transfer_manager()
        transfer = Transfer(None, None, TransferDirection.UPLOAD, ticket=ticket)
        manager._transfers = [transfer, ]

        with pytest.raises(LookupError):
            manager.get_transfer_by_ticket(2)

    # Retrieval of multiple transfers

    def test_whenGetUploading_shouldReturnUploading(self):
        manager = self._create_transfer_manager()

        transfer0 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer0.state = TransferState.INITIALIZING
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = TransferState.UPLOADING
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer2.state = TransferState.DOWNLOADING
        manager._transfers = [transfer0, transfer1, transfer2, ]

        assert manager.get_uploading() == [transfer0, transfer1, ]

    def test_whenGetDownloading_shouldReturnDownloading(self):
        manager = self._create_transfer_manager()

        transfer0 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer0.state = TransferState.INITIALIZING
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer1.state = TransferState.UPLOADING
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer2.state = TransferState.DOWNLOADING
        manager._transfers = [transfer0, transfer1, transfer2, ]

        assert manager.get_downloading() == [transfer0, transfer2, ]

    def test_whenGetUploads_shouldReturnUploads(self):
        manager = self._create_transfer_manager()
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer3 = Transfer(None, None, TransferDirection.UPLOAD)
        manager._transfers = [transfer1, transfer2, transfer3, ]

        assert manager.get_uploads() == [transfer1, transfer3]

    def test_whenGetDownloads_shouldReturnDownloads(self):
        manager = self._create_transfer_manager()
        transfer1 = Transfer(None, None, TransferDirection.UPLOAD)
        transfer2 = Transfer(None, None, TransferDirection.DOWNLOAD)
        transfer3 = Transfer(None, None, TransferDirection.UPLOAD)
        manager._transfers = [transfer1, transfer2, transfer3, ]

        assert manager.get_downloads() == [transfer2, ]
