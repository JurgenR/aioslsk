from __future__ import annotations
import aiofiles
from aiofiles import os as asyncos
import asyncio
from async_timeout import timeout as atimeout
from enum import auto, Flag
import logging
from operator import itemgetter
import os
import time
from typing import Optional, TYPE_CHECKING

from ..base_manager import BaseManager
from .cache import TransferNullCache, TransferCache
from ..constants import (
    MAX_TRANSFER_MGMT_INTERVAL,
    MIN_TRANSFER_MGMT_INTERVAL,
    TRANSFER_REPLY_TIMEOUT,
)
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
    BlockListChangedEvent,
    EventBus,
    FriendListChangedEvent,
    MessageReceivedEvent,
    PeerInitializedEvent,
    SessionInitializedEvent,
    ScanCompleteEvent,
    SharedDirectoryChangeEvent,
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
from .model import AbortReason, FailReason, Transfer, TransferDirection
from .state import TransferState
from ..settings import Settings
from ..shares.manager import SharesManager
from ..tasks import BackgroundTask
from ..user.manager import UserManager
from ..user.model import BlockingFlag, UserStatus, TrackingFlag
from ..utils import task_counter, ticket_generator

if TYPE_CHECKING:
    from ..network.network import Network


logger = logging.getLogger(__name__)


class _RequestFlag(Flag):
    SHARES_CHANGE = auto()
    TRANSFER_CHANGE = auto()


