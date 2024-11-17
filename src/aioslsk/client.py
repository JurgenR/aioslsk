from __future__ import annotations
import asyncio
from async_timeout import timeout as atimeout
import logging
from typing import Optional

from .base_manager import BaseManager
from .commands import BaseCommand, RC, RT
from .constants import DEFAULT_COMMAND_TIMEOUT
from .distributed import DistributedNetwork
from .events import (
    build_message_map,
    ConnectionStateChangedEvent,
    EventBus,
    ServerReconnectedEvent,
    SessionDestroyedEvent,
    SessionInitializedEvent,
)
from .exceptions import AioSlskException, AuthenticationError, InvalidSessionError
from .interest.manager import InterestManager
from .shares.cache import SharesCache, SharesNullCache
from .shares.manager import ExecutorFactory, SharesManager
from .network.connection import ConnectionState, ServerConnection
from .network.network import Network
from .peer import PeerManager
from .protocol.messages import Login
from .protocol.primitives import calc_md5
from .room.manager import RoomManager
from .search.manager import SearchManager
from .server import ServerManager
from .session import Session
from .settings import Settings
from .transfer.cache import TransferCache, TransferNullCache
from .transfer.manager import TransferManager
from .user.manager import UserManager
from .utils import ticket_generator


CLIENT_VERSION = 157
MINOR_VERSION = 100


logger = logging.getLogger(__name__)


