from __future__ import annotations
import asyncio
import logging
from typing import Optional, Union

from .commands import BaseCommand, LoginCommand
from .distributed import DistributedNetwork
from .events import EventBus, InternalEventBus
from .interest.manager import InterestManager
from .shares.cache import SharesCache, SharesNullCache
from .shares.manager import SharesManager
from .network.network import Network
from .peer import PeerManager
from .room.manager import RoomManager
from .server import ServerManager
from .search.manager import SearchManager
from .settings import Settings
from .transfer.cache import TransferCache, TransferNullCache
from .transfer.manager import TransferManager
from .user.manager import UserManager
from .user.model import User
from .utils import ticket_generator


CLIENT_VERSION = 157


logger = logging.getLogger(__name__)


class SoulSeekClient:
    """SoulSeek client class"""

    def __init__(
            self, settings: Settings,
            shares_cache: Optional[SharesCache] = None, transfer_cache: Optional[TransferCache] = None,
            event_bus: Optional[EventBus] = None):
        self.settings: Settings = settings

        self._ticket_generator = ticket_generator()
        self._stop_event: Optional[asyncio.Event] = None

        self.events: EventBus = event_bus or EventBus()
        self._internal_events: InternalEventBus = InternalEventBus()

        self.network: Network = self.create_network()
        self.distributed_network: DistributedNetwork = self.create_distributed_network()

        self.users: UserManager = self.create_user_manager()
        self.rooms: RoomManager = self.create_room_manager()
        self.interests: InterestManager = self.create_interest_manager()

        self.shares: SharesManager = self.create_shares_manager(
            shares_cache or SharesNullCache()
        )
        self.transfers: TransferManager = self.create_transfer_manager(
            transfer_cache or TransferNullCache()
        )
        self.peers: PeerManager = self.create_peer_manager()
        self.searches: SearchManager = self.create_search_manager()
        self.server_manager: ServerManager = self.create_server_manager()

    @property
    def event_loop(self):
        return asyncio.get_running_loop()

    async def start(self, scan_shares=True):
        """Performs a full start up of the client consisting of:
        * Connecting to the server
        * Opening listening ports
        * Performs a login with the user credentials defined in the settings
        * Reading transfer and shares caches
        * Optionally performs an initial scan of the shares

        :param scan_shares: start a shares scan as soon as the client starts
        """
        self.event_loop.set_exception_handler(self._exception_handler)

        # Allows creating client before actually calling asyncio.run(client.start())
        # see https://stackoverflow.com/questions/55918048/asyncio-semaphore-runtimeerror-task-got-future-attached-to-a-different-loop
        self._stop_event = asyncio.Event()

        await self.start_shares_manager(scan=scan_shares)
        await self.start_transfer_manager()
        await self.connect()
        await self.login()
        await self.transfers.manage_transfers()

    async def connect(self):
        """Initializes the network by connecting to the server and opening the
        configured listening ports
        """
        await self.network.initialize()

    async def login(self):
        """Performs a logon to the server with the `credentials` defined in the
        `settings`
        """
        await self.execute(LoginCommand(
            self.settings.credentials.username,
            self.settings.credentials.password
        ).response())

    async def start_shares_manager(self, scan=True):
        """Reads the shares cache and loads the shared directories from the
        settings

        :param scan: Boolean to indicate whether to start and initial scan or not
        """
        self.shares.read_cache()
        self.shares.load_from_settings()
        if scan:
            asyncio.create_task(self.shares.scan())

    async def start_transfer_manager(self):
        await self.transfers.read_cache()

    async def run_until_stopped(self):
        await self._stop_event.wait()

    async def stop(self):
        """Stops the client this method consists of:

        * Disconnecting the network and waiting for all connections to close
        * Cancel all pending tasks and waiting for them to complete
        * Write the transfer and shares caches
        """
        logger.info("signaling client to exit")
        self._stop_event.set()

        await self.network.disconnect()

        cancelled_tasks = (
            self.transfers.stop() +
            self.searches.stop() +
            self.distributed_network.stop()
        )
        await asyncio.gather(*cancelled_tasks, return_exceptions=True)

        self.shares.write_cache()
        self.transfers.write_cache()

    def _exception_handler(self, loop, context):
        message = f"unhandled exception on loop {loop!r} : context : {context!r}"
        logger.exception(message, exc_info=context.get('exception', None))

    async def __aenter__(self) -> SoulSeekClient:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def execute(self, command: BaseCommand):
        """Execute a `BaseCommand`, see the `commands.py` module for a list of
        possible commands.

        Waiting for a response is optional; the protocol does not always send
        error messages in case of failure. In these cases this method will
        timeout.

        Example waiting for response:

        ..code-block:: python
            from aioslsk.commands import GetUserStatusCommand

            status = await client.execute(GetUserStatusCommand('someuser').response())

        Example without response:

        ..code-block:: python
            from aioslsk.commands import JoinRoomCommand

            await client.execute(JoinRoomCommand('cool room'))

        :param command: Command class to execute
        :return: Optional response depending on how the command was configured
        """
        if command.response_future:
            self.network.register_response_future(command.response_future)

        try:
            await command.send(self)
        except Exception:
            if command.response_future:
                command.response_future.cancel()
            raise

        if command.response_future:
            _, response = await asyncio.wait_for(
                command.response_future, timeout=10)
            return command.process_response(self, response)

    # Peer requests
    async def get_user_info(self, user: Union[str, User]):
        username = user.name if isinstance(user, User) else user
        await self.peers.get_user_info(username)

    async def get_user_shares(self, user: Union[str, User]):
        username = user.name if isinstance(user, User) else user
        await self.peers.get_user_shares(username)

    async def get_user_directory(self, user: Union[str, User], directory: str):
        username = user.name if isinstance(user, User) else user
        await self.peers.get_user_directory(username, directory)

    # Creation methods

    def create_network(self) -> Network:
        return Network(
            self.settings,
            self._internal_events
        )

    def create_user_manager(self) -> UserManager:
        return UserManager(
            self.settings,
            self.events,
            self._internal_events,
            self.network
        )

    def create_room_manager(self) -> RoomManager:
        return RoomManager(
            self.settings,
            self.events,
            self._internal_events,
            self.users,
            self.network
        )

    def create_interest_manager(self) -> InterestManager:
        return InterestManager(
            self.settings,
            self.events,
            self._internal_events,
            self.users,
            self.network
        )

    def create_shares_manager(self, cache: SharesCache) -> SharesManager:
        return SharesManager(
            self.settings,
            self._internal_events,
            cache=cache
        )

    def create_transfer_manager(self, cache: TransferCache) -> TransferManager:
        return TransferManager(
            self.settings,
            self.events,
            self._internal_events,
            self.users,
            self.shares,
            self.network,
            cache=cache
        )

    def create_search_manager(self) -> SearchManager:
        return SearchManager(
            self.settings,
            self.events,
            self._internal_events,
            self.users,
            self.shares,
            self.transfers,
            self.network
        )

    def create_server_manager(self) -> ServerManager:
        return ServerManager(
            self.settings,
            self.events,
            self._internal_events,
            self.shares,
            self.network
        )

    def create_peer_manager(self) -> PeerManager:
        return PeerManager(
            self.settings,
            self.events,
            self._internal_events,
            self.users,
            self.shares,
            self.transfers,
            self.network
        )

    def create_distributed_network(self) -> DistributedNetwork:
        return DistributedNetwork(
            self.settings,
            self._internal_events,
            self.network
        )
