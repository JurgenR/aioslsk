from __future__ import annotations
from cachetools import TTLCache
from dataclasses import dataclass, field
from functools import partial
import logging
from selectors import EVENT_READ, EVENT_WRITE
import threading
from typing import Callable, List

from .connection import (
    Connection,
    ConnectionState,
    CloseReason,
    PeerConnectionState,
    ListeningConnection,
    NetworkLoop,
    PeerConnection,
    PeerConnectionType,
    ServerConnection,
)
from .events import on_message
from .messages import (
    CannotConnect,
    ConnectToPeer,
    GetPeerAddress,
    PeerInit,
    PeerPierceFirewall,
)
from . import upnp
from .transfer import Transfer, TransferDirection


logger = logging.getLogger()


@dataclass
class ConnectionRequest:
    ticket: int
    username: str
    is_requested_by_us: bool
    """Should be False if we received a ConnectToPeer message from another user"""
    ip: str = None
    port: int = None
    typ: str = None
    connection: PeerConnection = None
    transfer: Transfer = None
    messages: List[bytes] = field(default_factory=lambda: [])
    """List of messages to be delivered when connection is established"""
    on_failure: Callable = None
    """Callback called when connection cannot be initialized"""


class NetworkManager:

    def __init__(self, settings, stop_event):
        self._settings = settings

        self.upnp = upnp.UPNP()

        self.stop_event = stop_event
        self._cache_lock = threading.Lock()

        self.network_loop: NetworkLoop = None
        self.server: ServerConnection = None
        self.listening_connections: List[ListeningConnection] = []

        self.connection_requests = TTLCache(maxsize=1000, ttl=5 * 60)

        self.peer_listener = None
        self.server_listener = None
        self.transfer_listener = None

    def initialize(self):
        logger.info("initializing network")

        # Init connections
        self.network_loop = NetworkLoop(self._settings, self.stop_event)

        self.server = ServerConnection(
            hostname=self._settings['network']['server_hostname'],
            port=self._settings['network']['server_port'],
            listeners=[self, self.server_listener, ]
        )
        self.listening_connections = [
            ListeningConnection(
                port=self._settings['network']['listening_port'],
                listeners=[self, ]
            ),
            ListeningConnection(
                port=self._settings['network']['listening_port'] + 1,
                obfuscated=True,
                listeners=[self, ]
            )
        ]

        # Perform the socket connections and start the network loop
        self.server.connect()
        for listening_connection in self.listening_connections:
            listening_connection.connect()

        self.network_loop.start()

    def get_connections(self):
        return self.network_loop.get_connections()

    def get_network_loops(self):
        return [self.network_loop, ]

    def enable_upnp(self):
        listening_port = self._settings['network']['listening_port']
        for port in [listening_port, listening_port + 1, ]:
            self.upnp.map_port(
                self.server.get_connecting_ip(),
                port,
                self._settings['network']['upnp_lease_duration']
            )

    def expire_caches(self):
        with self._cache_lock:
            self.connection_requests.expire()

    def _register_to_network_loop(self, fileobj, events, connection):
        self.network_loop.selector.register(fileobj, events, connection)

    def _unregister_from_network_loop(self, fileobj):
        self.network_loop.selector.unregister(fileobj)

    # Connection state changes
    def on_state_changed(self, state: ConnectionState, connection: Connection, close_reason: CloseReason = None):
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

    def _on_server_connection_state_changed(self, state: ConnectionState, connection: ServerConnection, close_reason: CloseReason = None):
        if state == ConnectionState.CONNECTING:
            self._register_to_network_loop(
                connection.fileobj, EVENT_READ | EVENT_WRITE, connection)

        elif state == ConnectionState.CONNECTED:
            # For registering with UPNP we need to know our own IP first, we can
            # get this from the server connection but we first need to be
            # fully connected to it before we can request a valid IP
            if self._settings['network']['use_upnp']:
                self.enable_upnp()

        elif state == ConnectionState.CLOSED:
            self._unregister_from_network_loop(connection.fileobj)

    def _on_peer_connection_state_changed(self, state: ConnectionState, connection: PeerConnection, close_reason: CloseReason = None):
        if state == ConnectionState.CONNECTING:
            self._register_to_network_loop(
                connection.fileobj, EVENT_READ | EVENT_WRITE, connection)

        elif state == ConnectionState.CLOSED:
            self._unregister_from_network_loop(connection.fileobj)

            if close_reason == CloseReason.CONNECT_FAILED:
                with self._cache_lock:
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
                            self.fail_peer_connection_request(connection_req)
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

    def init_peer_connection(
            self, ticket: int, username: str, typ, ip: str = None, port: int = None,
            transfer: Transfer = None, messages=None, on_failure=None) -> ConnectionRequest:
        """Starts the process of peer connection initialization.

        The L{ip} and L{port} parameters are optional, in case they are missing
        a L{GetPeerAddress} message will be sent to request this information

        @param ticket: ticket to be used throughout the process
        @param username: username of the peer to connect to
        @param typ: type of peer connection
        @param ip: IP address of the peer (Default: None)
        @param port: port to which to connect (Default: None)
        @param messages: list of messages to be delivered when the connection
            is successfully established (Default: None)
        @param on_failure: callback for when connection failed

        @return: created L{ConnectionRequest} object
        """
        messages = [] if messages is None else messages
        connection_request = ConnectionRequest(
            ticket=ticket,
            username=username,
            typ=typ,
            is_requested_by_us=True,
            ip=ip,
            port=port,
            transfer=transfer,
            messages=messages,
            on_failure=on_failure
        )

        with self._cache_lock:
            self.connection_requests[ticket] = connection_request

        if ip is None and port is None:
            # Request peer address if ip and port are not given
            self.send_server_messages(GetPeerAddress.create(username))
        else:
            with self._cache_lock:
                self._connect_to_peer(ticket, connection_request)

        return connection_request

    def _connect_to_peer(self, ticket, request: ConnectionRequest) -> PeerConnection:
        """Attempts to establish a connection to a peer. This method will create
        the connection object and send a PeerInit or PeerPierceFirewall based
        on the L{request} passed to this method.

        The connection will automatically be attached to the network loop based
        on the state of the connection
        """
        connection = PeerConnection(
            hostname=request.ip,
            port=request.port,
            connection_type=request.typ,
            listeners=[self, self.peer_listener, ]
        )
        request.connection = connection

        if request.is_requested_by_us:
            connection.queue_message(
                PeerInit.create(
                    self._settings['credentials']['username'],
                    request.typ,
                    request.ticket
                ),
                callback=partial(self.finalize_peer_connection, request, connection)
            )
        else:
            connection.queue_message(
                PeerPierceFirewall.create(request.ticket),
                callback=partial(self.finalize_peer_connection, request, connection)
            )

        connection.connect()
        return connection

    def finalize_peer_connection(self, request: ConnectionRequest, connection: PeerConnection):
        """Method to be called after initialization of the peer connection has
        complete. In summary this would mean the connection should currently be
        in the following state:

        - ConnectionState: CONNECTED
        - PeerConnectionState: AWAITING_INIT

        This method will decide the following PeerConnectionState depending on
        the values from the request.

        It will also remove the connection request from the cache and queue any
        messages that are set in the connection request.

        @param request: the associated L{ConnectionRequest} object
        @param connection: the associated L{PeerConnection} object
        """
        logger.debug(f"finalizing peer connection : {request!r}")

        connection.connection_type = request.typ
        # A bit overkill
        connection.transfer = request.transfer
        if request.transfer is not None:
            request.transfer.connection = connection

        self.peer_listener.create_peer(request.username, connection)

        # Non-peer connections always go to unobfuscated after initialization
        if request.typ != PeerConnectionType.PEER:
            logger.debug(f"setting obfuscated to false for connection : {connection!r}")
            connection.obfuscated = False

        # File connections should go into AWAITING_TICKET or AWAITING_OFFSET
        # depending on the state of the transfer
        if request.typ == PeerConnectionType.FILE:
            connection.transfer_listeners.append(self.transfer_listener)
            # The transfer for the request will be none if the peer is connecting
            # to us. We don't know for which transfer he is connecting us yet
            if request.transfer is None:
                connection.set_connection_state(PeerConnectionState.AWAITING_TICKET)
            else:
                if request.transfer.direction == TransferDirection.DOWNLOAD:
                    connection.set_connection_state(PeerConnectionState.AWAITING_TICKET)
                else:
                    connection.set_connection_state(PeerConnectionState.AWAITING_OFFSET)
        else:
            connection.set_connection_state(PeerConnectionState.ESTABLISHED)

        # Remove the connection request
        if request.ticket is not None and request.ticket != 0:
            with self._cache_lock:
                try:
                    self.connection_requests.pop(request.ticket)
                except KeyError:
                    logger.warning(
                        f"finalized a peer connection for an unknown ticket (ticket={request.ticket})")

        for message in request.messages:
            connection.queue_message(message)

    def fail_peer_connection_request(self, connection_request: ConnectionRequest):
        """Method called after peer connection could not be established. It is
        called after the following 3 situations:

        - GetPeerAddress returned nothing
        - We received a CannotConnect from the server
        - We sent a ConnectToPeer to the server but didn't get an incoming
          connection in a timely fashion
        """
        if connection_request.on_failure is not None:
            connection_request.on_failure(connection_request)

    # Server related

    @on_message(PeerInit)
    def on_peer_init(self, message, connection: PeerConnection):
        username, typ, ticket = message.parse()
        logger.info(f"PeerInit : {username}, {typ} (ticket={ticket})")

        self.finalize_peer_connection(
            # Create a dummy connection request for peers that are directly
            # connecting to us
            ConnectionRequest(
                ticket=ticket,
                typ=typ.decode('utf-8'),
                username=username,
                is_requested_by_us=False
            ),
            connection
        )

    @on_message(PeerPierceFirewall)
    def on_peer_pierce_firewall(self, message, connection: PeerConnection):
        ticket = message.parse()
        logger.debug(f"PeerPierceFirewall : (ticket={ticket})")

        try:
            with self._cache_lock:
                request = self.connection_requests[ticket]
        except KeyError:
            logger.warning(f"PeerPierceFirewall : unknown ticket (ticket={ticket})")
        else:
            self.finalize_peer_connection(request, connection)

    @on_message(GetPeerAddress)
    def on_get_peer_address(self, message):
        username, ip, port, _, obfuscated_port = message.parse()
        logger.debug(f"GetPeerAddress : username={username}, ip={ip}, ports={port}/{obfuscated_port}")

        if ip == '0.0.0.0':
            logger.warning(f"GetPeerAddress : no address returned for username : {username}")
            with self._cache_lock:
                for ticket, request in self.connection_requests.items():
                    if request.username == username:
                        self.fail_peer_connection_request(request)
            return

        with self._cache_lock:
            for ticket, request in self.connection_requests.items():
                if request.username == username:
                    if username.decode('utf-8') == 'Khyle':
                        request.ip = '192.168.0.158'
                    else:
                        request.ip = ip
                    request.port = port
                    self._connect_to_peer(ticket, request)

    @on_message(ConnectToPeer)
    def on_connect_to_peer(self, message):
        contents = message.parse()
        logger.info("ConnectToPeer : {!r}".format(contents))
        username, typ, ip, port, ticket, privileged, _, obfuscated_port = contents

        if username.decode('utf-8') == 'Khyle':
            ip = '192.168.0.158'

        connection_request = ConnectionRequest(
            ticket=ticket,
            username=username,
            typ=typ.decode('utf-8'),
            is_requested_by_us=False,
            ip=ip,
            port=port
        )
        with self._cache_lock:
            self.connection_requests[ticket] = connection_request

        self._connect_to_peer(ticket, connection_request)

    @on_message(CannotConnect)
    def on_cannot_connect(self, message):
        ticket, username = message.parse()
        logger.debug(f"CannotConnect : username={username} (ticket={ticket})")
        with self._cache_lock:
            try:
                request = self.connection_requests.pop(ticket)
            except KeyError:
                logger.warning(
                    f"CannotConnect : ticket {ticket} (username={username}) was not found in cache")
            else:
                logger.debug(f"CannotConnect : removed ticket {ticket} (username={username}) from cache")
                self.fail_peer_connection_request(request)

    def send_server_messages(self, *messages):
        for message in messages:
            self.server.queue_message(message)
