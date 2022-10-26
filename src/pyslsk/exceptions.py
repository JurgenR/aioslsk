class PySlskException(Exception):
    pass


class UnknownMessageError(PySlskException):

    def __init__(self, message_id: int, data: bytes, message):
        self.message_id = message_id
        self.data = data
        self.message = message


class FileNotSharedError(PySlskException):
    pass
