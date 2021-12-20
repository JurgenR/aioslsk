import enum
import errno
import logging
import queue
import selectors
import socket
import struct
import threading
import time

from exceptions import PySlskException
import obfuscation
import messages
import upnp


logger = logging.getLogger()


class PeerConnectionType:
    FILE = 'F'
    PEER = 'P'
    DISTRIBUTED = 'D'


class ConnectionState(enum.Enum):
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    SHOULD_CLOSE = 3
    CLOSED = 4


class Connection:

    def __init__(self, hostname: str, port: int, fileobj=None, state: ConnectionState=ConnectionState.DISCONNECTED):
        self.hostname: str = hostname
        self.port: int = port
        self.fileobj = fileobj
        self.state: ConnectionState = state
        self.listener = None

    def set_state(self, state: ConnectionState):
        self.state = state
        self.listener.on_state_changed(state, self)

    def disconnect(self):
        logger.debug(f"disconnecting from {self.hostname}:{self.port}")
        try:
            self.fileobj.close()
        except OSError:
            logger.exception(f"exception while disconnecting {self.fileobj}")
        finally:
            self.set_state(ConnectionState.CLOSED)

    def __repr__(self):
        return (
            f"{self.__class__.__name__}(hostname={self.hostname!r}, port={self.port}, "
            f"fileobj={self.fileobj!r}, state={self.state})")


class ServerConnection(Connection):

    def __init__(self, hostname='server.slsknet.org', port=2416, listener=None):
        super().__init__(hostname, port)
        self._buffer = b''
        self.messages = queue.Queue()
        self.listener = listener
        self.last_interaction = 0

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

    def buffer(self, data):
        """Adds data to the internal L{_buffer} and tries to detects whether a
        message is complete. If a message is complete the L{handle_message}
        method is called and the message is cleared from the L{_buffer}.

        Detection is done by parsing the message length and comparing if the
        current L{_buffer} object has the desired length.

        If the length of the buffer is greater than the detected length then
        the extra bytes are kept in the L{_buffer} and only the message is
        removed
        """
        self._buffer += data

        if len(self._buffer) < struct.calcsize('I'):
            return

        _, msg_len = messages.parse_int(0, self._buffer)
        msg_len_with_len = struct.calcsize('I') + msg_len
        if len(self._buffer) >= msg_len_with_len:
            message = self._buffer[:msg_len_with_len]
            logger.debug(
                "server message {}:{} : {!r} ({} bytes)"
                .format(self.hostname, self.port, self._buffer[:8 * 2].hex()), len(message))
            # Remove message from buffer
            self._buffer = self._buffer[msg_len_with_len:]
            self.handle_message(message)

    def handle_message(self, message_data):
        try:
            message = messages.parse_message(message_data)
            self.listener.on_server_message(message, self)
        except Exception as exc:
            logger.error(
                f"Failed to handle server message data {message_data}",
                exc_info=True)


class ListeningConnection(Connection):
    """A listening connection, objects of this class are responsible for
    accepting incoming connections
    """

    def __init__(self, hostname='0.0.0.0', port=64823, obfuscated=False, listener=None):
        super().__init__(hostname, port)
        self._buffer = b''
        self.messages = queue.Queue()
        self.obfuscated = obfuscated
        self.listener = listener
        self.last_interaction = 0

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
        fileobj, addr = sock.accept()
        logger.info(f"accepted {addr[0]}:{addr[1]} on {self.hostname}:{self.port} (obfuscated={self.obfuscated})")
        fileobj.setblocking(False)

        peer_connection = PeerConnection(
            hostname=addr[0], port=addr[1],
            obfuscated=self.obfuscated,
            connection_type=PeerConnectionType.PEER,
            listener=self.listener,
            incoming=True
        )
        peer_connection.fileobj = fileobj
        peer_connection.state = ConnectionState.CONNECTED

        self.listener.on_peer_accepted(peer_connection)
        return peer_connection


