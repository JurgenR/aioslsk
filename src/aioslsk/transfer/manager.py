from __future__ import annotations
import aiofiles
from aiofiles import os as asyncos
import asyncio
from async_timeout import timeout as atimeout
import logging
from operator import itemgetter
import os
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from ..base_manager import BaseManager
from .cache import TransferNullCache, TransferCache
from ..constants import TRANSFER_REPLY_TIMEOUT
from ..exceptions import (
    AioSlskException,
    ConnectionReadError,
    ConnectionWriteError,
    FileNotFoundError,
    FileNotSharedError,
    InvalidStateTransition,
    PeerConnectionError,
    RequestPlaceFailedError,
    TransferNotFoundError,
)
from ..network.connection import (
    CloseReason,
    PeerConnection,
    PeerConnectionState,
    PeerConnectionType,
)
from ..events import (
    build_message_map,
    on_message,
    EventBus,
    MessageReceivedEvent,
    PeerInitializedEvent,
    SessionInitializedEvent,
    TransferAddedEvent,
    TransferProgressEvent,
    TransferRemovedEvent,
)
from ..protocol.primitives import uint32, uint64
from ..protocol.messages import (
    AddUser,
    GetUserStatus,
    PeerPlaceInQueueReply,
    PeerPlaceInQueueRequest,
    PeerTransferQueue,
    PeerTransferQueueFailed,
    PeerTransferReply,
    PeerTransferRequest,
    PeerUploadFailed,
    SendUploadSpeed,
)
from .model import Transfer, TransferDirection
from .state import TransferState
from ..user.model import UserStatus, TrackingFlag
from ..settings import Settings
from ..shares.manager import SharesManager
from ..user.manager import UserManager
from ..utils import task_counter, ticket_generator

if TYPE_CHECKING:
    from ..network.network import Network


logger = logging.getLogger(__name__)


class Reasons:
    CANCELLED = 'Cancelled'
    COMPLETE = 'Complete'
    QUEUED = 'Queued'
    FILE_NOT_SHARED = 'File not shared.'
    FILE_READ_ERROR = 'File read error.'


