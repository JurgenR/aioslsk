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


def is_already_connected(selector, ip_addr):
    for val in selector.get_map().values():
        if ip_addr == val.data.hostname:
            return val
    return None


def get_connection_by_ip(selector, ip_addr):
    for val in selector.get_map().values():
        if ip_addr == val.data.hostname:
            return val
    raise PySlskException(f"No connection with IP address {ip_addr} in selector")


class PeerConnectionType:
    FILE = 'F'
    PEER = 'P'
    DISTRIBUTED = 'D'


class Connection:

    def __init__(self, hostname: str, port: int):
        self.hostname = hostname
        self.port = port
        self.fileobj = None


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

    def connect(self, selector):
        """Open connection and register on the given L{selector}"""
        logger.info(
            f"open {self.hostname}:{self.port}")
        self.fileobj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.fileobj.setblocking(False)
        self.fileobj.connect_ex((self.hostname, self.port, ))
        selector.register(
            self.fileobj, selectors.EVENT_READ | selectors.EVENT_WRITE, data=self)

    def buffer(self, data):
        """Adds data to the internal L{_buffer} and tries to detects whether a
        message is complete. If a message is complete the L{handle_message}
        method is called and L{_buffer} is cleared.

        Detection is done by parsing the message length and comparing if the
        current L{_buffer} object has the desired length.

        If the length of the buffer is greater than the detected length then
        the extra bytes are kept in the L{_buffer} and only the message is
        removed
        """
        self._buffer += data
        _, msg_len = messages.parse_int(0, self._buffer)
        msg_len_with_len = struct.calcsize('I') + msg_len
        if len(self._buffer) >= msg_len_with_len:
            message = self._buffer[:msg_len_with_len]
            logger.debug(
                "server message {}:{} : {!r}"
                .format(self.hostname, self.port, self._buffer.hex()[:8 * 2]))
            # Remove message from buffer
            self._buffer = self._buffer[msg_len_with_len:]
            self.handle_message(message)

    def handle_message(self, message_data):
        try:
            message = messages.parse_message(message_data)
            # print(f"Handle message {message_data}")
            self.listener.on_message(message)
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

    def connect(self, selector):
        """Open connection and register on the given L{selector}"""
        logger.info(
            f"open {self.hostname}:{self.port} : listening connection")
        self.fileobj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.fileobj.bind((self.hostname, self.port, ))
        self.fileobj.setblocking(False)
        self.fileobj.listen()
        selector.register(self.fileobj, selectors.EVENT_READ, data=self)

    def accept(self, sock, selector):
        """Accept the incoming connection (L{sock}) and registers it with the
        given L{selector}.
        """
        fileobj, addr = sock.accept()
        logger.info(f"accepted {addr[0]}:{addr[1]}")
        fileobj.setblocking(False)

        peer_connection = PeerConnection(
            hostname=addr[0], port=addr[1], obfuscated=self.obfuscated, listener=self.listener)
        peer_connection.fileobj = fileobj

        # Register it to the selector
        selector.register(fileobj, selectors.EVENT_READ | selectors.EVENT_WRITE, data=peer_connection)
        return peer_connection


class PeerConnection(Connection):

    def __init__(
            self, hostname='0.0.0.0', port=None, obfuscated=False,
            listener=None, connection_type=PeerConnectionType.PEER):
        super().__init__(hostname, port)
        self._buffer = b''
        self.listener = listener
        self.messages = queue.Queue()
        self.received_messages = []
        self.obfuscated = obfuscated
        self.last_interaction = 0
        self.connection_type = connection_type
        self.fileobj = None

    def connect(self, selector):
        """Open connection and register on the given L{selector}"""
        logger.info(f"open {self.hostname}:{self.port} : peer connection")
        self.fileobj = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.fileobj.setblocking(False)
        res = self.fileobj.connect_ex((self.hostname, self.port, ))
        logger.info(f"open {self.hostname}:{self.port} : peer connection, result {res} [{errno.errorcode[res]}]")

        # This can return error code 10035 (WSAEWOULDBLOCK) which can be ignored
        # What to do with other error codes?
        selector.register(
            self.fileobj, selectors.EVENT_READ | selectors.EVENT_WRITE, data=self)

    def close(self, selector):
        """Closes the peer connection by unregistering it from the selector and
        closing the connection. If this is closed in the connection loop we
        must clear the message queue to avoid a message getting sent through
        this connection after we closed the connection
        """
        selector.unregister(self.fileobj)
        self.fileobj.close()

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
            raise Exception("Invalid buffer size for obfuscated message")

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
        if self.connection_type in (PeerConnectionType.PEER, PeerConnectionType.DISTRIBUTED, ):
            try:
                if self.connection_type == PeerConnectionType.PEER:
                    message = messages.parse_peer_message(message_data)
                else:
                    message = messages.parse_distributed_message(message_data)
                self.listener.on_peer_message(message, connection=self)
            except Exception as exc:
                logger.error(
                    f"Failed to handle peer ({self.connection_type}) message data {message_data}", exc_info=True)
            else:
                self.received_messages.append(message)

        elif self.connection_type == PeerConnectionType.FILE:
            raise NotImplementedError("File connections not yet implemented")

        else:
            raise Exception(
                f"Unknown connection type assigned to this peer connection {self.connection_type!r}")


