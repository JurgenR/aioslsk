from __future__ import annotations
from dataclasses import dataclass
from enum import auto, Enum
from typing import Callable, List, TYPE_CHECKING, Union
import copy
import errno
import logging
import queue
import socket
import struct
import time

from .events import get_listener_methods
from . import obfuscation
from .listeners import TransferListener
from . import messages

if TYPE_CHECKING:
    from .transfer import Transfer


logger = logging.getLogger()

DEFAULT_PEER_TIMEOUT = 30
DEFAULT_RECV_BUF_SIZE = 4
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
    """Connection is open, but no init message has been received yet"""
    AWAITING_TICKET = auto()
    """Transfer connections: awaiting the transfer ticket"""
    AWAITING_OFFSET = auto()
    """Transfer connections: awaiting the transfer offset"""
    ESTABLISHED = auto()
    """Message connections: ready to receive / send data"""
    TRANSFERING = auto()
    """Transfer connections: ready to receive / send data"""


class Connection:

    def __init__(self, hostname: str, port: int):
        self.hostname: str = hostname
        self.port: int = port
        self.fileobj = None
        self.state: ConnectionState = ConnectionState.UNINITIALIZED
        self.listeners = []

    def set_state(self, state: ConnectionState, close_reason: CloseReason = CloseReason.UNKNOWN):
        self.state = state
        for listener in self.listeners:
            if hasattr(listener, 'on_state_changed'):
                listener.on_state_changed(state, self, close_reason=close_reason)

    def disconnect(self, reason: CloseReason = CloseReason.UNKNOWN):
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

    def __init__(self, hostname='0.0.0.0', port=64823, obfuscated: bool = False, listeners=None):
        super().__init__(hostname, port)
        self.obfuscated = obfuscated
        self.listeners = listeners

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
            hostname=hostname, port=port,
            obfuscated=self.obfuscated,
            connection_type=PeerConnectionType.PEER,
            incoming=True
        )
        peer_connection.fileobj = fileobj
        peer_connection.state = ConnectionState.CONNECTED

        for listener in self.listeners:
            listener.on_peer_accepted(peer_connection)
        return peer_connection

    def has_data_to_write(self) -> bool:
        return False


class DataConnection(Connection):

    def __init__(self, hostname, port):
        super().__init__(hostname, port)
        self._buffer = bytes()
        self._messages = queue.Queue()

        self.last_interaction = 0
        self.bytes_received: int = 0
        self.bytes_sent: int = 0
        self.recv_buf_size: int = DEFAULT_RECV_BUF_SIZE
        self.send_buf_size: int = TRANSFER_RECV_BUF_SIZE

    def queue_message(self, message: Union[bytes, ProtocolMessage]):
        if isinstance(message, bytes):
            message = ProtocolMessage(message)
        self._messages.put(message)

    def queue_messages(self, *messages: List[Union[bytes, ProtocolMessage]]):
        for message in messages:
            self.queue_message(message)

    def interact(self):
        self.last_interaction = time.monotonic()

    def read(self) -> bool:
        """Attempts to read data from the socket. When data is received the
        L{buffer} method of this object will be called with the received data
        """
        try:
            recv_data = self.fileobj.recv(self.recv_buf_size)
        except OSError:
            logger.exception(f"exception receiving data on connection {self.fileobj}")
            # Only remove the peer connections?
            logger.info(f"close {self.hostname}:{self.port} : exception while reading")
            self.disconnect(reason=CloseReason.READ_ERROR)
            return False
        else:
            self.interact()
            if recv_data:
                self.buffer(recv_data)
                self.process_buffer()
            else:
                logger.warning(
                    f"close {self.hostname}:{self.port} : no data received")
                self.disconnect(reason=CloseReason.EOF)
                return False
        return True

    def write(self) -> bool:
        """Attempts to write data to the socket"""
        return self.send_message()

    def send_message(self) -> bool:
        """Sends a message if there is a message in the queue.

        @return: False in case an exception occured on the socket while sending.
            True in case a message was successfully sent or nothing was sent
        """
        try:
            message: ProtocolMessage = self._messages.get(block=False)
        except queue.Empty:
            pass
        else:
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
        return True

    def write_message(self, message: bytes):
        self.fileobj.sendall(message)

    def notify_message_sent(self, message: ProtocolMessage):
        if message.on_success is not None:
            try:
                message.on_success()
            except Exception:
                logger.exception(f"exception calling callback {message.on_success!r} (message={message!r})")

    def notify_message_received(self, message):
        """Notify all listeners that the given message was received"""
        logger.debug(f"notifying listeners of message : {message!r}")
        listeners_called = 0
        for listener in self.listeners:
            methods = get_listener_methods(listener, message.__class__)
            for method in methods:
                listeners_called += 1
                message_copy = copy.deepcopy(message)
                try:
                    method(message_copy, self)
                except Exception:
                    logger.exception(
                        f"error during callback : {message_copy!r} (listener={listener!r}, method={method!r})")

        if listeners_called == 0:
            logger.warning(f"no listeners registered for message : {message!r}")

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
        if len(self._buffer) < struct.calcsize('I'):
            return

        _, msg_len = messages.parse_int(0, self._buffer)
        # Calculate total message length (message length + length indicator)
        total_msg_len = struct.calcsize('I') + msg_len
        if len(self._buffer) >= total_msg_len:
            message = self._buffer[:total_msg_len]
            logger.debug(
                "recv message {}:{} : {!r}"
                .format(self.hostname, self.port, message.hex()))
            self._buffer = self._buffer[total_msg_len:]

            parsed_message = self.parse_message(message)
            self.notify_message_received(parsed_message)

    def process_obfuscated_message(self):
        # Require at least 8 bytes (4 bytes key, 4 bytes length)
        if len(self._buffer) < (obfuscation.KEY_SIZE + struct.calcsize('I')):
            return

        decoded_buffer = obfuscation.decode(self._buffer)

        _, msg_len = messages.parse_int(0, decoded_buffer)
        # Calculate total message length (message length + length indicator)
        total_msg_len = struct.calcsize('I') + msg_len
        if len(decoded_buffer) >= total_msg_len:
            message = decoded_buffer[:total_msg_len]
            logger.debug(
                "recv obfuscated message {}:{} : {!r}"
                .format(self.hostname, self.port, decoded_buffer.hex()))
            # Difference between buffer_unobfuscated, the key size is included
            self._buffer = self._buffer[total_msg_len + obfuscation.KEY_SIZE:]

            parsed_message = self.parse_message(message)
            self.notify_message_received(parsed_message)

    def has_data_to_write(self):
        return not self._messages.empty()


