from __future__ import annotations
import asyncio
from async_timeout import timeout as atimeout
from enum import auto, Enum
from typing import BinaryIO, Callable, List, Optional, TYPE_CHECKING, Union
import logging
import socket
import struct

from ..constants import (
    PEER_CONNECT_TIMEOUT,
    PEER_READ_TIMEOUT,
    SERVER_CONNECT_TIMEOUT,
    TRANSFER_TIMEOUT,
)
from ..exceptions import (
    ConnectionFailedError,
    ConnectionReadError,
    ConnectionWriteError,
    MessageDeserializationError,
    MessageSerializationError,
)
from ..protocol import obfuscation
from ..protocol.primitives import uint32, uint64, MessageDataclass
from ..protocol.messages import (
    DistributedMessage,
    PeerInitializationMessage,
    PeerMessage,
    ServerMessage,
)
from ..utils import task_counter

if TYPE_CHECKING:
    from .rate_limiter import RateLimiter
    from .network import Network


logger = logging.getLogger(__name__)

DEFAULT_RECV_BUF_SIZE = 8
"""Default amount of bytes to recv from the socket"""
TRANSFER_RECV_BUF_SIZE = 1024 * 8
"""Default amount of bytes to recv during file transfer"""
TRANSFER_SEND_BUF_SIZE = 1024 * 8
"""Default amount of bytes to send during file transfer"""
HEADER_SIZE_OBFUSCATED: int = obfuscation.KEY_SIZE + struct.calcsize('I')
HEADER_SIZE_UNOBFUSCATED: int = struct.calcsize('I')


class PeerConnectionType:
    FILE = 'F'
    PEER = 'P'
    DISTRIBUTED = 'D'


class ConnectionState(Enum):
    UNINITIALIZED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    CLOSING = auto()
    CLOSED = auto()


class CloseReason(Enum):
    UNKNOWN = auto()
    CONNECT_FAILED = auto()
    REQUESTED = auto()
    READ_ERROR = auto()
    WRITE_ERROR = auto()
    TIMEOUT = auto()
    EOF = auto()


class PeerConnectionState(Enum):
    AWAITING_INIT = auto()
    """No init message has been received yet (PeerInit, PeerPierceFirewall)"""
    ESTABLISHED = auto()
    """Message connections: ready to receive / send data"""
    AWAITING_TICKET = auto()
    """Transfer connections: awaiting the transfer ticket"""
    AWAITING_OFFSET = auto()
    """Transfer connections: awaiting the transfer offset"""
    TRANSFERRING = auto()
    """Transfer connections: ready to receive / send data"""


class Connection:

    def __init__(self, hostname: str, port: int, network: Network):
        self.hostname: str = hostname
        self.port: int = port
        self.network: Network = network
        self.state: ConnectionState = ConnectionState.UNINITIALIZED

    async def set_state(self, state: ConnectionState, close_reason: CloseReason = CloseReason.UNKNOWN):
        self.state = state
        await self.network.on_state_changed(state, self, close_reason=close_reason)

    def _is_closing(self) -> bool:
        return self.state in (ConnectionState.CLOSING, ConnectionState.CLOSED)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(hostname={self.hostname!r}, port={self.port}, "
            f"state={self.state})")


