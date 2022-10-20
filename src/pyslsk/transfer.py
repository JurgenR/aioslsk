from __future__ import annotations
from collections import deque
import copy
from dataclasses import dataclass
from enum import auto, Enum
from functools import partial
import hashlib
import logging
import os
import time
import shelve
from typing import Dict, List, Tuple, TYPE_CHECKING

from .configuration import Configuration
from .connection import (
    ConnectionState,
    CloseReason,
    PeerConnection,
    PeerConnectionState,
    PeerConnectionType,
    ProtocolMessage,
)
from .events import (
    build_message_map,
    on_message,
    EventBus,
    ConnectionStateChangedEvent,
    InternalEventBus,
    LoginEvent,
    PeerMessageEvent,
    ServerMessageEvent,
    TransferAddedEvent,
    TransferOffsetEvent,
    TransferTicketEvent,
    TransferDataSentEvent,
    TransferDataReceivedEvent,
)
from .filemanager import FileManager
from .messages import (
    pack_int64,
    pack_int,
    GetUserStatus,
    PeerPlaceInQueueReply,
    PeerPlaceInQueueRequest,
    PeerTransferQueue,
    PeerTransferQueueFailed,
    PeerTransferReply,
    PeerTransferRequest,
    SendUploadSpeed,
    PeerUploadFailed,
)
from .model import UserStatus
from .settings import Settings
from .state import State
from .utils import ticket_generator

if TYPE_CHECKING:
    from .network import Network


logger = logging.getLogger()


SPEED_LOG_INTERVAL = 0.1
SPEED_LOG_ENTRIES = 30


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


@dataclass
class TransferRequest:
    """Class representing a request to start transfering. An object will be
    created when the PeerTransferRequest is sent or received and should be
    destroyed once the transfer ticket has been received or a reply sent that
    the transfer cannot continue.
    """
    ticket: int
    transfer: Transfer


class TransferStorage:
    DEFAULT_FILENAME = 'transfers'

    def __init__(self, data_directory: str):
        self.data_directory = data_directory

    def read_database(self):
        db_path = os.path.join(self.data_directory, self.DEFAULT_FILENAME)

        transfers = []
        with shelve.open(db_path, flag='c') as database:
            for _, transfer in database.items():
                if transfer.is_processing():
                    # Needs to be forced here without using set_state. set_state
                    # explicitly denies a transfer going into queued when it is
                    # already processing
                    transfer.state = TransferState.QUEUED
                    transfer.reset_times()

                    transfers.append(transfers)

        return transfers

    def write_database(self, transfers):
        db_path = os.path.join(self.data_directory, self.DEFAULT_FILENAME)

        with shelve.open(db_path, flag='c') as database:
            # Update/add transfers
            for transfer in transfers:
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
                if not any(transfer.equals(db_transfer) for transfer in transfers):
                    keys_to_delete.append(key)
            for key_to_delete in keys_to_delete:
                database.pop(key_to_delete)


