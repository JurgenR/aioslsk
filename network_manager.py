import logging
from selectors import EVENT_READ, EVENT_WRITE
import threading
from typing import List

from connection import (
    Connection,
    ConnectionState,
    ListeningConnection,
    NetworkLoop,
    PeerConnection,
    ServerConnection,
)
import upnp


logger = logging.getLogger()


class NetworkManager:

    def __init__(self, settings, stop_event):
        self.settings = settings

        self.upnp = upnp.UPNP()

        self.stop_event = stop_event
        self.lock = threading.Lock()
        self.network_loop: NetworkLoop = None
        self.server: ServerConnection = None
        self.listening_connections: List[ListeningConnection] = []

        self.peer_listener = None
        self.server_listener = None

    def initialize(self):
        logger.info("initializing network")

        # Init connections
        self.network_loop = NetworkLoop(self.settings, self.stop_event, self.lock)

        self.server = ServerConnection(
            hostname=self.settings['server_hostname'],
            port=self.settings['server_port'],
            listener=self
        )
        self.listening_connections = [
            ListeningConnection(
                port=self.settings['listening_port'],
                listener=self
            ),
            ListeningConnection(
                port=self.settings['listening_port'] + 1,
                obfuscated=True,
                listener=self
            )
        ]

        # Perform the socket connections and start the network loop
        self.server.connect()
        for listening_connection in self.listening_connections:
            listening_connection.connect()

        self.network_loop.start()

    def get_network_loops(self):
        return [self.network_loop, ]

    def enable_upnp(self):
        listening_port = self.settings['listening_port']
        for port in [listening_port, listening_port + 1, ]:
            self.upnp.map_port(
                self.server.get_connecting_ip(),
                port,
                self.settings['upnp_lease_duration']
            )

    def _register_to_network_loop(self, fileobj, events, connection):
        self.network_loop.selector.register(fileobj, events, connection)

    def _unregister_from_network_loop(self, fileobj):
        self.network_loop.selector.unregister(fileobj)

    # Connection state changes
    def on_state_changed(self, state: ConnectionState, connection: Connection, close_reason=None):
        """Called when the state of a connection changes. This method calls 3
        private method based on the type of L{connection} that was passed

        @param state: the new state the connection has received
        @param connection: the connection for which the state changed
        @param close_reason: in case ConnectionState.CLOSED is passed a reason
            will be given as well, this is useful when we need to send a
            CannotConnect to the server after a ConnectToPeer was sent and we
            failed to connect to that peer
        """
        if isinstance(connection, ServerConnection):
            self._on_server_connection_state_changed(state, connection, close_reason=close_reason)

        elif isinstance(connection, PeerConnection):
            self._on_peer_connection_state_changed(state, connection, close_reason=close_reason)

        elif isinstance(connection, ListeningConnection):
            self._on_listening_connection_state_changed(state, connection)

    def _on_server_connection_state_changed(self, state: ConnectionState, connection: ServerConnection, close_reason=None):
        if state == ConnectionState.CONNECTING:
            self._register_to_network_loop(
                connection.fileobj, EVENT_READ | EVENT_WRITE, connection)
            self.server_listener.on_connecting()

        elif state == ConnectionState.CONNECTED:
            self.server_listener.on_connected()
            # For registering with UPNP we need to know our own IP first, we can
            # get this from the server connection but we first need to be
            # fully connected to it before we can request a valid IP
            if self.settings['use_upnp']:
                self.enable_upnp()

        elif state == ConnectionState.CLOSED:
            self._unregister_from_network_loop(connection.fileobj)
            self.server_listener.on_closed(reason=close_reason)

    def _on_peer_connection_state_changed(self, state: ConnectionState, connection: PeerConnection, close_reason=None):
        if state == ConnectionState.CONNECTING:
            self._register_to_network_loop(
                connection.fileobj, EVENT_READ | EVENT_WRITE, connection)
            self.peer_listener.on_connecting(connection)

        elif state == ConnectionState.CLOSED:
            self._unregister_from_network_loop(connection.fileobj)
            self.peer_listener.on_closed(connection, reason=close_reason)

    def _on_listening_connection_state_changed(self, state: ConnectionState, connection: ListeningConnection):
        if state == ConnectionState.CONNECTING:
            self._register_to_network_loop(
                connection.fileobj, EVENT_READ, connection)

        elif state == ConnectionState.CLOSED:
            self._unregister_from_network_loop(connection.fileobj)


    # Peer related
    def connect_to_peer(self, connection: PeerConnection, username: str):
        """This method should be called by the ServerManager in case it needs to
        connect to a peer. The PeerManager is then notified that we should add
        another peer to the list
        """
        self.peer_listener.on_connect_to_peer(connection, username)
        connection.listener = self
        connection.connect()

    def on_peer_accepted(self, connection: PeerConnection):
        self._register_to_network_loop(
            connection.fileobj, EVENT_READ | EVENT_WRITE, connection)
        self.peer_listener.on_accepted(connection)

    def on_peer_message(self, message, connection: PeerConnection):
        self.peer_listener.on_peer_message(message, connection)


    # Server related

    def on_server_message(self, message, connection: ServerConnection):
        self.server_listener.on_server_message(message)

    def send_server_messages(self, *messages):
        for message in messages:
            self.server.messages.put(message)
