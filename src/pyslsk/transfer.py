from __future__ import annotations
import copy
from enum import auto, Enum
from functools import partial
import hashlib
import logging
import os
import time
import shelve
from typing import List, Tuple, TYPE_CHECKING

from .configuration import Configuration
from .connection import (
    ConnectionState,
    CloseReason,
    PeerConnection,
    PeerConnectionState,
    ProtocolMessage,
)
from .events import (
    build_message_map,
    on_message,
    EventBus,
    InternalEventBus,
    ServerMessageEvent,
    TransferAddedEvent,
    TransferOffsetEvent,
    TransferTicketEvent,
    TransferDataSentEvent,
    TransferDataReceivedEvent,
)
from .filemanager import FileManager
from .listeners import TransferListener
from .messages import (
    pack_int64,
    GetUserStatus,
    PeerPlaceInQueueRequest,
    PeerTransferQueue,
    PeerTransferRequest,
    SendUploadSpeed,
    PeerUploadFailed,
)
from .model import UserStatus
from .settings import Settings
from .state import State

if TYPE_CHECKING:
    from .network import Network


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
    _UNPICKABLE_FIELDS = ('_fileobj', 'connection', 'listeners')

    def __init__(self, username: str, remote_path: str, direction: TransferDirection, ticket: int = None, listeners=None):
        self.state = TransferState.VIRGIN

        self.username: str = username
        self.remote_path: str = remote_path
        """Remote path, this is the path that is shared between peers"""
        self.local_path: str = None
        """Absolute path to the file on disk"""
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

        self.bytes_transfered: int = 0
        """Amount of bytes transfered (uploads and downloads)"""
        self.bytes_written: int = 0
        """Amount of bytes written to file (downloads)"""
        self.bytes_read: int = 0
        """Amount of bytes read from file (uploads)"""

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

        self.connection: PeerConnection = None
        """Connection related to the transfer (connection type 'F')"""
        self._fileobj = None
        self.listeners = [] if listeners is None else listeners

    def __setstate__(self, state):
        """Called when unpickling"""
        self.__dict__.update(state)

        self._fileobj = None
        self.listeners = []
        self.connection = None

    def __getstate__(self):
        """Called when pickling, removes unpickable fields from the fields to
        store
        """
        state = self.__dict__.copy()
        for unpickable_field in self._UNPICKABLE_FIELDS:
            del state[unpickable_field]

        return state

    def set_state(self, state: TransferState):
        # Avoid triggering a state changed if it is already in that state
        if state == self.state:
            return

        if state == TransferState.QUEUED:
            pass

        elif state == TransferState.INITIALIZING:
            pass

        elif state in (TransferState.DOWNLOADING, TransferState.UPLOADING):
            self.start_time = time.time()

        elif state == TransferState.ABORTED:
            # Aborting on a complete state does nothing
            if state in (TransferState.COMPLETE, TransferState.INCOMPLETE):
                return
            else:
                self.complete_time = time.time()
                self.close_file()
                self.close_connection()

        elif state == TransferState.FAILED:
            self.complete_time = time.time()
            self.close_file()
            self.close_connection()

        elif state == TransferState.COMPLETE:
            self.complete_time = time.time()
            self.close_file()
            self.close_connection()

        elif state == TransferState.INCOMPLETE:
            self.complete_time = time.time()
            self.close_file()
            self.close_connection()

        # Set state and notify listeners
        self.state = state
        for listener in self.listeners:
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
            self._fileobj = open(self.local_path, 'rb')

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
            self._fileobj = open(self.local_path, 'wb')

        bytes_written = self._fileobj.write(data)
        self.bytes_written += bytes_written

        return self.is_transfered()

    def close_file(self):
        if self._fileobj is not None:
            self._fileobj.close()
            self._fileobj = None

    def close_connection(self):
        if self.connection is not None:
            self.connection.set_state(ConnectionState.SHOULD_CLOSE)
            self.connection = None

    def equals(self, transfer):
        other = (transfer.remote_path, transfer.username, transfer.direction, )
        own = (self.remote_path, self.username, self.direction, )
        return other == own

    def __repr__(self):
        return (
            f"Transfer(username={self.username!r}, remote_path={self.remote_path!r}, "
            f"direction={self.direction}, ticket={self.ticket})"
        )


