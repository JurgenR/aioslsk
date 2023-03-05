from __future__ import annotations
import asyncio
from functools import partial
import logging
from typing import Dict, List, Union


from ..constants import (
    DEFAULT_LISTENING_HOST,
    PEER_INDIRECT_CONNECT_TIMEOUT,
)
from .connection import (
    Connection,
    ConnectionState,
    CloseReason,
    PeerConnectionState,
    ListeningConnection,
    PeerConnection,
    PeerConnectionType,
    ServerConnection,
)
from ..exceptions import (
    ConnectionFailedError,
    ConnectionWriteError,
    PeerConnectionError,
)
from ..events import (
    build_message_map,
    on_message,
    ConnectionStateChangedEvent,
    InternalEventBus,
    PeerInitializedEvent,
    MessageReceivedEvent,
)
from ..protocol.messages import (
    CannotConnect,
    ConnectToPeer,
    GetPeerAddress,
    MessageDataclass,
    PeerInit,
    PeerPierceFirewall,
)
from . import upnp
from .rate_limiter import RateLimiter, UnlimitedRateLimiter
from ..state import State
from ..settings import Settings
from ..utils import task_counter, ticket_generator


logger = logging.getLogger(__name__)


class ExpectedResponse(asyncio.Future):
    """Future for an expected response message"""

    def __init__(self, connection_class, message_class, peer=None, fields=None, loop=None):
        super().__init__(loop=loop)
        self.connection_class = connection_class
        self.message_class = message_class
        self.peer: str = peer
        self.fields = {} if fields is None else fields

    def matches(self, connection, response):
        if connection.__class__ != self.connection_class:
            return False

        if response.__class__ != self.message_class:
            return False

        if self.peer is not None:
            if connection.username != self.peer:
                return False

        for fname, fvalue in self.fields.items():
            if getattr(response, fname, None) != fvalue:
                return False

        return True


