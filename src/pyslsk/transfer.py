from __future__ import annotations
from enum import auto, Enum
from functools import partial
from typing import List, Tuple
import logging
import time

from connection import (
    ConnectionState,
    PeerConnection,
    PeerConnectionType,
    PeerConnectionState,
)
from filemanager import FileManager
from listeners import TransferListener
from messages import (
    pack_int64,
    PeerTransferQueue,
    PeerTransferRequest,
    SendUploadSpeed,
)
from state import State


logger = logging.getLogger()


class TransferDirection(Enum):
    UPLOAD = 0
    DOWNLOAD = 1


class TransferState(Enum):
    VIRGIN = auto()
    QUEUED = auto()
    INITIALIZING = auto()
    INCOMPLETE = auto()
    DOWNLOADING = auto()
    UPLOADING = auto()
    COMPLETE = auto()
    FAILED = auto()


class Transfer:

    def __init__(self, username: str, filename: str, direction: TransferDirection, ticket: int=None, listeners=None):
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
        self.connection = None
        self._fileobj = None

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
        if state in (TransferState.DOWNLOADING, TransferState.UPLOADING):
            self.start_time = time.time()
        elif state in (TransferState.COMPLETE, TransferState.INCOMPLETE):
            self.complete_time = time.time()

        self.state = state

        for listener in self.state_listeners:
            listener.on_transfer_state_changed(self, state)

    def set_offset(self, offset: int):
        self._offset = offset

    def fail(self, reason: str=None):
        """Sets the internal state to TransferState.FAILED with an optional
        reason for failure
        """
        self.set_state(TransferState.FAILED)
        self.fail_reason = reason

    def queue(self, place_in_queue=None):
        self.set_state(TransferState.QUEUED)
        self.place_in_queue = place_in_queue

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

    def is_closed(self) -> bool:
        return self.state in (TransferState.COMPLETE, )

    def is_processing(self) -> bool:
        return self.state in (TransferState.DOWNLOADING, TransferState.UPLOADING, TransferState.INITIALIZING, )

    def is_all_data_transfered(self) -> bool:
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

        return self.is_all_data_transfered()

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


