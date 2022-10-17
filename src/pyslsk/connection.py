from __future__ import annotations
from dataclasses import dataclass
from enum import auto, Enum
from typing import Callable, List, TYPE_CHECKING, Union
import errno
import logging
import socket
import struct
import time

from . import obfuscation
from . import messages

if TYPE_CHECKING:
    from .network import Network
    from .transfer import Transfer


logger = logging.getLogger()


DEFAULT_PEER_TIMEOUT = 30
DEFAULT_PEER_TRANSFER_TIMEOUT = 10 * 60
"""Increase the timeout in case we are transfering"""
DEFAULT_RECV_BUF_SIZE = 8
"""Default amount of bytes to recv from the socket"""
TRANSFER_RECV_BUF_SIZE = 1024 * 8
"""Default amount of bytes to recv during file transfer"""
TRANSFER_SEND_BUF_SIZE = 1024 * 8
"""Default amount of bytes to send during file transfer"""


@dataclass(frozen=True)
class ProtocolMessage:
    message: bytes
    on_success: Callable = None
    on_failure: Callable = None


class PeerConnectionType:
    FILE = 'F'
    PEER = 'P'
    DISTRIBUTED = 'D'


class ConnectionState(Enum):
    UNINITIALIZED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    SHOULD_CLOSE = auto()
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
    TRANSFERING = auto()
    """Transfer connections: ready to receive / send data"""


class Connection:

    def __init__(self, hostname: str, port: int, network: Network):
        self.hostname: str = hostname
        self.port: int = port
        self.network = network
        self.fileobj = None
        self.state: ConnectionState = ConnectionState.UNINITIALIZED

    def set_state(self, state: ConnectionState, close_reason: CloseReason = CloseReason.UNKNOWN):
        self.state = state
        self.network.on_state_changed(state, self, close_reason=close_reason)

    def disconnect(self, reason: CloseReason = CloseReason.UNKNOWN):
        """Performs the closing of the connection and sets the state to CLOSED
        """
        logger.debug(f"disconnecting from {self.hostname}:{self.port} reason : {reason.name}")
        try:
            self.fileobj.close()
        except OSError:
            logger.exception(f"exception while disconnecting {self.fileobj}")
        finally:
            self.set_state(ConnectionState.CLOSED, close_reason=reason)

    def __repr__(self):
        return (
            f"{self.__class__.__name__}(hostname={self.hostname!r}, port={self.port}, "
            f"fileobj={self.fileobj!r}, state={self.state})")


class ListeningConnection(Connection):
    """A listening connection, objects of this class are responsible for
    accepting incoming connections
    """

    def __init__(self, hostname: str, port: int, network: Network, obfuscated: bool = False):
        super().__init__(hostname, port, network)
        self.obfuscated = obfuscated

        self.connections_accepted = 0

    def connect(self):
        logger.info(
            f"open {self.hostname}:{self.port} : listening connection")
        self.fileobj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.fileobj.bind((self.hostname, self.port, ))
        self.fileobj.setblocking(False)
        self.fileobj.listen()

        self.set_state(ConnectionState.CONNECTING)

        return self.fileobj

    def accept(self, sock):
        """Accept the incoming connection (L{sock})"""
        self.connections_accepted += 1

        fileobj, addr = sock.accept()
        hostname, port = addr
        logger.info(f"accepted {hostname}:{port} on {self.hostname}:{self.port} (obfuscated={self.obfuscated})")

        fileobj.setblocking(False)

        peer_connection = PeerConnection(
            hostname, port, self.network,
            obfuscated=self.obfuscated,
            connection_type=PeerConnectionType.PEER,
            incoming=True
        )
        peer_connection.fileobj = fileobj
        peer_connection.set_state(ConnectionState.CONNECTED)

        self.network.on_peer_accepted(peer_connection)
        return peer_connection


