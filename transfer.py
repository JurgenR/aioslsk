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


class TransferManager:

    def __init__(self):
        self.transfers = {}


class Transfer:

    def __init__(self, ticket: int, username: str, filename: str, direction):
        self.state = TransferState.UNINITIALIZED
        self.username = username
        self.filename = filename
        self.ticket = ticket
        self.direction = direction