class TransferManager(TransferListener):

    def __init__(
            self, state: State, configuration: Configuration, settings: Settings,
            event_bus: EventBus, internal_event_bus: InternalEventBus,
            file_manager: FileManager, network: Network):
        self._state = state
        self._configuration: Configuration = configuration
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus

        self._file_manager: FileManager = file_manager
        self._network: Network = network

        self._transfers: List[Transfer] = []

        self.MESSAGE_MAP = build_message_map(self)
        self._internal_event_bus.register(ServerMessageEvent, self.on_server_message)
        self._internal_event_bus.register(TransferOffsetEvent, self.on_transfer_offset)
        self._internal_event_bus.register(TransferTicketEvent, self.on_transfer_ticket)
        self._internal_event_bus.register(TransferDataReceivedEvent, self.on_transfer_data_received)
        self._internal_event_bus.register(TransferDataSentEvent, self.on_transfer_data_sent)

    def read_database(self):
        db_path = os.path.join(self._configuration.data_directory, 'transfers')

        with shelve.open(db_path, flag='cr') as database:
            for _, transfer in database.items():
                if transfer.is_processing():
                    transfer.state = TransferState.QUEUED

                self._transfers.append(transfer)
                self._event_bus.emit(TransferAddedEvent(transfer))

    def write_database(self):
        db_path = os.path.join(self._configuration.data_directory, 'transfers')

        with shelve.open(db_path, flag='rw') as database:
            # Update/add transfers
            for transfer in self._transfers:
                key = hashlib.sha256(
                    (
                        transfer.username +
                        transfer.remote_path +
                        str(transfer.direction.value)
                    ).encode('utf-8')
                ).hexdigest()
                database[key] = transfer

            # Remove non existing transfers
            keys_to_delete = []
            for key, db_transfer in database.items():
                if not any(transfer.equals(db_transfer) for transfer in self._transfers):
                    keys_to_delete.append(key)
            for key_to_delete in keys_to_delete:
                database.pop(key_to_delete)

    @property
    def transfers(self):
        return self._transfers

    @property
    def upload_slots(self):
        return self._settings.get('sharing.limits.upload_slots')

    def abort(self, transfer: Transfer):
        """Abort the given transfer"""
        transfer.set_state(TransferState.ABORTED)

    def remove(self, transfer: Transfer):
        try:
            self._transfers.remove(transfer)
        except ValueError:
            return
        else:
            transfer.abort()

    def get_uploads(self):
        return [
            transfer for transfer in self._transfers
            if transfer.is_upload()
        ]

    def get_downloads(self):
        return [
            transfer for transfer in self._transfers
            if transfer.is_download()
        ]

    def has_slots_free(self) -> bool:
        return self.get_free_upload_slots() > 0

    def get_free_upload_slots(self) -> int:
        uploading_transfers = []
        for transfer in self._transfers:
            if transfer.is_upload() and transfer.is_processing():
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
            if transfer.is_download() and transfer.is_processing()
        ]

    def get_uploading(self) -> List[Transfer]:
        return [
            transfer for transfer in self._transfers
            if transfer.is_upload() and transfer.is_processing()
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
            if transfer.state == TransferState.COMPLETE and transfer.is_upload()
        ]
        if len(upload_speeds) == 0:
            return 0.0
        return sum(upload_speeds) / len(upload_speeds)

    def queue_transfer(self, transfer: Transfer, state: TransferState = TransferState.QUEUED):
        """Queue a transfer or return the existing transfer in case it already
        exists
        """
        logger.info(f"queuing transfer : {transfer!r}")
        for queued_transfer in self._transfers:
            if queued_transfer.equals(transfer):
                return queued_transfer

        self._transfers.append(transfer)
        self._event_bus.emit(TransferAddedEvent(transfer))

        transfer.listeners.append(self)
        if state is not None:
            transfer.set_state(state)

        return transfer

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

    def get_transfer(self, username: str, remote_path: str, direction: TransferDirection) -> Transfer:
        req_transfer = Transfer(username, remote_path, direction)
        for transfer in self._transfers:
            if transfer.equals(req_transfer):
                return transfer
        raise LookupError(
            f"transfer for user {username} and remote_path {remote_path} (direction={direction}) not found")

    def on_transfer_state_changed(self, transfer: Transfer, state: TransferState):
        downloads, uploads = self._get_queued_transfers()
        free_upload_slots = self.get_free_upload_slots()

        for download in downloads:
            if download.queue_attempts == 0:
                self._initialize_download(download)

        for upload in uploads[:free_upload_slots]:
            upload.set_state(TransferState.INITIALIZING)
            self._initialize_upload(upload)

    def on_file_connection_failed(self, transfer: Transfer):
        transfer.fail(reason='Failed')

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
            PeerPlaceInQueueRequest.create(transfer.remote_path)
        )

    def _initialize_download(self, transfer: Transfer):
        logger.debug(f"initializing download {transfer!r}")

        self._network.send_peer_messages(
            transfer.username,
            ProtocolMessage(
                PeerTransferQueue.create(transfer.remote_path),
                on_success=partial(self.on_transfer_queue_success, transfer),
                on_failure=partial(self.on_transfer_queue_failed, transfer)
            )
        )

    def _initialize_upload(self, transfer: Transfer):
        logger.debug(f"initializing upload {transfer!r}")

        self._network.send_peer_messages(
            transfer.username,
            PeerTransferRequest.create(
                TransferDirection.DOWNLOAD.value,
                transfer.ticket,
                transfer.remote_path,
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

    def on_transfer_queue_failed(self, transfer: Transfer):
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

    def on_upload_request_success(self, transfer: Transfer):
        pass

    # Events coming from the connection (connection type 'F')
    def on_transfer_offset(self, event: TransferOffsetEvent):
        """Called when the transfer offset has been received. This can only
        occur during upload and denotes from which offset in the file we need
        to start sending data
        """
        logger.info(f"received transfer offset (offset={event.offset})")

        transfer = event.connection.transfer
        if transfer is None:
            logger.error(f"got a transfer offset for a connection without transfer. connection={event.connection!r}")
            return

        transfer.set_offset(event.offset)
        transfer.filesize = self._file_manager.get_filesize(transfer.local_path)

        event.connection.set_connection_state(PeerConnectionState.TRANSFERING)

    def on_transfer_ticket(self, event: TransferTicketEvent):
        """Called when the transfer ticket has been received. This can only
        occur during download and denotes which transfer is going to be starting
        on this connection.

        @param ticket: ticket number
        @param connection: connection on which the ticket was received
        """
        logger.info(f"got transfer ticket event {event}")
        try:
            transfer = self.get_transfer_by_ticket(event.ticket)
        except LookupError:
            logger.exception(f"got a ticket for a transfer that does not exist (ticket={event.ticket})")
            return

        # We can only know the connection when we get the ticket
        transfer.connection = event.connection
        event.connection.transfer = transfer

        # Send the offset (for now always 0)
        event.connection.queue_messages(
            ProtocolMessage(
                pack_int64(0),
                on_success=partial(event.connection.set_connection_state, PeerConnectionState.TRANSFERING)
            )
        )

    def on_transfer_data_received(self, event: TransferDataReceivedEvent):
        """Called when data has been received in the context of a transfer.
        If the download path hasn't been set yet (ie. it is the first data we
        received for this transfer) it will be determined and data will start to
        be written.
        """
        transfer = self.get_transfer_by_connection(event.connection)

        transfer.set_state(TransferState.DOWNLOADING)

        if transfer.local_path is None:
            download_path = self._file_manager.get_download_path(transfer.remote_path)
            transfer.local_path = download_path
            logger.info(f"started receiving transfer data, download path : {download_path}")

        transfer.write(event.data)

        if transfer.is_transfered():
            logger.info(f"completed downloading of {transfer.remote_path} from {transfer.username} to {transfer.local_path}")
            transfer.set_state(TransferState.COMPLETE)

    def on_transfer_data_sent(self, event: TransferDataSentEvent):
        """Called when data was sent to the peer during upload

        @param bytes_sent: amount of bytes sent
        @param connection: connection over which the data was sent
        """
        transfer = self.get_transfer_by_connection(event.connection)

        transfer.set_state(TransferState.UPLOADING)

        transfer.bytes_transfered += event.bytes_sent

    def on_transfer_connection_closed(self, connection: PeerConnection, close_reason: CloseReason = None):
        """Called when a file connection is closed"""
        transfer = connection.transfer
        if transfer is None:
            logger.warning(
                f"couldn't find transfer associated with closed connection (connection={connection!r})")

        if transfer.is_transfered():
            if transfer.is_upload():
                # An upload is only complete when the other side confirms it by
                # closing the connection
                logger.info(
                    f"completed uploading of {transfer.remote_path} to {transfer.username}. "
                    f"filesize={transfer.filesize}, transfered={transfer.bytes_transfered}, read={transfer.bytes_read}")
                transfer.set_state(TransferState.COMPLETE)

                self._network.send_server_messages(
                    SendUploadSpeed.create(int(self.get_average_upload_speed()))
                )
        else:
            if transfer.is_upload():
                # Inform downloader that upload has failed
                self._network.send_peer_messages(
                    transfer.username,
                    PeerUploadFailed.create(transfer.remote_path)
                )
            transfer.set_state(TransferState.INCOMPLETE)

    def on_server_message(self, event: ServerMessageEvent):
        message = copy.deepcopy(event.message)
        if message.__class__ in self.MESSAGE_MAP:
            self.MESSAGE_MAP[message.__class__](message, event.connection)

    @on_message(GetUserStatus)
    def on_get_user_status(self, message, connection):
        username, status, _ = message.parse()
        status = UserStatus(status)
        user = self._state.get_or_create_user(username)
        if status in (UserStatus.ONLINE, UserStatus.AWAY, ):
            # Do something with the users queued uploads
            pass
