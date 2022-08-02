from __future__ import annotations
from enum import auto, Enum
from functools import partial
from typing import List, Tuple, TYPE_CHECKING
import logging
import time

from .connection import (
    ConnectionState,
    CloseReason,
    PeerConnection,
    PeerConnectionState,
    ProtocolMessage,
)
from .events import on_message
from .filemanager import FileManager
from .listeners import TransferListener
from .messages import (
    pack_int64,
    GetUserStatus,
    PeerPlaceInQueueRequest,
    PeerTransferQueue,
    PeerTransferRequest,
    SendUploadSpeed,
)
from .model import UserStatus
from .state import State

if TYPE_CHECKING:
    from .network import ConnectionRequest, Network


logger = logging.getLogger()


class TransferDirection(Enum):
    UPLOAD = 0
    DOWNLOAD = 1


class TransferState(Enum):
    VIRGIN = auto()
    QUEUED = auto()
    """Transfer is queued and awaiting handling"""
    INITIALIZING = auto()
    """Upload/download is initializing:

    - Download goes into this state when PeerTransferRequest is received
    - Upload goes into this state when we are about to send PeerTransferRequest
      (but doesn't need to be delivered yet)
    """
    INCOMPLETE = auto()
    """Connection was closed during transfer"""
    DOWNLOADING = auto()
    UPLOADING = auto()
    COMPLETE = auto()
    FAILED = auto()
    """Upload/download failed:

    - Download: Other peer rejected the upload for reasons other than 'Queued'
    - Upload: Failure due to for example: file not present, etc...
    """
    ABORTED = auto()
    """Aborted upon user request"""


class Transfer:

    def __init__(self, username: str, filename: str, direction: TransferDirection, ticket: int = None, listeners=None):
        self.state = TransferState.VIRGIN

        self.username: str = username
        self.filename: str = filename
        """Remote filename in case of download, local path in case of upload"""
        self.direction: TransferDirection = direction
        self.place_in_queue: int = None
        """Place in queue, only applicable for downloads"""
        self.fail_reason: str = None

        self.ticket: int = ticket
        self.filesize: int = None
        """Filesize in bytes"""
        self._offset: int = None
        """Offset used for resuming downloads. This offset will be used and
        reset by the L{read} method of this object
        """

        self.target_path: str = None
        """Path to download the file to or upload the file from"""
        self.bytes_transfered: int = 0
        """Amount of bytes transfered"""
        self.bytes_written: int = 0
        """Amount of bytes written to file"""
        self.bytes_read: int = 0
        self.connection: PeerConnection = None
        """Connection related to the transfer (connection type 'F')"""
        self._fileobj = None

        self.queue_attempts: int = 0
        self.last_queue_request: float = 0.0

        self.upload_attempts: int = 0
        self.last_upload_request: float = 0.0

        self.start_time: float = None
        """Time at which the transfer was started. This is the time the transfer
        entered the download or upload state
        """
        self.complete_time: float = None
        """Time at which the transfer was completed. This is the time the
        transfer entered the complete or incomplete state
        """

        self.state_listeners = [] if listeners is None else listeners

    def set_state(self, state: TransferState):
        if state == self.state:
            return

        if self.state == TransferState.COMPLETE and state == TransferState.INCOMPLETE:
            return

        self.state = state

        if state in (TransferState.DOWNLOADING, TransferState.UPLOADING):
            self.start_time = time.time()
        elif state in (TransferState.COMPLETE, TransferState.INCOMPLETE, TransferState.ABORTED):
            self.complete_time = time.time()

        for listener in self.state_listeners:
            listener.on_transfer_state_changed(self, state)

    def set_offset(self, offset: int):
        self._offset = offset
        self.bytes_transfered = offset

    def fail(self, reason: str = None):
        """Sets the internal state to TransferState.FAILED with an optional
        reason for failure
        """
        self.fail_reason = reason
        self.set_state(TransferState.FAILED)

    def get_speed(self) -> float:
        """Retrieve the speed of the transfer

        @return: Zero if the transfer has not yet begun. The current speed if
            the transfer is ongoing. The transfer speed if the transfer was
            complete. Bytes per second
        """
        # Transfer hasn't begun
        if self.start_time is None:
            return 0.0

        # Transfer in progress or complete
        if self.complete_time is None:
            end_time = time.time()
        else:
            end_time = self.complete_time
        transfer_duration = end_time - self.start_time

        if transfer_duration == 0.0:
            return 0.0
        return self.bytes_transfered / transfer_duration

    def is_upload(self):
        return self.direction == TransferDirection.UPLOAD

    def is_download(self):
        return self.direction == TransferDirection.DOWNLOAD

    def is_processing(self) -> bool:
        return self.state in (TransferState.DOWNLOADING, TransferState.UPLOADING, TransferState.INITIALIZING, )

    def is_transfered(self) -> bool:
        return self.filesize == self.bytes_transfered

    def read(self, bytes_amount: int) -> bytes:
        """Read the given amount of bytes from the file object"""
        if self._fileobj is None:
            self._fileobj = open(self.filename, 'rb')

        if self._offset is not None:
            self._fileobj.seek(self._offset)
            self._offset = None

        data = self._fileobj.read(bytes_amount)
        self.bytes_read += len(data)

        return data

    def write(self, data: bytes) -> bool:
        """Write data to the file object. A file object will be created if it
        does not yet exist and will be closed when the transfer was complete.

        This method updates the internal L{bytes_transfered} and
        L{bytes_written} variables.

        @return: a C{bool} indicating whether the transfer was complete or more
            data is expected
        """
        self.bytes_transfered += len(data)
        if self._fileobj is None:
            self._fileobj = open(self.target_path, 'wb')

        bytes_written = self._fileobj.write(data)
        self.bytes_written += bytes_written

        return self.is_transfered()

    def abort(self):
        # Don't bother if the transfer was already completed
        if self.state == TransferState.COMPLETE:
            return

        # Terminate the connection (file-connection)
        if self.connection is not None:
            self.connection.set_state(ConnectionState.SHOULD_CLOSE)
            self.connection = None

        self.set_state(TransferState.ABORTED)

    def complete(self):
        self.set_state(TransferState.COMPLETE)
        self.close()

    def close(self):
        if self._fileobj is not None:
            self._fileobj.close()
            self._fileobj = None

    def equals(self, transfer):
        other = (transfer.filename, transfer.username, transfer.direction, )
        own = (self.filename, self.username, self.direction, )
        return other == own

    def __repr__(self):
        return (
            f"Transfer(username={self.username!r}, filename={self.filename!r}, "
            f"direction={self.direction}, ticket={self.ticket})"
        )