class NetworkLoop(threading.Thread):

    def __init__(self, stop_event):
        super().__init__()
        self.selector = selectors.DefaultSelector()
        self.stop_event = stop_event
        self._last_log_time = 0

    def _is_already_connected(self, ip_addr):
        for val in self.selector.get_map().values():
            if ip_addr == val.data.hostname:
                return True
        return False

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

    def close_connection(self, connection_obj: Connection, work_socket):
        """Closes the connection and removes it from the selector"""
        self.selector.unregister(work_socket)
        work_socket.close()
        connection_obj.fileobj = None

    def run(self):
        """Start the network loop, and run until L{stop_event} is set. This is
        the network loop for all L{Connection} instances.
        """
        while not self.stop_event.is_set():
            events = self.selector.select(timeout=None)
            self._log_open_connections()
            current_time = time.time()

            for key, mask in events:
                work_socket = key.fileobj
                connection_obj = key.data

                if mask & selectors.EVENT_READ:
                    # Listening connection
                    if isinstance(connection_obj, ListeningConnection):
                        # Accept incoming connections on the listening socket
                        peer_connection = connection_obj.accept(work_socket, self.selector)
                        continue

                    # Server socket or peer socket
                    try:
                        recv_data = work_socket.recv(4)
                    except OSError as exc:
                        logger.exception(f"Exception receiving data on connection {work_socket}")
                        # Only remove the peer connections?
                        logger.info(f"close {connection_obj.hostname}:{connection_obj.port} : exception while reading")
                        self.close_connection(connection_obj, work_socket)
                        continue
                    else:
                        if recv_data:
                            connection_obj.last_interaction = current_time
                            connection_obj.buffer(recv_data)
                        else:
                            logger.warning(
                                f"close {connection_obj.hostname}:{connection_obj.port} : no data received")
                            self.close_connection(connection_obj, work_socket)
                            continue

                if mask & selectors.EVENT_WRITE:
                    # Sockets will go into write even if an error occurred on
                    # them. Clean them up and move on if this happens
                    socket_err = work_socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                    if socket_err != 0:
                        logger.debug(
                            "error {}:{} : {} [{}] : cleaning up"
                            .format(connection_obj.hostname, connection_obj.port, socket_err, errno.errorcode[socket_err]))
                        self.close_connection(connection_obj, work_socket)
                        continue

                    try:
                        # Attempt to get the message from the Queue and send it
                        # over the socket it belongs to
                        message = connection_obj.messages.get(block=False)
                    except queue.Empty:
                        pass
                    else:
                        try:
                            logger.debug(f"send {connection_obj.hostname}:{connection_obj.port} : message {message.hex()}")
                            connection_obj.last_interaction = current_time
                            work_socket.sendall(message)
                        except OSError as exc:
                            logger.exception(
                                f"close {connection_obj.hostname}:{connection_obj.port} : exception while sending")
                            self.close_connection(connection_obj, work_socket)
                            continue

        self.selector.close()


class NetworkManager:

    def __init__(self, settings):
        self.settings = settings

        self.upnp = upnp.UPNP()

        self.stop_event = threading.Event()
        self.network_loop: NetworkLoop = None
        self.server: ServerConnection = None
        self.listening_connections = []
        self.peers = []

    def send_server_message(self, message):
        self.server.messages.put(message)

    def initialize(self, listener):
        logger.info("initializing network")

        # Init connections
        self.network_loop = NetworkLoop(self.stop_event)

        self.server = ServerConnection(
            hostname=self.settings['server_hostname'],
            port=self.settings['server_port'],
            listener=listener
        )
        self.listening_connections = [
            ListeningConnection(
                port=self.settings['listening_port'],
                listener=listener
            ),
            ListeningConnection(
                port=self.settings['listening_port'] + 1,
                obfuscated=True,
                listener=listener
            )
        ]

        # Perform the socket connections and start the network loop
        self.server.connect(self.network_loop.selector)
        for listening_connection in self.listening_connections:
            listening_connection.connect(self.network_loop.selector)

        self.network_loop.start()

        if self.settings['use_upnp']:
            self.enable_upnp()

    def quit(self):
        logger.debug("stopping network")
        self.stop_event.set()
        self.network_loop.join(timeout=60)
        if self.network_loop.is_alive():
            pass

    def enable_upnp(self):
        listening_port = self.settings['listening_port']
        for port in [listening_port, listening_port + 1, ]:
            self.upnp.map_port(self.server.get_connecting_ip(), port)

    def create_peer_connection(self):
        pass