class DataConnection(Connection):

    HEADER_SIZE_OBFUSCATED: int = obfuscation.KEY_SIZE + struct.calcsize('I')
    HEADER_SIZE_UNOBFUSCATED: int = struct.calcsize('I')

    def __init__(self, hostname: str, port: int, network: Network):
        super().__init__(hostname, port, network)
        self._buffer = bytes()
        self._messages: List[ProtocolMessage] = []

        self.last_interaction: float = 0
        self.bytes_received: int = 0
        self.bytes_sent: int = 0
        self.recv_buf_size: int = DEFAULT_RECV_BUF_SIZE
        self.send_buf_size: int = TRANSFER_RECV_BUF_SIZE

    def set_state(self, state: ConnectionState, close_reason: CloseReason = CloseReason.UNKNOWN):
        if state == ConnectionState.CONNECTED:
            self.interact()
            if not self._messages:
                self.network.disable_write(self)

        super().set_state(state, close_reason)

    def queue_messages(self, *messages: List[Union[bytes, ProtocolMessage]]):
        for message in messages:
            if isinstance(message, bytes):
                message = ProtocolMessage(message)
            self._messages.append(message)

        if self._messages:
            self.network.enable_write(self)

    def interact(self):
        self.last_interaction = time.monotonic()

    def read(self) -> bool:
        """Attempts to read data from the socket. When data is received the
        L{buffer} method of this object will be called with the received data

        :return: False if an error occured on the socket during reading
        """
        return self.receive_message()

    def receive_message(self) -> bool:
        try:
            recv_data = self.fileobj.recv(self.recv_buf_size)

        except OSError:
            logger.exception(f"exception receiving data on connection {self.fileobj}")
            # Only remove the peer connections?
            logger.debug(f"close {self.hostname}:{self.port} : exception while reading")
            self.disconnect(reason=CloseReason.READ_ERROR)
            return False

        else:
            self.interact()
            if recv_data:
                self.buffer(recv_data)
                self.process_buffer()

            else:
                logger.debug(
                    f"close {self.hostname}:{self.port} : no data received")
                self.disconnect(reason=CloseReason.EOF)
                return False

        return True

    def write(self) -> bool:
        """Attempts to write data to the socket

        :return: False if an error occured on the socket during writing
        """
        return self.send_message()

    def send_message(self) -> bool:
        """Sends a message if there is a message in the queue.

        @return: False in case an exception occured on the socket while sending.
            True in case a message was successfully sent or nothing was sent
        """
        for message in self._messages:
            try:
                logger.debug(f"send {self.hostname}:{self.port} : message {message.message.hex()}")
                self.interact()
                self.write_message(message.message)

            except OSError:
                logger.exception(
                    f"close {self.hostname}:{self.port} : exception while sending")
                self.disconnect(reason=CloseReason.WRITE_ERROR)
                return False
            else:
                self.bytes_sent += len(message.message)
                self.notify_message_sent(message)

        self._messages = []
        self.network.disable_write(self)
        return True

    def write_message(self, message: bytes):
        self.fileobj.sendall(message)

    def notify_message_sent(self, message: ProtocolMessage):
        try:
            self.network.on_message_sent(message, self)
        except Exception:
            logger.exception(f"error during message sent callback: {message!r}")

    def notify_message_received(self, message):
        """Notify the network that the given message was received"""
        logger.debug(f"received message of type : {message.__class__.__name__!r}")
        try:
            self.network.on_message_received(message, self)
        except Exception:
            logger.exception(f"error during callback : {message!r}")

    def parse_message(self, message_data: bytes):
        """Should be called after a full message has been received. This method
        should parse the message and notify the listeners
        """
        raise NotImplementedError(
            "parse_message should be overwritten by a subclass")

    def buffer(self, data: bytes):
        """Adds data to the buffer"""
        self.bytes_received += len(data)
        self._buffer += data

    def process_buffer(self):
        """Processes what is currently in the buffer. Should be called after
        data has been added to the buffer
        """
        raise NotImplementedError(
            "process_buffer method should be overwritten by a subclass")

    def process_unobfuscated_message(self):
        """Helper method for the unobfuscated buffer.

        This method will look at the first 4-bytes of the L{_buffer} to
        determine the total length of the message. Once the length has been
        reached the L{parse_message} message will be called with the L{_buffer}
        contents based on the message length.

        This method won't clear the buffer entirely but will remove the message
        from the _buffer and keep the rest.
        """
        if len(self._buffer) < self.HEADER_SIZE_UNOBFUSCATED:
            return

        # Calculate total message length (message length + length indicator)
        _, msg_len = messages.parse_int(0, self._buffer)
        total_msg_len = self.HEADER_SIZE_UNOBFUSCATED + msg_len

        if len(self._buffer) >= total_msg_len:
            message = self._buffer[:total_msg_len]
            logger.debug(
                "recv message {}:{} : {!r}"
                .format(self.hostname, self.port, message.hex()))

            self._buffer = self._buffer[total_msg_len:]
            self.recv_buf_size = DEFAULT_RECV_BUF_SIZE

            parsed_message = self.parse_message(message)
            self.notify_message_received(parsed_message)
        else:
            self.recv_buf_size = total_msg_len - len(self._buffer)

    def process_obfuscated_message(self):
        if len(self._buffer) < self.HEADER_SIZE_OBFUSCATED:
            return

        decoded_header = obfuscation.decode(self._buffer[:self.HEADER_SIZE_OBFUSCATED])

        # Calculate total message length (key length + message length + length indicator)
        _, msg_len = messages.parse_int(0, decoded_header)
        total_msg_len = self.HEADER_SIZE_OBFUSCATED + msg_len

        if len(self._buffer) >= total_msg_len:
            message = obfuscation.decode(self._buffer[:total_msg_len])
            logger.debug(
                "recv obfuscated message {}:{} : {!r}"
                .format(self.hostname, self.port, message.hex()))

            self._buffer = self._buffer[total_msg_len:]
            self.recv_buf_size = DEFAULT_RECV_BUF_SIZE

            parsed_message = self.parse_message(message)
            self.notify_message_received(parsed_message)
        else:
            self.recv_buf_size = total_msg_len - len(self._buffer)


