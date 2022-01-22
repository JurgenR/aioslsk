import enum
import time


class TransferDirection(enum.Enum):
    UPLOAD = 0
    DOWNLOAD = 1


class TransferState(enum.Enum):
    UNINITIALIZED = -1
    REQUESTED = 0
    QUEUED = 1
    DOWNLOADING = 2
    UPLOADING = 3
    COMPLETE = 4
    FAILED = 5


class Transfer:

    def __init__(self, username: str, filename: str, direction: TransferDirection, ticket=None):
        self.state = TransferState.UNINITIALIZED

        self.username: str = username
        self.filename: str = filename
        """Filename of the remote file"""
        self.direction: TransferDirection = direction

        self.ticket: int = ticket
        self.filesize: int = None
        """Filesize in bytes"""

        self.target_path: str = None
        self.bytes_transfered: int = 0
        """Amount of bytes transfered"""
        self.bytes_written: int = 0
        """Amount of bytes written to file"""
        self.connection = None
        self._fileobj = None

        self.transfer_start_time: float = None
        """Time at which the transfer was started. This is the time the transfer
        entered the download or upload state
        """
        self.transfer_complete_time: float = None
        """Time at which the transfer was completed. This is the time the
        transfer entered the complete state.
        """

    def set_state(self, state: TransferState):
        if state == self.state:
            return

        if state in (TransferState.DOWNLOADING, TransferState.UPLOADING):
            self.transfer_start_time = time.time()
        elif state == TransferState.COMPLETE:
            self.transfer_complete_time = time.time()
        self.state = state

    def get_speed(self) -> float:
        """Retrieve the speed of the transfer

        @return: Zero if the transfer has not yet begun. The current speed if
            the transfer is ongoing. The transfer speed if the transfer was
            complete. Bytes per second
        """
        if self.transfer_start_time is None:
            return 0.0

        if self.transfer_complete_time is None:
            # Transfer in progress
            end_time = time.time()
        else:
            end_time = self.transfer_complete_time
        transfer_duration = end_time - self.transfer_start_time

        return self.bytes_transfered / transfer_duration

    def is_complete(self) -> bool:
        return self.filesize == self.bytes_transfered

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

        self._fileobj.write(data)
        self.bytes_written += len(data)

        is_complete = self.is_complete()
        if is_complete:
            self.set_state(TransferState.COMPLETE)
            self.finalize()

        return is_complete

    def finalize(self):
        if self._fileobj is not None:
            self._fileobj.close()


class TransferQueue:
    pass


class TransferManager:

    def __init__(self):
        self._transfers = []

    @property
    def transfers(self):
        return self._transfers

    def has_slots_free(self):
        return True

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
