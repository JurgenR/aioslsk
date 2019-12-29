import messages
import obfuscation

import logging
import queue
import selectors
import socket
import struct
import types
import threading


logger = logging.getLogger()


class Connection:
    pass


class ServerConnection(Connection):

    def __init__(self, hostname='server.slsknet.org', port=2416):
        self._buffer = b''
        self.messages = queue.Queue()
        self.connection = None
        self.hostname = hostname
        self.port = port
        self.listener = None

    def connect(self, selector):
        """Open connection and register on the given L{selector}"""
        logger.info(
            f"Opening server connection on {self.hostname}:{self.port}")
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
            print(
                "End of message from {}:{} : {!r}"
                .format(self.hostname, self.port, self._buffer.hex()[:8 * 2]))
            # Remove message from buffer
            self._buffer = self._buffer[msg_len_with_len:]
            self.handle_message(message)

    def handle_message(self, message_data):
        message = messages.parse_message(message_data)
        # print(f"Handle message {message_data}")
        self.listener.on_message(message)


class ListeningConnection(Connection):
    """A listening connection, objects of this class are responsible for
    accepting incoming connections

    """

    def __init__(self, hostname='0.0.0.0', port=64823, obfuscated=False):
        self._buffer = b''
        self.messages = queue.Queue()
        self.connection = None
        self.hostname = hostname
        self.port = port
        self.obfuscated = obfuscated
        self.listener = None

    def connect(self, selector):
        """Open connection and register on the given L{selector}"""
        logger.info(
            f"Opening listening connection on {self.hostname}:{self.port}")
        self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection.bind((self.hostname, self.port, ))
        self.connection.listen()
        self.connection.setblocking(False)
        selector.register(self.connection, selectors.EVENT_READ, data=self)

    def accept(self, sock, selector):
        conn, addr = sock.accept()
        conn.setblocking(False)
        logger.info(f"Accepted incoming connection from {addr}")
        peer_connection = PeerConnection(hostname=addr, obfuscated=self.obfuscated)
        peer_connection.connection = conn
        peer_connection.listener = self.listener
        selector.register(
            conn, selectors.EVENT_READ | selectors.EVENT_WRITE, data=peer_connection)
        return peer_connection


class PeerConnection(Connection):

    def __init__(self, hostname='0.0.0.0', port=None, obfuscated=False):
        self._buffer = b''
        self.messages = queue.Queue()
        self.connection = None
        self.hostname = hostname
        self.port = port
        self.obfuscated = obfuscated
        self.listener = None

    def connect(self, selector):
        """Open connection and register on the given L{selector}"""
        logger.info(
            f"Opening peer connection on {self.hostname}:{self.port}")
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
            print(
                "End of peer message from {}:{} : {!r}"
                .format(self.hostname, self.port, self._buffer.hex()[:8 * 2]))
            self._buffer = self._buffer[msg_len_with_len:]
            self.handle_message(message)

    def handle_message(self, message_data):
        message = messages.parse_peer_message(message_data)
        # print(f"Handle message {message_data}")
        self.listener.on_peer_message(message)


class NetworkLoop(threading.Thread):

    def __init__(self, stop_event):
        super().__init__()
        self.selector = selectors.DefaultSelector()
        self.stop_event = stop_event

    def run(self):
        while not self.stop_event.is_set():
            events = self.selector.select(timeout=0)
            for key, mask in events:
                if mask & selectors.EVENT_READ:
                    if isinstance(key.data, ListeningConnection):
                        # The listening socket
                        peer_connection = key.data.accept(
                            key.fileobj, self.selector)
                    else:
                        # Server socket or peer socket
                        try:
                            recv_data = key.fileobj.recv(4)
                        except OSError as exc:
                            logger.exception(
                                f"Exception receiving data on connection {key.fileobj}")
                        else:
                            if recv_data:
                                key.data.buffer(recv_data)
                            if not recv_data:
                                logger.warning(f"Closing connection to {key.fileobj}")
                                self.selector.unregister(key.fileobj)
                if mask & selectors.EVENT_WRITE:
                    try:
                        message = key.data.messages.get(block=False)
                    except queue.Empty:
                        pass
                    else:
                        logger.debug(f"Sending {message} to {key.fileobj}")
                        key.fileobj.sendall(message)
        self.selector.close()
