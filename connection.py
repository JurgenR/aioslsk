from exceptions import PySlskException
import messages
import obfuscation

import errno
import logging
import queue
import selectors
import socket
import struct
import threading
import time
import types


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


class Connection:

    def __init__(self, hostname, port):
        self.hostname = hostname
        self.port = port
        self.connection = None
        self.is_closed = False


class ServerConnection(Connection):

    def __init__(self, hostname='server.slsknet.org', port=2416):
        super().__init__(hostname, port)
        self._buffer = b''
        self.messages = queue.Queue()
        self.listener = None
        self.last_interaction = 0

    def connect(self, selector):
        """Open connection and register on the given L{selector}"""
        logger.info(
            f"open {self.hostname}:{self.port}")
        self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection.setblocking(False)
        self.connection.connect_ex((self.hostname, self.port, ))
        selector.register(
            self.connection, selectors.EVENT_READ | selectors.EVENT_WRITE, data=self)

    def buffer(self, data):
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

    def __init__(self, hostname='0.0.0.0', port=64823, obfuscated=False):
        super().__init__(hostname, port)
        self._buffer = b''
        self.messages = queue.Queue()
        self.obfuscated = obfuscated
        self.listener = None
        self.last_interaction = 0

    def connect(self, selector):
        """Open connection and register on the given L{selector}"""
        logger.info(
            f"Opening listening connection on {self.hostname}:{self.port}")
        self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection.bind((self.hostname, self.port, ))
        self.connection.setblocking(False)
        self.connection.listen()
        selector.register(self.connection, selectors.EVENT_READ, data=self)

    def accept(self, sock, selector):
        conn, addr = sock.accept()
        try:
            existing_conn = get_connection_by_ip(selector, addr[0])
        except PySlskException:
            pass
        else:
            logger.debug(f"close {existing_conn.data.hostname}:{existing_conn.data.port} : prefer incoming connection")
            existing_conn.data.close(selector)
        conn.setblocking(False)
        logger.info(f"accept {addr[0]}:{addr[1]}")
        peer_connection = PeerConnection(
            hostname=addr[0], port=addr[1], obfuscated=self.obfuscated)
        peer_connection.connection = conn
        peer_connection.listener = self.listener
        selector.register(
            conn, selectors.EVENT_READ | selectors.EVENT_WRITE, data=peer_connection)
        return peer_connection


class PeerConnection(Connection):

    def __init__(self, hostname='0.0.0.0', port=None, obfuscated=False):
        super().__init__(hostname, port)
        self._buffer = b''
        self.messages = queue.Queue()
        self.obfuscated = obfuscated
        self.listener = None
        self.received_messages = []
        self.last_interaction = 0

    def connect(self, selector):
        """Open connection and register on the given L{selector}"""
        logger.info(
            f"open {self.hostname}:{self.port} : peer connection")
        self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection.setblocking(False)
        res = self.connection.connect_ex((self.hostname, self.port, ))
        logger.info(
            f"open {self.hostname}:{self.port} : peer connection, result {res} [{errno.errorcode[res]}]")
        selector.register(
            self.connection, selectors.EVENT_READ | selectors.EVENT_WRITE, data=self)

    def close(self, selector):
        """Closes the peer connection by unregistering it from the selector and
        closing the connection. If this is closed in the connection loop we
        must clear the message queue to avoid a message getting sent through
        this connection after we closed the connection
        """
        self.is_closed = True
        selector.unregister(self.connection)
        self.connection.close()

    def buffer(self, data):
        """Main entry point for incoming network data. The L{data} should always
        have a length of 4-bytes. This method will append the data to the
        internal L{_buffer} object and call 2 helper methods depending on the
        L{obfuscated} flag.
        """
        self._buffer += data
        if self.obfuscated:
            self.buffer_obfuscated(data)
        else:
            self.buffer_unobfuscated(data)

    def buffer_unobfuscated(self, data):
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

    def buffer_obfuscated(self, data):
        # Require at least 8 bytes (4 bytes key, 4 bytes length)
        if len(self._buffer) < (KEY_SIZE + 4):
            return
        # NOTE: We might a check here if we have a multiple of 4
        decoded_buffer = obfuscation.decode(self._buffer)

        _, msg_len = messages.parse_int(0, decoded_buffer)
        # Calculate total message length (message length + length indicator)
        total_msg_len = struct.calcsize('I') + msg_len
        if len(decoded_buffer) >= total_msg_len:
            message = decoded_buffer[:total_msg_len]
            logger.debug(
                "recv obfuscated peer message {}:{} : {!r}"
                .format(self.hostname, self.port, decoded_buffer.hex()[:8 * 2]))
            # Difference between buffer_unobfuscated, the key size is included
            self._buffer = self._buffer[total_msg_len + KEY_SIZE:]
            self.handle_message(message)

    def handle_message(self, message_data):
        try:
            message = messages.parse_peer_message(message_data)
            # print(f"Handle message {message_data}")
            self.received_messages.append(message)
            self.listener.on_peer_message(message)
        except Exception as exc:
            logger.error(
                f"Failed to handle peer message data {message_data}",
                exc_info=True)


