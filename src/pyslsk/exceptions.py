class PySlskException(Exception):
    pass


class UnknownMessageError(PySlskException):

    def __init__(self, message_id: int, data: bytes, message):
        self.message_id = message_id
        self.data = data
        self.message = message


class MessageSerializationError(PySlskException):
    pass


class FileError(PySlskException):
    pass


class FileNotFoundError(FileError):
    pass


class FileNotSharedError(FileError):
    pass


class NetworkError(PySlskException):
    pass


class PeerConnectionError(NetworkError):
    pass


class ConnectionFailedError(NetworkError):
    pass


class ConnectionReadError(NetworkError):
    pass


class ConnectionWriteError(NetworkError):
    pass


class NoSuchUserError(PySlskException):
    pass


class LoginFailedError(PySlskException):
    pass
