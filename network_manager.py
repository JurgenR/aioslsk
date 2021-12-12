import logging
from selectors import EVENT_READ, EVENT_WRITE
import threading
from typing import List

from connection import (
    ListeningConnection,
    NetworkLoop,
    PeerConnection,
    ServerConnection,
)
import upnp


logger = logging.getLogger()


class NetworkManager:

    def __init__(self, settings):
        self.settings = settings

        self.upnp = upnp.UPNP()

        self.stop_event = threading.Event()
        self.network_loop: NetworkLoop = None
        self.server: ServerConnection = None
        self.listening_connections: List[ListeningConnection] = []
        self.peers: List[PeerConnection] = []

        self.peer_listener = None
        self.server_listener = None

    def initialize(self):
        logger.info("initializing network")

        # Init connections
        self.network_loop = NetworkLoop(self.stop_event)

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
            self.upnp.map_port(
                self.server.get_connecting_ip(),
                port,
                self.settings['upnp_lease_duration']
            )

    # Peer related
    def connect_to_peer(self, connection: PeerConnection):
        connection.listener = self
        connection.connect()

    def on_peer_connected(self, connection: PeerConnection):
        self.peer_listener.on_peer_connected(connection)
        self.network_loop.selector.register(
            connection.fileobj, EVENT_READ | EVENT_WRITE, connection)

    def on_peer_disconnected(self, connection: PeerConnection):
        self.peer_listener.on_peer_disconnected(connection)
        self.network_loop.selector.unregister(connection.fileobj)

    def on_peer_accepted(self, connection: PeerConnection):
        self.peer_listener.on_peer_accepted(connection)
        self.network_loop.selector.register(
            connection.fileobj, EVENT_READ | EVENT_WRITE, connection)

    def on_peer_message(self, message, connection: PeerConnection):
        self.peer_listener.on_peer_message(message, connection)


    # Server related
    def on_server_connected(self, connection: ServerConnection):
        self.server_listener.on_server_connected()
        self.network_loop.selector.register(
            connection.fileobj, EVENT_READ | EVENT_WRITE, connection)

    def on_server_disconnected(self, connection: ServerConnection):
        self.server_listener.on_server_disconnected()
        self.network_loop.selector.unregister(connection.fileobj)

    def on_server_message(self, message, connection: ServerConnection):
        self.server_listener.on_server_message(message)

    def send_server_messages(self, *messages):
        for message in messages:
            self.server.messages.put(message)


    # Listener related
    def on_listener_connected(self, connection):
        self.network_loop.selector.register(
            connection.fileobj, EVENT_READ, connection)

    def on_listener_disconnected(self, connection):
        self.network_loop.selector.unregister(connection.fileobj)
