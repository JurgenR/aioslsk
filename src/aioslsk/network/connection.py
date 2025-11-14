from __future__ import annotations
import abc
from aiofiles.threadpool.binary import AsyncBufferedIOBase, AsyncBufferedReader
import asyncio
from async_timeout import Timeout, timeout as atimeout
from collections.abc import Awaitable, Callable
from enum import auto, Enum
from typing import Optional, TYPE_CHECKING, Union
import logging
import socket
import struct
import sys

from ..constants import (
    DEFAULT_READ_TIMEOUT,
    DISCONNECT_TIMEOUT,
    PEER_CONNECT_TIMEOUT,
    PEER_READ_TIMEOUT,
    SERVER_CONNECT_TIMEOUT,
    SERVER_READ_TIMEOUT,
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
from ..log_utils import ConnectionLoggerAdapter
from ..utils import task_counter
from .rate_limiter import RateLimiter, UnlimitedRateLimiter

if TYPE_CHECKING:
    from .network import Network


logger = logging.getLogger(__name__)
adapter = ConnectionLoggerAdapter(logger, {})


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
    NEGOTIATING_TRANSFER = auto()
    """Transfer connections: negotiating the transfer ticket / offset"""
    TRANSFERRING = auto()
    """Transfer connections: ready to receive / send data"""


class Connection(abc.ABC):

    _CLOSING_STATES: tuple[ConnectionState, ConnectionState] = (
        ConnectionState.CLOSING, ConnectionState.CLOSED)

    def __init__(self, hostname: str, port: int, network: Network):
        self.hostname: str = hostname
        self.port: int = port
        self.network: Network = network
        self.state: ConnectionState = ConnectionState.UNINITIALIZED
        self._is_closing: bool = False

    @abc.abstractmethod
    async def disconnect(self, reason: CloseReason = CloseReason.UNKNOWN):
        ...

    async def set_state(self, state: ConnectionState, close_reason: CloseReason = CloseReason.UNKNOWN):
        self.state = state
        self._is_closing = state in self._CLOSING_STATES
        await self.network.on_state_changed(state, self, close_reason=close_reason)

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

    async def disconnect(self, reason: CloseReason = CloseReason.UNKNOWN):
        adapter.debug("disconnecting : %s", reason.name, extra=self.__dict__)
        await self.set_state(ConnectionState.CLOSING, close_reason=reason)
        try:
            if self._server is not None:
                if self._server.is_serving():
                    self._server.close()

                async with atimeout(DISCONNECT_TIMEOUT):
                    await self._server.wait_closed()

        except Exception as exc:
            adapter.warning(
                "exception while disconnecting", extra=self.__dict__, exc_info=exc)

        finally:
            self._server = None
            adapter.info("disconnected : %s", reason.name, extra=self.__dict__)
            await self.set_state(ConnectionState.CLOSED, close_reason=reason)

    async def connect(self):
        """Open a listening connection on the current :attr:`hostname` and
        :attr:`port`

        :raise ConnectionFailedError: raised when binding failed
        """
        adapter.info("open listening connection", extra=self.__dict__)
        await self.set_state(ConnectionState.CONNECTING)

        try:
            self._server = await asyncio.start_server(
                self.accept,
                self.hostname,
                self.port,
                family=socket.AF_INET,
                start_serving=True,
                reuse_address=sys.platform != 'win32'
            )

        except OSError as exc:
            adapter.exception("failed to bind listening port", extra=self.__dict__)
            await self.disconnect(CloseReason.CONNECT_FAILED)
            raise ConnectionFailedError(f"{self.hostname}:{self.port} : failed to connect") from exc

        await self.set_state(ConnectionState.CONNECTED)

    async def accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        hostname, port = writer.get_extra_info('peername')

        adapter.debug(
            "accepted connection : %s:%d", hostname, port, extra=self.__dict__)

        connection = PeerConnection(
            hostname, port, self.network,
            obfuscated=self.obfuscated,
            connection_type=PeerConnectionType.PEER,
            incoming=True
        )
        connection._reader, connection._writer = reader, writer
        await self.network.on_peer_accepted(connection)
        await connection.set_state(ConnectionState.CONNECTED)


class DataConnection(Connection, abc.ABC):
    """Connection for message and data transfer"""

    def __init__(
            self, hostname: str, port: int, network: Network,
            obfuscated: bool = False, read_timeout: float = DEFAULT_READ_TIMEOUT):

        super().__init__(hostname, port, network)
        self.obfuscated = obfuscated

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._reader_task: Optional[asyncio.Task] = None

        self._queued_messages: list[asyncio.Task] = []
        self._read_timeout_object: Optional[Timeout] = None

        self.read_timeout: float = read_timeout

    def get_connecting_ip(self) -> str:
        """Gets the IP address being used to connect to the server/peer.

        The connection needs to be established for this method to work
        """
        if not self._writer:  # pragma: no cover
            raise RuntimeError("connection not initialized")

        return self._writer.get_extra_info('sockname')[0]

    async def connect(self, timeout: float = 30):
        """Opens a TCP connection the hostname:ip provided in this object. The
        state of the connection will be changed to ``CONNECTING`` before the
        attempt is made

        Upon success the :attr:`state` will be set to ``CONNECTED`` and the
        message reader loop will be started. Upon failure the state will be set
        to ``CLOSED`` with ``CONNECT_FAILED`` as its reason

        :param timeout: timeout in seconds before giving up (default: 30)
        :raise ConnectionFailedError: raised when connection failed or timed out
        """
        adapter.info("connecting", extra=self.__dict__)
        await self.set_state(ConnectionState.CONNECTING)

        try:
            async with atimeout(timeout):
                self._reader, self._writer = await asyncio.open_connection(
                    self.hostname, self.port)

        except (Exception, asyncio.TimeoutError) as exc:
            await self.disconnect(CloseReason.CONNECT_FAILED)
            raise ConnectionFailedError(f"{self.hostname}:{self.port} : failed to connect") from exc

        else:
            adapter.debug("connected", extra=self.__dict__)
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
        adapter.debug("disconnecting : %s", reason.name, extra=self.__dict__)
        self._cancel_queued_messages()
        try:
            if self._writer is not None:
                if not self._writer.is_closing():
                    self._writer.close()

                async with atimeout(DISCONNECT_TIMEOUT):
                    await self._writer.wait_closed()

        except Exception as exc:
            adapter.warning(
                "exception while disconnecting : %r", exc, extra=self.__dict__)

        finally:
            await self.set_state(ConnectionState.CLOSED, close_reason=reason)
            # Because disconnect can be called when read failed setting the
            # reader task to none should be done last
            self._reader_task = None
            self._reader = None
            self._writer = None

    def start_reader_task(self):
        """Starts the message reader task"""
        self._reader_task = asyncio.create_task(self._message_reader_loop())

    def stop_reader_task(self):
        """Stops the message reader task if it exists"""
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None

    # Read/write methods

    async def _message_reader_loop(self):
        """Message reader loop. This will loop until the connection is closed or
        the network is closed
        """
        while not self._is_closing:
            try:
                message = await self.receive_message_object()

            except ConnectionReadError:
                adapter.warning("read error", extra=self.__dict__)

            except MessageDeserializationError as exc:
                adapter.warning(
                    "failed to deserialize message : %s", exc.proto_message, extra=self.__dict__)

            else:

                if not message:
                    return

                # Do not handle messages when closing/closed
                if self._is_closing:
                    adapter.warning(
                        "connection is closing, skipping handling message : %s",
                        message,
                        extra=self.__dict__
                    )
                else:
                    await self._perform_message_callback(message)

    async def _read(
            self, reader_coro: Awaitable[Optional[bytes]],
            timeout: Optional[float] = None) -> Optional[bytes]:
        """Read data from the connection using the passed ``reader_coro``. When
        an error occurs during reading the connection will be CLOSED

        :param reader_coro: coroutine that reads the data
        :return: the return value of the ``reader_coro``, ``None`` if EOF
        :raise ConnectionReadError: upon any kind of read error/timeout
        """
        try:
            if timeout:
                # TODO: change the type of `_read_timeout_object` to `asyncio.timeouts.Timeout`
                # when 3.11 is the oldest supported Python version
                async with atimeout(timeout) as self._read_timeout_object:  # type: ignore[assignment]
                    data = await reader_coro
            else:
                data = await reader_coro

        except asyncio.IncompleteReadError as exc:
            # Can only be raised by `readexactly`
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

        else:
            if not data:
                await self.disconnect(CloseReason.EOF)
                return None
            else:
                return data

    async def _read_message(self) -> bytes:
        if not self._reader:
            raise ConnectionReadError(
                f"{self.hostname}:{self.port} : cannot read message, connection is not open")

        header_size = HEADER_SIZE_OBFUSCATED if self.obfuscated else HEADER_SIZE_UNOBFUSCATED

        header = await self._reader.readexactly(header_size)

        message_len_buf = obfuscation.decode(header) if self.obfuscated else header
        _, message_len = uint32.deserialize(0, message_len_buf)

        message = await self._reader.readexactly(message_len)

        return header + message

    async def receive_message(self) -> Optional[bytes]:
        """Receives a single raw message

        :return: The message as a ``bytes`` object. ``None`` if the connection
            returned EOF
        """
        return await self._read(self._read_message(), timeout=self.read_timeout)

    async def receive_message_object(self) -> Optional[MessageDataclass]:
        """Receives a single message and parses it to a :class:`.MessageDataclass`

        :return: The parsed message, ``None`` if the connection returned EOF
        """
        message_data = await self.receive_message()

        if message_data:
            message = self.decode_message_data(message_data)
            adapter.debug(
                "received message : %s",
                message,
                extra={
                    **self.__dict__,
                    **{'message_type': message.__class__}
                }
            )
            return message

        return None

    async def receive_until_eof(self, raise_exception: bool = True) -> Optional[bytes]:
        """Receives data until the other end closes the connection. If
        ``raise_exception`` parameter is set to ``True`` other read errors are
        treated as EOF as well
        """
        if not self._reader:
            raise ConnectionReadError(
                f"{self.hostname}:{self.port} : cannot read until EOF, connection is not open")

        # Note: _read raises ConnectionReadError also on IncompleteReadError,
        # however when using StreamReader.read this error can never be raised
        # and thus this method shouldn't worry about potentially not returning
        # partial data
        try:
            return await self._read(self._reader.read(-1))
        except ConnectionReadError:
            if raise_exception:
                raise

            return b''

    def queue_message(self, message: Union[bytes, MessageDataclass]) -> asyncio.Task:
        task = asyncio.create_task(
            self.send_message(message),
            name=f'queue-message-task-{task_counter()}'
        )
        self._queued_messages.append(task)
        task.add_done_callback(self._queued_messages.remove)
        return task

    def queue_messages(self, *messages: Union[bytes, MessageDataclass]) -> list[asyncio.Task]:
        return [
            self.queue_message(message)
            for message in messages
        ]

    async def _send(self, data: bytes, timeout: Optional[float] = None):
        if not self._writer:
            raise ConnectionWriteError(
                f"{self.hostname}:{self.port} : cannot send data, connection is not open")

        try:
            self._writer.write(data)
            if timeout:
                async with atimeout(timeout):
                    await self._writer.drain()
            else:
                await self._writer.drain()

        except asyncio.TimeoutError as exc:
            await self.disconnect(CloseReason.TIMEOUT)
            raise ConnectionWriteError(f"{self.hostname}:{self.port} : write timeout") from exc

        except Exception as exc:
            await self.disconnect(CloseReason.WRITE_ERROR)
            raise ConnectionWriteError(f"{self.hostname}:{self.port} : exception during writing") from exc

    async def send_message(self, message: Union[bytes, MessageDataclass]):
        """Sends a message or a set of bytes over the connection. In case an
        object of :class:`.MessageDataClass` is provided the object will first
        be serialized. If the :attr:`obfuscated` flag is set for the connection
        the message or bytes will first be obfuscated

        :param message: message to be sent over the connection
        :raise ConnectionWriteError: error or timeout occured during writing
        """
        if self._is_closing:
            adapter.warning(
                "not sending message, connection is closing / closed : %s",
                message,
                extra=self.__dict__
            )
            return

        adapter.debug(
            "send message : %s",
            message,
            extra={
                **self.__dict__,
                **{'message_type': message.__class__}
            }
        )
        # Serialize the message
        try:
            data = self.encode_message_data(message)
        except MessageSerializationError:
            adapter.exception("failed to serialize message : %s", message)
            return

        await self._send(data, timeout=10)
        self._increase_read_timeout()

    def encode_message_data(self, message: Union[bytes, MessageDataclass]) -> bytes:
        """Serializes the :class:`.MessageDataclass` or ``bytes`` and obfuscates
        the contents. See :meth:`serialize_message`

        :return: ``bytes`` object
        :raise MessageSerializationError: raised when serialization failed
        """
        try:
            data = self.serialize_message(message)
        except Exception as exc:
            raise MessageSerializationError("failed to serialize message") from exc

        if self.obfuscated:
            data = obfuscation.encode(data)

        return data

    def decode_message_data(self, data: bytes) -> MessageDataclass:
        """De-obfuscates and deserializes message data into a
        :class:`.MessageDataclass` object. See :meth:`deserialize_message`

        :param data: message bytes to decode
        :return: object of :class:`.MessageDataclass`
        :raise MessageDeserializationError: raised when deserialization failed
        """
        if self.obfuscated:
            data = obfuscation.decode(data)

        try:
            message = self.deserialize_message(data)
        except Exception as exc:
            raise MessageDeserializationError(data, "failed to deserialize message") from exc

        return message

    @abc.abstractmethod
    def deserialize_message(self, message_data: bytes) -> MessageDataclass:
        """Should be called after a full message has been received. This method
        should parse the message
        """

    def serialize_message(self, message: Union[bytes, MessageDataclass]) -> bytes:
        if isinstance(message, MessageDataclass):
            return message.serialize()
        else:
            return message

    def _increase_read_timeout(self):
        if self.read_timeout and self._read_timeout_object:
            try:
                self._read_timeout_object.shift(self.read_timeout)
            except RuntimeError:
                pass

    async def _perform_message_callback(self, message: MessageDataclass):
        try:
            await self.network.on_message_received(message, self)
        except Exception:
            adapter.exception("error during callback : %s", message, extra=self.__dict__)

    def _cancel_queued_messages(self):
        for qmessage_task in self._queued_messages:
            qmessage_task.cancel()


class ServerConnection(DataConnection):

    def __init__(
            self, hostname: str, port: int, network: Network,
            obfuscated: bool = False, read_timeout: float = SERVER_READ_TIMEOUT):

        super().__init__(
            hostname, port, network,
            obfuscated=obfuscated, read_timeout=read_timeout)

    async def connect(self, timeout: float = SERVER_CONNECT_TIMEOUT):
        await super().connect(timeout=timeout)

    def deserialize_message(self, message_data: bytes) -> MessageDataclass:
        return ServerMessage.deserialize_response(message_data)


class PeerConnection(DataConnection):

    def __init__(
            self, hostname: str, port: int, network: Network, obfuscated: bool = False,
            username: Optional[str] = None, connection_type: str = PeerConnectionType.PEER,
            incoming: bool = False, read_timeout: float = PEER_READ_TIMEOUT,
            transfer_read_timeout: float = TRANSFER_TIMEOUT):

        super().__init__(
            hostname, port, network,
            obfuscated=obfuscated, read_timeout=read_timeout)

        self.transfer_read_timeout: float = transfer_read_timeout

        self.incoming: bool = incoming
        self.connection_state = PeerConnectionState.AWAITING_INIT
        self.connection_type: str = connection_type

        self.username: Optional[str] = username

        self.download_rate_limiter: RateLimiter = UnlimitedRateLimiter()
        self.upload_rate_limiter: RateLimiter = UnlimitedRateLimiter()

    async def connect(self, timeout: float = PEER_CONNECT_TIMEOUT):
        await super().connect(timeout=timeout)

    def set_connection_state(self, state: PeerConnectionState):
        """Sets the current connection state.

        If the current state is ``AWAITING_INIT`` and the connection type is a
        distributed or file connection the :attr:`obfuscated` flag for this
        connection will be set to ``False``

        If the state goes to the ``ESTABLISHED`` state the message reader task
        will be started. In all other cases it will be stopped (in case the
        task was running)

        :param state: The new state of the connection
        """
        # Set non-peer connections to non-obfuscated
        if state != PeerConnectionState.AWAITING_INIT:
            if self.connection_type != PeerConnectionType.PEER:
                self.obfuscated = False

        adapter.debug("setting state to %s", state, extra=self.__dict__)
        self.connection_state = state

        if state == PeerConnectionState.ESTABLISHED:
            self.start_reader_task()
        else:
            # This shouldn't occur, during all other states we call the
            # receive_* methods directly. But it can do no harm
            self.stop_reader_task()

    async def receive_transfer_ticket(self) -> int:
        """Receive the transfer ticket from the connection"""
        if not self._reader:
            raise ConnectionReadError(
                f"{self.hostname}:{self.port} : cannot read transfer ticket, "
                "connection is not open"
            )

        data = await self._read(self._reader.readexactly(struct.calcsize('I')))
        if data is None:  # pragma: no cover
            raise ConnectionReadError(
                f"{self.hostname}:{self.port} : couldn't receive transfer ticket, "
                "connection closed"
            )

        _, ticket = uint32.deserialize(0, data)
        return ticket

    async def receive_transfer_offset(self) -> int:
        """Receive the transfer offset from the connection"""
        if not self._reader:
            raise ConnectionReadError(
                f"{self.hostname}:{self.port} : cannot read transfer offset, "
                "connection is not open"
            )

        data = await self._read(self._reader.readexactly(struct.calcsize('Q')))
        if data is None:  # pragma: no cover
            raise ConnectionReadError(
                f"{self.hostname}:{self.port} : couldn't receive transfer offset, "
                "connection closed"
            )

        _, offset = uint64.deserialize(0, data)
        return offset

    async def receive_data(self, n_bytes: int) -> Optional[bytes]:
        """Receives data on the connection. The ``n_bytes`` indicates the max
        amount of bytes that should be received on the connection, less bytes
        can be returned.

        In case of error the socket will be disconnected. If no data is received
        it is assumed to be EOF and the connection will be disconnected.

        :param n_bytes: max amount of bytes to receive
        :raise ConnectionReadError: in case timeout occured on an error on the
            socket
        :return: ``bytes`` object containing the received data or ``None`` in
            case the connection reached EOF
        """
        if not self._reader:
            raise ConnectionReadError(
                f"{self.hostname}:{self.port} : cannot read data, connection is not open")

        return await self._read(
            self._reader.read(n_bytes), timeout=self.transfer_read_timeout)

    async def receive_file(
            self, file_handle: AsyncBufferedIOBase, filesize: int,
            callback: Optional[Callable[[bytes], None]] = None):
        """Receives a file on the current connection and writes it to the given
        ``file_handle``

        This method will attempt to keep reading data until EOF is received from
        the connection or the amount of received bytes has reached the
        ``filesize``

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
        await self._send(data, timeout=TRANSFER_TIMEOUT)

    async def send_file(self, file_handle: AsyncBufferedReader, callback: Optional[Callable[[bytes], None]] = None):
        """Sends a file over the connection. This method makes use of the
        :attr:`upload_rate_limiter` to limit how many bytes are being sent at a
        time

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
