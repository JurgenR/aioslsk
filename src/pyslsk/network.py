from __future__ import annotations
from cachetools import TTLCache
from dataclasses import dataclass, field
import errno
from functools import partial
import logging
from selectors import DefaultSelector, EVENT_READ, EVENT_WRITE
import socket
import time
from threading import Lock
from typing import Callable, List, Union

from .connection import (
    Connection,
    ConnectionState,
    CloseReason,
    PeerConnectionState,
    ProtocolMessage,
    ListeningConnection,
    PeerConnection,
    PeerConnectionType,
    ServerConnection,
)
from .events import on_message
from .listeners import TransferListener
from .messages import (
    CannotConnect,
    ConnectToPeer,
    GetPeerAddress,
    PeerInit,
    PeerPierceFirewall,
)
from . import upnp
from .state import State
from .transfer import Transfer, TransferDirection


logger = logging.getLogger()


CONNECT_TIMEOUT = 5
CONNECT_TO_PEER_TIMEOUT: int = 30


@dataclass
class ConnectionRequest:
    ticket: int
    username: str
    is_requested_by_us: bool
    """Should be False if we received a ConnectToPeer message from another user"""
    ip: str = None
    port: int = None
    typ: str = None
    obfuscated: bool = False
    connection: PeerConnection = None
    transfer: Transfer = None
    messages: List[Union[bytes, ProtocolMessage]] = field(default_factory=lambda: [])
    """List of messages to be delivered when connection is established"""
    on_failure: Callable = None
    """Callback called when connection cannot be initialized"""