class Network:

    def __init__(self, state: State, settings: Settings, internal_event_bus: InternalEventBus, stop_event: asyncio.Event):
        self._state = state
        self._settings: Settings = settings
        self._internal_event_bus: InternalEventBus = internal_event_bus
        self._upnp = upnp.UPNP(self._settings)
        self._ticket_generator = ticket_generator()
        self._stop_event = stop_event
        self._expected_response_futures: List[ExpectedResponse] = []

        # List of connections
        self.server: ServerConnection = ServerConnection(
            self._settings.get('network.server_hostname'),
            self._settings.get('network.server_port'),
            self
        )
        self.listening_connections: List[ListeningConnection] = [
            ListeningConnection(
                DEFAULT_LISTENING_HOST,
                self._settings.get('network.listening_port'),
                self
            ),
            ListeningConnection(
                DEFAULT_LISTENING_HOST,
                self._settings.get('network.listening_port') + 1,
                self,
                obfuscated=True
            )
        ]
        self.peer_connections: List[PeerConnection] = []

        self.MESSAGE_MAP = build_message_map(self)

        # Rate limiters
        self.upload_rate_limiter: RateLimiter = RateLimiter.create_limiter(
            self._settings.get('sharing.limits.upload_speed_kbps'))
        self.download_rate_limiter: RateLimiter = RateLimiter.create_limiter(
            self._settings.get('sharing.limits.download_speed_kbps'))

        self._settings.add_listener(
            'sharing.limits.upload_speed_kbps', self._on_upload_speed_changed)
        self._settings.add_listener(
            'sharing.limits.download_speed_kbps', self._on_download_speed_changed)

        # Debugging
        self._user_ip_overrides: Dict[str, str] = self._settings.get('debug.user_ip_overrides')

        # Operational
        self._log_connections_task: asyncio.Task = None
        self._create_peer_connection_tasks: List[asyncio.Task] = []
        self._upnp_task: asyncio.Task = None

    async def initialize(self):
        """Initializes the server and listening connections"""
        logger.info("initializing network")

        tasks = [asyncio.create_task(self._connect_server())]
        for listening_connection in self.listening_connections:
            tasks.append(asyncio.create_task(listening_connection.connect()))

        await asyncio.gather(*tasks, return_exceptions=True)

        if self._log_connections_task is None:
            self._log_connections_task = asyncio.create_task(
                self._log_connections_job(),
                name=f'log-connections-{task_counter()}'
            )

    async def _connect_server(self):
        await self.server.connect()

    async def disconnect(self):
        """Disconnects all current connections"""
        for task in self._create_peer_connection_tasks:
            task.cancel()

        if self._log_connections_task is not None:
            self._log_connections_task.cancel()
            self._log_connections_task = None

        if self._upnp_task is not None:
            self._upnp_task.cancel()
            self._upnp_task = None

        connections = [self.server, ] + self.listening_connections + self.peer_connections
        logger.info(f"waiting for network disconnect : {len(connections)} connections")
        results = await asyncio.gather(
            *[conn.disconnect(CloseReason.REQUESTED) for conn in connections],
            return_exceptions=True
        )
        logger.debug(f"disconnect results : {results!r}")

    async def _log_connections_job(self):
        while True:
            await asyncio.sleep(1)
            count = len(self.peer_connections)
            logger.info(f"currently {count} peer connections")
            logger.info(f"currently {len(self._create_peer_connection_tasks)} connect to peer tasks")

    async def map_upnp_ports(self):
        """Maps the listening ports using UPNP on the gateway"""
        listen_port = self._settings.get('network.listening_port')
        ports = [listen_port, listen_port + 1]
        ip_address = self.server.get_connecting_ip()

        devices = await self._upnp.search_igd_devices(ip_address)
        for port in ports:
            for device in devices:
                await self._upnp.map_port(device, ip_address, port)

    def _map_upnp_ports_callback(self, future: asyncio.Future):
        self._upnp_task = None

    async def create_peer_connection(
                self, username: str, typ: str, ip: str = None, port: int = None,
                initial_state: PeerConnectionState = PeerConnectionState.ESTABLISHED
            ) -> PeerConnection:
        """Creates a new peer connection to the given `username` and connection
        type.

        Optionally this method takes an `ip` and `port`. If not given it will
        be requested to the server.

        :param username: username of the peer
        :param typ: connection type ('P', 'D', 'F')
        :param ip: optional ip address of the peer
        :param port: optional port of the peer
        :return: an object of `PeerConnection`
        :raise PeerConnectionError:
        """
        ticket = next(self._ticket_generator)

        # Request peer address if ip and port are not given
        if ip is None or port is None:
            # Request peer address if ip and port are not given
            await self.server.send_message(GetPeerAddress.Request(username))
            connection, response = await self.wait_for_server_message(
                GetPeerAddress.Response, username=username)

            if response.ip == '0.0.0.0':
                logger.warning(f"GetPeerAddress : no address returned for username : {response.username}")
                raise PeerConnectionError(f"no address for username : {response.username}")
            else:
                ip = response.ip
                port = response.port

        # Override IP address if requested
        ip = self._user_ip_overrides.get(username, ip)

        # Make a direct connection to the peer
        logger.debug(f"attempting to connect to peer : {username!r} {ip}:{port}")
        connection = PeerConnection(
            ip, port, self,
            connection_type=typ,
            username=username,
            obfuscated=False
        )
        self.peer_connections.append(connection)

        try:
            await connection.connect()
            await connection.send_message(
                PeerInit.Request(
                    self._settings.get('credentials.username'),
                    typ,
                    ticket
                )
            )

            connection.set_connection_state(initial_state)

            await self._internal_event_bus.emit(
                PeerInitializedEvent(connection, requested=True))
            return connection

        except ConnectionFailedError as exc:
            logger.debug(
                f"direct connection to peer failed : {username} {ip}:{port} : {exc!r}")

        except ConnectionWriteError as exc:
            logger.debug(
                f"direct connection succeeded but failed to deliver init message : {username} {ip}:{port} : {exc!r}")

        # Make indirect connection
        connection = await self._make_indirect_connection(
            ticket, username, typ, initial_state
        )

        return connection

    async def get_peer_connection(self, username: str, typ: PeerConnectionType = PeerConnectionType.PEER) -> PeerConnection:
        """Gets a peer connection for the given `username`. It will first try to
        re-use an existing connection, otherwise it will create a new connection
        """
        connections = self.get_active_peer_connections(username, typ)
        if connections:
            return connections[0]

        return await self.create_peer_connection(
            username,
            PeerConnectionType.PEER
        )

    def _remove_response_future(self, expected_response):
        try:
            self._expected_response_futures.remove(expected_response)
        except ValueError:
            pass

    def wait_for_server_message(self, message_class, **kwargs) -> asyncio.Future:
        """Waits for a server message to arrive, the message must match the
        `message_class` and fields defined in the keyword arguments.

        :return: `asyncio.Future` object
        """
        future = ExpectedResponse(
            ServerConnection,
            message_class=message_class,
            fields=kwargs
        )
        self._expected_response_futures.append(future)
        future.add_done_callback(self._remove_response_future)
        return future

    def wait_for_peer_message(self, peer: str, message_class, **kwargs) -> asyncio.Future:
        """Waits for a peer message to arrive, the message must match the
        `message_class` and fields defined in the keyword arguments and must be
        coming from a connection by `peer`.

        :param peer: name of the peer for which the message should be received
        :return: `asyncio.Future` object
        """
        future = ExpectedResponse(
            PeerConnection,
            message_class=message_class,
            peer=peer,
            fields=kwargs
        )
        self._expected_response_futures.append(future)
        future.add_done_callback(self._remove_response_future)
        return future

    def get_peer_connections(self, username: str, typ: str) -> List[PeerConnection]:
        """Returns all connections for peer with given username and peer
        connection types.
        """
        return [
            connection for connection in self.peer_connections
            if connection.username == username and connection.connection_type == typ
        ]

    def get_active_peer_connections(
            self, username: str, typ: PeerConnectionType) -> List[PeerConnection]:
        """Return a list of currently active messaging connections for given
        peer connection type.

        :param username: username for which to get the active peer
        :param typ: peer connection type
        :return: list of PeerConnection instances
        """
        return list(
            filter(
                lambda conn: conn.state == ConnectionState.CONNECTED and conn.connection_state == PeerConnectionState.ESTABLISHED,
                self.get_peer_connections(username, typ)
            )
        )

    def remove_peer_connection(self, connection: PeerConnection):
        if connection in self.peer_connections:
            self.peer_connections.remove(connection)

    # Server related

    @on_message(ConnectToPeer.Response)
    async def _on_connect_to_peer(self, message: ConnectToPeer.Response, connection: ServerConnection):
        """Handles a ConnectToPeer request coming from another peer"""
        task = asyncio.create_task(
            self._handle_indirect_connection(message),
            name=f'connect-to-peer-{task_counter()}'
        )
        task.add_done_callback(
            partial(self._handle_indirect_connection_callback, message))
        self._create_peer_connection_tasks.append(task)

    async def _make_indirect_connection(
            self, ticket: int, username: str, typ: str, initial_state: PeerConnectionState) -> PeerConnection:
        """Attempts to make an indirect connection by sending a `ConnectToPeer`
        message to the server and waiting for an incoming connection and
        `PeerPierceFirewall` message.

        A `PeerInitializedEvent` will be emitted in case of success

        :param initial_state: the initial state of the connection after the
            connection is established and the init message received. This is
            going to be one of two values: PeerConnectionState.ESTABLISHED or
            PeerConnectionState.AWAITING_OFFSET
        :raise PeerConnectionError: in case timeout was reached or we received a
            `CannotConnect` message from the server containing the `ticket`
        """
        await self.server.send_message(ConnectToPeer.Request(ticket, username, typ))

        # Wait for either a PierceFirewall from the peer or a CannotConnect from
        # the server
        futures = (
            self.wait_for_peer_message(None, PeerPierceFirewall.Request, ticket=ticket),
            self.wait_for_server_message(CannotConnect.Response, ticket=ticket)
        )
        done, pending = await asyncio.wait(
            futures,
            timeout=PEER_INDIRECT_CONNECT_TIMEOUT,
            return_when=asyncio.FIRST_COMPLETED
        )

        # Whatever happens here, we can remove all the pending futures
        [future.cancel() for future in pending]
        [self._remove_response_future(future) for future in futures]

        # `done` will be empty in case of timeout
        if not done:
            raise PeerConnectionError(
                f"indirect connection timed out (username={username}, ticket={ticket})")

        connection, response = done.pop().result()

        if response.__class__ == CannotConnect.Response:
            logger.debug(f"received cannot connect (ticket={ticket})")
            raise PeerConnectionError(
                f"indirect connection failed (username={username}, ticket={ticket})")

        connection.username = username
        connection.connection_type = typ
        connection.set_connection_state(initial_state)

        await self._internal_event_bus.emit(
            PeerInitializedEvent(connection, requested=True))

    async def _handle_indirect_connection(self, message: ConnectToPeer.Response):
        """Handles an indirect connection request received from the server"""
        obfuscate = self._settings.get('network.peer.obfuscate') and bool(message.obfuscated_port)

        ip = self._user_ip_overrides.get(message.username, message.ip)
        port = message.obfuscated_port if obfuscate else message.port

        peer_connection = PeerConnection(
            ip,
            port,
            self,
            connection_type=message.typ,
            obfuscated=obfuscate,
            username=message.username
        )
        self.peer_connections.append(peer_connection)

        try:
            await peer_connection.connect()

        except Exception as exc:
            logger.warning(f"couldn't connect to peer : {exc!r}")
            await self.server.queue_message(CannotConnect.Request(message.ticket))
            return

        await peer_connection.send_message(
            PeerPierceFirewall.Request(message.ticket))

        if message.typ == PeerConnectionType.FILE:
            peer_connection.set_connection_state(PeerConnectionState.AWAITING_TICKET)
        else:
            peer_connection.set_connection_state(PeerConnectionState.ESTABLISHED)

        await self._internal_event_bus.emit(
            PeerInitializedEvent(peer_connection, requested=False))

    @on_message(PeerInit.Request)
    async def _on_peer_init(self, message: PeerInit.Request, connection: PeerConnection):
        connection.username = message.username
        connection.connection_type = message.typ
        # When the first message is PeerInit it's up to the other peer to send
        # us the transfer ticket in case it's a file connection
        if message.typ == PeerConnectionType.FILE:
            connection.set_connection_state(PeerConnectionState.AWAITING_TICKET)
        else:
            connection.set_connection_state(PeerConnectionState.ESTABLISHED)

        await self._internal_event_bus.emit(
            PeerInitializedEvent(connection, requested=False))

    async def queue_peer_messages(self, username: str, *messages: List[Union[bytes, MessageDataclass]]) -> List[asyncio.Task]:
        """Sends messages to the specified peer

        :param username: user to send the messages to
        :param messages: list of messages to send
        """
        connection = await self.get_peer_connection(username)
        return await connection.queue_messages(*messages)

    async def send_peer_messages(self, username: str, *messages: List[Union[bytes, MessageDataclass]]):
        queue_tasks = await self.queue_peer_messages(username, *messages)
        await asyncio.gather(*queue_tasks, return_exceptions=True)

    async def queue_server_messages(self, *messages: List[Union[bytes, MessageDataclass]]) -> List[asyncio.Task]:
        """Queues server messages

        :param messages: list of messages to queue
        """
        return await self.server.queue_messages(*messages)

    async def send_server_messages(self, *messages: List[Union[bytes, MessageDataclass]]):
        queue_tasks = await self.queue_server_messages(*messages)
        await asyncio.gather(*queue_tasks, return_exceptions=True)

    # Methods called by connections

    # Connection state changes
    async def on_state_changed(self, state: ConnectionState, connection: Connection, close_reason: CloseReason = None):
        """Called when the state of a connection changes. This method calls 3
        private method based on the type of L{connection} that was passed

        :param state: the new state the connection has received
        :param connection: the connection for which the state changed
        :param close_reason: in case ConnectionState.CLOSED is passed a reason
            will be given as well, this is useful when we need to send a
            CannotConnect to the server after a ConnectToPeer was sent and we
            failed to connect to that peer
        """
        if isinstance(connection, ServerConnection):
            await self._on_server_connection_state_changed(state, connection, close_reason=close_reason)

        elif isinstance(connection, PeerConnection):
            await self._on_peer_connection_state_changed(state, connection, close_reason=close_reason)

        elif isinstance(connection, ListeningConnection):
            self._on_listening_connection_state_changed(state, connection)

        await self._internal_event_bus.emit(
            ConnectionStateChangedEvent(connection, state, close_reason)
        )

    async def _on_server_connection_state_changed(self, state: ConnectionState, connection: ServerConnection, close_reason: CloseReason = None):
        if state == ConnectionState.CONNECTED:
            # For registering with UPNP we need to know our own IP first, we can
            # get this from the server connection but we first need to be
            # fully connected to it before we can request a valid IP
            if self._settings.get('network.upnp.enabled'):
                self._upnp_task = asyncio.create_task(
                    self.map_upnp_ports(),
                    name=f'enable-upnp-{task_counter()}'
                )
                self._upnp_task.add_done_callback(self._map_upnp_ports_callback)

        elif state == ConnectionState.CLOSED:

            if close_reason != CloseReason.REQUESTED:
                if self._settings.get('network.reconnect.auto'):

                    while not self.server.state == ConnectionState.CONNECTED:
                        logger.info("attempting to reconnect to server in 5 seconds")
                        try:
                            await self.server.connect()
                        except ConnectionFailedError:
                            pass

    async def _on_peer_connection_state_changed(self, state: ConnectionState, connection: PeerConnection, close_reason: CloseReason = None):
        if state == ConnectionState.CLOSED:
            self.remove_peer_connection(connection)

    def _on_listening_connection_state_changed(self, state: ConnectionState, connection: ListeningConnection):
        pass

    # Peer related
    def on_peer_accepted(self, connection: PeerConnection):
        self.peer_connections.append(connection)

    async def on_message_received(self, message, connection: Connection):
        # Complete expected response futures
        for expected_response in self._expected_response_futures:
            if expected_response.matches(connection, message):
                expected_response.set_result((connection, message, ))

        # Call the message callbacks for this object
        if message.__class__ in self.MESSAGE_MAP:
            await self.MESSAGE_MAP[message.__class__](message, connection)

        # Emit on the internal message bus
        await self._internal_event_bus.emit(MessageReceivedEvent(message, connection))

    # Settings listeners

    def _on_upload_speed_changed(self, limit_kbps: int):
        """Called when upload speed is changed in the settings

        :param limit_kbps: the new upload limit
        """
        new_limiter = RateLimiter.create_limiter(limit_kbps)
        if isinstance(new_limiter, UnlimitedRateLimiter):
            self.upload_rate_limiter = new_limiter
        else:
            # Transfer the tokens we had to the new limiter
            new_limiter.add_tokens(self.upload_rate_limiter.bucket)
            new_limiter.last_refill = self.upload_rate_limiter.last_refill
            self.upload_rate_limiter = new_limiter

    def _on_download_speed_changed(self, limit_kbps: int):
        """Called when download speed is changed in the settings

        :param limit_kbps: the new download limit
        """
        new_limiter = RateLimiter.create_limiter(limit_kbps)
        if isinstance(new_limiter, UnlimitedRateLimiter):
            self.download_rate_limiter = new_limiter
        else:
            # Transfer the tokens we had to the new limiter
            new_limiter.add_tokens(self.download_rate_limiter.bucket)
            new_limiter.last_refill = self.download_rate_limiter.last_refill
            self.download_rate_limiter = new_limiter

    # Task callbacks
    def _handle_indirect_connection_callback(self, message: ConnectToPeer.Response, task: asyncio.Task):
        try:
            task.result()
        except asyncio.CancelledError:
            logger.debug(f"cancelled ConnectToPeer request : {message}")
        except Exception as exc:
            logger.warning(f"failed to fulfill ConnectToPeer request : {exc!r} : {message}")
        else:
            logger.info(f"successfully fulfilled ConnectToPeer request : {message}")
        finally:
            self._create_peer_connection_tasks.remove(task)
