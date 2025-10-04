from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .transfer.state import TransferState
    from .transfer.model import Transfer


class AioSlskException(Exception):
    pass


class AuthenticationError(AioSlskException):

    def __init__(self, reason: str, message: str):
        self.reason: str = reason
        self.message: str = message


class InvalidSessionError(AioSlskException):
    """Raised when trying to execute a command but the user is not logged in"""


class NoSuchUserError(AioSlskException):
    pass


class UnknownMessageError(AioSlskException):

    def __init__(self, message_id: int, data: bytes, message: str):
        self.message_id: int = message_id
        self.data: bytes = data
        self.message: str = message


class MessageSerializationError(AioSlskException):
    pass


class MessageDeserializationError(AioSlskException):

    def __init__(self, proto_message: bytes, message: str) -> None:
        self.proto_message: bytes = proto_message
        self.message: str = message


class FileError(AioSlskException):
    pass


class FileNotFoundError(FileError):
    pass


class FileNotSharedError(FileError):
    pass


class SharedDirectoryError(AioSlskException):
    pass


class TransferException(AioSlskException):
    pass


class TransferNotFoundError(TransferException):
    pass


class InvalidStateTransition(TransferException):

    def __init__(
            self, transfer: Transfer,
            current: TransferState.State, desired: TransferState.State,
            message: str = "could not make the desired state transition"):
        self.transfer = transfer
        self.current: TransferState.State = current
        self.desired: TransferState.State = desired

        self.message: str = message


class RequestPlaceFailedError(AioSlskException):
    pass


class NetworkError(AioSlskException):
    pass


class PeerConnectionError(NetworkError):
    pass


class ConnectionFailedError(NetworkError):
    pass


class ListeningConnectionFailedError(NetworkError):
    pass


class ConnectionReadError(NetworkError):
    pass


class ConnectionWriteError(NetworkError):
    pass
