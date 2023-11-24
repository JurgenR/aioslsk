from __future__ import annotations
import asyncio
from async_timeout import timeout as atimeout
import enum
from functools import partial
import logging
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Union,
    Tuple,
    TypeVar,
    Type,
    TYPE_CHECKING
)

from ..constants import (
    DEFAULT_LISTENING_HOST,
    PEER_INDIRECT_CONNECT_TIMEOUT,
)
from .connection import (
    Connection,
    ConnectionState,
    CloseReason,
    DataConnection,
    PeerConnectionState,
    ListeningConnection,
    PeerConnection,
    PeerConnectionType,
    ServerConnection,
)
from ..exceptions import (
    ConnectionFailedError,
    ConnectionReadError,
    ListeningConnectionFailedError,
    MessageDeserializationError,
    NetworkError,
    PeerConnectionError,
)
from ..events import (
    build_message_map,
    on_message,
    ConnectionStateChangedEvent,
    EventBus,
    PeerInitializedEvent,
    MessageReceivedEvent,
    SessionInitializedEvent,
    ServerReconnectedEvent,
)
from ..protocol.messages import (
    CannotConnect,
    ConnectToPeer,
    GetPeerAddress,
    MessageDataclass,
    PeerInit,
    PeerPierceFirewall,
    SetListenPort,
)
from . import upnp
from .rate_limiter import RateLimiter
from ..utils import task_counter, ticket_generator

if TYPE_CHECKING:
    from ..settings import Settings


logger = logging.getLogger(__name__)


T = TypeVar('T', bound='MessageDataclass')
ListeningConnections = Tuple[Optional[ListeningConnection], Optional[ListeningConnection]]


class ListeningConnectionErrorMode(enum.Enum):
    """Error mode for listening connections. During initialization of the
    network the `connect_listening_connections` method will raise an error
    depending on the error mode
    """
    ALL = 'all'
    """Raise an exception if all listening connections failed to connect"""
    ANY = 'any'
    """Raise an exception if any listening connections failed to connect"""
    CLEAR = 'clear'
    """Raise an exception only if the non-obfuscated connection failed to
    connect
    """


class ExpectedResponse(asyncio.Future):
    """Future for an expected response message"""

    def __init__(
            self, connection_class: Type[Union[PeerConnection, ServerConnection]],
            message_class: Type[MessageDataclass],
            peer: Optional[str] = None, fields: Optional[Dict[str, Any]] = None,
            loop: Optional[asyncio.AbstractEventLoop] = None):
        super().__init__(loop=loop)
        self.connection_class: Type[Union[PeerConnection, ServerConnection]] = connection_class
        self.message_class: Type[MessageDataclass] = message_class
        self.peer: Optional[str] = peer
        self.fields: Dict[str, Any] = {} if fields is None else fields

    def matches(self, connection: Union[PeerConnection, ServerConnection], response: MessageDataclass) -> bool:
        if connection.__class__ != self.connection_class:
            return False

        if response.__class__ != self.message_class:
            return False

        if self.peer is not None and isinstance(connection, PeerConnection):
            if connection.username != self.peer:
                return False

        for fname, expected_value in self.fields.items():
            if callable(expected_value):
                try:
                    actual_value = getattr(response, fname)
                except AttributeError:
                    return False
                else:
                    return expected_value(actual_value)

            if getattr(response, fname, None) != expected_value:
                return False

        return True


