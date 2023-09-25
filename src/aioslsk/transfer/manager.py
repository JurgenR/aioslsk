from __future__ import annotations
import aiofiles
import asyncio
from dataclasses import dataclass
import logging
from operator import itemgetter
import os
from typing import Dict, List, Tuple, TYPE_CHECKING

from .cache import TransferCache, TransferShelveCache
from ..configuration import Configuration
from ..constants import TRANSFER_REPLY_TIMEOUT
from ..exceptions import (
    ConnectionReadError,
    ConnectionWriteError,
    FileNotFoundError,
    FileNotSharedError,
    PeerConnectionError,
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
    InternalEventBus,
    MessageReceivedEvent,
    PeerInitializedEvent,
    TrackUserEvent,
    TransferAddedEvent,
    UntrackUserEvent,
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
    SendUploadSpeed,
    PeerUploadFailed,
)
from .model import Transfer, TransferDirection
from .state import TransferState
from ..model import UserStatus, TrackingFlag
from ..settings import Settings
from ..shares.manager import SharesManager
from ..state import State
from ..utils import task_counter, ticket_generator

if TYPE_CHECKING:
    from ..network.network import Network


logger = logging.getLogger(__name__)


@dataclass
class TransferRequest:
    """Class representing a request to start transferring. An object will be
    created when the PeerTransferRequest is sent or received and should be
    destroyed once the transfer ticket has been received or a reply sent that
    the transfer cannot continue.

    It completes once the ticket is received or sent on the file connection
    """
    ticket: int
    transfer: Transfer


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

        self._cache: TransferCache = TransferShelveCache(self._configuration.data_directory)

        self._transfer_requests: Dict[int, TransferRequest] = {}
        self._transfers: List[Transfer] = []

        self.MESSAGE_MAP = build_message_map(self)

        self._internal_event_bus.register(MessageReceivedEvent, self._on_message_received)
        self._internal_event_bus.register(PeerInitializedEvent, self._on_peer_initialized)

    async def read_cache(self) -> List[Transfer]:
        transfers: List[Transfer] = self._cache.read()
        for transfer in transfers:
            # Analyze the current state of the stored transfers and set them to
            # the correct state
            transfer.remotely_queued = False
            if transfer.state.VALUE == TransferState.INITIALIZING:
                transfer.state.queue()

            elif transfer.is_transferring():
                if transfer.is_transfered():
                    state = TransferState.COMPLETE
                else:
                    state = TransferState.INCOMPLETE
                transfer.state = TransferState.init_from_state(state)
                transfer.reset_times()

            await self._add_transfer(transfer)

    def write_cache(self):
        self._cache.write(self._transfers)

    def stop(self):
        """Cancel all current transfer actions"""
        for transfer in self.transfers:
            if transfer._current_task:
                transfer._current_task.cancel()

    @property
    def transfers(self):
        return self._transfers

    @property
    def upload_slots(self):
        return self._settings.get('sharing.limits.upload_slots')

    async def abort(self, transfer: Transfer):
        """Aborts the given transfer"""
        transfer.state.abort()
        if transfer._current_task is not None:
            transfer._current_task.cancel()
        await self.manage_transfers()

    async def queue(self, transfer: Transfer):
        """Places given transfer on the queue"""
        transfer.state.queue()
        await self.manage_transfers()

    async def _initializing(self, transfer: Transfer):
        transfer.state.initialize()
        await self.manage_transfers()

    async def _incomplete(self, transfer: Transfer):
        transfer.state.incomplete()
        await self.manage_transfers()

    async def _complete(self, transfer: Transfer):
        transfer.state.complete()
        await self.manage_transfers()

    async def _fail(self, transfer: Transfer, reason: str = None):
        transfer.state.fail(reason = reason)
        await self.manage_transfers()

    async def _uploading(self, transfer: Transfer):
        transfer.state.start_transferring()
        await self.manage_transfers()

    async def _downloading(self, transfer: Transfer):
        transfer.state.start_transferring()
        await self.manage_transfers()

    async def _add_transfer(self, transfer: Transfer) -> Transfer:
        for queued_transfer in self._transfers:
            if queued_transfer == transfer:
                logger.info(f"skip adding transfer, already exists : {queued_transfer!r}")
                return queued_transfer

        logger.info(f"adding transfer : {transfer!r}")
        self._transfers.append(transfer)
        await self._event_bus.emit(TransferAddedEvent(transfer))
        return transfer

    async def add(self, transfer: Transfer) -> Transfer:
        """Adds a transfer if it does not already exist, otherwise it returns
        the already existing transfer. This method will emit a
        `TransferAddedEvent` only if the transfer did not exist

        :return: either the transfer we have passed or the already existing
            transfer
        """
        transfer = await self._add_transfer(transfer)

        await self.manage_transfers()
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

    async def get_place_in_queue(self, transfer: Transfer) -> int:
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
        """Lookup transfer by username, remote_path and transfer direction"""
        req_transfer = Transfer(username, remote_path, direction)
        for transfer in self._transfers:
            if transfer == req_transfer:
                return transfer
        raise LookupError(
            f"transfer for user {username} and remote_path {remote_path} (direction={direction}) not found")

    async def manage_user_tracking(self):
        """Remove or add user tracking based on the list of transfers. This
        method will untrack users for which there are no more unfinished
        transfers and start tracking users for which there are unfinished
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
            await self._internal_event_bus.emit(
                TrackUserEvent(username, TrackingFlag.TRANSFER)
            )
        for username in finished_users - unfinished_users:
            await self._internal_event_bus.emit(
                UntrackUserEvent(username, TrackingFlag.TRANSFER)
            )

    async def manage_transfers(self):
        """Manages the transfers. This method analyzes the state of the current
        downloads/uploads and starts them up in case there are free slots
        available
        """
        await self.manage_user_tracking()

        downloads, uploads = self._get_queued_transfers()
        free_upload_slots = self.get_free_upload_slots()

        # Downloads will just get remotely queued
        for download in downloads:
            if download._current_task:
                continue

            if download.remotely_queued:
                continue

            download._current_task = asyncio.create_task(
                self._queue_remotely(download),
                name=f'queue-remotely-{task_counter()}'
            )
            download._current_task.add_done_callback(download._queue_remotely_task_complete)

        for upload in uploads[:free_upload_slots]:
            if not upload._current_task:
                upload._current_task = asyncio.create_task(
                    self._initialize_upload(upload),
                    name=f'initialize-upload-{task_counter()}'
                )
                upload._current_task.add_done_callback(upload._upload_task_complete)

    def _get_queued_transfers(self) -> Tuple[List[Transfer], List[Transfer]]:
        """Returns all transfers eligable for being initialized

        :return: a tuple containing 2 lists: the eligable downloads and eligable
            uploads
        """
        queued_downloads = []
        queued_uploads = []
        for transfer in self._transfers:
            user = self._state.get_or_create_user(transfer.username)
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
            transfer.remotely_queued = True
            transfer.reset_queue_attempts()
            await self.manage_transfers()

    async def _request_place_in_queue(self, transfer: Transfer):
        await self._network.send_peer_messages(
            transfer.username,
            PeerPlaceInQueueRequest.Request(transfer.remote_path)
        )

    async def _initialize_upload(self, transfer: Transfer):
        """Notifies the peer we are ready to upload the file for the given
        transfer
        """
        logger.debug(f"initializing upload {transfer!r}")
        await self._initializing(transfer)

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
            await self.queue(transfer)
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
            await self.queue(transfer)
            return

        if not response.allowed:
            await self._fail(transfer, reason=response.reason)
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
        self._network.queue_server_messages(
            SendUploadSpeed.Request(int(self.get_average_upload_speed()))
        )

    async def _upload_file(self, transfer: Transfer, connection: PeerConnection):
        """Uploads the transfer over the connection. This method will set the
        appropriate states on the passed `transfer` and `connection` objects.

        :param transfer: `Transfer` object
        :param connection: connection on which file should be sent
        """
        connection.set_connection_state(PeerConnectionState.TRANSFERRING)
        await self._uploading(transfer)
        try:
            async with aiofiles.open(transfer.local_path, 'rb') as handle:
                await handle.seek(transfer.get_offset())
                await connection.send_file(
                    handle,
                    transfer._transfer_progress_callback
                )

        except OSError:
            logger.exception(f"error opening on local file : {transfer.local_path}")
            await self._fail(transfer)
            await connection.disconnect(CloseReason.REQUESTED)

        except ConnectionWriteError:
            logger.exception(f"error writing to socket : {transfer!r}")
            await self._fail(transfer)
            # Possible this needs to be put in a task or just queued, if the
            # peer went offline it's possible we are hogging the _current_task
            # for nothing (sending the peer message could time out)
            await self._network.send_peer_messages(
                PeerUploadFailed.Request(transfer.remote_path)
            )
        else:
            await connection.receive_until_eof(raise_exception=False)
            if transfer.is_transfered():
                await self._complete(transfer)
            else:
                await self._fail(transfer)

    async def _download_file(self, transfer: Transfer, connection: PeerConnection):
        """Downloads the transfer over the connection. This method will set the
        appropriate states on the passed `transfer` and `connection` objects.

        :param transfer: `Transfer` object
        :param connection: connection on which file should be received
        """
        connection.set_connection_state(PeerConnectionState.TRANSFERRING)
        await self._downloading(transfer)

        try:
            path, _ = os.path.split(transfer.local_path)
            await self._shares_manager.create_directory(path)
        except OSError:
            logger.exception(f"failed to create path {path}")
            await connection.disconnect(CloseReason.REQUESTED)
            await self._fail(transfer)
            return

        try:
            async with aiofiles.open(transfer.local_path, 'ab') as handle:
                await connection.receive_file(
                    handle,
                    transfer.filesize - transfer._offset,
                    transfer._transfer_progress_callback
                )

        except OSError:
            logger.exception(f"error opening on local file : {transfer.local_path}")
            await connection.disconnect(CloseReason.REQUESTED)
            await self._fail(transfer)

        except ConnectionReadError:
            logger.exception(f"error reading from socket : {transfer:!r}")
            await self._incomplete(transfer)

        else:
            await connection.disconnect(CloseReason.REQUESTED)
            if transfer.is_transfered():
                await self._complete(transfer)
            else:
                await self._incomplete(transfer)

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
        except ConnectionReadError as exc:
            logger.warning(f"failed to receive transfer ticket on file connection : {connection.hostname}:{connection.port}", exc_info=exc)
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
                transfer._download_task_complete
            )
            await self._initializing(transfer)

        # Calculate and send the file offset
        offset = transfer.calculate_offset()
        try:
            await connection.send_message(uint64(offset).serialize())
        except ConnectionWriteError:
            logger.warning(f"failed to send offset: {transfer!r}")
            if transfer.is_upload():
                await self._fail(transfer)
            else:
                await self._incomplete(transfer)
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
            item = self._shares_manager.get_shared_item(
                message.filename, connection.username)
            transfer.local_path = item.get_absolute_path()
            transfer.filesize = self._shares_manager.get_filesize(item)
        except (FileNotFoundError, FileNotSharedError):
            await self._fail(transfer, reason="File not shared.")
            await connection.queue_message(
                PeerTransferQueueFailed.Request(
                    filename=message.filename,
                    reason=transfer.fail_reason
                )
            )
        else:
            await self.queue(transfer)

    async def _on_peer_initialized(self, event: PeerInitializedEvent):
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
            # The other peer is asking us to upload a file. Check if this is not
            # a locked file for the given user
            try:
                self._shares_manager.get_shared_item(
                    message.filename, username=connection.username)
            except (FileNotFoundError, FileNotSharedError):
                await connection.queue_message(
                    PeerTransferReply.Request(
                        ticket=message.ticket,
                        allowed=False,
                        reason='Failed'
                    )
                )
                if transfer:
                    await self._fail(transfer, "File not shared.")
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
                # All good to download
                # Possibly needs a check to see if there's any inconsistencies
                # normally we get this response when we were the one requesting
                # to download so ideally all should be fine here.
                request = TransferRequest(message.ticket, transfer)
                self._transfer_requests[message.ticket] = request

                transfer.filesize = message.filesize
                if transfer.local_path is None:
                    download_path, file_path = self._shares_manager.calculate_download_path(transfer.remote_path)
                    transfer.local_path = os.path.join(download_path, file_path)

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
    #             self._fail(transfer, reason=message.reason)
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
            await self._fail(transfer)

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
            await self._fail(transfer, reason=reason)