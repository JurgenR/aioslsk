class PySlskException(Exception):
    pass


class UnknownMessageError(PySlskException):

    def __init__(self, message_id: bytes, data: int, message):
        self.message_id = message_id
        self.data = data
        self.message = message