class SoulSeekClient:
    """SoulSeek client class. This class is a facade for a collection of
    different :class:`aioslsk.base_manager.BaseManager` classes and orchestrates
    the lifecycle of those classes
    """

    def __init__(
            self, settings: Settings,
            shares_cache: Optional[SharesCache] = None, transfer_cache: Optional[TransferCache] = None,
            executor_factory: Optional[ExecutorFactory] = None,
            event_bus: Optional[EventBus] = None):

        self.settings: Settings = settings

        self._stop_event: Optional[asyncio.Event] = None

        self.ticket_generator = ticket_generator()
        self.events: EventBus = event_bus or EventBus()
        self.session: Optional[Session] = None

        self.network: Network = self.create_network()
        self.distributed_network: DistributedNetwork = self.create_distributed_network()

        self.users: UserManager = self.create_user_manager()
        self.rooms: RoomManager = self.create_room_manager()
        self.interests: InterestManager = self.create_interest_manager()

        self.shares: SharesManager = self.create_shares_manager(
            shares_cache or SharesNullCache(),
            executor_factory=executor_factory
        )
        self.transfers: TransferManager = self.create_transfer_manager(
            transfer_cache or TransferNullCache()
        )
        self.peers: PeerManager = self.create_peer_manager()
        self.searches: SearchManager = self.create_search_manager()
        self.server_manager: ServerManager = self.create_server_manager()

        self.services: list[BaseManager] = [
            self.users,
            self.rooms,
            self.interests,
            self.shares,
            self.transfers,
            self.peers,
            self.searches,
            self.server_manager
        ]

        self._MESSAGE_MAP = build_message_map(self)
        self.register_listeners()

    def get_event_loop(self):
        return asyncio.get_running_loop()

    def register_listeners(self):
        self.events.register(
            ConnectionStateChangedEvent, self._on_connection_state_changed)
        self.events.register(
            ServerReconnectedEvent, self._on_server_reconnected)

    async def start(self, connect: bool = True):
        """Performs a start up of the client consisting of:

        * Calls `load_data` on all defined services
        * Calls `start` on all defined services
        * Optionally: Starts a scan of the defined shares
        * Optionally: Connecting to the server and opening listening ports

        :param connect: Whether to connect the network after start up
        """
        self.get_event_loop().set_exception_handler(self._exception_handler)

        # Allows creating client before actually calling asyncio.run(client.start())
        # see https://stackoverflow.com/questions/55918048/asyncio-semaphore-runtimeerror-task-got-future-attached-to-a-different-loop  # noqa: E501
        self._stop_event = asyncio.Event()

        await asyncio.gather(*[svc.load_data() for svc in self.services])
        await asyncio.gather(*[svc.start() for svc in self.services])

        if self.settings.shares.scan_on_start:
            asyncio.create_task(self.shares.scan())

        if connect:
            await self.connect()

    async def run_until_stopped(self):
        if not self._stop_event:  # pragma: no cover
            raise AioSlskException("client was never started")

        await self._stop_event.wait()

    async def stop(self):
        """Stops the client, this method consists of:

        * Disconnecting the network and waiting for all connections to close
        * Cancel all pending tasks and waiting for them to complete
        * Write the transfer and shares caches
        """
        logger.info("signaling client to exit")
        if self._stop_event:
            self._stop_event.set()

        await self.network.disconnect()

        cancelled_tasks = []
        for service in self.services:
            cancelled_tasks.extend(await service.stop())

        await asyncio.gather(*cancelled_tasks, return_exceptions=True)
        await asyncio.gather(*[svc.store_data() for svc in self.services])

    async def connect(self):
        """Initializes the network by connecting to the server and opening the
        configured listening ports
        """
        await self.network.initialize()

    async def login(
            self, client_version: int = CLIENT_VERSION, minor_version: int = MINOR_VERSION):
        """Performs a logon to the server with the `credentials` defined in the
        `settings`

        :raise AuthenticationError: When authentication failed
        """
        username = self.settings.credentials.username
        password = self.settings.credentials.password

        # Send the login request and wait for the response
        await self.network.send_server_messages(
            Login.Request(
                username=username,
                password=password,
                client_version=client_version,
                md5hash=calc_md5(username + password),
                minor_version=minor_version
            )
        )

        response = await self.network.server_connection.receive_message_object()
        if not isinstance(response, Login.Response):
            raise AioSlskException(
                f"expected login response from server but got : {response}")

        if not response.success:
            raise AuthenticationError(
                response.reason if response.reason else '',
                f"authentication failed for user : {username}"
            )

        # Notify all listeners that the session has been initialized
        self.session = Session(
            user=self.users.get_user_object(username),
            ip_address=response.ip if response.ip is not None else '',
            greeting=response.greeting if response.greeting is not None else '',
            client_version=client_version,
            minor_version=minor_version
        )
        await self.events.emit(
            SessionInitializedEvent(
                session=self.session,
                raw_message=response
            )
        )

        # Finally start up the reader loop for the server
        self.network.server_connection.start_reader_task()

    def _exception_handler(self, loop, context):
        message = f"unhandled exception on loop {loop!r} : context : {context!r}"
        logger.exception(message, exc_info=context.get('exception', None))

    async def __aenter__(self) -> SoulSeekClient:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def __call__(
            self, command: BaseCommand[RC, Optional[RT]], response: bool = False,
            timeout: float = DEFAULT_COMMAND_TIMEOUT) -> Optional[RT]:

        return await self.execute(command, response=response, timeout=timeout)

    async def execute(
            self, command: BaseCommand[RC, Optional[RT]], response: bool = False,
            timeout: float = DEFAULT_COMMAND_TIMEOUT) -> Optional[RT]:
        """Execute a :class:`BaseCommand`, see the :mod:`aioslsk.commands`
        module for a list of possible commands.

        Waiting for a response is optional; the protocol does not always send
        error messages in case of failure. In these cases this method will
        timeout if the command is configured to wait for a response.

        Example waiting for response:

        ..code-block:: python

            from aioslsk.commands import GetUserStatusCommand

            status = await client.execute(
                GetUserStatusCommand('someuser'), reponse=True)

        Example without response:

        ..code-block:: python

            from aioslsk.commands import JoinRoomCommand

            await client.execute(JoinRoomCommand('cool room'))

        :param command: Command class to execute
        :param response: Whether to wait for the response or simply send
            (default: ``False``)
        :param timeout: Timeout waiting for response (default: ``10``)
        :raise InvalidSessionError: When no logon has been performed
        :return: Optional response depending on how the command was configured
        """
        if self.session is None:
            raise InvalidSessionError("client is not logged in")

        response_future = command.build_expected_response(self)
        if response and response_future:
            self.network.register_response_future(response_future)

        try:
            await command.send(self)
        except Exception:
            if response and response_future:
                response_future.cancel()
            raise

        if response and response_future:
            async with atimeout(timeout):
                _, response_obj = await response_future
            return command.handle_response(self, response_obj)
        return None

    # Creation methods

    def create_network(self) -> Network:
        return Network(self.settings, self.events)

    def create_user_manager(self) -> UserManager:
        return UserManager(
            self.settings,
            self.events,
            self.network
        )

    def create_room_manager(self) -> RoomManager:
        return RoomManager(
            self.settings,
            self.events,
            self.users,
            self.network
        )

    def create_interest_manager(self) -> InterestManager:
        return InterestManager(
            self.settings,
            self.events,
            self.users,
            self.network
        )

    def create_shares_manager(
            self, cache: SharesCache,
            executor_factory: Optional[ExecutorFactory] = None) -> SharesManager:

        return SharesManager(
            self.settings,
            self.events,
            self.network,
            cache=cache,
            executor_factory=executor_factory
        )

    def create_transfer_manager(self, cache: TransferCache) -> TransferManager:
        return TransferManager(
            self.settings,
            self.events,
            self.users,
            self.shares,
            self.network,
            cache=cache
        )

    def create_search_manager(self) -> SearchManager:
        return SearchManager(
            self.settings,
            self.events,
            self.shares,
            self.transfers,
            self.network
        )

    def create_server_manager(self) -> ServerManager:
        return ServerManager(
            self.settings,
            self.events,
            self.network
        )

    def create_peer_manager(self) -> PeerManager:
        return PeerManager(
            self.settings,
            self.events,
            self.users,
            self.shares,
            self.transfers,
            self.network
        )

    def create_distributed_network(self) -> DistributedNetwork:
        return DistributedNetwork(
            self.settings,
            self.events,
            self.network
        )

    async def _on_connection_state_changed(self, event: ConnectionStateChangedEvent):
        if isinstance(event.connection, ServerConnection):
            if event.state == ConnectionState.CLOSED:
                if session := self.session:
                    session_event = SessionDestroyedEvent(session)
                    self.session = None
                    await self.events.emit(session_event)

    async def _on_server_reconnected(self, event: ServerReconnectedEvent):
        """Automatically logs the user back on in case the server was """
        if self.settings.network.server.reconnect.auto:
            await self.login()