class TransferManager(TransferListener):

    def __init__(self, state: State, settings, file_manager: FileManager, network: Network):
        self._state = state
        self.settings = settings
        self.upload_slots: int = settings['sharing']['limits']['upload_slots']
        self._transfers: List[Transfer] = []

        self._file_manager: FileManager = file_manager
        self._network: Network = network

        self._network.transfer_listener = self
        self._network.server_listeners.append(self)

    @property
    def transfers(self):
        return self._transfers

    def has_slots_free(self) -> bool:
        return self.get_free_upload_slots() > 0

    def get_free_upload_slots(self) -> int:
        """Get the amount of free upload slots"""
        uploading_transfers = []
        for transfer in self._transfers:
            if transfer.direction == TransferDirection.UPLOAD and transfer.is_processing():
                uploading_transfers.append(transfer)

        available_slots = self.upload_slots - len(uploading_transfers)
        return max(0, available_slots)

    def get_queue_size(self) -> int:
        """Returns the amount of queued uploads"""
        return len([
            transfer for transfer in self._transfers
            if transfer.is_upload() and transfer.state == TransferState.QUEUED
        ])

    def get_downloading(self) -> List[Transfer]:
        return [
            transfer for transfer in self._transfers
            if transfer.state == TransferState.DOWNLOADING
        ]

    def get_uploading(self) -> List[Transfer]:
        return [
            transfer for transfer in self._transfers
            if transfer.state == TransferState.UPLOADING
        ]

    def get_download_speed(self) -> float:
        """Return current download speed (in bytes/second)"""
        return sum([
            transfer.get_speed() for transfer in self.get_downloading()
        ])

    def get_upload_speed(self) -> float:
        """Return current upload speed (in bytes/second)"""
        return sum([
            transfer.get_speed() for transfer in self.get_uploading()
        ])

    def get_average_upload_speed(self) -> float:
        """Returns average upload speed (in bytes/second)"""
        upload_speeds = [
            transfer.get_speed() for transfer in self._transfers
            if transfer.state == TransferState.COMPLETE and transfer.direction == TransferDirection.UPLOAD
        ]
        if len(upload_speeds) == 0:
            return 0.0
        return sum(upload_speeds) / len(upload_speeds)

    def queue_download(self, username: str, filename: str) -> Transfer:
        logger.info(f"queueing download from {username} : {filename}")
        transfer = Transfer(
            username=username,
            filename=filename,
            direction=TransferDirection.DOWNLOAD
        )
        self.queue_transfer(transfer)
        return transfer

    def queue_transfer(self, transfer: Transfer, state: TransferState = TransferState.QUEUED):
        """Queue a transfer or return the existing transfer in case it already
        exists
        """
        for queued_transfer in self._transfers:
            if queued_transfer.equals(transfer):
                return queued_transfer

        self._transfers.append(transfer)
        transfer.state_listeners.append(self)
        if state is not None:
            transfer.set_state(state)

    def get_place_in_queue(self, transfer: Transfer) -> int:
        """Gets the place of the given upload in the transfer queue

        @return: The place in the queue, 0 if not in the queue a value equal or
            greater than 1 indicating the position otherwise
        """
        queued_transfers = []
        for queued_transfer in self._transfers:
            if queued_transfer.is_upload() and queued_transfer.state == TransferState.QUEUED:
                queued_transfers.append(queued_transfer)
        try:
            return queued_transfers.index(transfer) + 1
        except ValueError:
            return 0

    def get_transfer_by_connection(self, connection) -> Transfer:
        for transfer in self._transfers:
            if transfer.connection == connection:
                return transfer
        raise LookupError(f"transfer with connection {connection} not found")

    def get_transfer_by_ticket(self, ticket: int) -> Transfer:
        for transfer in self._transfers:
            if transfer.ticket == ticket:
                return transfer
        raise LookupError(f"transfer with ticket {ticket} not found")

    def get_transfer(self, username: str, filename: str, direction: TransferDirection) -> Transfer:
        req_transfer = Transfer(username, filename, direction)
        for transfer in self._transfers:
            if transfer.equals(req_transfer):
                return transfer
        raise LookupError(
            f"transfer for user {username} and filename {filename} (direction={direction}) not found")

    def on_transfer_state_changed(self, transfer: Transfer, state: TransferState):
        downloads, uploads = self._get_queued_transfers()
        free_upload_slots = self.get_free_upload_slots()

        for download in downloads:
            if download.queue_attempts == 0:
                self._initialize_download(download)

        for upload in uploads[:free_upload_slots]:
            upload.set_state(TransferState.INITIALIZING)
            self._initialize_upload(upload)

    def _get_queued_transfers(self) -> Tuple[List[Transfer], List[Transfer]]:
        queued_downloads = []
        queued_uploads = []
        for transfer in self._transfers:
            if not transfer.state == TransferState.QUEUED:
                continue

            if transfer.direction == TransferDirection.UPLOAD:
                queued_uploads.append(transfer)
            else:
                queued_downloads.append(transfer)

        return queued_downloads, queued_uploads

    def _request_place_in_queue(self, transfer: Transfer):
        if transfer.state != TransferState.QUEUED:
            logger.debug(f"not requesting place in queue, transfer is not in QUEUED state (transfer={transfer!r})")
            return

        self._network.send_peer_messages(
            transfer.username,
            PeerPlaceInQueueRequest.create(transfer.filename)
        )

    def _initialize_download(self, transfer: Transfer):
        logger.debug(f"initializing download {transfer!r}")

        self._network.send_peer_messages(
            transfer.username,
            ProtocolMessage(
                PeerTransferQueue.create(transfer.filename),
                on_success=partial(self.on_transfer_queue_success, transfer)
            )
        )

    def _initialize_upload(self, transfer: Transfer):
        logger.debug(f"initializing upload {transfer!r}")

        self._network.send_peer_messages(
            transfer.username,
            PeerTransferRequest.create(
                TransferDirection.DOWNLOAD.value,
                transfer.ticket,
                transfer.filename,
                filesize=transfer.filesize
            )
        )

    def on_transfer_queue_success(self, transfer: Transfer):
        transfer.queue_attempts += 1
        transfer.last_queue_request = time.monotonic()

        # Set a job to request the place in queue
        self._state.scheduler.add(
            30,
            self._request_place_in_queue,
            args=[transfer, ],
            times=1
        )

    def on_transfer_queue_failed(self, transfer: Transfer, connection_request: ConnectionRequest):
        """Called when we attempted to queue a download but it failed because we
        couldn't deliver the message to the peer (peer was offline,
        connection failed, ...).

        Keep track of how many times this has failed, schedule to request again.
        """
        transfer.queue_attempts += 1
        transfer.last_queue_request = time.monotonic()

        # Calculate backoff
        backoff = min(transfer.queue_attempts * 120, 600)
        self._state.scheduler.add(
            backoff,
            self._initialize_download,
            args=[transfer],
            times=1
        )

    def on_upload_request_failed(self, transfer: Transfer):
        transfer.upload_attempts += 1
        transfer.last_upload_request = time.monotonic()

        transfer.set_state(TransferState.QUEUED)

    # Events coming from the connection (connection type 'F')
    def on_transfer_offset(self, offset: int, connection: PeerConnection):
        """Called when the transfer offset has been received. This can only
        occur during upload and denotes from which offset in the file we need
        to start sending data
        """
        logger.info(f"received transfer offset (offset={offset})")

        transfer = connection.transfer
        if transfer is None:
            logger.error(f"got a transfer offset for a connection without transfer. connection={connection!r}")
            return

        transfer.set_offset(offset)
        transfer.filesize = self._file_manager.get_filesize(transfer.filename)

        connection.set_connection_state(PeerConnectionState.TRANSFERING)

    def on_transfer_ticket(self, ticket: int, connection: PeerConnection):
        """Called when the transfer ticket has been received. This can only
        occur during download and denotes which transfer is going to be starting
        on this connection.

        @param ticket: ticket number
        @param connection: connection on which the ticket was received
        """
        logger.info(f"got transfer ticket {ticket} on {connection}")
        try:
            transfer = self.get_transfer_by_ticket(ticket)
        except LookupError:
            logger.exception(f"got a ticket for a transfer that does not exist (ticket={ticket})")
            return

        # We can only know the connection when we get the ticket
        transfer.connection = connection
        connection.transfer = transfer

        # Send the offset (for now always 0)
        connection.queue_message(
            ProtocolMessage(
                pack_int64(0),
                on_success=partial(connection.set_connection_state, PeerConnectionState.TRANSFERING)
            )
        )

    def on_transfer_data_received(self, data: bytes, connection: PeerConnection):
        """Called when data has been received in the context of a transfer.
        If the download path hasn't been set yet (ie. it is the first data we
        received for this transfer) it will be determined and data will start to
        be written.
        """
        transfer = self.get_transfer_by_connection(connection)

        transfer.set_state(TransferState.DOWNLOADING)

        if transfer.target_path is None:
            download_path = self._file_manager.get_download_path(transfer.filename.decode('utf-8'))
            transfer.target_path = download_path
            logger.info(f"started receiving transfer data, download path : {download_path}")

        transfer.write(data)

        if transfer.is_transfered():
            transfer.complete()
            transfer.connection = None
            logger.info(f"completed downloading of {transfer.filename} from {transfer.username} to {transfer.target_path}")
            connection.set_state(ConnectionState.SHOULD_CLOSE)

    def on_transfer_data_sent(self, bytes_sent: int, connection: PeerConnection):
        """Called when data was sent to the peer during upload

        @param bytes_sent: amount of bytes sent
        @param connection: connection over which the data was sent
        """
        transfer = self.get_transfer_by_connection(connection)

        transfer.set_state(TransferState.UPLOADING)

        transfer.bytes_transfered += bytes_sent

    def on_transfer_connection_closed(self, connection: PeerConnection, close_reason: CloseReason = None):
        """Called when a file connection is closed"""
        try:
            transfer = self.get_transfer_by_connection(connection)
        except LookupError:
            logger.warning(
                f"couldn't find transfer associated with closed connection (connection={connection!r})")
        else:
            if transfer.is_transfered():
                if transfer.is_upload():
                    # Complete the upload
                    transfer.complete()
                    transfer.connection = None
                    logger.info(
                        f"completed uploading of {transfer.filename} to {transfer.username}. "
                        f"filesize={transfer.filesize}, transfered={transfer.bytes_transfered}, read={transfer.bytes_read}")

                    # NOT closing connection here, this the responsibility of the
                    # downloading side. Closing here would cause the download to be
                    # incomplete

                    self._network.send_server_messages(
                        SendUploadSpeed.create(int(self.get_average_upload_speed()))
                    )
            else:
                if transfer.state != TransferState.COMPLETE:
                    transfer.set_state(TransferState.INCOMPLETE)

    @on_message(GetUserStatus)
    def on_get_user_status(self, message, connection):
        username, status, _ = message.parse()
        status = UserStatus(status)
        user = self._state.get_or_create_user(username)
        if status in (UserStatus.ONLINE, UserStatus.AWAY, ):
            # Do something with the users queued uploads
            pass