class NetworkLoop(threading.Thread):

    def __init__(self, stop_event):
        super().__init__()
        self.selector = selectors.DefaultSelector()
        self.stop_event = stop_event

    def _is_already_connected(self, ip_addr):
        for val in self.selector.get_map().values():
            if ip_addr == val.data.hostname:
                return True
        return False

    def run(self):
        """Start the network loop, and run until L{stop_event} is set. This is
        the network loop for all L{Connection} instances.

        Reading:
        - The
        """
        last_time = 0
        while not self.stop_event.is_set():
            events = self.selector.select(timeout=None)
            current_time = int(time.time())
            # Debug how many connections are still open
            if current_time % 5 == 0 and current_time > last_time:
                last_time = current_time
                open_connections = [
                    repr(open_conn.fileobj)
                    for open_conn in self.selector.get_map().values()]
                # logger.debug("Connections open: {}".format(open_connections))
                logger.debug(
                    "Currently {} connections".format(len(self.selector.get_map())))
            for key, mask in events:
                if mask & selectors.EVENT_READ:
                    if isinstance(key.data, ListeningConnection):
                        # Accept incoming connections on the listening socket
                        peer_connection = key.data.accept(
                            key.fileobj, self.selector)
                    else:
                        # Server socket or peer socket
                        try:
                            recv_data = key.fileobj.recv(4)
                        except OSError as exc:
                            logger.exception(
                                f"Exception receiving data on connection {key.fileobj}")
                            # Only remove the peer connections?
                            logger.info(
                                f"close {key.data.hostname}:{key.data.port} : exception while reading")
                            key.data.close(self.selector)
                        else:
                            if recv_data:
                                key.data.last_interaction = current_time
                                key.data.buffer(recv_data)
                            if not recv_data:
                                logger.warning(
                                    f"close {key.data.hostname}:{key.data.port} : no data received")
                                key.data.close(self.selector)
                if mask & selectors.EVENT_WRITE:
                    # Prevents calling socket methods if it was closed in the
                    # read. Perhaps a better way would be calling continue after
                    # closing connection in the read, but there are other places
                    # where the connection is closed. Or put in a stack, to be
                    # closed
                    if key.data.is_closed:
                        continue
                    # Sockets will go into write even if an error occurred on
                    # them. Clean them up and move on if this happens
                    socket_err = key.fileobj.getsockopt(
                        socket.SOL_SOCKET, socket.SO_ERROR)
                    if socket_err != 0:
                        logger.debug(
                            "error {}:{} : {} [{}] : cleaning up"
                            .format(key.data.hostname, key.data.port, socket_err, errno.errorcode[socket_err]))
                        key.data.close(self.selector)
                        continue
                    try:
                        # Attempt to get the message from the Queue and send it
                        # over the socket it belongs to
                        message = key.data.messages.get(block=False)
                    except queue.Empty:
                        pass
                    else:
                        try:
                            logger.debug(f"send {key.data.hostname}:{key.data.port} : message {message}")
                            key.data.last_interaction = current_time
                            key.fileobj.sendall(message)
                        except OSError as exc:
                            logger.exception(
                                f"close {key.data.hostname}:{key.data.port} : exception while sending")
                            key.data.close(self.selector)
        self.selector.close()