class ServerConnection(DataConnection):

    def get_connecting_ip(self):
        """Gets the IP address being used to connect to the SoulSeek server.

        The connection needs to be established for this method to work
        """
        return self.fileobj.getsockname()[0]

    def connect(self):
        logger.info(
            f"open {self.hostname}:{self.port} : server connection")

        self.fileobj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.fileobj.setblocking(False)

        # Setting the state to connecting will register it with the network
        # loop
        self.set_state(ConnectionState.CONNECTING)
        try:
            self.fileobj.connect_ex((self.hostname, self.port, ))
        except OSError:
            self.set_state(ConnectionState.CLOSED, close_reason=CloseReason.CONNECT_FAILED)

        return self.fileobj

    def process_buffer(self):
        # For server connection the messages are always unobfuscated
        self.process_unobfuscated_message()

    def parse_message(self, message_data: bytes):
        try:
            return messages.parse_server_message(message_data)
        except Exception:
            logger.exception(
                f"failed to parse server message data {message_data}")
            return


class PeerConnection(DataConnection):

    def __init__(
            self, hostname: str, port: int, network: Network, obfuscated: bool = False,
            username: str = None, connection_type: str = PeerConnectionType.PEER,
            incoming: bool = False):
        super().__init__(hostname, port, network)
        self.obfuscated: bool = obfuscated
        self.incoming: bool = incoming
        self.connection_state = PeerConnectionState.AWAITING_INIT
        self.timeout: int = DEFAULT_PEER_TIMEOUT

        self.username: str = username
        self.connection_type: str = connection_type

        self.transfer: Transfer = None

    def set_connection_state(self, state: PeerConnectionState):
        if state == PeerConnectionState.TRANSFERING:
            self.fileobj.setsockopt(socket.SOL_SOCKET, socket.TCP_NODELAY, 1)
            self.fileobj.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 0)
            self.timeout = DEFAULT_PEER_TRANSFER_TIMEOUT
            self.recv_buf_size = TRANSFER_RECV_BUF_SIZE
            if self.is_uploading():
                self.network.enable_write(self)

        # Set non-peer connections to non-obfuscated
        if state != PeerConnectionState.AWAITING_INIT:
            if self.connection_type != PeerConnectionType.PEER:
                self.obfuscated = False

        self.connection_state = state

    def connect(self):
        self.interact()
        # logger.info(f"open {self.hostname}:{self.port} : peer connection")
        self.fileobj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.fileobj.setblocking(False)

        self.set_state(ConnectionState.CONNECTING)
        result_code = self.fileobj.connect_ex((self.hostname, self.port, ))

        if result_code == 0:
            result_str = "success"
        else:
            result_str = errno.errorcode.get(result_code, 'unknown')

        logger.info(f"open {self.hostname}:{self.port} : peer connection. result {result_code} [{result_str}]")
        # This can return error code 10035 (WSAEWOULDBLOCK) which can be ignored
        # What to do with other error codes?

        return self.fileobj

    def is_uploading(self) -> bool:
        """Returns whether this connection is currently in the process of
        uploading
        """
        is_upload = self.transfer and self.transfer.is_upload()
        return is_upload and self.connection_state == PeerConnectionState.TRANSFERING

    def write(self) -> bool:
        if self.is_uploading():
            return self.send_data()
        else:
            return self.send_message()

    def send_data(self) -> bool:
        """Send data over the connection. This is to be used only for transfers.
        """
        if self.transfer.is_transfered():
            return True

        # Take tokens from the rate limiter
        tokens_taken = self.network.upload_rate_limiter.take_tokens()
        if tokens_taken == 0:
            return True

        data = self.transfer.read(tokens_taken)

        try:
            self.interact()
            bytes_sent = self.fileobj.send(data)

        except OSError:
            logger.exception(
                f"close {self.hostname}:{self.port} : exception while sending")
            self.disconnect(reason=CloseReason.WRITE_ERROR)
            return False

        else:
            self.bytes_sent += bytes_sent
            self.network.on_transfer_data_sent(tokens_taken, bytes_sent, self)

        return True

    def read(self) -> bool:
        if self.connection_state == PeerConnectionState.TRANSFERING:
            return self.receive_data()
        else:
            return self.receive_message()

    def receive_data(self) -> bool:
        # Take some tokens to receive from the buffer
        tokens_taken = self.network.download_rate_limiter.take_tokens()
        if tokens_taken == 0:
            return True

        try:
            recv_data = self.fileobj.recv(tokens_taken)

        except OSError:
            logger.exception(f"exception receiving data on connection {self.fileobj}")
            # Only remove the peer connections?
            logger.debug(f"close {self.hostname}:{self.port} : exception while reading")
            self.disconnect(reason=CloseReason.READ_ERROR)
            return False

        else:
            self.interact()
            if recv_data:
                self.buffer(recv_data)
                self.process_buffer(tokens_taken=tokens_taken)

            else:
                logger.debug(
                    f"close {self.hostname}:{self.port} : no data received")
                self.disconnect(reason=CloseReason.EOF)
                return False

        return True

    def process_buffer(self, tokens_taken: int = 0):
        """Attempts to process the buffer depending on the current
        connection_state. Called after we have received some data

        :param tokens_taken: only applicable when receiving transfer data, the
            amount of tokens taken for the download RateLimiter
        """
        if self.connection_state in (PeerConnectionState.AWAITING_INIT, PeerConnectionState.ESTABLISHED, ):

            if self.obfuscated:
                self.process_obfuscated_message()
            else:
                self.process_unobfuscated_message()

        elif self.connection_state == PeerConnectionState.AWAITING_TICKET:

            # After peer initialization, we should just receive 4 bytes with the
            # ticket number
            if len(self._buffer) >= struct.calcsize('I'):
                pos, ticket = messages.parse_int(0, self._buffer)
                self._buffer = self._buffer[pos:]
                self.network.on_transfer_ticket(ticket, self)

        elif self.connection_state == PeerConnectionState.AWAITING_OFFSET:

            if len(self._buffer) >= struct.calcsize('Q'):
                pos, ticket = messages.parse_int64(0, self._buffer)
                self._buffer = self._buffer[pos:]
                self.network.on_transfer_offset(ticket, self)

        elif self.connection_state == PeerConnectionState.TRANSFERING:

            data = self._buffer
            self._buffer = bytes()
            self.network.on_transfer_data_received(tokens_taken, data, self)

    def parse_message(self, message_data: bytes):
        try:
            if self.connection_state == PeerConnectionState.AWAITING_INIT:
                return messages.parse_peer_initialization_message(message_data)

            else:
                if self.connection_type == PeerConnectionType.PEER:
                    return messages.parse_peer_message(message_data)
                else:
                    return messages.parse_distributed_message(message_data)

        except Exception:
            logger.exception(f"failed to parse peer message : {message_data!r}")

    def write_message(self, message):
        if self.obfuscated:
            super().write_message(obfuscation.encode(message))
        else:
            super().write_message(message)
