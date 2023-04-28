import asyncio
import struct
from ..protocol.primitives import uint32
from ..protocol import obfuscation
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .connection import DataConnection


HEADER_SIZE_OBFUSCATED: int = obfuscation.KEY_SIZE + struct.calcsize('I')
HEADER_SIZE_UNOBFUSCATED: int = struct.calcsize('I')


class ProtocolReader:

    def __init__(self, connection: DataConnection, timeout: float = None):
        self.connection = connection
        self.timeout = timeout


class MessageReader(ProtocolReader):

    async def read(self):
        header_size = HEADER_SIZE_OBFUSCATED if self.obfuscated else HEADER_SIZE_UNOBFUSCATED
        header = await asyncio.wait_for(
            self._reader.readexactly(header_size), self.read_timeout)

        message_len_buf = obfuscation.decode(header) if self.obfuscated else header
        _, message_len = uint32.deserialize(0, message_len_buf)

        message = await asyncio.wait_for(
            self._reader.readexactly(message_len), self.read_timeout)

        return header + message


class FileReader(ProtocolReader):
    pass
