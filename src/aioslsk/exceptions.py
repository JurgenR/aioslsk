class AioSlskException(Exception):
    pass


class UnknownMessageError(AioSlskException):

    def __init__(self, message_id: int, data: bytes, message):
        self.message_id = message_id
        self.data = data
        self.message = message


class MessageSerializationError(AioSlskException):
    pass


class FileError(AioSlskException):
    pass


class FileNotFoundError(FileError):
    pass


class FileNotSharedError(FileError):
    pass


class NetworkError(AioSlskException):
    pass


class PeerConnectionError(NetworkError):
    pass


class ConnectionFailedError(NetworkError):
    pass


class ConnectionReadError(NetworkError):
    pass


class ConnectionWriteError(NetworkError):
    pass


class IncompleteFileReceiveError(NetworkError):
    pass
