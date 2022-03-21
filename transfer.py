from enum import auto, Enum
import time

from typing import List, Tuple


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

    def is_processing(self) -> bool:
        return self.state in (TransferState.DOWNLOADING, TransferState.UPLOADING, TransferState.INITIALIZING, )

    def is_complete(self) -> bool:
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

        return self.is_complete()

    def complete(self):
        self.set_state(TransferState.COMPLETE)
        self.close()

    def close(self):
        if self._fileobj is not None:
            self._fileobj.close()
            self._fileobj = None


class TransferManager:

    def __init__(self, settings):
        self.settings = settings
        self.upload_slots: int = settings['sharing']['limits']['upload_slots']
        self.download_slots: int = settings['sharing']['limits']['download_slots']
        self._transfers: List[Transfer] = []

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

    def queue_transfer(self, transfer: Transfer):
        self._transfers.append(transfer)
        transfer.state_listeners.append(self)
        transfer.set_state(TransferState.QUEUED)

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
        pass

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

        for transfer in to_download + to_upload:
            transfer.set_state(TransferState.INITIALIZING)

        return to_download, to_upload