class TransferManager(BaseManager):

    def __init__(
            self, settings: Settings, event_bus: EventBus,
            user_manager: UserManager, shares_manager: SharesManager,
            network: Network, cache: Optional[TransferCache] = None):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._user_manager: UserManager = user_manager
        self._shares_manager: SharesManager = shares_manager
        self._network: Network = network
        self.cache: TransferCache = cache if cache else TransferNullCache()
        self._ticket_generator = ticket_generator()

        self._transfers: List[Transfer] = []
        self._file_connection_futures: Dict[int, asyncio.Future] = {}
        self._progress_reporting_task: Optional[asyncio.Task] = None

        self._MESSAGE_MAP = build_message_map(self)

        self.register_listeners()

    @property
    def transfers(self):
        return self._transfers

    def register_listeners(self):
        self._event_bus.register(
            MessageReceivedEvent, self._on_message_received)
        self._event_bus.register(
            PeerInitializedEvent, self._on_peer_initialized)
        self._event_bus.register(
            SessionInitializedEvent, self._on_session_initialized)

    async def read_cache(self):
        """Reads the transfers from the caches and corrects the state of those
        transfers
        """
        transfers: List[Transfer] = self.cache.read()
        for transfer in transfers:
            # Analyze the current state of the stored transfers and set them to
            # the correct state
            # This needs to happen first: when calling _add_transfer the manager
            # will be registering itself as listener. `manage_transfers` should
            # only be called if everything is loaded
            transfer.remotely_queued = False
            if transfer.state.VALUE == TransferState.INITIALIZING:
                await transfer.state.queue()

            elif transfer.is_transferring():
                if transfer.is_transfered():
                    state = TransferState.COMPLETE
                else:
                    state = TransferState.INCOMPLETE
                transfer.state = TransferState.init_from_state(state, transfer)
                transfer.reset_times()

            await self._add_transfer(transfer)

    def write_cache(self):
        """Write all current transfers to the cache"""
        self.cache.write(self._transfers)

    async def load_data(self):
        await self.read_cache()

    async def store_data(self):
        self.write_cache()

    async def start(self):
        await self.start_progress_reporting_task()

    async def stop(self) -> List[asyncio.Task]:
        """Cancel all current transfer tasks

        :return: a list of tasks that have been cancelled so that they can be
            awaited
        """
        cancelled_tasks = []
        for transfer in self.transfers:
            cancelled_tasks.extend(transfer.cancel_tasks())

        if self._progress_reporting_task:
            cancelled_tasks.append(self._progress_reporting_task)
            self.stop_progress_reporting_task()

        return cancelled_tasks

    async def start_progress_reporting_task(self):
        if not self._progress_reporting_task:
            self._progress_reporting_task = asyncio.create_task(
                self._progress_reporting_job(),
                name=f'progress-reporting-{task_counter()}'
            )

    def stop_progress_reporting_task(self):
        if self._progress_reporting_task:
            self._progress_reporting_task.cancel()
            self._progress_reporting_task = None

    async def _progress_reporting_job(self):
        while True:
            updates = []
            for transfer in self._transfers:
                previous = transfer.progress_snapshot
                current = transfer.take_progress_snapshot()
                if previous != current:
                    updates.append((transfer, previous, current))

            if updates:
                await self._event_bus.emit(TransferProgressEvent(updates))

            await asyncio.sleep(self._settings.transfers.report_interval)

    async def download(self, username: str, filename: str) -> Transfer:
        """Requests to start a downloading the file from the given user

        :param user: User from which to download the file
        :param filename: Name of the file to download. This should be the full
            path to the file as returned in the search results
        :return: a `Transfer` object from which the status of the transfer can
            be requested. If the transfer already exists in the client then this
            transfer will be returned
        """
        transfer = await self.add(
            Transfer(
                username,
                filename,
                TransferDirection.DOWNLOAD
            )
        )
        await transfer.state.queue()
        return transfer

    async def abort(self, transfer: Transfer):
        """Aborts the given transfer. This will cancel all pending transfers
        and remove the file (in case of download)

        :param transfer: `Transfer` object to abort
        :raise TransferNotFoundError: if the transfer has not been added to the
            manager first
        :raise InvalidStateTransition: When the transfer could not be
            transitioned to aborted
        """
        if transfer not in self.transfers:
            raise TransferNotFoundError(
                "cannot queue transfer: transfer was not added to the manager")

        if not await transfer.state.abort():
            raise InvalidStateTransition(
                transfer,
                transfer.state.VALUE,
                TransferState.State.ABORTED,
                "Could not make the desired state transition"
            )

        # Only remove file when downloading
        if transfer.is_download():
            try:
                await self._remove_download_path(transfer)
            except OSError:
                logger.warning(f"failed to remove file during abort : {transfer.local_path}")

    async def queue(self, transfer: Transfer):
        """Places given transfer (back) in the queue

        :param transfer: `Transfer` object to queue
        :raise TransferNotFoundError: if the transfer has not been added to the
            manager first
        :raise InvalidStateTransition: When the transfer could not be
            transitioned to queued
        """
        if transfer not in self.transfers:
            raise TransferNotFoundError(
                "cannot queue transfer: transfer was not added to the manager")

        has_transitioned = await transfer.state.queue()
        if not has_transitioned:
            raise InvalidStateTransition(
                transfer,
                transfer.state.VALUE,
                TransferState.State.ABORTED,
                "Could not make the desired state transition"
            )

    async def _add_transfer(self, transfer: Transfer) -> Transfer:
        for queued_transfer in self._transfers:
            if queued_transfer == transfer:
                logger.info(f"skip adding transfer, already exists : {queued_transfer}")
                return queued_transfer

        logger.info(f"adding transfer : {transfer}")
        transfer.state_listeners.append(self)
        self._transfers.append(transfer)
        await self._event_bus.emit(TransferAddedEvent(transfer))

        return transfer

    async def add(self, transfer: Transfer) -> Transfer:
        """Adds a transfer if it does not already exist, otherwise it returns
        the already existing transfer. This method will emit a
        `TransferAddedEvent` only if the transfer did not exist

        This method only adds a transfer and does not automatically start it. To
        do call `.queue` on the manager

        :param transfer: Transfer to be added
        :return: either the transfer we have passed or the already existing
            transfer
        """
        transfer = await self._add_transfer(transfer)
        await self.manage_transfers()
        return transfer

    async def remove(self, transfer: Transfer):
        """Remove a transfer from the list of transfers. This will attempt to
        abort the transfer before removing it. Emits a `TransferRemovedEvent`
        after removal

        :param transfer: Transfer object to remove
        :raise TransferNotFoundError: Raised when the transfer was not added to
            the manager
        """
        if transfer not in self.transfers:
            raise TransferNotFoundError(
                "cannot remove transfer: transfer was not added to the manager")

        try:
            await self.abort(transfer)
        except InvalidStateTransition:
            pass
        except Exception:
            logger.exception(f"error aborting transfer before removal : {transfer}")
        finally:
            self._transfers.remove(transfer)
            await self._event_bus.emit(TransferRemovedEvent(transfer))

        await self.manage_transfers()

    def get_uploads(self) -> List[Transfer]:
        return [transfer for transfer in self._transfers if transfer.is_upload()]

    def get_downloads(self) -> List[Transfer]:
        return [transfer for transfer in self._transfers if transfer.is_download()]

    def get_upload_slots(self) -> int:
        """Returns the total amount of upload slots"""
        return self._settings.transfers.limits.upload_slots

    def has_slots_free(self) -> bool:
        return self.get_free_upload_slots() > 0

    def get_free_upload_slots(self) -> int:
        uploading_transfers = []
        for transfer in self._transfers:
            if transfer.is_upload() and transfer.is_processing():
                uploading_transfers.append(transfer)

        available_slots = self.get_upload_slots() - len(uploading_transfers)
        return max(0, available_slots)

    def get_queue_size(self) -> int:
        """Returns the amount of queued uploads"""
        return len([
            transfer for transfer in self._transfers
            if transfer.is_upload() and transfer.state == TransferState.QUEUED
        ])

    def get_downloading(self) -> List[Transfer]:
        """Returns all transfers that are currently downloading or an attempt is
        is made to start downloading
        """
        return [
            transfer for transfer in self._transfers
            if transfer.is_download() and transfer.is_processing()
        ]

    def get_uploading(self) -> List[Transfer]:
        """Returns all transfers that are currently uploading or an attempt is
        is made to start uploading
        """
        return [
            transfer for transfer in self._transfers
            if transfer.is_upload() and transfer.is_processing()
        ]

    def get_finished_transfers(self) -> List[Transfer]:
        """Returns a complete list of transfers that are in a finalized state
        (COMPLETE, ABORTED, FAILED)
        """
        return [
            transfer for transfer in self._transfers
            if transfer.is_finalized()
        ]

    def get_unfinished_transfers(self) -> List[Transfer]:
        """Returns a complete list of transfers that are not in a finalized
        state (COMPLETE, ABORTED, FAILED)
        """
        return [
            transfer for transfer in self._transfers
            if not transfer.is_finalized()
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
            if transfer.state.VALUE == TransferState.COMPLETE and transfer.is_upload()
        ]
        if len(upload_speeds) == 0:
            return 0.0
        return sum(upload_speeds) / len(upload_speeds)

    def get_place_in_queue(self, transfer: Transfer) -> int:
        """Gets the place of the given upload in the transfer queue

        :return: The place in the queue, 0 if not in the queue a value equal or
            greater than 1 indicating the position otherwise
        """
        _, uploads = self._get_queued_transfers()
        try:
            return uploads.index(transfer)
        except ValueError:
            return 0

    def get_transfer(self, username: str, remote_path: str, direction: TransferDirection) -> Transfer:
        """Lookup transfer by `username`, `remote_path` and `transfer` direction

        :param username: Username of the transfer
        :param remote_path: Full remote path of the transfer
        :param direction: Direction of the transfer (upload / download)
        :return: The matching transfer object
        :raise ValueError: If the transfer is not found
        """
        req_transfer = Transfer(username, remote_path, direction)
        for transfer in self._transfers:
            if transfer == req_transfer:
                return transfer
        raise ValueError(
            f"transfer for user {username} and remote_path {remote_path} (direction={direction}) not found")

    async def manage_user_tracking(self):
        """Remove or add user tracking based on the list of transfers. This
        method will untrack users for which there are no more unfinished
        transfers and start/keep tracking users for which there are unfinished
        transfers
        """
        unfinished_users = set(
            transfer.username
            for transfer in self.get_unfinished_transfers()
        )
        finished_users = set(
            transfer.username
            for transfer in self.get_finished_transfers()
        )

        for username in unfinished_users:
            await self._user_manager.track_user(username, TrackingFlag.TRANSFER)
        for username in finished_users - unfinished_users:
            await self._user_manager.untrack_user(username, TrackingFlag.TRANSFER)

    async def manage_transfers(self):
        """This method analyzes the state of the current downloads/uploads and
        starts them up in case there are free slots available
        """
        await self.manage_user_tracking()

        downloads, uploads = self._get_queued_transfers()
        free_upload_slots = self.get_free_upload_slots()

        # Downloads will just get remotely queued
        for download in downloads:
            if download.remotely_queued or download._remotely_queue_task:
                continue

            download._remotely_queue_task = asyncio.create_task(
                self._queue_remotely(download),
                name=f'queue-remotely-{task_counter()}'
            )
            download._remotely_queue_task.add_done_callback(
                download._remotely_queue_task_complete
            )

        # Uploads should be initialized and transfered if possible
        for upload in uploads[:free_upload_slots]:
            if not upload._transfer_task:
                upload._transfer_task = asyncio.create_task(
                    self._initialize_upload(upload),
                    name=f'initialize-upload-{task_counter()}'
                )
                upload._transfer_task.add_done_callback(
                    upload._transfer_task_complete
                )

    def _get_queued_transfers(self) -> Tuple[List[Transfer], List[Transfer]]:
        """Returns all transfers eligable for being initialized

        :return: a tuple containing 2 lists: the eligable downloads and eligable
            uploads
        """
        queued_downloads = []
        queued_uploads = []
        for transfer in self._transfers:
            # Get the user object from the user manager, if the user is tracked
            # this user object will be returned. Otherwise a new user object is
            # created, but not assigned to the user manager, whose status is
            # UNKNOWN, giving it the benefit of the doubt and scheduling the
            # transfers
            user = self._user_manager.get_user_object(transfer.username)
            if user.status == UserStatus.OFFLINE:
                continue

            if transfer.direction == TransferDirection.UPLOAD:
                if transfer.state.VALUE == TransferState.QUEUED:
                    queued_uploads.append(transfer)

            else:
                # For downloads we try to continue with incomplete downloads,
                # for uploads it's up to the other user
                if transfer.state.VALUE in (TransferState.QUEUED, TransferState.INCOMPLETE):
                    queued_downloads.append(transfer)

        queued_uploads = self._prioritize_uploads(queued_uploads)

        return queued_downloads, queued_uploads

    def _prioritize_uploads(self, uploads: List[Transfer]) -> List[Transfer]:
        """Ranks the queued uploads by priority based on certain parameters

        :return: sorted list of provided by uploads by priority
        """
        friends = self._settings.users.friends

        ranking = []
        for upload in uploads:
            user = self._user_manager.get_user_object(upload.username)

            rank = 0
            # Rank UNKNOWN status lower, OFFLINE should be blocked
            if user.status in (UserStatus.ONLINE, UserStatus.AWAY):
                rank += 1

            if upload.username in friends:
                rank += 5

            # Privileged users should have absolute priority
            if user.privileged:
                rank += 100

            ranking.append((rank, upload))

        ranking.sort(key=itemgetter(0))
        return list(reversed([upload for _, upload in ranking]))

    async def _remove_download_path(self, transfer: Transfer):
        if transfer.local_path:
            if await asyncos.path.exists(transfer.local_path):
                await asyncos.remove(transfer.local_path)

    async def _prepare_download_path(self, transfer: Transfer):
        if transfer.local_path is None:
            download_path, file_path = self._shares_manager.calculate_download_path(transfer.remote_path)
            transfer.local_path = os.path.join(download_path, file_path)

        path, _ = os.path.split(transfer.local_path)
        await self._shares_manager.create_directory(path)

    async def _calculate_offset(self, transfer: Transfer) -> int:
        """Calculates the offset when downloading a file by inspecting the file
        at the local path.

        :return: the calculated offset (in bytes)
        """
        # Shouldn't occur but this is to keep the typing happy
        if not transfer.local_path:
            return 0

        try:
            return await asyncos.path.getsize(transfer.local_path)
        except (OSError, TypeError):
            return 0

    async def _queue_remotely(self, transfer: Transfer):
        """Remotely queue the given transfer. If the message was successfully
        delivered the `remotely_queued` flag will be set for the transfer
        """
        logger.debug(f"attempting to queue transfer remotely : {transfer}")
        try:
            await self._network.send_peer_messages(
                transfer.username,
                PeerTransferQueue.Request(transfer.remote_path)
            )

        except (ConnectionWriteError, PeerConnectionError) as exc:
            logger.debug(f"failed to queue transfer remotely : {transfer} : {exc!r}")
            transfer.increase_queue_attempts()
            await transfer.state.queue()

        else:
            transfer.remotely_queued = True
            transfer.reset_queue_attempts()
            await self.manage_transfers()

    async def request_place_in_queue(self, transfer: Transfer) -> Optional[int]:
        """Requests the place in queue for the given transfer. The method will
        return the value in case of success and return the value

        :return: place in queue or `None` in case of error
        :raise RequestPlaceFailedError: when the request failed to send to the
            peer or waiting for a response timed out
        """
        try:
            await self._network.send_peer_messages(
                transfer.username,
                PeerPlaceInQueueRequest.Request(transfer.remote_path)
            )
        except ConnectionWriteError:
            logger.info(f"failed to request place in queue of transfer : {transfer}")
            raise RequestPlaceFailedError("failed to request place in queue")

        try:
            async with atimeout(15):
                _, response = await self._network.create_peer_response_future(
                    peer=transfer.username,
                    message_class=PeerPlaceInQueueReply.Request,
                    fields={
                        'filename': transfer.remote_path
                    }
                )
        except asyncio.TimeoutError:
            logger.info(f"timeout receiving response to place in queue for transfer : {transfer}")
            raise RequestPlaceFailedError("failed to request place in queue")
        else:
            transfer.place_in_queue = response.place
            return response.place

    async def _initialize_download(
            self, transfer: Transfer, peer_connection: PeerConnection,
            request: PeerTransferRequest.Request):
        """Initializes a download and starts downloading. This method should be
        called after a PeerTransferRequest has been received

        :param transfer: transfer object to initialize
        :param peer_connection: peer connection on which the transfer request
            was received
        :param request: transfer request object for the given transfer
        """
        await transfer.state.initialize()

        transfer.filesize = request.filesize

        try:
            await peer_connection.send_message(
                PeerTransferReply.Request(
                    ticket=request.ticket,
                    allowed=True
                )
            )
        except ConnectionWriteError:
            logger.warn(f"failed to send transfer reply for ticket {request.ticket} and transfer : {transfer}")
            await transfer.state.queue()
            return

        # Already create a future for the incoming connection
        file_connection_future: asyncio.Future = asyncio.Future()
        self._file_connection_futures[request.ticket] = file_connection_future

        try:
            async with atimeout(60):
                file_connection: PeerConnection = await file_connection_future

        except asyncio.TimeoutError:
            await transfer.state.queue()
            return

        # The transfer ticket should already have been received (otherwise the
        # future could not have completed)
        # Calculate and send the file offset
        offset = await self._calculate_offset(transfer)
        transfer.set_offset(offset)
        try:
            await file_connection.send_message(uint64(offset).serialize())

        except ConnectionWriteError:
            logger.warning(f"failed to send offset: {transfer}")
            if transfer.is_upload():
                await transfer.state.fail()
            else:
                await transfer.state.incomplete()
            return

        except asyncio.CancelledError:
            # Aborted or program shut down
            await file_connection.disconnect(CloseReason.REQUESTED)
            raise

        if transfer.direction == TransferDirection.DOWNLOAD:
            await self._download_file(transfer, file_connection)
        else:
            await self._upload_file(transfer, file_connection)

    async def _initialize_upload(self, transfer: Transfer):
        """Notifies the peer we are ready to upload the file for the given
        transfer
        """
        logger.debug(f"initializing upload {transfer}")
        await transfer.state.initialize()

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
            logger.debug(f"failed to send request to upload : {transfer} : {exc!r}")
            await transfer.state.queue()
            return

        try:
            async with atimeout(TRANSFER_REPLY_TIMEOUT):
                connection, response = await self._network.create_peer_response_future(
                    transfer.username,
                    PeerTransferReply.Request,
                    fields={
                        'ticket': ticket
                    }
                )

        except asyncio.TimeoutError:
            logger.debug(f"timeout waiting for transfer reply : {transfer}")
            await transfer.state.queue()
            return

        if not response.allowed:
            await transfer.state.fail(reason=response.reason)
            return

        # Create a file connection
        try:
            connection = await self._network.create_peer_connection(
                transfer.username,
                PeerConnectionType.FILE,
                initial_state=PeerConnectionState.AWAITING_OFFSET
            )

        except PeerConnectionError:
            logger.info(f"failed to create peer connection for transfer : {transfer}")
            await transfer.state.queue()
            return

        # Send transfer ticket
        try:
            await connection.send_message(uint32(ticket).serialize())
        except ConnectionWriteError:
            logger.info(f"failed to send transfer ticket : {transfer}")
            await transfer.state.queue()
            return

        connection.set_connection_state(PeerConnectionState.AWAITING_OFFSET)

        # Receive transfer offset
        try:
            offset = await connection.receive_transfer_offset()
        except ConnectionReadError:
            logger.info(f"failed to receive transfer offset : {transfer}")
            await transfer.state.queue()
            return

        else:
            logger.debug(f"received offset {offset} for transfer : {transfer}")
            transfer.set_offset(offset)

        await self._upload_file(transfer, connection)

        # Send transfer speed
        if transfer.state.VALUE == TransferState.COMPLETE:
            self._network.queue_server_messages(
                SendUploadSpeed.Request(int(transfer.get_speed()))
            )

    async def _upload_file(self, transfer: Transfer, connection: PeerConnection):
        """Uploads the transfer over the connection. This method will set the
        appropriate states on the passed `transfer` and `connection` objects.

        :param transfer: `Transfer` object
        :param connection: connection on which file should be sent
        """
        connection.set_connection_state(PeerConnectionState.TRANSFERRING)
        await transfer.state.start_transferring()
        try:
            if not transfer.local_path:
                raise AioSlskException(
                    f"attempted to upload a transfer that doesn't have a local path set : {transfer}")

            async with aiofiles.open(transfer.local_path, mode='rb') as handle:
                await handle.seek(transfer.get_offset())
                await connection.send_file(
                    handle,
                    transfer._transfer_progress_callback
                )

        except OSError:
            logger.exception(f"error opening local file : {transfer.local_path}")
            await transfer.state.fail(reason=Reasons.FILE_READ_ERROR)
            await connection.disconnect(CloseReason.REQUESTED)

        except ConnectionWriteError:
            logger.exception(f"error writing to socket for transfer : {transfer}")
            await transfer.state.fail()
            # Possible this needs to be put in a task or just queued, if the
            # peer went offline it's possible we are hogging the _current_task
            # for nothing (sending the peer message could time out)
            try:
                await self._network.send_peer_messages(
                    transfer.username,
                    PeerUploadFailed.Request(transfer.remote_path)
                )
            except PeerConnectionError:
                logger.info("failed to send PeerUploadFailed message (possibly peer went offline)")

        except asyncio.CancelledError:
            # Aborted or program shut down
            await connection.disconnect(CloseReason.REQUESTED)
            raise

        except AioSlskException:
            logger.exception(f"failed to upload transfer : {transfer}")
            await transfer.state.fail(Reasons.FILE_NOT_SHARED)
            await connection.disconnect(CloseReason.REQUESTED)
            try:
                await self._network.send_peer_messages(
                    transfer.username,
                    PeerUploadFailed.Request(transfer.remote_path)
                )
            except PeerConnectionError:
                logger.info("failed to send PeerUploadFailed message (possibly peer went offline)")

        else:
            await connection.receive_until_eof(raise_exception=False)
            if transfer.is_transfered():
                await transfer.state.complete()
            else:
                await transfer.state.fail()

    async def _download_file(self, transfer: Transfer, connection: PeerConnection):
        """Downloads the transfer over the connection. This method will set the
        appropriate states on the passed `transfer` and `connection` objects.

        :param transfer: `Transfer` object
        :param connection: connection on which file should be received
        """
        try:
            await self._prepare_download_path(transfer)
        except OSError:
            logger.exception(f"failed to create path {transfer.local_path}")
            await connection.disconnect(CloseReason.REQUESTED)
            await transfer.state.fail(reason=Reasons.FILE_READ_ERROR)
            return

        connection.set_connection_state(PeerConnectionState.TRANSFERRING)
        await transfer.state.start_transferring()

        try:
            async with aiofiles.open(transfer.local_path, mode='ab') as handle:
                await connection.receive_file(
                    handle,
                    transfer.filesize - transfer._offset,
                    transfer._transfer_progress_callback
                )

        except OSError:
            logger.exception(f"error opening local file : {transfer.local_path}")
            await transfer.state.fail(reason=Reasons.FILE_READ_ERROR)
            await connection.disconnect(CloseReason.REQUESTED)

        except ConnectionReadError:
            logger.exception(f"error reading from socket : {transfer:!r}")
            await transfer.state.incomplete()

        except asyncio.CancelledError:
            # Aborted or program shut down
            logger.debug(f"requested to cancel transfer: {transfer}")
            await connection.disconnect(CloseReason.REQUESTED)
            raise

        else:
            await connection.disconnect(CloseReason.REQUESTED)
            if transfer.is_transfered():
                await transfer.state.complete()
            else:
                await transfer.state.incomplete()

    async def on_transfer_state_changed(
            self, transfer: Transfer, old: TransferState.State, new: TransferState.State):
        await self.manage_transfers()

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self._MESSAGE_MAP:
            await self._MESSAGE_MAP[message.__class__](message, event.connection)

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
        if not connection.username:
            logger.warning(
                "got PeerTransferQueue for a connection that wasn't properly initialized")
            return

        transfer = await self.add(
            Transfer(
                username=connection.username,
                remote_path=message.filename,
                direction=TransferDirection.UPLOAD
            )
        )

        # Only put the transfer in queue if in states:
        # * FAILED: Re-attempt at downloader getting the file
        # * COMPLETE: Re-download of a file
        # In case the state is ABORTED:
        # * Explicitly reply that the transfer has been cancelled
        # In other cases where the message is not allowed (statuses=QUEUED, INITIALIZING, UPLOADING)
        # do not respond with anything. This could otherwise abort the already
        # processing transfer
        if transfer.state.VALUE == TransferState.ABORTED:
            await connection.queue_message(
                PeerTransferQueueFailed.Request(
                    filename=message.filename,
                    reason=Reasons.CANCELLED
                )
            )
            return
        elif transfer.state.VALUE == TransferState.QUEUED:
            logger.warning(f"ignoring queue request for transfer that is already being processed : {transfer}")
            return
        elif transfer.is_processing():
            logger.warning(f"ignoring queue request for transfer that is already being processed : {transfer}")
            return

        # Check if the shared file exists
        try:
            item = await self._shares_manager.get_shared_item(
                message.filename, connection.username)
            transfer.local_path = item.get_absolute_path()
            transfer.filesize = await self._shares_manager.get_filesize(item)

        except (FileNotFoundError, FileNotSharedError):
            await transfer.state.fail(reason=Reasons.FILE_NOT_SHARED)
            await connection.queue_message(
                PeerTransferQueueFailed.Request(
                    filename=message.filename,
                    reason=Reasons.FILE_NOT_SHARED
                )
            )

        else:
            await transfer.state.queue()

    async def _on_peer_initialized(self, event: PeerInitializedEvent):
        # Only create a task for file connections that we did not try to create
        # ourselves. This (usually) means the peer is connecting to us to upload
        # a file.
        # We should first wait for the ticket to be able to link this connection
        # to a transfer
        connection = event.connection
        if connection.connection_type == PeerConnectionType.FILE:
            if event.requested:
                return

            try:
                async with atimeout(5):
                    ticket = await connection.receive_transfer_ticket()

            except (ConnectionReadError, asyncio.TimeoutError) as exc:
                # Connection should automatically be closed
                logger.warning(
                    f"failed to receive transfer ticket on file connection : "
                    f"{connection.hostname}:{connection.port}",
                    exc_info=exc
                )
                return

            try:
                self._file_connection_futures[ticket].set_result(connection)
            except KeyError:
                logger.warning(f"did not find a task waiting for file connection with ticket : {ticket}")
                await connection.disconnect(CloseReason.REQUESTED)
            except asyncio.InvalidStateError:
                logger.warning(f"file connection for ticket {ticket} was already fulfilled")
                await connection.disconnect(CloseReason.REQUESTED)

    async def _on_session_initialized(self, event: SessionInitializedEvent):
        await self.manage_transfers()

    @on_message(PeerTransferRequest.Request)
    async def _on_peer_transfer_request(self, message: PeerTransferRequest.Request, connection: PeerConnection):
        """The PeerTransferRequest message is sent when the peer is ready to
        transfer the file. The message contains more information about the
        transfer.

        We also handle situations here where the other peer sends this message
        without sending PeerTransferQueue first
        """
        if not connection.username:
            logger.warning(
                "got PeerTransferRequest for a connection that wasn't properly initialized")
            return

        try:
            transfer = self.get_transfer(
                connection.username,
                message.filename,
                TransferDirection(message.direction)
            )
        except ValueError:
            transfer = None

        # Make a decision based on what was requested and what we currently have
        # in our queue
        if TransferDirection(message.direction) == TransferDirection.UPLOAD:
            # The other peer is asking us to upload a file. Check if this is not
            # a locked file for the given user
            try:
                await self._shares_manager.get_shared_item(
                    message.filename, username=connection.username)

            except (FileNotFoundError, FileNotSharedError):
                connection.queue_message(
                    PeerTransferReply.Request(
                        ticket=message.ticket,
                        allowed=False,
                        reason=Reasons.FILE_NOT_SHARED
                    )
                )
                if transfer:
                    await transfer.state.fail(Reasons.FILE_NOT_SHARED)
                    return

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
                await connection.send_message(
                    PeerTransferReply.Request(
                        ticket=message.ticket,
                        allowed=False,
                        reason=Reasons.QUEUED
                    )
                )
                transfer = await self.add(transfer)
                await transfer.state.queue()
            else:
                # The peer is asking us to upload a file already in our list:
                # this always leads to a refusal of the the request as it is up
                # to us to let the downloader know when we are ready to upload

                # If the state of transfer is ABORTED, COMPLETE, QUEUED: refuse
                # the request with a specific message
                # In other cases (INITIALIZING, UPLOADING, FAILED) the message
                # simply gets ignored
                # Additional notes:
                # * COMPLETE / FAILED, in reality we could re-queue here
                # * Other clients might abort the transfer when receiving this
                #   message in (at least) UPLOADING state
                fail_reason_map = {
                    TransferState.ABORTED: Reasons.CANCELLED,
                    TransferState.COMPLETE: Reasons.COMPLETE,
                    TransferState.QUEUED: Reasons.QUEUED
                }

                reason = fail_reason_map.get(transfer.state.VALUE, None)

                if reason:
                    await connection.send_message(
                        PeerTransferReply.Request(
                            ticket=message.ticket,
                            allowed=False,
                            reason=reason
                        )
                    )

        else:
            # Request to download (other peer is offering to upload a file)
            # If the transfer is not found, assume we aborted and let the
            # uploader know
            # If the transfer is ABORTED: let the uploader know
            # If the transfer was already COMPLETE: let the upload know
            # If the transfer is currently being processed, ignore the message
            # altogether
            # If the transfer is in FAILED state it needs to be re-queued first;
            # somehow we got this message before being able to queue the
            # transfer. Special note: because this message was received we
            # already know the transfer is remotely queued and sety the flag
            # accordingly
            # Finally: if the transfer is in states QUEUED or INCOMPLETE
            # continue with the transfer as we were expecting this message
            reason = None
            if transfer is None:
                # A download which we don't have in queue, assume we removed it
                reason = Reasons.CANCELLED
            elif transfer.state.VALUE == TransferState.ABORTED:
                reason = Reasons.CANCELLED
            elif transfer.state.VALUE == TransferState.COMPLETE:
                reason = Reasons.COMPLETE
            elif transfer.is_processing():
                # Needs investigation, currently don't do anything when the
                # transfer is already being processed
                return

            if reason is not None:
                await connection.send_message(
                    PeerTransferReply.Request(
                        ticket=message.ticket,
                        allowed=False,
                        reason=Reasons.CANCELLED
                    )
                )
            else:
                # All good to download
                if transfer.state.VALUE == TransferState.FAILED:
                    await transfer.state.queue(remotely=True)

                transfer._transfer_task = asyncio.create_task(
                    self._initialize_download(transfer, connection, message),
                    name=f'initialize-download-{task_counter()}'
                )
                transfer._transfer_task.add_done_callback(
                    transfer._transfer_task_complete
                )

    @on_message(PeerPlaceInQueueRequest.Request)
    async def _on_peer_place_in_queue_request(
            self, message: PeerPlaceInQueueRequest.Request, connection: PeerConnection):
        if not connection.username:
            logger.warning(
                "got PeerPlaceInQueueRequest for a connection that wasn't properly initialized")
            return

        filename = message.filename
        try:
            transfer = self.get_transfer(
                connection.username,
                filename,
                TransferDirection.UPLOAD
            )
        except ValueError:
            logger.error(
                f"PeerPlaceInQueueRequest : could not find transfer (upload) for "
                f"{filename} from {connection.username}"
            )
        else:
            place = self.get_place_in_queue(transfer)
            if place:
                connection.queue_message(
                    PeerPlaceInQueueReply.Request(filename, place))

    @on_message(PeerPlaceInQueueReply.Request)
    async def _on_peer_place_in_queue_reply(self, message: PeerPlaceInQueueReply.Request, connection: PeerConnection):
        if not connection.username:
            logger.warning(
                "got PeerPlaceInQueueReply for a connection that wasn't properly initialized")
            return

        try:
            transfer = self.get_transfer(
                connection.username,
                message.filename,
                TransferDirection.DOWNLOAD
            )
        except ValueError:
            logger.error(
                f"PeerPlaceInQueueReply : could not find transfer (download) for "
                f"{message.filename} from {connection.username}"
            )
        else:
            transfer.place_in_queue = message.place

    @on_message(PeerUploadFailed.Request)
    async def _on_peer_upload_failed(self, message: PeerUploadFailed.Request, connection: PeerConnection):
        """Called when there is a problem on their end uploading the file. This
        is actually a common message that happens for example when we close the
        connection before the upload is finished
        """
        if not connection.username:
            logger.warning(
                "got PeerUploadFailed for a connection that wasn't properly initialized")
            return

        try:
            transfer = self.get_transfer(
                connection.username,
                message.filename,
                TransferDirection.DOWNLOAD
            )
        except ValueError:
            logger.error(
                f"PeerUploadFailed : could not find transfer (download) for "
                f"{message.filename} from {connection.username}"
            )
        else:
            transfer.remotely_queued = False
            await self.manage_transfers()

    @on_message(PeerTransferQueueFailed.Request)
    async def _on_peer_transfer_queue_failed(
            self, message: PeerTransferQueueFailed.Request, connection: PeerConnection):

        if not connection.username:
            logger.warning(
                "got PeerTransferQueueFailed for a connection that wasn't properly initialized")
            return

        filename = message.filename
        reason = message.reason
        try:
            transfer = self.get_transfer(
                connection.username, filename, TransferDirection.DOWNLOAD)
        except ValueError:
            logger.error(
                f"PeerTransferQueueFailed : could not find transfer for "
                f"{filename} from {connection.username}"
            )
        else:
            await transfer.state.fail(reason=reason)