class ListeningConnection(Connection):
    """A listening connection, objects of this class are responsible for
    accepting incoming connections from peers
    """

    def __init__(self, hostname: str, port: int, network: Network, obfuscated: bool = False):
        super().__init__(hostname, port, network)
        self.obfuscated: bool = obfuscated

        self._server: Optional[asyncio.AbstractServer] = None
        self.connections_accepted: int = 0

    async def disconnect(self, reason: CloseReason = CloseReason.UNKNOWN):
        logger.debug(f"{self.hostname}:{self.port} : disconnecting : {reason.name}")
        await self.set_state(ConnectionState.CLOSING, close_reason=reason)
        try:
            if self._server is not None:
                if self._server.is_serving():
                    self._server.close()
                await self._server.wait_closed()

        except Exception as exc:
            logger.warning(
                f"{self.hostname}:{self.port} : exception while disconnecting", exc_info=exc)

        finally:
            self._server = None
            logger.debug(f"{self.hostname}:{self.port} : disconnected : {reason.name}")
            await self.set_state(ConnectionState.CLOSED, close_reason=reason)

    async def connect(self):
        """Open a listening connection on the current `hostname` and `port`

        :raise ConnectionFailedError: raised when binding failed
        """
        logger.info(
            f"open {self.hostname}:{self.port} : listening connection")
        await self.set_state(ConnectionState.CONNECTING)

        try:
            self._server = await asyncio.start_server(
                self.accept,
                self.hostname,
                self.port,
                family=socket.AF_INET,
                start_serving=True
            )

        except OSError:
            await self.disconnect(CloseReason.CONNECT_FAILED)
            raise ConnectionFailedError(f"{self.hostname}:{self.port} : failed to connect")

        await self.set_state(ConnectionState.CONNECTED)

    async def accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        hostname, port = writer.get_extra_info('peername')
        logger.debug(f"{self.hostname}:{self.port} : accepted connection {hostname}:{port}")
        connection = PeerConnection(
            hostname, port, self.network,
            obfuscated=self.obfuscated,
            connection_type=PeerConnectionType.PEER,
            incoming=True
        )
        connection._reader, connection._writer = reader, writer
        await self.network.on_peer_accepted(connection)
        await connection.set_state(ConnectionState.CONNECTED)