class Transfer:
    """Class representing a transfer"""
    _UNPICKABLE_FIELDS = ('_fileobj', 'connection', '_speed_log')

    def __init__(self, username: str, remote_path: str, direction: TransferDirection, ticket: int = None):
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
        self.last_queue_attempt: float = 0.0

        self.upload_request_attempts: int = 0
        self.last_upload_request_attempt: float = 0.0

        self.start_time: float = None
        """Time at which the transfer was started. This is the time the transfer
        entered the DOWNLOADING or UPLOADING state
        """
        self.complete_time: float = None
        """Time at which the transfer was completed. This is the time the
        transfer entered the complete or incomplete state
        """

        self.connection: PeerConnection = None
        """Connection related to the transfer (connection type 'F')"""
        self._fileobj = None
        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)

    def __setstate__(self, state):
        """Called when unpickling"""
        self.__dict__.update(state)

        self._fileobj = None
        self.connection = None
        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)
        self.ticket = None

    def __getstate__(self):
        """Called when pickling, removes unpickable fields from the fields to
        store
        """
        state = self.__dict__.copy()
        for unpickable_field in self._UNPICKABLE_FIELDS:
            if unpickable_field in state:
                del state[unpickable_field]

        return state

    def increase_queue_attempts(self):
        self.queue_attempts += 1
        self.last_queue_attempt = time.monotonic()

    def increase_upload_request_attempt(self):
        self.upload_request_attempts += 1
        self.last_upload_request_attempt = time.monotonic()

    def set_state(self, state: TransferState):
        # Avoid triggering a state changed if it is already in that state
        if state == self.state:
            return

        if state == TransferState.QUEUED:
            if self.is_processing():
                # Not allowed to queue processing transfers
                return

        elif state == TransferState.INITIALIZING:
            pass

        elif state in (TransferState.DOWNLOADING, TransferState.UPLOADING):
            self.start_time = time.time()
            self.complete_time = None

        elif state == TransferState.ABORTED:
            # Aborting on a complete state does nothing
            # TODO: Not sure what should # happen in case of INITIALIZING
            if self.state in (TransferState.COMPLETE, TransferState.INCOMPLETE, TransferState.ABORTED):
                return
            else:
                self._finalize()

        elif state == TransferState.FAILED:

            if self.state != TransferState.ABORTED:
                self._finalize()

        elif state == TransferState.COMPLETE:
            self._finalize()

        elif state == TransferState.INCOMPLETE:
            if self.state in (TransferState.COMPLETE, TransferState.ABORTED):
                return
            self._finalize()

        logger.debug(f"setting transfer state to {state} : {self!r}")

        self.state = state

    def _finalize(self):
        self.complete_time = time.time()
        self.close_file()
        self.close_connection()
        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)

    def calculate_offset(self) -> int:
        try:
            offset = os.path.getsize(self.local_path)
        except (OSError, TypeError):
            offset = 0

        self._offset = offset
        self.bytes_transfered = offset
        self.bytes_written = offset
        return offset

    def set_offset(self, offset: int):
        self._offset = offset
        self.bytes_transfered = offset

    def reset_times(self):
        self.start_time = None
        self.complete_time = None
        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)

    def get_speed(self) -> float:
        """Retrieve the speed of the transfer

        :return: Zero if the transfer has not yet begun. The current speed if
            the transfer is ongoing. The transfer speed if the transfer was
            complete. Bytes per second
        """
        # Transfer hasn't begun
        if self.start_time is None:
            return 0.0

        # Transfer in progress
        if self.is_transfering():
            if len(self._speed_log) == 0:
                return 0.0

            current_time = time.monotonic()
            bytes_transfered = sum(bytes_sent for _, bytes_sent in self._speed_log)
            oldest_time = self._speed_log[0][0]

            transfer_duration = current_time - oldest_time
            if current_time - oldest_time == 0.0:
                return 0.0

            return bytes_transfered / transfer_duration

        # Transfer complete
        if self.complete_time is None:
            transfer_duration = time.time() - self.start_time
        else:
            transfer_duration = self.complete_time - self.start_time
        if transfer_duration == 0.0:
            return 0.0

        return self.bytes_transfered / transfer_duration

    def add_speed_log_entry(self, bytes_transfered: int):
        current_time = time.monotonic()
        # Create speed log entry
        if len(self._speed_log) == 0:
            self._speed_log.append((current_time, bytes_transfered))
        else:
            if current_time - self._speed_log[-1][0] < SPEED_LOG_INTERVAL:
                last_time_log, last_sent_bytes = self._speed_log.pop()
                self._speed_log.append((last_time_log, bytes_transfered + last_sent_bytes))
            else:
                self._speed_log.append((current_time, bytes_transfered))

    def is_upload(self):
        return self.direction == TransferDirection.UPLOAD

    def is_download(self):
        return self.direction == TransferDirection.DOWNLOAD

    def is_processing(self) -> bool:
        return self.state in (TransferState.DOWNLOADING, TransferState.UPLOADING, TransferState.INITIALIZING, )

    def is_transfering(self) -> bool:
        return self.state in (TransferState.DOWNLOADING, TransferState.UPLOADING, )

    def is_transfered(self) -> bool:
        return self.filesize == self.bytes_transfered

    def read(self, bytes_amount: int) -> bytes:
        """Read the given amount of bytes from the file object"""
        if self._fileobj is None:
            self._fileobj = open(self.local_path, 'rb')

        if self._offset is not None:
            self._fileobj.seek(self._offset)
            self._offset = None

        self._fileobj.seek(self.bytes_transfered)
        data = self._fileobj.read(bytes_amount)
        self.bytes_read += len(data)

        return data

    def write(self, data: bytes) -> bool:
        """Write data to the file object. A file object will be created if it
        does not yet exist and will be closed when the transfer was complete.

        This method updates the internal L{bytes_transfered} and
        L{bytes_written} variables.

        :return: a C{bool} indicating whether the transfer was complete or more
            data is expected
        """
        self.bytes_transfered += len(data)
        if self._fileobj is None:
            self._fileobj = open(self.local_path, 'ab')

        bytes_written = self._fileobj.write(data)
        self.bytes_written += bytes_written

        return self.is_transfered()

    def close_file(self):
        """Closes the local file object in case it is present"""
        if self._fileobj is not None:
            self._fileobj.close()
            self._fileobj = None

    def close_connection(self):
        """Closes the transfer connection in case it is present"""
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
            f"local_path={self.local_path!r}, "
            f"direction={self.direction}, ticket={self.ticket})"
        )