class TransferManager(BaseManager):
    """Class responsible for transfer related functionality. This class stores
    transfer objects and handles related events.
    """

    def __init__(
            self, settings: Settings, event_bus: EventBus,
            user_manager: UserManager, shares_manager: SharesManager,
            network: Network, cache: Optional[TransferCache] = None):

        self.cache: TransferCache = cache if cache else TransferNullCache()
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._user_manager: UserManager = user_manager
        self._shares_manager: SharesManager = shares_manager
        self._network: Network = network

        self._ticket_generator = ticket_generator()

        self._transfers: list[Transfer] = []
        self._file_connection_futures: dict[int, asyncio.Future] = {}
        self._progress_reporting_task: BackgroundTask = BackgroundTask(
            interval=self._settings.transfers.report_interval,
            task_coro=self._progress_reporting_job,
            name='transfer-progress-task'
        )

        self._management_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._management_task: BackgroundTask = BackgroundTask(
            interval=MIN_TRANSFER_MGMT_INTERVAL,
            task_coro=self._management_job,
            name='transfer-management-task'
        )
        self._management_lock: asyncio.Lock = asyncio.Lock()
        self._management_flags: _RequestFlag = _RequestFlag(0)

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

        self._event_bus.register(
            BlockListChangedEvent, self._request_shares_cycle)
        self._event_bus.register(
            FriendListChangedEvent, self._request_shares_cycle)
        self._event_bus.register(
            SharedDirectoryChangeEvent, self._request_shares_cycle)
        self._event_bus.register(
            ScanCompleteEvent, self._request_shares_cycle)

    async def read_cache(self):
        """Reads the transfers from the caches and corrects the state of those
        transfers
        """
        transfers: list[Transfer] = self.cache.read()
        for transfer in transfers:
            # Analyze the current state of the stored transfers and set them to
            # the correct state
            transfer.remotely_queued = False
            if transfer.state.VALUE == TransferState.INITIALIZING:
                await transfer.state.queue()

            elif transfer.is_transferring():
                if transfer.is_transfered():
                    state = TransferState.COMPLETE
                else:
                    state = TransferState.INCOMPLETE
                transfer.state = TransferState.init_from_state(state, transfer)
                transfer.reset_time_vars()

            await self.add(transfer)

    def write_cache(self):
        """Write all currently stored transfers to the cache"""
        self.cache.write(self._transfers)

    async def load_data(self):
        await self.read_cache()

    async def store_data(self):
        self.write_cache()

    async def start(self):
        self._management_task.start()
        await self.start_progress_reporting_task()

    async def stop(self) -> list[asyncio.Task]:
        """Cancel all current transfer tasks

        :return: a list of tasks that have been cancelled so that they can be
            awaited
        """
        cancelled_tasks = []
        for transfer in self.transfers:
            cancelled_tasks.extend(transfer.cancel_tasks())

        if task := self._progress_reporting_task.cancel():
            cancelled_tasks.append(task)

        if task := self._management_task.cancel():
            cancelled_tasks.append(task)

        self._management_queue = asyncio.Queue()

        return cancelled_tasks

    async def start_progress_reporting_task(self):
        """Start the transfer progress reporting background task which will emit
        :class:`aioslsk.events.TransferProgressEvent` events at an interval
        defined in the settings. This method is called automatically when
        starting the client
        """
        self._progress_reporting_task.start()

    def stop_progress_reporting_task(self):
        """Start the transfer progress reporting task"""
        self._progress_reporting_task.cancel()

    async def _progress_reporting_job(self):
        updates = []
        for transfer in self._transfers:
            previous = transfer.progress_snapshot
            current = transfer.take_progress_snapshot()
            if previous != current:
                updates.append((transfer, previous, current))

        if updates:
            await self._event_bus.emit(TransferProgressEvent(updates))

    async def download(self, username: str, filename: str, paused: bool = False) -> Transfer:
        """Requests to start a downloading the file from the given user

        :param user: User from which to download the file
        :param filename: Name of the file to download. This should be the full
            path to the file as returned in the search results
        :param paused: Adds the download in the paused state
        :return: a :class:`.Transfer` object from which the status of the
            transfer can be requested. If the transfer already exists in the
            client then this transfer will be returned
        """
        transfer = await self.add(
            Transfer(
                username,
                filename,
                TransferDirection.DOWNLOAD
            )
        )
        if paused:
            await transfer.state.pause()
        else:
            await transfer.state.queue()

        return transfer

    async def abort(self, transfer: Transfer):
        """Aborts the given transfer. This will cancel all pending transfers
        and remove the file (in case of download)

        :param transfer: :class:`.Transfer` object to abort
        :raise TransferNotFoundError: if the transfer has not been added to the
            manager first
        :raise InvalidStateTransition: When the transfer could not be
            transitioned to aborted
        """
        if transfer not in self.transfers:
            raise TransferNotFoundError(
                "cannot queue transfer: transfer was not added to the manager")

        if not await transfer.state.abort(reason=AbortReason.REQUESTED):
            raise InvalidStateTransition(
                transfer,
                transfer.state.VALUE,
                TransferState.State.ABORTED,
                "Could not make the desired state transition"
            )

    async def queue(self, transfer: Transfer):
        """Places given transfer (back) in the queue

        This method can be called on downloads that are in the following states:

        * ``ABORTED``: Re-starts the aborted download
        * ``PAUSED``: Continues the paused download
        * ``COMPLETE``: Re-downloads the file. By default this will download
          the file to a new location unless the initial file was removed
        * ``INCOMPLETE``: The library should automatically attempt to retry
          a download in this state
        * ``FAILED``: Re-attempt to download the file

        :param transfer: :class:`.Transfer` object to queue
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
                TransferState.State.QUEUED,
                "Could not make the desired state transition"
            )

    async def pause(self, transfer: Transfer):
        if transfer not in self.transfers:
            raise TransferNotFoundError(
                "cannot pause transfer: transfer was not added to the manager")

        has_transitioned = await transfer.state.pause()
        if not has_transitioned:
            raise InvalidStateTransition(
                transfer,
                transfer.state.VALUE,
                TransferState.State.PAUSED,
                "Could not make the desired state transition"
            )

    async def add(self, transfer: Transfer) -> Transfer:
        """Adds a transfer if it does not already exist, otherwise it returns
        the already existing transfer. This method will emit a
        :class:`~aioslsk.events.TransferAddedEvent` only if the transfer did not
        exist.

        This method only adds a transfer and does not automatically start it. To
        do so call :func:`queue` on the manager

        :param transfer: Transfer to be added
        :return: either the transfer we have passed or the already existing
            transfer
        """
        for queued_transfer in self._transfers:
            if queued_transfer == transfer:
                logger.info("skip adding transfer, already exists : %s", queued_transfer)
                return queued_transfer

        logger.info("adding transfer : %s", transfer)
        transfer.state_listeners.append(self)
        self._transfers.append(transfer)

        self.request_management_cycle(_RequestFlag.TRANSFER_CHANGE)
        await self._event_bus.emit(TransferAddedEvent(transfer))

        return transfer

    async def remove(self, transfer: Transfer):
        """Remove a transfer from the list of transfers. This will attempt to
        abort the transfer before removing it. Emits a
        :class:`.TransferRemovedEvent` after removal

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
            logger.exception("error aborting transfer before removal : %s", transfer)
        finally:
            self._transfers.remove(transfer)
            await self._event_bus.emit(TransferRemovedEvent(transfer))

        self.request_management_cycle(_RequestFlag.TRANSFER_CHANGE)

    def get_uploads(self) -> list[Transfer]:
        return [transfer for transfer in self._transfers if transfer.is_upload()]

    def get_downloads(self) -> list[Transfer]:
        return [transfer for transfer in self._transfers if transfer.is_download()]

    def get_upload_slots(self) -> int:
        """Returns the total amount of upload slots"""
        return self._settings.transfers.limits.upload_slots

    def has_slots_free(self) -> bool:
        return self.get_free_upload_slots() > 0

    def get_free_upload_slots(self) -> int:
        uploading_transfers = self.get_uploading()
        available_slots = self.get_upload_slots() - len(uploading_transfers)
        return max(0, available_slots)

    def get_queue_size(self) -> int:
        """Returns the amount of queued uploads"""
        return len([
            transfer for transfer in self._transfers
            if transfer.is_upload() and transfer.state == TransferState.QUEUED
        ])

    def get_downloading(self) -> list[Transfer]:
        """Returns all transfers that are currently downloading or an attempt is
        is made to start downloading
        """
        return [
            transfer for transfer in self._transfers
            if transfer.is_download() and transfer.is_processing()
        ]

    def get_uploading(self) -> list[Transfer]:
        """Returns all transfers that are currently uploading or an attempt is
        is made to start uploading
        """
        return [
            transfer for transfer in self._transfers
            if transfer.is_upload() and transfer.is_processing()
        ]

    def get_finished_transfers(self) -> list[Transfer]:
        """Returns a complete list of transfers that are in a finalized state
        (COMPLETE, ABORTED, FAILED)
        """
        return [
            transfer for transfer in self._transfers
            if transfer.is_finalized()
        ]

    def get_unfinished_transfers(self) -> list[Transfer]:
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
        """Lookup transfer by ``username``, ``remote_path`` and ``transfer``
        direction. This method will raise an exception in case the transfer is
        not found

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

    def find_transfer(self, username: str, remote_path: str, direction: TransferDirection) -> Optional[Transfer]:
        """Lookup transfer by ``username``, ``remote_path`` and ``transfer``
        direction. This method will return ``None`` if the transfer is not found

        :param username: Username of the transfer
        :param remote_path: Full remote path of the transfer
        :param direction: Direction of the transfer (upload / download)
        :return: The matching transfer object or ``None``
        """
        req_transfer = Transfer(username, remote_path, direction)
        for transfer in self._transfers:
            if transfer == req_transfer:
                return transfer

        return None

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

    async def _management_job(self) -> float:
        await self._management_queue.get()

        start = time.monotonic()

        flags = self._management_flags
        self._management_flags = _RequestFlag(0)

        if flags & _RequestFlag.SHARES_CHANGE:
            await self.manage_shares_changed()

        await self.manage_user_tracking()
        self.manage_transfers()

        duration = time.monotonic() - start

        return min(MIN_TRANSFER_MGMT_INTERVAL + duration, MAX_TRANSFER_MGMT_INTERVAL)

    def request_management_cycle(self, flag: _RequestFlag):
        self._management_flags |= flag
        try:
            self._management_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    def manage_transfers(self):
        """This method analyzes the state of the current downloads/uploads and
        starts them up in case there are free slots available
        """
        downloads, uploads = self._get_queued_transfers()
        free_upload_slots = self.get_free_upload_slots()

        # Downloads will just get remotely queued
        for download in downloads:
            download._remotely_queue_task = asyncio.create_task(
                self._queue_remotely(download),
                name=f'queue-remotely-{task_counter()}'
            )
            download._remotely_queue_task.add_done_callback(
                download._remotely_queue_task_complete
            )

        # Uploads should be initialized and uploaded if possible
        for upload in uploads[:free_upload_slots]:
            upload._transfer_task = asyncio.create_task(
                self._initialize_upload(upload),
                name=f'initialize-upload-{task_counter()}'
            )
            upload._transfer_task.add_done_callback(
                upload._transfer_task_complete
            )

    async def manage_shares_changed(self):
        logger.debug("processing shares or block list changes")

        uploads = filter(
            lambda transfer: (
                transfer.is_upload()
                and transfer.state.VALUE not in (TransferState.COMPLETE, TransferState.FAILED)
            ),
            self.transfers
        )

        tasks = []
        for upload in uploads:

            should_change, abort_reason = self._evaluate_aborted_state(upload)

            if should_change:
                if upload.state.VALUE == TransferState.ABORTED:
                    tasks.append(upload.state.queue())
                else:
                    tasks.append(upload.state.abort(reason=abort_reason))

            elif abort_reason:
                upload.abort_reason = abort_reason

        await asyncio.gather(*tasks, return_exceptions=True)

    def _get_queued_transfers(self) -> tuple[list[Transfer], list[Transfer]]:
        """Returns all transfers eligable for being initialized

        :return: a tuple containing 2 lists: the eligable downloads and eligable
            uploads
        """
        uploading_users: set[str] = {
            transfer.username for transfer in self._transfers
            if transfer.is_upload() and transfer.is_processing()
        }
        users_with_queued_upload: set[str] = set()

        queued_downloads: list[Transfer] = []
        queued_uploads: list[Transfer] = []
        for transfer in self._transfers:
            # Get the user object from the user manager, if the user is tracked
            # this user object will be returned. Otherwise a new user object is
            # created, but not assigned to the user manager, whose status is
            # UNKNOWN, giving it the benefit of the doubt and scheduling the
            # transfer
            user = self._user_manager.get_user_object(transfer.username)
            if user.status == UserStatus.OFFLINE:
                continue

            if transfer.direction == TransferDirection.UPLOAD:
                # Do not add the user if the user is already uploading or a
                # transfer was already added to the queud upload list (only
                # allow 1 transfer per user)
                if transfer.username in uploading_users:
                    continue
                if transfer.username in users_with_queued_upload:
                    continue

                if transfer.state.VALUE == TransferState.QUEUED:
                    users_with_queued_upload.add(transfer.username)
                    queued_uploads.append(transfer)

            else:
                if transfer.remotely_queued:
                    continue

                # For downloads we try to continue with incomplete downloads,
                # for uploads it's up to the other user
                # Failed downloads without a reason are retried
                if transfer.state.VALUE in (TransferState.QUEUED, TransferState.INCOMPLETE):
                    queued_downloads.append(transfer)
                elif transfer.state.VALUE == TransferState.FAILED and transfer.fail_reason is None:
                    queued_downloads.append(transfer)

        queued_uploads = self._prioritize_uploads(queued_uploads)

        return queued_downloads, queued_uploads

    def _prioritize_uploads(self, uploads: list[Transfer]) -> list[Transfer]:
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

    def _reset_remotely_queued_flags(self, username: str):
        """Removes the ``remotely_queued`` flag from all downloads for the given
        given user
        """
        for transfer in self._transfers:
            if transfer.direction == TransferDirection.DOWNLOAD:
                if transfer.username == username:
                    transfer.remotely_queued = False

    async def _queue_remotely(self, transfer: Transfer):
        """Remotely queue the given transfer. If the message was successfully
        delivered the ``remotely_queued`` flag will be set for the transfer
        """
        logger.debug("attempting to queue transfer remotely : %s", transfer)
        try:
            await self._network.send_peer_messages(
                transfer.username,
                PeerTransferQueue.Request(transfer.remote_path)
            )

        except (ConnectionWriteError, PeerConnectionError) as exc:
            logger.debug("failed to queue transfer remotely : %s : %r", transfer, exc)
            transfer.increase_queue_attempts()
            await transfer.state.queue()

        else:
            transfer.remotely_queued = True
            transfer.reset_queue_attempts()
            self.request_management_cycle(_RequestFlag.TRANSFER_CHANGE)

    async def request_place_in_queue(self, transfer: Transfer) -> Optional[int]:
        """Requests the place in queue for the given transfer. The method will
        return the value in case of success and return the value

        :return: place in queue or ``None`` in case of error
        :raise RequestPlaceFailedError: when the request failed to send to the
            peer or waiting for a response timed out
        """
        try:
            await self._network.send_peer_messages(
                transfer.username,
                PeerPlaceInQueueRequest.Request(transfer.remote_path)
            )
        except ConnectionWriteError:
            logger.info("failed to request place in queue of transfer : %s", transfer)
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
            logger.warning(
                "timeout receiving response to place in queue for transfer : %s", transfer)
            raise RequestPlaceFailedError("failed to request place in queue")

        else:
            transfer.place_in_queue = response.place
            return response.place

    async def _initialize_download(
            self, transfer: Transfer, peer_connection: PeerConnection,
            request: PeerTransferRequest.Request):
        """Initializes a download and starts downloading. This method should be
        called after a :class:`.PeerTransferRequest` has been received

        Following steps are taken in this method:

        1. Set the state of the transfer to INITIALIZING
        2. Send a :class:`PeerTransferReply` with allowed set to true

           * In case the message cannot be delivered put the transfer back to
             QUEUED

        3. Create a future for an incoming file connection with the ticket from
           the :class:`PeerTransferRequest` message, await the future

           * In case a timeout occurs waiting for the file connection: put the
             transfer to QUEUED

        4. Calculate the transfer offset and send it

           * In case this fails: put transfer to INCOMPLETE

        5. Start downloading, see :meth:`_download_file` : exception cases are
           handled internally by this method

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
            logger.warning(
                "failed to send transfer reply for ticket %d and transfer : %s", request.ticket, transfer)
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
        transfer.bytes_transfered = offset
        try:
            await file_connection.send_message(uint64(offset).serialize())

        except ConnectionWriteError:
            logger.warning("failed to send offset : %d : %s", offset, transfer)
            if transfer.is_upload():
                await transfer.state.fail()
            else:
                await transfer.state.incomplete()
            return

        except asyncio.CancelledError:
            # Aborted or program shut down
            logger.debug("requested to cancel transfer: %s", transfer)
            await file_connection.disconnect(CloseReason.REQUESTED)
            raise

        if transfer.direction == TransferDirection.DOWNLOAD:
            await self._download_file(transfer, file_connection)
        else:
            await self._upload_file(transfer, file_connection)

    async def _initialize_upload(self, transfer: Transfer):
        """Attempts to initialize and upload to another peer. Following steps
        are taken in this method:

        1. Set the state of the transfer to INITIALIZING
        2. Notify the downloader we are ready to upload a file by sending a
           :class:`.PeerTransferRequest` message, this includes a ticket

           * In case the message cannot be delivered put the transfer back to
             QUEUED

        3. Wait for a response in the form of a :class:`PeerTransferReply`
           message

           * In case no response in received on time: put transfer to QUEUED
           * In case the response message disallows upload: put the transfer to
             FAILED

        4. Open a file connection

           * In case this fails: put transfer to QUEUED

        5. Send the transfer ticket

           * In case this fails: put transfer to QUEUED

        6. Wait for transfer offset

           * In case this fails: put transfer to QUEUED

        7. Start uploading, see :meth:`_upload_file` : exception cases are
           handled internally by this method
        8. Report upload speed to the server : :class:`SendUploadSpeed`
        """
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
            logger.debug("failed to send request to upload : %s : %r", transfer, exc)
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
            logger.debug("timeout waiting for transfer reply : %s", transfer)
            await transfer.state.queue()
            return

        if not response.allowed:
            await transfer.state.fail(reason=response.reason)
            return

        # Create a file connection
        try:
            connection = await self._network.create_peer_connection(
                transfer.username,
                PeerConnectionType.FILE
            )

        except PeerConnectionError:
            logger.info("failed to create peer connection for transfer : %s", transfer)
            await transfer.state.queue()
            return

        # Send transfer ticket
        try:
            await connection.send_message(uint32(ticket).serialize())
        except ConnectionWriteError:
            logger.info("failed to send transfer ticket : %d : %s", ticket, transfer)
            await transfer.state.queue()
            return

        # Receive transfer offset
        try:
            transfer.bytes_transfered = await connection.receive_transfer_offset()
        except ConnectionReadError:
            logger.info("failed to receive transfer offset : %s", transfer)
            await transfer.state.queue()
            return

        else:
            logger.debug("received offset for transfer : %d : %s", transfer.bytes_transfered, transfer)

        await self._upload_file(transfer, connection)

        # Send transfer speed
        if transfer.state.VALUE == TransferState.COMPLETE:
            self._network.queue_server_messages(
                SendUploadSpeed.Request(int(transfer.get_speed()))
            )

    async def _upload_file(self, transfer: Transfer, connection: PeerConnection):
        """Uploads the transfer over the connection. This method will set the
        appropriate states on the passed ``transfer`` and ``connection`` objects

        This method performs the following actions:

        1. Set the state of the transfer to TRANSFERRING
        2. Opens the upload file and set the file pointer to transfer offset

           * In case the file cannot be opened the transfer goes to FAILED

        3. Starts transfering the file

           * In case the local path is not set on the file :

             * Put the transfer to FAILED
             * Disconnect the socket

           * In case an error occurs while reading the file :

             * Put the transfer to FAILED
             * Disconnect the socket

           * In case a network error occurs :

             * Put the transfer to FAILED
             * Send a :class:`PeerUploadFailed` message to the peer

           * In case this task is cancelled :

             * Disconnect the socket

        4. If the file is fully transferred, wait for the other peer to close
           the socket
        5. Verify the that file has been completely transfered

           * In case it is : COMPLETE
           * In case it is not : FAILED

        :param transfer: :class:`.Transfer` object
        :param connection: connection on which file should be sent
        """
        connection.set_connection_state(PeerConnectionState.TRANSFERRING)
        await transfer.state.start_transferring()

        try:
            if not transfer.local_path:
                raise AioSlskException(
                    f"attempted to upload a transfer that doesn't have a local path set : {transfer}")

            async with aiofiles.open(transfer.local_path, mode='rb') as handle:
                await handle.seek(transfer.bytes_transfered)
                await connection.send_file(
                    handle,
                    transfer._transfer_progress_callback
                )

        except OSError:
            logger.exception("error opening local file : %s", transfer.local_path)
            await transfer.state.fail(reason=FailReason.FILE_READ_ERROR)
            await connection.disconnect(CloseReason.REQUESTED)

        except ConnectionWriteError:
            logger.warning("error writing to socket for transfer : %s", transfer)
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
            logger.exception("failed to upload transfer : %s", transfer)
            await transfer.state.fail(FailReason.FILE_NOT_SHARED)

            await connection.disconnect(CloseReason.REQUESTED)

            try:
                await self._network.send_peer_messages(
                    transfer.username,
                    PeerUploadFailed.Request(transfer.remote_path)
                )

            except PeerConnectionError:
                logger.debug("failed to send PeerUploadFailed message (possibly peer went offline)")

        else:
            await connection.receive_until_eof(raise_exception=False)
            if transfer.is_transfered():
                await transfer.state.complete()
            else:
                await transfer.state.fail()

    async def _download_file(self, transfer: Transfer, connection: PeerConnection):
        """Downloads the transfer over the connection. This method will set the
        appropriate states on the passed ``transfer`` and ``connection`` objects.

        This method will:

        1. Calculate and create the download path

           * In case of failure fail the download and disconnect

        2. Set the state of the transfer to TRANSFERRING
        3. Open and start receiving the file, the amount of bytes that are
           expected to be received will be calculated from the offset

           * In case of failure to write to the file: put the transfer to FAILED
           * In case a read error occurred on the socket: put the transfer to INCOMPLETE

        4. Verify the transfer is complete

           * If all bytes are transfered: put the transfer to COMPLETE
           * If not all bytes are transfered: put the transfer to FAIL

        :param transfer: :class:`.Transfer` object of the download
        :param connection: connection on which file should be received
        """
        try:
            await self._prepare_download_path(transfer)
        except OSError:
            logger.exception("failed to create path : %s", transfer.local_path)
            await connection.disconnect(CloseReason.REQUESTED)
            await transfer.state.fail(reason=FailReason.FILE_READ_ERROR)
            return

        connection.set_connection_state(PeerConnectionState.TRANSFERRING)
        await transfer.state.start_transferring()

        if transfer.local_path is None:  # pragma: no cover
            raise AioSlskException(
                f"attempted to start download for which local_path was not set : {transfer}")

        if transfer.filesize is None:  # pragma: no cover
            raise AioSlskException(
                f"attempted to start download for which filesize was not set : {transfer}")

        try:
            async with aiofiles.open(transfer.local_path, mode='ab') as handle:
                await connection.receive_file(
                    handle,
                    transfer.filesize - transfer.bytes_transfered,
                    transfer._transfer_progress_callback
                )

        except OSError:
            logger.exception("error opening local file : %s", transfer.local_path)
            await transfer.state.fail(reason=FailReason.FILE_READ_ERROR)

            await connection.disconnect(CloseReason.REQUESTED)

        except ConnectionReadError as exc:
            logger.warning("error reading from socket : %s", transfer, exc_info=exc)
            await transfer.state.incomplete()

        except asyncio.CancelledError:
            # Aborted or program shut down. The state does not need to be set
            # here as this usually occurs during a state transition (aborting)
            logger.debug("requested to cancel transfer: %s", transfer)
            await connection.disconnect(CloseReason.REQUESTED)
            raise

        else:
            await connection.disconnect(CloseReason.REQUESTED)
            if transfer.is_transfered():
                await transfer.state.complete()
            else:
                await transfer.state.fail(reason=FailReason.CANCELLED)

    async def on_transfer_state_changed(
            self, transfer: Transfer, old: TransferState.State, new: TransferState.State):

        self.request_management_cycle(_RequestFlag.TRANSFER_CHANGE)

    async def _on_message_received(self, event: MessageReceivedEvent):
        message = event.message
        if message.__class__ in self._MESSAGE_MAP:
            await self._MESSAGE_MAP[message.__class__](message, event.connection)

    @on_message(AddUser.Response)
    async def _on_add_user(self, message: AddUser.Response, connection: PeerConnection):
        self.request_management_cycle(_RequestFlag.TRANSFER_CHANGE)

    @on_message(GetUserStatus.Response)
    async def _on_get_user_status(self, message: GetUserStatus.Response, connection: PeerConnection):
        if message.status == UserStatus.OFFLINE.value:
            self._reset_remotely_queued_flags(message.username)

        self.request_management_cycle(_RequestFlag.TRANSFER_CHANGE)

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

        username = connection.username
        filename = message.filename
        direction = TransferDirection.UPLOAD

        if self._settings.users.is_blocked(username, BlockingFlag.UPLOADS):
            connection.queue_message(
                PeerTransferQueueFailed.Request(
                    filename=filename,
                    reason=FailReason.FILE_NOT_SHARED
                )
            )
            return

        transfer = self.find_transfer(username, filename, direction)
        fail_reason = None

        if not transfer:
            try:
                transfer = await self._add_upload(username, filename)

            except (FileNotFoundError, FileNotSharedError):
                fail_reason = FailReason.FILE_NOT_SHARED

            else:
                await transfer.state.queue()

        else:
            shared_item = await self._shares_manager.find_shared_item(
                filename,
                username
            )
            if not shared_item:
                await transfer.state.fail(FailReason.FILE_NOT_SHARED)
                fail_reason = FailReason.FILE_NOT_SHARED

            else:
                # Only put the transfer back in queue if in states:
                # * FAILED: Re-attempt at downloader getting the file
                # * COMPLETE: Re-download of a file
                # In case the state is ABORTED:
                # * Explicitly reply that the transfer has been cancelled
                # In other cases where the message is not allowed (statuses=QUEUED, INITIALIZING, UPLOADING)
                # do not respond with anything. This could otherwise abort the already
                # processing transfer
                if transfer.state.VALUE == TransferState.ABORTED:
                    fail_reason = FailReason.CANCELLED

                elif transfer.state.VALUE in (TransferState.FAILED, TransferState.COMPLETE):
                    await transfer.state.queue()

        if fail_reason:
            connection.queue_message(
                PeerTransferQueueFailed.Request(
                    filename=filename,
                    reason=fail_reason
                )
            )

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
                    "failed to receive transfer ticket on file connection : %s:%d",
                    connection.hostname, connection.port,
                    exc_info=exc
                )
                return

            try:
                self._file_connection_futures[ticket].set_result(connection)

            except KeyError:
                logger.warning("did not find a task waiting for file connection with ticket : %d", ticket)
                await connection.disconnect(CloseReason.REQUESTED)

            except asyncio.InvalidStateError:
                logger.warning("file connection for ticket was already fulfilled : %d", ticket)
                await connection.disconnect(CloseReason.REQUESTED)

    async def _on_session_initialized(self, event: SessionInitializedEvent):
        self.request_management_cycle(_RequestFlag.TRANSFER_CHANGE)

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

        ticket = message.ticket
        username = connection.username
        filename = message.filename
        direction = TransferDirection(message.direction)

        if self._settings.users.is_blocked(username, BlockingFlag.UPLOADS) and direction == TransferDirection.UPLOAD:
            connection.queue_message(
                PeerTransferReply.Request(
                    ticket=message.ticket,
                    allowed=False,
                    reason=FailReason.FILE_NOT_SHARED
                )
            )
            return

        transfer = self.find_transfer(username, filename, direction)

        # Make a decision based on what was requested and what we currently have
        # in our queue
        if direction == TransferDirection.UPLOAD:
            # The other peer is asking us to upload a file. Check if this is not
            # a locked file for the given user and if the item even exists
            if not transfer:
                try:
                    transfer = await self._add_upload(username, filename)

                except (FileNotFoundError, FileNotSharedError):
                    await connection.send_message(
                        PeerTransferReply.Request(
                            ticket=ticket,
                            allowed=False,
                            reason=FailReason.FILE_NOT_SHARED
                        )
                    )

                else:
                    # Send before queueing: queueing will trigger the transfer
                    # manager to re-asses the tranfers and possibly immediatly start
                    # the upload
                    connection.queue_message(
                        PeerTransferReply.Request(
                            ticket=ticket,
                            allowed=False,
                            reason=FailReason.QUEUED
                        )
                    )
                    await transfer.state.queue()

            else:
                # The peer is asking us to upload a file already in our list:
                # this always leads to a refusal of the the request as it is up
                # to us to let the downloader know when we are ready to upload
                shared_item = await self._shares_manager.find_shared_item(
                    filename,
                    username
                )
                if not shared_item:
                    await transfer.state.fail(FailReason.FILE_NOT_SHARED)
                    await connection.send_message(
                        PeerTransferReply.Request(
                            ticket=ticket,
                            allowed=False,
                            reason=FailReason.FILE_NOT_SHARED
                        )
                    )
                    return

                # If the state of transfer is PAUSED, ABORTED, COMPLETE, QUEUED:
                # refuse the request with a specific message
                # In other cases (INITIALIZING, UPLOADING, FAILED) the message
                # simply gets ignored
                # Additional notes:
                # * COMPLETE / FAILED, in reality we could re-queue here
                # * Other clients might abort the transfer when receiving this
                #   message in (at least) UPLOADING state
                fail_reason_map = {
                    TransferState.PAUSED: FailReason.CANCELLED,
                    TransferState.ABORTED: FailReason.CANCELLED,
                    TransferState.COMPLETE: FailReason.COMPLETE,
                    TransferState.QUEUED: FailReason.QUEUED
                }

                reason = fail_reason_map.get(transfer.state.VALUE, None)

                if reason:
                    await connection.send_message(
                        PeerTransferReply.Request(
                            ticket=ticket,
                            allowed=False,
                            reason=reason
                        )
                    )

        else:
            # Request to download (other peer is offering to upload a file)
            # If the transfer is not found, assume we aborted and let the
            # uploader know
            # If the transfer is ABORTED/PAUSED: let the uploader know
            # If the transfer was already COMPLETE: let the upload know
            # If the transfer is currently being processed, ignore the message
            # altogether
            # If the transfer is in FAILED state it needs to be re-queued first;
            # somehow we got this message before being able to queue the
            # transfer. Special note: because this message was received we
            # already know the transfer is remotely queued and set the flag
            # accordingly
            # Finally: if the transfer is in states QUEUED or INCOMPLETE
            # continue with the transfer as we were expecting this message

            reason = None
            if not transfer:
                # A download which we don't have in queue, assume we removed it
                reason = FailReason.CANCELLED
            else:
                current_state = transfer.state.VALUE
                if current_state in (TransferState.ABORTED, TransferState.PAUSED):
                    reason = FailReason.CANCELLED
                elif current_state == TransferState.COMPLETE:
                    reason = FailReason.COMPLETE
                elif transfer.is_processing():
                    # Needs investigation, currently don't do anything when the
                    # transfer is already being processed
                    return
                else:
                    # All good to download

                    if current_state == TransferState.FAILED:
                        await transfer.state.queue(remotely=True)

                    transfer._transfer_task = asyncio.create_task(
                        self._initialize_download(transfer, connection, message),
                        name=f'initialize-download-{task_counter()}'
                    )
                    transfer._transfer_task.add_done_callback(
                        transfer._transfer_task_complete
                    )
                    return

            await connection.send_message(
                PeerTransferReply.Request(
                    ticket=ticket,
                    allowed=False,
                    reason=reason
                )
            )

    @on_message(PeerPlaceInQueueRequest.Request)
    async def _on_peer_place_in_queue_request(
            self, message: PeerPlaceInQueueRequest.Request, connection: PeerConnection):

        if not connection.username:
            logger.warning(
                "got PeerPlaceInQueueRequest for a connection that wasn't properly initialized")
            return

        filename = message.filename
        username = connection.username
        if transfer := self.find_transfer(username, filename, TransferDirection.UPLOAD):
            place = self.get_place_in_queue(transfer)
            if place:
                connection.queue_message(
                    PeerPlaceInQueueReply.Request(filename, place))

        else:
            logger.warning(
                "PeerPlaceInQueueRequest : could not find transfer (upload) for %s from %s",
                filename,
                connection.username
            )

    @on_message(PeerPlaceInQueueReply.Request)
    async def _on_peer_place_in_queue_reply(
            self, message: PeerPlaceInQueueReply.Request, connection: PeerConnection):

        if not connection.username:
            logger.warning(
                "got PeerPlaceInQueueReply for a connection that wasn't properly initialized")
            return

        filename = message.filename
        username = connection.username
        if transfer := self.find_transfer(username, filename, TransferDirection.DOWNLOAD):
            transfer.place_in_queue = message.place

        else:
            logger.warning(
                "PeerPlaceInQueueReply : could not find transfer (download) for %s from %s",
                message.filename,
                connection.username
            )

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

        filename = message.filename
        username = connection.username
        if transfer := self.find_transfer(username, filename, TransferDirection.DOWNLOAD):
            transfer.remotely_queued = False
            self.request_management_cycle(_RequestFlag.TRANSFER_CHANGE)

        else:
            logger.warning(
                "PeerUploadFailed : could not find transfer (download) for %s from %s",
                message.filename,
                connection.username
            )

    @on_message(PeerTransferQueueFailed.Request)
    async def _on_peer_transfer_queue_failed(
            self, message: PeerTransferQueueFailed.Request, connection: PeerConnection):

        if not connection.username:
            logger.warning(
                "got PeerTransferQueueFailed for a connection that wasn't properly initialized")
            return

        username = connection.username
        filename = message.filename
        if transfer := self.find_transfer(username, filename, TransferDirection.DOWNLOAD):
            await transfer.state.fail(reason=message.reason)

        else:
            logger.warning(
                "PeerTransferQueueFailed : could not find transfer for %s from %s",
                filename, connection.username
            )

    async def _add_upload(self, username: str, remote_path: str) -> Transfer:
        """Adds a new upload if the desired shared item exists"""

        shared_item = await self._shares_manager.get_shared_item(
            remote_path, username)

        transfer = Transfer(username, remote_path, direction=TransferDirection.UPLOAD)
        transfer.local_path = shared_item.get_absolute_path()
        transfer.filesize = await self._shares_manager.get_filesize(shared_item)

        await self.add(transfer)
        return transfer

    def _request_shares_cycle(self, event):
        self.request_management_cycle(_RequestFlag.SHARES_CHANGE)

    def _evaluate_aborted_state(self, upload: Transfer) -> tuple[bool, Optional[str]]:
        """Evaluates the aborted state of an upload to determine whether it:

        1. Should be requeued
        2. Should be aborted
        3. Abort reason has changed

        :return: a tuple with whether the transfer should change from aborted to
            queued or the other way around and the blocked reason (None if it
            needs to be requeued)
        """

        def _is_abort_requested(transfer: Transfer) -> bool:
            return transfer.abort_reason == AbortReason.REQUESTED

        def _is_blocked(transfer: Transfer) -> bool:
            return self._settings.users.is_blocked(transfer.username, BlockingFlag.UPLOADS)

        def _is_not_shared(transfer: Transfer) -> bool:
            return not bool(self._shares_manager.find_shared_item_cache(
                transfer.remote_path, transfer.username
            ))

        conditions = (
            (_is_abort_requested, AbortReason.REQUESTED),
            (_is_blocked, AbortReason.BLOCKED),
            (_is_not_shared, AbortReason.FILE_NOT_SHARED)
        )
        abort_reason = None
        for condition, reason in conditions:
            if condition(upload):
                abort_reason = reason
                break

        aborted = upload.state.VALUE == TransferState.ABORTED
        should_change = aborted != bool(abort_reason)

        return (should_change, abort_reason)