class DataConnection(Connection):
    """Connection for message and data transfer"""

    def __init__(self, hostname: str, port: int, network: Network, obfuscated: bool = False):
        super().__init__(hostname, port, network)
        self.obfuscated = obfuscated

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._reader_task: Optional[asyncio.Task] = None
        self.read_timeout: Optional[float] = None
        self._queued_messages: List[asyncio.Task] = []

    def get_connecting_ip(self) -> str:
        """Gets the IP address being used to connect to the server/peer.

        The connection needs to be established for this method to work
        """
        return self._writer.get_extra_info('sockname')[0]

    async def connect(self, timeout: float = 30):
        """Opens a TCP connection the hostname:ip provided in this object. The
        state of the connection will be changed to CONNECTING before the attempt
        is made

        Upon success the `state` will be set to CONNECTED and the message
        reader loop will be started. Upon failure the state will be set to
        CLOSED with CONNECT_FAILED as its reason

        :param timeout: timeout in seconds before giving up (default: 30)
        :raise ConnectionFailedError: raised when connection failed or timed out
        """
        logger.info(f"{self.hostname}:{self.port} : connecting")
        await self.set_state(ConnectionState.CONNECTING)

        try:
            async with atimeout(timeout):
                self._reader, self._writer = await asyncio.open_connection(
                    self.hostname, self.port)

        except (Exception, asyncio.TimeoutError) as exc:
            await self.disconnect(CloseReason.CONNECT_FAILED)
            raise ConnectionFailedError(f"{self.hostname}:{self.port} : failed to connect") from exc

        else:
            logger.debug(f"{self.hostname}:{self.port} : connected")
            await self.set_state(ConnectionState.CONNECTED)

    async def disconnect(self, reason: CloseReason = CloseReason.UNKNOWN):
        """Disconnects the TCP connection. The method will not raise an
        exception in case the connection wasn't yet connected

        :param reason: optional reason for the disconnect. This parameter is
            purely informational
        """
        # Prevents this method being called twice during the process of
        # disconnecting. This is necessary because during disconnecting the
        # reader task throw an EOF and attempt to call this method again.
        if self.state in (ConnectionState.CLOSED, ConnectionState.CLOSING):
            return

        await self.set_state(ConnectionState.CLOSING, close_reason=reason)
        logger.debug(f"{self.hostname}:{self.port} : disconnecting : {reason.name}")
        self._cancel_queued_messages()
        try:
            if self._writer is not None:
                if not self._writer.is_closing():
                    self._writer.close()
                await self._writer.wait_closed()

        except Exception as exc:
            logger.warning(f"{self.hostname}:{self.port} : exception while disconnecting : {exc}")

        finally:
            await self.set_state(ConnectionState.CLOSED, close_reason=reason)
            # Because disconnect can be called when read failed setting the
            # reader task to none should be done last
            self._reader_task = None
            self._reader = None
            self._writer = None

    def start_reader_task(self):
        self._reader_task = asyncio.create_task(self._message_reader_loop())

    def stop_reader_task(self):
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None

    # Read/write methods

    async def _read_until_eof(self):
        await self._reader.read(-1)

    async def receive_until_eof(self, raise_exception=True):
        try:
            return await self._read(self._read_until_eof)
        except ConnectionReadError:
            if raise_exception:
                raise

    async def _message_reader_loop(self):
        """Message reader loop. This will loop until the connection is closed or
        the network is closed
        """
        while not self._is_closing():
            try:
                message_data = await self.receive_message()
                if message_data:
                    message = self.decode_message_data(message_data)

            except ConnectionReadError:
                logger.warning(f"{self.hostname}:{self.port} : read error")

            except MessageDeserializationError:
                logger.warning(f"{self.hostname}:{self.port} : failed to deserialize message")

            else:
                # Do not handle messages when closing/closed
                if not self._is_closing():
                    if message:
                        await self._perform_message_callback(message)

    async def _read_message(self):
        header_size = HEADER_SIZE_OBFUSCATED if self.obfuscated else HEADER_SIZE_UNOBFUSCATED

        async with atimeout(self.read_timeout):
            header = await self._reader.readexactly(header_size)

        message_len_buf = obfuscation.decode(header) if self.obfuscated else header
        _, message_len = uint32.deserialize(0, message_len_buf)

        async with atimeout(self.read_timeout):
            message = await self._reader.readexactly(message_len)

        return header + message

    async def receive_message_object(self) -> Optional[MessageDataclass]:
        message_data = await self.receive_message()
        if message_data:
            return self.decode_message_data(message_data)
        else:
            return None

    async def receive_message(self) -> Optional[bytes]:
        """Receives a single raw message"""
        return await self._read(self._read_message)

    def decode_message_data(self, data: bytes) -> MessageDataclass:
        """De-obfuscates and deserializes message data into a `MessageDataclass`
        object. See `deserialize_message`

        :param data: message bytes to decode
        :return: object of `MessageDataclass`
        :raise MessageDeserializationError: raised when deserialization failed
        """
        if self.obfuscated:
            data = obfuscation.decode(data)

        try:
            message = self.deserialize_message(data)
        except Exception as exc:
            logger.exception(f"{self.hostname}:{self.port} : failed to deserialize message : {data.hex()}")
            raise MessageDeserializationError("failed to deserialize message") from exc

        return message

    def encode_message_data(self, message: Union[bytes, MessageDataclass]) -> bytes:
        """Serializes the `MessageDataclass` or `bytes` and obfuscates the
        contents. See `serialize_message`

        :return: `bytes` object
        :raise MessageSerializationError: raised when serialization failed
        """
        try:
            data = self.serialize_message(message)
        except Exception as exc:
            logger.exception(f"{self.hostname}:{self.port} : failed to serialize message : {message!r}")
            raise MessageSerializationError("failed to serialize Message") from exc

        if self.obfuscated:
            data = obfuscation.encode(data)

        return data

    async def _perform_message_callback(self, message: MessageDataclass):
        logger.debug(f"{self.hostname}:{self.port} : received message : {message!r}")
        try:
            await self.network.on_message_received(message, self)
        except Exception:
            logger.exception(f"error during callback : {message!r}")

    async def _read(self, reader_func, timeout: Optional[float] = None) -> Optional[bytes]:
        """Read data from the connection using the passed `reader_func`. When an
        error occurs during reading the connection will be CLOSED

        :param reader_func: callable that reads the data
        :return: the return value of the `reader_func`, None if EOF
        :raise ConnectionReadError: upon any kind of read error/timeout
        """
        try:
            if timeout:
                async with atimeout(timeout):
                    return await reader_func()
            else:
                return await reader_func()

        except asyncio.IncompleteReadError as exc:
            if exc.partial:
                await self.disconnect(CloseReason.READ_ERROR)
                raise ConnectionReadError(
                    f"{self.hostname}:{self.port} : incomplete read on connection : {exc.partial!r}") from exc
            else:
                await self.disconnect(CloseReason.EOF)
                return None

        except asyncio.TimeoutError as exc:
            await self.disconnect(CloseReason.TIMEOUT)
            raise ConnectionReadError(f"{self.hostname}:{self.port} : read timeout") from exc

        except Exception as exc:
            await self.disconnect(CloseReason.READ_ERROR)
            raise ConnectionReadError(f"{self.hostname}:{self.port} : exception during reading") from exc

    def queue_message(self, message: Union[bytes, MessageDataclass]) -> asyncio.Task:
        task = asyncio.create_task(
            self.send_message(message),
            name=f'queue-message-task-{task_counter()}'
        )
        self._queued_messages.append(task)
        task.add_done_callback(self._queued_messages.remove)
        return task

    def queue_messages(self, *messages: Union[bytes, MessageDataclass]) -> List[asyncio.Task]:
        return [
            self.queue_message(message)
            for message in messages
        ]

    def _cancel_queued_messages(self):
        for qmessage_task in self._queued_messages:
            qmessage_task.cancel()

    async def send_message(self, message: Union[bytes, MessageDataclass]):
        """Sends a message or a set of bytes over the connection. In case an
        object of `MessageDataClass` is provided the object will first be
        serialized. If the `obfuscated` flag is set for the connection the
        message or bytes will first be obfuscated

        :param message: message to be sent over the connection
        :raise ConnectionWriteError: error or timeout occured during writing
        """
        if self._is_closing():
            logger.warning(
                f"{self.hostname}:{self.port} : not sending message, connection is closing / closed : {message!r}")
            return

        logger.debug(f"{self.hostname}:{self.port} : send message : {message!r}")
        # Serialize the message
        try:
            data = self.encode_message_data(message)
        except MessageSerializationError:
            return

        # Perform actual send
        try:
            self._writer.write(data)
            async with atimeout(10):
                await self._writer.drain()

        except asyncio.TimeoutError as exc:
            await self.disconnect(CloseReason.TIMEOUT)
            raise ConnectionWriteError(f"{self.hostname}:{self.port} : write timeout") from exc

        except Exception as exc:
            await self.disconnect(CloseReason.WRITE_ERROR)
            raise ConnectionWriteError(f"{self.hostname}:{self.port} : exception during writing") from exc

    def deserialize_message(self, message_data: bytes) -> MessageDataclass:
        """Should be called after a full message has been received. This method
        should parse the message
        """
        raise NotImplementedError(
            "'deserialize_message' should be overwritten by a subclass")

    def serialize_message(self, message: Union[bytes, MessageDataclass]) -> bytes:
        if isinstance(message, MessageDataclass):
            return message.serialize()
        else:
            return message