class ServerConnection(DataConnection):

    def __init__(self, hostname='server.slsknet.org', port=2416, listeners=None):
        super().__init__(hostname, port)
        self.listeners = [] if listeners is None else listeners

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
            return messages.parse_message(message_data)
        except Exception:
            logger.exception(
                f"failed to parse server message data {message_data}")
            return


class PeerConnection(DataConnection):

    def __init__(
            self, hostname='0.0.0.0', port=None, obfuscated: bool = False,
            connection_type=PeerConnectionType.PEER,
            incoming: bool = False, listeners=None):
        super().__init__(hostname, port)
        self.obfuscated: bool = obfuscated
        self.incoming: bool = incoming
        self.connection_type = connection_type
        self.listeners = [] if listeners is None else listeners
        self.connection_state = PeerConnectionState.AWAITING_INIT
        self.timeout: int = DEFAULT_PEER_TIMEOUT

        self.transfer: Transfer = None
        self.transfer_listeners: List[TransferListener] = []

    def set_connection_state(self, state: PeerConnectionState):
        if state == PeerConnectionState.TRANSFERING:
            self.recv_buf_size = TRANSFER_RECV_BUF_SIZE
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

    def has_data_to_write(self) -> bool:
        if self.is_uploading():
            return not self.transfer.is_transfered()
        else:
            return super().has_data_to_write()

    def is_uploading(self) -> bool:
        """Returns whether this connection is currently in the process of
        uploading
        """
        is_upload = self.transfer is not None and self.transfer.is_upload()
        return is_upload and self.connection_state == PeerConnectionState.TRANSFERING

    def write(self) -> bool:
        if self.is_uploading():
            return self.send_data()
        else:
            return self.send_message()

    def send_data(self) -> bool:
        """Transfers data over the connection"""
        if self.transfer.is_transfered():
            return True

        data = self.transfer.read(self.send_buf_size)

        try:
            self.interact()
            self.fileobj.sendall(data)
        except OSError:
            logger.exception(
                f"close {self.hostname}:{self.port} : exception while sending")
            self.disconnect(reason=CloseReason.WRITE_ERROR)
            return False
        else:
            self.bytes_sent += len(data)
            for listener in self.transfer_listeners:
                listener.on_transfer_data_sent(len(data), self)
        return True

    def process_buffer(self):
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
                for listener in self.transfer_listeners:
                    listener.on_transfer_ticket(ticket, self)

        elif self.connection_state == PeerConnectionState.AWAITING_OFFSET:

            if len(self._buffer) >= struct.calcsize('Q'):
                pos, ticket = messages.parse_int64(0, self._buffer)
                self._buffer = self._buffer[pos:]
                for listener in self.transfer_listeners:
                    listener.on_transfer_offset(ticket, self)

        elif self.connection_state == PeerConnectionState.TRANSFERING:

            data = self._buffer
            self._buffer = bytes()
            for listener in self.transfer_listeners:
                listener.on_transfer_data_received(data, self)

    def parse_message(self, message_data: bytes):
        try:
            if self.connection_state == PeerConnectionState.AWAITING_INIT:
                return messages.parse_peer_message(message_data)
            else:
                if self.connection_type == PeerConnectionType.DISTRIBUTED:
                    return messages.parse_distributed_message(message_data)
                else:
                    return messages.parse_peer_message(message_data)
        except Exception:
            logger.exception(f"failed to parse peer message : {message_data!r}")
            return

    def write_message(self, message):
        if self.obfuscated:
            super().write_message(obfuscation.encode(message))
        else:
            super().write_message(message)
