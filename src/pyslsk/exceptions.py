class PySlskException(Exception):
    pass


class UnknownMessageError(PySlskException):

    def __init__(self, message_id: int, data: bytes, message):
        self.message_id = message_id
        self.data = data
        self.message = message


class MessageSerializationError(PySlskException):
    pass


class FileNotSharedError(PySlskException):
    pass


class PeerConnectionError(PySlskException):
    pass


class ConnectionFailedError(PySlskException):
    pass


class ConnectionReadError(PySlskException):
    pass


class ConnectionWriteError(PySlskException):
    pass
