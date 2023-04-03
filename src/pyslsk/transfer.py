from __future__ import annotations
import aiofiles
import asyncio
from collections import deque
from dataclasses import dataclass
from enum import auto, Enum
from functools import partial
import hashlib
import logging
from operator import itemgetter
import os
import time
import shelve
from typing import Dict, List, Tuple, TYPE_CHECKING

from .configuration import Configuration
from .constants import TRANSFER_REPLY_TIMEOUT
from .exceptions import (
    ConnectionReadError,
    ConnectionWriteError,
    FileNotFoundError,
    PeerConnectionError,
)
from .network.connection import (
    CloseReason,
    PeerConnection,
    PeerConnectionState,
    PeerConnectionType,
)
from .events import (
    build_message_map,
    on_message,
    EventBus,
    InternalEventBus,
    MessageReceivedEvent,
    PeerInitializedEvent,
    TransferAddedEvent,
)
from .protocol.primitives import uint32, uint64
from .protocol.messages import (
    AddUser,
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
from .shares import SharesManager
from .state import State
from .utils import task_counter, ticket_generator

if TYPE_CHECKING:
    from .network.network import Network


logger = logging.getLogger(__name__)


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
    REMOTELY_QUEUED = auto()


@dataclass
class TransferRequest:
    """Class representing a request to start transfering. An object will be
    created when the PeerTransferRequest is sent or received and should be
    destroyed once the transfer ticket has been received or a reply sent that
    the transfer cannot continue.

    It completes once the ticket is received or sent on the file connection
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
                    transfer.set_state(TransferState.QUEUED, force=True)

                transfers.append(transfer)

        logger.info(f"read {len(transfers)} transfers from : {db_path}")

        return transfers

    def write_database(self, transfers):
        db_path = os.path.join(self.data_directory, self.DEFAULT_FILENAME)

        logger.info(f"writing {len(transfers)} transfers to : {db_path}")

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
    _UNPICKABLE_FIELDS = ('_speed_log', '_current_task')

    def __init__(self, username: str, remote_path: str, direction: TransferDirection):
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

        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)
        self._current_task: asyncio.Task = None

    def __setstate__(self, state):
        """Called when unpickling"""
        self.__dict__.update(state)
        self._speed_log = deque(maxlen=SPEED_LOG_ENTRIES)
        self._current_task = None

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

    def reset_queue_attempts(self):
        self.queue_attempts = 0
        self.last_queue_attempt = 0.0

    def increase_upload_request_attempt(self):
        self.upload_request_attempts += 1
        self.last_upload_request_attempt = time.monotonic()

    def reset_upload_request_attempt(self):
        self.upload_request_attempts = 0
        self.last_upload_request_attempt = 0.0

    def set_state(self, state: TransferState, force: bool = False):
        """Sets the current state for the transfer. This will do nothing in case
        the transfer is already in that state

        :param state: the new state
        :param force: only used for the QUEUED state, normally we don't allow
            to queue a transfer in case the transfer is processing but in some
            cases it needs to be forced: during loading of transfers from
            storage for transfers who were processing when they were stored or
            if initialization failed (default: False)
        :return: previous state in case state was changed, otherwise None
        """
        if state == self.state:
            return None

        if state == TransferState.QUEUED:
            if force:
                self.reset_times()
            elif self.is_processing():
                # Not allowed to queue processing transfers
                return None

        elif state == TransferState.REMOTELY_QUEUED:
            pass

        elif state == TransferState.INITIALIZING:
            pass

        elif state in (TransferState.DOWNLOADING, TransferState.UPLOADING):
            self.start_time = time.time()
            self.complete_time = None

        elif state == TransferState.ABORTED:
            # Aborting on a complete state does nothing
            # TODO: Not sure what should # happen in case of INITIALIZING
            if self.state in (TransferState.COMPLETE, TransferState.INCOMPLETE, TransferState.ABORTED):
                return None
            else:
                self._finalize()

        elif state == TransferState.FAILED:

            if self.state != TransferState.ABORTED:
                self._finalize()

        elif state == TransferState.COMPLETE:
            self._finalize()

        elif state == TransferState.INCOMPLETE:
            if self.state in (TransferState.COMPLETE, TransferState.ABORTED):
                return None
            self._finalize()

        old_state = state
        self.state = state
        return old_state

    def _finalize(self):
        self.complete_time = time.time()
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

    def get_offset(self) -> int:
        return self._offset

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

    def is_upload(self) -> bool:
        return self.direction == TransferDirection.UPLOAD

    def is_download(self) -> bool:
        return self.direction == TransferDirection.DOWNLOAD

    def is_finalized(self) -> bool:
        return self.state in (TransferState.COMPLETE, TransferState.ABORTED, TransferState.FAILED)

    def is_processing(self) -> bool:
        return self.state in (TransferState.DOWNLOADING, TransferState.UPLOADING, TransferState.INITIALIZING, )

    def is_transfering(self) -> bool:
        return self.state in (TransferState.DOWNLOADING, TransferState.UPLOADING, )

    def is_transfered(self) -> bool:
        return self.filesize == self.bytes_transfered

    def equals(self, transfer):
        other = (transfer.remote_path, transfer.username, transfer.direction, )
        own = (self.remote_path, self.username, self.direction, )
        return other == own

    def _queue_remotely_task_complete(self, task: asyncio.Task):
        self._current_task = None
        # try:
        #     task.result()
        # except asyncio.CancelledError:
        #     pass
        # except Exception as exc:
        #     logger.warning(f"uploading failed : {self!r}")
        #     self.upload_request_attempts += 1
        # else:
        #     self.upload_request_attempts = 0
        #     self.last_upload_request_attempt = 0.0

    def _upload_task_complete(self, task: asyncio.Task):
        self._current_task = None

    def _download_task_complete(self, task: asyncio.Task):
        self._current_task = None

    def __repr__(self):
        return (
            f"Transfer(username={self.username!r}, remote_path={self.remote_path!r}, "
            f"local_path={self.local_path!r}, direction={self.direction}, "
            f"state={self.state}, _current_task={self._current_task!r})"
        )


class TransferManager:

    def __init__(
            self, state: State, configuration: Configuration, settings: Settings,
            event_bus: EventBus, internal_event_bus: InternalEventBus,
            shares_manager: SharesManager, network: Network):
        self._state = state
        self._configuration: Configuration = configuration
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self._ticket_generator = ticket_generator()

        self._shares_manager: SharesManager = shares_manager
        self._network: Network = network

        self._storage: TransferStorage = TransferStorage(self._configuration.data_directory)

        self._transfer_requests: Dict[int, TransferRequest] = {}
        self._transfers: List[Transfer] = []

        self.MESSAGE_MAP = build_message_map(self)

        self._internal_event_bus.register(MessageReceivedEvent, self._on_message_received)
        self._internal_event_bus.register(PeerInitializedEvent, self._on_peer_initialized)

    async def read_transfers_from_storage(self) -> List[Transfer]:
        transfers = self._storage.read_database()
        for transfer in transfers:
            await self.add(transfer)

    def write_transfers_to_storage(self):
        self._storage.write_database(self._transfers)

    @property
    def transfers(self):
        return self._transfers

    @property
    def upload_slots(self):
        return self._settings.get('sharing.limits.upload_slots')

    # Methods for state changes on the transfers
    async def _set_transfer_state(
            self, transfer: Transfer, state: TransferState,
            fail_reason: str = None, force: bool = False):
        logger.info(
            f"setting transfer state to {state} (fail_reason={fail_reason} : {transfer})")

        transfer.set_state(state, force=force)
        transfer.fail_reason = fail_reason
        await self.manage_transfers()

    async def incomplete(self, transfer: Transfer):
        await self._set_transfer_state(transfer, TransferState.INCOMPLETE)

    async def complete(self, transfer: Transfer):
        await self._set_transfer_state(transfer, TransferState.COMPLETE)

    async def abort(self, transfer: Transfer):
        await self._set_transfer_state(transfer, TransferState.ABORTED)

    async def fail(self, transfer: Transfer, reason: str = None):
        await self._set_transfer_state(
            transfer,
            TransferState.FAILED,
            fail_reason=reason
        )

    async def uploading(self, transfer: Transfer):
        await self._set_transfer_state(transfer, TransferState.UPLOADING)
        self._network.upload_rate_limiter.transfer_amount += 1

    async def downloading(self, transfer: Transfer):
        await self._set_transfer_state(transfer, TransferState.DOWNLOADING)
        self._network.download_rate_limiter.transfer_amount += 1

    async def queue(self, transfer: Transfer, force: bool = False):
        await self._set_transfer_state(transfer, TransferState.QUEUED, force=force)
        await self._network.send_server_messages(
            AddUser.Request(transfer.username)
        )

    async def remotely_queue(self, transfer: Transfer):
        await self._set_transfer_state(transfer, TransferState.REMOTELY_QUEUED)

    async def add(self, transfer: Transfer) -> Transfer:
        """Adds a transfer if it does not already exist, otherwise it returns
        the already existing transfer.

        This method will emit a `TransferAddedEvent` only if the transfer did
        not exist and will also perform an `AddUser` command on the server in
        case the transfer isn't finalized yet

        :return: either the transfer we have passed or the already existing
            transfer
        """
        for queued_transfer in self._transfers:
            if queued_transfer.equals(transfer):
                logger.info(f"skip adding transfer, returning existing : {queued_transfer!r}")
                return queued_transfer

        if not transfer.is_finalized():
            await self._network.send_server_messages(
                AddUser.Request(transfer.username)
            )

        logger.info(f"adding transfer : {transfer!r}")
        self._transfers.append(transfer)
        await self._event_bus.emit(TransferAddedEvent(transfer))
        return transfer

    async def remove(self, transfer: Transfer):
        """Remove a transfer from the list of transfers. This will attempt to
        abort the transfer.
        """
        try:
            self._transfers.remove(transfer)
        except ValueError:
            return
        else:
            await self.abort(transfer)

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

    async def get_place_in_queue(self, transfer: Transfer) -> int:
        """Gets the place of the given upload in the transfer queue

        :return: The place in the queue, 0 if not in the queue a value equal or
            greater than 1 indicating the position otherwise
        """
        _, uploads = await self._get_queued_transfers()
        try:
            return uploads.index(transfer)
        except ValueError:
            return 0

    def get_transfer(self, username: str, remote_path: str, direction: TransferDirection) -> Transfer:
        """Lookup transfer by username, remote_path and transfer direction"""
        req_transfer = Transfer(username, remote_path, direction)
        for transfer in self._transfers:
            if transfer.equals(req_transfer):
                return transfer
        raise LookupError(
            f"transfer for user {username} and remote_path {remote_path} (direction={direction}) not found")

    async def manage_transfers(self):
        """Manages the transfers. This method analyzes the state of the current
        downloads/uploads and starts them up in case there are free slots
        available
        """
        for transfer in self._transfers:
            if transfer.state == TransferState.QUEUED and transfer.direction == TransferDirection.DOWNLOAD:
                # import pdb; pdb.set_trace()
                pass

        downloads, uploads = await self._get_queued_transfers()
        free_upload_slots = self.get_free_upload_slots()

        # Downloads will just get remotely queued
        # logger.debug(f"downloads to queue remotely : {downloads!r}")
        # logger.debug(f"uploads to start : {uploads!r}")
        for download in downloads:
            if not download._current_task:
                download._current_task = asyncio.create_task(
                    self._queue_remotely(download),
                    name=f'queue-remotely-{task_counter()}'
                )
                download._current_task.add_done_callback(transfer._queue_remotely_task_complete)

        for upload in uploads[:free_upload_slots]:
            if not upload._current_task:
                upload._current_task = asyncio.create_task(
                    self._initialize_upload(upload),
                    name=f'initialize-upload-{task_counter()}'
                )
                upload._current_task.add_done_callback(upload._upload_task_complete)

    async def _get_queued_transfers(self) -> Tuple[List[Transfer], List[Transfer]]:
        """Returns all transfers eligeble for being initialized"""
        queued_downloads = []
        queued_uploads = []
        for transfer in self._transfers:
            user = self._state.get_or_create_user(transfer.username)
            if user.status == UserStatus.OFFLINE:
                continue

            if transfer.direction == TransferDirection.UPLOAD:
                if transfer.state == TransferState.QUEUED:
                    queued_uploads.append(transfer)

            else:
                # For downloads we try to continue with incomplete downloads,
                # for uploads it's up to the other user
                if transfer.state in (TransferState.QUEUED, TransferState.INCOMPLETE):
                    queued_downloads.append(transfer)

        queued_uploads = self._rank_queued_uploads(queued_uploads)

        return queued_downloads, queued_uploads

    def _rank_queued_uploads(self, uploads: List[Transfer]) -> List[Transfer]:
        """Ranks the queued uploads based on certain parameters"""
        friends = self._settings.get('users.friends')

        ranking = []
        for upload in uploads:
            user = self._state.get_or_create_user(upload.username)

            rank = 0
            # Rank UNKNOWN status lower, OFFLINE should be blocked
            if user.status in (UserStatus.ONLINE, UserStatus.AWAY):
                rank += 1

            if upload.username in friends:
                rank += 5

            if user.privileged:
                rank += 10

            ranking.append((rank, upload))

        ranking.sort(key=itemgetter(0))
        return list(reversed([upload for _, upload in ranking]))

    async def _queue_remotely(self, transfer: Transfer):
        """Remotely queue the given transfer. If the message was successfully
        delivered the transfer will go in REMOTELY_QUEUED state. Otherwise the
        transfer will remain in QUEUED state
        """
        logger.debug(f"attempting to queue transfer remotely : {transfer!r}")
        try:
            await self._network.send_peer_messages(
                transfer.username,
                PeerTransferQueue.Request(transfer.remote_path)
            )

        except (ConnectionWriteError, PeerConnectionError) as exc:
            logger.debug(f"failed to queue transfer remotely : {transfer!r} : {exc!r}")
            transfer.increase_queue_attempts()
            await self.queue(transfer)

        else:
            transfer.reset_queue_attempts()
            await self.remotely_queue(transfer)

    async def _request_place_in_queue(self, transfer: Transfer):
        await self._network.queue_peer_messages(
            transfer.username,
            PeerPlaceInQueueRequest.Request(transfer.remote_path)
        )

    async def _initialize_upload(self, transfer: Transfer):
        logger.debug(f"initializing upload {transfer!r}")
        await self._set_transfer_state(transfer, TransferState.INITIALIZING)

        ticket = next(self._ticket_generator)

        try:
            await self._network.send_peer_messages(
                transfer.username,
                PeerTransferRequest.Request(
                    TransferDirection.DOWNLOAD.value,
                    ticket,
                    transfer.remote_path,
                    filesize=transfer.filesize
                )
            )

        except (ConnectionWriteError, PeerConnectionError) as exc:
            logger.debug(f"failed to send request to upload : {transfer!r} : {exc!r}")
            await self.queue(transfer, force=True)
            return

        try:
            connection, response = await asyncio.wait_for(
                self._network.wait_for_peer_message(
                    transfer.username,
                    PeerTransferReply.Request,
                    ticket=ticket
                ),
                TRANSFER_REPLY_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.debug(f"timeout waiting for transfer reply : {transfer!r}")
            await self.queue(transfer, force=True)
            return

        if not response.allowed:
            await self.fail(transfer, reason=response.reason)
            return

        try:
            connection = await self._network.create_peer_connection(
                transfer.username,
                PeerConnectionType.FILE,
                initial_state=PeerConnectionState.AWAITING_OFFSET
            )

        except PeerConnectionError:
            logger.info(f"failed to create peer connection for transfer : {transfer!r}")
            await self.queue(transfer)
            return

        # Send transfer ticket
        try:
            await connection.send_message(uint32.serialize(ticket))
        except ConnectionWriteError:
            logger.info(f"failed to send transfer ticket : {transfer!r}")
            await self.queue(transfer)
            return

        connection.set_connection_state(PeerConnectionState.AWAITING_OFFSET)

        # Receive transfer offset
        try:
            offset = await connection.receive_transfer_offset()
        except ConnectionReadError:
            logger.info(f"failed to receive transfer offset : {transfer!r}")
            await self.queue(transfer)
            return

        else:
            logger.debug(f"received offset {offset} for transfer : {transfer!r}")
            transfer.set_offset(offset)

        await self._upload_file(transfer, connection)

        # Send transfer speed
        await self._network.queue_server_messages(
            SendUploadSpeed.Request(int(self.get_average_upload_speed()))
        )

    async def _upload_file(self, transfer: Transfer, connection: PeerConnection):
        """Uploads the transfer over the connection. This method will set the
        appropriate states on the passed `transfer` and `connection` objects.

        :param transfer: `Transfer` object
        :param connection: connection on which file should be sent
        """
        connection.set_connection_state(PeerConnectionState.TRANSFERING)
        await self.uploading(transfer)
        try:
            async with aiofiles.open(transfer.local_path, 'rb') as handle:
                await handle.seek(transfer.get_offset())
                await connection.send_file(
                    handle,
                    partial(self._upload_progress_callback, transfer)
                )

        except OSError:
            logger.exception(f"error opening on local file : {transfer.local_path}")
            await self.fail(transfer)
            await connection.disconnect(CloseReason.REQUESTED)

        except ConnectionWriteError:
            logger.exception(f"error writing to socket : {transfer!r}")
            await self.fail(transfer)
            await self._network.queue_peer_messages(
                PeerUploadFailed.Request(transfer.remote_path)
            )
        else:
            await connection.receive_until_eof(raise_exception=False)
            if transfer.is_transfered():
                await self.complete(transfer)
            else:
                await self.fail(transfer)

    async def _download_file(self, transfer: Transfer, connection: PeerConnection):
        """Downloads the transfer over the connection. This method will set the
        appropriate states on the passed `transfer` and `connection` objects.

        :param transfer: `Transfer` object
        :param connection: connection on which file should be received
        """
        connection.set_connection_state(PeerConnectionState.TRANSFERING)
        await self.downloading(transfer)
        try:
            async with aiofiles.open(transfer.local_path, 'ab') as handle:
                await connection.receive_file(
                    handle,
                    transfer.filesize - transfer._offset,
                    partial(self._download_progress_callback, transfer)
                )

        except OSError:
            logger.exception(f"error opening on local file : {transfer.local_path}")
            await connection.disconnect(CloseReason.REQUESTED)
            await self.fail(transfer)

        except ConnectionReadError:
            logger.exception(f"error reading from socket : {transfer:!r}")
            await self.incomplete(transfer)

        else:
            await connection.disconnect(CloseReason.REQUESTED)
            if transfer.is_transfered():
                await self.complete(transfer)
            else:
                await self.incomplete(transfer)

    def _upload_progress_callback(self, transfer: Transfer, data: bytes):
        transfer.bytes_transfered += len(data)
        transfer.add_speed_log_entry(len(data))

    def _download_progress_callback(self, transfer: Transfer, data: bytes):
        transfer.bytes_transfered += len(data)
        transfer.add_speed_log_entry(len(data))

    async def _handle_incoming_file_connection(self, connection: PeerConnection):
        """Called only when a file connection was opened with PeerInit. Usually
        this means the other peer attempting to upload a file but a request to
        upload to the other peer is also handled here.

        This method handles:
        * receiving the ticket
        * calculating and sending the file offset
        * downloading/uploading

        The received `ticket` must be present in the `_transfer_requests` (a
        `PeerTransferRequest` must have preceded the opening of the connection)
        """
        # Wait for the transfer ticket
        try:
            ticket = await connection.receive_transfer_ticket()
        except ConnectionReadError:
            logger.warning(f"failed to receive transfer ticket on file connection : {connection.hostname}:{connection.port}")
            await connection.disconnect(CloseReason.REQUESTED)
            return

        # Get the transfer from the transfer requests
        try:
            transfer = self._transfer_requests.pop(ticket).transfer
        except KeyError:
            logger.warning(f"file connection sent unknown transfer ticket: {ticket!r}")
            return
        else:
            transfer._current_task = asyncio.current_task()
            transfer._current_task.add_done_callback(
                transfer._download_task_complete)
            await self._set_transfer_state(transfer, TransferState.INITIALIZING)

        # Calculate and send the file offset
        offset = transfer.calculate_offset()
        try:
            await connection.send_message(uint64(offset).serialize())
        except ConnectionWriteError:
            logger.warning(f"failed to send offset: {transfer!r}")
            await self.incomplete(transfer)
            return

        # Start transfer
        if transfer.direction == TransferDirection.DOWNLOAD:
            await self._download_file(transfer, connection)
        else:
            await self._upload_file(transfer, connection)

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self.MESSAGE_MAP:
            await self.MESSAGE_MAP[message.__class__](message, event.connection)

    @on_message(AddUser.Response)
    async def _on_add_user(self, message: AddUser.Response, connection: PeerConnection):
        await self.manage_transfers()

    @on_message(GetUserStatus.Response)
    async def _on_get_user_status(self, message: GetUserStatus.Response, connection: PeerConnection):
        await self.manage_transfers()

    @on_message(PeerTransferQueue.Request)
    async def _on_peer_transfer_queue(self, message: PeerTransferQueue.Request, connection: PeerConnection):
        """The peer is requesting to transfer a file to them or at least put it
        in the queue. This is usually the first message in the transfer process.

        This method will add a new transfer object to the list of transfer but
        will also check if the file actually does exist before putting it in the
        queue.
        """
        logger.info(f"PeerTransferQueue : {message.filename}")

        transfer = await self.add(
            Transfer(
                username=connection.username,
                remote_path=message.filename,
                direction=TransferDirection.UPLOAD
            )
        )

        # Check if the shared file exists
        try:
            shared_item = self._shares_manager.get_shared_item(message.filename)
            transfer.local_path = shared_item.get_absolute_path()
            transfer.filesize = self._shares_manager.get_filesize(shared_item)
        except FileNotFoundError:
            await self.fail(transfer, reason="File not shared.")
            await connection.queue_message(
                PeerTransferQueueFailed.Request(
                    filename=message.filename,
                    reason=transfer.fail_reason
                )
            )
        else:
            await self.queue(transfer)

    async def _on_peer_initialized(self, event: PeerInitializedEvent):
        """Handle incoming file connections that we did not request"""
        if event.connection.connection_type == PeerConnectionType.FILE:
            if not event.requested:
                asyncio.create_task(
                    self._handle_incoming_file_connection(event.connection),
                    name=f'incoming-file-connection-task-{task_counter()}'
                )

    @on_message(PeerTransferRequest.Request)
    async def _on_peer_transfer_request(self, message: PeerTransferRequest.Request, connection: PeerConnection):
        """The PeerTransferRequest message is sent when the peer is ready to
        transfer the file. The message contains more information about the
        transfer.

        We also handle situations here where the other peer sends this message
        without sending PeerTransferQueue first
        """
        try:
            transfer = self.get_transfer(
                connection.username, message.filename, TransferDirection(message.direction)
            )
        except LookupError:
            transfer = None

        # Make a decision based on what was requested and what we currently have
        # in our queue
        if TransferDirection(message.direction) == TransferDirection.UPLOAD:
            if transfer is None:
                # Got a request to upload, possibly without prior PeerTransferQueue
                # message. Kindly put it in queue
                transfer = Transfer(
                    connection.username,
                    message.filename,
                    TransferDirection.UPLOAD
                )
                # Send before queueing: queueing will trigger the transfer
                # manager to re-asses the tranfers and possibly immediatly start
                # the upload
                await connection.queue_message(
                    PeerTransferReply.Request(
                        ticket=message.ticket,
                        allowed=False,
                        reason='Queued'
                    )
                )
                transfer = await self.add(transfer)
                await self.queue(transfer)
            else:
                # The peer is asking us to upload.
                # Possibly needs a check for state here, perhaps:
                # - QUEUED : Queued
                # - ABORTED : Aborted (or Cancelled?)
                # - COMPLETE : Should go back to QUEUED (reset values for transfer)?
                # - INCOMPLETE : Should go back to QUEUED?
                await connection.queue_message(
                    PeerTransferReply.Request(
                        ticket=message.ticket,
                        allowed=False,
                        reason='Queued'
                    )
                )

        else:
            # Download
            if transfer is None:
                # A download which we don't have in queue, assume we removed it
                await connection.queue_message(
                    PeerTransferReply.Request(
                        ticket=message.ticket,
                        allowed=False,
                        reason='Cancelled'
                    )
                )
            else:
                # All clear to download
                # Possibly needs a check to see if there's any inconsistencies
                # normally we get this response when we were the one requesting
                # to download so ideally all should be fine here.
                request = TransferRequest(message.ticket, transfer)
                self._transfer_requests[message.ticket] = request

                transfer.filesize = message.filesize
                if transfer.local_path is None:
                    download_path = self._shares_manager.get_download_path(transfer.remote_path)
                    transfer.local_path = download_path

                await connection.queue_message(
                    PeerTransferReply.Request(
                        ticket=message.ticket,
                        allowed=True
                    )
                )

    # @on_message(PeerTransferReply.Request)
    # async def _on_peer_transfer_reply(self, message: PeerTransferReply.Request, connection: PeerConnection):
    #     try:
    #         request = self._transfer_requests[message.ticket]
    #     except KeyError:
    #         logger.warning(f"got a ticket for an unknown transfer request (ticket={message.ticket})")
    #         return
    #     else:
    #         transfer = request.transfer

    #     if not message.allowed:
    #         if message.reason == 'Queued':
    #             self.queue(transfer)
    #         elif message.reason == 'Complete':
    #             pass
    #         else:
    #             self.fail(transfer, reason=message.reason)
    #             self._fail_transfer_request(request)
    #         return

    @on_message(PeerPlaceInQueueRequest.Request)
    async def _on_peer_place_in_queue_request(self, message: PeerPlaceInQueueRequest.Request, connection: PeerConnection):
        filename = message.filename
        try:
            transfer = self.get_transfer(
                connection.username,
                filename,
                TransferDirection.UPLOAD
            )
        except LookupError:
            logger.error(f"PeerPlaceInQueueRequest : could not find transfer (upload) for {filename} from {connection.username}")
        else:
            place = await self.get_place_in_queue(transfer)
            if place:
                await connection.queue_message(
                    PeerPlaceInQueueReply.Request(filename, place))

    @on_message(PeerPlaceInQueueReply.Request)
    async def _on_peer_place_in_queue_reply(self, message: PeerPlaceInQueueReply.Request, connection: PeerConnection):
        try:
            transfer = self.get_transfer(
                connection.username,
                message.filename,
                TransferDirection.DOWNLOAD
            )
        except LookupError:
            logger.error(f"PeerPlaceInQueueReply : could not find transfer (download) for {message.filename} from {connection.username}")
        else:
            transfer.place_in_queue = message.place

    @on_message(PeerUploadFailed.Request)
    async def _on_peer_upload_failed(self, message: PeerUploadFailed.Request, connection: PeerConnection):
        """Called when there is a problem on their end uploading the file. This
        is actually a common message that happens when we close the connection
        before the upload is finished
        """
        try:
            transfer = self.get_transfer(
                connection.username,
                message.filename,
                TransferDirection.DOWNLOAD
            )
        except LookupError:
            logger.error(f"PeerUploadFailed : could not find transfer (download) for {message.filename} from {connection.username}")
        else:
            await self.fail(transfer)

    @on_message(PeerTransferQueueFailed.Request)
    async def _on_peer_transfer_queue_failed(self, message: PeerTransferQueueFailed.Request, connection: PeerConnection):
        filename = message.filename
        reason = message.reason
        try:
            transfer = self.get_transfer(
                connection.username, filename, TransferDirection.DOWNLOAD)
        except LookupError:
            logger.error(f"PeerTransferQueueFailed : could not find transfer for {filename} from {connection.username}")
        else:
            await self.fail(transfer, reason=reason)
