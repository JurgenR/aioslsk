from enum import auto, Enum
import time

from typing import List


class TransferDirection(Enum):
    UPLOAD = 0
    DOWNLOAD = 1


class TransferState(Enum):
    UNINITIALIZED = auto()
    QUEUED = auto()
    INCOMPLETE = auto()
    DOWNLOADING = auto()
    UPLOADING = auto()
    COMPLETE = auto()
    FAILED = auto()


class Transfer:

    def __init__(self, username: str, filename: str, direction: TransferDirection, ticket: int=None):
        self.state = TransferState.QUEUED

        self.username: str = username
        self.filename: str = filename
        """Filename of the remote file"""
        self.direction: TransferDirection = direction
        self.place_in_queue: int = None

        self.ticket: int = ticket
        self.filesize: int = None
        """Filesize in bytes"""
        self._offset: int = None
        """Offset used for resuming downloads. This offset will be used and
        reset by the L{read} method of this object
        """

        self.fail_reason: str = None

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
        transfer entered the complete state.
        """

    def set_state(self, state: TransferState):
        if state == self.state:
            return

        if state in (TransferState.DOWNLOADING, TransferState.UPLOADING):
            self.start_time = time.time()
        elif state == TransferState.COMPLETE:
            self.complete_time = time.time()
        self.state = state

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

        return self.bytes_transfered / transfer_duration

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
        self.bytes_written += len(bytes_written)

        return self.is_complete()

    def finalize(self):
        self.set_state(TransferState.COMPLETE)
        if self._fileobj is not None:
            self._fileobj.close()


class TransferQueue:
    pass


class TransferManager:

    def __init__(self, settings):
        self.settings = settings
        self._transfers = []

    @property
    def transfers(self):
        return self._transfers

    def has_slots_free(self) -> bool:
        return True

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
        return sum([
            transfer.get_speed() for transfer in self.get_downloading()
        ])

    def get_upload_speed(self) -> float:
        return sum([
            transfer.get_speed() for transfer in self.get_uploading()
        ])

    def get_average_upload_speed(self) -> float:
        upload_speeds = [
            transfer.get_speed() for transfer in self._transfers
            if transfer.state == TransferState.COMPLETE and transfer.direction == TransferDirection.UPLOAD
        ]
        return sum(upload_speeds) / len(upload_speeds)

    def queue_transfer(self, transfer: Transfer):
        self.add(transfer)

    def add(self, transfer: Transfer):
        self._transfers.append(transfer)

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
