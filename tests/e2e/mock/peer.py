from __future__ import annotations
import asyncio
import logging
from typing import Optional, TYPE_CHECKING
from aioslsk.protocol.primitives import uint32
from aioslsk.protocol.messages import MessageDataclass, ServerMessage
from tests.e2e.mock.constants import HEADER_SIZE
from tests.e2e.mock.model import User


if TYPE_CHECKING:
    from server import MockServer


logger = logging.getLogger(__name__)


class Peer:

    def __init__(
            self, hostname: str, port: int, server: MockServer,
            reader: asyncio.StreamReader = None, writer: asyncio.StreamWriter = None):
        self.hostname: str = hostname
        self.port: int = port
        self.server = server

        self.user: User = None

        self.reader: asyncio.StreamReader = reader
        self.writer: asyncio.StreamWriter = writer
        self.reader_loop = None

        self.should_close: bool = False
        self.last_ping: float = 0.0

        self.client_version: Optional[int] = None
        self.minor_version: Optional[int] = None

        self.branch_level: Optional[int] = None
        self.branch_root: Optional[str] = None
        self.child_depth: Optional[int] = None

    async def disconnect(self):
        logger.debug(f"{self.hostname}:{self.port} : disconnecting")
        self.stop_reader_loop()
        try:
            if self.writer is not None:
                if not self.writer.is_closing():
                    self.writer.close()
                await self.writer.wait_closed()
        except Exception:
            logger.exception(f"{self.hostname}:{self.port} : exception while disconnecting")

        finally:
            self.writer = None
            self.reader = None
            await self.server.on_peer_disconnected(self)

    def start_reader_loop(self):
        self.reader_loop = asyncio.create_task(
            self._message_reader_loop(),
            name=f'reader-loop-{self.hostname}:{self.port}'
        )

    def stop_reader_loop(self):
        if self.reader_loop:
            self.reader_loop.cancel()
            self.reader_loop = None

    async def receive_message(self):
        header = await self.reader.readexactly(HEADER_SIZE)
        _, message_len = uint32.deserialize(0, header)
        message = await self.reader.readexactly(message_len)
        return header + message

    async def _message_reader_loop(self):
        """Message reader loop. This will loop until the connection is closed or
        the network is closed
        """
        while True:
            try:
                message_data = await self.receive_message()
            except Exception as exc:
                logger.warning(f"{self.hostname}:{self.port} : read error : {exc!r}")
                await self.disconnect()
                break
            else:
                if not message_data:
                    logger.info(f"{self.hostname}:{self.port} : no data received")
                    continue

                try:
                    message = ServerMessage.deserialize_request(message_data)
                except Exception:
                    logger.exception(f"{self.hostname}:{self.port} : failed to parse message data : {message_data.hex()}")
                else:
                    logger.info(f"{self.hostname}:{self.port}: receive : {message!r}")
                    try:
                        await self.server.on_peer_message(message, self)
                    except Exception:
                        logger.exception(f"failed to handle message : {message}")

    async def send_message(self, message: MessageDataclass):
        if self.writer is None:
            logger.warning(f"{self.hostname}:{self.port} : disconnected, not sending message : {message!r}")
            return

        logger.debug(f"{self.hostname}:{self.port} : send message : {message!r}")
        data = message.serialize()

        try:
            self.writer.write(data)
            await self.writer.drain()

        except Exception:
            logger.exception(f"failed to send message {message}")
            await self.disconnect()