class ServerConnection(DataConnection):

    async def connect(self, timeout: float = SERVER_CONNECT_TIMEOUT):
        await super().connect(timeout=timeout)
        # self.start_reader_task()

    def deserialize_message(self, message_data: bytes) -> MessageDataclass:
        return ServerMessage.deserialize_response(message_data)


class PeerConnection(DataConnection):

    def __init__(
            self, hostname: str, port: int, network: Network, obfuscated: bool = False,
            username: Optional[str] = None, connection_type: str = PeerConnectionType.PEER,
            incoming: bool = False):
        super().__init__(hostname, port, network, obfuscated=obfuscated)
        self.incoming: bool = incoming
        self.connection_state = PeerConnectionState.AWAITING_INIT

        self.username: Optional[str] = username
        self.connection_type: str = connection_type
        self.read_timeout = PEER_READ_TIMEOUT

        self.download_rate_limiter: Optional[RateLimiter] = None
        self.upload_rate_limiter: Optional[RateLimiter] = None

    async def connect(self, timeout: float = PEER_CONNECT_TIMEOUT):
        await super().connect(timeout=timeout)

    def set_connection_state(self, state: PeerConnectionState):
        """Sets the current connection state.

        If the current state is AWAITING_INIT and the connection type is a
        distributed or file connection the `obfuscated` flag for this connection
        will be set to `False`

        If the state goes to the ESTABLISHED state the message reader task will
        be started. In all other cases it will be stopped (in case the task was
        running)

        :param state: The new state of the connection
        """
        # Set non-peer connections to non-obfuscated
        if state != PeerConnectionState.AWAITING_INIT:
            if self.connection_type != PeerConnectionType.PEER:
                self.obfuscated = False

        if state == PeerConnectionState.ESTABLISHED:
            self.start_reader_task()
        else:
            # This shouldn't occur, during all other states we call the
            # receive_* methods directly. But it can do no harm
            self.stop_reader_task()

        logger.debug(f"{self.hostname}:{self.port} setting state to {state} : {self!r}")
        self.connection_state = state

    async def _read_transfer_ticket(self) -> bytes:
        return await self._reader.readexactly(struct.calcsize('I'))

    async def _read_transfer_offset(self) -> bytes:
        return await self._reader.readexactly(struct.calcsize('Q'))

    async def receive_transfer_ticket(self) -> int:
        """Receive the transfer ticket from the connection"""
        data = await self._read(self._read_transfer_ticket)
        _, ticket = uint32.deserialize(0, data)
        return ticket

    async def receive_transfer_offset(self) -> int:
        """Receive the transfer offset from the connection"""
        data = await self._read(self._read_transfer_offset)
        _, offset = uint64.deserialize(0, data)
        return offset

    async def receive_data(self, n_bytes: int, timeout: float = TRANSFER_TIMEOUT) -> Optional[bytes]:
        """Receives given amount of bytes on the connection.

        In case of error the socket will be disconnected. If no data is received
        it is assumed to be EOF and the connection will be disconnected.

        :param n_bytes: amount of bytes to receive
        :param timeout: timeout in seconds
        :raise ConnectionReadError: in case timeout occured on an error on the
            socket
        :return: `bytes` object containing the received data
        """
        try:
            async with atimeout(timeout):
                data = await self._reader.read(n_bytes)

        except asyncio.TimeoutError as exc:
            await self.disconnect(CloseReason.TIMEOUT)
            raise ConnectionReadError(f"{self.hostname}:{self.port} : timeout writing") from exc

        except Exception as exc:
            await self.disconnect(CloseReason.READ_ERROR)
            raise ConnectionReadError(f"{self.hostname}:{self.port} : read error") from exc

        else:
            if not data:
                await self.disconnect(CloseReason.EOF)
                return None
            else:
                return data

    async def receive_file(
            self, file_handle: BinaryIO, filesize: int, callback: Optional[Callable[[bytes], None]] = None):
        """Receives a file on the current connection and writes it to the given
        `file_handle`

        This method will attempt to keep reading data until EOF is received from
        the connection or the amount of received bytes has reached the `filesize`

        :param file_handle: a file handle to write the received data to
        :param filesize: expected filesize
        :param callback: optional callback that gets called each time a chunk
            of data is received
        """
        bytes_received = 0
        while True:
            bytes_to_read = await self.download_rate_limiter.take_tokens()
            data = await self.receive_data(bytes_to_read)
            if data is None:
                return

            await file_handle.write(data)
            if callback is not None:
                callback(data)

            # Check if all data received and return
            bytes_received += len(data)
            if bytes_received >= filesize:
                return

    async def send_data(self, data: bytes):
        try:
            self._writer.write(data)
            async with atimeout(TRANSFER_TIMEOUT):
                await self._writer.drain()

        except asyncio.TimeoutError as exc:
            await self.disconnect(CloseReason.TIMEOUT)
            raise ConnectionWriteError(f"{self.hostname}:{self.port} : timeout writing") from exc

        except Exception as exc:
            await self.disconnect(CloseReason.WRITE_ERROR)
            raise ConnectionWriteError(f"{self.hostname}:{self.port} : write error") from exc

    async def send_file(self, file_handle: BinaryIO, callback: Optional[Callable[[bytes], None]] = None):
        """Sends a file over the connection. This method makes use of the
        `upload_rate_limiter` to limit how many bytes are being sent at a time.

        :param file_handle: binary opened file handle
        :param callback: progress callback that gets called each time a chunk
            of data was sent
        """
        while True:
            bytes_to_write = await self.upload_rate_limiter.take_tokens()
            data = await file_handle.read(bytes_to_write)
            if not data:
                return

            await self.send_data(data)
            if callback is not None:
                callback(data)

    def deserialize_message(self, message_data: bytes) -> MessageDataclass:
        if self.connection_state == PeerConnectionState.AWAITING_INIT:
            return PeerInitializationMessage.deserialize_request(message_data)

        else:
            if self.connection_type == PeerConnectionType.PEER:
                return PeerMessage.deserialize_request(message_data)
            else:
                return DistributedMessage.deserialize_request(message_data)

    def __repr__(self):
        return (
            f"{self.__class__.__name__}("
            f"hostname={self.hostname!r}, port={self.port}, state={self.state}, "
            f"incoming={self.incoming}, obfuscated={self.obfuscated}, username={self.username!r}, "
            f"connection_state={self.connection_state}, connection_type={self.connection_type!r})")
