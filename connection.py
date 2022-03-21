from enum import auto, Enum
import copy
import errno
import logging
import queue
import selectors
import socket
import struct
import threading
import time

from events import get_listener_methods
import obfuscation
from transfer import Transfer, TransferDirection, TransferState
import messages


logger = logging.getLogger()

DEFAULT_PEER_TIMEOUT = 30


DEFAULT_RECV_BUF_SIZE = 4
"""Default amount of bytes to recv from the socket"""

TRANSFER_RECV_BUF_SIZE = 1024 * 8
"""Default amount of bytes to recv during file transfer"""

TRANSFER_SEND_BUF_SIZE = 1024 * 8
"""Default amount of bytes to send during file transfer"""


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

    def set_state(self, state: ConnectionState, close_reason=CloseReason.UNKNOWN):
        self.state = state
        for listener in self.listeners:
            listener.on_state_changed(state, self, close_reason=close_reason)

    def disconnect(self, reason=CloseReason.UNKNOWN):
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

    def __init__(self, hostname='0.0.0.0', port=64823, obfuscated=False, listeners=None):
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


class DataConnection(Connection):

    def __init__(self, hostname, port):
        super().__init__(hostname, port)
        self._buffer = bytes()
        self.messages = queue.Queue()

        self.last_interaction = 0
        self.bytes_received = 0
        self.bytes_sent = 0
        self.recv_buf_size = DEFAULT_RECV_BUF_SIZE
        self.send_buf_size = TRANSFER_RECV_BUF_SIZE

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
            if recv_data:
                self.last_interaction = time.time()
                self.buffer(recv_data)
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

        @return: False in case an error occured on the socket while sending.
            True in case a message was successfully sent or nothing was sent
        """
        try:
            message, callback = self.messages.get(block=False)
        except queue.Empty:
            pass
        else:
            try:
                logger.debug(f"send {self.hostname}:{self.port} : message {message.hex()}")
                self.last_interaction = time.time()
                self.write_message(message)
            except OSError:
                logger.exception(
                    f"close {self.hostname}:{self.port} : exception while sending")
                self.disconnect(reason=CloseReason.WRITE_ERROR)
                return False
            else:
                self.bytes_sent += len(message)
                if callback is not None:
                    self.notify_message_sent(message, callback)
        return True

    def write_message(self, message: bytes):
        self.fileobj.sendall(message)

    def notify_message_sent(self, message, callback):
        try:
            callback()
        except Exception:
            logger.exception(f"exception calling callback {callback!r} (message={message!r})")

    def notify_message_received(self, message, *args):
        """Notify all listeners that the given message was received"""
        logger.debug(f"notifying listeners of message : {message!r}")
        listeners_called = 0
        for listener in self.listeners:
            methods = get_listener_methods(listener, message.__class__)
            for method in methods:
                listeners_called += 1
                message_copy = copy.deepcopy(message)
                try:
                    method(message_copy, *args)
                except Exception:
                    logger.exception(
                        f"error during callback : {message_copy!r} (listener={listener!r}, method={method!r})")

        if listeners_called == 0:
            logger.warning(f"no listeners registered for message : {message!r}")

    def queue_message(self, message, callback=None):
        self.messages.put((message, callback, ))

    def queue_messages(self, *messages):
        for message in messages:
            self.queue_message(message)

    def handle_message_data(self, message_data: bytes):
        """Should be called after a full message has been received"""
        raise NotImplementedError(
            "handle_message_data should be overwritten by a subclass")

    def buffer(self, data: bytes):
        self.bytes_received += len(data)
        self._buffer += data

        self.process_buffer()

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
        reached the L{handle_message_data} message will be called with the L{_buffer}
        contents based on the message length.

        This method won't clear the buffer entirely but will remove the message
        from the _buffer and keep the rest. (When does this happen?)
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
            self.handle_message_data(message)

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
            self.handle_message_data(message)


class ServerConnection(DataConnection):

    def __init__(self, hostname='server.slsknet.org', port=2416, listeners=None):
        super().__init__(hostname, port)
        self.listeners = listeners

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
        self.fileobj.connect_ex((self.hostname, self.port, ))

        self.set_state(ConnectionState.CONNECTING)
        return self.fileobj

    def process_buffer(self):
        # For server connection the messages are always unobfuscated
        self.process_unobfuscated_message()

    def handle_message_data(self, message_data: bytes):
        try:
            message = messages.parse_message(message_data)
        except Exception:
            logger.exception(
                f"failed to parse server message data {message_data}")
            return

        self.notify_message_received(message)


class PeerConnection(DataConnection):

    def __init__(
            self, hostname='0.0.0.0', port=None, obfuscated=False,
            listeners=None, connection_type=PeerConnectionType.PEER,
            incoming=False):
        super().__init__(hostname, port)
        self.listeners = listeners
        self.obfuscated: bool = obfuscated
        self.connection_type = connection_type
        self.incoming: bool = incoming
        self.connection_state = PeerConnectionState.AWAITING_INIT
        self.transfer: Transfer = None
        self.timeout = DEFAULT_PEER_TIMEOUT

    def set_connection_type(self, connection_type):
        self.connection_type = connection_type

    def set_connection_state(self, state: PeerConnectionState):
        if state == PeerConnectionState.TRANSFERING:
            self.recv_buf_size = TRANSFER_RECV_BUF_SIZE
        self.connection_state = state

    def connect(self):
        logger.info(f"open {self.hostname}:{self.port} : peer connection")
        self.fileobj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.fileobj.setblocking(False)
        res = self.fileobj.connect_ex((self.hostname, self.port, ))

        logger.info(f"open {self.hostname}:{self.port} : peer connection, result {res} [{errno.errorcode[res]}]")
        # This can return error code 10035 (WSAEWOULDBLOCK) which can be ignored
        # What to do with other error codes?

        self.set_state(ConnectionState.CONNECTING)

        return self.fileobj

    def write(self) -> bool:
        is_upload = self.transfer is not None and self.transfer.direction == TransferDirection.UPLOAD
        if self.connection_state == PeerConnectionState.TRANSFERING and is_upload:
            return self.send_data()
        else:
            return self.send_message()

    def send_data(self) -> bool:
        """Transfers data over the connection"""
        if self.transfer.state == TransferState.COMPLETE:
            return True

        data = self.transfer.read(self.send_buf_size)

        try:
            self.last_interaction = time.time()
            self.fileobj.sendall(data)
        except OSError:
            logger.exception(
                f"close {self.hostname}:{self.port} : exception while sending")
            self.disconnect(reason=CloseReason.WRITE_ERROR)
            return False
        else:
            self.bytes_sent += len(data)
            for listener in self.listeners:
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
                for listener in self.listeners:
                    listener.on_transfer_ticket(ticket, self)

        elif self.connection_state == PeerConnectionState.AWAITING_OFFSET:

            if len(self._buffer) >= struct.calcsize('Q'):
                pos, ticket = messages.parse_int64(0, self._buffer)
                self._buffer = self._buffer[pos:]
                for listener in self.listeners:
                    listener.on_transfer_offset(ticket, self)

        elif self.connection_state == PeerConnectionState.TRANSFERING:

            data = self._buffer
            self._buffer = bytes()
            for listener in self.listeners:
                listener.on_transfer_data_received(data, self)

    def handle_message_data(self, message_data: bytes):
        try:
            if self.connection_state == PeerConnectionState.AWAITING_INIT:
                message = messages.parse_peer_message(message_data)
            else:
                if self.connection_type == PeerConnectionType.DISTRIBUTED:
                    message = messages.parse_distributed_message(message_data)
                else:
                    message = messages.parse_peer_message(message_data)
        except Exception:
            logger.exception(f"failed to parse peer message : {message_data!r}")
            return

        self.notify_message_received(message, self)

    def write_message(self, message):
        if self.obfuscated:
            super().write_message(obfuscation.encode(message))
        else:
            super().write_message(message)


class NetworkLoop(threading.Thread):

    def __init__(self, settings, stop_event):
        super().__init__()
        self.selector = selectors.DefaultSelector()
        self.settings = settings
        self.stop_event = stop_event
        self._last_log_time = 0

    def _log_open_connections(self):
        current_time = int(time.time())
        # Debug how many connections are still open
        if current_time % 5 == 0 and current_time > self._last_log_time:
            self._last_log_time = current_time
            logger.debug(
                "Currently {} open connections".format(len(self.selector.get_map())))

    def get_connections(self):
        """Returns a list of currently registered L{Connection} objects"""
        return [
            selector_key.data
            for selector_key in self.selector.get_map().values()
        ]

    def run(self):
        """Start the network loop, and run until L{stop_event} is set. This is
        the network loop for all L{Connection} instances.
        """
        try:
            while not self.stop_event.is_set():
                if len(self.selector.get_map()) == 0:
                    time.sleep(0.1)
                    continue

                self._log_open_connections()

                events = self.selector.select(timeout=None)

                current_time = time.time()

                for key, mask in events:
                    work_socket = key.fileobj
                    connection = key.data

                    # If this is the first time the connection is selected we should
                    # still be in the CONNECTING state. Check if we are successfully
                    # connected otherwise close the socket
                    if connection.state == ConnectionState.CONNECTING:
                        socket_err = work_socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                        if socket_err != 0:
                            logger.debug(
                                "error connecting {}:{} : {} [{}] : cleaning up"
                                .format(connection.hostname, connection.port, socket_err, errno.errorcode[socket_err]))
                            connection.disconnect(reason=CloseReason.CONNECT_FAILED)
                        else:
                            logger.debug(
                                "successfully connected {}:{}".format(connection.hostname, connection.port))
                            connection.set_state(ConnectionState.CONNECTED)
                        continue

                    if mask & selectors.EVENT_READ:
                        # Listening connection
                        if isinstance(connection, ListeningConnection):
                            # Accept incoming connections on the listening socket
                            connection.accept(work_socket)
                            continue

                        # Server socket or peer socket
                        if not connection.read():
                            continue

                    if mask & selectors.EVENT_WRITE:
                        # Sockets will go into write even if an error occurred on
                        # them. Clean them up and move on if this happens
                        socket_err = work_socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                        if socket_err != 0:
                            logger.warning(
                                "error {}:{} : {} [{}] : cleaning up"
                                .format(connection.hostname, connection.port, socket_err, errno.errorcode[socket_err]))
                            connection.disconnect(reason=CloseReason.WRITE_ERROR)
                            continue

                        if not connection.write():
                            continue

                # Clean up connections
                for selector_key in list(self.selector.get_map().values()):
                    connection = selector_key.data

                    # Clean up connections we requested to close
                    if connection.state == ConnectionState.SHOULD_CLOSE:
                        connection.disconnect(reason=CloseReason.REQUESTED)
                        continue

                    # Clean up connections that went into timeout
                    if isinstance(connection, PeerConnection):
                        if connection.last_interaction == 0:
                            continue

                        if connection.last_interaction + connection.timeout < current_time:
                            logger.warning(f"connection {connection.hostname}:{connection.port}: timeout reached")
                            connection.disconnect(reason=CloseReason.TIMEOUT)
                            continue

        except Exception as exc:
            logger.exception("failure inside network loop")
        finally:
            for data in self.selector.get_map().values():
                data.fileobj.close()

            self.selector.close()
