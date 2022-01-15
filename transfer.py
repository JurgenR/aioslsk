import enum


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


class Transfer:

    def __init__(self, username: str, filename: str, direction: TransferDirection, ticket=None):
        self.state = TransferState.UNINITIALIZED

        self.username: str = username
        self.filename: str = filename
        self.direction: TransferDirection = direction

        self.ticket: int = ticket
        self.filesize: int = None

        self.target_path: str = None
        self.bytes_transfered: int = 0
        self.bytes_written: int = 0
        self.connection = None
        self._fileobj = None

    def set_state(self, state: TransferState):
        self.state = state

    def is_complete(self) -> bool:
        return self.filesize == self.bytes_transfered

    def write(self, data: bytes) -> bool:
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
