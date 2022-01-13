from cachetools import TTLCache
from dataclasses import dataclass, field
import logging
from selectors import EVENT_READ, EVENT_WRITE
import threading
from typing import List

from connection import (
    Connection,
    ConnectionState,
    CloseReason,
    ListeningConnection,
    NetworkLoop,
    PeerConnection,
    PeerConnectionType,
    ServerConnection,
)
from messages import (
    Message,
    CannotConnect,
    ConnectToPeer,
    GetPeerAddress,
    PeerInit,
    PeerPierceFirewall,
)
import upnp


logger = logging.getLogger()


@dataclass
class ConnectionRequest:
    ticket: int
    username: str
    is_requested_by_us: bool
    ip: str = None
    port: int = 0
    typ: str = None
    connection: PeerConnection = None
    messages: List[Message] = field(default_factory=lambda: [])


class NetworkManager:

    def __init__(self, settings, stop_event, cache_lock):
        self.settings = settings

        self.upnp = upnp.UPNP()

        self.stop_event = stop_event
        self.cache_lock = cache_lock
        self.lock = threading.Lock()

        self.network_loop: NetworkLoop = None
        self.server: ServerConnection = None
        self.listening_connections: List[ListeningConnection] = []

        self.connection_requests = TTLCache(maxsize=1000, ttl=15 * 60)

        self.peer_listener = None
        self.server_listener = None

    def initialize(self):
        logger.info("initializing network")

        # Init connections
        self.network_loop = NetworkLoop(self.settings, self.stop_event, self.lock)

        self.server = ServerConnection(
            hostname=self.settings['network']['server_hostname'],
            port=self.settings['network']['server_port'],
            listeners=[self, self.server_listener, ]
        )
        self.listening_connections = [
            ListeningConnection(
                port=self.settings['network']['listening_port'],
                listeners=[self, ]
            ),
            ListeningConnection(
                port=self.settings['network']['listening_port'] + 1,
                obfuscated=True,
                listeners=[self, ]
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
        listening_port = self.settings['network']['listening_port']
        for port in [listening_port, listening_port + 1, ]:
            self.upnp.map_port(
                self.server.get_connecting_ip(),
                port,
                self.settings['network']['upnp_lease_duration']
            )

    def expire_caches(self):
        with self.cache_lock:
            self.connection_requests.expire()

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

        elif state == ConnectionState.CONNECTED:
            # For registering with UPNP we need to know our own IP first, we can
            # get this from the server connection but we first need to be
            # fully connected to it before we can request a valid IP
            if self.settings['network']['use_upnp']:
                self.enable_upnp()

        elif state == ConnectionState.CLOSED:
            self._unregister_from_network_loop(connection.fileobj)

    def _on_peer_connection_state_changed(self, state: ConnectionState, connection: PeerConnection, close_reason=None):
        if state == ConnectionState.CONNECTING:
            self._register_to_network_loop(
                connection.fileobj, EVENT_READ | EVENT_WRITE, connection)

        elif state == ConnectionState.CONNECTED:
            with self.cache_lock:
                for ticket, request in self.connection_requests.items():
                    if connection == request.connection:
                        logger.debug(f"handled connection request (ticket={ticket})")
                        self.connection_requests.pop(ticket)
                        self.peer_listener.create_peer(request.username, connection)
                        break

        elif state == ConnectionState.CLOSED:
            self._unregister_from_network_loop(connection.fileobj)

            if close_reason == CloseReason.CONNECT_FAILED:
                with self.cache_lock:
                    for ticket, connection_req in self.connection_requests.items():
                        if connection != connection_req.connection:
                            continue

                        if connection_req.is_requested_by_us:
                            # In case we want to connect to someone, don't give up just yet
                            # and send a ConnectToPeer
                            self.send_server_messages(
                                ConnectToPeer.create(
                                    connection_req.ticket,
                                    connection_req.username,
                                    connection_req.typ
                                )
                            )
                        else:
                            # In case we failed to connect to the other after they requested it, give up
                            self.send_server_messages(
                                CannotConnect.create(ticket, connection_req.username)
                            )
                            self.connection_requests.pop(ticket)
                            break

    def _on_listening_connection_state_changed(self, state: ConnectionState, connection: ListeningConnection):
        if state == ConnectionState.CONNECTING:
            self._register_to_network_loop(
                connection.fileobj, EVENT_READ, connection)

        elif state == ConnectionState.CLOSED:
            self._unregister_from_network_loop(connection.fileobj)


    # Peer related

    def on_peer_accepted(self, connection: PeerConnection):
        connection.listeners = [self, self.peer_listener, ]
        self._register_to_network_loop(
            connection.fileobj, EVENT_READ | EVENT_WRITE, connection)

    def on_peer_message(self, message, connection: PeerConnection):
        if message.MESSAGE_ID == PeerInit.MESSAGE_ID:
            username, typ, ticket = message.parse()
            logger.info(f"PeerInit from {username}, {typ}, {ticket}")

            # Maybe this is misplaced?
            connection.connection_type = typ.decode('utf-8')

            self.peer_listener.create_peer(username, connection)

        elif message.MESSAGE_ID == PeerPierceFirewall.MESSAGE_ID:
            ticket = message.parse()
            logger.debug(f"PeerPierceFirewall (connection={connection}, ticket={ticket})")

            try:
                with self.cache_lock:
                    request = self.connection_requests.pop(ticket)
            except KeyError:
                logger.warning(f"received PeerPierceFirewall with unknown ticket {ticket}")
                return

            connection.connection_type = request.typ
            self.peer_listener.create_peer(request.username, connection)
            logger.debug(f"handled connection ticket {ticket}")

            # I'm seeing connections that go from obfuscated to non-obfuscated
            # for some reason but only for distributed connections
            if connection.obfuscated and request.typ == PeerConnectionType.DISTRIBUTED:
                logger.debug(f"setting connection to unobfuscated : {connection}")
                connection.obfuscated = False

            # We get here when we failed to connect, after which we sent a
            # ConnectToPeer. We probably still have some messages that were never
            # sent
            if request.is_requested_by_us:
                for queued_message in request.messages:
                    connection.messages.put(queued_message)

    def init_peer_connection(self, ticket, username, typ, ip=None, port=None, messages=None):
        messages = [] if messages is None else messages
        connection_request = ConnectionRequest(
            ticket=ticket,
            username=username,
            typ=typ,
            is_requested_by_us=True,
            ip=ip,
            port=port,
            messages=messages
        )

        with self.cache_lock:
            self.connection_requests[ticket] = connection_request

        if ip is None and port is None:
            # Request peer address if ip and port are not given
            self.send_server_messages(GetPeerAddress.create(username))

        else:
            self._connect_to_peer(ticket, connection_request)

    def _connect_to_peer(self, ticket, connection_request):
        """Attempts to establish a connection to a peer"""
        peer_connection = PeerConnection(
            hostname=connection_request.ip,
            port=connection_request.port,
            connection_type=connection_request.typ,
            listeners=[self, self.peer_listener, ]
        )
        with self.cache_lock:
            connection_request.connection = peer_connection

        if connection_request.is_requested_by_us:
            peer_connection.messages.put(
                PeerInit.create(
                    self.settings['credentials']['username'],
                    connection_request.typ,
                    connection_request.ticket
                )
            )
        else:
            peer_connection.messages.put(
                PeerPierceFirewall.create(connection_request.ticket)
            )

        peer_connection.connect()

    # Server related

    def on_server_message(self, message, connection: ServerConnection):
        if message.MESSAGE_ID == CannotConnect.MESSAGE_ID:
            ticket, username = message.parse()
            logger.debug(f"got CannotConnect: {ticket} , {username}")
            with self.cache_lock:
                try:
                    self.connection_requests.pop(ticket)
                except KeyError:
                    logger.warning(
                        f"CannotConnect : ticket {ticket} (username={username}) was not found in cache")
                else:
                    logger.debug(f"CannotConnect : removed ticket {ticket} (username={username}) from cache")

        elif message.MESSAGE_ID == ConnectToPeer.MESSAGE_ID:
            contents = message.parse()
            logger.info("ConnectToPeer message contents: {!r}".format(contents))
            username, typ, ip, port, ticket, privileged, unknown, obfuscated_port = contents

            connection_request = ConnectionRequest(
                ticket=ticket,
                username=username,
                typ=typ.decode('utf-8'),
                is_requested_by_us=False,
                ip=ip,
                port=port
            )
            with self.cache_lock:
                self.connection_requests[ticket] = connection_request

            self._connect_to_peer(ticket, connection_request)

        elif message.MESSAGE_ID == GetPeerAddress.MESSAGE_ID:
            username, ip, port, _, obfuscated_port = message.parse()
            if ip == '0.0.0.0':
                logger.warning(f"GetPeerAddress: no address returned for username : {username}")
                return

            with self.cache_lock:
                for ticket, request in self.connection_requests.items():
                    if request.username == username:
                        request.ip = ip
                        request.port = port
                        self._connect_to_peer(ticket, request)

    def send_server_messages(self, *messages):
        for message in messages:
            self.server.messages.put(message)