class TransferManager(TransferListener):

    def __init__(self, state: State, settings, file_manager: FileManager, network_manager: 'NetworkManager'):
        self._state = state
        self.settings = settings
        self.upload_slots: int = settings['sharing']['limits']['upload_slots']
        self.download_slots: int = settings['sharing']['limits']['download_slots']
        self._transfers: List[Transfer] = []

        self._file_manager: FileManager = file_manager
        self._network_manager: 'NetworkManager' = network_manager

        self._network_manager.transfer_listener = self

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
        return 0 if available_slots < 0 else available_slots

    def get_free_download_slots(self) -> int:
        """Get the amount of free download slots"""
        downloading_transfers = []
        for transfer in self._transfers:
            if transfer.direction == TransferDirection.DOWNLOAD and transfer.is_processing():
                downloading_transfers.append(transfer)

        available_slots = self.download_slots - len(downloading_transfers)
        return 0 if available_slots < 0 else available_slots

    def get_queue_size(self) -> int:
        return len([
            transfer for transfer in self._transfers
            if transfer.state == TransferState.QUEUED
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

    def queue_transfer(self, transfer: Transfer, state: TransferState=TransferState.QUEUED):
        for queued_transfer in self._transfers:
            if not queued_transfer.equals(transfer):
                continue

            # Attempt to resume transfering in case upload is incomplete.
            # There should be some logic here for checking if the file is
            # complete on disk
            if queued_transfer.state == TransferState.INCOMPLETE:
                pass

        self._transfers.append(transfer)
        transfer.state_listeners.append(self)
        if state is not None:
            transfer.set_state(state)

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

    def get_transfer(self, filename: str, direction: TransferDirection) -> Transfer:
        for transfer in self._transfers:
            if transfer.filename == filename and transfer.direction == direction:
                return transfer
        raise LookupError(
            f"transfer with filename {filename} (direction={direction}) not found")

    def on_transfer_state_changed(self, transfer: Transfer, state: TransferState):
        # Prevent infinite loop
        if state == TransferState.INITIALIZING:
            return

        to_download, to_upload = self.get_next_transfers()

        for download in to_download:
            download.set_state(TransferState.INITIALIZING)
            self.initialize_download(download)

        for upload in to_upload:
            upload.set_state(TransferState.INITIALIZING)
            self.initialize_upload(upload)

    def get_next_transfers(self) -> Tuple[List[Transfer], List[Transfer]]:
        """Get the next transfers to initialize"""
        free_download_slots = self.get_free_download_slots()
        free_upload_slots = self.get_free_upload_slots()

        queued_uploads = [
            transfer for transfer in self._transfers
            if transfer.state == TransferState.QUEUED and transfer.direction == TransferDirection.UPLOAD
        ]

        queued_downloads = [
            transfer for transfer in self._transfers
            if transfer.state == TransferState.QUEUED and transfer.direction == TransferDirection.DOWNLOAD
        ]

        to_download = queued_downloads[:free_download_slots]
        to_upload = queued_uploads[:free_upload_slots]

        return to_download, to_upload

    def initialize_download(self, transfer: Transfer):
        connection_ticket = next(self._state.ticket_generator)

        self._network_manager.init_peer_connection(
            connection_ticket,
            transfer.username,
            PeerConnectionType.PEER,
            messages=[
                PeerTransferQueue.create(transfer.filename)
            ]
        )

    def initialize_upload(self, transfer: Transfer):
        connection_ticket = next(self._state.ticket_generator)

        self._network_manager.init_peer_connection(
            connection_ticket,
            transfer.username,
            PeerConnectionType.PEER,
            messages=[
                PeerTransferRequest.create(
                    TransferDirection.DOWNLOAD.value,
                    transfer.ticket,
                    transfer.filename,
                    filesize=transfer.filesize
                )
            ]
        )

    def on_transfer_offset(self, offset: int, connection: PeerConnection):
        logger.info(f"received transfer offset (offset={offset})")

        transfer = connection.transfer
        if transfer is None:
            logger.error(f"got a transfer offset for a connection without transfer. connection={connection!r}")
            return

        transfer.set_offset(offset)
        transfer.filesize = self._file_manager.get_filesize(transfer.filename)

        connection.set_connection_state(PeerConnectionState.TRANSFERING)

    def on_transfer_ticket(self, ticket: int, connection: PeerConnection):
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
            pack_int64(0),
            callback=partial(connection.set_connection_state, PeerConnectionState.TRANSFERING)
        )

    def on_transfer_data_received(self, data: bytes, connection: PeerConnection):
        """Called when data has been received in the context of a transfer.
        If the download path hasn't been set yet (ie. it is the first data we
        received for this transfer) it will be determined and data will start to
        be written.

        This method also checks whether the transfer has been completed and
        closes the connection.
        """
        transfer = self.get_transfer_by_connection(connection)

        if transfer.state != TransferState.DOWNLOADING:
            transfer.set_state(TransferState.DOWNLOADING)

        if transfer.target_path is None:
            download_path = self._file_manager.get_download_path(transfer.filename.decode('utf-8'))
            transfer.target_path = download_path
            logger.info(f"started receiving transfer data, download path : {download_path}")

        is_all_data_transfered = transfer.write(data)
        if is_all_data_transfered:
            transfer.complete()
            logger.info(f"completed downloading of {transfer.filename} from {transfer.username} to {transfer.target_path}")
            connection.set_state(ConnectionState.SHOULD_CLOSE)
            transfer.connection = None

    def on_transfer_data_sent(self, bytes_sent: int, connection: PeerConnection):
        transfer = self.get_transfer_by_connection(connection)

        if transfer.state != TransferState.UPLOADING:
            transfer.set_state(TransferState.UPLOADING)

        transfer.bytes_transfered += bytes_sent
        if transfer.is_all_data_transfered():
            transfer.complete()
            logger.info(
                f"completed uploading of {transfer.filename} to {transfer.username}. "
                f"filesize={transfer.filesize}, transfered={transfer.bytes_transfered}, read={transfer.bytes_read}")
            transfer.connection = None

            # NOT closing connection here, this the responsibility of the
            # downloading side. Closing here would cause the download to be
            # incomplete

            self._network_manager.send_server_messages(
                SendUploadSpeed.create(int(self.get_average_upload_speed()))
            )

    def on_transfer_connection_closed(self, connection: PeerConnection, close_reason=None):
        # Handle broken downloads
        try:
            transfer = self.get_transfer_by_connection(connection)
        except LookupError:
            logger.warning(
                f"couldn't find transfer associated with closed connection (connection={connection!r})")
        else:
            if transfer.state != TransferState.COMPLETE:
                transfer.set_state(TransferState.INCOMPLETE)