class TransferManager:

    def __init__(
            self, state: State, configuration: Configuration, settings: Settings,
            event_bus: EventBus, internal_event_bus: InternalEventBus,
            file_manager: FileManager, network: Network):
        self._state = state
        self._configuration: Configuration = configuration
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self._ticket_generator = ticket_generator()

        self._file_manager: FileManager = file_manager
        self._network: Network = network

        self._storage: TransferStorage = TransferStorage(self._configuration.data_directory)

        self._transfer_requests: Dict[int, TransferRequest] = {}
        self._transfers: List[Transfer] = []

        self._last_speed_log_time: float = 0.0

        self.MESSAGE_MAP = build_message_map(self)

        self._internal_event_bus.register(ConnectionStateChangedEvent, self._on_connection_state_changed)
        self._internal_event_bus.register(LoginEvent, self._on_server_login)
        self._internal_event_bus.register(PeerMessageEvent, self._on_peer_message)
        self._internal_event_bus.register(ServerMessageEvent, self._on_server_message)
        self._internal_event_bus.register(TransferOffsetEvent, self._on_transfer_offset)
        self._internal_event_bus.register(TransferTicketEvent, self._on_transfer_ticket)
        self._internal_event_bus.register(TransferDataReceivedEvent, self._on_transfer_data_received)
        self._internal_event_bus.register(TransferDataSentEvent, self._on_transfer_data_sent)

    def load_transfers(self):
        transfers = self._storage.read_database()
        for transfer in transfers:
            self.add(transfer)

    def store_transfers(self):
        self._storage.write_database(self._transfers)

    @property
    def transfers(self):
        return self._transfers

    @property
    def upload_slots(self):
        return self._settings.get('sharing.limits.upload_slots')

    # Methods for state changes on the transfers
    def _set_transfer_state(self, transfer: Transfer, state: TransferState, fail_reason: str = None):
        transfer.set_state(state)
        transfer.fail_reason = fail_reason
        self.manage_transfers()

    def incomplete(self, transfer: Transfer):
        self._set_transfer_state(transfer, TransferState.INCOMPLETE)

    def complete(self, transfer: Transfer):
        logger.info(f"completing transfer : {transfer!r}")
        self._set_transfer_state(transfer, TransferState.COMPLETE)

    def abort(self, transfer: Transfer):
        logger.info(f"aborting transfer : {transfer!r}")
        self._set_transfer_state(transfer, TransferState.ABORTED)

    def fail(self, transfer: Transfer, reason: str = None):
        logger.info(f"failing transfer, reason = {reason!r} : {transfer!r}")
        self._set_transfer_state(
            transfer,
            TransferState.FAILED,
            fail_reason=reason
        )

    def uploading(self, transfer: Transfer):
        logger.info(f"uploading starting : {transfer!r}")
        self._set_transfer_state(transfer, TransferState.UPLOADING)
        self._network.upload_rate_limiter.transfer_amount += 1

    def downloading(self, transfer: Transfer):
        logger.info(f"downloading starting : {transfer!r}")
        self._set_transfer_state(transfer, TransferState.DOWNLOADING)
        self._network.download_rate_limiter.transfer_amount += 1

    def queue(self, transfer: Transfer):
        logger.debug(f"queueing transfer : {transfer!r}")
        self._set_transfer_state(transfer, TransferState.QUEUED)

    def add(self, transfer: Transfer) -> Transfer:
        """Adds a transfer if it does not already exist, otherwise it returns
        the already existing transfer.

        This will emit a TransferAddedEvent but only if the transfer did not
        exist. This will also add the user.

        :return: either the transfer we have passed or the already existing
            transfer
        """
        for queued_transfer in self._transfers:
            if queued_transfer.equals(transfer):
                logger.info(f"skip adding transfer, returning existing : {queued_transfer!r}")
                return queued_transfer

        logger.info(f"adding transfer : {transfer!r}")
        self._transfers.append(transfer)
        self._event_bus.emit(TransferAddedEvent(transfer))
        return transfer

    def remove(self, transfer: Transfer):
        """Remove a transfer from the list of transfers. This will attempt to
        abort the transfer.
        """
        try:
            self._transfers.remove(transfer)
        except ValueError:
            return
        else:
            self.abort(transfer)

    def get_uploads(self) -> List[Transfer]:
        return [transfer for transfer in self._transfers if transfer.is_upload()]

    def get_downloads(self) -> List[Transfer]:
        return [transfer for transfer in self._transfers if transfer.is_download()]

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
        return sum(transfer.get_speed() for transfer in self.get_downloading())

    def get_upload_speed(self) -> float:
        """Return current upload speed (in bytes/second)"""
        return sum(transfer.get_speed() for transfer in self.get_uploading())

    def get_average_upload_speed(self) -> float:
        """Returns average upload speed (in bytes/second)"""
        upload_speeds = [
            transfer.get_speed() for transfer in self._transfers
            if transfer.state == TransferState.COMPLETE and transfer.is_upload()
        ]
        if len(upload_speeds) == 0:
            return 0.0
        return sum(upload_speeds) / len(upload_speeds)

    def get_place_in_queue(self, transfer: Transfer) -> int:
        """Gets the place of the given upload in the transfer queue

        :return: The place in the queue, 0 if not in the queue a value equal or
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

    def get_transfer_by_ticket(self, ticket: int) -> Transfer:
        for transfer in self._transfers:
            if transfer.ticket == ticket:
                return transfer
        raise LookupError(f"transfer with ticket {ticket} not found")

    def get_transfer(self, username: str, remote_path: str, direction: TransferDirection) -> Transfer:
        """Lookup transfer by username, remote_path and transfer direction"""
        req_transfer = Transfer(username, remote_path, direction)
        for transfer in self._transfers:
            if transfer.equals(req_transfer):
                return transfer
        raise LookupError(
            f"transfer for user {username} and remote_path {remote_path} (direction={direction}) not found")

    def manage_transfers(self):
        """Manages the transfers. This method analyzes the state of the current
        downloads/uploads and starts them up in case there are free slots
        available
        """
        downloads, uploads = self._get_queued_transfers()
        free_upload_slots = self.get_free_upload_slots()

        for download in downloads:
            self._initialize_download(download)

        for upload in uploads[:free_upload_slots]:
            self._initialize_upload(upload)

    def _get_queued_transfers(self) -> Tuple[List[Transfer], List[Transfer]]:
        queued_downloads = []
        queued_uploads = []
        for transfer in self._transfers:

            if transfer.direction == TransferDirection.UPLOAD:
                if transfer.state == TransferState.QUEUED:
                    queued_uploads.append(transfer)

            else:
                # For downloads we try to continue with incomplete downloads, for
                # uploads it's up to the other user
                if transfer.state in (TransferState.QUEUED, TransferState.INCOMPLETE):
                    queued_downloads.append(transfer)

        return queued_downloads, queued_uploads

    def _request_place_in_queue(self, transfer: Transfer):
        if transfer.state != TransferState.QUEUED:
            logger.debug(
                f"not requesting place in queue, transfer is not in QUEUED state (transfer={transfer!r})")
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
                on_success=partial(self._on_transfer_queue_success, transfer),
                on_failure=partial(self._on_transfer_queue_failed, transfer)
            )
        )

    def _initialize_upload(self, transfer: Transfer):
        logger.debug(f"initializing upload {transfer!r}")
        self._set_transfer_state(transfer, TransferState.INITIALIZING)

        ticket = next(self._ticket_generator)
        request = TransferRequest(ticket, transfer)
        self._transfer_requests[ticket] = request

        self._network.send_peer_messages(
            transfer.username,
            ProtocolMessage(
                PeerTransferRequest.create(
                    TransferDirection.DOWNLOAD.value,
                    ticket,
                    transfer.remote_path,
                    filesize=transfer.filesize
                ),
                on_success=partial(self._on_upload_request_success, transfer),
                on_failure=partial(self._on_upload_request_failed, transfer)
            )
        )

    def complete_transfer_request(self, request: TransferRequest):
        logger.info(f"completing transfer request : {request!r}")
        del self._transfer_requests[request.ticket]

    def fail_transfer_request(self, request: TransferRequest):
        logger.info(f"failing transfer request : {request!r}")
        del self._transfer_requests[request.ticket]

    def _on_transfer_queue_success(self, transfer: Transfer):
        transfer.increase_queue_attempts()

        # Set a job to request the place in queue
        self._state.scheduler.add(
            30,
            self._request_place_in_queue,
            args=[transfer, ],
            times=1
        )

    def _on_transfer_queue_failed(self, transfer: Transfer):
        """Called when we attempted to queue a download but it failed because we
        couldn't deliver the message to the peer (peer was offline,
        connection failed, ...).

        Keep track of how many times this has failed, schedule to request again.
        """
        transfer.increase_queue_attempts()

        # Calculate backoff
        backoff = min(transfer.queue_attempts * 120, 600)
        self._state.scheduler.add(
            backoff,
            self._initialize_download,
            args=[transfer],
            times=1
        )

    def _on_upload_request_failed(self, transfer: Transfer):
        transfer.increase_upload_request_attempt()

        self._set_transfer_state(transfer, TransferState.QUEUED)

    def _on_upload_request_success(self, transfer: Transfer):
        pass

    def _on_connection_state_changed(self, event: ConnectionStateChangedEvent):

        if isinstance(event.connection, PeerConnection):

            if event.state == ConnectionState.CLOSED:
                if event.connection.connection_type == PeerConnectionType.FILE:
                    self._on_transfer_connection_closed(event.connection, close_reason=event.close_reason)

    def _on_server_login(self, event: LoginEvent):
        if event.success:
            self.manage_transfers()

    # Events coming from the connection (connection type 'F')
    def _on_transfer_offset(self, event: TransferOffsetEvent):
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
        self.uploading(transfer)

    def _on_transfer_ticket(self, event: TransferTicketEvent):
        """Called when the transfer ticket has been received. This can only
        occur during download and denotes which transfer is going to be starting
        on this connection. We respond here with the transfer offset after which
        data transfer should start

        :param ticket: ticket number
        :param connection: connection on which the ticket was received
        """
        logger.info(f"got transfer ticket event {event}")
        try:
            request = self._transfer_requests[event.ticket]
            transfer = request.transfer
        except KeyError:
            logger.exception(f"got a ticket for an unknown transfer (ticket={event.ticket})")
            return
        else:
            self.complete_transfer_request(request)

        # We can only know the transfer when we get the ticket. Link them
        # together here
        transfer.connection = event.connection
        event.connection.transfer = transfer

        # Send the offset
        event.connection.queue_messages(
            ProtocolMessage(
                pack_int64(transfer.calculate_offset()),
                on_success=partial(self._on_transfer_offset_sent, event.connection)
            )
        )

    def _on_transfer_offset_sent(self, connection: PeerConnection):
        """Called when the transfer offset has been successfully delivered to
        the peer (download)
        """
        connection.set_connection_state(PeerConnectionState.TRANSFERING)
        self.downloading(connection.transfer)

    def _on_transfer_data_received(self, event: TransferDataReceivedEvent):
        """Called when data has been received in the context of a transfer.
        If the download path hasn't been set yet (ie. it is the first data we
        received for this transfer) it will be determined and data will start to
        be written.
        """
        transfer = event.connection.transfer

        # Set the local download path in case it was not yet set
        if transfer.local_path is None:
            download_path = self._file_manager.get_download_path(transfer.remote_path)
            transfer.local_path = download_path
            logger.info(f"started receiving transfer data, download path : {download_path}")

        transfer.write(event.data)

        transfer.add_speed_log_entry(len(event.data))

        if transfer.is_transfered():
            self.complete(transfer)

    def _on_transfer_data_sent(self, event: TransferDataSentEvent):
        """Called when data was sent to the peer during upload

        :param bytes_sent: amount of bytes sent
        :param connection: connection over which the data was sent
        """
        transfer = event.connection.transfer

        transfer.bytes_transfered += event.bytes_sent

        transfer.add_speed_log_entry(event.bytes_sent)

    def _on_transfer_connection_closed(self, connection: PeerConnection, close_reason: CloseReason = None):
        """Called when a file connection is closed"""
        transfer = connection.transfer
        if transfer is None:
            logger.warning(
                f"couldn't find transfer associated with closed connection (connection={connection!r})")
            return

        if transfer.is_transfered():
            if transfer.is_upload():
                # An upload is only complete when the other side confirms it by
                # closing the connection
                self.complete(transfer)

                self._network.send_server_messages(
                    SendUploadSpeed.create(int(self.get_average_upload_speed()))
                )
        else:
            self.incomplete(transfer)
            if transfer.is_upload():
                # Inform downloader that upload has failed
                self._network.send_peer_messages(
                    transfer.username,
                    PeerUploadFailed.create(transfer.remote_path)
                )

    def _on_peer_message(self, event: PeerMessageEvent):
        message = copy.deepcopy(event.message)
        if message.__class__ in self.MESSAGE_MAP:
            self.MESSAGE_MAP[message.__class__](message, event.connection)

    def _on_server_message(self, event: ServerMessageEvent):
        message = copy.deepcopy(event.message)
        if message.__class__ in self.MESSAGE_MAP:
            self.MESSAGE_MAP[message.__class__](message, event.connection)

    @on_message(GetUserStatus)
    def _on_get_user_status(self, message, connection):
        username, status, _ = message.parse()
        status = UserStatus(status)
        self._state.get_or_create_user(username)
        if status in (UserStatus.ONLINE, UserStatus.AWAY, ):
            # Do something with the users queued uploads
            pass

    @on_message(PeerTransferQueue)
    def _on_peer_transfer_queue(self, message, connection: PeerConnection):
        """The peer is requesting to transfer a file to them or at least put it
        in the queue. This is usually the first message in the transfer process.

        This method will add a new transfer object to the list of transfer but
        will also check if the file actually does exist before putting it in the
        queue.
        """
        filename = message.parse()
        logger.info(f"PeerTransferQueue : {filename}")

        transfer = self.add(
            Transfer(
                username=connection.username,
                remote_path=filename,
                direction=TransferDirection.UPLOAD
            )
        )

        # Check if the shared file exists. Otherwise fail the error
        try:
            shared_item = self._file_manager.get_shared_item(filename)
            transfer.local_path = self._file_manager.resolve_path(shared_item)
            transfer.filesize = self._file_manager.get_filesize(transfer.local_path)
        except LookupError:
            self.fail(transfer, reason="File not shared.")
            self._network.send_peer_messages(
                connection.username,
                PeerTransferQueueFailed.create(filename, transfer.fail_reason),
                connection=connection
            )
        else:
            self.queue(transfer)

    @on_message(PeerTransferRequest)
    def _on_peer_transfer_request(self, message, connection: PeerConnection):
        """The PeerTransferRequest message is sent when the peer is ready to
        transfer the file. The message contains more information about the
        transfer.

        We also handle situations here where the other peer sends this message
        without sending PeerTransferQueue first
        """
        direction, ticket, filename, filesize = message.parse()
        logger.info(f"PeerTransferRequest : {filename} {direction} (filesize={filesize}, ticket={ticket})")

        try:
            transfer = self.get_transfer(
                connection.username, filename, TransferDirection(direction)
            )
        except LookupError:
            transfer = None

        # Make a decision based on what was requested and what we currently have
        # in our queue
        if TransferDirection(direction) == TransferDirection.UPLOAD:
            if transfer is None:
                # Got a request to upload, possibly without prior PeerTransferQueue
                # message. Kindly put it in queue
                transfer = Transfer(
                    connection.username,
                    filename,
                    TransferDirection.UPLOAD
                )
                # Send before queueing: queueing will trigger the transfer
                # manager to re-asses the tranfers and possibly immediatly start
                # the upload
                self._network.send_peer_messages(
                    connection.username,
                    PeerTransferReply.create(ticket, False, reason='Queued'),
                    connection=connection
                )
                transfer = self.add(transfer)
                self.queue(transfer)
            else:
                # The peer is asking us to upload.
                # Possibly needs a check for state here, perhaps:
                # - QUEUED : Queued
                # - ABORTED : Aborted (or Cancelled?)
                # - COMPLETE : Should go back to QUEUED (reset values for transfer)?
                # - INCOMPLETE : Should go back to QUEUED?
                self._network.send_peer_messages(
                    connection.username,
                    PeerTransferReply.create(ticket, False, reason='Queued'),
                    connection=connection
                )

        else:
            # Download
            if transfer is None:
                # A download which we don't have in queue, assume we removed it
                self._network.send_peer_messages(
                    connection.username,
                    PeerTransferReply.create(ticket, False, reason='Cancelled'),
                    connection=connection
                )
            else:
                # All clear to download
                # Possibly needs a check to see if there's any inconsistencies
                # normally we get this response when we were the one requesting
                # to download so ideally all should be fine here.
                request = TransferRequest(ticket, transfer)
                self._transfer_requests[ticket] = request

                transfer.filesize = filesize

                logger.debug(f"PeerTransferRequest : sending PeerTransferReply (ticket={ticket})")
                self._network.send_peer_messages(
                    connection.username,
                    PeerTransferReply.create(ticket, True),
                    connection=connection
                )

    @on_message(PeerTransferReply)
    def _on_peer_transfer_reply(self, message, connection: PeerConnection):
        ticket, allowed, filesize, reason = message.parse()
        logger.info(f"PeerTransferReply : allowed={allowed}, filesize={filesize}, reason={reason!r} (ticket={ticket})")

        try:
            request = self._transfer_requests[ticket]
        except KeyError:
            logger.warning(f"got a ticket for an unknown transfer request (ticket={ticket})")
            return
        else:
            transfer = request.transfer

        if not allowed:
            if reason == 'Queued':
                self.queue(transfer)
            elif reason == 'Complete':
                pass
            else:
                self.fail(transfer, reason=reason)
                self.fail_transfer_request(request)
            return

        # Init the file connection for transfering the file
        self._network.init_peer_connection(
            transfer.username,
            typ=PeerConnectionType.FILE,
            transfer=transfer,
            messages=[pack_int(ticket)],
            on_failure=partial(self._on_file_connection_failed, transfer)
        )

    def _on_file_connection_failed(self, transfer: Transfer, request):
        logger.debug(f"failed to initialize file connection for {transfer!r}")
        self._network.send_peer_messages(
            transfer.username,
            PeerUploadFailed.create(transfer.remote_path)
        )

    @on_message(PeerPlaceInQueueRequest)
    def _on_peer_place_in_queue_request(self, message, connection: PeerConnection):
        filename = message.parse()
        logger.info(f"{message.__class__.__name__}: {filename}")

        try:
            transfer = self.get_transfer(
                connection.username,
                filename,
                TransferDirection.UPLOAD
            )
        except LookupError:
            logger.error(f"PeerPlaceInQueueRequest : could not find transfer (upload) for {filename} from {connection.username}")
        else:
            place = self.get_place_in_queue(transfer)
            if place > 0:
                self._network.send_peer_messages(
                    connection.username,
                    PeerPlaceInQueueReply.create(filename, place),
                    connection=connection
                )

    @on_message(PeerPlaceInQueueReply)
    def _on_peer_place_in_queue_reply(self, message, connection: PeerConnection):
        filename, place = message.parse()
        logger.info(f"{message.__class__.__name__}: filename={filename}, place={place}")

        try:
            transfer = self.get_transfer(
                connection.username,
                filename,
                TransferDirection.DOWNLOAD
            )
        except LookupError:
            logger.error(f"PeerPlaceInQueueReply : could not find transfer (download) for {filename} from {connection.username}")
        else:
            transfer.place_in_queue = place

    @on_message(PeerUploadFailed)
    def _on_peer_upload_failed(self, message, connection: PeerConnection):
        """Called when there is a problem on their end uploading the file. This
        is actually a common message that happens when we close the connection
        before the upload is finished
        """
        filename = message.parse()
        logger.info(f"PeerUploadFailed : upload failed for {filename}")

        try:
            transfer = self.get_transfer(
                connection.username,
                filename,
                TransferDirection.DOWNLOAD
            )
        except LookupError:
            logger.error(f"PeerUploadFailed : could not find transfer (download) for {filename} from {connection.username}")
        else:
            self.fail(transfer)

    @on_message(PeerTransferQueueFailed)
    def _on_peer_transfer_queue_failed(self, message, connection: PeerConnection):
        filename, reason = message.parse()
        logger.info(f"PeerTransferQueueFailed : transfer failed for {filename}, reason={reason}")

        try:
            transfer = self.get_transfer(
                connection.username, filename, TransferDirection.DOWNLOAD)
        except LookupError:
            logger.error(f"PeerTransferQueueFailed : could not find transfer for {filename} from {connection.username}")
        else:
            self.fail(transfer, reason=reason)