class Network:

    def __init__(self, state: State, settings):
        self._state = state
        self._settings = settings

        self._upnp = upnp.UPNP()

        self.server: ServerConnection = None
        self.listening_connections: List[ListeningConnection] = []

        self._connection_requests = TTLCache(maxsize=1000, ttl=5 * 60)

        self.peer_listener = None
        self.server_listeners = [self, ]
        self.transfer_listener: TransferListener = None

        # Selectors
        self.selector = DefaultSelector()
        self._last_log_time: float = 0

        self._server_connect_attempts: int = 0

        self._lock = Lock()

    def initialize(self):
        logger.info("initializing network")

        self.server = ServerConnection(
            hostname=self._settings['network']['server_hostname'],
            port=self._settings['network']['server_port'],
            listeners=self.server_listeners
        )
        self.server.connect()

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
        for listening_connection in self.listening_connections:
            listening_connection.connect()

    def get_connections(self):
        """Returns a list of currently registered L{Connection} objects"""
        return [
            selector_key.data
            for selector_key in self.selector.get_map().values()
        ]

    def _log_open_connections(self):
        """Utility for debugging how many connections are still open every 5
        seconds
        """
        current_time = int(time.monotonic())
        if current_time % 5 == 0 and current_time > self._last_log_time:
            self._last_log_time = current_time
            logger.debug(
                "Currently {} open connections".format(len(self.selector.get_map())))

    def loop(self):
        # On Windows an exception will be raised if select is called without any
        # registered sockets
        if len(self.selector.get_map()) == 0:
            time.sleep(0.1)
            return

        self._log_open_connections()

        current_time = time.monotonic()

        events = self.selector.select(timeout=0.05)
        for key, mask in events:
            work_socket = key.fileobj
            connection = key.data

            socket_err = work_socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if connection.state == ConnectionState.CONNECTING:

                # If this is the first time the connection is selected we should
                # still be in the CONNECTING state. Check if we are successfully
                # connected otherwise close the socket

                if socket_err != 0:
                    logger.warning(
                        "error connecting {}:{} : {} [{}] : cleaning up"
                        .format(connection.hostname, connection.port, socket_err, errno.errorcode[socket_err]))
                    connection.disconnect(reason=CloseReason.CONNECT_FAILED)
                else:
                    logger.debug(
                        "successfully connected {}:{}".format(connection.hostname, connection.port))
                    connection.set_state(ConnectionState.CONNECTED)
                continue
            else:
                if socket_err != 0:
                    logger.warning(
                        "error {}:{} : {} [{}] : cleaning up"
                        .format(connection.hostname, connection.port, socket_err, errno.errorcode[socket_err]))
                    connection.disconnect(reason=CloseReason.EOF)
                    continue

            if mask & EVENT_READ:
                # Listening connection
                if isinstance(connection, ListeningConnection):
                    connection.accept(work_socket)
                    continue

                # Data connection (peer/server)
                if not connection.read():
                    continue

            if mask & EVENT_WRITE:

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
                # Ignore connections that haven't had an interaction yet
                if not connection.last_interaction:
                    continue

                if connection.state == ConnectionState.CONNECTING:
                    if connection.last_interaction + CONNECT_TIMEOUT < current_time:
                        logger.warning(f"connection {connection.hostname}:{connection.port}: timeout reached during connecting")
                        connection.disconnect(reason=CloseReason.CONNECT_FAILED)
                        continue

                if connection.last_interaction + connection.timeout < current_time:
                    logger.warning(f"connection {connection.hostname}:{connection.port}: timeout reached")
                    connection.disconnect(reason=CloseReason.TIMEOUT)
                    continue

        # Set write event
        with self._lock:
            for key in list(self.selector.get_map().values()):
                connection = key.data
                # Connection needs to stay in write mode to detect whether we
                # have completed connecting or error occurred. If we were to
                # just keep that connection in READ then the select would only
                # trigger when there is data to read, which is not necesserily
                # what we want
                if connection.state == ConnectionState.CONNECTING and not isinstance(connection, ListeningConnection):
                    if not (key.events & EVENT_WRITE):
                        logger.info(f"enable write for {connection.hostname}:{connection.port}")
                        self.selector.modify(
                            key.fileobj,
                            EVENT_READ | EVENT_WRITE,
                            data=connection
                        )

                elif connection.has_data_to_write():
                    if not (key.events & EVENT_WRITE):
                        logger.info(f"enable write for {connection.hostname}:{connection.port}")
                        self.selector.modify(
                            key.fileobj,
                            EVENT_READ | EVENT_WRITE,
                            data=connection
                        )

                else:
                    if (key.events & EVENT_WRITE):
                        logger.info(f"disable write for {connection.hostname}:{connection.port}")
                        self.selector.modify(
                            key.fileobj,
                            EVENT_READ,
                            data=connection
                        )

    def exit(self):
        for data in self.selector.get_map().values():
            data.fileobj.close()

        self.selector.close()

    def enable_upnp(self):
        listening_port = self._settings['network']['listening_port']
        for port in [listening_port, listening_port + 1, ]:
            self._upnp.map_port(
                self.server.get_connecting_ip(),
                port,
                self._settings['network']['upnp_lease_duration']
            )

    def expire_caches(self):
        self._connection_requests.expire()

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
            self.selector.register(
                connection.fileobj, EVENT_READ | EVENT_WRITE, connection)

        elif state == ConnectionState.CONNECTED:
            self._server_connect_attempts = 0
            # For registering with UPNP we need to know our own IP first, we can
            # get this from the server connection but we first need to be
            # fully connected to it before we can request a valid IP
            if self._settings['network']['use_upnp']:
                self.enable_upnp()

        elif state == ConnectionState.CLOSED:
            self.selector.unregister(connection.fileobj)

            if close_reason != CloseReason.REQUESTED:
                if self._settings['network']['reconnect']['auto']:
                    logger.info("scheduling to re-attempting connecting in 5 seconds")
                    self._server_connect_attempts += 1
                    self._state.scheduler.add(5, self.server.connect, times=1)

    def _on_peer_connection_state_changed(self, state: ConnectionState, connection: PeerConnection, close_reason: CloseReason = None):
        if state == ConnectionState.CONNECTING:
            self.selector.register(
                connection.fileobj, EVENT_READ | EVENT_WRITE, connection)

        elif state == ConnectionState.CLOSED:
            self.selector.unregister(connection.fileobj)

            if close_reason == CloseReason.CONNECT_FAILED:
                for request in self._connection_requests.values():
                    if connection != request.connection:
                        continue

                    if request.is_requested_by_us:
                        # In case we want to connect to someone, don't give up just yet
                        # and send a ConnectToPeer
                        self.send_server_messages(
                            ConnectToPeer.create(
                                request.ticket,
                                request.username,
                                request.typ
                            )
                        )
                        self._state.scheduler.add(
                            CONNECT_TO_PEER_TIMEOUT,
                            callback=self._check_if_connecttopeer_request_handled,
                            args=[request.ticket, ],
                            times=1
                        )
                    else:
                        # In case we failed to connect to the other after they requested it, give up
                        self.send_server_messages(
                            CannotConnect.create(request.ticket, request.username)
                        )
                        self.fail_peer_connection_request(request)
                        break

    def _on_listening_connection_state_changed(self, state: ConnectionState, connection: ListeningConnection):
        if state == ConnectionState.CONNECTING:
            self.selector.register(
                connection.fileobj, EVENT_READ, connection)

        elif state == ConnectionState.CLOSED:
            self.selector.unregister(connection.fileobj)

    # Peer related
    def on_peer_accepted(self, connection: PeerConnection):
        connection.listeners = [self, self.peer_listener, ]
        self.selector.register(
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

        self._connection_requests[ticket] = connection_request

        if ip is None and port is None:
            # Request peer address if ip and port are not given
            self.send_server_messages(GetPeerAddress.create(username))
        else:
            self._connect_to_peer(connection_request)

        return connection_request

    def _connect_to_peer(self, request: ConnectionRequest) -> PeerConnection:
        """Attempts to establish a connection to a peer. This method will create
        the connection object and send a PeerInit or PeerPierceFirewall based
        on the L{request} passed to this method.

        The connection will automatically be attached to the network loop based
        on the state of the connection
        """
        logger.debug(f"attempting to connect to peer : {request!r}")
        connection = PeerConnection(
            hostname=request.ip,
            port=request.port,
            connection_type=request.typ,
            obfuscated=request.obfuscated,
            listeners=[self, self.peer_listener, ]
        )
        request.connection = connection

        if request.is_requested_by_us:
            message = PeerInit.create(
                self._settings['credentials']['username'],
                request.typ,
                request.ticket
            )
        else:
            message = PeerPierceFirewall.create(request.ticket)

        with self._lock:
            connection.queue_message(
                ProtocolMessage(
                    message=message,
                    on_success=partial(self.finalize_peer_connection, request, connection)
                )
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

        peer = self.peer_listener.create_peer(request.username, connection)

        # Non-peer connections always go to unobfuscated after initialization
        if request.typ != PeerConnectionType.PEER:
            logger.debug(f"setting obfuscated to false for connection : {connection!r}")
            connection.obfuscated = False

        # Check if this is a child connection
        if request.typ == PeerConnectionType.DISTRIBUTED:
            self.peer_listener.add_potential_child(peer, connection)

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
            try:
                self._connection_requests.pop(request.ticket)
            except KeyError:
                logger.warning(
                    f"finalized a peer connection for an unknown ticket (ticket={request.ticket})")

        for message in request.messages:
            with self._lock:
                connection.queue_message(message)

    def fail_peer_connection_request(self, request: ConnectionRequest):
        """Method called after peer connection could not be established. It is
        called after the following 3 situations:

        - GetPeerAddress returned nothing
        - We received a CannotConnect from the server
        - We sent a ConnectToPeer to the server but didn't get an incoming
          connection in a timely fashion
        """
        self._connection_requests.pop(request.ticket)
        if request.on_failure is not None:
            request.on_failure(request)

        for message in request.messages:
            if isinstance(message, ProtocolMessage):
                if message.on_failure is not None:
                    message.on_failure()

    def _check_if_connecttopeer_request_handled(self, ticket: int):
        try:
            request = self._connection_requests[ticket]
        except KeyError:
            pass  # Handled, connection request is no longer present
        else:
            logger.warning(f"ConnectToPeer request was not handled in a timely fashion (ticket={ticket})")
            self.fail_peer_connection_request(request)

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
                typ=typ,
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
            request = self._connection_requests[ticket]
        except KeyError:
            logger.warning(f"PeerPierceFirewall : unknown ticket (ticket={ticket})")
        else:
            self.finalize_peer_connection(request, connection)

    @on_message(GetPeerAddress)
    def on_get_peer_address(self, message, connection):
        username, ip, port, _, obfuscated_port = message.parse()
        logger.debug(f"GetPeerAddress : username={username}, ip={ip}, ports={port}/{obfuscated_port}")

        if ip == '0.0.0.0':
            logger.warning(f"GetPeerAddress : no address returned for username : {username}")
            for ticket, request in self._connection_requests.items():
                if request.username == username:
                    self.fail_peer_connection_request(request)
            return

        for ticket, request in self._connection_requests.items():
            if request.username == username:
                if username == 'Khyle':
                    request.ip = '192.168.0.152'
                else:
                    request.ip = ip
                request.port = port
                self._connect_to_peer(request)

    @on_message(ConnectToPeer)
    def on_connect_to_peer(self, message, connection):
        contents = message.parse()
        logger.info("ConnectToPeer : {!r}".format(contents))
        username, typ, ip, port, ticket, privileged, _, obfuscated_port = contents

        if username == 'Khyle':
            ip = '192.168.0.152'

        request = ConnectionRequest(
            ticket=ticket,
            username=username,
            typ=typ,
            is_requested_by_us=False,
            ip=ip,
            port=port
        )
        self._connection_requests[ticket] = request

        self._connect_to_peer(request)

    @on_message(CannotConnect)
    def on_cannot_connect(self, message, connection):
        ticket, username = message.parse()
        logger.debug(f"CannotConnect : username={username} (ticket={ticket})")
        try:
            request = self._connection_requests[ticket]
        except KeyError:
            logger.warning(
                f"CannotConnect : ticket {ticket} (username={username}) was not found in cache")
        else:
            self.fail_peer_connection_request(request)

    def send_peer_messages(self, username: str, *messages: List[Union[bytes, ProtocolMessage]]):
        with self._lock:
            if username in self.peer_listener.peers:
                peer = self.peer_listener.peers[username]
                active_connections = peer.get_active_connections(PeerConnectionType.PEER)
                if len(active_connections) > 0:
                    active_connections[0].queue_messages(*messages)
                    return

        connection_ticket = next(self._state.ticket_generator)
        self.init_peer_connection(
            connection_ticket,
            username,
            PeerConnectionType.PEER,
            messages=messages
        )

    def send_server_messages(self, *messages: List[Union[bytes, ProtocolMessage]]):
        with self._lock:
            for message in messages:
                self.server.queue_message(message)