class Network:

    def __init__(self, settings: Settings, event_bus: EventBus):
        self._settings: Settings = settings
        self._event_bus: EventBus = event_bus
        self._upnp = upnp.UPNP(self._settings)
        self._ticket_generator = ticket_generator()
        self._expected_response_futures: List[ExpectedResponse] = []
        self._expected_connection_futures: Dict[int, asyncio.Future] = {}

        # List of connections
        self.server_connection: ServerConnection = self.create_server_connection()
        self.listening_connections: ListeningConnections = self.create_listening_connections()
        self.peer_connections: List[PeerConnection] = []

        self._MESSAGE_MAP = build_message_map(self)

        # Rate limiters
        self._upload_rate_limiter: RateLimiter = RateLimiter.create_limiter(
            self._settings.network.limits.upload_speed_kbps)
        self._download_rate_limiter: RateLimiter = RateLimiter.create_limiter(
            self._settings.network.limits.download_speed_kbps)

        # Debugging
        self._ip_overrides: Dict[str, str] = self._settings.debug.ip_overrides

        # Operational
        self._log_connections_task: Optional[asyncio.Task] = None
        self._create_peer_connection_tasks: List[asyncio.Task] = []
        self._upnp_task: Optional[asyncio.Task] = None
        self._connection_watchdog_task: Optional[asyncio.Task] = None

        self.register_listeners()

    def register_listeners(self):
        self._event_bus.register(
            SessionInitializedEvent, self._on_session_initialized)

    def create_server_connection(self) -> ServerConnection:
        return ServerConnection(
            self._settings.network.server.hostname,
            self._settings.network.server.port,
            self
        )

    def create_listening_connections(self) -> ListeningConnections:
        return (
            ListeningConnection(
                DEFAULT_LISTENING_HOST,
                self._settings.network.listening.port,
                self,
                obfuscated=False
            ) if self._settings.network.listening.port else None,
            ListeningConnection(
                DEFAULT_LISTENING_HOST,
                self._settings.network.listening.obfuscated_port,
                self,
                obfuscated=True
            ) if self._settings.network.listening.obfuscated_port else None
        )

    async def initialize(self):
        """Initializes the server and listening connections"""
        logger.info("initializing network")

        await self.connect_listening_ports()
        await self.connect_server()

        log_connections = self._settings.debug.log_connection_count
        if log_connections and self._log_connections_task is None:
            self._log_connections_task = asyncio.create_task(
                self._log_connections_job(),
                name=f'log-connections-{task_counter()}'
            )

    async def connect_listening_ports(self):
        """This method will attempt to connect both listening ports (if
        configured) but will raise an exception depending on the settings
        `network.listening.error_mode` setting. All other listening connections
        will be disconnected before raising the error

        :raise ListeningConnectionFailedError: if an error occurred connecting
            the listening ports
        """
        error_mode = self._settings.network.listening.error_mode
        results = await asyncio.gather(
            *[
                listening_connection.connect()
                for listening_connection in self.listening_connections
                if listening_connection
            ],
            return_exceptions=True
        )

        if error_mode == ListeningConnectionErrorMode.ALL:
            if all(isinstance(res, ConnectionFailedError) for res in results):
                await self.disconnect_listening_ports()
                raise ListeningConnectionFailedError("failed to open any listening ports")

        elif error_mode == ListeningConnectionErrorMode.ANY:
            if any(isinstance(res, ConnectionFailedError) for res in results):
                await self.disconnect_listening_ports()
                raise ListeningConnectionFailedError("one or more listening ports failed to connect")

        elif error_mode == ListeningConnectionErrorMode.CLEAR:
            if not self.listening_connections[0] or self.listening_connections[0].state != ConnectionState.CONNECTED:
                await self.disconnect_listening_ports()
                raise ListeningConnectionFailedError("failed to connect non-obfuscated listening port")

    async def disconnect_listening_ports(self):
        """Disconnects all listening ports"""
        await asyncio.gather(
            *[
                listening_connection.disconnect(CloseReason.REQUESTED)
                for listening_connection in self.listening_connections
                if listening_connection
            ],
            return_exceptions=True
        )

    async def connect_server(self):
        await self.server_connection.connect()

    async def disconnect_server(self):
        await self.server_connection.disconnect(CloseReason.REQUESTED)

    async def disconnect(self):
        """Cancels all connection creation tasks and disconnects all current
        open connections
        """
        self._cancel_all_tasks()

        connections = [self.server_connection, ] + self.peer_connections
        connections += [conn for conn in self.listening_connections if conn]
        logger.info(f"waiting for network disconnect : {len(connections)} connections")
        await asyncio.gather(
            *[conn.disconnect(CloseReason.REQUESTED) for conn in connections],
            return_exceptions=True
        )
        logger.info("network disconnected")

    def get_listening_ports(self) -> Tuple[int, int]:
        """Gets the currently connected listening ports

        :return: `tuple` with 2 elements: the non-obfuscated- and obfuscated
            ports. If either is not connected or not configured `0` will be
            returned for this port
        """
        def get_port(conn: Optional[ListeningConnection]):
            if conn and conn.state == ConnectionState.CONNECTED:
                return conn.port
            return 0

        nonobf_port = get_port(self.listening_connections[0])
        obf_port = get_port(self.listening_connections[1])
        return nonobf_port, obf_port

    async def advertise_listening_ports(self):
        """Notifies the server of our current listening ports"""
        port, obfuscated_port = self.get_listening_ports()

        await self.send_server_messages(
            SetListenPort.Request(
                port,
                obfuscated_port_amount=1 if obfuscated_port else 0,
                obfuscated_port=obfuscated_port
            )
        )

    # Settings listeners
    def load_speed_limits(self):
        """(Re)loads the speed limits from the settings"""
        self.set_download_speed_limit(
            self._settings.network.limits.download_speed_kbps)
        self.set_upload_speed_limit(
            self._settings.network.limits.upload_speed_kbps)

    def set_upload_speed_limit(self, limit_kbps: int):
        """Modifies the upload speed limit. Passing 0 will set the upload speed
        to unlimited

        :param limit_kbps: the new upload limit
        """
        new_limiter = RateLimiter.create_limiter(limit_kbps)
        if self._upload_rate_limiter is not None:
            new_limiter.copy_tokens(self._upload_rate_limiter)
        self._upload_rate_limiter = new_limiter

        for conn in self.peer_connections:
            conn.upload_rate_limiter = self._upload_rate_limiter

    def set_download_speed_limit(self, limit_kbps: int):
        """Modifies the download speed limit. Passing 0 will set the download
        speed to unlimited

        :param limit_kbps: the new download limit
        """
        new_limiter = RateLimiter.create_limiter(limit_kbps)
        if self._download_rate_limiter is not None:
            new_limiter.copy_tokens(self._download_rate_limiter)
        self._download_rate_limiter = new_limiter

        for conn in self.peer_connections:
            conn.download_rate_limiter = self._download_rate_limiter

    async def _server_connection_watchdog_job(self):
        """Reconnects to the server if it is closed. This should be started as a
        task and should be cancelled upon request.
        """
        timeout = self._settings.network.server.reconnect.timeout
        logger.info("starting server connection watchdog")
        last_state = self.server_connection.state
        while True:
            await asyncio.sleep(0.5)

            if self.server_connection.state == ConnectionState.CLOSED:

                if not self._settings.credentials.are_configured():
                    if self.server_connection.state != last_state:
                        logger.warning(
                            "credentials are not correctly configured in the "
                            "settings, will not attempt to reconnect"
                        )
                    continue

                else:
                    logger.info(f"will attempt to reconnect to server in {timeout} seconds")
                    await asyncio.sleep(timeout)
                    try:
                        await self.connect_server()
                    except ConnectionFailedError:
                        logger.warning("failed to reconnect to server")
                    else:
                        await self._event_bus.emit(
                            ServerReconnectedEvent())

            last_state = self.server_connection.state

    async def start_server_connection_watchdog(self):
        """Starts the server connection watchdog if it is not already running"""
        if self._connection_watchdog_task is None:
            self._connection_watchdog_task = asyncio.create_task(
                self._server_connection_watchdog_job(),
                name=f'watchdog-task-{task_counter()}'
            )

    def stop_server_connection_watchdog(self):
        """Stops the server connection watchdog if it is running"""
        if self._connection_watchdog_task is not None:
            self._connection_watchdog_task.cancel()
            self._connection_watchdog_task = None

    async def _log_connections_job(self):
        while True:
            await asyncio.sleep(10)
            count = len(self.peer_connections)
            logger.info(
                f"currently {count} peer connections ({len(self._create_peer_connection_tasks)} tasks)")

    async def map_upnp_ports(self):
        """Maps the listening ports using UPNP on the gateway"""
        ports = [port for port in self.get_listening_ports() if port]
        ip_address = self.server_connection.get_connecting_ip()

        devices = await self._upnp.search_igd_devices(ip_address)
        for port in ports:
            for device in devices:
                await self._upnp.map_port(device, ip_address, port)

    def _map_upnp_ports_callback(self, task: asyncio.Task):
        try:
            task.result()
        except asyncio.CancelledError:
            logger.warning("upnp: port mapping task cancelled")
        except Exception:
            logger.exception("upnp: failed to map ports")
        finally:
            self._upnp_task = None

    def select_port(self, port, obfuscated_port) -> Tuple[int, bool]:
        """Selects the port used for making a connection. This attempts to take
        into account the `network.peer.obfuscate` parameter however falls back
        on using whatever port is available if necessary

        :param port: available non-obfuscated port
        :param obfuscated_port: available obfuscated port
        :return: a tuple with the port number and whether the port is obfuscated
        """
        prefer_obfuscated = self._settings.network.peer.obfuscate
        if port and obfuscated_port:
            if prefer_obfuscated:
                return obfuscated_port, True
            else:
                return port, False
        elif port:
            return port, False
        else:
            return obfuscated_port, True

    async def create_peer_connection(
            self, username: str, typ: str, ip: Optional[str] = None, port: Optional[int] = None,
            obfuscate: bool = False,
            initial_state: PeerConnectionState = PeerConnectionState.ESTABLISHED) -> PeerConnection:
        """Creates a new peer connection to the given `username` and connection
        type.

        Optionally this method takes `ip`, `port` and `obfuscate` parameters. If
        not given it will be requested to the server (GetPeerAddress) before
        attempting connection

        :param username: username of the peer
        :param typ: connection type ('P', 'D', 'F')
        :param ip: optional ip address of the peer
        :param port: optional port of the peer
        :param obfuscate: whether to obfuscate the connection. Should be used in
            combination with the `ip` and `port`
        :return: an object of `PeerConnection`
        :raise PeerConnectionError: when establishing a peer connection has
            failed
        """
        ticket = next(self._ticket_generator)

        # Request peer address if ip and port are not given
        if ip is None or port is None:
            ip, clear_port, obfuscated_port = await self._get_peer_address(username)

            port, obfuscate = self.select_port(clear_port, obfuscated_port)

        # Override IP address if requested
        ip = self._ip_overrides.get(username, ip)

        # Make direct connection
        try:
            connection = await self._make_direct_connection(
                ticket, username, typ, ip, port, obfuscate
            )

        except NetworkError as exc:
            logger.debug(
                f"direct connection ({typ}) to peer failed : {username} {ip}:{port} : {exc!r}")

            # Make indirect connection
            try:
                connection = await self._make_indirect_connection(
                    ticket, username, typ
                )

            except NetworkError as exc:
                logger.debug(
                    f"indirect connection to peer failed : {username} : {exc!r}")
                raise PeerConnectionError(
                    f"failed to connect to peer {username} ({typ=}, {ticket=})")

        connection.set_connection_state(initial_state)
        if typ == PeerConnectionType.FILE:
            connection.download_rate_limiter = self._download_rate_limiter
            connection.upload_rate_limiter = self._upload_rate_limiter

        await self._event_bus.emit(
            PeerInitializedEvent(connection, requested=True))
        return connection

    async def _get_peer_address(self, username: str) -> Tuple[str, int, int]:
        """Requests the peer address for the given `username` from the server.

        :raise PeerConnectionError: if no IP address or no valid ports were
            returned
        """
        await self.server_connection.send_message(GetPeerAddress.Request(username))
        _, response = await self.create_server_response_future(
            GetPeerAddress.Response,
            fields={
                'username': username
            }
        )

        if response.ip == '0.0.0.0':
            logger.warning(f"GetPeerAddress : no address returned for username : {username}")
            raise PeerConnectionError(f"no address for user : {username}")

        elif not response.port and not response.obfuscated_port:
            logger.warning(f"GetPeerAddress : no valid ports found for user : {username}")
            raise PeerConnectionError(f"no valid ports for user : {username}")

        return response.ip, response.port, response.obfuscated_port

    async def get_peer_connection(self, username: str, typ: str = PeerConnectionType.PEER) -> PeerConnection:
        """Gets a peer connection for the given `username`. It will first try to
        re-use an existing connection, otherwise it will create a new connection

        :param username: username of the peer to connect to
        :param typ: Type of connection to create or reuse
        :return: A `PeerConnection` instance
        """
        connections = self.get_active_peer_connections(username, typ)
        if connections:
            return connections[0]

        return await self.create_peer_connection(username, typ)

    def _remove_response_future(self, expected_response: ExpectedResponse):
        if expected_response in self._expected_response_futures:
            self._expected_response_futures.remove(expected_response)

    def _remove_connection_future(self, ticket: int, connection_future: asyncio.Future):
        logger.debug(f"removing expected incoming connection with {ticket=}")
        self._expected_connection_futures.pop(ticket)

    def create_server_response_future(
            self, message_class: Type[T], fields: Optional[Dict[str, Any]] = None) -> ExpectedResponse:
        """Creates a future for a server message to arrive, the message must
        match the `message_class` and fields defined in the keyword arguments.

        The future will be stored by the current class and will be removed once
        the future is complete or cancelled.

        :param message_class: The expected `MessageDataClass`
        :return: `ExpectedResponse` object
        """
        fields = fields or {}
        future = ExpectedResponse(
            ServerConnection,
            message_class=message_class,
            fields=fields
        )
        self._expected_response_futures.append(future)
        future.add_done_callback(self._remove_response_future)
        return future

    def register_response_future(self, expected_response: ExpectedResponse):
        """Registers an expected response future"""
        self._expected_response_futures.append(expected_response)
        expected_response.add_done_callback(self._remove_response_future)

    async def wait_for_server_message(
            self, message_class: Type[T], fields: Optional[Dict[str, Any]] = None, timeout: float = 10) -> T:
        """Waits for a message from the server

        :param message_class: Class of the expected server message
        :param fields: Optional matchers for the message fields
        :return: The `MessageData` object corresponding to the response
        """
        future = self.create_server_response_future(
            message_class=message_class,
            fields=fields
        )
        try:
            async with atimeout(timeout):
                _, response = await future
        except TimeoutError as exc:
            future.set_exception(exc)
            raise

        return response

    def create_peer_response_future(
            self, peer: str, message_class: Type[T], fields: Optional[Dict[str, Any]] = None) -> ExpectedResponse:
        """Creates a future for a peer message to arrive, the message must match
        the `message_class` and fields defined in the keyword arguments and
        must be coming from a connection by `peer`.

        The future will be stored by the current class and will be removed once
        the future is complete or cancelled.

        :param peer: name of the peer for which the message should be received
        :return: `ExpectedResponse` object
        """
        fields = fields or {}
        future = ExpectedResponse(
            PeerConnection,
            message_class=message_class,
            peer=peer,
            fields=fields
        )
        self._expected_response_futures.append(future)
        future.add_done_callback(self._remove_response_future)
        return future

    async def wait_for_peer_message(
            self, peer: str, message_class: Type[T], fields: Optional[Dict[str, Any]] = None, timeout: float = 60) -> T:
        future = self.create_peer_response_future(
            peer=peer,
            message_class=message_class,
            fields=fields
        )
        try:
            async with atimeout(timeout):
                _, response = await future
        except TimeoutError as exc:
            future.set_exception(exc)
            raise

        return response

    def get_peer_connections(self, username: str, typ: str) -> List[PeerConnection]:
        """Returns all connections for peer with given username and peer
        connection types.

        :param username: username of the peer
        :param typ: type of the connection (from `PeerConnectionType`)
        :return: list of connections for that matches the parameters
        """
        return [
            connection for connection in self.peer_connections
            if connection.username == username and connection.connection_type == typ
        ]

    def get_active_peer_connections(
            self, username: str, typ: str) -> List[PeerConnection]:
        """Return a list of currently active messaging connections for given
        peer connection type.

        :param username: username for which to get the active peer
        :param typ: peer connection type
        :return: list of PeerConnection instances
        """
        return list(
            filter(
                lambda conn: conn.state == ConnectionState.CONNECTED and conn.connection_state == PeerConnectionState.ESTABLISHED,  # noqa: E501
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
            self._handle_connect_to_peer(message),
            name=f'connect-to-peer-{task_counter()}'
        )
        task.add_done_callback(
            partial(self._handle_connect_to_peer_callback, message)
        )
        self._create_peer_connection_tasks.append(task)

    async def _make_direct_connection(
            self, ticket: int, username: str, typ: str, ip: str, port: int, obfuscate: bool) -> PeerConnection:
        """Attempts to make a direct connection to the peer and send a `PeerInit`
        message. This will be the first step in case we are the one initiating
        the connection
        """
        logger.debug(f"attempting to connect to peer : {username!r} {ip}:{port}")
        connection = PeerConnection(
            ip, port, self,
            connection_type=typ,
            username=username,
            obfuscated=obfuscate
        )
        self.peer_connections.append(connection)

        await connection.connect()
        await connection.send_message(
            PeerInit.Request(
                self._settings.credentials.username,
                typ,
                ticket
            )
        )
        return connection

    async def _make_indirect_connection(
            self, ticket: int, username: str, typ: str) -> PeerConnection:
        """Attempts to make an indirect connection by sending a `ConnectToPeer`
        message to the server. The method will wait for an incoming connection
        with a `PeerPierceFirewall` message containing the provided ticket or a
        `CannotConnect` message from the server.

        :return: `PeerConnection` object in case of success
        :raise PeerConnectionError: in case timeout was reached or we received a
            `CannotConnect` message from the server containing the `ticket`
        """
        # Wait for either a established connection with PeerPierceFirewall or a
        # CannotConnect from the server
        expected_connection_future: asyncio.Future = asyncio.Future()
        expected_connection_future.add_done_callback(
            partial(self._remove_connection_future, ticket)
        )
        self._expected_connection_futures[ticket] = expected_connection_future

        cannot_connect_future = self.create_server_response_future(
            CannotConnect.Response,
            fields={
                'ticket': ticket
            }
        )

        # Send the connect to peer message
        await self.server_connection.send_message(
            ConnectToPeer.Request(ticket, username, typ))

        futures = (expected_connection_future, cannot_connect_future)
        done, pending = await asyncio.wait(
            futures,
            timeout=PEER_INDIRECT_CONNECT_TIMEOUT,
            return_when=asyncio.FIRST_COMPLETED
        )

        # Whatever happens here, we can cancel all pending futures
        [fut.cancel() for fut in pending]

        # `done` will be empty in case of timeout
        if not done:
            raise PeerConnectionError(
                f"indirect connection timed out ({username=}, {ticket=})")

        completed_future = done.pop()

        if completed_future == cannot_connect_future:
            raise PeerConnectionError(
                f"indirect connection failed ({username=}, {ticket=})")

        connection = completed_future.result()

        connection.username = username
        connection.connection_type = typ

        return connection

    async def _handle_connect_to_peer(self, message: ConnectToPeer.Response):
        """Handles an indirect connection request received from the server.

        A task is created for this coroutine when a `ConnectToPeer` message is
        received.

        A `PeerInitializedEvent` will be emitted if the connection has been
        successfully established

        :param message: received `ConnectToPeer` message
        """
        ip = self._ip_overrides.get(message.username, message.ip)
        port, obfuscate = self.select_port(message.port, message.obfuscated_port)

        peer_connection = PeerConnection(
            ip, port, self,
            connection_type=message.typ,
            obfuscated=obfuscate,
            username=message.username
        )
        self.peer_connections.append(peer_connection)

        try:
            await peer_connection.connect()
            await peer_connection.send_message(
                PeerPierceFirewall.Request(message.ticket)
            )

        except NetworkError:
            await self.server_connection.queue_message(
                CannotConnect.Request(
                    ticket=message.ticket,
                    username=message.username
                )
            )
            raise PeerConnectionError("failed connect on user request")

        if message.typ == PeerConnectionType.FILE:
            peer_connection.set_connection_state(PeerConnectionState.AWAITING_TICKET)
            peer_connection.download_rate_limiter = self._download_rate_limiter
            peer_connection.upload_rate_limiter = self._upload_rate_limiter
        else:
            peer_connection.set_connection_state(PeerConnectionState.ESTABLISHED)

        await self._event_bus.emit(
            PeerInitializedEvent(peer_connection, requested=False))

    async def send_peer_messages(
            self, username: str, *messages: Union[bytes, MessageDataclass],
            raise_on_error: bool = True):
        """Sends a list of messages to the peer with given `username`. This uses
        `get_peer_connection` and will attempt to re-use a connection or create
        a new peer (P) connection

        :param username: Peer username to send the messages to
        :param messages: List of messages to send
        :param raise_on_error: When `True` an exception is raised when a message
            failed to send, if `False` a list of tuples with the result for each
            message will be returned
        :return: a list of tuples containing the sent messages and the result
            of the sent messages. If `None` is returned for a message it was
            successfully sent, otherwise the result will contain the exception.
            `None` if the `raise_on_error` is `True`
        """
        connection = await self.get_peer_connection(username)
        results = await asyncio.gather(
            *[connection.send_message(message) for message in messages],
            return_exceptions=not raise_on_error
        )
        if not raise_on_error:
            return list(zip(messages, results))

    def queue_server_messages(self, *messages: Union[bytes, MessageDataclass]) -> List[asyncio.Task]:
        """Queues server messages

        :param messages: list of messages to queue
        """
        return self.server_connection.queue_messages(*messages)

    async def send_server_messages(
            self, *messages: Union[bytes, MessageDataclass],
            raise_on_error: bool = True):
        """Sends a list of messages to the server

        :param messages: List of messages to send
        :param raise_on_error: When `True` an exception is raised when a message
            failed to send, if `False` a list of tuples with the result for each
            message will be returned
        :return: a list of tuples containing the sent messages and the result
            of the sent messages. If `None` is returned for a message it was
            successfully sent, otherwise the result will contain the exception.
            `None` if the `raise_on_error` is `True`
        """
        results = await asyncio.gather(
            *[self.server_connection.send_message(message) for message in messages],
            return_exceptions=not raise_on_error
        )
        if not raise_on_error:
            return list(zip(messages, results))

    # Connection state changes
    async def on_state_changed(
            self, state: ConnectionState, connection: Connection,
            close_reason: CloseReason = CloseReason.UNKNOWN):
        """Called when the state of a connection changes. This method calls 3
        private method based on the type of `connection` that was passed

        :param state: the new state the connection has received
        :param connection: the connection for which the state changed
        :param close_reason: in case ConnectionState.CLOSED is passed a reason
            will be given as well
        """
        if isinstance(connection, ServerConnection):
            await self._on_server_connection_state_changed(state, connection, close_reason=close_reason)

        elif isinstance(connection, PeerConnection):
            await self._on_peer_connection_state_changed(state, connection, close_reason=close_reason)

        await self._event_bus.emit(
            ConnectionStateChangedEvent(connection, state, close_reason)
        )

    async def _on_server_connection_state_changed(
            self, state: ConnectionState, connection: ServerConnection,
            close_reason: CloseReason = CloseReason.UNKNOWN):
        if state == ConnectionState.CONNECTED:
            # For registering with UPNP we need to know our own IP first, we can
            # get this from the server connection but we first need to be
            # fully connected to it before we can request a valid IP
            if self._settings.network.upnp.enabled:
                self._upnp_task = asyncio.create_task(
                    self.map_upnp_ports(),
                    name=f'enable-upnp-{task_counter()}'
                )
                self._upnp_task.add_done_callback(self._map_upnp_ports_callback)

            # Register server connection watchdog
            if self._settings.network.server.reconnect.auto:
                await self.start_server_connection_watchdog()

        elif state == ConnectionState.CLOSING:

            # When `disconnect` is called on the connection it will always first
            # go into the CLOSING state. The watchdog will only attempt to
            # reconnect if the server is in CLOSED state. So the code needs to
            # make a decision here whether we want to reconnect or not before it
            # goes into CLOSED state.
            # Cancel the watchdog only if we are closing up on request or the
            # server sends an EOF. The server sends an EOF as soon as you are
            # connected if your IP address is banned, this happens when you make
            # too many connections in a short period of time. Making any more
            # connections will only extend your ban period. Possibly the server
            # will also EOF when the login message is not sent after a certain
            # period of time
            # An EOF will also be sent in case you are kicked due to the same
            # login being used in another location
            if close_reason == CloseReason.REQUESTED:
                self.stop_server_connection_watchdog()

            elif close_reason == CloseReason.EOF:
                logger.warning(
                    "server closed connection, will not attempt to reconnect")
                self.stop_server_connection_watchdog()

    async def _on_peer_connection_state_changed(
            self, state: ConnectionState, connection: PeerConnection,
            close_reason: CloseReason = CloseReason.UNKNOWN):

        if state == ConnectionState.CLOSED:
            self.remove_peer_connection(connection)

    # Peer related
    async def on_peer_accepted(self, connection: PeerConnection):
        """Called when a connection has been accepted on one of the listening
        connections. This method will wait for the peer initialization message:
        either PeerInit or PeerPierceFirewall.

        In case of PeerInit the method will perform the initialization of the
        connection.

        In case of PeerPierceFirewall we look for an associated future object
        for the ticket provided in the message; there should be a task waiting
        for it to be completed (see `_make_indirect_connection`). Full
        initialization of the connection should be done in that method.

        In any other case we disconnect the connection.

        :param connection: the accepted `PeerConnection`
        """
        self.peer_connections.append(connection)

        try:
            message_data = await connection.receive_message()
            if message_data:
                peer_init_message = connection.decode_message_data(message_data)
            else:
                # EOF reached before receiving a message. Connection should've
                # been automatically closed
                return
        except ConnectionReadError:
            # Some read error. Connection should've been automatically closed
            return
        except MessageDeserializationError:
            # Couldn't deserialize the first message. Assume something is broken
            # and disconnect
            await connection.disconnect(CloseReason.REQUESTED)
            return

        if isinstance(peer_init_message, PeerInit.Request):
            connection.username = peer_init_message.username
            connection.connection_type = peer_init_message.typ
            # When the first message is PeerInit it's up to the other peer to send
            # us the transfer ticket in case it's a file connection
            if peer_init_message.typ == PeerConnectionType.FILE:
                connection.set_connection_state(PeerConnectionState.AWAITING_TICKET)
                connection.download_rate_limiter = self._download_rate_limiter
                connection.upload_rate_limiter = self._upload_rate_limiter
            else:
                connection.set_connection_state(PeerConnectionState.ESTABLISHED)

            await self._event_bus.emit(
                PeerInitializedEvent(connection, requested=False))

        elif isinstance(peer_init_message, PeerPierceFirewall.Request):
            ticket = peer_init_message.ticket
            try:
                connection_future = self._expected_connection_futures[ticket]
            except KeyError:
                logger.warning(
                    f"{connection.hostname}:{connection.port} : unknown pierce firewall ticket : {ticket}")
                await connection.disconnect(CloseReason.REQUESTED)
            else:
                connection_future.set_result(connection)

        else:
            logger.warning(
                f"{connection.hostname}:{connection.port} : unknown peer init message : {peer_init_message}")
            await connection.disconnect(CloseReason.REQUESTED)

    async def on_message_received(self, message: MessageDataclass, connection: DataConnection):
        """Method called by `connection` instances when a message is received

        :param message: Received message instance
        :param connection: Connection on which the message was received
        """
        # Call the message callbacks for this object
        if message.__class__ in self._MESSAGE_MAP:
            await self._MESSAGE_MAP[message.__class__](message, connection)

        # Emit on the message bus. Event handling has priority over completing
        # the future responses
        await self._event_bus.emit(MessageReceivedEvent(message, connection))

        # Complete expected response futures
        for expected_response in self._expected_response_futures:
            if expected_response.matches(connection, message):
                expected_response.set_result((connection, message, ))

    async def _on_session_initialized(self, event: SessionInitializedEvent):
        await self.advertise_listening_ports()

    # Task callbacks
    def _handle_connect_to_peer_callback(self, message: ConnectToPeer.Response, task: asyncio.Task):
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

    def _cancel_all_tasks(self):
        for task in self._create_peer_connection_tasks:
            task.cancel()

        if self._log_connections_task is not None:
            self._log_connections_task.cancel()
            self._log_connections_task = None

        if self._upnp_task is not None:
            self._upnp_task.cancel()
            self._upnp_task = None