class PeerConnection(Connection):

    def __init__(
            self, hostname='0.0.0.0', port=None, obfuscated=False,
            listener=None, connection_type=PeerConnectionType.PEER,
            incoming=False):
        super().__init__(hostname, port)
        self._buffer = b''
        self.listener = listener
        self.messages = queue.Queue()
        self.obfuscated = obfuscated
        self.last_interaction = 0
        self.connection_type = connection_type
        self.incoming = incoming

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

    def buffer(self, data):
        """Main entry point for incoming network data. The L{data} should always
        have a length of 4-bytes. This method will append the data to the
        internal L{_buffer} object and call 2 helper methods depending on the
        L{obfuscated} flag.
        """
        self._buffer += data
        if self.obfuscated:
            self.buffer_obfuscated()
        else:
            self.buffer_unobfuscated()

    def buffer_unobfuscated(self):
        """Helper method for the unobfuscated buffer.

        This method will look at the first 4-bytes of the L{_buffer} to
        determine the total length of the message. Once the length has been
        reached the L{handle_message} message will be called with the L{_buffer}
        contents based on the message length.

        This method won't clear the buffer entirely but will remove the message
        from the _buffer and keep the rest. (When does this happen?)
        """
        if len(self._buffer) < (obfuscation.KEY_SIZE + 4):
            return

        _, msg_len = messages.parse_int(0, self._buffer)
        # Calculate total message length (message length + length indicator)
        total_msg_len = struct.calcsize('I') + msg_len
        if len(self._buffer) >= total_msg_len:
            message = self._buffer[:total_msg_len]
            logger.debug(
                "recv peer message {}:{} : {!r}"
                .format(self.hostname, self.port, self._buffer.hex()[:8 * 2]))
            self._buffer = self._buffer[total_msg_len:]
            self.handle_message(message)

    def buffer_obfuscated(self):
        # Require at least 8 bytes (4 bytes key, 4 bytes length)
        if len(self._buffer) < (obfuscation.KEY_SIZE + 4):
            return

        # NOTE: We might need a check here if we have a multiple of 4
        decoded_buffer = obfuscation.decode(self._buffer)

        # TODO: there should be common code between this and buffer_unobfuscated
        # merge them if possible
        _, msg_len = messages.parse_int(0, decoded_buffer)
        # Calculate total message length (message length + length indicator)
        total_msg_len = struct.calcsize('I') + msg_len
        if len(decoded_buffer) >= total_msg_len:
            message = decoded_buffer[:total_msg_len]
            logger.debug(
                "recv obfuscated peer message {}:{} : {!r}"
                .format(self.hostname, self.port, decoded_buffer.hex()[:8 * 2]))
            # Difference between buffer_unobfuscated, the key size is included
            self._buffer = self._buffer[total_msg_len + obfuscation.KEY_SIZE:]
            self.handle_message(message)

    def handle_message(self, message_data):
        self.listener.on_peer_message(message_data, self)


class NetworkLoop(threading.Thread):

    def __init__(self, settings, stop_event, lock):
        super().__init__()
        self.selector = selectors.DefaultSelector()
        self.settings = settings
        self.stop_event = stop_event
        self.lock = lock
        self._last_log_time = 0

    def _log_open_connections(self):
        current_time = int(time.time())
        # Debug how many connections are still open
        if current_time % 5 == 0 and current_time > self._last_log_time:
            self._last_log_time = current_time
            open_connections = [
                repr(open_conn.fileobj) for open_conn in self.selector.get_map().values()
            ]
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
        while not self.stop_event.is_set():
            if len(self.selector.get_map()) == 0:
                time.sleep(0.1)
                continue

            with self.lock:
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
                        connection.disconnect()
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
                    try:
                        recv_data = work_socket.recv(4)
                    except OSError as exc:
                        logger.exception(f"Exception receiving data on connection {work_socket}")
                        # Only remove the peer connections?
                        logger.info(f"close {connection.hostname}:{connection.port} : exception while reading")
                        connection.disconnect()
                        continue
                    else:
                        if recv_data:
                            connection.last_interaction = current_time
                            connection.buffer(recv_data)
                        else:
                            logger.warning(
                                f"close {connection.hostname}:{connection.port} : no data received")
                            connection.disconnect()
                            continue

                if mask & selectors.EVENT_WRITE:
                    # Sockets will go into write even if an error occurred on
                    # them. Clean them up and move on if this happens
                    socket_err = work_socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                    if socket_err != 0:
                        logger.warning(
                            "error {}:{} : {} [{}] : cleaning up"
                            .format(connection.hostname, connection.port, socket_err, errno.errorcode[socket_err]))
                        connection.disconnect()
                        continue

                    try:
                        # Attempt to get the message from the Queue and send it
                        # over the socket it belongs to
                        message = connection.messages.get(block=False)
                    except queue.Empty:
                        pass
                    else:
                        try:
                            logger.debug(f"send {connection.hostname}:{connection.port} : message {message.hex()}")
                            connection.last_interaction = current_time
                            work_socket.sendall(message)
                        except OSError as exc:
                            logger.exception(
                                f"close {connection.hostname}:{connection.port} : exception while sending")
                            connection.disconnect()
                            continue

            # Clean up connections
            for selector_key in list(self.selector.get_map().values()):
                connection = selector_key.data

                # Clean up connections we requested to close
                if connection.state == ConnectionState.SHOULD_CLOSE:
                    connection.disconnect()
                    continue

                # Clean up connections that went into timeout
                if isinstance(connection, PeerConnection):
                    if connection.last_interaction == 0:
                        continue

                    if connection.last_interaction + 30 < current_time:
                        logger.warning(f"connection {connection.hostname}:{connection.port}: timeout reached")
                        connection.disconnect()
                        continue

        self.selector.close()
